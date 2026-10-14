"""Botni long-polling rejimida ishga tushirish: `python -m app.bot`."""

from __future__ import annotations

import asyncio
import logging

from app.bootstrap import close_context, create_context
from app.bot.factory import create_dispatcher
from app.webapp.telegram import setup_menu_button

log = logging.getLogger("app.bot")


async def main() -> None:
    ctx = await create_context()
    try:
        if ctx.config.bot_mode == "webhook":
            log.info("BOT_MODE=webhook — yangilanishlarni API xizmati qabul qiladi. Chiqildi.")
            return
        dp = create_dispatcher(ctx)
        assert ctx.bot is not None  # noqa: S101
        await ctx.bot.delete_webhook(drop_pending_updates=False)
        async with ctx.sessionmaker() as session:
            rt = await ctx.services(session).settings.snapshot()
        await setup_menu_button(ctx.bot, ctx.config, rt.webapp_enabled)
        log.info("Polling boshlandi")
        await dp.start_polling(ctx.bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await close_context(ctx)


if __name__ == "__main__":
    asyncio.run(main())
