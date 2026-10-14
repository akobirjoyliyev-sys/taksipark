"""🤖 Avto to‘lov: admin yuborgan o‘yin ID lari ro‘yxatiga kassadan avtomatik depozit."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AutoBatchStatus, AutoItemStatus
from app.db import Base, TimestampMixin, str_enum


class AutoDepositBatch(TimestampMixin, Base):
    __tablename__ = "auto_deposit_batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # None — eski yagona Mob-Cash kassa. Nomi tarix uchun alohida saqlanadi.
    bookmaker_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kassa_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AutoBatchStatus] = mapped_column(
        str_enum(AutoBatchStatus), default=AutoBatchStatus.DRAFT, nullable=False, index=True
    )
    default_amount: Mapped[Decimal | None] = mapped_column()
    total_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_by: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column()
    # Jonli progress xabari (worker tahrirlaydi).
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    pause_reason: Mapped[str | None] = mapped_column(String(255))
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AutoDepositItem(Base):
    __tablename__ = "auto_deposit_items"
    __table_args__ = (
        UniqueConstraint("batch_id", "payer_id", name="uq_auto_deposit_items_batch_payer"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("auto_deposit_batches.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    payer_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    status: Mapped[AutoItemStatus] = mapped_column(
        str_enum(AutoItemStatus), default=AutoItemStatus.PENDING, nullable=False, index=True
    )
    nickname: Mapped[str | None] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error: Mapped[str | None] = mapped_column(String(500))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
