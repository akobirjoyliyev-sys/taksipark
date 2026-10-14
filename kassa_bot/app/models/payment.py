from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PaymentStatus, ProviderEventKind
from app.db import Base, TimestampMixin, str_enum


class Payment(TimestampMixin, Base):
    """Hisob to‘ldirish (depozit) — provayder checkout/invoice."""

    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_payments_provider_ext"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ref: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    fee: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    credited_amount: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), default="UZS", server_default="UZS")
    status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus), default=PaymentStatus.PENDING, index=True, nullable=False
    )
    external_id: Mapped[str | None] = mapped_column(String(128))
    checkout_url: Mapped[str | None] = mapped_column(Text)
    is_test: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    paid_at: Mapped[datetime | None] = mapped_column()
    failure_reason: Mapped[str | None] = mapped_column(String(255))
    chat_message_id: Mapped[int | None] = mapped_column(BigInteger)


class WebhookEvent(Base):
    """Provayder webhooklari — (provider, event_id) bo‘yicha idempotentlik."""

    __tablename__ = "webhook_events"
    __table_args__ = (UniqueConstraint("provider", "event_id", name="uq_webhook_events_event"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[ProviderEventKind] = mapped_column(str_enum(ProviderEventKind), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class PayoutCard(TimestampMixin, Base):
    """Karta yozuvi: provayder tokeni yoki («manual» rejimda) to‘liq raqam. CVV saqlanmaydi."""

    __tablename__ = "payout_cards"
    __table_args__ = (UniqueConstraint("provider", "token", name="uq_payout_cards_token"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    token: Mapped[str] = mapped_column(String(255), nullable=False)
    masked_pan: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
