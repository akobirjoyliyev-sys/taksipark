"""Sandbox checkout va karta ulash sahifalari (faqat test rejimi, real pul yo‘q).

Sahifa tugmasi bosilganda imzolangan webhook yaratiladi va xuddi haqiqiy provayder
webhooki kabi `verify_webhook` → `process_provider_event` yo‘lidan o‘tadi.
"""

from __future__ import annotations

import html
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.core.money import fmt_money
from app.payments.sandbox import TEST_CARDS, SandboxProvider
from app.webhooks.processor import notify_result, process_provider_event

router = APIRouter(prefix="/sandbox", tags=["sandbox"], include_in_schema=False)

_PAGE = """<!doctype html><html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kassa — Sandbox</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f4f6fb;margin:0;padding:24px;color:#1b2333}}
.card{{max-width:420px;margin:0 auto;background:#fff;border-radius:16px;padding:24px;
box-shadow:0 8px 24px rgba(20,30,60,.08)}}
.badge{{display:inline-block;background:#fff3cd;color:#7a5b00;border-radius:8px;padding:4px 10px;
font-size:13px}}
h1{{font-size:22px;margin:12px 0}} .amount{{font-size:32px;font-weight:700;margin:12px 0}}
button{{width:100%;padding:14px;border:0;border-radius:12px;font-size:16px;margin-top:10px;
cursor:pointer}}
.ok{{background:#1f7a4d;color:#fff}} .no{{background:#e9ecf3;color:#1b2333}}
.muted{{color:#69728a;font-size:13px;margin-top:16px}}
</style></head><body><div class="card">
<span class="badge">🧪 SANDBOX — real pul yechilmaydi</span>{body}</div></body></html>"""


def _provider(request: Request) -> SandboxProvider:
    provider = request.app.state.ctx.providers.find(SandboxProvider.code)
    if not isinstance(provider, SandboxProvider):
        raise HTTPException(status_code=404)
    return provider


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(body=body), status_code=status)


async def _form(request: Request) -> dict[str, str]:
    raw = (await request.body())[:4096].decode("utf-8", "ignore")
    return {k: v[0] for k, v in parse_qs(raw).items()}


async def _deliver(request: Request, provider: SandboxProvider, payload: dict) -> str:
    headers, body = provider.build_webhook(payload)
    event = provider.verify_webhook(headers, body)
    ctx = request.app.state.ctx
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        result = await process_provider_event(svc, provider.code, event)
        await notify_result(svc, result)
    return result.status


@router.get("/checkout/{reference}", response_class=HTMLResponse)
async def checkout_page(reference: str, request: Request, t: str = "") -> HTMLResponse:
    provider = _provider(request)
    if not provider.check_page_token("pay", reference, t):
        return _page("<h1>Havola yaroqsiz</h1>", 403)
    state = await provider.get_payment(reference)
    if not state:
        return _page("<h1>To‘lov topilmadi</h1>", 404)
    if state.get("status") != "pending":
        return _page(f"<h1>To‘lov yakunlangan</h1><p>Holat: {html.escape(state['status'])}</p>")
    amount = fmt_money(state["amount"])  # type: ignore[arg-type]
    ref = html.escape(reference)
    token = html.escape(t)
    body = f"""
<h1>Hisobni to‘ldirish</h1><div class="amount">{amount}</div>
<form method="post" action="/sandbox/checkout/{ref}/pay">
<input type="hidden" name="t" value="{token}">
<button class="ok" type="submit">✅ To‘lash (test)</button></form>
<form method="post" action="/sandbox/checkout/{ref}/fail">
<input type="hidden" name="t" value="{token}">
<button class="no" type="submit">❌ Rad etish (test)</button></form>
<p class="muted">Bu sahifa faqat sinov uchun. Haqiqiy provayder ulanganda foydalanuvchi
rasmiy to‘lov sahifasiga yo‘naltiriladi.</p>"""
    return _page(body)


@router.post("/checkout/{reference}/{action}", response_class=HTMLResponse)
async def checkout_action(reference: str, action: str, request: Request) -> HTMLResponse:
    provider = _provider(request)
    form = await _form(request)
    if action not in {"pay", "fail"} or not provider.check_page_token(
        "pay", reference, form.get("t", "")
    ):
        return _page("<h1>Havola yaroqsiz</h1>", 403)
    payload = await provider.complete_payment(reference, success=action == "pay")
    if payload is None:
        return _page("<h1>To‘lov allaqachon yakunlangan</h1>")
    await _deliver(request, provider, payload)
    title = {
        "paid": "✅ To‘lov qabul qilindi",
        "failed": "❌ To‘lov rad etildi",
        "expired": "⌛ To‘lov muddati tugagan",
    }.get(payload["status"], payload["status"])
    return _page(f"<h1>{title}</h1><p>Telegram botga qaytishingiz mumkin.</p>")


@router.get("/cards/{reference}", response_class=HTMLResponse)
async def cards_page(reference: str, request: Request, t: str = "") -> HTMLResponse:
    provider = _provider(request)
    if not provider.check_page_token("bind", reference, t):
        return _page("<h1>Havola yaroqsiz</h1>", 403)
    ref, token = html.escape(reference), html.escape(t)
    buttons = "".join(f"""<form method="post" action="/sandbox/cards/{ref}/select">
<input type="hidden" name="t" value="{token}"><input type="hidden" name="card" value="{key}">
<button class="{'no' if key == 'decline' else 'ok'}" type="submit">💳 {mask} — {html.escape(desc)}
</button></form>""" for key, mask, desc in TEST_CARDS)
    body = f"""<h1>Kartani ulash</h1>
<p>Haqiqiy provayderda bu yerda karta ma’lumotlari provayderning xavfsiz formasida kiritiladi
va botga faqat token hamda maskalangan raqam qaytadi. Sandboxda test kartani tanlang:</p>
{buttons}"""
    return _page(body)


@router.post("/cards/{reference}/select", response_class=HTMLResponse)
async def cards_select(reference: str, request: Request) -> HTMLResponse:
    provider = _provider(request)
    form = await _form(request)
    if not provider.check_page_token("bind", reference, form.get("t", "")):
        return _page("<h1>Havola yaroqsiz</h1>", 403)
    payload = await provider.complete_card_binding(reference, form.get("card", ""))
    if payload is None:
        return _page("<h1>Havola eskirgan yoki allaqachon ishlatilgan</h1>", 410)
    await _deliver(request, provider, payload)
    return _page(
        f"<h1>✅ Karta ulandi</h1><p>{html.escape(payload['card_mask'])}</p>"
        "<p>Telegram botga qaytishingiz mumkin.</p>"
    )
