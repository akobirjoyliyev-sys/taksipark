from __future__ import annotations

from contextlib import suppress
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.bot.keyboards.callbacks import AmountCb, MenuCb, PaymentCb
from app.bot.keyboards.user import cancel_kb, payment_kb, topup_kb
from app.bot.states import DepositStates
from app.bot.utils import edit_or_send, with_link_fallback
from app.core.enums import PaymentStatus
from app.core.errors import DomainError
from app.core.money import fmt_money, parse_amount
from app.core.utils import fmt_dt
from app.models import Payment, User
from app.services.container import Services
from app.services.settings import RuntimeSettings

router = Router(name="deposit")


def _ask_text(rt: RuntimeSettings) -> str:
    return texts.DEPOSIT_ASK_AMOUNT.format(
        min=fmt_money(rt.deposit_min), max=fmt_money(rt.deposit_max)
    )


def payment_text(payment: Payment, rt: RuntimeSettings) -> str:
    text = texts.DEPOSIT_CREATED.format(
        id=payment.id,
        amount=fmt_money(payment.amount),
        fee=fmt_money(payment.fee),
        net=fmt_money(payment.amount - payment.fee),
        expires=fmt_dt(payment.expires_at, rt.timezone),
    )
    if payment.is_test:
        text += texts.TEST_MODE_NOTE
    return with_link_fallback(text, payment.checkout_url or "")


async def _create(
    message: Message,
    amount: Decimal,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
    state: FSMContext,
) -> None:
    try:
        payment = await svc.deposits.create(user, amount)
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=cancel_kb())
        return
    await state.clear()
    sent = await message.answer(
        payment_text(payment, rt), reply_markup=payment_kb(payment), disable_web_page_preview=True
    )
    await svc.deposits.set_message_id(payment, sent.message_id)


@router.message(F.text == texts.BTN_DEPOSIT)
async def start_deposit(message: Message, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.set_state(DepositStates.amount)
    await message.answer(_ask_text(rt), reply_markup=cancel_kb())


@router.callback_query(MenuCb.filter(F.action == "deposit"))
async def cb_deposit(call: CallbackQuery, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.set_state(DepositStates.amount)
    await call.answer()
    await edit_or_send(call, _ask_text(rt), cancel_kb())


@router.callback_query(MenuCb.filter(F.action == "topup"))
async def cb_topup(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await edit_or_send(call, texts.TOPUP_CHOOSE, topup_kb())


@router.callback_query(AmountCb.filter())
async def cb_quick_amount(
    call: CallbackQuery,
    callback_data: AmountCb,
    state: FSMContext,
    svc: Services,
    user: User,
    rt: RuntimeSettings,
) -> None:
    await call.answer()
    if callback_data.value <= 0 or not isinstance(call.message, Message):
        await state.set_state(DepositStates.amount)
        await edit_or_send(call, _ask_text(rt), cancel_kb())
        return
    await _create(call.message, Decimal(callback_data.value), svc, user, rt, state)


@router.message(DepositStates.amount, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def on_amount(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID, reply_markup=cancel_kb())
        return
    await _create(message, amount, svc, user, rt, state)


@router.callback_query(PaymentCb.filter(F.action == "check"))
async def cb_check(
    call: CallbackQuery, callback_data: PaymentCb, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    try:
        payment = await svc.deposits.get_for_user(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    if payment.status == PaymentStatus.PENDING:
        outcome = await svc.deposits.refresh(payment.id)
        if outcome is not None:
            await svc.notifier.deposit(outcome)
            payment = outcome.payment
    await call.answer(
        texts.DEPOSIT_STATUS.format(id=payment.id, status=texts.PAYMENT_STATUS[payment.status]),
        show_alert=True,
    )
    if payment.status != PaymentStatus.PENDING and isinstance(call.message, Message):
        with suppress(TelegramBadRequest):
            await call.message.edit_reply_markup(reply_markup=None)


@router.callback_query(PaymentCb.filter(F.action == "cancel"))
async def cb_cancel(
    call: CallbackQuery, callback_data: PaymentCb, svc: Services, user: User
) -> None:
    try:
        payment = await svc.deposits.cancel(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, texts.DEPOSIT_CANCELLED.format(id=payment.id))
