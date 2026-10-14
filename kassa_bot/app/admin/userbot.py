"""🛰 Userbot: bank xabarlarini (CardXabar, HUMO) o‘qiydigan Telegram akkauntlarni boshqarish.

Qo‘shish: telefon → Telegram yuborgan kod → (bo‘lsa) 2FA parol. Kod va parol yozilgan
xabarlar darhol o‘chiriladi, sessiya bazada faqat shifrlangan holda saqlanadi.
Userbot jarayoni (`python -m app.userbot`) yangi akkauntni 30 soniya ichida ishga tushiradi.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc, safe_delete
from app.core.enums import UserbotStatus
from app.core.errors import DomainError
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt, mask_phone
from app.models import Admin
from app.services.audit import Actor
from app.services.container import Services
from app.services.settings import DEFS_BY_KEY, display_value
from app.services.userbots import LoginResult
from app.userbot.crypto import is_valid_fernet_key
from app.userbot.login import LoginError, get_login_manager

router = Router(name="admin_userbot")

STATUS_ICON = {UserbotStatus.ACTIVE: "🟢", UserbotStatus.DISABLED: "⏸", UserbotStatus.ERROR: "🔴"}


async def userbot_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    accounts = await svc.userbots.all_accounts()
    api_ok = bool(rt.tg_api_id and rt.tg_api_hash)
    key_ok = is_valid_fernet_key(rt.userbot_session_key)
    key_note = (
        "✅" if key_ok else ("❌ noto‘g‘ri format" if rt.userbot_session_key else "❌ yaratilmagan")
    )
    lines = []
    for a in accounts:
        name = f"@{a.username}" if a.username else esc(a.first_name or "—")
        line = (
            f"{STATUS_ICON.get(a.status, '❔')} <b>#{a.id}</b> {mask_phone(a.phone)} ({name})\n"
            f"    oxirgi faollik: {fmt_dt(a.last_seen_at, rt.timezone)}"
        )
        if a.last_error:
            line += f"\n    ⚠️ {esc(a.last_error)}"
        lines.append(line)
    text = (
        "🛰 <b>Userbot</b>\n\n"
        "Userbot sizning Telegram akkauntingizdagi bank xabarlarini o‘qiydi va kartaga kelgan "
        "noyob summani kutilayotgan to‘lov bilan solishtiradi.\n\n"
        f"🔑 API (my.telegram.org): {'✅' if api_ok else '❌ sozlanmagan'}\n"
        f"🔐 Shifrlash kaliti: {key_note}\n"
        f"📨 Manbalar: {esc(display_value(DEFS_BY_KEY['p2p_sources'], rt.p2p_sources))}\n\n"
        + ("\n".join(lines) if lines else "Akkaunt qo‘shilmagan.")
    )
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.USERBOT_MANAGE):
        for a in accounts:
            toggle = "⏸ O‘chirish" if a.status == UserbotStatus.ACTIVE else "▶️ Yoqish"
            b.row(
                btn(f"{toggle} #{a.id}", "ub", "toggle", id=a.id),
                btn(f"🗑 #{a.id}", "ub", "del", id=a.id),
            )
        b.row(btn("➕ Userbot qo‘shish", "ub", "add"))
        if not key_ok:
            b.row(btn("🔐 Kalit yaratish", "ub", "genkey"))
    if has_perm(admin.role, Perm.SETTINGS_CRITICAL):
        b.row(btn("✏️ API sozlamalari", "s", "list", arg="userbot"))
        b.row(btn("✏️ Manbalarni o‘zgartirish", "s", "edit", arg="p2p_sources"))
    b.row(btn("🔄 Yangilash", "ub", "main"))
    return text, b.as_markup()


@router.message(F.text == texts.ADM_USERBOT, HasPerm(Perm.MOBCASH_VIEW))
async def show_userbots(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await userbot_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "ub") & (F.action == "main")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_main(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    await call.answer()
    text, markup = await userbot_view(svc, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ub") & F.action.in_({"toggle", "del"})),
    HasPerm(Perm.USERBOT_MANAGE),
)
async def cb_toggle(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        if callback_data.action == "toggle":
            await svc.userbots.toggle(callback_data.id, actor)
        else:
            await svc.userbots.delete(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(
        "✅ Saqlandi. Userbot jarayoni 30 soniya ichida yangilanadi.", show_alert=True
    )
    text, markup = await userbot_view(svc, admin)
    await edit_or_send(call, text, markup)


# --------------------------------------------------------------------------- qo‘shish
def _cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn("❌ Bekor", "ub", "cancel")])


@router.callback_query(
    AdmCb.filter((F.section == "ub") & (F.action == "genkey")), HasPerm(Perm.USERBOT_MANAGE)
)
async def cb_genkey(call: CallbackQuery, svc: Services, admin: Admin, actor: Actor) -> None:
    rt = await svc.settings.snapshot()
    if is_valid_fernet_key(rt.userbot_session_key):
        await call.answer("Kalit allaqachon yaratilgan.", show_alert=True)
    else:
        await svc.settings.ensure_userbot_key(actor)
        await call.answer("✅ Shifrlash kaliti yaratildi", show_alert=True)
    text, markup = await userbot_view(svc, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ub") & (F.action == "add")), HasPerm(Perm.USERBOT_MANAGE)
)
async def cb_add(call: CallbackQuery, state: FSMContext, svc: Services, actor: Actor) -> None:
    rt = await svc.settings.snapshot()
    if not (rt.tg_api_id and rt.tg_api_hash):
        await call.answer(
            "Avval «✏️ API sozlamalari» orqali TG_API_ID va TG_API_HASH ni kiriting.",
            show_alert=True,
        )
        return
    note = ""
    if not is_valid_fernet_key(rt.userbot_session_key):
        await svc.settings.ensure_userbot_key(actor)
        note = "\n\n🔐 Shifrlash kaliti avtomatik yaratildi."
    await state.set_state(AdminStates.userbot_phone)
    await call.answer()
    await edit_or_send(
        call,
        "📱 <b>Userbot qo‘shish</b>\n\n"
        "Bank xabarlari keladigan Telegram akkaunt telefon raqamini yuboring:\n"
        "<code>+998901234567</code>\n\n"
        "⚠️ Shu akkauntda @CardXabarBot / HUMO boti ishga tushirilgan va kartangiz ulangan "
        "bo‘lishi kerak." + note,
        _cancel_kb(),
    )


@router.callback_query(AdmCb.filter((F.section == "ub") & (F.action == "cancel")))
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await get_login_manager().cancel(call.from_user.id)
    await state.clear()
    await call.answer(texts.CANCELLED)
    await edit_or_send(call, texts.CANCELLED)


@router.message(
    AdminStates.userbot_phone, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERBOT_MANAGE)
)
async def on_phone(message: Message, state: FSMContext, svc: Services) -> None:
    if message.from_user is None:
        return
    rt = await svc.settings.snapshot()
    manager = get_login_manager()
    try:
        phone = await manager.start(
            message.from_user.id,
            message.text or "",
            api_id=rt.tg_api_id,
            api_hash=rt.tg_api_hash,
        )
    except LoginError as exc:
        await message.answer(f"⚠️ {esc(exc)}", reply_markup=_cancel_kb())
        return
    await state.set_state(AdminStates.userbot_code)
    await message.answer(
        f"📩 Telegram <b>{mask_phone(phone)}</b> akkauntiga kod yubordi.\n\n"
        "Kodni <b>raqamlar orasiga bo‘sh joy qo‘yib</b> yuboring, masalan: <code>1 2 3 4 5</code>\n"
        "<i>Aks holda Telegram kodni «ulashilgan» deb bloklaydi.</i>",
        reply_markup=_cancel_kb(),
    )


async def _finish(
    message: Message, state: FSMContext, svc: Services, actor: Actor, result: LoginResult
) -> None:
    await state.clear()
    try:
        account = await svc.userbots.save_login(result, actor)
    except DomainError as exc:
        await message.answer(f"⚠️ {esc(exc.message)}")
        return
    name = f"@{account.username}" if account.username else esc(account.first_name or "—")
    await message.answer(
        f"✅ <b>Userbot qo‘shildi:</b> {name} ({mask_phone(account.phone)})\n\n"
        "Userbot jarayoni uni 30 soniya ichida ishga tushiradi. Holatni «🛰 Userbot» "
        "bo‘limida kuzating.",
        reply_markup=kb([btn("🛰 Userbotlar", "ub", "main")]),
    )


@router.message(
    AdminStates.userbot_code, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERBOT_MANAGE)
)
async def on_code(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    raw = message.text or ""
    await safe_delete(message)
    manager = get_login_manager()
    try:
        result = await manager.submit_code(message.from_user.id, raw)  # type: ignore[union-attr]
    except LoginError as exc:
        await message.answer(f"⚠️ {esc(exc)}", reply_markup=_cancel_kb())
        return
    if result is None:
        await state.set_state(AdminStates.userbot_password)
        await message.answer(
            "🔐 Akkauntda ikki bosqichli himoya (2FA) yoqilgan. Bulut parolini yuboring.\n"
            "<i>Xabar darhol o‘chiriladi.</i>",
            reply_markup=_cancel_kb(),
        )
        return
    await _finish(message, state, svc, actor, result)


@router.message(
    AdminStates.userbot_password, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERBOT_MANAGE)
)
async def on_password(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    password = message.text or ""
    await safe_delete(message)
    manager = get_login_manager()
    try:
        result = await manager.submit_password(message.from_user.id, password)  # type: ignore[union-attr]
    except LoginError as exc:
        await message.answer(f"⚠️ {esc(exc)}", reply_markup=_cancel_kb())
        return
    await _finish(message, state, svc, actor, result)
