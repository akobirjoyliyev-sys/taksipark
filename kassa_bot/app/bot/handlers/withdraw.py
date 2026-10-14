from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.bot.keyboards.callbacks import CardCb, MenuCb, WdCb
from app.bot.keyboards.user import (
    back_kb,
    cancel_kb,
    card_select_kb,
    link_kb,
    my_requests_kb,
    withdraw_amount_kb,
    withdraw_confirm_kb,
)
from app.bot.states import WithdrawStates
from app.bot.utils import edit_or_send, esc, safe_delete, with_link_fallback
from app.core.enums import WithdrawalStatus
from app.core.errors import DomainError
from app.core.money import fmt_money, parse_amount
from app.core.permissions import Perm
from app.core.utils import fmt_dt
from app.models import User
from app.services.container import Services
from app.services.settings import RuntimeSettings

router = Router(name="withdraw")


async def _overview(
    svc: Services, user: User, rt: RuntimeSettings
) -> tuple[str, InlineKeyboardMarkup]:
    wallet = await svc.users.get_wallet(user.id)
    cards = await svc.cards.list_page(user)
    if not cards:
        text = texts.WITHDRAW_NO_CARDS
    else:
        text = texts.WITHDRAW_CHOOSE_CARD.format(
            available=fmt_money(wallet.available),
            min=fmt_money(rt.withdraw_min),
            max=fmt_money(rt.withdraw_max),
            fee=rt.withdraw_fee_percent,
        )
    if wallet.available < rt.withdraw_min:
        text += "\n\n" + texts.WITHDRAW_LOW_BALANCE.format(
            min=fmt_money(rt.withdraw_min), available=fmt_money(wallet.available)
        )
    return text, card_select_kb(cards)


