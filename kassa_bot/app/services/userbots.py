"""Userbot akkauntlari (bank xabarlarini o‘qiydigan Telegram akkauntlar) — DB qatlami."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import UserbotStatus
from app.core.errors import DomainError, NotFoundError
from app.core.utils import utcnow
from app.models import UserbotAccount
from app.services.audit import Actor, AuditService
from app.services.settings import SettingsService
from app.userbot.crypto import SessionCipher, SessionCipherError


@dataclass(frozen=True, slots=True)
class LoginResult:
    phone: str
    session: str
    tg_user_id: int
    username: str | None
    first_name: str | None


class UserbotService:
    def __init__(self, session: AsyncSession, settings: SettingsService) -> None:
        self.session = session
        self.settings = settings

    async def cipher(self) -> SessionCipher:
        rt = await self.settings.snapshot()
        try:
            return SessionCipher(rt.userbot_session_key)
        except SessionCipherError as exc:
            raise DomainError(str(exc)) from exc

    async def all_accounts(self) -> list[UserbotAccount]:
        return list(await self.session.scalars(select(UserbotAccount).order_by(UserbotAccount.id)))

    async def active_accounts(self) -> list[UserbotAccount]:
        stmt = (
            select(UserbotAccount)
            .where(UserbotAccount.status == UserbotStatus.ACTIVE)
            .order_by(UserbotAccount.id)
        )
        return list(await self.session.scalars(stmt))

    async def get(self, account_id: int) -> UserbotAccount:
        account = await self.session.get(UserbotAccount, account_id)
        if account is None:
            raise NotFoundError("Userbot topilmadi.")
        return account

    async def save_login(self, result: LoginResult, actor: Actor) -> UserbotAccount:
        cipher = await self.cipher()
        encrypted = cipher.encrypt(result.session)
        account = await self.session.scalar(
            select(UserbotAccount).where(UserbotAccount.phone == result.phone)
        )
        action = "userbot.relogin"
        if account is None:
            account = UserbotAccount(phone=result.phone, session_encrypted=encrypted)
            self.session.add(account)
            action = "userbot.add"
        account.session_encrypted = encrypted
        account.tg_user_id = result.tg_user_id
        account.username = result.username
        account.first_name = result.first_name
        account.status = UserbotStatus.ACTIVE
        account.last_error = None
        account.added_by = actor.telegram_id
        await self.session.flush()
        await AuditService(self.session).log(
            actor, action, "userbot", account.id, after={"tg_user_id": result.tg_user_id}
        )
        await self.session.commit()
        return account

    async def toggle(self, account_id: int, actor: Actor) -> UserbotAccount:
        account = await self.get(account_id)
        account.status = (
            UserbotStatus.DISABLED
            if account.status == UserbotStatus.ACTIVE
            else UserbotStatus.ACTIVE
        )
        account.last_error = None
        await AuditService(self.session).log(
            actor, "userbot.toggle", "userbot", account.id, after={"status": account.status}
        )
        await self.session.commit()
        return account

    async def delete(self, account_id: int, actor: Actor) -> None:
        account = await self.get(account_id)
        await AuditService(self.session).log(
            actor, "userbot.delete", "userbot", account.id, before={"phone": account.phone}
        )
        await self.session.delete(account)
        await self.session.commit()

    async def mark_error(self, account_id: int, error: str) -> None:
        account = await self.session.get(UserbotAccount, account_id)
        if account is None:
            return
        account.status = UserbotStatus.ERROR
        account.last_error = error[:500]
        await self.session.commit()

    async def touch(self, account_id: int) -> None:
        account = await self.session.get(UserbotAccount, account_id)
        if account is None:
            return
        account.last_seen_at = utcnow()
        await self.session.commit()
