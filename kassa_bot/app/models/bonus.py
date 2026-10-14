from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    false,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PromoActivationStatus, PromoType
from app.db import Base, TimestampMixin, str_enum


class PromoCode(TimestampMixin, Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    bonus_type: Mapped[PromoType] = mapped_column(str_enum(PromoType), nullable=False)
    bonus_value: Mapped[Decimal] = mapped_column(nullable=False)
    max_bonus: Mapped[Decimal | None] = mapped_column()
    min_deposit: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    total_limit: Mapped[int | None] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    used_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_from: Mapped[datetime | None] = mapped_column()
    valid_until: Mapped[datetime | None] = mapped_column()
    created_by: Mapped[int | None] = mapped_column(BigInteger)


class PromoActivation(Base):
    __tablename__ = "promo_activations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("promo_codes.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    status: Mapped[PromoActivationStatus] = mapped_column(
        str_enum(PromoActivationStatus), default=PromoActivationStatus.PENDING, nullable=False
    )
    payment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="SET NULL")
    )
    bonus_amount: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column()


class VipLevel(TimestampMixin, Base):
    __tablename__ = "vip_levels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    min_total_deposit: Mapped[Decimal] = mapped_column(nullable=False)
    bonus_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())


class ReferralReward(Base):
    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    referred_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    payment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("payments.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    deposit_amount: Mapped[Decimal] = mapped_column(nullable=False)
    percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False, index=True
    )
