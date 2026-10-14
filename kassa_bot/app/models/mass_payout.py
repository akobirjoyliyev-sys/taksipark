from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MassBatchStatus, MassItemStatus
from app.db import Base, TimestampMixin, str_enum


class MassPayoutBatch(TimestampMixin, Base):
    __tablename__ = "mass_payout_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    file_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[MassBatchStatus] = mapped_column(
        str_enum(MassBatchStatus), default=MassBatchStatus.PREVIEW, nullable=False, index=True
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(BigInteger)
    approved_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duplicate_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    paid_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MassPayoutItem(Base):
    __tablename__ = "mass_payout_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("mass_payout_batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_telegram_id: Mapped[int | None] = mapped_column(BigInteger)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal | None] = mapped_column()
    provider: Mapped[str | None] = mapped_column(String(32))
    fingerprint: Mapped[str | None] = mapped_column(String(128), index=True)
    status: Mapped[MassItemStatus] = mapped_column(str_enum(MassItemStatus), nullable=False)
    error: Mapped[str | None] = mapped_column(String(255))
    withdrawal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("withdrawals.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
