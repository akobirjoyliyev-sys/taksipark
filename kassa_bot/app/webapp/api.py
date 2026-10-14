"""Web App JSON API: `/api/webapp/*`.

Har bir so‘rov `X-Telegram-Init-Data` sarlavhasi bilan keladi (Telegram imzolagan initData).
Biznes mantiq bot bilan bir xil servislar orqali ishlaydi — limitlar, noyob summa, Mob-Cash
xavfsizlik qoidalari va audit o‘zgarmaydi.
"""

from __future__ import annotations

import functools
import html
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import texts
from app.bot.middlewares import ThrottlingMiddleware
from app.core.enums import P2PDepositTarget, PromoType
from app.core.errors import DomainError
from app.core.money import fmt_money, percent_of
from app.core.permissions import Perm
from app.models import Admin, MobcashWithdrawal, P2PDeposit, User
from app.services.container import Services
from app.services.mobcash_withdrawals import mask_card
from app.services.settings import RuntimeSettings
from app.webapp.auth import InitDataError, validate_init_data

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webapp", tags=["webapp"])

PAYER_RE = re.compile(r"^\d{5,15}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{4,64}$")
_TAGS = re.compile(r"<[^>]+>")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}


def plain(message: str) -> str:
    """Bot matnlaridagi HTML teglarni olib tashlaydi — UI matnni textContent bilan ko‘rsatadi."""
    return html.unescape(_TAGS.sub("", message)).strip()


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)  # noqa: S101
    return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)


@dataclass(slots=True)
class WebCtx:
    svc: Services
    user: User
    admin: Admin | None
    rt: RuntimeSettings


async def web_ctx(request: Request) -> AsyncIterator[WebCtx]:
    ctx = request.app.state.ctx
    token = ctx.config.bot_token.get_secret_value()
    try:
        tg = validate_init_data(request.headers.get("x-telegram-init-data", ""), token)
    except InitDataError as exc:
        raise ApiError(
            f"Avtorizatsiya xatosi: {exc}. Ilovani bot orqali qayta oching.", 401
        ) from exc
    limiter = ThrottlingMiddleware(
        ctx.redis, ctx.config.rate_limit_per_second * 2, ctx.config.rate_limit_per_minute * 2
    )
    try:
        limited = await limiter.is_limited(tg.id)
    except Exception:  # Redis ishlamasa — bloklamaymiz
        limited = False
    if limited:
        raise ApiError(plain(texts.FLOOD), 429)
    async with ctx.sessionmaker() as session:
        svc: Services = ctx.services(session)
        user, _ = await svc.users.get_or_create(tg)  # type: ignore[arg-type]
        admin = await svc.admins.get_active(tg.id)
        rt = await svc.settings.snapshot()
        if admin is None:
            if not rt.webapp_enabled:
                raise ApiError("Web App vaqtincha o‘chirilgan. Botdan foydalaning.", 403)
            if user.is_banned:
                raise ApiError(plain(texts.BANNED), 403)
            if rt.maintenance:
                raise ApiError(plain(texts.MAINTENANCE), 503)
        yield WebCtx(svc, user, admin, rt)


async def gate(w: WebCtx) -> dict[str, Any] | None:
    """Kontakt / majburiy obuna — bot bilan bir xil talablar (adminlarga emas)."""
    if w.admin is not None:
        return None
    if w.rt.contact_required and not w.user.contact_verified:
        return {"type": "contact", "message": "Avval botda telefon raqamingizni yuboring."}
    if w.rt.subscription_enabled:
        missing = await w.svc.subscription.missing_channels(w.user.telegram_id)
        if missing:
            return {
                "type": "subscription",
                "message": plain(texts.SUB_REQUIRED),
                "channels": [
                    {"title": c.title, "url": c.invite_link or f"https://t.me/{c.username}"}
                    for c in missing
                ],
            }
    return None


async def require_open(w: WebCtx) -> None:
    g = await gate(w)
    if g is not None:
        raise ApiError(g["message"], 403, {"gate": g})


def money(value: Decimal | int | None) -> str:
    return str(Decimal(value or 0).quantize(Decimal("0.01")))


