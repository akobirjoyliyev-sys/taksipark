"""🏦 Mob-Cash kassa: holat, yechishlar (kartaga to‘lash), depozit tekshiruvi, mos kelmagan
kirimlar va P2P kartalar. Ogohlantirish xabarlaridagi tugmalar ham shu handlerlarga keladi.
"""

from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, kb, pager
from app.bot.keyboards.admin_mobcash import bank_tx_kb, mcwd_kb, p2p_kb
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc, safe_delete
from app.core.enums import (
    BankTxStatus,
    MobcashWithdrawalStatus,
    P2PDepositStatus,
    P2PDepositTarget,
    UserbotStatus,
)
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt, get_tz, utcnow
from app.mobcash import MobCashError
from app.models import Admin, BankTransaction
from app.services.audit import Actor
from app.services.container import Services
from app.services.integrations import apply_runtime_integrations
from app.services.mobcash_withdrawals import pretty_card
from app.services.notifier import mcwd_admin_text, p2p_admin_text

router = Router(name="admin_mobcash")
PER_PAGE = 8

P2P_GROUPS: dict[str, tuple[str, tuple[P2PDepositStatus, ...]]] = {
    "review": ("🕵️ Tekshiruvda", (P2PDepositStatus.REVIEW,)),
    "paid": ("🔄 Tushirilmoqda", (P2PDepositStatus.PAID,)),
    "pending": ("⏳ Kutilmoqda", (P2PDepositStatus.PENDING,)),
    "closed": (
        "📁 Yakunlangan",
        (
            P2PDepositStatus.CREDITED,
            P2PDepositStatus.EXPIRED,
            P2PDepositStatus.CANCELLED,
            P2PDepositStatus.REJECTED,
        ),
    ),
}
MCW_GROUPS: dict[str, tuple[str, tuple[MobcashWithdrawalStatus, ...]]] = {
    "await": ("📤 To‘lash kerak", (MobcashWithdrawalStatus.AWAITING_PAYOUT,)),
    "review": (
        "🕵️ Tekshiruvda",
        (MobcashWithdrawalStatus.REVIEW, MobcashWithdrawalStatus.REFUND_REVIEW),
    ),
    "closed": (
        "📁 Yakunlangan",
        (
            MobcashWithdrawalStatus.PAID,
            MobcashWithdrawalStatus.REFUNDED,
            MobcashWithdrawalStatus.FAILED,
            MobcashWithdrawalStatus.REJECTED,
        ),
    ),
}


