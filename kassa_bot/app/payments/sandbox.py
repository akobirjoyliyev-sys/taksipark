"""Sandbox (test) provayderi — real pul harakatlanmaydi.

Holat Redis'da saqlanadi, shuning uchun bot, API va worker jarayonlari bir xil
ma’lumotni ko‘radi. Checkout va karta ulash sahifalari `app/webhooks/sandbox.py` da.
"""

from __future__ import annotations

import json
import random
import secrets
import time
import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from redis.asyncio import Redis

from app.core.enums import ProviderEventKind, ProviderStatus
from app.core.utils import hmac_equal, hmac_hex
from app.payments.base import (
    CheckoutSession,
    PaymentProvider,
    PaymentProviderError,
    PayoutResult,
    ProviderEvent,
    StatusResult,
    WebhookVerificationError,
)

SIGNATURE_HEADER = "x-sandbox-signature"
TIMESTAMP_HEADER = "x-sandbox-timestamp"
STATE_TTL = 3 * 24 * 3600

# Faqat namoyish uchun test kartalar (haqiqiy raqamlar emas).
TEST_CARDS: tuple[tuple[str, str, str], ...] = (
    ("ok", "8600 **** **** 0001", "Muvaffaqiyatli payout"),
    ("ok2", "9860 **** **** 0003", "Muvaffaqiyatli payout (Humo)"),
    ("decline", "8600 **** **** 0002", "Payout rad etiladi"),
)


