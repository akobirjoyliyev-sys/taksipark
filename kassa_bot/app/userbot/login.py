"""Admin paneldan userbot qo‘shish: telefon → Telegram kodi → (bo‘lsa) 2FA parol.

Login jarayoni bot jarayoni xotirasida turadi (TelegramClient obyektini Redis'ga yozib
bo‘lmaydi). 5 daqiqada yakunlanmagan urinishlar avtomatik tozalanadi.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.services.userbots import LoginResult

log = logging.getLogger(__name__)

PHONE_RE = re.compile(r"^\+?\d{9,15}$")
DEVICE = {"device_model": "Kassa Userbot", "system_version": "1.0", "app_version": "1.0"}


class LoginError(Exception):
    pass


def make_client(api_id: int, api_hash: str, session: str = "") -> TelegramClient:
    return TelegramClient(StringSession(session), api_id, api_hash, **DEVICE)


def normalize_phone(raw: str) -> str:
    phone = re.sub(r"[\s\-()]", "", raw)
    if not PHONE_RE.match(phone):
        raise LoginError("Telefon raqami noto‘g‘ri. Masalan: +998901234567")
    return phone if phone.startswith("+") else f"+{phone}"


@dataclass(slots=True)
class _Pending:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    started: float


class LoginManager:
    TTL = 300

    def __init__(self) -> None:
        self._pending: dict[int, _Pending] = {}

    async def _cleanup(self) -> None:
        now = time.monotonic()
        for admin_id, p in list(self._pending.items()):
            if now - p.started > self.TTL:
                await self.cancel(admin_id)

    def _get(self, admin_id: int) -> _Pending:
        pending = self._pending.get(admin_id)
        if pending is None or time.monotonic() - pending.started > self.TTL:
            raise LoginError("Login jarayoni eskirgan. Qaytadan boshlang.")
        return pending

    async def start(self, admin_id: int, raw_phone: str, *, api_id: int, api_hash: str) -> str:
        if not api_id or not api_hash:
            raise LoginError(
                "Userbot API ma’lumotlari yo‘q — admin panelda «🛰 Userbot → ✏️ API sozlamalari» "
                "orqali TG_API_ID va TG_API_HASH ni kiriting."
            )
        await self._cleanup()
        await self.cancel(admin_id)
        phone = normalize_phone(raw_phone)
        client = make_client(api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            await client.disconnect()
            raise LoginError("Bu raqam Telegram'da ro‘yxatdan o‘tmagan.") from exc
        except PhoneNumberBannedError as exc:
            await client.disconnect()
            raise LoginError("Bu raqam Telegram tomonidan bloklangan.") from exc
        except FloodWaitError as exc:
            await client.disconnect()
            raise LoginError(f"Telegram cheklovi: {exc.seconds} soniyadan keyin urining.") from exc
        except Exception:
            await client.disconnect()
            raise
        self._pending[admin_id] = _Pending(client, phone, sent.phone_code_hash, time.monotonic())
        return phone

    async def submit_code(self, admin_id: int, raw_code: str) -> LoginResult | None:
        """Kod to‘g‘ri bo‘lsa natija; 2FA parol kerak bo‘lsa None."""
        pending = self._get(admin_id)
        code = re.sub(r"\D", "", raw_code)
        if not 4 <= len(code) <= 8:
            raise LoginError("Kod 5 ta raqamdan iborat. Masalan: 1 2 3 4 5")
        try:
            await pending.client.sign_in(
                phone=pending.phone, code=code, phone_code_hash=pending.phone_code_hash
            )
        except SessionPasswordNeededError:
            return None
        except PhoneCodeInvalidError as exc:
            raise LoginError("Kod noto‘g‘ri. Qaytadan yuboring.") from exc
        except PhoneCodeExpiredError as exc:
            await self.cancel(admin_id)
            raise LoginError(
                "Kod eskirgan yoki bloklangan. Qaytadan boshlang va kodni raqamlar orasiga "
                "bo‘sh joy qo‘yib yuboring."
            ) from exc
        return await self._finish(admin_id)

    async def submit_password(self, admin_id: int, password: str) -> LoginResult:
        pending = self._get(admin_id)
        try:
            await pending.client.sign_in(password=password)
        except PasswordHashInvalidError as exc:
            raise LoginError("2FA parol noto‘g‘ri. Qaytadan yuboring.") from exc
        return await self._finish(admin_id)

    async def _finish(self, admin_id: int) -> LoginResult:
        pending = self._pending.pop(admin_id)
        try:
            me = await pending.client.get_me()
            session = pending.client.session.save()
        finally:
            await pending.client.disconnect()
        log.info("Userbot login muvaffaqiyatli: tg_id=%s", getattr(me, "id", "?"))
        return LoginResult(
            phone=pending.phone,
            session=session,
            tg_user_id=int(me.id),
            username=getattr(me, "username", None),
            first_name=getattr(me, "first_name", None),
        )

    async def cancel(self, admin_id: int) -> None:
        pending = self._pending.pop(admin_id, None)
        if pending is not None:
            try:
                await pending.client.disconnect()
            except Exception:
                log.debug("Login clientini uzishda xato", exc_info=True)


_manager: LoginManager | None = None


def get_login_manager() -> LoginManager:
    global _manager
    if _manager is None:
        _manager = LoginManager()
    return _manager
