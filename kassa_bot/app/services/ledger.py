from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core.enums import LedgerAccount, LedgerDirection, LedgerReason
from app.core.errors import InsufficientFundsError
from app.core.money import ZERO, fmt_money, q
from app.models import LedgerEntry, Wallet
from app.repositories.wallets import LedgerRepository

_FIELDS = {
    LedgerAccount.MAIN: "available",
    LedgerAccount.BLOCKED: "blocked",
    LedgerAccount.BONUS: "bonus_balance",
}


class LedgerService:
    """Hamyon balansini faqat ledger yozuvi orqali o‘zgartiradi.

    Har bir yozuv `idempotency_key` bilan yagona — bir xil operatsiya qayta chaqirilsa
    balans ikkinchi marta o‘zgarmaydi. Hamyon chaqiruvchi tomonidan FOR UPDATE bilan
    bloklangan bo‘lishi shart.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LedgerRepository(session)

    async def post(
        self,
        *,
        wallet: Wallet | None,
        account: LedgerAccount,
        direction: LedgerDirection,
        amount: Decimal,
        reason: LedgerReason,
        idempotency_key: str,
        reference_type: str | None = None,
        reference_id: object | None = None,
        external_tx_id: str | None = None,
        actor_telegram_id: int | None = None,
        comment: str | None = None,
        user_id: int | None = None,
    ) -> LedgerEntry:
        amount = q(amount)
        if amount <= ZERO:
            raise ValueError("Ledger summasi musbat bo‘lishi kerak")
        existing = await self.repo.get_by_key(idempotency_key)
        if existing is not None:
            return existing

        balance_after: Decimal | None = None
        if account != LedgerAccount.SYSTEM:
            if wallet is None:
                raise ValueError("Hamyon hisobidagi yozuv uchun wallet kerak")
            field = _FIELDS[account]
            current: Decimal = getattr(wallet, field)
            new_value = (
                current + amount if direction == LedgerDirection.CREDIT else current - amount
            )
            if new_value < ZERO:
                raise InsufficientFundsError(
                    texts.WITHDRAW_INSUFFICIENT.format(available=fmt_money(current))
                )
            setattr(wallet, field, new_value)
            balance_after = new_value
            user_id = wallet.user_id

        entry = LedgerEntry(
            user_id=user_id,
            account=account,
            direction=direction,
            amount=amount,
            balance_after=balance_after,
            reason=reason,
            reference_type=reference_type,
            reference_id=None if reference_id is None else str(reference_id),
            external_tx_id=external_tx_id,
            idempotency_key=idempotency_key,
            actor_telegram_id=actor_telegram_id,
            comment=comment,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def transfer(
        self,
        *,
        wallet: Wallet,
        source: LedgerAccount,
        target: LedgerAccount,
        amount: Decimal,
        reason: LedgerReason,
        key_prefix: str,
        reference_type: str | None = None,
        reference_id: object | None = None,
        actor_telegram_id: int | None = None,
        comment: str | None = None,
    ) -> None:
        """Bitta hamyon ichidagi ikki hisob o‘rtasida (masalan main → blocked)."""
        common = {
            "wallet": wallet,
            "amount": amount,
            "reason": reason,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "actor_telegram_id": actor_telegram_id,
            "comment": comment,
        }
        await self.post(
            account=source,
            direction=LedgerDirection.DEBIT,
            idempotency_key=f"{key_prefix}:{source.value}",
            **common,  # type: ignore[arg-type]
        )
        await self.post(
            account=target,
            direction=LedgerDirection.CREDIT,
            idempotency_key=f"{key_prefix}:{target.value}",
            **common,  # type: ignore[arg-type]
        )