# =========================================================================== bosh sahifa
async def main_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    await apply_runtime_integrations(svc)
    rt = await svc.settings.snapshot()
    dep = await svc.p2p.counts()
    wd = await svc.mcwd.counts()
    unmatched = len(await svc.p2p.unmatched(limit=100))
    cards = await svc.p2p.active_cards()
    bots = [a for a in await svc.userbots.all_accounts() if a.status == UserbotStatus.ACTIVE]
    local = utcnow().astimezone(get_tz(rt.timezone))
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    n_dep, sum_dep = await svc.p2p.credited_since(day_start)

    bookmakers = await svc.bookmakers.list_all()
    if bookmakers:
        active_n = sum(1 for bm in bookmakers if bm.is_active)
        conn = f"🏢 Kantoralar: <b>{active_n}</b> faol / {len(bookmakers)} ta"
    elif not svc.mobcash or not svc.mobcash.configured:
        conn = "⚪ Sozlanmagan — «🏢 Kantoralar» bo‘limidan kassa qo‘shing"
    else:
        conn = f"🔑 Kassa <code>{svc.mobcash.cashbox_code}</code> — «🔌 Tekshirish» bosing"
    n_review = dep.get(P2PDepositStatus.REVIEW, 0)
    n_await = wd.get(MobcashWithdrawalStatus.AWAITING_PAYOUT, 0)
    n_wd_review = wd.get(MobcashWithdrawalStatus.REVIEW, 0) + wd.get(
        MobcashWithdrawalStatus.REFUND_REVIEW, 0
    )
    text = (
        "🏦 <b>Mob-Cash kassa</b>\n\n"
        f"🔌 Ulanish: {conn}\n"
        f"⚙️ Rejim: {'✅ Yoqilgan' if rt.mobcash_enabled else '⛔ O‘chirilgan (eski hamyon)'}\n"
        f"💳 Faol P2P kartalar: <b>{len(cards)}</b>\n"
        f"🛰 Faol userbotlar: <b>{len(bots)}</b>\n\n"
        f"⏳ Kutilayotgan to‘lovlar: {dep.get(P2PDepositStatus.PENDING, 0)}\n"
        f"🔄 Tushirilmoqda: {dep.get(P2PDepositStatus.PAID, 0)}\n"
        f"🕵️ Depozit tekshiruvda: <b>{n_review}</b>\n"
        f"❓ Mos kelmagan kirimlar: <b>{unmatched}</b>\n"
        f"📤 Kartaga to‘lash kerak: <b>{n_await}</b>\n"
        f"🕵️ Yechish tekshiruvda: <b>{n_wd_review}</b>\n\n"
        f"📊 Bugun tushirildi: {n_dep} ta • {fmt_money(sum_dep)}"
    )
    if not cards:
        text += "\n\n⚠️ Faol karta yo‘q — foydalanuvchilar to‘lov qila olmaydi."
    if not bots:
        text += "\n⚠️ Faol userbot yo‘q — to‘lovlar avtomatik tasdiqlanmaydi."
    b = InlineKeyboardBuilder()
    b.row(btn("🏢 Kantoralar", "bm", "list"), btn("🔌 Ulanishni tekshirish", "mc", "check"))
    if not bookmakers and has_perm(admin.role, Perm.SETTINGS_CRITICAL):
        b.row(btn("⚙️ Yagona kassa (eski rejim)", "mc", "connect"))
    b.row(
        btn(f"📤 Yechishlar ({n_await + n_wd_review})", "mcw", "list", arg="await"),
        btn(f"🧾 Depozitlar ({n_review})", "p2p", "list", arg="review"),
    )
    b.row(btn(f"❓ Mos kelmaganlar ({unmatched})", "btx", "list"))
    if has_perm(admin.role, Perm.MOBCASH_MANAGE):
        b.row(btn("💳 P2P kartalar", "card", "list"))
    b.row(btn("🔄 Yangilash", "mc", "main"))
    return text, b.as_markup()


