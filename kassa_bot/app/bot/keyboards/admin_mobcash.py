"""Mob-Cash admin ogohlantirishlari uchun inline tugmalar (notifier va admin bo‘limi umumiy)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.keyboards.callbacks import AdmCb
from app.core.enums import MobcashWithdrawalStatus, P2PDepositStatus, P2PDepositTarget
from app.models import BankTransaction, MobcashWithdrawal, P2PDeposit


def _b(text: str, section: str, action: str, id: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=AdmCb(section=section, action=action, id=id).pack()
    )


def mcwd_kb(wd: MobcashWithdrawal) -> InlineKeyboardMarkup | None:
    """section «mcw» — yechish arizasi."""
    if wd.status == MobcashWithdrawalStatus.AWAITING_PAYOUT:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_b("✅ Kartaga o‘tkazdim", "mcw", "paid", wd.id)],
                [_b("↩️ O‘yin hisobiga qaytarish", "mcw", "refund", wd.id)],
            ]
        )
    if wd.status == MobcashWithdrawalStatus.REFUND_REVIEW:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_b("✅ Panelda tekshirdim: qaytarilgan", "mcw", "rf_ok", wd.id)],
                [_b("❌ Panelda tekshirdim: qaytarilmagan", "mcw", "rf_fail", wd.id)],
            ]
        )
    if wd.status == MobcashWithdrawalStatus.REVIEW:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [_b("✅ Mob-Cash'da yechilgan", "mcw", "rv_ok", wd.id)],
                [_b("❌ Yechilmagan", "mcw", "rv_fail", wd.id)],
            ]
        )
    return None


def p2p_kb(dep: P2PDeposit) -> InlineKeyboardMarkup | None:
    """section «p2p» — depozit."""
    rows: list[list[InlineKeyboardButton]] = []
    if dep.status == P2PDepositStatus.REVIEW:
        retry_label = (
            "🔁 Hamyonga qayta urinish"
            if dep.target == P2PDepositTarget.WALLET
            else "🔁 Mob-Cash'ga qayta yuborish"
        )
        rows.append([_b(retry_label, "p2p", "retry", dep.id)])
        rows.append([_b("✅ Qo‘lda tushirildi", "p2p", "credited", dep.id)])
        rows.append([_b("❌ Rad etish", "p2p", "reject", dep.id)])
    elif dep.status in (
        P2PDepositStatus.PENDING,
        P2PDepositStatus.EXPIRED,
        P2PDepositStatus.CANCELLED,
    ):
        rows.append([_b("✅ To‘lov keldi (qo‘lda tasdiqlash)", "p2p", "confirm", dep.id)])
    elif dep.status == P2PDepositStatus.PAID:
        rows.append([_b("🔁 Hozir tushirish", "p2p", "credit_now", dep.id)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def bank_tx_kb(tx: BankTransaction) -> InlineKeyboardMarkup:
    """section «btx» — mos kelmagan kirim."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_b("🔗 Depozitga bog‘lash", "btx", "link", tx.id)],
            [_b("🙈 E’tiborsiz qoldirish", "btx", "ignore", tx.id)],
        ]
    )
