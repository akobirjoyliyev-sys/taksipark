"""Bot, API va worker jarayonlari uchun umumiy ishga tushirish."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Config, get_config
from app.core.logging import setup_logging
from app.db import create_engine, create_sessionmaker
from app.mobcash import MobCashClient
from app.payments.registry import ProviderRegistry, build_registry
from app.services.admins import AdminService
from app.services.container import Services
from app.services.integrations import apply_runtime_integrations
from app.services.settings import SettingsService

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    config: Config
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    providers: ProviderRegistry
    bot: Bot | None
    mobcash: MobCashClient | None = None
    refresh_task: asyncio.Task[None] | None = None
    mobcash_warned: bool = False

    def services(self, session: AsyncSession) -> Services:
        return Services(
            session=session,
            redis=self.redis,
            providers=self.providers,
            config=self.config,
            bot=self.bot,
            mobcash=self.mobcash,
        )


def create_bot(config: Config) -> Bot:
    token = config.bot_token.get_secret_value()
    if not token:
        raise RuntimeError("BOT_TOKEN ko‘rsatilmagan (.env)")
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_redis(url: str) -> Redis:
    """`memory://` — faqat lokal sinov uchun xotiradagi Redis (bitta jarayon, fakeredis)."""
    if url.startswith("memory://"):
        import fakeredis

        log.warning("REDIS_URL=memory:// — xotiradagi Redis. Productionda ishlatmang!")
        return fakeredis.FakeAsyncRedis()
    return Redis.from_url(url)


async def create_context(*, with_bot: bool = True, sync_admins: bool = True) -> AppContext:
    config = get_config()
    setup_logging(config.log_level, config.log_json)
    redis = create_redis(config.redis_url)
    providers = build_registry(config, redis)
    engine = create_engine(config.database_url)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        rt = await SettingsService(session, redis, config, providers).snapshot()
    if rt.payment_mode == "production" and providers.has_sandbox(rt.enabled_providers):
        raise RuntimeError(
            "To‘lov rejimi production, lekin sandbox provayder faol. Sandbox real pul "
            "harakatlantirmaydi — admin panelda «Faol provayderlar»dan uni olib tashlang."
        )
    bot = create_bot(config) if with_bot else None
    mobcash = MobCashClient.from_config(config, redis)
    ctx = AppContext(config, engine, sessionmaker, redis, providers, bot, mobcash)
    if sync_admins:
        async with sessionmaker() as session:
            await AdminService(session).sync_from_env(config.admin_roles)
    await _apply_integrations(ctx)
    if bot is not None and not config.bot_username:
        me = await bot.me()
        config.bot_username = me.username or ""
    ctx.refresh_task = asyncio.create_task(_integrations_loop(ctx))
    log.info(
        "Kontekst tayyor: registry=%s enabled=%s mode=%s",
        providers.codes,
        rt.enabled_providers,
        rt.payment_mode,
    )
    return ctx


async def _apply_integrations(ctx: AppContext) -> None:
    async with ctx.sessionmaker() as session:
        try:
            await apply_runtime_integrations(ctx.services(session))
        except Exception:
            log.warning("Integratsiyalarni qo‘llab bo‘lmadi", exc_info=True)
    if ctx.mobcash is not None:
        if not ctx.mobcash.configured:
            if not ctx.mobcash_warned:
                log.warning(
                    "Mob-Cash hali sozlanmagan — admin panelda «🏦 Mob-Cash → 🔌 Kassa ulash» "
                    "orqali ulang"
                )
                ctx.mobcash_warned = True
        elif ctx.mobcash_warned:
            log.info("Mob-Cash sozlamalari kiritildi — kassa ulanishi tayyor")
            ctx.mobcash_warned = False


async def _integrations_loop(ctx: AppContext) -> None:
    """Boshqa jarayonda o‘zgargan sozlamalar 60 sekund ichida klientlarga yetib boradi."""
    while True:
        await asyncio.sleep(60)
        try:
            await _apply_integrations(ctx)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Integratsiya yangilash xatosi", exc_info=True)


async def close_context(ctx: AppContext) -> None:
    if ctx.refresh_task is not None:
        ctx.refresh_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ctx.refresh_task
        ctx.refresh_task = None
    if ctx.bot is not None:
        await ctx.bot.session.close()
    if ctx.mobcash is not None:
        await ctx.mobcash.close()
    await ctx.providers.close()
    await ctx.redis.aclose()
    await ctx.engine.dispose()
