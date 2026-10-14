"""Background worker: `python -m app.jobs`.

Har bir vazifa Redis lock bilan himoyalangan — bir nechta worker replika bo‘lsa ham
bir vaqtda faqat bittasi bajaradi.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.bootstrap import AppContext, close_context, create_context
from app.jobs import tasks

log = logging.getLogger("app.jobs")


@dataclass(slots=True)
class Job:
    name: str
    interval: int
    func: Callable[[AppContext], Awaitable[int]]
    next_run: float = 0.0


JOBS: tuple[Job, ...] = (
    Job("process_payouts", 10, tasks.process_payouts),
    Job("poll_payouts", 15, tasks.poll_payouts),
    Job("expire_payments", 30, tasks.expire_payments),
    Job("expire_p2p", 30, tasks.expire_p2p),
    Job("credit_p2p", 30, tasks.credit_p2p),
    Job("userbot_watchdog", 60, tasks.userbot_watchdog),
    Job("reconcile_payments", 120, tasks.reconcile_payments),
    Job("provider_health", 60, tasks.provider_health),
    Job("refresh_channels", 1800, tasks.refresh_channels),
    Job("daily_report", 300, tasks.daily_report),
)


async def run_job(ctx: AppContext, job: Job) -> None:
    lock_key = f"lock:job:{job.name}"
    if not await ctx.redis.set(lock_key, "1", nx=True, ex=max(job.interval * 3, 120)):
        return
    started = time.monotonic()
    try:
        processed = await job.func(ctx)
        if processed:
            log.info("%s: %s ta yozuv (%.2fs)", job.name, processed, time.monotonic() - started)
    except Exception:
        log.exception("Vazifa xatosi: %s", job.name)
    finally:
        await ctx.redis.delete(lock_key)


async def main() -> None:
    ctx = await create_context(sync_admins=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    log.info("Worker ishga tushdi: %s", ", ".join(j.name for j in JOBS))
    try:
        while not stop.is_set():
            now = time.monotonic()
            for job in JOBS:
                if now >= job.next_run:
                    job.next_run = now + job.interval
                    await run_job(ctx, job)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=1.0)
    finally:
        await close_context(ctx)
