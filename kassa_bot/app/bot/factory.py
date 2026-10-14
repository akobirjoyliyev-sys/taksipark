from __future__ import annotations

from aiogram import Dispatcher
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage

from app.admin import build_admin_router
from app.bootstrap import AppContext
from app.bot.handlers import build_user_routers
from app.bot.handlers.common import errors_router
from app.bot.middlewares import DbSessionMiddleware, ThrottlingMiddleware, UserContextMiddleware


def create_dispatcher(ctx: AppContext) -> Dispatcher:
    """FSM holatlari Redis'da saqlanadi (bir nechta replika va restartlarga chidamli)."""
    storage = RedisStorage(
        redis=ctx.redis,
        key_builder=DefaultKeyBuilder(prefix="fsm", with_destiny=True),
        state_ttl=24 * 3600,
        data_ttl=24 * 3600,
    )
    dp = Dispatcher(storage=storage)

    dp.update.outer_middleware(
        DbSessionMiddleware(ctx.sessionmaker, ctx.redis, ctx.providers, ctx.config, ctx.mobcash)
    )
    throttling = ThrottlingMiddleware(
        ctx.redis, ctx.config.rate_limit_per_second, ctx.config.rate_limit_per_minute
    )
    user_context = UserContextMiddleware()
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(throttling)
        observer.outer_middleware(user_context)

    dp.include_router(build_admin_router())
    for router in build_user_routers():
        dp.include_router(router)
    dp.include_router(errors_router)
    return dp
