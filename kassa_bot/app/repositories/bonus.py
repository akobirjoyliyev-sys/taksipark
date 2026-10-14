from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import PromoActivationStatus
from app.models import PromoActivation, PromoCode, ReferralReward, VipLevel


class PromoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, promo_id: int) -> PromoCode | None:
        return await self.session.get(PromoCode, promo_id)

    async def get_by_code(self, code: str, *, for_update: bool = False) -> PromoCode | None:
        stmt = select(PromoCode).where(
            PromoCode.code == code.strip().upper(), PromoCode.is_deleted.is_(False)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_page(self, limit: int, offset: int) -> list[PromoCode]:
        stmt = (
            select(PromoCode)
            .where(PromoCode.is_deleted.is_(False))
            .order_by(PromoCode.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(stmt))

    async def user_usage_count(self, promo_id: int, user_id: int) -> int:
        stmt = select(func.count(PromoActivation.id)).where(
            PromoActivation.promo_id == promo_id,
            PromoActivation.user_id == user_id,
            PromoActivation.status != PromoActivationStatus.EXPIRED,
        )
        return int(await self.session.scalar(stmt) or 0)

    async def pending_activation(self, user_id: int) -> PromoActivation | None:
        stmt = (
            select(PromoActivation)
            .where(
                PromoActivation.user_id == user_id,
                PromoActivation.status == PromoActivationStatus.PENDING,
            )
            .order_by(PromoActivation.id)
            .limit(1)
            .with_for_update()
        )
        return await self.session.scalar(stmt)

    async def increment_usage(self, promo_id: int) -> None:
        await self.session.execute(
            update(PromoCode)
            .where(PromoCode.id == promo_id)
            .values(used_count=PromoCode.used_count + 1)
        )


class VipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active(self) -> list[VipLevel]:
        stmt = (
            select(VipLevel)
            .where(VipLevel.is_active.is_(True))
            .order_by(VipLevel.min_total_deposit, VipLevel.sort_order)
        )
        return list(await self.session.scalars(stmt))

    async def list_all(self) -> list[VipLevel]:
        stmt = select(VipLevel).order_by(VipLevel.min_total_deposit, VipLevel.sort_order)
        return list(await self.session.scalars(stmt))

    async def get(self, level_id: int) -> VipLevel | None:
        return await self.session.get(VipLevel, level_id)


class ReferralRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def total_paid(self) -> Decimal:
        value = await self.session.scalar(select(func.coalesce(func.sum(ReferralReward.amount), 0)))
        return Decimal(value or 0)
