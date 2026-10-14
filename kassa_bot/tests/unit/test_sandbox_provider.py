from __future__ import annotations

import json
import time
from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.enums import ProviderEventKind, ProviderStatus
from app.core.utils import utcnow
from app.payments.base import PaymentProviderError, WebhookVerificationError
from app.payments.sandbox import SIGNATURE_HEADER, TIMESTAMP_HEADER, SandboxProvider


async def test_payment_roundtrip_signed_webhook(sandbox: SandboxProvider) -> None:
    checkout = await sandbox.create_payment(
        reference="ref-1",
        amount=Decimal("50000"),
        currency="UZS",
        description="t",
        expires_at=utcnow() + timedelta(minutes=10),
    )
    assert checkout.checkout_url.startswith("https://kassa.example.com/sandbox/checkout/ref-1?t=")
    status = await sandbox.check_status(kind=ProviderEventKind.PAYMENT, reference="ref-1")
    assert status.status == ProviderStatus.PENDING

    payload = await sandbox.complete_payment("ref-1", success=True)
    assert payload is not None
    headers, body = sandbox.build_webhook(payload)
    event = sandbox.verify_webhook(headers, body)
    assert event.status == ProviderStatus.PAID
    assert event.amount == Decimal("50000")
    assert event.kind == ProviderEventKind.PAYMENT
    # Ikkinchi marta yakunlab bo‘lmaydi
    assert await sandbox.complete_payment("ref-1", success=True) is None


async def test_webhook_rejects_tampering_and_replay(sandbox: SandboxProvider) -> None:
    payload = {
        "event_id": "e1",
        "kind": "payment",
        "reference": "r",
        "status": "paid",
        "amount": "100",
    }
    headers, body = sandbox.build_webhook(payload)

    tampered = json.dumps({**payload, "amount": "999999"}).encode()
    with pytest.raises(WebhookVerificationError):
        sandbox.verify_webhook(headers, tampered)

    with pytest.raises(WebhookVerificationError):
        sandbox.verify_webhook({**headers, SIGNATURE_HEADER: "0" * 64}, body)

    old_ts = int(time.time()) - 3600
    old_headers = {SIGNATURE_HEADER: sandbox.sign(body, old_ts), TIMESTAMP_HEADER: str(old_ts)}
    with pytest.raises(WebhookVerificationError):
        sandbox.verify_webhook(old_headers, body)

    with pytest.raises(WebhookVerificationError):
        sandbox.verify_webhook({}, body)


async def test_expired_payment(sandbox: SandboxProvider) -> None:
    await sandbox.create_payment(
        reference="ref-exp",
        amount=Decimal("1000"),
        currency="UZS",
        description="t",
        expires_at=utcnow() - timedelta(seconds=1),
    )
    status = await sandbox.check_status(kind=ProviderEventKind.PAYMENT, reference="ref-exp")
    assert status.status == ProviderStatus.EXPIRED
    payload = await sandbox.complete_payment("ref-exp", success=True)
    assert payload is not None and payload["status"] == "expired"


async def test_payout_is_idempotent(sandbox: SandboxProvider) -> None:
    first = await sandbox.create_payout(
        reference="w1", amount=Decimal("1000"), currency="UZS", card_token="sbx_tok_abc"
    )
    second = await sandbox.create_payout(
        reference="w1", amount=Decimal("1000"), currency="UZS", card_token="sbx_tok_abc"
    )
    assert first.external_id == second.external_id
    status = await sandbox.check_status(kind=ProviderEventKind.PAYOUT, reference="w1")
    assert status.status == ProviderStatus.PAID  # delay=0
    missing = await sandbox.check_status(kind=ProviderEventKind.PAYOUT, reference="nope")
    assert missing.status == ProviderStatus.NOT_FOUND


async def test_payout_decline_and_transient(redis: object) -> None:
    provider = SandboxProvider(
        redis=redis, secret="s", public_base_url="https://x.example", payout_failure_rate=1.0  # type: ignore[arg-type]
    )
    with pytest.raises(PaymentProviderError) as exc:
        await provider.create_payout(
            reference="w2", amount=Decimal("1"), currency="UZS", card_token="sbx_tok_x"
        )
    assert exc.value.retryable
    ok_provider = SandboxProvider(redis=redis, secret="s", public_base_url="https://x.example")  # type: ignore[arg-type]
    declined = await ok_provider.create_payout(
        reference="w3", amount=Decimal("1"), currency="UZS", card_token="sbx_tok_decline_1"
    )
    assert declined.status == ProviderStatus.FAILED


async def test_card_binding_single_use(sandbox: SandboxProvider) -> None:
    url = await sandbox.create_card_binding(reference="b1")
    assert "/sandbox/cards/b1?t=" in url
    payload = await sandbox.complete_card_binding("b1", "ok")
    assert payload is not None
    assert payload["card_mask"].endswith("0001")
    assert payload["card_token"].startswith("sbx_tok_")
    assert await sandbox.complete_card_binding("b1", "ok") is None


def test_page_token(sandbox: SandboxProvider) -> None:
    token = sandbox.page_token("pay", "abc")
    assert sandbox.check_page_token("pay", "abc", token)
    assert not sandbox.check_page_token("pay", "abd", token)
    assert not sandbox.check_page_token("bind", "abc", token)
