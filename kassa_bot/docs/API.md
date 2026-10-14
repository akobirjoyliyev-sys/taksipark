# Kassa API

FastAPI xizmati (`app/webhooks/app.py`). Interaktiv sxema: `GET /docs` (OpenAPI).

## `GET /health`

DB va Redis holati. `200` — hammasi ishlayapti, `503` — biror xizmat ishlamayapti.

```json
{"db": true, "redis": true, "status": "ok", "mode": "test"}
```

## `POST /webhooks/payments/{provider}`

To‘lov provayderi webhooki. Qayta ishlash tartibi:

1. `provider` ulanganmi (`404` — yo‘q).
2. Tana hajmi ≤ 64 KB (`413`).
3. `provider.verify_webhook(headers, body)` — imzo/format (`401 invalid signature`).
4. Bitta DB tranzaksiyasida: `webhook_events`ga `(provider, event_id)` yozuvi
   (`ON CONFLICT DO NOTHING`) → holatni qo‘llash (to‘lov qatori `FOR UPDATE`) → commit.
5. Commitdan keyin foydalanuvchiga bildirishnoma.

Javob: `{"status": "ok"}` yoki takroriy hodisa uchun `{"status": "duplicate"}` (har ikkisi `200`,
provayder qayta yubormasligi uchun).

### Sandbox imzo sxemasi

| Sarlavha | Qiymat |
|---|---|
| `X-Sandbox-Timestamp` | Unix vaqt (soniya), ±300 s oralig‘ida bo‘lishi shart |
| `X-Sandbox-Signature` | `hex(HMAC_SHA256(SANDBOX_WEBHOOK_SECRET, "{timestamp}." + body))` |

Tana (JSON):

```json
{
  "event_id": "uuid",               // idempotentlik kaliti
  "kind": "payment",                // payment | payout | card_binding
  "reference": "payments.ref UUID", // bizning ID (payout uchun withdrawals.ref)
  "external_id": "sbx_pay_...",
  "status": "paid",                 // pending | processing | paid | failed | expired
  "amount": "50000.00",             // payment: summa mos kelmasa to‘lov FAILED + audit
  "card_token": "...",              // faqat card_binding
  "card_mask": "8600 **** **** 0001"
}
```

Holat semantikasi:

- `payment/paid` — balans **bir marta** oshadi (ledger `idempotency_key=payment:{id}:deposit`),
  VIP/promokod/referal bonuslari shu tranzaksiyada. Muddati o‘tgan yoki bekor qilingan
  to‘lov keyin `paid` kelsa ham kreditlanadi (pul provayderda olingan) va audit qilinadi.
- `payment/failed|expired` — faqat `pending` holatdan.
- `payout/paid` — bloklangan summa yechiladi; `payout/failed` — summa balansga qaytariladi.
- `card_binding/paid` — token va maskalangan raqam saqlanadi (PAN/CVV hech qachon kelmaydi).

## `POST /telegram/webhook`

Faqat `BOT_MODE=webhook`. `X-Telegram-Bot-Api-Secret-Token` sarlavhasi
`TELEGRAM_WEBHOOK_SECRET` bilan solishtiriladi (`403`). API startda `setWebhook` chaqiradi.

## Sandbox sahifalari (faqat `sandbox` provayderi ulangan bo‘lsa)

Barcha havolalar HMAC page-token (`?t=`) bilan himoyalangan; noto‘g‘ri token — `403`.

| Endpoint | Vazifasi |
|---|---|
| `GET /sandbox/checkout/{ref}?t=` | test checkout sahifasi |
| `POST /sandbox/checkout/{ref}/pay` / `/fail` | to‘lash / rad etish → imzolangan webhook |
| `GET /sandbox/cards/{ref}?t=` | test kartani tanlash (tokenlashtirish simulyatsiyasi) |
| `POST /sandbox/cards/{ref}/select` | karta tokeni → `card_binding` webhook (bir martalik) |

## Provayder adapteri shartnomasi (`app/payments/base.py`)

```python
class PaymentProvider(ABC):
    async def create_payment(*, reference, amount, currency, description, expires_at) -> CheckoutSession
    def verify_webhook(headers, body) -> ProviderEvent           # WebhookVerificationError
    async def create_payout(*, reference, amount, currency, card_token) -> PayoutResult
    async def check_status(*, kind, reference, external_id=None) -> StatusResult
    async def create_card_binding(*, reference) -> str           # ixtiyoriy
    async def health_check() -> bool
```

`create_payout` uchun `reference` provayderda idempotentlik kaliti bo‘lishi shart — tarmoq
xatosidan keyingi retry ikki marta to‘lov qilmasligi uchun. `PaymentProviderError(retryable=...)`
worker retry/backoff va manual navbat qarorini belgilaydi.
