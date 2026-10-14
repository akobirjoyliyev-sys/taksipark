from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.admin.common import HasPerm, admin_menu_kb, btn, kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.keyboards.user import main_menu_kb
from app.bot.utils import edit_or_send
from app.core.money import fmt_money
from app.core.permissions import Perm
from app.models import Admin
from app.services.container import Services

router = Router(name="admin_dashboard")


async def dashboard_text(svc: Services, admin: Admin) -> str:
    rt = await svc.settings.snapshot()
    d = await svc.stats.dashboard(svc.providers, svc.health, rt)
    active_boxes = await svc.bookmakers.list_active()
    active_cards = await svc.p2p.active_cards()
    active_bots = await svc.userbots.active_accounts()
    _, auto_ok, auto_amount = await svc.auto.today_summary()
    auto_active = await svc.auto.active_batches()
    return (
        f"⚙️ <b>TIZIM BOSHQARUV PANELI</b>\n"
        f"Admin: <code>{admin.telegram_id}</code>\n"
        f"🟢 Tizim holati: {'Faol' if not rt.maintenance else 'Texnik ishlar'}\n\n"
        f"📊 Tezkor ko‘rsatkichlar:\n"
        f"• 👥 Foydalanuvchilar: <b>{d.total_users} ta</b>\n"
        f"• 📱 Kontakt tasdiqlaganlar: <b>{d.contact_verified} ta</b>\n"
        f"• 🏦 Faol kassalar: <b>{len(active_boxes)} ta</b>\n"
        f"• 🛰 Faol userbotlar: <b>{len(active_bots)} ta</b>\n"
        f"• 💳 Faol kartalar: <b>{len(active_cards)} ta</b>\n"
        f"• 💰 Depozit limit: {fmt_money(rt.deposit_min)} — {fmt_money(rt.deposit_max)}\n"
        f"• 🤖 Avto to‘lov (24 soat): <b>{auto_ok} ID</b> • {fmt_money(auto_amount)}"
        + (f" • ⚡ faol: {len(auto_active)}" if auto_active else "")
        + "\n\n"
        "👉 Kerakli bo‘limni tanlang:"
    )


def dashboard_kb() -> InlineKeyboardMarkup:
    return kb([btn("🔄 Yangilash", "dash", "refresh")])


@router.message(Command("admin"), HasPerm(Perm.DASHBOARD))
async def cmd_admin(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    await message.answer("🛠 Admin menyusi", reply_markup=admin_menu_kb())
    await message.answer(await dashboard_text(svc, admin), reply_markup=dashboard_kb())


@router.callback_query(
    AdmCb.filter((F.section == "dash") & (F.action == "refresh")), HasPerm(Perm.DASHBOARD)
)
async def cb_refresh(call: CallbackQuery, svc: Services, admin: Admin) -> None:
    await call.answer("Yangilandi")
    await edit_or_send(call, await dashboard_text(svc, admin), dashboard_kb())


@router.callback_query(AdmCb.filter((F.section == "dash") & (F.action == "cancel")))
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer(texts.CANCELLED)
    await edit_or_send(call, texts.CANCELLED)


@router.message(F.text == texts.ADM_EXIT)
async def exit_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu_kb())
