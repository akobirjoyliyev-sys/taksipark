"""⚙️ Tizim sozlamalari — har o‘zgarish ikki bosqichli tasdiq va audit log bilan."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.permissions import Perm, has_perm
from app.models import Admin
from app.services.audit import Actor
from app.services.container import Services
from app.services.integrations import apply_runtime_integrations
from app.services.settings import DEFS_BY_KEY, SETTING_DEFS, display_value

router = Router(name="admin_settings")

GROUPS = {
    "system": "⚙️ Tizim",
    "payout": "🤖 Payout",
    "bonus": "🎁 Bonus",
    "channels": "📢 Obuna",
    "mobcash": "🏦 Mob-Cash",
    "userbot": "🛰 Userbot",
}
HINTS = {
    "money": "Summa (so‘m), masalan: <code>50000</code>",
    "percent": "Foiz 0–100, masalan: <code>1.5</code>",
    "int": "Butun son",
    "link": "<code>@username</code>, <code>https://...</code> yoki <code>-</code> (o‘chirish)",
    "tz": "Masalan: <code>Asia/Tashkent</code>",
    "mode": "<code>test</code> yoki <code>production</code>",
    "providers": (
        "Kodlar vergul bilan yoki <code>-</code> (o‘chirish). Mavjud: <code>sandbox</code>"
    ),
    "usernames": "Bot usernamelari vergul bilan: <code>CardXabarBot, HUMOcardbot</code>",
    "text": "Matn, masalan: <code>login123</code> yoki <code>-</code> (tozalash)",
    "secret": "Maxfiy qiymat (chatda ko‘rinmaydi) yoki <code>-</code> (tozalash)",
}
KEY_HINTS = {
    "userbot_session_key": (
        "Qo‘lda kiritish shart emas — «🛰 Userbot → 🔐 Kalit yaratish» orqali avtomatik " "yarating."
    ),
}


async def settings_view(
    svc: Services, admin: Admin, group: str
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    defs = [d for d in SETTING_DEFS if group == "all" or d.group == group]
    lines = [f"• {d.label}: <b>{esc(display_value(d, getattr(rt, d.key)))}</b>" for d in defs]
    b = InlineKeyboardBuilder()
    b.row(
        *[
            btn(("• " if g == group else "") + title, "s", "list", arg=g)
            for g, title in GROUPS.items()
        ]
    )
    if has_perm(admin.role, Perm.SETTINGS_EDIT):
        for d in defs:
            if d.critical and not has_perm(admin.role, Perm.SETTINGS_CRITICAL):
                continue
            b.row(btn(f"✏️ {d.label}", "s", "edit", arg=d.key))
    title = GROUPS.get(group, "Barcha")
    return f"⚙️ <b>Tizim sozlamalari</b> — {title}\n\n" + "\n".join(lines), b.as_markup()


@router.message(F.text == texts.ADM_SETTINGS, HasPerm(Perm.SETTINGS_VIEW))
async def show_settings(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await settings_view(svc, admin, "system")
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "s") & (F.action == "list")), HasPerm(Perm.SETTINGS_VIEW)
)
async def cb_list(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    await state.clear()
    text, markup = await settings_view(svc, admin, callback_data.arg or "system")
    await call.answer()
    await edit_or_send(call, text, markup)


async def _preview(
    target: Message | CallbackQuery, state: FSMContext, svc: Services, key: str, raw: str
) -> None:
    try:
        old, new, serialized = await svc.settings.prepare_change(key, raw)
    except ValueError as exc:
        text = f"⚠️ {esc(exc)}"
        if isinstance(target, CallbackQuery):
            await target.answer(str(exc)[:190], show_alert=True)
        else:
            await target.answer(text)
        return
    await state.set_state(AdminStates.setting_confirm)
    await state.update_data(set_key=key, set_value=serialized, set_step=1)
    text = (
        f"1️⃣ <b>O‘zgarish preview</b>\n\n{DEFS_BY_KEY[key].label}\n"
        f"Eski: <b>{esc(old)}</b>\nYangi: <b>{esc(new)}</b>"
    )
    markup = kb([btn("➡️ Davom etish", "s", "step2", arg=key), btn("❌ Bekor", "dash", "cancel")])
    if isinstance(target, CallbackQuery):
        await target.answer()
        await edit_or_send(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "s") & (F.action == "edit")), HasPerm(Perm.SETTINGS_EDIT)
)
async def cb_edit(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    d = DEFS_BY_KEY.get(callback_data.arg)
    if d is None:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    if d.critical and not has_perm(admin.role, Perm.SETTINGS_CRITICAL):
        await call.answer(texts.ADMIN_NO_PERM, show_alert=True)
        return
    rt = await svc.settings.snapshot()
    if d.kind == "bool":
        await _preview(call, state, svc, d.key, "false" if getattr(rt, d.key) else "true")
        return
    await state.set_state(AdminStates.setting_value)
    await state.update_data(set_key=d.key)
    await call.answer()
    await edit_or_send(
        call,
        f"✏️ <b>{d.label}</b>\nJoriy: <b>{esc(display_value(d, getattr(rt, d.key)))}</b>\n\n"
        f"Yangi qiymatni yuboring.\n{KEY_HINTS.get(d.key) or HINTS.get(d.kind, '')}",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.setting_value, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.SETTINGS_EDIT)
)
async def on_value(message: Message, state: FSMContext, svc: Services) -> None:
    data = await state.get_data()
    key = data.get("set_key")
    if not key:
        await state.clear()
        await message.answer(texts.EXPIRED_ACTION)
        return
    await _preview(message, state, svc, key, (message.text or "").strip()[:256])


@router.callback_query(
    AdminStates.setting_confirm,
    AdmCb.filter((F.section == "s") & (F.action == "step2")),
    HasPerm(Perm.SETTINGS_EDIT),
)
async def cb_step2(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("set_key") != callback_data.arg or data.get("set_step") != 1:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await state.update_data(set_step=2)
    await call.answer()
    await edit_or_send(
        call,
        f"2️⃣ <b>Yakuniy tasdiq</b>\n\n«{DEFS_BY_KEY[callback_data.arg].label}» o‘zgartiriladi va "
        "audit logga yoziladi. Ishonchingiz komilmi?",
        kb(
            [
                btn("✅ Ha, tasdiqlayman", "s", "apply", arg=callback_data.arg),
                btn("❌ Bekor", "dash", "cancel"),
            ]
        ),
    )


@router.callback_query(
    AdminStates.setting_confirm,
    AdmCb.filter((F.section == "s") & (F.action == "apply")),
    HasPerm(Perm.SETTINGS_EDIT),
)
async def cb_apply(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    data = await state.get_data()
    key = callback_data.arg
    if data.get("set_key") != key or data.get("set_step") != 2:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    if DEFS_BY_KEY[key].critical and not has_perm(admin.role, Perm.SETTINGS_CRITICAL):
        await call.answer(texts.ADMIN_NO_PERM, show_alert=True)
        return
    await state.clear()
    try:
        await svc.settings.update(key, data["set_value"], actor)
    except ValueError as exc:
        await call.answer(str(exc)[:190], show_alert=True)
        return
    await apply_runtime_integrations(svc)
    await call.answer("✅ Saqlandi", show_alert=True)
    text, markup = await settings_view(svc, admin, DEFS_BY_KEY[key].group)
    await edit_or_send(call, text, markup)
