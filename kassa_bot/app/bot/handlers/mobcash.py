"""Mob-Cash oqimlari: ➕ Hisob/Hamyon to‘ldirish (P2P noyob summa) va ➖ Pul chiqarish.

Hisob to‘ldirish o‘yin akkauntiga (Mob-Cash), hamyon to‘ldirish esa bot hamyoniga tushadi.
📤 Kartaga yechish (MenuCb "withdraw") bu routerda ushlanmaydi — u hamyon oqimida qoladi.
`mobcash_enabled` sozlamasi o‘chiq bo‘lsa, tugmalar eski hamyon oqimiga tushadi
(bu router ulardan oldin ulanadi va `MobCashOn` filtri bilan ishlaydi).
"""

from __future__ import annotations

import re
from contextlib import suppress
from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.bot.keyboards.callbacks import McCb, MenuCb
from app.bot.keyboards.user import QUICK_AMOUNTS, cancel_kb, wallet_kb
from app.bot.states import (
    McDepositStates,
    McTopupStates,
    McWalletGameStates,
    McWithdrawStates,
)
from app.bot.utils import edit_or_send, esc, safe_delete
from app.core.enums import MobcashWithdrawalStatus, P2PDepositStatus, P2PDepositTarget
from app.core.errors import DomainError
from app.core.money import fmt_money, parse_amount, percent_of
from app.core.permissions import Perm
from app.core.utils import fmt_dt
from app.models import P2PCard, P2PDeposit, User
from app.services.container import Services
from app.services.mobcash_withdrawals import WithdrawQuote, mask_card
from app.services.settings import RuntimeSettings

router = Router(name="mobcash")

PAYER_RE = re.compile(r"^\d{5,15}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{4,64}$")

# To‘ldirish oqimlari: "dep" — karta orqali o‘yin hisobiga, "wgame" — hamyondan o‘yin
# hisobiga, "wd" — o‘yin hisobidan yechish. Har oqim o‘z FSM guruhida yuradi.
FLOW_STATES = {
    "dep": McDepositStates,
    "wgame": McWalletGameStates,
    "wd": McWithdrawStates,
}
FLOW_SAVED_ID = {
    "dep": texts.MC_DEP_SAVED_ID,
    "wgame": texts.MC_WGAME_SAVED_ID,
    "wd": texts.MC_WD_SAVED_ID,
}
FLOW_ASK_ID = {
    "dep": texts.MC_DEP_ASK_ID,
    "wgame": texts.MC_WGAME_ASK_ID,
    "wd": texts.MC_WD_ASK_ID,
}
FLOW_BM_TITLE = {
    "dep": texts.MC_CHOOSE_BOOKMAKER_DEP,
    "wgame": texts.MC_CHOOSE_BOOKMAKER_WGAME,
    "wd": texts.MC_CHOOSE_BOOKMAKER_WD,
}


class MobCashOn(Filter):
    async def __call__(self, event: TelegramObject, rt: RuntimeSettings | None = None) -> bool:
        return bool(rt is not None and rt.mobcash_enabled)


def normalize_payer(text: str | None) -> str | None:
    value = re.sub(r"[\s\-]", "", text or "")
    return value if PAYER_RE.match(value) else None


def normalize_card(text: str | None) -> str | None:
    digits = re.sub(r"\D", "", text or "")
    return digits if len(digits) == 16 else None