def call(fn: Any) -> Any:
    """DomainError → foydalanuvchiga tushunarli 400 javob."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except DomainError as exc:
            raise ApiError(plain(exc.message)) from exc

    return wrapper


# =========================================================================== DTO
async def deposit_dto(w: WebCtx, d: P2PDeposit) -> dict[str, Any]:
    card = await w.svc.p2p.card_for(d)
    credit = d.credit_amount or (
        d.unique_amount - percent_of(d.unique_amount, w.rt.deposit_fee_percent)
    )
    return {
        "id": d.id,
        "target": d.target.value,
        "bookmaker": (
            await w.svc.bookmakers.name_of(d.bookmaker_id)
            if d.target == P2PDepositTarget.GAME
            else None
        ),
        "payer_id": d.payer_id or None,
        "nickname": d.payer_nickname,
        "amount": money(d.unique_amount),
        "amount_text": fmt_money(d.unique_amount),
        "credit_text": fmt_money(credit),
        "card": (
            {"number": card.pretty, "raw": card.number, "holder": card.holder, "bank": card.bank}
            if card
            else None
        ),
        "status": d.status.value,
        "status_text": texts.mc_status(d.target, d.status),
        "expires_at": d.expires_at.isoformat(),
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def withdrawal_dto(w: WebCtx, wd: MobcashWithdrawal) -> dict[str, Any]:
    return {
        "id": wd.id,
        "bookmaker": await w.svc.bookmakers.name_of(wd.bookmaker_id),
        "payer_id": wd.payer_id,
        "amount_text": fmt_money(wd.amount),
        "fee_text": fmt_money(wd.fee),
        "payout_text": fmt_money(wd.payout_amount),
        "card": mask_card(wd.card_number),
        "status": wd.status.value,
        "status_text": texts.MC_WD_STATUS[wd.status],
        "created_at": wd.created_at.isoformat() if wd.created_at else None,
    }


async def bookmakers_dto(w: WebCtx) -> list[dict[str, Any]]:
    items = [
        {"id": bm.id, "name": bm.name, "payer_id": w.user.payer_id_for(bm.id)}
        for bm in await w.svc.bookmakers.list_active()
    ]
    if not items and await w.svc.bookmakers.legacy_available():
        items = [{"id": None, "name": "Mob-Cash", "payer_id": w.user.payer_id_for(None)}]
    return items


# =========================================================================== endpointlar
@router.get("/me")
async def me(w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    rt = w.rt
    wallet = await w.svc.users.get_wallet(w.user.id)
    vip = None
    if rt.vip_section_enabled:
        progress = await w.svc.vip.progress(wallet.total_deposit)
        vip = {
            "level": progress.current.name if progress.current else None,
            "percent": str(progress.current.bonus_percent) if progress.current else "0",
            "next": progress.next.name if progress.next else None,
            "left_text": fmt_money(progress.left) if progress.next else None,
            "progress": progress.percent,
            "levels": [
                {
                    "name": lv.name,
                    "from_text": fmt_money(lv.min_total_deposit),
                    "percent": str(lv.bonus_percent),
                    "current": bool(progress.current and progress.current.id == lv.id),
                }
                for lv in await w.svc.vip.levels()
            ],
        }
    referral = None
    if rt.referral_enabled:
        stats = await w.svc.referral.stats(w.user)
        referral = {
            "link": stats.link,
            "percent": str(stats.percent),
            "count": stats.count,
            "earned_text": fmt_money(stats.earned),
        }
    pending = [
        await deposit_dto(w, d)
        for target in (P2PDepositTarget.GAME, P2PDepositTarget.WALLET)
        if (d := await w.svc.p2p.pending_for_user(w.user, target)) is not None
    ]
    return {
        "user": {
            "first_name": w.user.first_name or "",
            "username": w.user.username,
            "is_admin": w.admin is not None,
        },
        "wallet": {
            "available_text": fmt_money(wallet.available),
            "bonus_text": fmt_money(wallet.bonus_balance),
            "total_deposit_text": fmt_money(wallet.total_deposit),
        },
        "vip": vip,
        "referral": referral,
        "limits": {
            "deposit_min": money(rt.deposit_min),
            "deposit_max": money(rt.deposit_max),
            "deposit_min_text": fmt_money(rt.deposit_min),
            "deposit_max_text": fmt_money(rt.deposit_max),
            "withdraw_min_text": fmt_money(rt.withdraw_min),
            "withdraw_max_text": fmt_money(rt.withdraw_max),
            "deposit_fee": str(rt.deposit_fee_percent),
            "withdraw_fee": str(rt.withdraw_fee_percent),
        },
        "mobcash_enabled": rt.mobcash_enabled,
        "bookmakers": await bookmakers_dto(w) if rt.mobcash_enabled else [],
        "saved_card": mask_card(w.user.payout_card_number) if w.user.payout_card_number else None,
        "pending": pending,
        "support_url": rt.support_url,
        "test_mode": rt.payment_mode != "production",
        "gate": await gate(w),
    }


class PayerIn(BaseModel):
    bookmaker_id: int | None = None
    payer_id: str = Field(max_length=32)


def _payer(raw: str) -> str:
    value = re.sub(r"[\s\-]", "", raw)
    if not PAYER_RE.match(value):
        raise ApiError(plain(texts.MC_ID_INVALID))
    return value


def _require_mobcash(w: WebCtx) -> None:
    if not w.rt.mobcash_enabled:
        raise ApiError("Bu bo‘lim hozir o‘chirilgan.", 403)


@router.post("/payer")
@call
async def check_payer(body: PayerIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    _require_mobcash(w)
    nickname = await w.svc.p2p.check_payer(_payer(body.payer_id), body.bookmaker_id)
    return {"nickname": nickname}


class DepositIn(PayerIn):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


@router.post("/deposits")
@call
async def create_deposit(body: DepositIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    _require_mobcash(w)
    payer = _payer(body.payer_id)
    nickname = await w.svc.p2p.check_payer(payer, body.bookmaker_id)
    deposit = await w.svc.p2p.create(
        w.user, payer, nickname, body.amount, bookmaker_id=body.bookmaker_id
    )
    return await deposit_dto(w, deposit)


class TopupIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


@router.post("/topups")
@call
async def create_topup(body: TopupIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    _require_mobcash(w)
    deposit = await w.svc.p2p.create(w.user, "", "", body.amount, target=P2PDepositTarget.WALLET)
    return await deposit_dto(w, deposit)


@router.get("/deposits/{deposit_id}")
@call
async def get_deposit(deposit_id: int, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    return await deposit_dto(w, await w.svc.p2p.get_for_user(w.user, deposit_id))


@router.post("/deposits/{deposit_id}/cancel")
@call
async def cancel_deposit(deposit_id: int, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    return await deposit_dto(w, await w.svc.p2p.cancel(w.user, deposit_id))


class QuoteIn(PayerIn):
    code: str = Field(max_length=64)


def _code(raw: str) -> str:
    code = raw.strip()
    if not CODE_RE.match(code):
        raise ApiError(plain(texts.MC_WD_CODE_INVALID))
    return code


@router.post("/withdrawals/quote")
@call
async def quote_withdrawal(body: QuoteIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    _require_mobcash(w)
    quote = await w.svc.mcwd.quote(_payer(body.payer_id), _code(body.code), body.bookmaker_id)
    return {
        "amount_text": fmt_money(quote.amount),
        "fee_text": fmt_money(quote.fee),
        "payout_text": fmt_money(quote.payout),
    }


class WithdrawIn(QuoteIn):
    card: str = Field(max_length=32)  # 16 raqam yoki "saved"


@router.post("/withdrawals")
@call
async def create_withdrawal(body: WithdrawIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    _require_mobcash(w)
    if body.card == "saved":
        card = w.user.payout_card_number
        if not card:
            raise ApiError(plain(texts.MC_WD_CARD_INVALID))
    else:
        card = re.sub(r"\D", "", body.card)
        if len(card) != 16:
            raise ApiError(plain(texts.MC_WD_CARD_INVALID))
    payer, code = _payer(body.payer_id), _code(body.code)
    # Summa mijozdan olinmaydi — Mob-Cash'dan qayta so‘raladi.
    quote = await w.svc.mcwd.quote(payer, code, body.bookmaker_id)
    wd = await w.svc.mcwd.execute(w.user, payer, code, quote, card, bookmaker_id=body.bookmaker_id)
    admins = await w.svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
    await w.svc.notifier.mcwd_new(wd, admins, await w.svc.bookmakers.name_of(wd.bookmaker_id))
    return await withdrawal_dto(w, wd)


@router.get("/history")
async def history(w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    deposits = await w.svc.p2p.list_for_user(w.user, limit=20)
    withdrawals = await w.svc.mcwd.list_for_user(w.user, limit=20)
    return {
        "deposits": [await deposit_dto(w, d) for d in deposits],
        "withdrawals": [await withdrawal_dto(w, wd) for wd in withdrawals],
    }


class PromoIn(BaseModel):
    code: str = Field(max_length=32)


@router.post("/promo")
@call
async def activate_promo(body: PromoIn, w: WebCtx = Depends(web_ctx)) -> dict[str, Any]:
    await require_open(w)
    result = await w.svc.promo.activate(w.user, body.code)
    if result.applied_now:
        return {"message": plain(texts.PROMO_APPLIED_NOW.format(amount=fmt_money(result.bonus)))}
    promo = result.promo
    value = (
        fmt_money(promo.bonus_value)
        if promo.bonus_type == PromoType.FIXED
        else f"{promo.bonus_value}%"
    )
    return {
        "message": plain(texts.PROMO_RESERVED.format(min=fmt_money(promo.min_deposit), value=value))
    }
