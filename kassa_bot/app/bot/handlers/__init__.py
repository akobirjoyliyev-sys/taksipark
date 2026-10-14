from __future__ import annotations

from aiogram import Router

from app.bot.handlers import bonus, common, deposit, info, mobcash, start, wallet, withdraw
from app.bot.middlewares import GateMiddleware


def build_user_routers() -> list[Router]:
    """Onboarding (gate'siz) + asosiy foydalanuvchi bo‘limlari (gate bilan) + fallback.

    `mobcash` routeri eski depozit/yechishdan oldin turadi: Mob-Cash rejimi yoqilgan bo‘lsa
    «➕ Hisob to‘ldirish» va «➖ Pul chiqarish» tugmalarini u ushlaydi.
    """
    gated = Router(name="user")
    gated.message.middleware(GateMiddleware())
    gated.callback_query.middleware(GateMiddleware())
    gated.include_routers(
        mobcash.router,
        wallet.router,
        deposit.router,
        withdraw.router,
        bonus.router,
        info.router,
    )
    return [start.router, gated, common.router]