@router.message(F.text == texts.ADM_MOBCASH, HasPerm(Perm.MOBCASH_VIEW))
async def show_main(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await main_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "mc") & (F.action == "main")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_main(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    await call.answer()
    text, markup = await main_view(svc, admin)
    await edit_or_send(call, text, markup)


async def _connection_text(svc: Services) -> str:
    bookmakers = await svc.bookmakers.list_all()
    if bookmakers:
        lines = ["🔌 <b>Kantoralar ulanishi</b>\n"]
        for bm in bookmakers:
            try:
                info = await (await svc.bookmakers.client(bm.id)).check_connection()
                state = f"🟢 ulandi ({esc(info.currency_id)})"
            except MobCashError as exc:
                state = f"🔴 {esc(exc.message[:120])}"
            except DomainError as exc:
                state = f"🔴 {esc(exc.message[:120])}"
            off = "" if bm.is_active else " · <i>o‘chirilgan</i>"
            lines.append(f"🏢 <b>{esc(bm.name)}</b>{off}\n   {state}")
        return "\n".join(lines)
    if svc.mobcash is None:
        return "🔴 Mob-Cash klienti mavjud emas."
    try:
        info = await svc.mobcash.check_connection()
    except MobCashError as exc:
        return f"🔴 <b>Ulanish xatosi</b> ({exc.kind})\n\n{esc(exc.message)}"
    rt = await svc.settings.snapshot()
    return (
        "🟢 <b>Mob-Cash ulandi</b>\n\n"
        f"🏦 Kassa: <code>{esc(info.code)}</code>\n"
        f"💱 Valyuta ID: <code>{esc(info.currency_id)}</code>\n"
        f"📥 Depozit: {'✅' if info.is_deposit else '⛔'}\n"
        f"📤 Yechish: {'✅' if info.is_withdrawal else '⛔'}\n"
        f"⏳ Token muddati: {fmt_dt(info.expires_at, rt.timezone)}"
    )


@router.callback_query(
    AdmCb.filter((F.section == "mc") & (F.action == "check")), HasPerm(Perm.MOBCASH_VIEW)
)
async def cb_check(call: CallbackQuery, svc: Services) -> None:
    await apply_runtime_integrations(svc)
    has_bm = bool(await svc.bookmakers.list_all())
    if not has_bm and (svc.mobcash is None or not svc.mobcash.configured):
        await call.answer("Kassa sozlanmagan — «🏢 Kantoralar» orqali qo‘shing.", show_alert=True)
        return
    await call.answer("Tekshirilmoqda…")
    text = await _connection_text(svc)
    await edit_or_send(call, text, kb([btn(texts.BTN_BACK, "mc", "main")]))


# ====================================================================== ⚙️ kassa ulash ustasi
@router.callback_query(
    AdmCb.filter((F.section == "mc") & (F.action == "connect")),
    HasPerm(Perm.SETTINGS_CRITICAL),
)
async def mc_connect_ask(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.mobcash_connect)
    await state.update_data(mc_step=0)
    await call.answer()
    await edit_or_send(
        call,
        "⚙️ <b>Kassa ulash</b>\n\nBitta xabarda yuboring:\n"
        "<code>kassa_kodi | login | parol</code>\n\n"
        "Masalan: <code>12345 | admin | parol123</code>\n\n"
        "Uchala ma’lumot Mob-Cash kabinetidagi kassa sozlamalaridan olinadi. Saqlangach "
        "eski token bekor qilinadi va ulanish darhol tekshiriladi.",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.mobcash_connect, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.SETTINGS_CRITICAL)
)
async def mc_connect_do(message: Message, state: FSMContext, svc: Services) -> None:
    raw = message.text or ""
    await safe_delete(message)  # parol chatda qolmasin
    parts = [p.strip() for p in raw.replace("\n", "|").split("|", 2)]
    if len(parts) < 3 or not all(parts):
        await message.answer(
            "⚠️ Uchta qiymat kerak: <code>kassa_kodi | login | parol</code>\n"
            "Masalan: <code>12345 | admin | parol123</code>"
        )
        return
    code, login, password = parts
    try:
        values: dict[str, str] = {}
        for key, raw in (
            ("mobcash_cashbox_code", code),
            ("mobcash_login", login),
            ("mobcash_password", password),
        ):
            _, _, serialized = await svc.settings.prepare_change(key, raw)
            values[key] = serialized
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(exc)}")
        return
    await state.update_data(mc_values=values, mc_step=1)
    await message.answer(
        "1️⃣ <b>Tekshiring</b>\n\n"
        f"🏦 Kassa kodi: <b>{esc(code)}</b>\n"
        f"👤 Login: <b>{esc(login)}</b>\n"
        f"🔑 Parol: <b>{'•' * min(len(password), 12)}</b> ({len(password)} belgi)\n\n"
        "Ma’lumotlar to‘g‘rimi?",
        reply_markup=kb([btn("➡️ Davom etish", "mc", "step2"), btn("❌ Bekor", "dash", "cancel")]),
    )


