"""HTTP darajasida: sandbox checkout sahifasi → imzolangan webhook → balans; dublikat webhook."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from app.bootstrap import AppContext
from app.webhooks.app import app
from tests.integration.helpers import make_user, services, wallet_of

pytestmark = pytest.mark.integration


async def test_checkout_page_and_webhook(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    app.state.ctx = AppContext(config, None, sessionmaker, redis, registry, None)  # type: ignore[arg-type]
    app.state.dp = None
    transport = httpx.ASGITransport(app=app)
    async with (
        sessionmaker() as session,
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 8001)
        payment = await svc.deposits.create(user, Decimal("40000"))
        url = payment.checkout_url.replace("https://kassa.example.com", "")  # type: ignore[union-attr]
        page = await client.get(url)
        assert page.status_code == 200 and "40 000" in page.text

        token = url.split("t=")[1]
        paid = await client.post(f"/sandbox/checkout/{payment.ref}/pay", content=f"t={token}")
        assert paid.status_code == 200 and "qabul qilindi" in paid.text
        assert (await wallet_of(session, user)).available == Decimal("40000")

        # Xuddi shu hodisa provayder tomonidan qayta yuborilsa — dublikat, balans o‘zgarmaydi
        payload = {
            "event_id": "fixed-1",
            "kind": "payment",
            "reference": str(payment.ref),
            "status": "paid",
            "amount": "40000",
        }
        headers, body = sandbox.build_webhook(payload)
        first = await client.post("/webhooks/payments/sandbox", content=body, headers=headers)
        second = await client.post("/webhooks/payments/sandbox", content=body, headers=headers)
        assert first.json() == {"status": "ok"}
        assert second.json() == {"status": "duplicate"}
        assert (await wallet_of(session, user)).available == Decimal("40000")

        again = await client.post(f"/sandbox/checkout/{payment.ref}/pay", content=f"t={token}")
        assert "allaqachon" in again.text
