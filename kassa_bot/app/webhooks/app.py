"""FastAPI xizmati: provayder webhooklari, Telegram webhook (ixtiyoriy), sandbox sahifalari."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from aiogram import Dispatcher
from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.bootstrap import AppContext, close_context, create_context
from app.bot.factory import create_dispatcher
from app.core.utils import hmac_equal
from app.payments.base import WebhookVerificationError
from app.webapp.api import ApiError, api_error_handler
from app.webapp.api import router as webapp_router
from app.webapp.telegram import setup_menu_button
from app.webhooks.kassa_api import router as kassa_api_router
from app.webhooks.processor import notify_result, process_provider_event
from app.webhooks.sandbox import router as sandbox_router

log = logging.getLogger(__name__)
MAX_WEBHOOK_BODY = 64 * 1024
TELEGRAM_WEBHOOK_PATH = "/telegram/webhook"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx = await create_context()
    app.state.ctx = ctx
    app.state.dp = None
    if ctx.config.bot_mode == "webhook" and ctx.bot is not None:
        dp = create_dispatcher(ctx)
        app.state.dp = dp
        url = ctx.config.public_base_url.rstrip("/") + TELEGRAM_WEBHOOK_PATH
        await ctx.bot.set_webhook(
            url=url,
            secret_token=ctx.config.telegram_webhook_secret.get_secret_value() or None,
            allowed_updates=dp.resolve_used_update_types(),
        )
        log.info("Telegram webhook o‘rnatildi")
        async with ctx.sessionmaker() as session:
            rt = await ctx.services(session).settings.snapshot()
        await setup_menu_button(ctx.bot, ctx.config, rt.webapp_enabled)
    try:
        yield
    finally:
        await close_context(ctx)


app = FastAPI(
    title="Kassa API",
    version="1.0.0",
    description="To‘lov provayderi webhooklari va xizmat endpointlari",
    lifespan=lifespan,
)
app.include_router(sandbox_router)
app.include_router(kassa_api_router)
app.include_router(webapp_router)
app.add_exception_handler(ApiError, api_error_handler)
WEBAPP_STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"
app.mount("/webapp", StaticFiles(directory=WEBAPP_STATIC, html=True), name="webapp")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/webapp/")


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


@app.get("/health", tags=["system"])
async def health(request: Request) -> JSONResponse:
    ctx = get_ctx(request)
    status: dict[str, Any] = {"db": False, "redis": False}
    try:
        async with ctx.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
            status["mode"] = (await ctx.services(session).settings.snapshot()).payment_mode
        status["db"] = True
    except Exception:
        log.warning("DB health xatosi", exc_info=True)
    try:
        status["redis"] = bool(await ctx.redis.ping())
    except Exception:
        log.warning("Redis health xatosi", exc_info=True)
    ok = status["db"] and status["redis"]
    status["status"] = "ok" if ok else "degraded"
    return JSONResponse(status, status_code=200 if ok else 503)


@app.post("/webhooks/payments/{provider_code}", tags=["payments"])
async def payment_webhook(provider_code: str, request: Request) -> dict[str, str]:
    """Provayder webhooki: imzo tekshiruvi → idempotent qayta ishlash → bildirishnoma."""
    ctx = get_ctx(request)
    provider = ctx.providers.find(provider_code)
    if provider is None:
        raise HTTPException(status_code=404, detail="unknown provider")
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY:
        raise HTTPException(status_code=413, detail="payload too large")
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        event = provider.verify_webhook(headers, body)
    except WebhookVerificationError as exc:
        log.warning("Webhook rad etildi provider=%s: %s", provider_code, exc)
        raise HTTPException(status_code=401, detail="invalid signature") from exc
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        result = await process_provider_event(svc, provider_code, event)
        await notify_result(svc, result)
    return {"status": result.status}


@app.post(TELEGRAM_WEBHOOK_PATH, tags=["telegram"], include_in_schema=False)
async def telegram_webhook(request: Request) -> dict[str, bool]:
    ctx = get_ctx(request)
    dp: Dispatcher | None = request.app.state.dp
    if dp is None or ctx.bot is None:
        raise HTTPException(status_code=404)
    expected = ctx.config.telegram_webhook_secret.get_secret_value()
    received = request.headers.get("x-telegram-bot-api-secret-token", "")
    if expected and not hmac_equal(expected, received):
        raise HTTPException(status_code=403)
    update = Update.model_validate(await request.json(), context={"bot": ctx.bot})
    await dp.feed_update(ctx.bot, update)
    return {"ok": True}
