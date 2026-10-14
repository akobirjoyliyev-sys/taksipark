from __future__ import annotations

import logging
import re

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatJoinRequest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import JoinRequestStatus
from app.core.errors import DomainError, NotFoundError
from app.core.utils import utcnow
from app.models import JoinRequest, RequiredChannel
from app.repositories.channels import ChannelRepository, JoinRequestRepository
from app.services.audit import Actor, AuditService

log = logging.getLogger(__name__)

_CHANNEL_FORM = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,31})\s*\|\s*(.{1,128})$")
_MEMBER_OK = {ChatMemberStatus.CREATOR, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.MEMBER}


def parse_channel_form(text: str) -> tuple[str, str]:
    """`@username | Kanal nomi` formatini tekshiradi."""
    m = _CHANNEL_FORM.match(text.strip())
    if not m:
        raise DomainError("Format: <code>@username | Kanal nomi</code>")
    return m.group(1), m.group(2).strip()


class SubscriptionService:
    """Majburiy obuna tekshiruvi (natija Redis'da qisqa muddat keshlanadi)."""

    OK_TTL = 120

    def __init__(self, session: AsyncSession, redis: Redis, bot: Bot | None) -> None:
        self.session = session
        self.redis = redis
        self.bot = bot
        self.channels = ChannelRepository(session)
        self.join_requests = JoinRequestRepository(session)

    async def missing_channels(
        self, telegram_id: int, use_cache: bool = True
    ) -> list[RequiredChannel]:
        cache_key = f"sub_ok:{telegram_id}"
        if use_cache and await self.redis.get(cache_key):
            return []
        channels = await self.channels.list_active()
        if not channels or self.bot is None:
            return []
        missing: list[RequiredChannel] = []
        for channel in channels:
            chat: int | str = channel.chat_id or f"@{channel.username}"
            try:
                member = await self.bot.get_chat_member(chat, telegram_id)
            except TelegramAPIError as exc:
                # Bot kanalda admin emas yoki kanal topilmadi — foydalanuvchini bloklamaymiz.
                log.warning("Obunani tekshirib bo‘lmadi kanal=@%s: %s", channel.username, exc)
                continue
            is_member = member.status in _MEMBER_OK or (
                member.status == ChatMemberStatus.RESTRICTED and getattr(member, "is_member", False)
            )
            if is_member:
                continue
            if channel.chat_id and await self.join_requests.find_pending(
                channel.chat_id, telegram_id
            ):
                continue  # kirish so‘rovi yuborilgan — yetarli
            missing.append(channel)
        if not missing:
            await self.redis.set(cache_key, "1", ex=self.OK_TTL)
        return missing


class ChannelService:
    def __init__(self, session: AsyncSession, bot: Bot | None) -> None:
        self.session = session
        self.bot = bot
        self.repo = ChannelRepository(session)
        self.audit = AuditService(session)

    async def list_page(self) -> list[RequiredChannel]:
        return await self.repo.list_all()

    async def get(self, channel_id: int) -> RequiredChannel:
        channel = await self.repo.get(channel_id)
        if channel is None:
            raise NotFoundError("Kanal topilmadi.")
        return channel

    async def _refresh_admin(self, channel: RequiredChannel) -> bool:
        if self.bot is None:
            return False
        try:
            chat = await self.bot.get_chat(channel.chat_id or f"@{channel.username}")
            me = await self.bot.me()
            member = await self.bot.get_chat_member(chat.id, me.id)
        except TelegramAPIError as exc:
            log.info("Kanal tekshiruvi @%s: %s", channel.username, exc)
            channel.bot_is_admin = False
            channel.checked_at = utcnow()
            return False
        channel.chat_id = chat.id
        if chat.title:
            channel.title = chat.title[:128]
        channel.invite_link = chat.invite_link or channel.invite_link
        channel.bot_is_admin = member.status in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }
        channel.checked_at = utcnow()
        return channel.bot_is_admin

    async def add(self, raw: str, actor: Actor) -> RequiredChannel:
        username, title = parse_channel_form(raw)
        if await self.repo.get_by_username(username) is not None:
            raise DomainError("Bu kanal allaqachon qo‘shilgan.")
        channel = RequiredChannel(
            username=username, title=title, sort_order=await self.repo.max_order() + 1
        )
        self.session.add(channel)
        await self._refresh_admin(channel)
        channel.title = title  # admin kiritgan nom ustun
        await self.session.flush()
        await self.audit.log(
            actor,
            "channel.add",
            "channel",
            channel.id,
            after={"username": username, "title": title, "bot_is_admin": channel.bot_is_admin},
        )
        await self.session.commit()
        return channel

    async def check_admin(self, channel_id: int, actor: Actor) -> RequiredChannel:
        channel = await self.get(channel_id)
        title = channel.title
        await self._refresh_admin(channel)
        channel.title = title
        await self.audit.log(
            actor,
            "channel.check",
            "channel",
            channel.id,
            after={"bot_is_admin": channel.bot_is_admin},
        )
        await self.session.commit()
        return channel

    async def toggle(self, channel_id: int, actor: Actor) -> RequiredChannel:
        channel = await self.get(channel_id)
        channel.is_active = not channel.is_active
        await self.audit.log(
            actor, "channel.toggle", "channel", channel.id, after={"is_active": channel.is_active}
        )
        await self.session.commit()
        return channel

    async def move(self, channel_id: int, direction: int, actor: Actor) -> None:
        channels = await self.repo.list_all()
        index = next((i for i, c in enumerate(channels) if c.id == channel_id), None)
        if index is None:
            raise NotFoundError("Kanal topilmadi.")
        target = index + direction
        if not 0 <= target < len(channels):
            return
        channels[index], channels[target] = channels[target], channels[index]
        for order, channel in enumerate(channels, start=1):
            channel.sort_order = order
        await self.audit.log(
            actor,
            "channel.reorder",
            "channel",
            channel_id,
            after={"order": [c.id for c in channels]},
        )
        await self.session.commit()

    async def delete(self, channel_id: int, actor: Actor) -> None:
        channel = await self.get(channel_id)
        await self.audit.log(
            actor,
            "channel.delete",
            "channel",
            channel.id,
            before={"username": channel.username, "title": channel.title},
        )
        await self.session.delete(channel)
        await self.session.commit()

    async def refresh_all(self) -> None:
        for channel in await self.repo.list_all():
            title = channel.title
            await self._refresh_admin(channel)
            channel.title = title
        await self.session.commit()


