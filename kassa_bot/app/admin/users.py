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
from app.core.enums import AdminRole, LedgerDirection
from app.core.errors import DomainError
from app.core.money import fmt_money, parse_amount
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt, mask_phone
from app.models import Admin, User
from app.repositories.users import UserRepository
from app.repositories.wallets import LedgerRepository
from app.services.audit import Actor
from app.services.container import Services

router = Router(name="admin_users")


async def _user(svc: Services, user_id: int) -> User:
    user = await UserRepository(svc.session).get(user_id)
    if user is None:
        raise DomainError("Foydalanuvchi topilmadi.")
    return user


async def user_card(svc: Services, user: User, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    wallet = await svc.users.get_wallet(user.id)
    referrer = await UserRepository(svc.session).get(user.referrer_id) if user.referrer_id else None
    status = f"🚫 Bloklangan ({esc(user.ban_reason)})" if user.is_banned else "✅ Faol"
    text = (
        f"👤 <b>Foydalanuvchi #{user.id}</b>\n\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"👤 Ism: {esc(user.full_name)}"
        + (f" (@{esc(user.username)})" if user.username else "")
        + "\n"
        f"📱 Telefon: {mask_phone(user.phone)} {'✅' if user.contact_verified else ''}\n"
        f"📌 Holat: {status}\n"
        f"📅 Ro‘yxatdan o‘tgan: {fmt_dt(user.created_at, rt.timezone)}\n"
        f"🤝 Taklif qilgan: {referrer.telegram_id if referrer else '—'}\n\n"
        f"💰 Mavjud: <b>{fmt_money(wallet.available)}</b>\n"
        f"🔒 Bloklangan: {fmt_money(wallet.blocked)}\n"
        f"🎁 Bonus: {fmt_money(wallet.bonus_balance)}\n"
        f"📥 Jami depozit: {fmt_money(wallet.total_deposit)}\n"
        f"📤 Jami yechish: {fmt_money(wallet.total_withdraw)}"
    )
    b = InlineKeyboardBuilder()
    b.row(btn("📜 Tranzaksiyalar", "u", "tx", id=user.id))
    if has_perm(admin.role, Perm.USERS_BALANCE):
        b.row(
            btn("➕ Kredit", "u", "bal", id=user.id, arg="credit"),
            btn("➖ Debet", "u", "bal", id=user.id, arg="debit"),
        )
    row = []
    if has_perm(admin.role, Perm.USERS_BAN):
        row.append(
            btn("✅ Unban", "u", "unban", id=user.id)
            if user.is_banned
            else btn("🚫 Ban", "u", "ban", id=user.id)
        )
    if has_perm(admin.role, Perm.USERS_MESSAGE):
        row.append(btn("✉️ Xabar", "u", "msg", id=user.id))
    if row:
        b.row(*row)
    if user.phone and has_perm(admin.role, Perm.USERS_PII):
        b.row(btn("📞 To‘liq raqamni ko‘rish", "u", "phone", id=user.id))
    b.row(btn("🔍 Yangi qidiruv", "u", "search"))
    return text, b.as_markup()


@router.message(F.text == texts.ADM_USERS, HasPerm(Perm.USERS_VIEW))
async def show_users(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    total = await UserRepository(svc.session).count()
    rows = [[btn("🔍 Qidirish", "u", "search")]]
    if has_perm(admin.role, Perm.ADMINS_MANAGE):
        rows.append([btn("🛡 Adminlar va rollar", "ad", "list")])
    await message.answer(
        f"👥 <b>Foydalanuvchilar</b>: {total}\n\nQidirish: Telegram ID, @username yoki telefon.",
        reply_markup=kb(*rows),
    )


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "search")), HasPerm(Perm.USERS_VIEW)
)
async def cb_search(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.user_search)
    await call.answer()
    await edit_or_send(call, "🔍 Telegram ID, @username yoki telefon raqamini yuboring:")


