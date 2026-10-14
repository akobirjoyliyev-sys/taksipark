from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LedgerAccount, LedgerDirection, LedgerReason
from app.core.errors import DomainError, NotFoundError
from app.core.money import ZERO, q
from app.core.utils import utcnow
from app.models import User, Wallet
from app.repositories.users import UserRepository
from app.repositories.wallets import WalletRepository
from app.services.audit import Actor, AuditService
from app.services.ledger import LedgerService


class TelegramUserLike(Protocol):
    id: int
    username: str | None
    first_name: str
    last_name: str | None


@dataclass(frozen=True, slots=True)
class BalanceAdjustment:
    user: User
    wallet: Wallet
    amount: Decimal
    direction: LedgerDirection


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserRepository(session)
        self.wallets = WalletRepository(session)
        self.audit = AuditService(session)

    async def get_or_create(self, tg: TelegramUserLike) -> tuple[User, bool]:
        user = await self.repo.get_by_telegram_id(tg.id)
        if user is not None:
            changed = False
            for attr, value in (
                ("username", tg.username),
                ("first_name", (tg.first_name or "")[:128] or None),
                ("last_name", (tg.last_name or "")[:128] or None),
            ):
                if getattr(user, attr) != value:
                    setattr(user, attr, value)
                    changed = True
            if utcnow() - user.last_seen_at > timedelta(minutes=10):
                user.last_seen_at = utcnow()
                changed = True
            if changed:
                await self.session.commit()
            return user, False

        new_id = await self.repo.insert_if_absent(
            telegram_id=tg.id,
            username=tg.username,
            first_name=(tg.first_name or "")[:128] or None,
            last_name=(tg.last_name or "")[:128] or None,
        )
        if new_id is None:  # parallel so‘rov allaqachon yaratgan
            await self.session.rollback()
            user = await self.repo.get_by_telegram_id(tg.id)
            if user is None:  # pragma: no cover
                raise RuntimeError("Foydalanuvchini yaratib bo‘lmadi")
            return user, False
        self.session.add(Wallet(user_id=new_id))
        await self.session.commit()
        user = await self.repo.get(new_id)
        if user is None:  # pragma: no cover
            raise RuntimeError("Foydalanuvchini yaratib bo‘lmadi")
        return user, True

    async def attach_referrer(self, user: User, raw_arg: str) -> User | None:
        """`ref_<telegram_id>` — faqat yangi foydalanuvchi uchun; o‘zini taklif qilib bo‘lmaydi."""
        if user.referrer_id is not None or not raw_arg.startswith("ref_"):
            return None
        try:
            ref_tg_id = int(raw_arg[4:])
        except ValueError:
            return None
        if ref_tg_id == user.telegram_id:
            return None
        referrer = await self.repo.get_by_telegram_id(ref_tg_id)
        if referrer is None or referrer.is_banned or referrer.id == user.id:
            return None
        user.referrer_id = referrer.id
        await self.session.commit()
        return referrer

    async def save_contact(self, user: User, phone: str) -> None:
        digits = "".join(ch for ch in phone if ch.isdigit())[:15]
        user.phone = f"+{digits}" if digits else None
        user.contact_verified = bool(digits)
        user.onboarding_done = True
        await self.session.commit()

    async def finish_onboarding(self, user: User) -> None:
        if not user.onboarding_done:
            user.onboarding_done = True
            await self.session.commit()

    async def get_wallet(self, user_id: int) -> Wallet:
        wallet = await self.wallets.get_by_user(user_id)
        if wallet is None:
            wallet = Wallet(user_id=user_id)
            self.session.add(wallet)
            await self.session.commit()
        return wallet

    async def set_ban(self, user_id: int, banned: bool, reason: str | None, actor: Actor) -> User:
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError("Foydalanuvchi topilmadi.")
        before = {"banned": user.is_banned, "reason": user.ban_reason}
        user.is_banned = banned
        user.ban_reason = reason if banned else None
        await self.audit.log(
            actor,
            "user.ban" if banned else "user.unban",
            "user",
            user.telegram_id,
            before=before,
            after={"banned": banned, "reason": user.ban_reason},
            comment=reason,
        )
        await self.session.commit()
        return user

    async def adjust_balance(
        self,
        user_id: int,
        amount: Decimal,
        direction: LedgerDirection,
        reason: str,
        actor: Actor,
    ) -> BalanceAdjustment:
        """Admin tomonidan qo‘lda kredit/debet — faqat sabab va audit yozuvi bilan."""
        amount = q(amount)
        if amount <= ZERO:
            raise DomainError("Summa musbat bo‘lishi kerak.")
        if not reason or len(reason.strip()) < 3:
            raise DomainError("Sabab majburiy.")
        user = await self.repo.get(user_id)
        if user is None:
            raise NotFoundError("Foydalanuvchi topilmadi.")
        wallet = await self.wallets.get_for_update(user_id)
        before = {"available": wallet.available}
        ledger_reason = (
            LedgerReason.MANUAL_CREDIT
            if direction == LedgerDirection.CREDIT
            else LedgerReason.MANUAL_DEBIT
        )
        op_id = uuid.uuid4().hex
        await LedgerService(self.session).post(
            wallet=wallet,
            account=LedgerAccount.MAIN,
            direction=direction,
            amount=amount,
            reason=ledger_reason,
            idempotency_key=f"manual:{op_id}",
            reference_type="admin_adjustment",
            reference_id=op_id,
            actor_telegram_id=actor.telegram_id,
            comment=reason,
        )
        await self.audit.log(
            actor,
            f"wallet.{ledger_reason.value}",
            "user",
            user.telegram_id,
            before=before,
            after={"available": wallet.available, "amount": amount},
            comment=reason,
        )
        await self.session.commit()
        return BalanceAdjustment(user=user, wallet=wallet, amount=amount, direction=direction)
