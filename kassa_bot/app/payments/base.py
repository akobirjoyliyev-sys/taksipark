"""To‘lov provayderi interfeysi (adapter pattern).

Handlerlar va servislar faqat shu interfeys bilan ishlaydi — providerga xos kod faqat
`app/payments/<provider>.py` adapterlarida bo‘ladi.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from app.core.enums import ProviderEventKind, ProviderStatus


class PaymentProviderError(Exception):
    """Provayder bilan aloqa xatosi. `retryable=True` bo‘lsa qayta urinish mumkin."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class WebhookVerificationError(Exception):
    """Webhook imzosi yoki formati noto‘g‘ri."""


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    external_id: str
    checkout_url: str
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    event_id: str
    kind: ProviderEventKind
    reference: str
    status: ProviderStatus
    external_id: str | None = None
    amount: Decimal | None = None
    card_token: str | None = None
    card_mask: str | None = None
    error: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PayoutResult:
    status: ProviderStatus
    external_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class StatusResult:
    status: ProviderStatus
    external_id: str | None = None
    amount: Decimal | None = None
    error: str | None = None


class PaymentProvider(ABC):
    code: ClassVar[str]
    title: ClassVar[str]
    is_sandbox: ClassVar[bool] = False
    supports_payout: ClassVar[bool] = False
    supports_card_binding: ClassVar[bool] = False

    @abstractmethod
    async def create_payment(
        self,
        *,
        reference: str,
        amount: Decimal,
        currency: str,
        description: str,
        expires_at: datetime,
    ) -> CheckoutSession:
        """Provayderda checkout/invoice yaratadi. `reference` — bizning payment.ref."""

    @abstractmethod
    def verify_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        """Imzoni tekshiradi va normallashtirilgan hodisani qaytaradi.

        `headers` kalitlari kichik harflarda. Xato bo‘lsa WebhookVerificationError.
        """

    @abstractmethod
    async def create_payout(
        self, *, reference: str, amount: Decimal, currency: str, card_token: str
    ) -> PayoutResult:
        """Tokenlashtirilgan kartaga to‘lov. `reference` idempotentlik kaliti sifatida."""

    @abstractmethod
    async def check_status(
        self, *, kind: ProviderEventKind, reference: str, external_id: str | None = None
    ) -> StatusResult:
        """Reconciliation uchun provayderdagi holatni so‘raydi."""

    async def create_card_binding(self, *, reference: str) -> str:
        """Kartani provayderning xavfsiz sahifasida tokenlashtirish URLini qaytaradi."""
        raise PaymentProviderError("Karta ulash qo‘llab-quvvatlanmaydi", retryable=False)

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        return None