@router.message(AdminStates.user_search, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERS_VIEW))
async def on_search(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    users = await UserRepository(svc.session).search((message.text or "")[:64])
    if not users:
        await message.answer("Hech narsa topilmadi. Qayta urinib ko‘ring.")
        return
    await state.set_state(None)
    if len(users) == 1:
        text, markup = await user_card(svc, users[0], admin)
        await message.answer(text, reply_markup=markup)
        return
    b = InlineKeyboardBuilder()
    for u in users:
        b.row(btn(f"#{u.id} • {u.telegram_id} • {u.first_name or ''}"[:60], "u", "view", id=u.id))
    await message.answer(f"Topildi: {len(users)} ta", reply_markup=b.as_markup())


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "view")), HasPerm(Perm.USERS_VIEW)
)
async def cb_view(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    await state.set_state(None)
    text, markup = await user_card(svc, await _user(svc, callback_data.id), admin)
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "tx")), HasPerm(Perm.USERS_VIEW)
)
async def cb_tx(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    rt = await svc.settings.snapshot()
    entries = await LedgerRepository(svc.session).list_for_user(callback_data.id, limit=15)
    lines = [
        f"{'➕' if e.direction == LedgerDirection.CREDIT else '➖'} {fmt_money(e.amount)} "
        f"[{e.account.value}] {texts.LEDGER_REASON.get(e.reason, e.reason)}\n"
        f"   {fmt_dt(e.created_at, rt.timezone)} • {esc(e.reference_type)}:{esc(e.reference_id)}"
        for e in entries
    ]
    await call.answer()
    await edit_or_send(
        call,
        "📜 <b>So‘nggi 15 ta ledger yozuvi</b>\n\n" + ("\n".join(lines) or "—"),
        kb([btn(texts.BTN_BACK, "u", "view", id=callback_data.id)]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "phone")), HasPerm(Perm.USERS_PII)
)
async def cb_phone(call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor) -> None:
    user = await _user(svc, callback_data.id)
    await svc.audit.log(actor, "user.phone_revealed", "user", user.telegram_id)
    await svc.session.commit()
    await call.answer(f"📞 {user.phone}", show_alert=True)


# ---- ban / unban -------------------------------------------------------------
@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "ban")), HasPerm(Perm.USERS_BAN)
)
async def cb_ban(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.ban_reason)
    await state.update_data(uid=callback_data.id)
    await call.answer()
    await edit_or_send(call, "🚫 Bloklash sababini yozing:")


@router.message(AdminStates.ban_reason, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERS_BAN))
async def on_ban_reason(message: Message, state: FSMContext) -> None:
    reason = (message.text or "").strip()[:255]
    if len(reason) < 3:
        await message.answer("Sabab kamida 3 belgi bo‘lsin.")
        return
    data = await state.get_data()
    await state.update_data(ban_reason=reason)
    await state.set_state(None)
    await message.answer(
        f"🚫 Foydalanuvchi #{data['uid']} bloklansinmi?\nSabab: {esc(reason)}",
        reply_markup=confirm_kb("u", "ban_do", id=data["uid"]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action.in_({"ban_do", "unban_do"}))),
    HasPerm(Perm.USERS_BAN),
)
async def cb_ban_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    actor: Actor,
    admin: Admin,
) -> None:
    banned = callback_data.action == "ban_do"
    data = await state.get_data()
    reason = data.get("ban_reason") if banned else None
    if banned and data.get("uid") != callback_data.id:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    user = await svc.users.set_ban(callback_data.id, banned, reason, actor)
    await state.clear()
    await call.answer("✅ Bajarildi")
    text, markup = await user_card(svc, user, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "unban")), HasPerm(Perm.USERS_BAN)
)
async def cb_unban(call: CallbackQuery, callback_data: AdmCb) -> None:
    await call.answer()
    await edit_or_send(
        call,
        f"✅ Foydalanuvchi #{callback_data.id} blokdan chiqarilsinmi?",
        confirm_kb("u", "unban_do", id=callback_data.id),
    )


