"""🏢 Kantoralar (bukmekerlar): har biri alohida Mob-Cash kassa.

Ekran: ro‘yxat (bosilsa yoqiladi/o‘chiriladi), ⚙️ batafsil, ➕ qo‘shish, 📊 tartiblash.
"""

from __future__ import annotations

import re
import secrets
import string

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc, safe_delete
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.permissions import Perm, has_perm
from app.mobcash import MobCashClient, MobCashError
from app.models import Admin
from app.services.audit import Actor
from app.services.container import Services

router = Router(name="admin_bookmakers")

HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")

CREDS_HELP = (
    "Kassa ma’lumotlarini <b>bitta xabarda</b> yuboring:\n\n"
    "<b>G&S / 1xBet / Melbet kassa</b> — depozit va yechish ishlaydi:\n"
    "<code>kassa_kodi | kassir paroli | hash</code>\n"
    "Masalan: <code>1234567 | parol | a1b2c3…</code> (hash — 64 belgili kalit)\n\n"
    "<b>TeamCash / MELLO CASH (agent) kassa</b> — depozit va yechish ishlaydi:\n"
    "<code>agent: login | parol | kassa_kodi</code>\n"
    "Masalan: <code>agent: kassir1 | parol123 | 1234567</code>\n\n"
    "🔒 Xabaringiz darhol o‘chiriladi, parol va hash bazada shifrlangan holda saqlanadi."
)


def _status(active: bool) -> str:
    return "🟢" if active else "🔴"


async def list_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    items = await svc.bookmakers.list_all()
    can_manage = has_perm(admin.role, Perm.MOBCASH_MANAGE)
    lines = [
        "⚙️ <b>Kantoralar Sozlamalari</b>\n",
        "Kantorani faollashtirish yoki o‘chirish uchun ustiga bosing, ⚙️ — batafsil, "
        "yoxud yangisini qo‘shing.\n",
    ]
    if not items:
        lines.append("<i>Hozircha kantora qo‘shilmagan.</i>")
        if await svc.bookmakers.legacy_available():
            lines.append("ℹ️ Hozir «🏦 Mob-Cash» sozlamalaridagi yagona kassa ishlatilmoqda.")
    rows = []
    for bm in items:
        rows.append(
            [
                btn(f"🏢 {bm.name} {_status(bm.is_active)}", "bm", "toggle", id=bm.id),
                btn("⚙️", "bm", "view", id=bm.id),
            ]
        )
    if can_manage:
        rows.append([btn("➕ Mobcash kassa qo‘shish", "bm", "add")])
        if len(items) > 1:
            rows.append([btn("📊 Tartiblash", "bm", "sort")])
    rows.append([btn(texts.BTN_BACK, "mc", "main")])
    return "\n".join(lines), kb(*rows)


_GATEWAY_NAMES = {"mobcash": "Mob-Cash", "cashdesk": "Cashdesk (1xBet)", "agent": "TeamCash agent"}


async def detail_view(svc: Services, bookmaker_id: int) -> tuple[str, InlineKeyboardMarkup]:
    bm = await svc.bookmakers.get(bookmaker_id)
    lines = [
        f"🏢 <b>{esc(bm.name)}</b>\n",
        f"Holat: {_status(bm.is_active)} {'Faol' if bm.is_active else 'O‘chirilgan'}",
        f"🌐 Turi: {_GATEWAY_NAMES.get(bm.gateway, bm.gateway)}",
        f"🔑 Kassa kodi: <code>{bm.cashbox_code}</code>",
    ]
    if bm.login:
        lines.append(f"👤 Login: <code>{esc(bm.login)}</code>")
    lines.append(f"💱 Valyuta: <code>{esc(bm.currency)}</code>")
    text = "\n".join(lines)
    toggle = "🔴 O‘chirish" if bm.is_active else "🟢 Yoqish"
    return text, kb(
        [btn("🔌 Ulanishni tekshirish", "bm", "check", id=bm.id)],
        [btn(toggle, "bm", "toggle_d", id=bm.id), btn("✏️ Nomi", "bm", "rename", id=bm.id)],
        [btn("🔑 Kassa ma’lumotlarini yangilash", "bm", "creds", id=bm.id)],
        [btn("🗑 O‘chirib tashlash", "bm", "del", id=bm.id)],
        [btn(texts.BTN_BACK, "bm", "list")],
    )


async def sort_view(svc: Services) -> tuple[str, InlineKeyboardMarkup]:
    items = await svc.bookmakers.list_all()
    rows = [
        [
            btn("⬆️", "bm", "up", id=bm.id),
            btn(f"{i}. {bm.name}", "bm", "view", id=bm.id),
            btn("⬇️", "bm", "down", id=bm.id),
        ]
        for i, bm in enumerate(items, 1)
    ]
    rows.append([btn("✅ Tayyor", "bm", "list")])
    return "📊 <b>Tartiblash</b>\n\nFoydalanuvchilarga shu tartibda ko‘rsatiladi.", kb(*rows)


