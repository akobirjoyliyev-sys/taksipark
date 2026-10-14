from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReferralReward, User, Wallet


@dataclass(frozen=True, slots=True)
class ReferrerRow:
    user_id: int
    telegram_id: int
    name: str
    friends: int
    earned: Decimal


@dataclass(frozen=True, slots=True)
class FriendRow:
    name: str
    joined_at: datetime
    total_deposit: Decimal


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return await self.session.scalar(select(User).where(User.telegram_id == telegram_id))

    async def insert_if_absent(self, **values: object) -> int | None:
        stmt = (
            insert(User)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[User.telegram_id])
            .returning(User.id)
        )
        return await self.session.scalar(stmt)

    async def search(self, query: str, limit: int = 10) -> list[User]:
        query = query.strip()
        conditions = []
        digits = query.lstrip("+").replace(" ", "")
        if digits.isdigit():
            conditions.append(User.telegram_id == int(digits))
            if len(digits) >= 7:
                conditions.append(User.phone.like(f"%{digits[-9:]}"))
        username = query.lstrip("@")
        if username:
            conditions.append(func.lower(User.username) == username.lower())
        if not conditions:
            return []
        stmt = select(User).where(or_(*conditions)).order_by(User.id.desc()).limit(limit)
        return list(await self.session.scalars(stmt))

    async def count(self) -> int:
        return int(await self.session.scalar(select(func.count(User.id))) or 0)

    async def count_contact_verified(self) -> int:
        stmt = select(func.count(User.id)).where(User.contact_verified.is_(True))
        return int(await self.session.scalar(stmt) or 0)

    async def count_created_between(self, start: datetime, end: datetime) -> int:
        stmt = select(func.count(User.id)).where(User.created_at >= start, User.created_at < end)
        return int(await self.session.scalar(stmt) or 0)

    async def referrals_count(self, user_id: int) -> int:
        stmt = select(func.count(User.id)).where(User.referrer_id == user_id)
        return int(await self.session.scalar(stmt) or 0)

    async def friends(self, user_id: int, limit: int, offset: int) -> list[FriendRow]:
        stmt = (
            select(User.first_name, User.created_at, Wallet.total_deposit)
            .join(Wallet, Wallet.user_id == User.id)
            .where(User.referrer_id == user_id)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = await self.session.execute(stmt)
        return [FriendRow(name=r[0] or "", joined_at=r[1], total_deposit=r[2]) for r in rows]

    async def top_referrers(
        self, since: datetime | None = None, limit: int = 10
    ) -> list[ReferrerRow]:
        """Reyting: taklif qilingan do‘stlar soni va referal bonus summasi bo‘yicha."""
        friends_q: Select[tuple[int | None, int]] = select(
            User.referrer_id.label("rid"), func.count(User.id).label("cnt")
        ).where(User.referrer_id.is_not(None))
        earned_q = select(
            ReferralReward.referrer_id.label("rid"), func.sum(ReferralReward.amount).label("amt")
        )
        if since is not None:
            friends_q = friends_q.where(User.created_at >= since)
            earned_q = earned_q.where(ReferralReward.created_at >= since)
        friends_sq = friends_q.group_by(User.referrer_id).subquery()
        earned_sq = earned_q.group_by(ReferralReward.referrer_id).subquery()
        stmt = (
            select(
                User.id,
                User.telegram_id,
                User.first_name,
                func.coalesce(friends_sq.c.cnt, 0),
                func.coalesce(earned_sq.c.amt, 0),
            )
            .join(friends_sq, friends_sq.c.rid == User.id, isouter=True)
            .join(earned_sq, earned_sq.c.rid == User.id, isouter=True)
            .where(or_(friends_sq.c.cnt > 0, earned_sq.c.amt > 0))
            .order_by(
                func.coalesce(friends_sq.c.cnt, 0).desc(),
                func.coalesce(earned_sq.c.amt, 0).desc(),
                User.id,
            )
            .limit(limit)
        )
        rows = await self.session.execute(stmt)
        return [
            ReferrerRow(
                user_id=r[0], telegram_id=r[1], name=r[2] or "", friends=int(r[3]), earned=r[4]
            )
            for r in rows
        ]
