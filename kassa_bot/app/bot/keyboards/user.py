from __future__ import annotations

from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.bot.keyboards.callbacks import (
    AmountCb,
    BonusCb,
    CardCb,
    HistoryCb,
    MenuCb,
    PaymentCb,
    SubCb,
    WdCb,
)
from app.core.money import fmt_money
from app.core.utils import is_public_url
from app.models import Payment, PayoutCard, RequiredChannel, Withdrawal

QUICK_AMOUNTS = (10_000, 50_000, 100_000, 200_000, 500_000)


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in texts.MAIN_MENU_ROWS],
        resize_keyboard=True,
        input_field_placeholder="Bo‘limni tanlang",
    )


def webapp_kb(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=texts.BTN_WEBAPP, web_app=WebAppInfo(url=url))]]
    )


def contact_kb(required: bool) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=texts.BTN_SHARE_CONTACT, request_contact=True)]]
    if not required:
        rows.append([KeyboardButton(text=texts.BTN_SKIP_CONTACT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def url_or_none(text: str, url: str) -> InlineKeyboardButton | None:
    return InlineKeyboardButton(text=text, url=url) if url and is_public_url(url) else None


def link_kb(text: str, url: str) -> InlineKeyboardMarkup | None:
    button = url_or_none(text, url)
    return InlineKeyboardMarkup(inline_keyboard=[[button]]) if button else None


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel").pack()
                )
            ]
        ]
    )


def wallet_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_W_WGAME, callback_data=MenuCb(action="wgame"))
    b.button(text=texts.BTN_W_TOPUP, callback_data=MenuCb(action="topup"))
    b.button(text=texts.BTN_W_WITHDRAW, callback_data=MenuCb(action="withdraw"))
    b.button(text=texts.BTN_W_HISTORY, callback_data=HistoryCb(kind="led", status="all"))
    b.button(text=texts.BTN_W_CARDS, callback_data=CardCb(action="list"))
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="back"))
    b.adjust(2, 1, 2, 1)
    return b.as_markup()


def topup_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in QUICK_AMOUNTS:
        b.button(text=fmt_money(value), callback_data=AmountCb(value=value))
    b.button(text=texts.BTN_CUSTOM_AMOUNT, callback_data=AmountCb(value=0))
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="wallet"))
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def payment_kb(payment: Payment) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pay = url_or_none(texts.BTN_PAY, payment.checkout_url or "")
    if pay:
        rows.append([pay])
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BTN_CHECK_STATUS,
                callback_data=PaymentCb(action="check", id=payment.id).pack(),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=texts.BTN_CANCEL,
                callback_data=PaymentCb(action="cancel", id=payment.id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def card_select_kb(cards: list[PayoutCard]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for card in cards:
        b.button(text=f"💳 {card.masked_pan}", callback_data=CardCb(action="pick", id=card.id))
    b.button(text=texts.BTN_BIND_CARD, callback_data=CardCb(action="bind"))
    b.button(text=texts.BTN_MY_REQUESTS, callback_data=WdCb(action="list"))
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="back"))
    b.adjust(1)
    return b.as_markup()


def withdraw_amount_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_WITHDRAW_ALL, callback_data=WdCb(action="all"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(1)
    return b.as_markup()


def withdraw_confirm_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_CONFIRM, callback_data=WdCb(action="confirm"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(2)
    return b.as_markup()


def my_requests_kb(items: list[Withdrawal]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for w in items:
        status = texts.WITHDRAW_STATUS[w.status].split(" ", 1)[0]
        b.button(
            text=f"{status} #{w.id} • {fmt_money(w.amount)}",
            callback_data=WdCb(action="view", id=w.id),
        )
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="withdraw"))
    b.adjust(1)
    return b.as_markup()


def back_kb(action: str = "back") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=texts.BTN_BACK, callback_data=MenuCb(action=action).pack())]
        ]
    )


def cards_manage_kb(cards: list[PayoutCard]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for card in cards:
        b.button(text=f"🗑 {card.masked_pan}", callback_data=CardCb(action="del", id=card.id))
    b.button(text=texts.BTN_BIND_CARD, callback_data=CardCb(action="bind"))
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="wallet"))
    b.adjust(1)
    return b.as_markup()


def history_kb(kind: str, status: str, page: int, has_next: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for k, label in (("dep", "📥 To‘ldirish"), ("wd", "📤 Yechish"), ("led", "📒 Hammasi")):
        mark = "• " if k == kind else ""
        b.button(text=f"{mark}{label}", callback_data=HistoryCb(kind=k, status=status))
    for st, label in (("all", "Barchasi"), ("pending", "⏳"), ("ok", "✅"), ("fail", "❌")):
        mark = "• " if st == status else ""
        b.button(text=f"{mark}{label}", callback_data=HistoryCb(kind=kind, status=st))
    nav = 0
    if page > 0:
        b.button(text="◀️", callback_data=HistoryCb(kind=kind, status=status, page=page - 1))
        nav += 1
    if has_next:
        b.button(text="▶️", callback_data=HistoryCb(kind=kind, status=status, page=page + 1))
        nav += 1
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="wallet"))
    b.adjust(3, 4, *([nav] if nav else []), 1)
    return b.as_markup()


def bonus_kb(vip: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_PROMO, callback_data=BonusCb(action="promo"))
    if vip:
        b.button(text=texts.BTN_VIP, callback_data=BonusCb(action="vip"))
    b.button(text=texts.BTN_REFERRAL, callback_data=BonusCb(action="ref"))
    b.button(text=texts.BTN_BACK, callback_data=MenuCb(action="back"))
    b.adjust(1)
    return b.as_markup()


def referral_kb(link: str) -> InlineKeyboardMarkup:
    share = f"https://t.me/share/url?url={quote(link)}&text={quote(texts.REFERRAL_SHARE_TEXT)}"
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text=texts.BTN_REF_SHARE, url=share))
    b.row(
        InlineKeyboardButton(text=texts.BTN_REF_TOP, callback_data=BonusCb(action="top").pack()),
        InlineKeyboardButton(
            text=texts.BTN_REF_TOP_10D, callback_data=BonusCb(action="top10d").pack()
        ),
    )
    b.row(
        InlineKeyboardButton(
            text=texts.BTN_REF_FRIENDS, callback_data=BonusCb(action="friends").pack()
        )
    )
    b.row(
        InlineKeyboardButton(
            text=texts.BTN_REF_WITHDRAW, callback_data=BonusCb(action="refwd").pack()
        )
    )
    b.row(InlineKeyboardButton(text=texts.BTN_BACK, callback_data=BonusCb(action="menu").pack()))
    return b.as_markup()


def bonus_back_kb(
    action: str = "menu", page: int | None = None, has_next: bool = False
) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if page is not None:
        if page > 0:
            b.button(text="◀️", callback_data=BonusCb(action="friends", page=page - 1))
        if has_next:
            b.button(text="▶️", callback_data=BonusCb(action="friends", page=page + 1))
    b.button(text=texts.BTN_BACK, callback_data=BonusCb(action=action))
    b.adjust(2, 1)
    return b.as_markup()


def subscription_kb(channels: list[RequiredChannel]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for channel in channels:
        url = channel.invite_link or f"https://t.me/{channel.username}"
        b.row(InlineKeyboardButton(text=f"📢 {channel.title}", url=url))
    b.row(
        InlineKeyboardButton(text=texts.BTN_CHECK_SUB, callback_data=SubCb(action="check").pack())
    )
    return b.as_markup()
