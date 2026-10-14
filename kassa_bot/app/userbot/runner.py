"""Userbot jarayoni: `python -m app.userbot`.

Har bir faol akkaunt uchun Telethon client ishga tushadi va bank botlarining (CardXabar,
HUMO) xabarlarini o‘qiydi:
* real vaqt — `NewMessage` hodisasi;
* zaxira — har 30 soniyada oxirgi xabarlarni so‘rash (uzilish/restartdan keyin ham
  to‘lov o‘tkazib yuborilmasin). Takroriy ishlov DB UNIQUE bilan bloklanadi.

Xavfsizlik: faqat manba bot o‘zi yuborgan, forward qilinmagan, kiruvchi xabarlar qabul
qilinadi — boshqa odam soxta «➕ 50 000 UZS» yozib yuborsa ham hisobga olinmaydi.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from telethon import TelegramClient, events
from telethon.errors import AuthKeyUnregisteredError, UserDeactivatedBanError

from app.bootstrap import AppContext
from app.core.permissions import Perm
from app.core.utils import utcnow
from app.models import UserbotAccount
from app.p2p.parser import parse_bank_message
from app.services.settings import RuntimeSettings
from app.userbot.crypto import SessionCipher, SessionCipherError
from app.userbot.login import make_client

log = logging.getLogger("app.userbot")

SYNC_INTERVAL = 30
BACKLOG = timedelta(hours=3)
ALERT_WINDOW = timedelta(minutes=10)


@dataclass(slots=True)
class _Running:
    account_id: int
    tg_user_id: int
    client: TelegramClient
    session_hash: str
    source_names: list[str] = field(default_factory=list)
    sources: dict[int, str] = field(default_factory=dict)  # chat_id -> username
    last_ids: dict[int, int] = field(default_factory=dict)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class UserbotRunner:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.clients: dict[int, _Running] = {}
        self.started_at = utcnow()

    # ------------------------------------------------------------------ hayot sikli
    async def run(self, stop: asyncio.Event) -> None:
        warned = False
        try:
            while not stop.is_set():
                try:
                    rt = await self.sync()
                except Exception:
                    log.exception("Userbot sikl xatosi: sync")
                else:
                    if rt.userbot_configured:
                        if warned:
                            log.info("Userbot sozlamalari kiritildi — ish davom etadi")
                            warned = False
                        try:
                            await self.poll()
                        except Exception:
                            log.exception("Userbot sikl xatosi: poll")
                    elif not warned:
                        log.warning(
                            "Userbot sozlanmagan — admin panelda «🛰 Userbot» bo‘limidan "
                            "TG_API_ID, TG_API_HASH va shifrlash kalitini sozlang. Kutish rejimi."
                        )
                        warned = True
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=SYNC_INTERVAL)
        finally:
            for account_id in list(self.clients):
                await self._stop(account_id)

    async def sync(self) -> RuntimeSettings:
        """DB dagi faol akkauntlar bilan ishlayotgan clientlarni moslashtiradi."""
        async with self.ctx.sessionmaker() as session:
            svc = self.ctx.services(session)
            rt = await svc.settings.snapshot()
            accounts = await svc.userbots.active_accounts() if rt.userbot_configured else []
        wanted = {a.id: a for a in accounts}
        for account_id, running in list(self.clients.items()):
            account = wanted.get(account_id)
            if account is None or running.session_hash != _hash(account.session_encrypted):
                await self._stop(account_id)
        for account in accounts:
            if account.id not in self.clients:
                await self._start(account, rt)
        for running in self.clients.values():
            if running.source_names != rt.p2p_sources:
                await self._resolve_sources(running, rt.p2p_sources)
        return rt

    async def _start(self, account: UserbotAccount, rt: RuntimeSettings) -> None:
        try:
            cipher = SessionCipher(rt.userbot_session_key)
            session_str = cipher.decrypt(account.session_encrypted)
        except SessionCipherError as exc:
            await self._mark_error(account.id, str(exc))
            return
        client = make_client(rt.tg_api_id, rt.tg_api_hash, session_str)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                await self._mark_error(
                    account.id, "Sessiya bekor qilingan — userbotni qaytadan qo‘shing"
                )
                return
            me = await client.get_me()
        except Exception as exc:
            with contextlib.suppress(Exception):
                await client.disconnect()
            await self._mark_error(account.id, f"Ulanib bo‘lmadi: {exc}")
            return
        running = _Running(account.id, int(me.id), client, _hash(account.session_encrypted))

        async def on_message(event: events.NewMessage.Event) -> None:
            if event.chat_id in running.sources:
                await self._process(running, event.chat_id, event.message)

        client.add_event_handler(on_message, events.NewMessage(incoming=True))
        self.clients[account.id] = running
        log.info("Userbot #%s ishga tushdi", account.id)

    async def _stop(self, account_id: int) -> None:
        running = self.clients.pop(account_id, None)
        if running is None:
            return
        with contextlib.suppress(Exception):
            await running.client.disconnect()
        log.info("Userbot #%s to‘xtatildi", account_id)

    async def _mark_error(self, account_id: int, error: str) -> None:
        log.warning("Userbot #%s xato: %s", account_id, error)
        async with self.ctx.sessionmaker() as session:
            svc = self.ctx.services(session)
            await svc.userbots.mark_error(account_id, error)
            admins = await svc.admins.telegram_ids_with(Perm.USERBOT_MANAGE)
            await svc.notifier.send_many(
                admins, f"🔴 <b>Userbot #{account_id} to‘xtadi</b>\n\n{error}"
            )

    async def _resolve_sources(self, running: _Running, names: list[str]) -> None:
        resolved: dict[int, str] = {}
        for name in names:
            try:
                entity = await running.client.get_entity(name)
            except Exception as exc:
                log.warning("Userbot #%s: @%s topilmadi: %s", running.account_id, name, exc)
                continue
            if not getattr(entity, "bot", False):
                log.warning("@%s bot emas — manba sifatida qabul qilinmadi", name)
                continue
            resolved[int(entity.id)] = name
        running.sources = resolved
        running.source_names = list(names)
        if not resolved:
            log.warning("Userbot #%s: birorta manba bot topilmadi", running.account_id)

    # ------------------------------------------------------------------ xabarlar
    async def poll(self) -> None:
        for running in list(self.clients.values()):
            try:
                for chat_id in list(running.sources):
                    messages = await running.client.get_messages(
                        chat_id, limit=30, min_id=running.last_ids.get(chat_id, 0)
                    )
                    for message in reversed(list(messages or [])):
                        await self._process(running, chat_id, message)
            except (AuthKeyUnregisteredError, UserDeactivatedBanError) as exc:
                await self._stop(running.account_id)
                await self._mark_error(running.account_id, f"Sessiya yaroqsiz: {exc}")
                continue
            except Exception:
                log.exception("Userbot #%s: xabarlarni olishda xato", running.account_id)
                continue
            async with self.ctx.sessionmaker() as session:
                await self.ctx.services(session).userbots.touch(running.account_id)

    async def _process(self, running: _Running, chat_id: int, message: Any) -> None:
        if message is None or getattr(message, "out", False):
            return
        if getattr(message, "fwd_from", None) is not None:
            return  # forward qilingan xabar — soxta bo‘lishi mumkin
        sender_id = getattr(message, "sender_id", None)
        if sender_id is not None and sender_id != chat_id:
            return  # bot chatida faqat botning o‘zi yozgan xabar
        running.last_ids[chat_id] = max(running.last_ids.get(chat_id, 0), int(message.id))
        date = message.date
        if date is not None and date < self.started_at - BACKLOG:
            return
        text = message.message or ""
        parsed = parse_bank_message(text)
        if parsed is None:
            return
        async with self.ctx.sessionmaker() as session:
            svc = self.ctx.services(session)
            match = await svc.p2p.handle_bank_message(
                account_id=running.account_id,
                owner_tg_id=running.tg_user_id,
                source_chat_id=chat_id,
                source_name=running.sources.get(chat_id, ""),
                message_id=int(message.id),
                text=text,
                message_date=date,
                parsed=parsed,
            )
            if match is None:
                return  # allaqachon qayta ishlangan
            admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
            if match.deposit is None:
                log.info("Mos kelmagan kirim tx=%s summa=%s", match.tx.id, match.tx.amount)
                if date is None or date >= self.started_at - ALERT_WINDOW:
                    await svc.notifier.bank_unmatched(match.tx, admins)
                return
            log.info("Kirim tx=%s → depozit #%s", match.tx.id, match.deposit.id)
            outcome = await svc.p2p.credit(match.deposit.id)
            if outcome is not None:
                outcome.late = match.late
                bm = await svc.bookmakers.name_of(outcome.deposit.bookmaker_id)
                await svc.notifier.p2p_deposit(outcome, admins, bm)


async def main() -> None:
    import signal

    from app.bootstrap import close_context, create_context

    ctx = await create_context(sync_admins=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    log.info("Userbot jarayoni ishga tushdi")
    try:
        await UserbotRunner(ctx).run(stop)
    finally:
        await close_context(ctx)