# ============================================================================ klaviaturalar
def saved_id_kb(flow: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_MC_SAME_ID, callback_data=McCb(action=f"{flow}_same"))
    b.button(text=texts.BTN_MC_OTHER_ID, callback_data=McCb(action=f"{flow}_other"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(1)
    return b.as_markup()


def amounts_kb(action: str = "dep_amt") -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in QUICK_AMOUNTS:
        b.button(text=fmt_money(value), callback_data=McCb(action=action, value=value))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(2, 2, 1)
    return b.as_markup()


def deposit_kb(deposit: P2PDeposit) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_CHECK_STATUS, callback_data=McCb(action="dep_check", id=deposit.id))
    b.button(text=texts.BTN_CANCEL, callback_data=McCb(action="dep_cancel", id=deposit.id))
    b.adjust(1)
    return b.as_markup()


def deposit_text(deposit: P2PDeposit, card: P2PCard | None, rt: RuntimeSettings) -> str:
    amount = f"{int(deposit.unique_amount):,}".replace(",", " ")
    if deposit.unique_amount != deposit.unique_amount.to_integral_value():
        amount = f"{deposit.unique_amount:,.2f}".replace(",", " ")
    credit = deposit.credit_amount or (
        deposit.unique_amount - percent_of(deposit.unique_amount, rt.deposit_fee_percent)
    )
    common = dict(
        id=deposit.id,
        card=card.pretty if card else "—",
        holder=esc(card.holder if card and card.holder else "—"),
        amount=amount,
        credit=fmt_money(credit),
        expires=fmt_dt(deposit.expires_at, rt.timezone),
    )
    if deposit.target == P2PDepositTarget.WALLET:
        return texts.MC_TOPUP_CREATED.format(**common)
    return texts.MC_DEP_CREATED.format(
        **common,
        payer_id=esc(deposit.payer_id),
        nickname=esc(deposit.payer_nickname or "—"),
    )


# ============================================================================ kantora tanlash
async def _reply(target: Message | CallbackQuery, text: str, markup: Any = None) -> None:
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup, disable_web_page_preview=True)


def _bm_line(name: str | None) -> str:
    return f"🏢 Kantora: <b>{esc(name)}</b>\n\n" if name else ""


async def _choose_bookmaker(
    target: Message | CallbackQuery, state: FSMContext, svc: Services, user: User, flow: str
) -> None:
    """Faol kantora bitta bo‘lsa — o‘zi tanlanadi, bir nechta bo‘lsa — ro‘yxat ko‘rsatiladi."""
    active = await svc.bookmakers.list_active()
    if not active:
        if await svc.bookmakers.legacy_available():
            await _ask_payer(target, state, user, flow, None, None)
            return
        await _reply(target, texts.MC_NO_BOOKMAKERS, cancel_kb())
        return
    if len(active) == 1:
        await _ask_payer(target, state, user, flow, active[0].id, active[0].name)
        return
    b = InlineKeyboardBuilder()
    for bm in active:
        b.button(text=f"🏢 {bm.name}", callback_data=McCb(action=f"{flow}_bm", id=bm.id))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(1)
    await _reply(target, FLOW_BM_TITLE[flow], b.as_markup())


async def _ask_payer(
    target: Message | CallbackQuery,
    state: FSMContext,
    user: User,
    flow: str,
    bookmaker_id: int | None,
    bookmaker_name: str | None,
) -> None:
    await state.set_state(FLOW_STATES[flow].payer_id)
    await state.update_data(bm_id=bookmaker_id, bm_name=bookmaker_name)
    saved = user.payer_id_for(bookmaker_id)
    head = _bm_line(bookmaker_name)
    if saved:
        await _reply(
            target, head + FLOW_SAVED_ID[flow].format(payer_id=esc(saved)), saved_id_kb(flow)
        )
    else:
        await _reply(target, head + FLOW_ASK_ID[flow], cancel_kb())