# =========================================================================== ro‘yxat
@router.message(F.text == texts.ADM_BOOKMAKERS, HasPerm(Perm.MOBCASH_VIEW))
async def show_list(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await list_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "list")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_list(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    await call.answer()
    text, markup = await list_view(svc, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "view")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_view(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    try:
        text, markup = await detail_view(svc, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "bm") & F.action.in_({"toggle", "toggle_d"})),
    HasPerm(Perm.MOBCASH_MANAGE),
)
async def cb_toggle(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        bm = await svc.bookmakers.toggle(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(f"{bm.name}: {'🟢 Faol' if bm.is_active else '🔴 O‘chirildi'}")
    if callback_data.action == "toggle_d":
        text, markup = await detail_view(svc, bm.id)
    else:
        text, markup = await list_view(svc, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "check")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_check(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    await call.answer("Tekshirilmoqda…")
    back = kb([btn(texts.BTN_BACK, "bm", "view", id=callback_data.id)])
    try:
        bm = await svc.bookmakers.get(callback_data.id)
        info = await (await svc.bookmakers.client(bm.id)).check_connection()
    except DomainError as exc:
        await edit_or_send(call, f"🔴 {esc(exc.message)}", back)
        return
    except MobCashError as exc:
        await edit_or_send(
            call, f"🔴 <b>Ulanish xatosi</b> ({exc.kind})\n\n{esc(exc.message)}", back
        )
        return
    balance_note = ""
    if getattr(info, "balance", None) is not None:
        balance_note = f"\n💰 Balans: <b>{fmt_money(info.balance)}</b>"
        if getattr(info, "limit", None) is not None:
            balance_note += f"\n📊 Limit: {fmt_money(info.limit)}"
    await edit_or_send(
        call,
        f"🟢 <b>{esc(bm.name)} — ulandi</b>\n\n"
        f"🔑 Kassa: <code>{esc(info.code)}</code>\n"
        f"💱 Valyuta: <code>{esc(info.currency_id)}</code>\n"
        f"📥 Depozit: {'✅' if info.is_deposit else '⛔'}   "
        f"📤 Yechish: {'✅' if info.is_withdrawal else '⛔'}"
        f"{balance_note}",
        back,
    )


# =========================================================================== tartiblash
@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "sort")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_sort(call: CallbackQuery, svc: Services) -> None:
    await call.answer()
    text, markup = await sort_view(svc)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "bm") & F.action.in_({"up", "down"})), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_move(call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor) -> None:
    await svc.bookmakers.move(callback_data.id, -1 if callback_data.action == "up" else 1, actor)
    await call.answer()
    text, markup = await sort_view(svc)
    await edit_or_send(call, text, markup)


# =========================================================================== o‘chirish
@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "del")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_delete_ask(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    bm = await svc.bookmakers.get(callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"🗑 <b>{esc(bm.name)}</b> kantorasini o‘chirib tashlaysizmi?",
        kb(
            [btn("✅ Ha, o‘chirish", "bm", "del_ok", id=bm.id)],
            [btn(texts.BTN_BACK, "bm", "view", id=bm.id)],
        ),
    )


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "del_ok")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_delete(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        await svc.bookmakers.delete(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("🗑 O‘chirildi")
    text, markup = await list_view(svc, admin)
    await edit_or_send(call, text, markup)


# =========================================================================== qo‘shish
@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "add")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.bm_name)
    await call.answer()
    await edit_or_send(
        call,
        "✍️ Yangi kantora nomini yozing (foydalanuvchilarga shunday ko‘rinadi).\n\n"
        "Masalan: <code>1xBet UZS</code>, <code>Melbet</code>",
        kb([btn("❌ Bekor", "bm", "list")]),
    )


@router.message(AdminStates.bm_name, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_MANAGE))
async def on_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:64]
    if not name:
        return
    await state.update_data(bm_name=name)
    await state.set_state(AdminStates.bm_creds)
    await message.answer(
        f"✅ Nomi: <b>{esc(name)}</b>\n\n{CREDS_HELP}",
        reply_markup=kb([btn("❌ Bekor", "bm", "list")]),
    )


