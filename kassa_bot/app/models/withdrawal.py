from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, false, func, true
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import WithdrawalSource, WithdrawalStatus
from app.db import Base, TimestampMixin, str_enum


class Withdrawal(TimestampMixin, Base):
    __tablename__ = "withdrawals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ref: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    source: Mapped[WithdrawalSource] = mapped_column(
        str_enum(WithdrawalSource), default=WithdrawalSource.USER, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    card_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payout_cards.id", ondelete="SET NULL")
    )
    card_mask: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    fee: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    net_amount: Mapped[Decimal] = mapped_column(nullable=False)
    status: Mapped[WithdrawalStatus] = mapped_column(
        str_enum(WithdrawalStatus), default=WithdrawalStatus.PENDING, index=True, nullable=False
    )
    manual_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    external_id: Mapped[str | None] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    processed_by: Mapped[int | None] = mapped_column(BigInteger)
    processed_at: Mapped[datetime | None] = mapped_column()
    paid_at: Mapped[datetime | None] = mapped_column()
    batch_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("mass_payout_batches.id", ondelete="SET NULL"), index=True
    )
    is_test: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class WithdrawalStatusHistory(Base):
    __tablename__ = "withdrawal_status_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    withdrawal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("withdrawals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_role: Mapped[str] = mapped_column(String(16), default="system", server_default="system")
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
