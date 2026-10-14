"""Mob-Cash kassa, P2P (karta → karta) noyob summa depozitlari va userbot akkauntlari."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    BankTxStatus,
    MobcashWithdrawalStatus,
    P2PDepositStatus,
    P2PDepositTarget,
    UserbotStatus,
)
from app.db import Base, TimestampMixin, str_enum


class P2PCard(TimestampMixin, Base):
    """Foydalanuvchilar pul o‘tkazadigan kassir kartasi (P2P qabul qilish uchun)."""

    __tablename__ = "p2p_cards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(String(19), unique=True, nullable=False)
    holder: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    bank: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    @property
    def last4(self) -> str:
        return self.number[-4:]

    @property
    def pretty(self) -> str:
        return " ".join(self.number[i : i + 4] for i in range(0, len(self.number), 4))


class UserbotAccount(TimestampMixin, Base):
    """Bank xabarlarini (CardXabar, HUMO) o‘qiydigan Telegram akkaunt.

    `session_encrypted` — Fernet bilan shifrlangan Telethon StringSession. Ochiq holda
    hech qachon saqlanmaydi va logga yozilmaydi.
    """

    __tablename__ = "userbot_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    session_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[UserbotStatus] = mapped_column(
        str_enum(UserbotStatus), default=UserbotStatus.ACTIVE, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_seen_at: Mapped[datetime | None] = mapped_column()
    added_by: Mapped[int | None] = mapped_column(BigInteger)


class BankTransaction(Base):
    """Userbot o‘qigan bank xabari (faqat kirim). Bir xabar bir marta qayta ishlanadi.

    Takrorni aniqlash kaliti — xabarni olgan Telegram akkaunt ID si (`owner_tg_id`): xabar
    raqamlari har bir akkaunt uchun alohida, userbot o‘chirib qayta qo‘shilsa ham o‘zgarmaydi.
    """

    __tablename__ = "bank_transactions"
    __table_args__ = (
        UniqueConstraint(
            "owner_tg_id", "source_chat_id", "message_id", name="uq_bank_transactions_message"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("userbot_accounts.id", ondelete="SET NULL"), index=True
    )
    owner_tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    card_last4: Mapped[str | None] = mapped_column(String(4))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[BankTxStatus] = mapped_column(
        str_enum(BankTxStatus), default=BankTxStatus.UNMATCHED, index=True, nullable=False
    )
    deposit_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    message_date: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class P2PDeposit(TimestampMixin, Base):
    """Noyob summa bilan depozit: foydalanuvchi aynan `unique_amount`ni kartaga o‘tkazadi."""

    __tablename__ = "p2p_deposits"
    __table_args__ = (
        # Bir vaqtda ikkita kutilayotgan to‘lov bir xil summaga ega bo‘lmasligi kerak —
        # aks holda bank xabarini qaysi foydalanuvchiga bog‘lashni bilib bo‘lmaydi.
        Index(
            "uq_p2p_deposits_pending_amount",
            "unique_amount",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    bookmaker_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bookmakers.id", ondelete="RESTRICT"), index=True
    )
    target: Mapped[P2PDepositTarget] = mapped_column(
        str_enum(P2PDepositTarget),
        default=P2PDepositTarget.GAME,
        server_default=P2PDepositTarget.GAME.value,
        index=True,
        nullable=False,
    )
    payer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    payer_nickname: Mapped[str | None] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    unique_amount: Mapped[Decimal] = mapped_column(nullable=False)
    # Mob-Cash'ga tushiriladigan summa (kelgan summa − komissiya). To‘lov tasdiqlanganda yoziladi.
    credit_amount: Mapped[Decimal | None] = mapped_column()
    card_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("p2p_cards.id", ondelete="SET NULL")
    )
    status: Mapped[P2PDepositStatus] = mapped_column(
        str_enum(P2PDepositStatus), default=P2PDepositStatus.PENDING, index=True, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    paid_at: Mapped[datetime | None] = mapped_column()
    credited_at: Mapped[datetime | None] = mapped_column()
    bank_tx_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bank_transactions.id", ondelete="SET NULL"), unique=True
    )
    credit_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(500))
    mobcash_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    chat_message_id: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)


class MobcashWithdrawal(TimestampMixin, Base):
    """Mob-Cash'dan yechish arizasi. Pul kassaga tushgach admin kartaga qo‘lda o‘tkazadi."""

    __tablename__ = "mobcash_withdrawals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    bookmaker_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bookmakers.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    payer_id: Mapped[str] = mapped_column(String(32), nullable=False)
    # Yechish kodi bir martalik va maxfiy — bazada faqat maskalangan ko‘rinishi qoladi.
    code_mask: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    fee: Mapped[Decimal] = mapped_column(default=Decimal(0), server_default="0")
    payout_amount: Mapped[Decimal] = mapped_column(nullable=False)
    card_number: Mapped[str] = mapped_column(String(19), nullable=False)
    status: Mapped[MobcashWithdrawalStatus] = mapped_column(
        str_enum(MobcashWithdrawalStatus),
        default=MobcashWithdrawalStatus.AWAITING_PAYOUT,
        index=True,
        nullable=False,
    )
    mobcash_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(String(500))
    processed_by: Mapped[int | None] = mapped_column(BigInteger)
    paid_at: Mapped[datetime | None] = mapped_column()
    comment: Mapped[str | None] = mapped_column(String(255))
