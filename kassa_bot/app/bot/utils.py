from __future__ import annotations

import html
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.core.utils import is_public_url


def esc(value: object) -> str:
    return html.escape(str(value)) if value is not None else "—"


async def edit_or_send(
    call: CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Callbackdagi xabarni tahrirlaydi; imkonsiz bo‘lsa yangi xabar yuboradi."""
    message = call.message
    if isinstance(message, Message):
        try:
            await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc):
                return
        await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


async def safe_delete(message: Message) -> None:
    """48 soatdan eski yoki allaqachon o‘chirilgan xabar xato bermasin."""
    with suppress(TelegramBadRequest):
        await message.delete()


def with_link_fallback(text: str, url: str) -> str:
    """URL Telegram tugmasiga yaramasa (localhost), havolani matnga qo‘shadi."""
    if url and not is_public_url(url):
        return text + texts.LINK_FALLBACK.format(url=esc(url))
    return text
