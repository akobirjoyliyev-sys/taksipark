from __future__ import annotations

from typing import Any

from aiogram.filters import Filter
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    TelegramObject,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.bot.keyboards.callbacks import AdmCb
from app.core.permissions import Perm, has_perm
from app.models import Admin
from app.services.audit import Actor

ADMIN_MENU_TEXTS = frozenset(t for row in texts.ADMIN_MENU_ROWS for t in row)
NOT_MENU = frozenset(ADMIN_MENU_TEXTS | texts.MAIN_MENU_TEXTS)


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, admin: Admin | None = None) -> bool:
        return admin is not None


class HasPerm(Filter):
    def __init__(self, *perms: Perm) -> None:
        self.perms = perms

    async def __call__(
        self, event: TelegramObject, admin: Admin | None = None
    ) -> bool | dict[str, Any]:
        if admin is None or not all(has_perm(admin.role, p) for p in self.perms):
            return False
        return {"actor": Actor.from_admin(admin)}


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in row] for row in texts.ADMIN_MENU_ROWS],
        resize_keyboard=True,
    )


def btn(
    text: str, section: str, action: str, id: int = 0, page: int = 0, arg: str = ""
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text,
        callback_data=AdmCb(section=section, action=action, id=id, page=page, arg=arg).pack(),
    )


def kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[r for r in rows if r])


def confirm_kb(
    section: str, action: str, id: int = 0, arg: str = "", back: tuple[str, str, int] | None = None
) -> InlineKeyboardMarkup:
    rows = [
        [
            btn("✅ Ha, tasdiqlayman", section, action, id=id, arg=arg),
            btn("❌ Bekor", "dash", "cancel"),
        ]
    ]
    if back:
        rows.append([btn(texts.BTN_BACK, back[0], back[1], id=back[2])])
    return kb(*rows)


def pager(
    builder: InlineKeyboardBuilder,
    section: str,
    action: str,
    page: int,
    has_next: bool,
    arg: str = "",
) -> None:
    nav = []
    if page > 0:
        nav.append(btn("◀️", section, action, page=page - 1, arg=arg))
    if has_next:
        nav.append(btn("▶️", section, action, page=page + 1, arg=arg))
    if nav:
        builder.row(*nav)
