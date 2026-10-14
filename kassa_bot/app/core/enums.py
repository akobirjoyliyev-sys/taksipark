from __future__ import annotations

from enum import StrEnum


class AdminRole(StrEnum):
    SUPERADMIN = "superadmin"
    ADMIN = "admin"
    OPERATOR = "operator"
    AUDITOR = "auditor"


class LedgerAccount(StrEnum):
    MAIN = "main"
    BLOCKED = "blocked"
    BONUS = "bonus"
    SYSTEM = "system"


class LedgerDirection(StrEnum):
    CREDIT = "credit"
    DEBIT = "debit"


class LedgerReason(StrEnum):
    DEPOSIT = "deposit"
    WITHDRAW_HOLD = "withdraw_hold"
    WITHDRAW_RELEASE = "withdraw_release"
    WITHDRAW_PAID = "withdraw_paid"
    PROMO_BONUS = "promo_bonus"
    VIP_BONUS = "vip_bonus"
    REFERRAL_BONUS = "referral_bonus"
    REFERRAL_TRANSFER = "referral_transfer"
    MANUAL_CREDIT = "manual_credit"
    MANUAL_DEBIT = "manual_debit"
    MASS_PAYOUT = "mass_payout"
    GAME_DEPOSIT = "game_deposit"
    GAME_DEPOSIT_REFUND = "game_deposit_refund"
    GAME_WITHDRAW = "game_withdraw"


class LedgerStatus(StrEnum):
    COMPLETED = "completed"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class WithdrawalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    PROCESSING = "processing"
    PAID = "paid"
    REJECTED = "rejected"
    FAILED = "failed"


ACTIVE_WITHDRAWAL_STATUSES = (
    WithdrawalStatus.PENDING,
    WithdrawalStatus.APPROVED,
    WithdrawalStatus.PROCESSING,
)


class WithdrawalSource(StrEnum):
    USER = "user"
    MASS = "mass"


class PromoType(StrEnum):
    FIXED = "fixed"
    PERCENT = "percent"


class PromoActivationStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    EXPIRED = "expired"


class JoinRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"


class MassBatchStatus(StrEnum):
    PREVIEW = "preview"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MassItemStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    DUPLICATE = "duplicate"
    QUEUED = "queued"
    PAID = "paid"
    FAILED = "failed"
    SKIPPED = "skipped"


class P2PDepositTarget(StrEnum):
    """Noyob summa to‘lovi qayerga tushadi.

    game — Mob-Cash orqali o‘yin hisobiga; wallet — to‘g‘ridan-to‘g‘ri bot hamyoniga.
    """

    GAME = "game"
    WALLET = "wallet"


class P2PDepositStatus(StrEnum):
    """Noyob summa bilan karta → karta depozit.

    pending → paid (bank xabari mos keldi) → credited (Mob-Cash'ga tushirildi).
    review — avtomatik yakunlab bo‘lmadi, admin tekshiradi (Mob-Cash javobi noaniq/xato).
    """

    PENDING = "pending"
    PAID = "paid"
    CREDITED = "credited"
    REVIEW = "review"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


ACTIVE_P2P_STATUSES = (P2PDepositStatus.PENDING, P2PDepositStatus.PAID, P2PDepositStatus.REVIEW)


class BankTxStatus(StrEnum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    IGNORED = "ignored"


class MobcashWithdrawalStatus(StrEnum):
    """Mob-Cash'dan yechish → admin kartaga qo‘lda o‘tkazadi.

    awaiting_payout — Mob-Cash withdrawal bajarildi, pul kassada, admin to‘lashi kerak.
    review — Mob-Cash javobi noaniq (timeout), admin Mob-Cash panelida tekshiradi.
    """

    AWAITING_PAYOUT = "awaiting_payout"
    PAID = "paid"
    REVIEW = "review"
    REFUND_REVIEW = "refund_review"
    REFUNDED = "refunded"
    REJECTED = "rejected"
    FAILED = "failed"


class UserbotStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"


class ProviderEventKind(StrEnum):
    PAYMENT = "payment"
    PAYOUT = "payout"
    CARD_BINDING = "card_binding"


class ProviderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"


class AutoBatchStatus(StrEnum):
    """🤖 Avto to‘lov partiyasi: ID ro‘yxatiga kassadan ommaviy depozit."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AutoItemStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    REVIEW = "review"  # so‘rov yuborilgan, natija noma’lum — panelda tekshirish kerak
    SKIPPED = "skipped"


ACTIVE_AUTO_BATCH_STATUSES = (AutoBatchStatus.RUNNING, AutoBatchStatus.PAUSED)
