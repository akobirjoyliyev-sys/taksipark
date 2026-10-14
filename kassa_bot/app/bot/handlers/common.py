from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app import texts
from app.bot.keyboards.user import main_menu_kb
from app.core.errors import DomainError

router = Router(name="common")
log = logging.getLogger(__name__)


@router.message()
async def fallback_message(message: Message) -> None:
    if message.chat.type != "private":
        return
    await message.answer(texts.UNKNOWN, reply_markup=main_menu_kb())


@router.callback_query()
async def fallback_callback(call: CallbackQuery) -> None:
    await call.answer(texts.EXPIRED_ACTION, show_alert=True)


async def _notify(event: ErrorEvent, text: str) -> None:
    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(text[:190], show_alert=True)
        elif update.message is not None:
            await update.message.answer(text)
    except Exception:
        log.debug("Xato xabarini yuborib bo‘lmadi", exc_info=True)


errors_router = Router(name="errors")


@errors_router.error(ExceptionTypeFilter(DomainError))
async def on_domain_error(event: ErrorEvent) -> None:
    await _notify(event, event.exception.message)  # type: ignore[attr-defined]


@errors_router.error()
async def on_error(event: ErrorEvent) -> None:
    log.exception("Handler xatosi update_id=%s", event.update.update_id, exc_info=event.exception)
    await _notify(event, texts.ERROR_GENERIC)
