from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PaymentStatus, ProviderEventKind
from app.models import Payment, PayoutCard, WebhookEvent


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: int, *, for_update: bool = False) -> Payment | None:
        stmt = select(Payment).where(Payment.id == payment_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def get_by_ref(self, ref: str, *, for_update: bool = False) -> Payment | None:
        try:
            ref_uuid = uuid.UUID(ref)
        except (ValueError, TypeError):
            return None
        stmt = select(Payment).where(Payment.ref == ref_uuid)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def count_pending_for_user(self, user_id: int) -> int:
        stmt = select(func.count(Payment.id)).where(
            Payment.user_id == user_id, Payment.status == PaymentStatus.PENDING
        )
        return int(await self.session.scalar(stmt) or 0)

    async def list_for_user(
        self,
        user_id: int,
        statuses: Sequence[PaymentStatus] | None,
        limit: int,
        offset: int,
    ) -> list[Payment]:
        stmt = select(Payment).where(Payment.user_id == user_id)
        if statuses:
            stmt = stmt.where(Payment.status.in_(statuses))
        stmt = stmt.order_by(Payment.id.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def pending_ids(
        self,
        *,
        expires_before: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 100,
    ) -> list[int]:
        stmt = select(Payment.id).where(Payment.status == PaymentStatus.PENDING)
        if expires_before is not None:
            stmt = stmt.where(Payment.expires_at < expires_before)
        if created_before is not None:
            stmt = stmt.where(Payment.created_at < created_before)
        stmt = stmt.order_by(Payment.id).limit(limit)
        return list(await self.session.scalars(stmt))

    async def count_by_status(self, status: PaymentStatus) -> int:
        stmt = select(func.count(Payment.id)).where(Payment.status == status)
        return int(await self.session.scalar(stmt) or 0)


class WebhookEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def insert_if_new(
        self,
        *,
        provider: str,
        event_id: str,
        kind: ProviderEventKind,
        reference: str,
        status: str,
        payload: dict[str, Any],
    ) -> int | None:
        """Yangi bo‘lsa id qaytaradi, takroriy hodisa bo‘lsa None (idempotentlik)."""
        stmt = (
            insert(WebhookEvent)
            .values(
                provider=provider,
                event_id=event_id,
                kind=kind,
                reference=reference,
                status=status,
                payload=payload,
                processed=True,
            )
            .on_conflict_do_nothing(constraint="uq_webhook_events_event")
            .returning(WebhookEvent.id)
        )
        return await self.session.scalar(stmt)


class CardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self, user_id: int) -> list[PayoutCard]:
        stmt = (
            select(PayoutCard)
            .where(PayoutCard.user_id == user_id, PayoutCard.is_active.is_(True))
            .order_by(PayoutCard.id)
        )
        return list(await self.session.scalars(stmt))

    async def get_active(self, card_id: int, user_id: int) -> PayoutCard | None:
        stmt = select(PayoutCard).where(
            PayoutCard.id == card_id,
            PayoutCard.user_id == user_id,
            PayoutCard.is_active.is_(True),
        )
        return await self.session.scalar(stmt)

    async def get_by_token(self, provider: str, token: str) -> PayoutCard | None:
        stmt = select(PayoutCard).where(PayoutCard.provider == provider, PayoutCard.token == token)
        return await self.session.scalar(stmt)

    async def first_active_for_provider(self, user_id: int, provider: str) -> PayoutCard | None:
        stmt = (
            select(PayoutCard)
            .where(
                PayoutCard.user_id == user_id,
                PayoutCard.provider == provider,
                PayoutCard.is_active.is_(True),
            )
            .order_by(PayoutCard.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def count_active(self) -> int:
        stmt = select(func.count(PayoutCard.id)).where(PayoutCard.is_active.is_(True))
        return int(await self.session.scalar(stmt) or 0)