# ---- balans ------------------------------------------------------------------
@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "bal")), HasPerm(Perm.USERS_BALANCE)
)
async def cb_balance(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.balance_amount)
    await state.update_data(uid=callback_data.id, direction=callback_data.arg)
    word = "kredit (qo‘shish)" if callback_data.arg == "credit" else "debet (ayirish)"
    await call.answer()
    await edit_or_send(call, f"💰 Qo‘lda {word} summasini kiriting:")


@router.message(
    AdminStates.balance_amount, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERS_BALANCE)
)
async def on_balance_amount(message: Message, state: FSMContext) -> None:
    amount = parse_amount(message.text)
    if amount is None:
        await message.answer(texts.AMOUNT_INVALID)
        return
    await state.update_data(amount=str(amount))
    await state.set_state(AdminStates.balance_reason)
    await message.answer("📝 Sababni yozing (majburiy, audit logga yoziladi):")


@router.message(
    AdminStates.balance_reason, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERS_BALANCE)
)
async def on_balance_reason(message: Message, state: FSMContext) -> None:
    reason = (message.text or "").strip()[:500]
    if len(reason) < 3:
        await message.answer("Sabab kamida 3 belgi bo‘lsin.")
        return
    await state.update_data(reason=reason)
    await state.set_state(AdminStates.balance_confirm)
    data = await state.get_data()
    sign = "➕" if data["direction"] == "credit" else "➖"
    await message.answer(
        f"⚠️ <b>Tasdiqlang</b>\n\nFoydalanuvchi #{data['uid']}\n"
        f"{sign} {fmt_money(parse_amount(data['amount']))}\nSabab: {esc(reason)}",
        reply_markup=confirm_kb("u", "bal_do", id=data["uid"]),
    )


@router.callback_query(
    AdminStates.balance_confirm,
    AdmCb.filter((F.section == "u") & (F.action == "bal_do")),
    HasPerm(Perm.USERS_BALANCE),
)
async def cb_balance_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    actor: Actor,
    admin: Admin,
) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("uid") != callback_data.id:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    direction = LedgerDirection.CREDIT if data["direction"] == "credit" else LedgerDirection.DEBIT
    amount = parse_amount(data["amount"])
    if amount is None:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    try:
        result = await svc.users.adjust_balance(
            callback_data.id, amount, direction, data["reason"], actor
        )
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Balans yangilandi")
    text, markup = await user_card(svc, result.user, admin)
    await edit_or_send(call, text, markup)


# ---- xabar yuborish ----------------------------------------------------------
@router.callback_query(
    AdmCb.filter((F.section == "u") & (F.action == "msg")), HasPerm(Perm.USERS_MESSAGE)
)
async def cb_message(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.message_text)
    await state.update_data(uid=callback_data.id)
    await call.answer()
    await edit_or_send(call, "✉️ Foydalanuvchiga yuboriladigan xabar matnini yozing:")


@router.message(
    AdminStates.message_text, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.USERS_MESSAGE)
)
async def on_message_text(message: Message, state: FSMContext) -> None:
    body = (message.text or "").strip()[:3500]
    await state.update_data(body=body)
    await state.set_state(AdminStates.message_confirm)
    data = await state.get_data()
    await message.answer(
        f"👁 <b>Preview</b> (foydalanuvchi #{data['uid']}):\n\n{esc(body)}\n\nYuborilsinmi?",
        reply_markup=confirm_kb("u", "msg_do", id=data["uid"]),
    )


