"""Qo‘lda o‘tkazish rejimi — tashqi to‘lov provayderisiz.

Karta raqami bot chatida olinadi (`CardService.add_manual_card`), yechish arizasi
`manual_required` bo‘lib admin navbatiga tushadi; operator pulni o‘zi o‘tkazib,
«💵 To‘landi deb belgilash» tugmasi bilan yakunlaydi. Avtomatik payout yo‘q.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from app.core.enums import ProviderEventKind, ProviderStatus
from app.payments.base import (
    CheckoutSession,
    PaymentProvider,
    PaymentProviderError,
    PayoutResult,
    ProviderEvent,
    StatusResult,
    WebhookVerificationError,
)

MANUAL_CODE = "manual"
_NO_ONLINE = "Qo‘lda rejimida onlayn to‘lovlar qo‘llab-quvvatlanmaydi"


class ManualProvider(PaymentProvider):
    code = MANUAL_CODE
    title = "Qo‘lda o‘tkazish (operator)"
    is_sandbox = False
    supports_payout = False
    supports_card_binding = False

    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: str,
        description: str,
        expires_at: datetime,
    ) -> CheckoutSession:
        raise PaymentProviderError(_NO_ONLINE, retryable=False)

    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        raise WebhookVerificationError("Qo‘lda rejimida webhook yo‘q")

    async def create_payout(
        self, *, reference: str, amount: Decimal, currency: str, card_token: str
    ) -> PayoutResult:
        raise PaymentProviderError("Qo‘lda rejimida avtomatik payout yo‘q", retryable=False)

    async def check_status(
        self, *, kind: ProviderEventKind, reference: str, external_id: str | None = None
    ) -> StatusResult:
        return StatusResult(status=ProviderStatus.NOT_FOUND)
