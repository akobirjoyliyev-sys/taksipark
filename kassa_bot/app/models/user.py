from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, String, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(20), index=True)
    contact_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    onboarding_done: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), default="uz", server_default="uz")
    is_banned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    ban_reason: Mapped[str | None] = mapped_column(String(255))
    referrer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # Mob-Cash: oxirgi ishlatilgan o‘yin ID si va pul chiqarish kartasi (qayta kiritmaslik uchun)
    mobcash_payer_id: Mapped[str | None] = mapped_column(String(32))
    payout_card_number: Mapped[str | None] = mapped_column(String(19))
    # Har bir bukmekerdagi o‘yin ID si: {"<bookmaker_id>": "123456"}
    payer_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    def payer_id_for(self, bookmaker_id: int | None) -> str | None:
        if bookmaker_id is None:
            return self.mobcash_payer_id
        value = (self.payer_ids or {}).get(str(bookmaker_id))
        return str(value) if value else None

    def remember_payer_id(self, bookmaker_id: int | None, payer_id: str) -> None:
        self.mobcash_payer_id = payer_id
        if bookmaker_id is not None:
            # JSONB o‘zgarishini SQLAlchemy sezishi uchun yangi dict beriladi.
            self.payer_ids = {**(self.payer_ids or {}), str(bookmaker_id): payer_id}

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p) or "—"
