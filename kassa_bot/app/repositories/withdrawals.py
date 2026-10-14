from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ACTIVE_WITHDRAWAL_STATUSES, WithdrawalSource, WithdrawalStatus
from app.models import Withdrawal, WithdrawalStatusHistory


class WithdrawalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, withdrawal_id: int, *, for_update: bool = False) -> Withdrawal | None:
        stmt = select(Withdrawal).where(Withdrawal.id == withdrawal_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def get_by_ref(self, ref: str, *, for_update: bool = False) -> Withdrawal | None:
        try:
            ref_uuid = uuid.UUID(ref)
        except (ValueError, TypeError):
            return None
        stmt = select(Withdrawal).where(Withdrawal.ref == ref_uuid)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def count_active_for_user(self, user_id: int) -> int:
        stmt = select(func.count(Withdrawal.id)).where(
            Withdrawal.user_id == user_id,
            Withdrawal.source == WithdrawalSource.USER,
            Withdrawal.status.in_(ACTIVE_WITHDRAWAL_STATUSES),
        )
        return int(await self.session.scalar(stmt) or 0)

    async def list_for_user(
        self,
        user_id: int,
        statuses: Sequence[WithdrawalStatus] | None,
        limit: int,
        offset: int = 0,
    ) -> list[Withdrawal]:
        stmt = select(Withdrawal).where(
            Withdrawal.user_id == user_id, Withdrawal.source == WithdrawalSource.USER
        )
        if statuses:
            stmt = stmt.where(Withdrawal.status.in_(statuses))
        stmt = stmt.order_by(Withdrawal.id.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def list_by_status(
        self, status: WithdrawalStatus, limit: int, offset: int = 0
    ) -> list[Withdrawal]:
        stmt = (
            select(Withdrawal)
            .where(Withdrawal.status == status)
            .order_by(Withdrawal.id)
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(stmt))

    async def count_by_status(self, status: WithdrawalStatus) -> int:
        stmt = select(func.count(Withdrawal.id)).where(Withdrawal.status == status)
        return int(await self.session.scalar(stmt) or 0)

    async def count_manual_pending(self) -> int:
        stmt = select(func.count(Withdrawal.id)).where(
            Withdrawal.status == WithdrawalStatus.PENDING, Withdrawal.manual_required.is_(True)
        )
        return int(await self.session.scalar(stmt) or 0)

    async def lock_due_for_payout(self, now: datetime, limit: int) -> list[Withdrawal]:
        """Navbatdagi tasdiqlangan arizalar. SKIP LOCKED — bir nechta worker xavfsiz ishlaydi."""
        stmt = (
            select(Withdrawal)
            .where(
                Withdrawal.status == WithdrawalStatus.APPROVED,
                (Withdrawal.next_attempt_at.is_(None)) | (Withdrawal.next_attempt_at <= now),
            )
            .order_by(Withdrawal.next_attempt_at.nulls_first(), Withdrawal.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(await self.session.scalars(stmt))

    async def processing_ids(
        self, updated_before: datetime | None = None, limit: int = 100
    ) -> list[int]:
        stmt = select(Withdrawal.id).where(Withdrawal.status == WithdrawalStatus.PROCESSING)
        if updated_before is not None:
            stmt = stmt.where(Withdrawal.updated_at < updated_before)
        return list(await self.session.scalars(stmt.order_by(Withdrawal.id).limit(limit)))

    async def manual_ids(self, limit: int = 500) -> list[int]:
        stmt = (
            select(Withdrawal.id)
            .where(
                Withdrawal.status == WithdrawalStatus.PENDING,
                Withdrawal.manual_required.is_(True),
            )
            .order_by(Withdrawal.id)
            .limit(limit)
        )
        return list(await self.session.scalars(stmt))

    async def history(self, withdrawal_id: int) -> list[WithdrawalStatusHistory]:
        stmt = (
            select(WithdrawalStatusHistory)
            .where(WithdrawalStatusHistory.withdrawal_id == withdrawal_id)
            .order_by(WithdrawalStatusHistory.id)
        )
        return list(await self.session.scalars(stmt))
