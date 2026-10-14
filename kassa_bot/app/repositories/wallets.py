from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LedgerReason
from app.models import LedgerEntry, Wallet


class WalletRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user(self, user_id: int) -> Wallet | None:
        return await self.session.scalar(select(Wallet).where(Wallet.user_id == user_id))

    async def get_for_update(self, user_id: int) -> Wallet:
        """Hamyonni `SELECT ... FOR UPDATE` bilan bloklaydi (parallel o‘zgarishlardan himoya)."""
        stmt = (
            select(Wallet)
            .where(Wallet.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        wallet = await self.session.scalar(stmt)
        if wallet is None:
            wallet = Wallet(user_id=user_id)
            self.session.add(wallet)
            await self.session.flush()
        return wallet


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> LedgerEntry | None:
        return await self.session.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == key)
        )

    async def list_for_user(
        self,
        user_id: int,
        *,
        limit: int,
        offset: int = 0,
        reasons: tuple[LedgerReason, ...] | None = None,
    ) -> list[LedgerEntry]:
        stmt = select(LedgerEntry).where(LedgerEntry.user_id == user_id)
        if reasons:
            stmt = stmt.where(LedgerEntry.reason.in_(reasons))
        stmt = stmt.order_by(LedgerEntry.id.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))