@router.message(F.text == texts.BTN_WITHDRAW)
async def start_withdraw(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    text, markup = await _overview(svc, user, rt)
    await message.answer(text, reply_markup=markup)


@router.callback_query(MenuCb.filter(F.action == "withdraw"))
async def cb_withdraw(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    await call.answer()
    text, markup = await _overview(svc, user, rt)
    await edit_or_send(call, text, markup)


@router.callback_query(CardCb.filter(F.action == "bind"))
async def cb_bind(call: CallbackQuery, state: FSMContext, svc: Services, user: User) -> None:
    if not await svc.cards.binding_providers():
        # Provayder yo‘q — karta raqami chatda olinadi (qo‘lda o‘tkazish rejimi).
        await call.answer()
        await state.set_state(WithdrawStates.card)
        if isinstance(call.message, Message):
            await call.message.answer(texts.WITHDRAW_ASK_CARD, reply_markup=cancel_kb())
        return
    try:
        url = await svc.cards.start_binding(user)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.answer(
            with_link_fallback(texts.CARD_BIND_TEXT, url),
            reply_markup=link_kb(texts.BTN_BIND_CARD, url),
            disable_web_page_preview=True,
        )


@router.message(WithdrawStates.card, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def on_card(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    try:
        card = await svc.cards.add_manual_card(user, message.text or "")
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=cancel_kb())
        return
    await safe_delete(message)  # karta raqami chatda qolmasin
    await state.clear()
    await message.answer(texts.CARD_BOUND.format(mask=card.masked_pan))
    text, markup = await _overview(svc, user, rt)
    await message.answer(text, reply_markup=markup)


@router.callback_query(CardCb.filter(F.action == "pick"))
async def cb_pick_card(
    call: CallbackQuery,
    callback_data: CardCb,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
) -> None:
    cards = {c.id: c for c in await svc.cards.list_page(user)}
    card = cards.get(callback_data.id)
    if card is None:
        await call.answer("Karta topilmadi.", show_alert=True)
        return
    wallet = await svc.users.get_wallet(user.id)
    await state.set_state(WithdrawStates.amount)
    await state.update_data(card_id=card.id, card_mask=card.masked_pan)
    await call.answer()
    await edit_or_send(
        call,
        texts.WITHDRAW_ASK_AMOUNT.format(
            card=card.masked_pan,
            available=fmt_money(wallet.available),
            min=fmt_money(rt.withdraw_min),
            max=fmt_money(rt.withdraw_max),
        ),
        withdraw_amount_kb(),
    )


async def _to_confirm(
    message: Message, amount: Decimal, state: FSMContext, svc: Services, user: User
) -> None:
    data = await state.get_data()
    if "card_id" not in data:
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    try:
        fee, net = await svc.withdrawals.validate_amount(user, amount)
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=withdraw_amount_kb())
        return
    await state.set_state(WithdrawStates.confirm)
    await state.update_data(amount=str(amount))
    await message.answer(
        texts.WITHDRAW_CONFIRM.format(
            card=data["card_mask"],
            amount=fmt_money(amount),
            fee=fmt_money(fee),
            net=fmt_money(net),
        ),
        reply_markup=withdraw_confirm_kb(),
    )


@router.message(WithdrawStates.amount, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def on_amount(message: Message, state: FSMContext, svc: Services, user: User) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID, reply_markup=withdraw_amount_kb())
        return
    await _to_confirm(message, amount, state, svc, user)


@router.callback_query(WithdrawStates.amount, WdCb.filter(F.action == "all"))
async def cb_all(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    wallet = await svc.users.get_wallet(user.id)
    await call.answer()
    if isinstance(call.message, Message):
        await _to_confirm(call.message, min(wallet.available, rt.withdraw_max), state, svc, user)


@router.callback_query(WithdrawStates.confirm, WdCb.filter(F.action == "confirm"))
async def cb_confirm(call: CallbackQuery, state: FSMContext, svc: Services, user: User) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        withdrawal = await svc.withdrawals.create(
            user, int(data["card_id"]), Decimal(data["amount"])
        )
    except (KeyError, ValueError):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    pan = await svc.cards.manual_pan(withdrawal.card_id)
    if pan:
        admins = await svc.admins.telegram_ids_with(Perm.WITHDRAW_PROCESS)
        await svc.notifier.wallet_withdrawal_new(withdrawal, user.telegram_id, pan, admins)
        await edit_or_send(
            call,
            texts.WITHDRAW_CREATED_MANUAL.format(
                id=withdrawal.id, net=fmt_money(withdrawal.net_amount)
            ),
            back_kb("withdraw"),
        )
        return
    await edit_or_send(
        call,
        texts.WITHDRAW_CREATED.format(
            id=withdrawal.id, status=texts.WITHDRAW_STATUS[withdrawal.status]
        ),
        back_kb("withdraw"),
    )


@router.callback_query(WdCb.filter(F.action.in_({"confirm", "all"})))
async def cb_stale(call: CallbackQuery) -> None:
    await call.answer(texts.EXPIRED_ACTION, show_alert=True)


@router.callback_query(WdCb.filter(F.action == "list"))
async def cb_list(call: CallbackQuery, svc: Services, user: User) -> None:
    items = await svc.withdrawals.list_for_user(user, limit=10)
    await call.answer()
    text = texts.MY_REQUESTS_TITLE if items else texts.NO_WITHDRAWALS
    await edit_or_send(call, text, my_requests_kb(items))


@router.callback_query(WdCb.filter(F.action == "view"))
async def cb_view(
    call: CallbackQuery, callback_data: WdCb, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    try:
        w = await svc.withdrawals.get_for_user(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    history = await svc.withdrawals.history(w.id)
    lines = []
    for h in history:
        status = texts.WITHDRAW_STATUS[WithdrawalStatus(h.to_status)]
        comment = f" — {esc(h.comment)}" if h.comment and h.actor_role != "worker" else ""
        lines.append(f"• {fmt_dt(h.created_at, rt.timezone)}: {status}{comment}")
    await call.answer()
    await edit_or_send(
        call,
        texts.WITHDRAW_DETAILS.format(
            id=w.id,
            amount=fmt_money(w.amount),
            fee=fmt_money(w.fee),
            net=fmt_money(w.net_amount),
            card=w.card_mask,
            status=texts.WITHDRAW_STATUS[w.status],
            created=fmt_dt(w.created_at, rt.timezone),
            history="\n".join(lines) or "—",
        ),
        my_requests_kb([]),
    )
