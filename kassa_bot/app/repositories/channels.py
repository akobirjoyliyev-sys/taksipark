from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JoinRequestStatus
from app.models import JoinRequest, RequiredChannel


class ChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[RequiredChannel]:
        stmt = select(RequiredChannel).order_by(RequiredChannel.sort_order, RequiredChannel.id)
        return list(await self.session.scalars(stmt))

    async def list_active(self) -> list[RequiredChannel]:
        stmt = (
            select(RequiredChannel)
            .where(RequiredChannel.is_active.is_(True))
            .order_by(RequiredChannel.sort_order, RequiredChannel.id)
        )
        return list(await self.session.scalars(stmt))

    async def get(self, channel_id: int) -> RequiredChannel | None:
        return await self.session.get(RequiredChannel, channel_id)

    async def get_by_username(self, username: str) -> RequiredChannel | None:
        stmt = select(RequiredChannel).where(
            func.lower(RequiredChannel.username) == username.lower()
        )
        return await self.session.scalar(stmt)

    async def max_order(self) -> int:
        value = await self.session.scalar(select(func.max(RequiredChannel.sort_order)))
        return int(value or 0)


class JoinRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, request_id: int) -> JoinRequest | None:
        return await self.session.get(JoinRequest, request_id)

    async def find_pending(self, chat_id: int, user_telegram_id: int) -> JoinRequest | None:
        stmt = select(JoinRequest).where(
            JoinRequest.chat_id == chat_id,
            JoinRequest.user_telegram_id == user_telegram_id,
            JoinRequest.status == JoinRequestStatus.PENDING,
        )
        return await self.session.scalar(stmt)

    async def list_page(
        self,
        status: JoinRequestStatus | None,
        chat_id: int | None,
        limit: int,
        offset: int,
    ) -> list[JoinRequest]:
        stmt = select(JoinRequest)
        if status is not None:
            stmt = stmt.where(JoinRequest.status == status)
        if chat_id is not None:
            stmt = stmt.where(JoinRequest.chat_id == chat_id)
        stmt = stmt.order_by(JoinRequest.id.desc()).limit(limit).offset(offset)
        return list(await self.session.scalars(stmt))

    async def count(self, status: JoinRequestStatus | None, chat_id: int | None) -> int:
        stmt = select(func.count(JoinRequest.id))
        if status is not None:
            stmt = stmt.where(JoinRequest.status == status)
        if chat_id is not None:
            stmt = stmt.where(JoinRequest.chat_id == chat_id)
        return int(await self.session.scalar(stmt) or 0)

    async def chats(self) -> list[tuple[int, str]]:
        stmt = (
            select(JoinRequest.chat_id, func.max(JoinRequest.chat_title))
            .group_by(JoinRequest.chat_id)
            .order_by(JoinRequest.chat_id)
        )
        return [(r[0], r[1] or str(r[0])) for r in await self.session.execute(stmt)]