class JoinRequestService:
    def __init__(self, session: AsyncSession, bot: Bot | None) -> None:
        self.session = session
        self.bot = bot
        self.repo = JoinRequestRepository(session)
        self.audit = AuditService(session)

    async def store(self, event: ChatJoinRequest) -> JoinRequest:
        existing = await self.repo.find_pending(event.chat.id, event.from_user.id)
        if existing is not None:
            return existing
        request = JoinRequest(
            chat_id=event.chat.id,
            chat_title=(event.chat.title or "")[:128] or None,
            user_telegram_id=event.from_user.id,
            username=event.from_user.username,
            full_name=event.from_user.full_name[:128],
        )
        self.session.add(request)
        await self.session.commit()
        return request

    async def list_page(
        self, status: JoinRequestStatus | None, chat_id: int | None, page: int, per_page: int = 8
    ) -> tuple[list[JoinRequest], int]:
        rows = await self.repo.list_page(status, chat_id, per_page, page * per_page)
        return rows, await self.repo.count(status, chat_id)

    async def chats(self) -> list[tuple[int, str]]:
        return await self.repo.chats()

    async def get(self, request_id: int) -> JoinRequest:
        request = await self.repo.get(request_id)
        if request is None:
            raise NotFoundError("So‘rov topilmadi.")
        return request

    async def decide(self, request_id: int, approve: bool, actor: Actor) -> JoinRequest:
        request = await self.get(request_id)
        if request.status != JoinRequestStatus.PENDING:
            raise DomainError("So‘rov allaqachon ko‘rib chiqilgan.")
        await self._apply(request, approve, actor)
        await self.session.commit()
        return request

    async def approve_all(self, chat_id: int | None, actor: Actor, limit: int = 50) -> int:
        rows = await self.repo.list_page(JoinRequestStatus.PENDING, chat_id, limit, 0)
        done = 0
        for request in rows:
            try:
                await self._apply(request, True, actor)
                done += 1
            except DomainError:
                continue
        await self.session.commit()
        return done

    async def _apply(self, request: JoinRequest, approve: bool, actor: Actor) -> None:
        if self.bot is None:
            raise DomainError("Bot ulanmagan.")
        try:
            if approve:
                await self.bot.approve_chat_join_request(request.chat_id, request.user_telegram_id)
            else:
                await self.bot.decline_chat_join_request(request.chat_id, request.user_telegram_id)
        except TelegramAPIError as exc:
            # So‘rov Telegramda allaqachon yopilgan bo‘lishi mumkin — holatni yangilaymiz.
            log.info("Join request %s: %s", request.id, exc)
        request.status = JoinRequestStatus.APPROVED if approve else JoinRequestStatus.DECLINED
        request.processed_by = actor.telegram_id
        request.processed_at = utcnow()
        await self.audit.log(
            actor,
            "join_request.approve" if approve else "join_request.decline",
            "join_request",
            request.id,
            after={"chat_id": request.chat_id, "user": request.user_telegram_id},
        )
