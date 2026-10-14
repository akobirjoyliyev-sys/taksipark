"""Lokal sinov: bot (polling) + API (sandbox sahifalari) + worker + userbot — bitta jarayonda.

`REDIS_URL=memory://` bilan Redis'siz ishlaydi (lock va token keshi jarayon ichida umumiy
bo‘lishi uchun hammasi bitta jarayonda). Productionda Docker Compose ishlating.

    python scripts/run_local.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import uvicorn

from app.bootstrap import close_context, create_context
from app.bot.factory import create_dispatcher
from app.jobs.worker import JOBS, run_job
from app.userbot.runner import UserbotRunner
from app.webhooks.app import app

log = logging.getLogger("run_local")


async def worker_loop(ctx) -> None:  # type: ignore[no-untyped-def]
    while True:
        now = time.monotonic()
        for job in JOBS:
            if now >= job.next_run:
                job.next_run = now + job.interval
                await run_job(ctx, job)
        await asyncio.sleep(1)


async def main() -> None:
    ctx = await create_context()
    assert ctx.bot is not None  # noqa: S101
    app.state.ctx = ctx
    app.state.dp = None
    dp = create_dispatcher(ctx)
    api_port = int(os.environ.get("API_PORT", "8000"))
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, lifespan="off", log_level="warning")
    )
    await ctx.bot.delete_webhook(drop_pending_updates=False)
    me = await ctx.bot.me()
    log.info("Bot @%s ishga tushdi. API: http://127.0.0.1:%s", me.username, api_port)
    userbot_stop = asyncio.Event()
    tasks = [
        asyncio.create_task(server.serve()),
        asyncio.create_task(worker_loop(ctx)),
        asyncio.create_task(UserbotRunner(ctx).run(userbot_stop)),
    ]
    try:
        await dp.start_polling(ctx.bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        server.should_exit = True
        userbot_stop.set()
        for task in tasks:
            task.cancel()
        await close_context(ctx)


if __name__ == "__main__":
    asyncio.run(main())
