from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import LedgerAccount, LedgerDirection, LedgerReason, LedgerStatus
from app.db import Base, str_enum


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        CheckConstraint("available >= 0", name="available_non_negative"),
        CheckConstraint("blocked >= 0", name="blocked_non_negative"),
        CheckConstraint("bonus_balance >= 0", name="bonus_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    available: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    blocked: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    bonus_balance: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    total_deposit: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    total_withdraw: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    referral_earned: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    referral_withdrawn: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class LedgerEntry(Base):
    """O‘zgarmas (immutable) buxgalteriya yozuvi. UPDATE/DELETE DB triggeri bilan taqiqlangan."""

    __tablename__ = "ledger_entries"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    account: Mapped[LedgerAccount] = mapped_column(str_enum(LedgerAccount), nullable=False)
    direction: Mapped[LedgerDirection] = mapped_column(str_enum(LedgerDirection), nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    balance_after: Mapped[Decimal | None] = mapped_column()
    reason: Mapped[LedgerReason] = mapped_column(str_enum(LedgerReason), nullable=False, index=True)
    status: Mapped[LedgerStatus] = mapped_column(
        str_enum(LedgerStatus), default=LedgerStatus.COMPLETED, server_default="completed"
    )
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[str | None] = mapped_column(String(64))
    external_tx_id: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    actor_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )
