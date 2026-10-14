from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Index, Integer, String, false, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import JoinRequestStatus
from app.db import Base, TimestampMixin, str_enum


class RequiredChannel(TimestampMixin, Base):
    __tablename__ = "required_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    invite_link: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    bot_is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    checked_at: Mapped[datetime | None] = mapped_column()


class JoinRequest(Base):
    __tablename__ = "join_requests"
    __table_args__ = (Index("ix_join_requests_chat_user", "chat_id", "user_telegram_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chat_title: Mapped[str | None] = mapped_column(String(128))
    user_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[JoinRequestStatus] = mapped_column(
        str_enum(JoinRequestStatus),
        default=JoinRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    processed_by: Mapped[int | None] = mapped_column(BigInteger)
    processed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