@router.callback_query(
    McCb.filter(F.action.in_({"dep_bm", "wgame_bm", "wd_bm"})), MobCashOn()
)
async def bookmaker_picked(
    call: CallbackQuery, callback_data: McCb, state: FSMContext, svc: Services, user: User
) -> None:
    try:
        bm = await svc.bookmakers.get_active(callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    await _ask_payer(call, state, user, callback_data.action.removesuffix("_bm"), bm.id, bm.name)


@router.callback_query(
    McCb.filter(F.action.in_({"dep_other", "wgame_other", "wd_other"})), MobCashOn()
)
async def other_id_ask(call: CallbackQuery, callback_data: McCb, state: FSMContext) -> None:
    flow = callback_data.action.removesuffix("_other")
    await state.set_state(FLOW_STATES[flow].payer_id)
    await call.answer()
    await edit_or_send(call, FLOW_ASK_ID[flow], cancel_kb())


# ============================================================================ ➕ to‘ldirish
@router.message(F.text == texts.BTN_DEPOSIT, MobCashOn())
async def dep_start(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    pending = await svc.p2p.pending_for_user(user, P2PDepositTarget.GAME)
    if pending is not None:
        await message.answer(
            deposit_text(pending, await svc.p2p.card_for(pending), rt),
            reply_markup=deposit_kb(pending),
        )
        return
    await _choose_bookmaker(message, state, svc, user, "dep")


@router.callback_query(MenuCb.filter(F.action == "deposit"), MobCashOn())
async def cb_dep_start(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await call.answer()
    await state.clear()
    pending = await svc.p2p.pending_for_user(user, P2PDepositTarget.GAME)
    if pending is not None:
        await edit_or_send(
            call,
            deposit_text(pending, await svc.p2p.card_for(pending), rt),
            deposit_kb(pending),
        )
        return
    await _choose_bookmaker(call, state, svc, user, "dep")


@router.callback_query(MenuCb.filter(F.action == "topup"), MobCashOn())
async def cb_topup_start(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await call.answer()
    await state.clear()
    pending = await svc.p2p.pending_for_user(user, P2PDepositTarget.WALLET)
    if pending is not None:
        await edit_or_send(
            call,
            deposit_text(pending, await svc.p2p.card_for(pending), rt),
            deposit_kb(pending),
        )
        return
    await state.set_state(McTopupStates.amount)
    await edit_or_send(
        call,
        texts.MC_TOPUP_ASK_AMOUNT.format(
            min=fmt_money(rt.deposit_min), max=fmt_money(rt.deposit_max)
        ),
        amounts_kb("top_amt"),
    )


async def _dep_check_payer(
    message: Message, state: FSMContext, svc: Services, rt: RuntimeSettings, payer_id: str
) -> None:
    wait = await message.answer("🔎 Tekshirilmoqda...")
    data = await state.get_data()
    try:
        nickname = await svc.p2p.check_payer(payer_id, data.get("bm_id"))
    except DomainError as exc:
        await state.set_state(McDepositStates.payer_id)
        await _edit(wait, exc.message, cancel_kb())
        return
    await state.set_state(McDepositStates.amount)
    await state.update_data(mc_payer=payer_id, mc_nick=nickname)
    await _edit(
        wait,
        _bm_line(data.get("bm_name"))
        + texts.MC_DEP_ASK_AMOUNT.format(
            nickname=esc(nickname),
            payer_id=esc(payer_id),
            min=fmt_money(rt.deposit_min),
            max=fmt_money(rt.deposit_max),
        ),
        amounts_kb(),
    )


@router.callback_query(McCb.filter(F.action == "dep_same"), MobCashOn())
async def dep_same(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await call.answer()
    saved = user.payer_id_for((await state.get_data()).get("bm_id"))
    if not saved or not isinstance(call.message, Message):
        await state.set_state(McDepositStates.payer_id)
        await edit_or_send(call, texts.MC_DEP_ASK_ID, cancel_kb())
        return
    await safe_delete(call.message)
    await _dep_check_payer(call.message, state, svc, rt, saved)


@router.message(McDepositStates.payer_id, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def dep_payer(
    message: Message, state: FSMContext, svc: Services, rt: RuntimeSettings
) -> None:
    payer_id = normalize_payer(message.text)
    if payer_id is None:
        await message.answer(texts.MC_ID_INVALID, reply_markup=cancel_kb())
        return
    await _dep_check_payer(message, state, svc, rt, payer_id)


async def _dep_create(
    message: Message,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
    amount: Decimal,
) -> None:
    data = await state.get_data()
    payer_id, nickname = data.get("mc_payer"), data.get("mc_nick")
    if not payer_id:
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    try:
        deposit = await svc.p2p.create(
            user, payer_id, nickname or "", amount, bookmaker_id=data.get("bm_id")
        )
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=amounts_kb())
        return
    await state.clear()
    sent = await message.answer(
        _bm_line(data.get("bm_name")) + deposit_text(deposit, await svc.p2p.card_for(deposit), rt),
        reply_markup=deposit_kb(deposit),
    )
    await svc.p2p.set_message_id(deposit, sent.message_id)


@router.callback_query(McDepositStates.amount, McCb.filter(F.action == "dep_amt"))
async def dep_quick_amount(
    call: CallbackQuery,
    callback_data: McCb,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        await _dep_create(call.message, state, svc, user, rt, Decimal(callback_data.value))


@router.message(McDepositStates.amount, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def dep_amount(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID, reply_markup=amounts_kb())
        return
    await _dep_create(message, state, svc, user, rt, amount)


# ---------------------------------------------------- 🎮 hamyondan o‘yin hisobiga o‘tkazish
@router.callback_query(MenuCb.filter(F.action == "wgame"), MobCashOn())
async def cb_wgame_start(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await call.answer()
    await state.clear()
    wallet = await svc.users.get_wallet(user.id)
    if wallet.available < rt.deposit_min:
        await edit_or_send(
            call,
            texts.MC_WGAME_LOW_BALANCE.format(
                available=fmt_money(wallet.available), min=fmt_money(rt.deposit_min)
            ),
            wallet_kb(),
        )
        return
    await _choose_bookmaker(call, state, svc, user, "wgame")


@router.callback_query(McCb.filter(F.action == "wgame_same"), MobCashOn())
async def wgame_same(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    saved = user.payer_id_for((await state.get_data()).get("bm_id"))
    if not saved:
        await state.set_state(McWalletGameStates.payer_id)
        await edit_or_send(call, texts.MC_WGAME_ASK_ID, cancel_kb())
        return
    await safe_delete(call.message)
    await _wgame_check_payer(call.message, state, svc, user, rt, saved)


async def _wgame_check_payer(
    message: Message,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
    payer_id: str,
) -> None:
    wait = await message.answer("🔎 Tekshirilmoqda...")
    data = await state.get_data()
    try:
        nickname = await svc.p2p.check_payer(payer_id, data.get("bm_id"))
    except DomainError as exc:
        await state.set_state(McWalletGameStates.payer_id)
        await _edit(wait, exc.message, cancel_kb())
        return
    wallet = await svc.users.get_wallet(user.id)
    await state.set_state(McWalletGameStates.amount)
    await state.update_data(mc_payer=payer_id, mc_nick=nickname)
    await _edit(
        wait,
        _bm_line(data.get("bm_name"))
        + texts.MC_WGAME_ASK_AMOUNT.format(
            nickname=esc(nickname),
            payer_id=esc(payer_id),
            balance=fmt_money(wallet.available),
            min=fmt_money(rt.deposit_min),
            max=fmt_money(rt.deposit_max),
        ),
        amounts_kb("wgame_amt"),
    )


@router.message(McWalletGameStates.payer_id, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def wgame_payer(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    payer_id = normalize_payer(message.text)
    if payer_id is None:
        await message.answer(texts.MC_ID_INVALID, reply_markup=cancel_kb())
        return
    await _wgame_check_payer(message, state, svc, user, rt, payer_id)


async def _wgame_to_confirm(
    message: Message,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
    amount: Decimal,
) -> None:
    data = await state.get_data()
    if not data.get("mc_payer"):
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    if not rt.deposit_min <= amount <= rt.deposit_max:
        await message.answer(
            texts.AMOUNT_OUT_OF_RANGE.format(
                min=fmt_money(rt.deposit_min), max=fmt_money(rt.deposit_max)
            ),
            reply_markup=amounts_kb("wgame_amt"),
        )
        return
    wallet = await svc.users.get_wallet(user.id)
    if wallet.available < amount:
        await message.answer(
            texts.WITHDRAW_INSUFFICIENT.format(available=fmt_money(wallet.available)),
            reply_markup=amounts_kb("wgame_amt"),
        )
        return
    await state.set_state(McWalletGameStates.confirm)
    await state.update_data(wgame_amount=str(amount))
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_CONFIRM, callback_data=McCb(action="wgame_go"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(2)
    await message.answer(
        _bm_line(data.get("bm_name"))
        + texts.MC_WGAME_CONFIRM.format(
            payer_id=esc(data["mc_payer"]),
            nickname=esc(data.get("mc_nick") or "—"),
            amount=fmt_money(amount),
            balance=fmt_money(wallet.available - amount),
        ),
        reply_markup=b.as_markup(),
    )


@router.callback_query(McWalletGameStates.amount, McCb.filter(F.action == "wgame_amt"))
async def wgame_quick_amount(
    call: CallbackQuery,
    callback_data: McCb,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        await _wgame_to_confirm(call.message, state, svc, user, rt, Decimal(callback_data.value))


@router.message(McWalletGameStates.amount, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def wgame_amount(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID, reply_markup=amounts_kb("wgame_amt"))
        return
    await _wgame_to_confirm(message, state, svc, user, rt, amount)


@router.callback_query(McWalletGameStates.confirm, McCb.filter(F.action == "wgame_go"))
async def wgame_go(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User
) -> None:
    data = await state.get_data()
    await state.clear()  # ikki marta bosilsa qayta yuborilmasin
    payer_id, raw_amount = data.get("mc_payer"), data.get("wgame_amount")
    if not payer_id or not raw_amount:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, texts.MC_WGAME_PROCESSING)
    amount = Decimal(raw_amount)
    try:
        deposit = await svc.p2p.create_wallet_funded(
            user, payer_id, data.get("mc_nick") or "", amount, bookmaker_id=data.get("bm_id")
        )
    except DomainError as exc:
        await edit_or_send(call, exc.message)
        return
    outcome = await svc.p2p.credit(deposit.id)
    event = outcome.event if outcome is not None else "retry"
    wallet = await svc.users.get_wallet(user.id)
    if event == "credited":
        await edit_or_send(
            call,
            texts.MC_WGAME_DONE.format(
                id=deposit.id,
                amount=fmt_money(deposit.credit_amount or amount),
                payer_id=esc(deposit.payer_id),
                balance=fmt_money(wallet.available),
            ),
        )
    elif event == "review":
        await edit_or_send(call, texts.MC_WGAME_REVIEW.format(id=deposit.id))
        admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
        await svc.notifier.p2p_admin_review(
            deposit, admins, await svc.bookmakers.name_of(deposit.bookmaker_id)
        )
    else:
        # Tarmoq xatosi — fon jarayoni (credit_due) summani qayta yuboradi.
        await edit_or_send(call, texts.MC_WGAME_PENDING.format(id=deposit.id))


# ------------------------------------------------------------------------ ➕ hamyon to‘ldirish
async def _topup_create(
    message: Message,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
    amount: Decimal,
) -> None:
    try:
        deposit = await svc.p2p.create(user, "", "", amount, target=P2PDepositTarget.WALLET)
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=amounts_kb("top_amt"))
        return
    await state.clear()
    sent = await message.answer(
        deposit_text(deposit, await svc.p2p.card_for(deposit), rt),
        reply_markup=deposit_kb(deposit),
    )
    await svc.p2p.set_message_id(deposit, sent.message_id)


@router.callback_query(McTopupStates.amount, McCb.filter(F.action == "top_amt"))
async def top_quick_amount(
    call: CallbackQuery,
    callback_data: McCb,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        await _topup_create(call.message, state, svc, user, rt, Decimal(callback_data.value))


@router.message(McTopupStates.amount, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def top_amount(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID, reply_markup=amounts_kb("top_amt"))
        return
    await _topup_create(message, state, svc, user, rt, amount)


@router.callback_query(McCb.filter(F.action == "dep_check"))
async def dep_check(call: CallbackQuery, callback_data: McCb, svc: Services, user: User) -> None:
    try:
        deposit = await svc.p2p.get_for_user(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(
        texts.MC_DEP_STATUS_LINE.format(
            id=deposit.id, status=texts.mc_status(deposit.target, deposit.status)
        ),
        show_alert=True,
    )
    if deposit.status != P2PDepositStatus.PENDING and isinstance(call.message, Message):
        with suppress(TelegramBadRequest):
            await call.message.edit_reply_markup(reply_markup=None)


@router.callback_query(McCb.filter(F.action == "dep_cancel"))
async def dep_cancel(call: CallbackQuery, callback_data: McCb, svc: Services, user: User) -> None:
    try:
        deposit = await svc.p2p.cancel(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, texts.MC_DEP_CANCELLED.format(id=deposit.id))


# ===================================================================== ➖ yechish (o‘yin hisobidan)
@router.message(F.text == texts.BTN_WITHDRAW, MobCashOn())
async def wd_start(message: Message, state: FSMContext, svc: Services, user: User) -> None:
    await state.clear()
    await _choose_bookmaker(message, state, svc, user, "wd")


async def _wd_ask_code(message: Message, state: FSMContext, payer_id: str) -> None:
    await state.set_state(McWithdrawStates.code)
    await state.update_data(mc_payer=payer_id)
    await message.answer(
        texts.MC_WD_ASK_CODE.format(payer_id=esc(payer_id)), reply_markup=cancel_kb()
    )


@router.callback_query(McCb.filter(F.action == "wd_same"), MobCashOn())
async def wd_same(call: CallbackQuery, state: FSMContext, user: User) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    saved = user.payer_id_for((await state.get_data()).get("bm_id"))
    if not saved:
        await state.set_state(McWithdrawStates.payer_id)
        await edit_or_send(call, texts.MC_WD_ASK_ID, cancel_kb())
        return
    await safe_delete(call.message)
    await _wd_ask_code(call.message, state, saved)


@router.message(McWithdrawStates.payer_id, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def wd_payer(message: Message, state: FSMContext) -> None:
    payer_id = normalize_payer(message.text)
    if payer_id is None:
        await message.answer(texts.MC_ID_INVALID, reply_markup=cancel_kb())
        return
    await _wd_ask_code(message, state, payer_id)


def _card_kb(user: User) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if user.payout_card_number:
        b.button(
            text=f"💳 {mask_card(user.payout_card_number)}",
            callback_data=McCb(action="wd_card_saved"),
        )
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(1)
    return b.as_markup()


@router.message(McWithdrawStates.code, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def wd_code(message: Message, state: FSMContext, svc: Services) -> None:
    code = (message.text or "").strip()
    await safe_delete(message)  # yechish kodi chatda qolmasin
    if not CODE_RE.match(code):
        await message.answer(texts.MC_WD_CODE_INVALID, reply_markup=cancel_kb())
        return
    data = await state.get_data()
    payer_id = data.get("mc_payer")
    if not payer_id:
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    try:
        preview = await svc.mcwd.supports_preview(data.get("bm_id"))
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=cancel_kb())
        return
    if not preview:
        # Summani oldindan ko‘rish yo‘q — u Payout bajarilganda aniqlanadi.
        await state.set_state(McWithdrawStates.destination)
        await state.update_data(mc_code=code, mc_unknown=True)
        await message.answer(texts.MC_WD_ASK_DEST_ANY, reply_markup=_dest_kb())
        return
    # Kod shu yerda tekshiriladi: quote xato kodda MC_WD_NOT_FOUND ko'taradi.
    wait = await message.answer("🔎 Tekshirilmoqda...")
    try:
        quote = await svc.mcwd.quote(payer_id, code, data.get("bm_id"))
    except DomainError as exc:
        await _edit(wait, exc.message, cancel_kb())
        return
    await state.set_state(McWithdrawStates.destination)
    await state.update_data(
        mc_code=code,
        mc_unknown=False,
        mc_amount=str(quote.amount),
        mc_fee=str(quote.fee),
        mc_payout=str(quote.payout),
    )
    await _edit(
        wait,
        texts.MC_WD_ASK_DEST.format(
            amount=fmt_money(quote.amount), fee=fmt_money(quote.fee), payout=fmt_money(quote.payout)
        ),
        _dest_kb(),
    )


def _dest_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_WD_DEST_CARD, callback_data=McCb(action="wd_dest_card"))
    b.button(text=texts.BTN_WD_DEST_WALLET, callback_data=McCb(action="wd_dest_wallet"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(2, 1)
    return b.as_markup()


@router.callback_query(McWithdrawStates.destination, McCb.filter(F.action == "wd_dest_card"))
async def wd_dest_card(call: CallbackQuery, state: FSMContext, user: User) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    data = await state.get_data()
    if not data.get("mc_code"):
        await state.clear()
        await edit_or_send(call, texts.EXPIRED_ACTION)
        return
    await state.set_state(McWithdrawStates.card)
    await state.update_data(mc_dest="card")
    if data.get("mc_unknown"):
        text = texts.MC_WD_ASK_CARD_ANY
    else:
        text = texts.MC_WD_ASK_CARD.format(
            amount=fmt_money(Decimal(data["mc_amount"])),
            fee=fmt_money(Decimal(data["mc_fee"])),
            payout=fmt_money(Decimal(data["mc_payout"])),
        )
    await _edit(call.message, text, _card_kb(user))


@router.callback_query(McWithdrawStates.destination, McCb.filter(F.action == "wd_dest_wallet"))
async def wd_dest_wallet(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    if not isinstance(call.message, Message):
        return
    data = await state.get_data()
    if not data.get("mc_code"):
        await state.clear()
        await edit_or_send(call, texts.EXPIRED_ACTION)
        return
    await state.update_data(mc_dest="wallet")
    await _wd_confirm(call.message, state, "")


async def _wd_confirm(message: Message, state: FSMContext, card: str) -> None:
    data = await state.get_data()
    if not data.get("mc_code"):
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    dest = data.get("mc_dest", "card")
    await state.set_state(McWithdrawStates.confirm)
    await state.update_data(mc_card=card, mc_dest=dest)
    b = InlineKeyboardBuilder()
    b.button(text=texts.BTN_CONFIRM, callback_data=McCb(action="wd_confirm"))
    b.button(text=texts.BTN_CANCEL, callback_data=MenuCb(action="cancel"))
    b.adjust(2)
    if data.get("mc_unknown"):
        if dest == "wallet":
            body = texts.MC_WD_CONFIRM_WALLET_ANY.format(payer_id=esc(data["mc_payer"]))
        else:
            body = texts.MC_WD_CONFIRM_ANY.format(
                payer_id=esc(data["mc_payer"]), card=mask_card(card)
            )
    else:
        common = dict(
            payer_id=esc(data["mc_payer"]),
            amount=fmt_money(Decimal(data["mc_amount"])),
            fee=fmt_money(Decimal(data["mc_fee"])),
            payout=fmt_money(Decimal(data["mc_payout"])),
        )
        if dest == "wallet":
            body = texts.MC_WD_CONFIRM_WALLET.format(**common)
        else:
            body = texts.MC_WD_CONFIRM.format(**common, card=mask_card(card))
    await message.answer(_bm_line(data.get("bm_name")) + body, reply_markup=b.as_markup())


@router.callback_query(McWithdrawStates.card, McCb.filter(F.action == "wd_card_saved"))
async def wd_card_saved(call: CallbackQuery, state: FSMContext, user: User) -> None:
    await call.answer()
    if user.payout_card_number and isinstance(call.message, Message):
        await _wd_confirm(call.message, state, user.payout_card_number)


@router.message(McWithdrawStates.card, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def wd_card(message: Message, state: FSMContext, user: User) -> None:
    card = normalize_card(message.text)
    if card is None:
        await message.answer(texts.MC_WD_CARD_INVALID, reply_markup=_card_kb(user))
        return
    await _wd_confirm(message, state, card)


@router.callback_query(McWithdrawStates.confirm, McCb.filter(F.action == "wd_confirm"))
async def wd_execute(call: CallbackQuery, state: FSMContext, svc: Services, user: User) -> None:
    data: dict[str, Any] = await state.get_data()
    await state.clear()  # ikki marta bosilsa ham qayta yuborilmasin
    if not data.get("mc_payer") or not data.get("mc_code"):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    to_wallet = data.get("mc_dest") == "wallet"
    unknown = bool(data.get("mc_unknown"))
    if not to_wallet and not data.get("mc_card"):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    if not unknown and not all(
        data.get(k) for k in ("mc_amount", "mc_fee", "mc_payout")
    ):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, texts.MC_WD_PROCESSING)
    quote = None
    if not unknown:
        quote = WithdrawQuote(
            amount=Decimal(data["mc_amount"]),
            fee=Decimal(data["mc_fee"]),
            payout=Decimal(data["mc_payout"]),
        )
    try:
        wd = await svc.mcwd.execute(
            user,
            data["mc_payer"],
            data["mc_code"],
            quote,
            data.get("mc_card") or "",
            bookmaker_id=data.get("bm_id"),
            to_wallet=to_wallet,
        )
    except DomainError as exc:
        await edit_or_send(call, exc.message)
        return
    if wd.status == MobcashWithdrawalStatus.REVIEW:
        text = texts.MC_WD_REVIEW.format(id=wd.id)
    elif to_wallet and wd.status == MobcashWithdrawalStatus.PAID:
        text = texts.MC_WD_WALLET_DONE.format(id=wd.id, payout=fmt_money(wd.payout_amount))
    else:
        text = texts.MC_WD_CREATED.format(
            id=wd.id, payout=fmt_money(wd.payout_amount), card=mask_card(wd.card_number)
        )
    await edit_or_send(call, text)
    if not (to_wallet and wd.status == MobcashWithdrawalStatus.PAID):
        admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
        await svc.notifier.mcwd_new(wd, admins, await svc.bookmakers.name_of(wd.bookmaker_id))


# ============================================================================ 📋 tarix
@router.callback_query(McCb.filter(F.action == "history"))
async def history(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    deposits = await svc.p2p.list_for_user(user, limit=5)
    withdrawals = await svc.mcwd.list_for_user(user, limit=5)
    lines = [texts.MC_HISTORY_TITLE, ""]
    for d in deposits:
        who = (
            "🏠 Hamyon"
            if d.target == P2PDepositTarget.WALLET
            else f"{esc(await svc.bookmakers.name_of(d.bookmaker_id) or 'Mob-Cash')} • "
            f"ID {esc(d.payer_id)}"
        )
        lines.append(
            f"📥 #{d.id} • {fmt_money(d.unique_amount)} • "
            f"{texts.mc_status(d.target, d.status)}\n"
            f"    {fmt_dt(d.created_at, rt.timezone)} • {who}"
        )
    for w in withdrawals:
        dest = mask_card(w.card_number) if w.card_number else "💎 Hamyon"
        lines.append(
            f"📤 #{w.id} • {fmt_money(w.payout_amount)} • "
            f"{texts.mc_wd_status(w.status, w.card_number)}\n"
            f"    {fmt_dt(w.created_at, rt.timezone)} • {dest}"
        )
    await call.answer()
    text = "\n".join(lines) if deposits or withdrawals else texts.MC_HISTORY_EMPTY
    await edit_or_send(call, text, cancel_kb())


async def _edit(message: Message, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
