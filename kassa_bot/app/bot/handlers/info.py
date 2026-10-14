from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import texts
from app.bot.keyboards.user import link_kb
from app.bot.utils import with_link_fallback
from app.services.settings import RuntimeSettings

router = Router(name="info")


@router.message(F.text == texts.BTN_SUPPORT)
async def show_support(message: Message, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.clear()
    if not rt.support_url:
        await message.answer(texts.NOT_CONFIGURED)
        return
    await message.answer(
        with_link_fallback(texts.SUPPORT_TEXT, rt.support_url),
        reply_markup=link_kb(texts.BTN_OPEN_SUPPORT, rt.support_url),
    )


@router.message(F.text == texts.BTN_CASHBOX)
async def show_cashbox(message: Message, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.clear()
    if not rt.cashbox_url:
        await message.answer(texts.NOT_CONFIGURED)
        return
    await message.answer(
        with_link_fallback(texts.CASHBOX_TEXT, rt.cashbox_url),
        reply_markup=link_kb(texts.BTN_OPEN_CASHBOX, rt.cashbox_url),
    )
