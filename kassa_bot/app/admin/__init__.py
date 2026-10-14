from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from app import texts
from app.admin import (
    bonus,
    bookmakers,
    channels,
    dashboard,
    join_requests,
    mobcash,
    payouts,
    settings,
    stats,
    userbot,
    users,
)
from app.admin.common import ADMIN_MENU_TEXTS, IsAdmin
from app.bot.keyboards.callbacks import AdmCb

# Ruxsat yetmagan admin amallari uchun javob. Router o‘z handlerlarini sub-routerlardan
# oldin tekshirgani uchun bu alohida router sifatida eng oxirida ulanadi.
fallback = Router(name="admin_fallback")


@fallback.callback_query(AdmCb.filter())
async def no_permission(call: CallbackQuery) -> None:
    await call.answer(texts.ADMIN_NO_PERM, show_alert=True)


@fallback.message(F.text.in_(ADMIN_MENU_TEXTS - {texts.ADM_EXIT}))
async def no_section_permission(message: Message) -> None:
    await message.answer(texts.ADMIN_NO_PERM)


def build_admin_router() -> Router:
    """Faqat faol adminlar uchun. Har bir handler o‘z ruxsatini HasPerm bilan tekshiradi."""
    router = Router(name="admin")
    router.message.filter(IsAdmin())
    router.callback_query.filter(IsAdmin())
    router.include_routers(
        dashboard.router,
        stats.router,
        users.router,
        settings.router,
        payouts.router,
        join_requests.router,
        bonus.router,
        channels.router,
        mobcash.router,
        bookmakers.router,
        userbot.router,
        fallback,
    )
    return router