class SandboxProvider(PaymentProvider):
    code = "sandbox"
    title = "Sandbox (test)"
    is_sandbox = True
    supports_payout = True
    supports_card_binding = True

    def __init__(
        self,
        *,
        redis: Redis,
        secret: str,
        public_base_url: str,
        payout_failure_rate: float = 0.0,
        payout_delay_seconds: int = 3,
        tolerance_seconds: int = 300,
    ) -> None:
        if not secret:
            raise ValueError("SANDBOX_WEBHOOK_SECRET bo‘sh bo‘lmasligi kerak")
        self._redis = redis
        self._secret = secret
        self._base = public_base_url.rstrip("/")
        self._failure_rate = payout_failure_rate
        self._delay = payout_delay_seconds
        self._tolerance = tolerance_seconds

    # ---- imzo ----------------------------------------------------------------
    def sign(self, body: bytes, timestamp: int) -> str:
        return hmac_hex(self._secret, f"{timestamp}.".encode() + body)

    def page_token(self, kind: str, reference: str) -> str:
        return hmac_hex(self._secret, f"page:{kind}:{reference}".encode())[:32]

    def check_page_token(self, kind: str, reference: str, token: str) -> bool:
        return hmac_equal(self.page_token(kind, reference), token or "")

    def build_webhook(self, payload: Mapping[str, Any]) -> tuple[dict[str, str], bytes]:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        ts = int(time.time())
        headers = {
            SIGNATURE_HEADER: self.sign(body, ts),
            TIMESTAMP_HEADER: str(ts),
            "content-type": "application/json",
        }
        return headers, body

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        signature = headers.get(SIGNATURE_HEADER, "")
        raw_ts = headers.get(TIMESTAMP_HEADER, "")
        try:
            ts = int(raw_ts)
        except ValueError as exc:
            raise WebhookVerificationError("timestamp yo‘q") from exc
        if abs(time.time() - ts) > self._tolerance:
            raise WebhookVerificationError("timestamp eskirgan")
        if not signature or not hmac_equal(self.sign(body, ts), signature):
            raise WebhookVerificationError("imzo noto‘g‘ri")
        try:
            data = json.loads(body)
            amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
            return ProviderEvent(
                event_id=str(data["event_id"]),
                kind=ProviderEventKind(data["kind"]),
                reference=str(data["reference"]),
                status=ProviderStatus(data["status"]),
                external_id=data.get("external_id"),
                amount=amount,
                card_token=data.get("card_token"),
                card_mask=data.get("card_mask"),
                error=data.get("error"),
                raw={k: v for k, v in data.items() if k != "card_token"},
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise WebhookVerificationError("payload formati noto‘g‘ri") from exc

    # ---- to‘lov --------------------------------------------------------------
    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: str,
        description: str,
        expires_at: datetime,
    ) -> CheckoutSession:
        external_id = f"sbx_pay_{secrets.token_hex(8)}"
        key = f"sandbox:pay:{reference}"
        await self._redis.hset(
            key,
            mapping={
                "external_id": external_id,
                "amount": str(amount),
                "currency": currency,
                "status": ProviderStatus.PENDING.value,
                "expires_at": str(int(expires_at.timestamp())),
            },
        )
        await self._redis.expire(key, STATE_TTL)
        url = f"{self._base}/sandbox/checkout/{reference}?t={self.page_token('pay', reference)}"
        return CheckoutSession(external_id=external_id, checkout_url=url, expires_at=expires_at)

    async def get_payment(self, reference: str) -> dict[str, str]:
        raw = await self._redis.hgetall(f"sandbox:pay:{reference}")
        return {_s(k): _s(v) for k, v in raw.items()}

    async def complete_payment(self, reference: str, success: bool) -> dict[str, Any] | None:
        """Sandbox sahifasidagi 'To‘lash'/'Rad etish' — webhook payloadini qaytaradi."""
        state = await self.get_payment(reference)
        if not state or state.get("status") != ProviderStatus.PENDING.value:
            return None
        if int(state.get("expires_at", "0")) < time.time():
            status = ProviderStatus.EXPIRED
        else:
            status = ProviderStatus.PAID if success else ProviderStatus.FAILED
        await self._redis.hset(f"sandbox:pay:{reference}", "status", status.value)
        return {
            "event_id": str(uuid.uuid4()),
            "kind": ProviderEventKind.PAYMENT.value,
            "reference": reference,
            "external_id": state["external_id"],
            "status": status.value,
            "amount": state["amount"],
        }

    # ---- payout --------------------------------------------------------------
    async def create_payout(
        self, *, reference: str, amount: Decimal, currency: str, card_token: str
    ) -> PayoutResult:
        key = f"sandbox:payout:{reference}"
        existing = await self._redis.hgetall(key)
        if existing:  # idempotent: bir reference — bitta payout
            state = {_s(k): _s(v) for k, v in existing.items()}
            return PayoutResult(
                status=ProviderStatus(state["status"]),
                external_id=state["external_id"],
                error=state.get("error") or None,
            )
        if self._failure_rate and random.random() < self._failure_rate:
            raise PaymentProviderError("sandbox: vaqtinchalik xato", retryable=True)
        external_id = f"sbx_out_{secrets.token_hex(8)}"
        if card_token.startswith("sbx_tok_decline"):
            status, error = ProviderStatus.FAILED, "card_declined"
        else:
            status, error = ProviderStatus.PROCESSING, ""
        await self._redis.hset(
            key,
            mapping={
                "external_id": external_id,
                "status": status.value,
                "amount": str(amount),
                "ready_at": str(int(time.time()) + self._delay),
                "error": error,
            },
        )
        await self._redis.expire(key, STATE_TTL)
        return PayoutResult(status=status, external_id=external_id, error=error or None)

    async def check_status(
        self, *, kind: ProviderEventKind, reference: str, external_id: str | None = None
    ) -> StatusResult:
        if kind == ProviderEventKind.PAYMENT:
            state = await self.get_payment(reference)
            if not state:
                return StatusResult(status=ProviderStatus.NOT_FOUND)
            status = ProviderStatus(state["status"])
            if status == ProviderStatus.PENDING and int(state["expires_at"]) < time.time():
                status = ProviderStatus.EXPIRED
            return StatusResult(
                status=status,
                external_id=state["external_id"],
                amount=Decimal(state["amount"]),
            )
        if kind == ProviderEventKind.PAYOUT:
            key = f"sandbox:payout:{reference}"
            raw = await self._redis.hgetall(key)
            if not raw:
                return StatusResult(status=ProviderStatus.NOT_FOUND)
            state = {_s(k): _s(v) for k, v in raw.items()}
            status = ProviderStatus(state["status"])
            if status == ProviderStatus.PROCESSING and int(state["ready_at"]) <= time.time():
                status = ProviderStatus.PAID
                await self._redis.hset(key, "status", status.value)
            return StatusResult(
                status=status, external_id=state["external_id"], error=state.get("error") or None
            )
        return StatusResult(status=ProviderStatus.NOT_FOUND)

    # ---- karta tokenlashtirish ----------------------------------------------
    async def create_card_binding(self, *, reference: str) -> str:
        await self._redis.set(f"sandbox:bind:{reference}", "1", ex=900)
        return f"{self._base}/sandbox/cards/{reference}?t={self.page_token('bind', reference)}"

    async def complete_card_binding(self, reference: str, card_key: str) -> dict[str, Any] | None:
        if not await self._redis.delete(f"sandbox:bind:{reference}"):
            return None
        card = next((c for c in TEST_CARDS if c[0] == card_key), None)
        if card is None:
            return None
        prefix = "sbx_tok_decline_" if card_key == "decline" else "sbx_tok_"
        return {
            "event_id": str(uuid.uuid4()),
            "kind": ProviderEventKind.CARD_BINDING.value,
            "reference": reference,
            "status": ProviderStatus.PAID.value,
            "card_token": prefix + secrets.token_hex(12),
            "card_mask": card[1],
        }

    async def health_check(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False


def _s(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value
