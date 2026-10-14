"""Bukmekerlar (kantoralar): har biri alohida kassa — admin paneldan boshqariladi.

Uchta gateway bor:
* `mobcash` — admin.mob-cash.com (login + parol bilan login qilinadi);
* `cashdesk` — 1xBet Cashdesk Bot API (kassir paroli + hash bilan imzolanadi, login yo‘q):
  balans, o‘yinchi, depozit va yechish (kod bo‘yicha oldindan ko‘rish yo‘q);
* `agent` — TeamCash / MELLO CASH agent API (cashdbcore): agent login/paroli bilan token
  olinadi, keyin kassa tanlanadi. Depozit va yechish endpointlari ochiq.

* Bukmeker qo‘shilmagan bo‘lsa, admin paneldagi «🏦 Mob-Cash» sozlamalaridagi bitta kassa
  (eski rejim) ishlatiladi — `bookmaker_id=None`.
* Tanlangan bukmeker kassasi ishlamasa, boshqa kassaga jimgina o‘tib ketilmaydi: pul noto‘g‘ri
  kassaga tushmasligi uchun xato qaytariladi.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Config
from app.core.errors import DomainError, NotFoundError
from app.mobcash import AgentClient, CashdeskClient, MobCashClient, MobCashError
from app.core.enums import AutoBatchStatus
from app.models import AutoDepositBatch, Bookmaker, MobcashWithdrawal, P2PDeposit
from app.services.audit import Actor, AuditService
from app.services.settings import SettingsService
from app.userbot.crypto import SessionCipher, SessionCipherError

log = logging.getLogger(__name__)

# Jarayon ichida klientlar qayta ishlatiladi (har so‘rovda yangi HTTP ulanish ochilmasin).
_CLIENTS: dict[int, tuple[str, MobCashClient | CashdeskClient | AgentClient]] = {}

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")

GATEWAY_MOBCASH = "mobcash"
GATEWAY_CASHDESK = "cashdesk"
GATEWAY_AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Credentials:
    code: int
    login: str
    password: str
    gateway: str
    hash_key: str = ""


def _fingerprint(code: int, login: str, password: str, hash_key: str = "") -> str:
    return hashlib.sha256(f"{code}:{login}:{password}:{hash_key}".encode()).hexdigest()


def parse_credentials(raw: str) -> Credentials:
    """`kassa_kodi | login | parol` (mobcash), `kods | kassir paroli | hash` (cashdesk)
    yoki `agent: login | parol | kassa_kodi` (TeamCash/MELLO agent API).

    Cashdesk shakli 3-maydon 64 belgili hex hash bilan aniqlanadi (G&S/1xBet kassalari).
    `:` ham ajratgich bo‘la oladi (agent prefiksida — faqat `agent:` boshlanishi sifatida).
    """
    text = raw.strip().replace("\n", "|")
    if text.lower().startswith("agent:"):
        rest = text[len("agent:"):].strip()
        sep = "|" if "|" in rest else ":"
        parts = [p.strip() for p in rest.split(sep, 2)]
        if len(parts) != 3 or not all(parts):
            raise DomainError(
                "Agent kassasi formati: <code>agent: login | parol | kassa_kodi</code>"
            )
        login, password, code_raw = parts
        if not code_raw.isdigit() or len(code_raw) > 15:
            raise DomainError("Kassa kodi (oxirgi maydon) faqat raqamlardan iborat bo‘lishi kerak.")
        return Credentials(
            code=int(code_raw), login=login[:128], password=password, gateway=GATEWAY_AGENT
        )
    sep = "|" if "|" in text else ":"
    parts = [p.strip() for p in text.split(sep, 2)]
    if len(parts) != 3 or not all(parts):
        raise DomainError(
            "Format noto‘g‘ri. Kerak: <code>kassa_kodi | login | parol</code> yoki "
            "<code>kassa_kodi | kassir paroli | hash</code>"
        )
    code_raw, second, third = parts
    if not code_raw.isdigit() or len(code_raw) > 15:
        raise DomainError("Kassa kodi faqat raqamlardan iborat bo‘lishi kerak.")
    code = int(code_raw)
    if HASH_RE.match(third):
        return Credentials(code=code, login="", password=second, gateway=GATEWAY_CASHDESK, hash_key=third)
    return Credentials(code=code, login=second[:128], password=third, gateway=GATEWAY_MOBCASH)


class BookmakerService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        config: Config,
        settings: SettingsService,
        legacy: MobCashClient | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.config = config
        self.settings = settings
        self.legacy = legacy

    # ------------------------------------------------------------------ ro‘yxat
    async def list_all(self) -> list[Bookmaker]:
        stmt = select(Bookmaker).order_by(Bookmaker.sort_order, Bookmaker.id)
        return list(await self.session.scalars(stmt))

    async def list_active(self) -> list[Bookmaker]:
        stmt = (
            select(Bookmaker)
            .where(Bookmaker.is_active.is_(True))
            .order_by(Bookmaker.sort_order, Bookmaker.id)
        )
        return list(await self.session.scalars(stmt))

    async def get(self, bookmaker_id: int) -> Bookmaker:
        bm = await self.session.get(Bookmaker, bookmaker_id)
        if bm is None:
            raise NotFoundError("Kantora topilmadi.")
        return bm

    async def get_active(self, bookmaker_id: int) -> Bookmaker:
        bm = await self.get(bookmaker_id)
        if not bm.is_active:
            raise DomainError("Bu kantora vaqtincha o‘chirilgan. Boshqasini tanlang.")
        return bm

    async def name_of(self, bookmaker_id: int | None) -> str | None:
        """Kantora nomi; eski yagona kassa (`None`) uchun — None."""
        if bookmaker_id is None:
            return None
        bm = await self.session.get(Bookmaker, bookmaker_id)
        return bm.name if bm else f"#{bookmaker_id}"

    async def legacy_available(self) -> bool:
        """Bukmeker qo‘shilmagan, lekin eski yagona kassa sozlangan bo‘lsa — u ishlatiladi."""
        has_any = await self.session.scalar(select(func.count(Bookmaker.id)))
        return not has_any and self.legacy is not None and self.legacy.configured

    # ------------------------------------------------------------------ admin amallari
    async def _cipher(self, actor: Actor | None = None) -> SessionCipher:
        key = (await self.settings.snapshot()).userbot_session_key
        if actor is not None:
            key = await self.settings.ensure_userbot_key(actor)
        try:
            return SessionCipher(key)
        except SessionCipherError as exc:
            raise DomainError(str(exc)) from exc

    def _make_client(self, code: int, login: str, password: str) -> MobCashClient:
        return MobCashClient(
            redis=self.redis,
            cashbox_code=code,
            login=login,
            password=password,
            auth_url=self.config.mobcash_auth_url,
            api_url=self.config.mobcash_api_url,
            timeout=float(self.config.mobcash_timeout_seconds),
        )

    def _make_cashdesk(self, creds: Credentials) -> CashdeskClient:
        return CashdeskClient(
            cashdesk_id=creds.code,
            cashier_pass=creds.password,
            hash_key=creds.hash_key,
            api_url=self.config.cashdesk_api_url,
            timeout=float(self.config.mobcash_timeout_seconds),
        )

    def _make_agent(self, creds: Credentials) -> AgentClient:
        return AgentClient(
            login=creds.login,
            password=creds.password,
            cashdesk_id=creds.code,
            api_base=self.config.agent_api_base,
            timeout=float(self.config.mobcash_timeout_seconds),
        )

    def _make_for_gateway(
        self, creds: Credentials
    ) -> MobCashClient | CashdeskClient | AgentClient:
        if creds.gateway == GATEWAY_CASHDESK:
            return self._make_cashdesk(creds)
        if creds.gateway == GATEWAY_AGENT:
            return self._make_agent(creds)
        return self._make_client(creds.code, creds.login, creds.password)

    async def create(self, name: str, raw_credentials: str, actor: Actor) -> Bookmaker:
        """Kassaga ulanishni tekshiradi va bukmekerni saqlaydi (gateway turiga qarab)."""
        name = name.strip()[:64]
        if not name:
            raise DomainError("Kantora nomi bo‘sh bo‘lmasin.")
        creds = parse_credentials(raw_credentials)
        exists = await self.session.scalar(
            select(Bookmaker).where(
                Bookmaker.cashbox_code == creds.code, Bookmaker.login == creds.login
            )
        )
        if exists is not None:
            raise DomainError(f"Bu kassa allaqachon qo‘shilgan: {exists.name}")
        cipher = await self._cipher(actor)
        client = self._make_for_gateway(creds)
        try:
            info = await client.check_connection()
        except MobCashError as exc:
            raise DomainError(f"Kassaga ulanib bo‘lmadi: {exc.message}") from exc
        finally:
            await client.close()
        last = await self.session.scalar(select(func.max(Bookmaker.sort_order)))
        bm = Bookmaker(
            name=name,
            cashbox_code=creds.code,
            login=creds.login,
            password_encrypted=cipher.encrypt(creds.password),
            hash_encrypted=cipher.encrypt(creds.hash_key) if creds.hash_key else None,
            gateway=creds.gateway,
            currency=info.currency_id[:16],
            is_active=True,
            sort_order=(last or 0) + 1,
        )
        self.session.add(bm)
        await self.session.flush()
        await AuditService(self.session).log(
            actor, "bookmaker.add", "bookmaker", bm.id, after={"name": name, "code": creds.code, "gateway": creds.gateway}
        )
        await self.session.commit()
        return bm

    async def update_credentials(
        self, bookmaker_id: int, raw_credentials: str, actor: Actor
    ) -> Bookmaker:
        bm = await self.get(bookmaker_id)
        creds = parse_credentials(raw_credentials)
        cipher = await self._cipher(actor)
        client = self._make_for_gateway(creds)
        try:
            info = await client.check_connection()
        except MobCashError as exc:
            raise DomainError(f"Kassaga ulanib bo‘lmadi: {exc.message}") from exc
        finally:
            await client.close()
        before = {"code": bm.cashbox_code, "login": bm.login}
        bm.cashbox_code, bm.login = creds.code, creds.login
        bm.password_encrypted = cipher.encrypt(creds.password)
        bm.hash_encrypted = cipher.encrypt(creds.hash_key) if creds.hash_key else None
        bm.gateway = creds.gateway
        bm.currency = info.currency_id[:16]
        await AuditService(self.session).log(
            actor,
            "bookmaker.credentials",
            "bookmaker",
            bm.id,
            before=before,
            after={"code": creds.code, "login": creds.login, "gateway": creds.gateway},
        )
        await self.session.commit()
        _CLIENTS.pop(bm.id, None)
        return bm

    async def rename(self, bookmaker_id: int, name: str, actor: Actor) -> Bookmaker:
        bm = await self.get(bookmaker_id)
        name = name.strip()[:64]
        if not name:
            raise DomainError("Kantora nomi bo‘sh bo‘lmasin.")
        before = bm.name
        bm.name = name
        await AuditService(self.session).log(
            actor, "bookmaker.rename", "bookmaker", bm.id, before={"name": before}
        )
        await self.session.commit()
        return bm

    async def toggle(self, bookmaker_id: int, actor: Actor) -> Bookmaker:
        bm = await self.get(bookmaker_id)
        bm.is_active = not bm.is_active
        await AuditService(self.session).log(
            actor, "bookmaker.toggle", "bookmaker", bm.id, after={"is_active": bm.is_active}
        )
        await self.session.commit()
        return bm

    async def move(self, bookmaker_id: int, delta: int, actor: Actor) -> None:
        """Tartibni o‘zgartiradi: delta=-1 — yuqoriga, +1 — pastga."""
        items = await self.list_all()
        idx = next((i for i, b in enumerate(items) if b.id == bookmaker_id), None)
        if idx is None:
            raise NotFoundError("Kantora topilmadi.")
        j = idx + delta
        if not 0 <= j < len(items):
            return
        items[idx], items[j] = items[j], items[idx]
        for order, bm in enumerate(items, 1):
            bm.sort_order = order
        await AuditService(self.session).log(actor, "bookmaker.move", "bookmaker", bookmaker_id)
        await self.session.commit()

    async def delete(self, bookmaker_id: int, actor: Actor) -> None:
        bm = await self.get(bookmaker_id)
        used = await self.session.scalar(
            select(func.count(P2PDeposit.id)).where(P2PDeposit.bookmaker_id == bm.id)
        ) or await self.session.scalar(
            select(func.count(MobcashWithdrawal.id)).where(MobcashWithdrawal.bookmaker_id == bm.id)
        ) or await self.session.scalar(
            select(func.count(AutoDepositBatch.id)).where(
                AutoDepositBatch.bookmaker_id == bm.id,
                AutoDepositBatch.status != AutoBatchStatus.DRAFT,
            )
        )
        if used:
            raise DomainError(
                "Bu kantorada to‘lovlar tarixi bor — o‘chirib bo‘lmaydi. "
                "Uni faqat 🔴 o‘chirib qo‘yish mumkin."
            )
        await AuditService(self.session).log(
            actor, "bookmaker.delete", "bookmaker", bm.id, before={"name": bm.name}
        )
        await self.session.delete(bm)
        await self.session.commit()
        _CLIENTS.pop(bookmaker_id, None)

    # ------------------------------------------------------------------ klient
    async def _cached_client(
        self, bookmaker_id: int, fp: str, make: Callable[[], Any]
    ) -> MobCashClient | CashdeskClient | AgentClient:
        cached = _CLIENTS.get(bookmaker_id)
        if cached is not None:
            if cached[0] == fp:
                return cached[1]
            await cached[1].close()
        client = make()
        _CLIENTS[bookmaker_id] = (fp, client)
        return client

    async def client(self, bookmaker_id: int | None) -> MobCashClient | CashdeskClient | AgentClient:
        """Kassa klienti (har qanday gateway): balans va o‘yinchini tekshirish uchun."""
        if bookmaker_id is None:
            if self.legacy is not None and self.legacy.configured:
                return self.legacy
            raise DomainError(texts.MC_UNAVAILABLE)
        bm = await self.get(bookmaker_id)
        cipher = await self._cipher()
        try:
            password = cipher.decrypt(bm.password_encrypted)
        except SessionCipherError as exc:
            raise DomainError(f"«{bm.name}» kassa paroli ochilmadi: {exc}") from exc
        if bm.gateway == GATEWAY_CASHDESK:
            if not bm.hash_encrypted:
                raise DomainError(
                    f"«{bm.name}» kassasida hash saqlanmagan — ma’lumotlarni qayta kiriting."
                )
            try:
                hash_key = cipher.decrypt(bm.hash_encrypted)
            except SessionCipherError as exc:
                raise DomainError(f"«{bm.name}» kassa hashi ochilmadi: {exc}") from exc
            return await self._cached_client(
                bm.id,
                _fingerprint(bm.cashbox_code, "", password, hash_key),
                lambda: CashdeskClient(
                    cashdesk_id=bm.cashbox_code,
                    cashier_pass=password,
                    hash_key=hash_key,
                    api_url=self.config.cashdesk_api_url,
                    timeout=float(self.config.mobcash_timeout_seconds),
                ),
            )
        if bm.gateway == GATEWAY_AGENT:
            return await self._cached_client(
                bm.id,
                _fingerprint(bm.cashbox_code, bm.login, password),
                lambda: AgentClient(
                    login=bm.login or "",
                    password=password,
                    cashdesk_id=bm.cashbox_code,
                    api_base=self.config.agent_api_base,
                    timeout=float(self.config.mobcash_timeout_seconds),
                ),
            )
        return await self._cached_client(
            bm.id,
            _fingerprint(bm.cashbox_code, bm.login, password),
            lambda: self._make_client(bm.cashbox_code, bm.login, password),
        )

    async def money_client(self, bookmaker_id: int | None) -> MobCashClient | AgentClient | CashdeskClient:
        """Pul o‘tkazmalari uchun klient (depozit/yechish qo‘llab-quvvatlaydigan barcha gateway'lar)."""
        return await self.client(bookmaker_id)
