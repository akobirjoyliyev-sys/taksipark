"""Bukmeker kassalari (kantoralar): har biri alohida kassa hisobi.

`gateway`: "mobcash" (admin.mob-cash.com), "cashdesk" (1xBet Cashdesk Bot API —
`kods | kassir paroli | hash` bilan ulanadi, login bo'sh, pul harakati yo'q) yoki
"agent" (TeamCash/MELLO agent API — `agent: login | parol | kassa_kodi`).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Integer, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Bookmaker(TimestampMixin, Base):
    __tablename__ = "bookmakers"
    __table_args__ = (UniqueConstraint("cashbox_code", "login", name="uq_bookmakers_code_login"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    cashbox_code: Mapped[int] = mapped_column(BigInteger, nullable=False)
    login: Mapped[str] = mapped_column(String(128), nullable=False)
    # Parol/hash tizim shifrlash kaliti (Fernet) bilan shifrlanadi — bazada ochiq turmaydi.
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    hash_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    gateway: Mapped[str] = mapped_column(String(16), nullable=False, default="mobcash", server_default="mobcash")
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="—")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
