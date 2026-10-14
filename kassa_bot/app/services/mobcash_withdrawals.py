"""Mob-Cash'dan pul chiqarish: kod → summa → karta yoki hamyon → Mob-Cash `withdrawal`.

Yechish kodi faqat FSM (Redis, 24 soat TTL) va so‘rov paytida ishlatiladi — bazada
maskalangan ko‘rinishi qoladi. Mob-Cash javobi noaniq bo‘lsa (timeout) ariza `review`ga
o‘tadi: admin Mob-Cash panelida tekshirmaguncha foydalanuvchiga pul o‘tkazilmaydi.
Hamyon yo‘nalishida pul karta kartasiz — muvaffaqiyatli yechimdan so‘ng darhol bot
hamyoniga yoziladi (ledger, idempotent); kartada esa admin qo‘lda o‘tkazadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core.enums import (
    LedgerAccount,
    LedgerDirection,
    LedgerReason,
    MobcashWithdrawalStatus,
)
from app.core.errors import DomainError, NotFoundError
from app.core.money import ZERO, fmt_money, percent_of, q
from app.core.utils import utcnow
from app.mobcash import AgentClient, MobCashClient, MobCashError, MobCashErrorKind
from app.models import MobcashWithdrawal, User
from app.repositories.wallets import WalletRepository
from app.services.audit import Actor, AuditService, jsonable
from app.services.bookmakers import BookmakerService
from app.services.ledger import LedgerService
from app.services.settings import SettingsService

log = logging.getLogger(__name__)

IN_PROGRESS = "in_progress"


@dataclass(frozen=True, slots=True)
class WithdrawQuote:
    amount: Decimal
    fee: Decimal
    payout: Decimal


@dataclass(slots=True)
class WithdrawEvent:
    withdrawal: MobcashWithdrawal
    user_telegram_id: int


def mask_code(code: str) -> str:
    return (code[:3] + "***" + code[-2:]) if len(code) > 6 else "***"


def _amount_from_result(result: dict[str, object]) -> Decimal | None:
    raw = result.get("amount")
    if raw is None:
        return None
    try:
        parsed = q(Decimal(str(raw)))
    except (ArithmeticError, ValueError):
        return None
    return parsed if parsed > ZERO else None


def mask_card(number: str) -> str:
    return f"{number[:4]} **** **** {number[-4:]}" if len(number) == 16 else "****"


def pretty_card(number: str) -> str:
    return " ".join(number[i : i + 4] for i in range(0, len(number), 4))


class MobcashWithdrawalService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        settings: SettingsService,
        mobcash: MobCashClient | None,
        bookmakers: BookmakerService | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.mobcash = mobcash
        self.bookmakers = bookmakers or BookmakerService(
            session, redis, settings.config, settings, mobcash
        )
        self.wallets = WalletRepository(session)
        self.ledger = LedgerService(session)

    async def _client(self, bookmaker_id: int | None) -> MobCashClient | AgentClient:
        return await self.bookmakers.money_client(bookmaker_id)

    # ------------------------------------------------------------------ foydalanuvchi
    async def supports_preview(self, bookmaker_id: int | None = None) -> bool:
        """Kassa kod summasini oldindan bera oladimi (1xBet Cashdesk'da yo‘q)."""
        client = await self._client(bookmaker_id)
        return bool(getattr(client, "supports_amount_preview", True))

    async def quote(
        self, payer_id: str, code: str, bookmaker_id: int | None = None
    ) -> WithdrawQuote:
        """4-metod: kod bo‘yicha summani oladi va limit/komissiyani hisoblaydi."""
        if bookmaker_id is not None:
            await self.bookmakers.get_active(bookmaker_id)
        client = await self._client(bookmaker_id)
        if not getattr(client, "supports_amount_preview", True):
            # 1xBet Cashdesk: kod summasini oldindan ko'rib bo'lmaydi — bu oqim talab qiladi.
            raise DomainError(texts.MC_WD_NO_PREVIEW)
        try:
            amount = await client.get_withdrawal_amount(payer_id, code)
        except MobCashError as exc:
            log.info("getWithdrawalAmount xato payer=%s: %s", payer_id, exc.message)
            if exc.kind == MobCashErrorKind.REJECTED:
                raise DomainError(texts.MC_WD_NOT_FOUND) from exc
            raise DomainError(texts.MC_UNAVAILABLE) from exc
        s = await self.settings.snapshot()
        amount = q(amount)
        if not s.withdraw_min <= amount <= s.withdraw_max:
            raise DomainError(
                texts.MC_WD_OUT_OF_RANGE.format(
                    min=fmt_money(s.withdraw_min),
                    max=fmt_money(s.withdraw_max),
                    amount=fmt_money(amount),
                )
            )
        fee = percent_of(amount, s.withdraw_fee_percent)
        return WithdrawQuote(amount=amount, fee=fee, payout=q(amount - fee))

    async def execute(
        self,
        user: User,
        payer_id: str,
        code: str,
        quote: WithdrawQuote | None,
        card_number: str,
        bookmaker_id: int | None = None,
        *,
        to_wallet: bool = False,
    ) -> MobcashWithdrawal:
        """5-metod: Mob-Cash withdrawal. Muvaffaqiyatsiz bo‘lsa DomainError (pul yechilmagan).

        `quote=None` — kassa summani oldindan bermaydi (1xBet Cashdesk): haqiqiy summa
        Payout javobidan olinadi, komissiya o‘sha paytda hisoblanadi.
        `to_wallet` — summa kartaga emas, bot hamyoniga tushadi (karta raqami kerak emas).
        """
        if bookmaker_id is not None:
            await self.bookmakers.get_active(bookmaker_id)
        client = await self._client(bookmaker_id)
        lock_key = f"lock:mcwd:user:{user.id}"
        if not await self.redis.set(lock_key, "1", nx=True, ex=120):
            raise DomainError(texts.MC_WD_BUSY)
        try:
            wd = MobcashWithdrawal(
                user_id=user.id,
                bookmaker_id=bookmaker_id,
                payer_id=payer_id,
                code_mask=mask_code(code),
                amount=quote.amount if quote else ZERO,
                fee=quote.fee if quote else ZERO,
                payout_amount=quote.payout if quote else ZERO,
                card_number=card_number,
                status=MobcashWithdrawalStatus.REVIEW,
                last_error=IN_PROGRESS,
            )
            self.session.add(wd)
            user.remember_payer_id(bookmaker_id, payer_id)
            if card_number:
                user.payout_card_number = card_number
            await self.session.commit()  # avval yozuv, keyin pul harakati

            try:
                result = await client.withdrawal(
                    payer_id, code, quote.amount if quote else None
                )
            except MobCashError as exc:
                log.warning("Mob-Cash withdrawal xato wd=%s kind=%s", wd.id, exc.kind)
                wd.last_error = exc.message[:500]
                if exc.outcome_unknown:
                    # Pul yechilgan bo‘lishi mumkin — admin Mob-Cash panelida tekshiradi.
                    await self.session.commit()
                    return wd
                wd.status = MobcashWithdrawalStatus.FAILED
                await self.session.commit()
                if exc.kind == MobCashErrorKind.REJECTED:
                    raise DomainError(texts.MC_WD_FAILED.format(reason=exc.message)) from exc
                raise DomainError(texts.MC_UNAVAILABLE) from exc

            wd.mobcash_result = jsonable(result)
            wd.last_error = None
            if quote is None:
                amount = _amount_from_result(result)
                if amount is None:
                    # Pul yechilgan bo‘lishi mumkin, lekin summa noma’lum — operator tekshiradi.
                    wd.status = MobcashWithdrawalStatus.REVIEW
                    wd.last_error = "Payout javobida summa yo‘q — kassada tekshiring"
                    await self.session.commit()
                    return wd
                s = await self.settings.snapshot()
                wd.amount = amount
                wd.fee = percent_of(wd.amount, s.withdraw_fee_percent)
                wd.payout_amount = q(wd.amount - wd.fee)
                if not s.withdraw_min <= wd.amount <= s.withdraw_max:
                    log.warning(
                        "Cashdesk yechim oralig‘dan tashqari wd=%s summa=%s", wd.id, wd.amount
                    )
            if to_wallet:
                await self._credit_wallet(wd)
                wd.status = MobcashWithdrawalStatus.PAID
                wd.paid_at = utcnow()
            else:
                wd.status = MobcashWithdrawalStatus.AWAITING_PAYOUT
            await AuditService(self.session).log(
                Actor.user(user.telegram_id),
                "mcwd.created",
                "mobcash_withdrawal",
                wd.id,
                after={
                    "amount": wd.amount,
                    "payout": wd.payout_amount,
                    "payer_id": payer_id,
                    "destination": "wallet" if to_wallet else "card",
                },
            )
            await self.session.commit()
            return wd
        finally:
            await self.redis.delete(lock_key)

    async def _credit_wallet(self, wd: MobcashWithdrawal) -> None:
        """Yechilgan summani bot hamyoniga yozadi.

        `idempotency_key` tufayli takroriy chaqiruv balansni ikkinchi marta oshirmaydi —
        jarayon uzilib, admin `confirm_review` orqali qayta tasdiqlasa ham xavfsiz.
        """
        if wd.payout_amount <= ZERO:
            raise DomainError("Summa noma’lum — arizani kassada tekshiring.")
        wallet = await self.wallets.get_for_update(wd.user_id)
        await self.ledger.post(
            wallet=wallet,
            account=LedgerAccount.MAIN,
            direction=LedgerDirection.CREDIT,
            amount=wd.payout_amount,
            reason=LedgerReason.GAME_WITHDRAW,
            idempotency_key=f"mcwd:{wd.id}:wallet",
            reference_type="mobcash_withdrawal",
            reference_id=wd.id,
        )

    async def list_for_user(self, user: User, limit: int = 10) -> list[MobcashWithdrawal]:
        stmt = (
            select(MobcashWithdrawal)
            .where(MobcashWithdrawal.user_id == user.id)
            .order_by(MobcashWithdrawal.id.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(stmt))

    # ------------------------------------------------------------------ admin
    async def get(self, wd_id: int, *, for_update: bool = False) -> MobcashWithdrawal:
        stmt = select(MobcashWithdrawal).where(MobcashWithdrawal.id == wd_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        wd = await self.session.scalar(stmt)
        if wd is None:
            raise NotFoundError("Ariza topilmadi.")
        return wd

    async def list_by_status(
        self, statuses: tuple[MobcashWithdrawalStatus, ...], limit: int, offset: int = 0
    ) -> list[MobcashWithdrawal]:
        stmt = (
            select(MobcashWithdrawal)
            .where(MobcashWithdrawal.status.in_(statuses))
            .order_by(MobcashWithdrawal.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(stmt))

    async def counts(self) -> dict[MobcashWithdrawalStatus, int]:
        stmt = (
            select(MobcashWithdrawal.status, func.count(MobcashWithdrawal.id))
            .where(
                MobcashWithdrawal.status.in_(
                    (
                        MobcashWithdrawalStatus.AWAITING_PAYOUT,
                        MobcashWithdrawalStatus.REVIEW,
                        MobcashWithdrawalStatus.REFUND_REVIEW,
                    )
                )
            )
            .group_by(MobcashWithdrawal.status)
        )
        return {status: int(n) for status, n in (await self.session.execute(stmt)).all()}

    async def _event(self, wd: MobcashWithdrawal) -> WithdrawEvent:
        user = await self.session.get(User, wd.user_id)
        return WithdrawEvent(wd, user.telegram_id if user else 0)

    async def mark_paid(self, wd_id: int, actor: Actor) -> WithdrawEvent:
        """Admin kartaga pulni o‘tkazdi."""
        wd = await self.get(wd_id, for_update=True)
        if wd.status != MobcashWithdrawalStatus.AWAITING_PAYOUT:
            raise DomainError(f"Holat mos emas: {texts.MC_WD_STATUS[wd.status]}")
        wd.status = MobcashWithdrawalStatus.PAID
        wd.paid_at = utcnow()
        wd.processed_by = actor.telegram_id
        await AuditService(self.session).log(
            actor, "mcwd.paid", "mobcash_withdrawal", wd.id, after={"payout": wd.payout_amount}
        )
        await self.session.commit()
        return await self._event(wd)

    async def confirm_review(self, wd_id: int, actor: Actor, *, withdrawn: bool) -> WithdrawEvent:
        """Admin Mob-Cash panelida tekshirdi: pul yechilgan → to‘lov navbati, yo‘q → bajarilmadi.

        Hamyon yo‘nalishli arizada «kartaga to‘lov navbati» yo‘q — pul darhol hamyonga
        o‘tkaziladi (idempotent, `execute` yozib ulgurmagan bo‘lsa ham).
        """
        wd = await self.get(wd_id, for_update=True)
        if wd.status != MobcashWithdrawalStatus.REVIEW:
            raise DomainError(f"Holat mos emas: {texts.MC_WD_STATUS[wd.status]}")
        wd.processed_by = actor.telegram_id
        if not withdrawn:
            wd.status = MobcashWithdrawalStatus.FAILED
            wd.last_error = wd.last_error or "not_withdrawn"
        elif wd.card_number:
            wd.status = MobcashWithdrawalStatus.AWAITING_PAYOUT
            wd.last_error = None
        else:
            await self._credit_wallet(wd)
            wd.status = MobcashWithdrawalStatus.PAID
            wd.paid_at = utcnow()
            wd.last_error = None
        await AuditService(self.session).log(
            actor,
            "mcwd.review_ok" if withdrawn else "mcwd.review_fail",
            "mobcash_withdrawal",
            wd.id,
        )
        await self.session.commit()
        return await self._event(wd)

    async def refund(self, wd_id: int, actor: Actor, comment: str) -> WithdrawEvent:
        """Kartaga o‘tkazib bo‘lmasa — summa Mob-Cash deposit orqali o‘yin hisobiga qaytariladi."""
        wd = await self.get(wd_id, for_update=True)
        client = await self._client(wd.bookmaker_id)
        if wd.status != MobcashWithdrawalStatus.AWAITING_PAYOUT:
            raise DomainError(f"Holat mos emas: {texts.MC_WD_STATUS[wd.status]}")
        lock_key = f"lock:mcwd:refund:{wd.id}"
        if not await self.redis.set(lock_key, "1", nx=True, ex=180):
            raise DomainError("Qaytarish allaqachon bajarilmoqda.")
        try:
            # HTTP'dan OLDIN qayd etiladi: jarayon uzilsa, qaytarish takrorlanmaydi
            # va boshqa admin bu arizani kartaga to‘langan deb belgilay olmaydi.
            wd.status = MobcashWithdrawalStatus.REFUND_REVIEW
            wd.last_error = "Qaytarish so‘rovi boshlandi; natija hali tasdiqlanmagan"
            wd.comment = comment[:255] or None
            wd.processed_by = actor.telegram_id
            await self.session.commit()
            try:
                result = await client.deposit(wd.payer_id, wd.amount)
            except MobCashError as exc:
                wd = await self.get(wd_id, for_update=True)
                wd.last_error = exc.message[:500]
                if not exc.outcome_unknown:
                    wd.status = MobcashWithdrawalStatus.AWAITING_PAYOUT
                await self.session.commit()
                if exc.outcome_unknown:
                    raise DomainError(
                        "Qaytarish natijasi noma’lum. Mob-Cash panelida tekshiring; "
                        "ariza «Tekshiruvda» bo‘limida, qayta yuborilmadi."
                    ) from exc
                raise DomainError(f"Qaytarish bajarilmadi: {exc.message}") from exc
            wd = await self.get(wd_id, for_update=True)
            wd.status = MobcashWithdrawalStatus.REFUNDED
            wd.processed_by = actor.telegram_id
            wd.comment = comment[:255] or None
            wd.last_error = None
            wd.mobcash_result = {"withdrawal": wd.mobcash_result, "refund": jsonable(result)}
            await AuditService(self.session).log(
                actor, "mcwd.refund", "mobcash_withdrawal", wd.id, comment=comment
            )
            await self.session.commit()
        finally:
            await self.redis.delete(lock_key)
        return await self._event(wd)

    async def confirm_refund(self, wd_id: int, actor: Actor, *, refunded: bool) -> WithdrawEvent:
        """Admin paneldagi tekshiruv natijasi; bu amal Mob-Cash'ga pul so‘rovi yubormaydi."""
        wd = await self.get(wd_id, for_update=True)
        if wd.status != MobcashWithdrawalStatus.REFUND_REVIEW:
            raise DomainError(f"Holat mos emas: {texts.MC_WD_STATUS[wd.status]}")
        if await self.redis.exists(f"lock:mcwd:refund:{wd.id}"):
            raise DomainError("Qaytarish so‘rovi hali yakunlanmagan. Biroz kuting.")
        wd.status = (
            MobcashWithdrawalStatus.REFUNDED
            if refunded
            else MobcashWithdrawalStatus.AWAITING_PAYOUT
        )
        wd.processed_by = actor.telegram_id
        wd.last_error = None
        await AuditService(self.session).log(
            actor,
            "mcwd.refund_confirmed" if refunded else "mcwd.refund_not_applied",
            "mobcash_withdrawal",
            wd.id,
        )
        await self.session.commit()
        return await self._event(wd)
