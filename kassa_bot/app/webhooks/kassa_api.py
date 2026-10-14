"""REST API: kassani ulash va pul operatsiyalari (botdan tashqari tizimlar uchun).

Sarlavha `X-Token: <API_TOKEN>` bo'lishi shart (API_TOKEN .env'da; bo'sh bo'lsa API o'chiq).
Format: `kassa_kodi | login | parol` (Mob-Cash), `kassa_kodi | kassir paroli | hash` (Cashdesk)
yoki `agent: login | parol | kassa_kodi` (TeamCash).

Depozit va yechish barcha gateway'larda ishlaydi. Cashdesk (1xBet) kassalarida kod bo'yicha
summani oldindan ko'rish yo'q — shuning uchun `/yechish` da `summa` majburiy bo'ladi.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from app.bootstrap import AppContext
from app.core.errors import DomainError, NotFoundError
from app.core.utils import hmac_equal
from app.mobcash import MobCashError
from app.services.audit import Actor
from app.services.bookmakers import BookmakerService
from app.services.settings import SettingsService

router = APIRouter(prefix="/api/kassa", tags=["kassa"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.ctx


async def _svc(
    request: Request, x_token: str = Header(default="")
) -> AsyncIterator[BookmakerService]:
    ctx = _ctx(request)
    expected = ctx.config.api_token.get_secret_value()
    if not expected:
        raise HTTPException(status_code=503, detail="API_TOKEN sozlanmagan — .env ga qo'shing")
    if not x_token or not hmac_equal(expected, x_token):
        raise HTTPException(status_code=401, detail="Noto'g'ri token (X-Token sarlavhasi)")
    async with ctx.sessionmaker() as session:
        settings = SettingsService(session, ctx.redis, ctx.config, ctx.providers)
        yield BookmakerService(session, ctx.redis, ctx.config, settings, ctx.mobcash)


def _money(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


class UlashBody(BaseModel):
    nom: str
    kassa: str


class KassaIdBody(BaseModel):
    kassa_id: int | None = None


class DepozitBody(KassaIdBody):
    payer_id: str
    summa: Decimal


class YechishBody(KassaIdBody):
    payer_id: str
    kod: str
    summa: Decimal | None = None  # Cashdesk kassalarida majburiy (preview yo'q)


def _bad(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(getattr(exc, "message", exc)))


@router.post("/ulash")
async def ulash(
    body: UlashBody, svc: BookmakerService = Depends(_svc)
) -> dict:
    """Yangi kassa ulash: nom + `kassa_kodi | login | parol` (yoki `kodi | parol | hash`)."""
    try:
        bm = await svc.create(body.nom, body.kassa, Actor.system())
        info = await (await svc.client(bm.id)).check_connection()
    except NotFoundError as exc:
        raise _bad(exc, 404) from exc
    except DomainError as exc:
        raise _bad(exc) from exc
    except MobCashError as exc:
        raise _bad(exc, 502) from exc
    return {
        "ok": True,
        "id": bm.id,
        "nom": bm.name,
        "tur": bm.gateway,
        "kassa_kodi": bm.cashbox_code,
        "login": bm.login or None,
        "valyuta": bm.currency,
        "balans": _money(info.balance),
        "limit": _money(info.limit),
    }


@router.get("/royxat")
async def royxat(svc: BookmakerService = Depends(_svc)) -> dict:
    try:
        items = await svc.list_all()
    except NotFoundError as exc:
        raise _bad(exc, 404) from exc
    except DomainError as exc:
        raise _bad(exc) from exc
    return {
        "ok": True,
        "kassalar": [
            {
                "id": bm.id,
                "nom": bm.name,
                "tur": bm.gateway,
                "kassa_kodi": bm.cashbox_code,
                "login": bm.login or None,
                "valyuta": bm.currency,
                "faol": bm.is_active,
            }
            for bm in items
        ],
    }


@router.post("/balans")
async def balans(
    body: KassaIdBody, svc: BookmakerService = Depends(_svc)
) -> dict:
    """Jonli balans: {"balans": "...", "limit": "..."} (string — aniqligi saqlanadi)."""
    try:
        client = await svc.client(body.kassa_id)
        info = await client.check_connection()
    except NotFoundError as exc:
        raise _bad(exc, 404) from exc
    except DomainError as exc:
        raise _bad(exc) from exc
    except MobCashError as exc:
        raise _bad(exc, 502) from exc
    return {
        "ok": True,
        "kassa": info.code,
        "valyuta": info.currency_id,
        "balans": _money(info.balance),
        "limit": _money(info.limit),
    }


@router.post("/depozit")
async def depozit(
    body: DepozitBody, svc: BookmakerService = Depends(_svc)
) -> dict:
    """Pul kiritish: avval oluvchi tekshiriladi, keyin yuboriladi."""
    try:
        client = await svc.money_client(body.kassa_id)
        nickname = await client.payer_nickname(body.payer_id)
        result = await client.deposit(body.payer_id, body.summa)
    except NotFoundError as exc:
        raise _bad(exc, 404) from exc
    except DomainError as exc:
        raise _bad(exc) from exc
    except MobCashError as exc:
        raise _bad(exc, 502) from exc
    return {"ok": True, "oluvchi": nickname, "summa": _money(body.summa), "natija": result}


@router.post("/yechish")
async def yechish(
    body: YechishBody, svc: BookmakerService = Depends(_svc)
) -> dict:
    """Pul yechish: kod bo'yicha summa olinib, yechiladi.

    Cashdesk (1xBet) kassalarida preview yo'q — so'rovda `summa` ko'rsatilishi shart;
    haqiqiy summa baribir Payout javobidan olinadi ("natija.amount")."""
    try:
        client = await svc.money_client(body.kassa_id)
        if getattr(client, "supports_amount_preview", True):
            amount = await client.get_withdrawal_amount(body.payer_id, body.kod)
        else:
            if body.summa is None:
                raise HTTPException(
                    status_code=400,
                    detail="Bu kassa (1xBet Cashdesk) kod summasini oldindan ko'rsatmaydi — "
                    "so'rovda 'summa' maydonini ham yuboring.",
                )
            amount = body.summa
        result = await client.withdrawal(body.payer_id, body.kod, amount)
    except NotFoundError as exc:
        raise _bad(exc, 404) from exc
    except DomainError as exc:
        raise _bad(exc) from exc
    except MobCashError as exc:
        raise _bad(exc, 502) from exc
    return {"ok": True, "summa": _money(amount), "natija": result}