@router.callback_query(
    AdminStates.mobcash_connect,
    AdmCb.filter((F.section == "mc") & (F.action == "step2")),
    HasPerm(Perm.SETTINGS_CRITICAL),
)
async def mc_step2(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("mc_step") != 1:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await state.update_data(mc_step=2)
    await call.answer()
    await edit_or_send(
        call,
        "2️⃣ <b>Yakuniy tasdiq</b>\n\nKassa ma’lumotlari saqlanadi, eski token bekor qilinadi "
        "va ulanish qayta tekshiriladi. Ishonchingiz komilmi?",
        kb([btn("✅ Ha, tasdiqlayman", "mc", "apply"), btn("❌ Bekor", "dash", "cancel")]),
    )


@router.callback_query(
    AdminStates.mobcash_connect,
    AdmCb.filter((F.section == "mc") & (F.action == "apply")),
    HasPerm(Perm.SETTINGS_CRITICAL),
)
async def mc_apply(call: CallbackQuery, state: FSMContext, svc: Services, actor: Actor) -> None:
    data = await state.get_data()
    values = data.get("mc_values")
    if not values or data.get("mc_step") != 2:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await state.clear()
    for key, serialized in values.items():
        await svc.settings.update(key, serialized, actor)
    await apply_runtime_integrations(svc)
    await call.answer("✅ Saqlandi, tekshirilmoqda…")
    text = await _connection_text(svc)
    await edit_or_send(call, text, kb([btn(texts.BTN_BACK, "mc", "main")]))


# =========================================================================== 📤 yechishlar
@router.callback_query(
    AdmCb.filter((F.section == "mcw") & (F.action == "list")), HasPerm(Perm.MOBCASH_VIEW)
)
async def mcw_list(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    group = callback_data.arg if callback_data.arg in MCW_GROUPS else "await"
    page = max(callback_data.page, 0)
    items = await svc.mcwd.list_by_status(MCW_GROUPS[group][1], PER_PAGE + 1, page * PER_PAGE)
    b = InlineKeyboardBuilder()
    b.row(
        *[
            btn(("• " if g == group else "") + title, "mcw", "list", arg=g)
            for g, (title, _) in MCW_GROUPS.items()
        ]
    )
    for w in items[:PER_PAGE]:
        dest = f"*{w.card_number[-4:]}" if w.card_number else "💎"
        b.row(
            btn(
                f"#{w.id} • {fmt_money(w.payout_amount)} • {dest}",
                "mcw",
                "view",
                id=w.id,
            )
        )
    pager(b, "mcw", "list", page, len(items) > PER_PAGE, arg=group)
    b.row(btn(texts.BTN_BACK, "mc", "main"))
    await call.answer()
    title = MCW_GROUPS[group][0]
    await edit_or_send(
        call, f"📤 <b>Yechishlar</b> — {title}" + ("" if items else "\n\nBo‘sh."), b.as_markup()
    )


@router.callback_query(
    AdmCb.filter((F.section == "mcw") & (F.action == "view")), HasPerm(Perm.MOBCASH_VIEW)
)
async def mcw_view(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    try:
        wd = await svc.mcwd.get(callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    rt = await svc.settings.snapshot()
    text = mcwd_admin_text(
        wd,
        f"📤 <b>Yechish #{wd.id}</b> — {texts.MC_WD_STATUS[wd.status]}",
        await svc.bookmakers.name_of(wd.bookmaker_id),
    )
    text += f"\n🕓 {fmt_dt(wd.created_at, rt.timezone)} • kod: <code>{esc(wd.code_mask)}</code>"
    if wd.comment:
        text += f"\n💬 {esc(wd.comment)}"
    markup = mcwd_kb(wd) or InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([btn(texts.BTN_BACK, "mcw", "list")])
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "mcw") & (F.action == "paid")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def mcw_paid(call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor) -> None:
    try:
        event = await svc.mcwd.mark_paid(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ To‘landi deb belgilandi", show_alert=True)
    await svc.notifier.mcwd_status(event)
    wd = event.withdrawal
    await edit_or_send(
        call, mcwd_admin_text(wd, f"✅ <b>Yechish #{wd.id}</b> — to‘landi ({_who(actor)})")
    )


@router.callback_query(
    AdmCb.filter((F.section == "mcw") & F.action.in_({"rv_ok", "rv_fail", "rf_ok", "rf_fail"})),
    HasPerm(Perm.MOBCASH_PROCESS),
)
async def mcw_review(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    withdrawn = callback_data.action == "rv_ok"
    refund_review = callback_data.action.startswith("rf_")
    try:
        if refund_review:
            event = await svc.mcwd.confirm_refund(
                callback_data.id, actor, refunded=callback_data.action == "rf_ok"
            )
        else:
            event = await svc.mcwd.confirm_review(callback_data.id, actor, withdrawn=withdrawn)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("Saqlandi")
    await svc.notifier.mcwd_status(event)
    wd = event.withdrawal
    if refund_review:
        title = f"<b>Yechish #{wd.id}</b> — {texts.MC_WD_STATUS[wd.status]}"
        await edit_or_send(call, mcwd_admin_text(wd, title), mcwd_kb(wd))
        return
    if withdrawn and not wd.card_number:
        title = f"✅ <b>Yechish #{wd.id}</b> — hamyonga o‘tkazildi"
    elif withdrawn:
        title = f"📤 <b>Yechish #{wd.id}</b> — endi kartaga o‘tkazing"
    else:
        title = f"❌ <b>Yechish #{wd.id}</b> — bajarilmadi deb belgilandi"
    await edit_or_send(call, mcwd_admin_text(wd, title), mcwd_kb(wd))


@router.callback_query(
    AdmCb.filter((F.section == "mcw") & (F.action == "refund")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def mcw_refund_ask(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.mcw_refund_comment)
    await state.update_data(mcw_id=callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"↩️ <b>Yechish #{callback_data.id}</b> summasi Mob-Cash deposit orqali o‘yin hisobiga "
        "qaytariladi.\n\nFoydalanuvchiga ko‘rsatiladigan sababni yozing (yoki <code>-</code>):",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.mcw_refund_comment, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_PROCESS)
)
async def mcw_refund_do(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    wd_id = (await state.get_data()).get("mcw_id")
    await state.clear()
    comment = "" if (message.text or "").strip() == "-" else (message.text or "").strip()[:255]
    if not wd_id:
        await message.answer(texts.EXPIRED_ACTION)
        return
    wait = await message.answer("⏳ Mob-Cash'ga yuborilmoqda…")
    try:
        event = await svc.mcwd.refund(int(wd_id), actor, comment)
    except DomainError as exc:
        await wait.edit_text(f"⚠️ {esc(exc.message)}")
        return
    await svc.notifier.mcwd_status(event, comment)
    await wait.edit_text(f"↩️ Yechish #{wd_id} o‘yin hisobiga qaytarildi.")


# =========================================================================== 🧾 depozitlar
@router.callback_query(
    AdmCb.filter((F.section == "p2p") & (F.action == "list")), HasPerm(Perm.MOBCASH_VIEW)
)
async def p2p_list(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    group = callback_data.arg if callback_data.arg in P2P_GROUPS else "review"
    page = max(callback_data.page, 0)
    items = await svc.p2p.list_by_status(P2P_GROUPS[group][1], PER_PAGE + 1, page * PER_PAGE)
    b = InlineKeyboardBuilder()
    groups = list(P2P_GROUPS.items())
    for chunk in (groups[:2], groups[2:]):
        b.row(*[btn(("• " if g == group else "") + t, "p2p", "list", arg=g) for g, (t, _) in chunk])
    for d in items[:PER_PAGE]:
        who = "🏠 Hamyon" if d.target == P2PDepositTarget.WALLET else f"ID {d.payer_id}"
        b.row(
            btn(
                f"#{d.id} • {fmt_money(d.unique_amount)} • {who}",
                "p2p",
                "view",
                id=d.id,
            )
        )
    pager(b, "p2p", "list", page, len(items) > PER_PAGE, arg=group)
    b.row(btn(texts.BTN_BACK, "mc", "main"))
    await call.answer()
    await edit_or_send(
        call,
        f"🧾 <b>Depozitlar</b> — {P2P_GROUPS[group][0]}" + ("" if items else "\n\nBo‘sh."),
        b.as_markup(),
    )


@router.callback_query(
    AdmCb.filter((F.section == "p2p") & (F.action == "view")), HasPerm(Perm.MOBCASH_VIEW)
)
async def p2p_view(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    deposit = await svc.p2p.get(callback_data.id)
    if deposit is None:
        await call.answer("Topilmadi", show_alert=True)
        return
    rt = await svc.settings.snapshot()
    card = await svc.p2p.card_for(deposit)
    text = p2p_admin_text(
        deposit,
        f"🧾 <b>Depozit #{deposit.id}</b>",
        await svc.bookmakers.name_of(deposit.bookmaker_id),
    )
    text += (
        f"\n💳 Karta: *{card.last4 if card else '—'}"
        f"\n🕓 Yaratildi: {fmt_dt(deposit.created_at, rt.timezone)}"
        f" • muddat: {fmt_dt(deposit.expires_at, rt.timezone)}"
    )
    if deposit.paid_at:
        text += f"\n📥 To‘landi: {fmt_dt(deposit.paid_at, rt.timezone)}"
    if deposit.credited_at:
        text += f"\n✅ Tushirildi: {fmt_dt(deposit.credited_at, rt.timezone)}"
    markup = p2p_kb(deposit) or InlineKeyboardMarkup(inline_keyboard=[])
    markup.inline_keyboard.append([btn(texts.BTN_BACK, "p2p", "list")])
    await call.answer()
    await edit_or_send(call, text, markup)


async def _credit_and_notify(svc: Services, call: CallbackQuery, deposit_id: int) -> None:
    outcome = await svc.p2p.credit(deposit_id)
    deposit = outcome.deposit if outcome else await svc.p2p.get(deposit_id)
    if outcome is not None:
        admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
        await svc.notifier.p2p_deposit(outcome, [a for a in admins if a != call.from_user.id])
    if deposit is None:
        return
    title = {
        P2PDepositStatus.CREDITED: (
            "✅ Hamyonga tushirildi"
            if deposit.target == P2PDepositTarget.WALLET
            else "✅ Mob-Cash'ga tushirildi"
        ),
        P2PDepositStatus.REVIEW: "🕵️ Hali ham tekshiruvda",
        P2PDepositStatus.PAID: "🔄 Navbatda (keyinroq qayta uriniladi)",
    }.get(deposit.status, texts.mc_status(deposit.target, deposit.status))
    await edit_or_send(call, p2p_admin_text(deposit, f"<b>{title}</b>"), p2p_kb(deposit))


@router.callback_query(
    AdmCb.filter((F.section == "p2p") & F.action.in_({"retry", "confirm", "credit_now"})),
    HasPerm(Perm.MOBCASH_PROCESS),
)
async def p2p_retry(call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor) -> None:
    try:
        if callback_data.action == "retry":
            await svc.p2p.admin_retry(callback_data.id, actor)
        elif callback_data.action == "confirm":
            await svc.p2p.admin_confirm_paid(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("⏳ Mob-Cash'ga yuborilmoqda…")
    await _credit_and_notify(svc, call, callback_data.id)


@router.callback_query(
    AdmCb.filter((F.section == "p2p") & (F.action == "credited")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def p2p_credited(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    try:
        deposit = await svc.p2p.admin_mark_credited(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Saqlandi")
    user_tg = await svc.p2p.user_telegram_id(deposit)
    amount = fmt_money(deposit.credit_amount or deposit.unique_amount)
    if deposit.target == P2PDepositTarget.WALLET:
        note = texts.MC_TOPUP_CREDITED.format(id=deposit.id, amount=amount)
    else:
        note = texts.MC_DEP_CREDITED.format(
            id=deposit.id, amount=amount, payer_id=html.escape(deposit.payer_id)
        )
    await svc.notifier.send(user_tg, note)
    await edit_or_send(
        call, p2p_admin_text(deposit, f"✅ <b>Qo‘lda tushirildi</b> ({_who(actor)})")
    )


@router.callback_query(
    AdmCb.filter((F.section == "p2p") & (F.action == "reject")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def p2p_reject_ask(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services
) -> None:
    await state.set_state(AdminStates.p2p_reject_comment)
    await state.update_data(p2p_id=callback_data.id)
    await call.answer()
    deposit = await svc.p2p.get(callback_data.id)
    wallet_funded = (
        deposit is not None
        and deposit.target == P2PDepositTarget.GAME
        and deposit.card_id is None
    )
    note = (
        "Summa foydalanuvchi hamyoniga avtomatik qaytariladi."
        if wallet_funded
        else "Pulni qaytarishni bot tashqarisida hal qiling."
    )
    await edit_or_send(
        call,
        f"❌ <b>Depozit #{callback_data.id}</b> rad etiladi (Mob-Cash'ga tushirilmaydi).\n"
        f"{note}\n\n"
        "Foydalanuvchiga ko‘rsatiladigan sababni yozing (yoki <code>-</code>):",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.p2p_reject_comment, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_PROCESS)
)
async def p2p_reject_do(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    dep_id = (await state.get_data()).get("p2p_id")
    await state.clear()
    comment = "" if (message.text or "").strip() == "-" else (message.text or "").strip()[:255]
    if not dep_id:
        await message.answer(texts.EXPIRED_ACTION)
        return
    try:
        deposit = await svc.p2p.admin_reject(int(dep_id), actor, comment)
    except DomainError as exc:
        await message.answer(f"⚠️ {esc(exc.message)}")
        return
    await svc.notifier.p2p_rejected(deposit, await svc.p2p.user_telegram_id(deposit), comment)
    await message.answer(f"❌ Depozit #{deposit.id} rad etildi.")


# =================================================================== ❓ mos kelmagan kirimlar
def _tx_line(tx: BankTransaction) -> str:
    return f"#{tx.id} • {fmt_money(tx.amount)} • *{tx.card_last4 or '????'}"


@router.callback_query(
    AdmCb.filter((F.section == "btx") & (F.action == "list")), HasPerm(Perm.MOBCASH_VIEW)
)
async def btx_list(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    page = max(callback_data.page, 0)
    items = await svc.p2p.unmatched(PER_PAGE + 1, page * PER_PAGE)
    b = InlineKeyboardBuilder()
    for tx in items[:PER_PAGE]:
        b.row(btn(_tx_line(tx), "btx", "view", id=tx.id))
    pager(b, "btx", "list", page, len(items) > PER_PAGE)
    b.row(btn(texts.BTN_BACK, "mc", "main"))
    await call.answer()
    await edit_or_send(
        call,
        "❓ <b>Mos kelmagan kirimlar</b>\n\nBank xabari keldi, lekin bunday summali kutilayotgan "
        "to‘lov topilmadi." + ("" if items else "\n\nBo‘sh."),
        b.as_markup(),
    )


@router.callback_query(
    AdmCb.filter((F.section == "btx") & (F.action == "view")), HasPerm(Perm.MOBCASH_VIEW)
)
async def btx_view(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    try:
        tx = await svc.p2p.get_tx(callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    rt = await svc.settings.snapshot()
    text = (
        f"❓ <b>Kirim #{tx.id}</b>\n\n💰 {fmt_money(tx.amount)}\n"
        f"📨 @{esc(tx.source_name)} • 🕓 {fmt_dt(tx.message_date, rt.timezone)}\n\n"
        f"<pre>{esc(tx.raw_text[:900])}</pre>"
    )
    markup = (
        bank_tx_kb(tx)
        if tx.status == BankTxStatus.UNMATCHED
        else InlineKeyboardMarkup(inline_keyboard=[])
    )
    markup.inline_keyboard.append([btn(texts.BTN_BACK, "btx", "list")])
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "btx") & (F.action == "ignore")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def btx_ignore(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    try:
        await svc.p2p.ignore_transaction(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("🙈 E’tiborsiz qoldirildi")
    await edit_or_send(call, f"🙈 Kirim #{callback_data.id} e’tiborsiz qoldirildi ({_who(actor)}).")


@router.callback_query(
    AdmCb.filter((F.section == "btx") & (F.action == "link")), HasPerm(Perm.MOBCASH_PROCESS)
)
async def btx_link_ask(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.btx_link)
    await state.update_data(btx_id=callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"🔗 <b>Kirim #{callback_data.id}</b>ni qaysi depozitga bog‘laymiz?\n\n"
        "Depozit raqamini yuboring (masalan <code>125</code>). Mob-Cash'ga haqiqatda kelgan "
        "summa tushiriladi.",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(AdminStates.btx_link, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_PROCESS))
async def btx_link_do(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    raw = (message.text or "").strip().lstrip("#")
    if not raw.isdigit():
        await message.answer("⚠️ Faqat depozit raqamini yuboring, masalan: 125")
        return
    tx_id = (await state.get_data()).get("btx_id")
    await state.clear()
    if not tx_id:
        await message.answer(texts.EXPIRED_ACTION)
        return
    try:
        deposit = await svc.p2p.link_transaction(int(tx_id), int(raw), actor)
    except DomainError as exc:
        await message.answer(f"⚠️ {esc(exc.message)}")
        return
    wait = await message.answer(f"🔗 Bog‘landi. Depozit #{deposit.id} Mob-Cash'ga yuborilmoqda…")
    outcome = await svc.p2p.credit(deposit.id)
    if outcome is not None:
        await svc.notifier.p2p_deposit(outcome)
        deposit = outcome.deposit
    await wait.edit_text(
        p2p_admin_text(
            deposit,
            f"🔗 <b>Bog‘landi</b> — {texts.mc_status(deposit.target, deposit.status)}",
        ),
        reply_markup=p2p_kb(deposit),
    )


# =========================================================================== 💳 P2P kartalar
async def cards_view(svc: Services) -> tuple[str, InlineKeyboardMarkup]:
    cards = await svc.p2p.list_cards()
    lines = [
        f"{'🟢' if c.is_active else '⚪'} <code>{pretty_card(c.number)}</code> — "
        f"{esc(c.holder or '—')} {('(' + esc(c.bank) + ')') if c.bank else ''}"
        for c in cards
    ]
    b = InlineKeyboardBuilder()
    for c in cards:
        b.row(
            btn(f"{'⏸' if c.is_active else '▶️'} *{c.last4}", "card", "toggle", id=c.id),
            btn(f"🗑 *{c.last4}", "card", "del", id=c.id),
        )
    b.row(btn("➕ Karta qo‘shish", "card", "add"))
    b.row(btn(texts.BTN_BACK, "mc", "main"))
    text = (
        "💳 <b>P2P kartalar</b>\n\nFoydalanuvchilar shu kartalarga pul o‘tkazadi. Har bir "
        "faol karta uchun bank xabarlari userbot akkauntiga kelishi shart.\n\n"
        + ("\n".join(lines) if lines else "Karta yo‘q.")
    )
    return text, b.as_markup()


@router.callback_query(
    AdmCb.filter((F.section == "card") & (F.action == "list")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def card_list(call: CallbackQuery, state: FSMContext, svc: Services) -> None:
    await state.clear()
    await call.answer()
    text, markup = await cards_view(svc)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "card") & F.action.in_({"toggle", "del"})),
    HasPerm(Perm.MOBCASH_MANAGE),
)
async def card_toggle(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    try:
        if callback_data.action == "toggle":
            await svc.p2p.toggle_card(callback_data.id, actor)
        else:
            await svc.p2p.delete_card(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Saqlandi")
    text, markup = await cards_view(svc)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "card") & (F.action == "add")), HasPerm(Perm.MOBCASH_MANAGE)
)
async def card_add_ask(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.p2p_card_form)
    await call.answer()
    await edit_or_send(
        call,
        "➕ <b>Yangi P2P karta</b>\n\nBitta xabarda yuboring:\n"
        "<code>8600123412341234 | Ism Familiya | Uzcard</code>\n\n"
        "Karta egasining ismi foydalanuvchiga ko‘rsatiladi.",
        kb([btn("❌ Bekor", "card", "list")]),
    )


@router.message(
    AdminStates.p2p_card_form, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.MOBCASH_MANAGE)
)
async def card_add_do(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    parts = [p.strip() for p in (message.text or "").replace("\n", "|").split("|")]
    number = parts[0] if parts else ""
    holder = parts[1] if len(parts) > 1 else ""
    bank = parts[2] if len(parts) > 2 else ""
    try:
        card = await svc.p2p.add_card(number, holder, bank, actor)
    except DomainError as exc:
        await message.answer(f"⚠️ {esc(exc.message)}")
        return
    await state.clear()
    text, markup = await cards_view(svc)
    await message.answer(f"✅ Karta *{card.last4} qo‘shildi.\n\n" + text, reply_markup=markup)


def _who(actor: Actor) -> str:
    return f"admin {actor.telegram_id}" if actor.telegram_id else "tizim"