@router.callback_query(
    AdminStates.message_confirm,
    AdmCb.filter((F.section == "u") & (F.action == "msg_do")),
    HasPerm(Perm.USERS_MESSAGE),
)
async def cb_message_do(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, actor: Actor
) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("uid") != callback_data.id:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    user = await _user(svc, callback_data.id)
    sent = await svc.notifier.send(
        user.telegram_id, f"📩 <b>Kassa ma’muriyatidan xabar</b>\n\n{esc(data['body'])}"
    )
    await svc.audit.log(
        actor,
        "user.message",
        "user",
        user.telegram_id,
        after={"sent": sent},
        comment=data["body"][:500],
    )
    await svc.session.commit()
    await call.answer(
        "✅ Yuborildi" if sent else "⚠️ Yuborilmadi (bot bloklangan)", show_alert=True
    )


# ---- adminlar va rollar --------------------------------------------------------
async def _admins_view(svc: Services) -> tuple[str, InlineKeyboardMarkup]:
    admins = await svc.admins.list_all()
    b = InlineKeyboardBuilder()
    lines = []
    for a in admins:
        icon = "🟢" if a.is_active else "⚪️"
        env = " (ENV)" if a.from_env else ""
        lines.append(f"{icon} <code>{a.telegram_id}</code> — {a.role.value}{env}")
        if not a.from_env:
            b.row(
                btn(
                    f"{'⏸ O‘chirish' if a.is_active else '▶️ Yoqish'} {a.telegram_id}",
                    "ad",
                    "toggle",
                    id=a.id,
                )
            )
    b.row(btn("➕ Admin qo‘shish / rolni o‘zgartirish", "ad", "add"))
    text = (
        "🛡 <b>Adminlar</b>\n\n"
        + "\n".join(lines)
        + "\n\nRollar: superadmin, admin, operator, auditor"
    )
    return text, b.as_markup()


@router.callback_query(
    AdmCb.filter((F.section == "ad") & (F.action == "list")), HasPerm(Perm.ADMINS_MANAGE)
)
async def cb_admins(call: CallbackQuery, state: FSMContext, svc: Services) -> None:
    await state.clear()
    text, markup = await _admins_view(svc)
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ad") & (F.action == "toggle")), HasPerm(Perm.ADMINS_MANAGE)
)
async def cb_admin_toggle(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    current = next((a for a in await svc.admins.list_all() if a.id == callback_data.id), None)
    if current is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    try:
        await svc.admins.set_active(current.id, not current.is_active, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    text, markup = await _admins_view(svc)
    await call.answer("✅ Saqlandi")
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ad") & (F.action == "add")), HasPerm(Perm.ADMINS_MANAGE)
)
async def cb_admin_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.admin_add)
    await call.answer()
    await edit_or_send(
        call, "Format: <code>telegram_id rol</code>\nMasalan: <code>123456789 operator</code>"
    )


@router.message(AdminStates.admin_add, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.ADMINS_MANAGE))
async def on_admin_add(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split()
    try:
        tg_id, role = int(parts[0]), AdminRole(parts[1].lower())
    except (IndexError, ValueError):
        await message.answer("Noto‘g‘ri format. Masalan: <code>123456789 operator</code>")
        return
    await state.update_data(new_admin=[tg_id, role.value])
    await state.set_state(None)
    await message.answer(
        f"🛡 <code>{tg_id}</code> → <b>{role.value}</b>. Tasdiqlaysizmi?",
        reply_markup=confirm_kb("ad", "add_do"),
    )


@router.callback_query(
    AdmCb.filter((F.section == "ad") & (F.action == "add_do")), HasPerm(Perm.ADMINS_MANAGE)
)
async def cb_admin_add_do(
    call: CallbackQuery, state: FSMContext, svc: Services, actor: Actor
) -> None:
    data = await state.get_data()
    await state.clear()
    if not data.get("new_admin"):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    tg_id, role = data["new_admin"]
    try:
        await svc.admins.upsert(int(tg_id), AdminRole(role), actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    text, markup = await _admins_view(svc)
    await call.answer("✅ Saqlandi")
    await edit_or_send(call, text, markup)
