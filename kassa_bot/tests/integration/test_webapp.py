"""Web App API: initData avtorizatsiya → to‘ldirish → to‘lov → yechish → tarix."""

from __future__ import annotations

import json
import time
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.bootstrap import AppContext
from app.core.utils import utcnow
from app.p2p.parser import ParsedTx
from app.webapp.api import ApiError, api_error_handler
from app.webapp.api import router as webapp_router
from app.webapp.auth import sign_init_data
from tests.integration.helpers import ADMIN
from tests.integration.test_p2p import FakeMobCash

pytestmark = pytest.mark.integration
TOKEN = "123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def init_data(uid: int) -> dict[str, str]:
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": uid, "first_name": f"U{uid}"}),
    }
    return {"X-Telegram-Init-Data": sign_init_data(fields, TOKEN)}


async def test_webapp_full_flow(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    config.bot_token = SecretStr(TOKEN)
    config.mobcash_enabled = True
    config.rate_limit_per_second = 1000
    config.rate_limit_per_minute = 10000
    mobcash = FakeMobCash()
    ctx = AppContext(config, None, sessionmaker, redis, registry, None, mobcash)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(webapp_router)
    app.add_exception_handler(ApiError, api_error_handler)
    app.state.ctx = ctx
    async with sessionmaker() as s:
        await ctx.services(s).p2p.add_card("8600123456781234", "Kassir", "Uzcard", ADMIN)

    me_h, other_h = init_data(8100001), init_data(8100002)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/webapp/me")).status_code == 401
        bad = {"X-Telegram-Init-Data": me_h["X-Telegram-Init-Data"].replace("U81", "X81")}
        assert (await c.get("/api/webapp/me", headers=bad)).status_code == 401

        me = (await c.get("/api/webapp/me", headers=me_h)).json()
        assert me["mobcash_enabled"] and me["gate"] is None
        assert me["bookmakers"] == [{"id": None, "name": "Mob-Cash", "payer_id": None}]

        r = await c.post("/api/webapp/payer", json={"payer_id": "404404"}, headers=me_h)
        assert r.status_code == 400 and r.json()["error"]
        r = await c.post("/api/webapp/payer", json={"payer_id": "12"}, headers=me_h)
        assert r.status_code == 400
        assert (
            await c.post("/api/webapp/payer", json={"payer_id": "123 456"}, headers=me_h)
        ).json() == {"nickname": "nick_123456"}

        dep = (
            await c.post(
                "/api/webapp/deposits", json={"payer_id": "123456", "amount": 50000}, headers=me_h
            )
        ).json()
        assert dep["status"] == "pending" and dep["card"]["raw"] == "8600123456781234"
        assert Decimal("50001") <= Decimal(dep["amount"]) <= Decimal("50999")
        # Boshqa foydalanuvchi bu to‘lovni ko‘ra olmaydi
        assert (
            await c.get(f"/api/webapp/deposits/{dep['id']}", headers=other_h)
        ).status_code == 400
        # Ikkinchi kutilayotgan o‘yin to‘lovi ochilmaydi
        again = await c.post(
            "/api/webapp/deposits", json={"payer_id": "123456", "amount": 50000}, headers=me_h
        )
        assert again.status_code == 400

        async with sessionmaker() as s:
            svc = ctx.services(s)
            await svc.p2p.handle_bank_message(
                account_id=None,
                owner_tg_id=1,
                source_chat_id=777,
                source_name="CardXabarBot",
                message_id=91,
                text="➕",
                message_date=utcnow() + timedelta(seconds=5),
                parsed=ParsedTx(amount=Decimal(dep["amount"]), card_last4="1234"),
            )
            await svc.p2p.credit(dep["id"])
        fresh = (await c.get(f"/api/webapp/deposits/{dep['id']}", headers=me_h)).json()
        assert fresh["status"] == "credited"
        assert mobcash.deposits == [("123456", Decimal(dep["amount"]))]

        # Hamyonni to‘ldirish → bekor qilish
        top = (await c.post("/api/webapp/topups", json={"amount": 20000}, headers=me_h)).json()
        assert top["target"] == "wallet" and top["bookmaker"] is None
        cancelled = (await c.post(f"/api/webapp/deposits/{top['id']}/cancel", headers=me_h)).json()
        assert cancelled["status"] == "cancelled"

        # Yechish: summa serverda qayta so‘raladi
        q = await c.post(
            "/api/webapp/withdrawals/quote",
            json={"payer_id": "123456", "code": "Secret_1"},
            headers=me_h,
        )
        assert q.status_code == 200 and q.json()["payout_text"]
        wd = (
            await c.post(
                "/api/webapp/withdrawals",
                json={"payer_id": "123456", "code": "Secret_1", "card": "8600 1111 2222 3333"},
                headers=me_h,
            )
        ).json()
        assert wd["status"] == "awaiting_payout" and wd["card"] == "8600 **** **** 3333"
        assert mobcash.withdrawals == [("123456", "Secret_1", Decimal("100000.00"))]
        me = (await c.get("/api/webapp/me", headers=me_h)).json()
        assert me["saved_card"] == "8600 **** **** 3333"
        r = await c.post(
            "/api/webapp/withdrawals",
            json={"payer_id": "123456", "code": "Secret_2", "card": "saved"},
            headers=other_h,
        )
        assert r.status_code == 400  # boshqa foydalanuvchida saqlangan karta yo‘q

        hist = (await c.get("/api/webapp/history", headers=me_h)).json()
        assert {d["id"] for d in hist["deposits"]} == {dep["id"], top["id"]}
        assert [w["id"] for w in hist["withdrawals"]] == [wd["id"]]

        promo = await c.post("/api/webapp/promo", json={"code": "YOQKOD"}, headers=me_h)
        assert promo.status_code == 400 and promo.json()["error"]
