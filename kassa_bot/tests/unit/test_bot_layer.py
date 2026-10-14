"""Klaviaturalar, rate limit va API endpointlarining DBsiz qismlari."""

from __future__ import annotations

from types import SimpleNamespace

from aiogram.types import InlineKeyboardMarkup
from fastapi.testclient import TestClient

from app import texts
from app.bot.keyboards.callbacks import AdmCb
from app.bot.keyboards.user import bonus_kb, main_menu_kb, wallet_kb
from app.bot.middlewares import ThrottlingMiddleware
from app.payments.registry import ProviderRegistry


def _texts(markup: InlineKeyboardMarkup) -> list[str]:
    return [b.text for row in markup.inline_keyboard for b in row]


def test_main_menu_order() -> None:
    rows = [[b.text for b in row] for row in main_menu_kb().keyboard]
    assert rows == [
        ["➕ Hisob to‘ldirish", "➖ Pul chiqarish"],
        ["💠 Hamyon", "👨‍💻 Aloqa"],
        ["🎁 Bonus", "🌐 Kassa manzili"],
    ]


def test_wallet_and_bonus_buttons() -> None:
    wallet = _texts(wallet_kb())
    for label in (
        "📥 Hisob to‘ldirish",
        "➕ Hamyonni to‘ldirish",
        "📤 Kartaga yechish",
        "🔙 Orqaga",
    ):
        assert label in wallet
    assert _texts(bonus_kb())[:3] == ["🎟 Promokod", "🏆 VIP hisob", "🤝 Referal"]


def test_admin_menu_sections() -> None:
    sections = [t for row in texts.ADMIN_MENU_ROWS for t in row]
    for name in (
        "📊 Statistika & Hisobot",
        "👥 Foydalanuvchilar & Boshqaruv",
        "⚙️ Tizim Sozlamalari",
        "📦 Ommaviy to‘lov",
        "🤖 Avto to‘lov",
        "💸 Ruchnoy yechish",
        "📋 Join Requestlar",
        "🎁 Bonus tizimi",
        "📢 Majburiy Obuna Kanallari",
    ):
        assert name in sections


def test_callback_data_fits_telegram_limit() -> None:
    packed = AdmCb(section="s", action="edit", id=2**40, page=999, arg="max_bonus_per_deposit")
    assert len(packed.pack().encode()) <= 64


async def test_throttling(redis, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Vaqt qotiriladi: aks holda chaqiruvlar soniya chegarasiga tushsa test tasodifan yiqiladi.
    monkeypatch.setattr("app.bot.middlewares.time.time", lambda: 1_700_000_000.5)
    mw = ThrottlingMiddleware(redis, per_second=3, per_minute=100)
    results = [await mw.is_limited(42) for _ in range(5)]
    assert results[:3] == [False, False, False]
    assert results[3] is True
    assert await mw.is_limited(43) is False


def _client(registry: ProviderRegistry) -> TestClient:
    from app.webhooks.app import app

    app.state.ctx = SimpleNamespace(providers=registry)
    app.state.dp = None
    return TestClient(app)  # lifespan ishlatilmaydi — DB kerak emas


def test_webhook_rejects_unknown_provider_and_bad_signature(registry: ProviderRegistry) -> None:
    client = _client(registry)
    assert client.post("/webhooks/payments/unknown", content=b"{}").status_code == 404
    resp = client.post(
        "/webhooks/payments/sandbox",
        content=b'{"event_id":"1"}',
        headers={"x-sandbox-signature": "bad", "x-sandbox-timestamp": "1"},
    )
    assert resp.status_code == 401
    big = client.post("/webhooks/payments/sandbox", content=b"x" * (70 * 1024))
    assert big.status_code == 413


def test_sandbox_page_requires_token(registry: ProviderRegistry) -> None:
    client = _client(registry)
    assert client.get("/sandbox/checkout/abc?t=wrong").status_code == 403
    assert client.get("/sandbox/cards/abc?t=wrong").status_code == 403
    assert client.post("/sandbox/checkout/abc/pay", content=b"t=wrong").status_code == 403