def _gen_password(n: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


async def _activate_hash(svc: Services, token: str) -> tuple[int, str, str]:
    """Bir martalik HASH → vaqtinchalik login → doimiy parol.

    Qaytaradi: (kassa_kodi, login, doimiy_parol). Doimiy parol o‘rnatib bo‘lmasa,
    vaqtinchalik parol qoladi (u baribir kassir paroli bo‘lib qolgan).
    """
    client = MobCashClient.from_config(svc.bookmakers.config, svc.bookmakers.redis)
    try:
        creds = await client.one_time_login(token)
        code_raw = creds["cashbox_code"]
        if not code_raw.isdigit():
            raise DomainError(f"Mob-Cash javobida kassa kodi yo‘q: {esc(code_raw)}")
        code, login, temp_pw = int(code_raw), creds["login"], creds["password"]
        await client.raw_login(code, login, temp_pw)
        generated = _gen_password()
        try:
            await client.set_persistent_password(code, login, temp_pw, generated)
        except MobCashError:
            return code, login, temp_pw
        return code, login, generated
    finally:
        await client.close()


@router.message(AdminStates.bm_creds, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_MANAGE))
async def on_creds(
    message: Message, state: FSMContext, svc: Services, admin: Admin, actor: Actor
) -> None:
    raw = (message.text or "").strip()
    await safe_delete(message)  # parol chatda qolmasin
    data = await state.get_data()
    is_hash = bool(HASH_RE.fullmatch(raw))
    wait = await message.answer(
        "🔑 HASH faollashtirilmoqda — kassaga ulanib, doimiy parol o‘rnatilmoqda…"
        if is_hash
        else "🔄 Kassaga ulanish tekshirilmoqda…"
    )
    try:
        if is_hash:
            code, login, password = await _activate_hash(svc, raw)
            raw_creds = f"{code} | {login} | {password}"
            hash_note = f"\n🔐 Doimiy kassir paroli: <code>{esc(password)}</code>"
        else:
            raw_creds = raw
            hash_note = ""
        if data.get("bm_edit_id"):
            bm = await svc.bookmakers.update_credentials(int(data["bm_edit_id"]), raw_creds, actor)
        else:
            bm = await svc.bookmakers.create(data.get("bm_name", ""), raw_creds, actor)
    except (DomainError, MobCashError) as exc:
        if is_hash:
            # 64-belgili kalitning ikki xili bor (Mob-Cash bir martalik token va 1xBet
            # Cashdesk imzo hashi) — server xatosi o'ziga xos bo'lmasa ham, foydalanuvchi
            # qaysi birini ushlaganini ko'rsatish kerak.
            await wait.edit_text(
                f"❌ <b>Bu kalit Mob-Cash bir martalik token sifatida tasdiqlanmadi.</b>\n"
                f"Server javobi: {esc(exc.message)}\n\n"
                "64 belgili kalitning ikki xili bor:\n"
                "• G&S bergan <b>Cashdesk (1xBet) hash</b> — u bir martalik token emas. "
                "Ushbu shaklda yuboring:\n"
                "<code>kassa_kodi | kassir paroli | hash</code>\n"
                "• Mob-Cash <b>bir martalik kalit</b> — daqiqalar ichida ishlatilishi kerak, "
                "aks holda eskiradi. Yangisini G&S kabinetidan so‘rang.\n\n"
                "Pul o‘tkazmalari (depozit/yechish) uchun esa Mob-Cash kassir login/paroli "
                "kerak bo‘ladi: <code>kassa_kodi | login | parol</code>",
                reply_markup=kb([btn("❌ Bekor", "bm", "list")]),
            )
        else:
            await wait.edit_text(
                f"❌ {esc(exc.message)}\n\n{CREDS_HELP}", reply_markup=kb([btn("❌ Bekor", "bm", "list")])
            )
        return
    await state.clear()
    login_note = f"\n👤 Login: <code>{esc(bm.login)}</code>" if bm.login else ""
    hash_note = "\n🔐 Hash saqlandi (shifrlangan)" if bm.gateway == "cashdesk" else hash_note
    await wait.edit_text(
        f"🎉 <b>Kantora ulandi va saqlandi!</b>\n\n"
        f"🏢 Nomi: <b>{esc(bm.name)}</b>\n"
        f"🔑 Kassa kodi: <code>{bm.cashbox_code}</code>"
        f"{login_note}\n"
        f"💱 Valyuta: <code>{esc(bm.currency)}</code>{hash_note}",
        reply_markup=kb([btn("📋 Kantoralar ro‘yxati", "bm", "list")]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "creds")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_creds(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.bm_creds)
    await state.update_data(bm_edit_id=callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"🔑 <b>Yangi kassa ma’lumotlari</b>\n\n{CREDS_HELP}",
        kb([btn("❌ Bekor", "bm", "view", id=callback_data.id)]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "bm") & (F.action == "rename")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def cb_rename(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.bm_rename)
    await state.update_data(bm_edit_id=callback_data.id)
    await call.answer()
    await edit_or_send(
        call, "✏️ Yangi nomni yozing:", kb([btn("❌ Bekor", "bm", "view", id=callback_data.id)])
    )


@router.message(AdminStates.bm_rename, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_MANAGE))
async def on_rename(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    data = await state.get_data()
    try:
        bm = await svc.bookmakers.rename(
            int(data.get("bm_edit_id") or 0), message.text or "", actor
        )
    except DomainError as exc:
        await message.answer(exc.message)
        return
    await state.clear()
    text, markup = await detail_view(svc, bm.id)
    await message.answer(text, reply_markup=markup)
