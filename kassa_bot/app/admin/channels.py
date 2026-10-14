from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, confirm_kb, kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.errors import DomainError
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt
from app.models import Admin
from app.services.audit import Actor
from app.services.container import Services
from app.services.settings import DEFS_BY_KEY, display_value

router = Router(name="admin_channels")

ADMIN_HINT = (
    "ℹ️ Bot kanalda <b>admin</b> bo‘lishi kerak — aks holda obunani tekshirib bo‘lmaydi "
    "(bunday kanal foydalanuvchini bloklamaydi)."
)


async def channels_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    channels = await svc.channels.list_page()
    lines = [
        f"{i}. {'✅' if c.is_active else '⏸'} <b>{esc(c.title)}</b> — @{esc(c.username)} "
        f"{'🛡 bot admin' if c.bot_is_admin else '⚠️ bot admin emas'}"
        for i, c in enumerate(channels, start=1)
    ]
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.CHANNELS_MANAGE):
        for c in channels:
            b.row(btn(f"⚙️ {c.title}"[:40], "ch", "view", id=c.id))
        b.row(btn("➕ Kanal qo‘shish", "ch", "add"))
        b.row(btn("🔁 Majburiy obunani yoqish/o‘chirish", "s", "edit", arg="subscription_enabled"))
    status = display_value(DEFS_BY_KEY["subscription_enabled"], rt.subscription_enabled)
    text = (
        f"📢 <b>Majburiy obuna kanallari</b>\nHolat: {status}\n\n"
        + ("\n".join(lines) or "Kanallar yo‘q.")
        + f"\n\n{ADMIN_HINT}"
    )
    return text, b.as_markup()


@router.message(F.text == texts.ADM_CHANNELS, HasPerm(Perm.CHANNELS_VIEW))
async def show_channels(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await channels_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action == "list")), HasPerm(Perm.CHANNELS_VIEW)
)
async def cb_list(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await channels_view(svc, admin)
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action == "view")), HasPerm(Perm.CHANNELS_MANAGE)
)
async def cb_view(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    rt = await svc.settings.snapshot()
    c = await svc.channels.get(callback_data.id)
    text = (
        f"📢 <b>{esc(c.title)}</b> (@{esc(c.username)})\n"
        f"ID: <code>{c.chat_id or '—'}</code>\n"
        f"Holat: {'✅ aktiv' if c.is_active else '⏸ deaktiv'} • tartib: {c.sort_order}\n"
        f"Bot: {'🛡 admin' if c.bot_is_admin else '⚠️ admin emas'} "
        f"(tekshirilgan: {fmt_dt(c.checked_at, rt.timezone)})"
    )
    markup = kb(
        [
            btn("⏸ Deaktiv" if c.is_active else "▶️ Aktiv", "ch", "toggle", id=c.id),
            btn("🔍 Adminlikni tekshirish", "ch", "check", id=c.id),
        ],
        [btn("⬆️ Yuqoriga", "ch", "up", id=c.id), btn("⬇️ Pastga", "ch", "down", id=c.id)],
        [btn("🗑 O‘chirish", "ch", "del", id=c.id)],
        [btn(texts.BTN_BACK, "ch", "list")],
    )
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action.in_({"toggle", "check", "up", "down"}))),
    HasPerm(Perm.CHANNELS_MANAGE),
)
async def cb_action(call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor) -> None:
    if callback_data.action == "toggle":
        await svc.channels.toggle(callback_data.id, actor)
        await call.answer("✅ Saqlandi")
    elif callback_data.action == "check":
        channel = await svc.channels.check_admin(callback_data.id, actor)
        await call.answer(
            (
                "🛡 Bot admin"
                if channel.bot_is_admin
                else "⚠️ Bot kanalda admin emas yoki kanal topilmadi"
            ),
            show_alert=True,
        )
    else:
        await svc.channels.move(callback_data.id, -1 if callback_data.action == "up" else 1, actor)
        await call.answer("✅ Tartib o‘zgardi")
    await cb_view(call, AdmCb(section="ch", action="view", id=callback_data.id), svc)


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action == "del")), HasPerm(Perm.CHANNELS_MANAGE)
)
async def cb_del(call: CallbackQuery, callback_data: AdmCb) -> None:
    await call.answer()
    await edit_or_send(
        call, "🗑 Kanal ro‘yxatdan o‘chirilsinmi?", confirm_kb("ch", "del_do", id=callback_data.id)
    )


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action == "del_do")), HasPerm(Perm.CHANNELS_MANAGE)
)
async def cb_del_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    await svc.channels.delete(callback_data.id, actor)
    await cb_list(call, state, svc, admin)


@router.callback_query(
    AdmCb.filter((F.section == "ch") & (F.action == "add")), HasPerm(Perm.CHANNELS_MANAGE)
)
async def cb_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.channel_form)
    await call.answer()
    await edit_or_send(
        call,
        "➕ Kanalni quyidagi formatda yuboring:\n<code>@username | Kanal nomi</code>\n\n"
        + ADMIN_HINT,
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.channel_form, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.CHANNELS_MANAGE)
)
async def on_channel_form(
    message: Message, state: FSMContext, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        channel = await svc.channels.add(message.text or "", actor)
    except DomainError as exc:
        await message.answer(exc.message)
        return
    await state.clear()
    note = (
        "🛡 Bot kanalda admin."
        if channel.bot_is_admin
        else (
            "⚠️ Bot kanalda admin emas — botni admin qiling va «🔍 Adminlikni tekshirish»ni bosing."
        )
    )
    text, markup = await channels_view(svc, admin)
    await message.answer(
        f"✅ Qo‘shildi: <b>{esc(channel.title)}</b>\n{note}\n\n{text}", reply_markup=markup
    )
