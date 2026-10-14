from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import texts
from app.bot.keyboards.user import contact_kb, subscription_kb
from app.config import Config
from app.mobcash import MobCashClient
from app.payments.registry import ProviderRegistry
from app.services.container import Services

log = logging.getLogger(__name__)
Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


async def _reply(event: TelegramObject, text: str, **kwargs: Any) -> None:
    if isinstance(event, Message):
        await event.answer(text, **kwargs)
    elif isinstance(event, CallbackQuery):
        await event.answer(text[:190], show_alert=True)


class DbSessionMiddleware(BaseMiddleware):
    """Har bir update uchun alohida DB sessiya va servislar konteyneri."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        redis: Redis,
        providers: ProviderRegistry,
        config: Config,
        mobcash: MobCashClient | None = None,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.redis = redis
        self.providers = providers
        self.config = config
        self.mobcash = mobcash

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        async with self.sessionmaker() as session:
            data["session"] = session
            data["svc"] = Services(
                session=session,
                redis=self.redis,
                providers=self.providers,
                config=self.config,
                bot=data.get("bot"),
                mobcash=self.mobcash,
            )
            return await handler(event, data)


class ThrottlingMiddleware(BaseMiddleware):
    """Redis asosidagi rate limit: soniyasiga va daqiqasiga N ta so‘rov."""

    def __init__(self, redis: Redis, per_second: int, per_minute: int) -> None:
        self.redis = redis
        self.per_second = per_second
        self.per_minute = per_minute

    async def is_limited(self, user_id: int) -> bool:
        now = int(time.time())
        sec_key = f"rl:s:{user_id}:{now}"
        min_key = f"rl:m:{user_id}:{now // 60}"
        pipe = self.redis.pipeline()
        pipe.incr(sec_key)
        pipe.expire(sec_key, 2)
        pipe.incr(min_key)
        pipe.expire(min_key, 61)
        sec_count, _, min_count, _ = await pipe.execute()
        return int(sec_count) > self.per_second or int(min_count) > self.per_minute

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        try:
            limited = await self.is_limited(user.id)
        except Exception:  # Redis ishlamasa botni to‘xtatmaymiz
            log.warning("Rate limit tekshiruvi ishlamadi", exc_info=True)
            limited = False
        if limited:
            if await self.redis.set(f"rl:warn:{user.id}", "1", ex=10, nx=True):
                await _reply(event, texts.FLOOD)
            elif isinstance(event, CallbackQuery):
                await event.answer()
            return None
        return await handler(event, data)


class UserContextMiddleware(BaseMiddleware):
    """Foydalanuvchini yaratadi/yuklaydi, admin rolini, ban va texnik rejimni tekshiradi."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.is_bot:
            return await handler(event, data)
        if isinstance(event, Message) and event.chat.type != "private":
            return None  # bot faqat shaxsiy chatda ishlaydi
        svc: Services = data["svc"]
        user, created = await svc.users.get_or_create(tg_user)
        admin = await svc.admins.get_active(tg_user.id)
        rt = await svc.settings.snapshot()
        data.update(user=user, is_new_user=created, admin=admin, rt=rt)
        if admin is None:
            if user.is_banned:
                await _reply(event, texts.BANNED)
                return None
            if rt.maintenance:
                await _reply(event, texts.MAINTENANCE)
                return None
        return await handler(event, data)


class GateMiddleware(BaseMiddleware):
    """Asosiy menyu oldidan: majburiy kontakt va majburiy obuna tekshiruvi."""

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        if data.get("admin") is not None:
            return await handler(event, data)
        user = data.get("user")
        rt = data.get("rt")
        svc: Services = data["svc"]
        if user is None or rt is None:
            return await handler(event, data)
        if rt.contact_required and not user.contact_verified:
            if isinstance(event, CallbackQuery):
                await event.answer()
                if event.message:
                    await event.message.answer(
                        texts.CONTACT_PROMPT_REQUIRED, reply_markup=contact_kb(True)
                    )
            else:
                await _reply(event, texts.CONTACT_PROMPT_REQUIRED, reply_markup=contact_kb(True))
            return None
        if rt.subscription_enabled:
            missing = await svc.subscription.missing_channels(user.telegram_id)
            if missing:
                markup = subscription_kb(missing)
                if isinstance(event, CallbackQuery):
                    await event.answer()
                    if event.message:
                        await event.message.answer(texts.SUB_REQUIRED, reply_markup=markup)
                else:
                    await _reply(event, texts.SUB_REQUIRED, reply_markup=markup)
                return None
        return await handler(event, data)
