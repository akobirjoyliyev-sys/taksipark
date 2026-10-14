"""📦 Ommaviy to‘lov, 🤖 Avto to‘lov va 💸 Ruchnoy yechish bo‘limlari."""

from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, confirm_kb, kb, pager
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.enums import MassBatchStatus, WithdrawalSource, WithdrawalStatus
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt
from app.models import Admin, MassPayoutBatch
from app.repositories.users import UserRepository
from app.repositories.withdrawals import WithdrawalRepository
from app.services.audit import Actor
from app.services.container import Services
from app.services.mass_payout import CSV_HELP
from app.services.mobcash_withdrawals import pretty_card
from app.services.withdrawals import WithdrawalEvent

router = Router(name="admin_payouts")
PER_PAGE = 8


# =========================================================================== 📦 Ommaviy to‘lov
async def batch_view(
    svc: Services, batch: MassPayoutBatch, admin: Admin
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    counts = await svc.mass.item_counts(batch.id)
    progress = ", ".join(f"{texts.ITEM_STATUS[s]}: {n}" for s, n in counts.items()) or "—"
    preview = await svc.mass.items(batch.id, limit=12)
    lines = [
        f"{it.line_no}. {it.recipient_telegram_id or '?'} • "
        f"{fmt_money(it.amount) if it.amount else '?'} • {texts.ITEM_STATUS[it.status]}"
        + (f" — {esc(it.error)}" if it.error else "")
        for it in preview
    ]
    text = (
        f"📦 <b>Partiya #{batch.id}</b> — {texts.BATCH_STATUS[batch.status]}\n"
        f"📄 {esc(batch.file_name)} • {fmt_dt(batch.created_at, rt.timezone)}\n"
        f"👤 Yuklagan: <code>{batch.created_by}</code>"
        + (f" • Tasdiqlagan: <code>{batch.approved_by}</code>" if batch.approved_by else "")
        + f"\n\nQatorlar: {batch.total_rows} | ✅ {batch.valid_rows} | ❌ {batch.invalid_rows}"
        f" | ♻️ {batch.duplicate_rows}\n"
        f"💰 Jami (to‘g‘ri qatorlar): <b>{fmt_money(batch.total_amount)}</b>\n"
        f"📈 Progress: {progress}\n"
        f"✅ To‘landi: {batch.paid_count} | ⚠️ Bajarilmadi: {batch.failed_count}\n\n"
        + "\n".join(lines)
        + ("\n…" if batch.total_rows > len(lines) else "")
    )
    b = InlineKeyboardBuilder()
    if batch.status == MassBatchStatus.PREVIEW:
        if has_perm(admin.role, Perm.MASS_APPROVE):
            b.row(btn("✅ Tasdiqlash va yuborish", "mp", "approve", id=batch.id))
        if has_perm(admin.role, Perm.MASS_CREATE):
            b.row(btn("🚫 Bekor qilish", "mp", "cancel", id=batch.id))
    else:
        b.row(btn("🔄 Yangilash", "mp", "view", id=batch.id))
    b.row(btn("📄 To‘liq hisobot (CSV)", "mp", "csv", id=batch.id))
    b.row(btn("📋 Partiyalar", "mp", "list"))
    return text, b.as_markup()


def mass_menu_kb(admin: Admin) -> InlineKeyboardMarkup:
    rows = []
    if has_perm(admin.role, Perm.MASS_CREATE):
        rows.append([btn("📤 CSV yuklash", "mp", "upload")])
    rows.append([btn("📋 Partiyalar", "mp", "list")])
    return kb(*rows)


@router.message(F.text == texts.ADM_MASS, HasPerm(Perm.MASS_VIEW))
async def show_mass(message: Message, state: FSMContext, admin: Admin) -> None:
    await state.clear()
    await message.answer(
        f"📦 <b>Ommaviy to‘lov</b>\n\n{CSV_HELP}", reply_markup=mass_menu_kb(admin)
    )


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "upload")), HasPerm(Perm.MASS_CREATE)
)
async def cb_upload(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.mass_upload)
    await call.answer()
    await edit_or_send(
        call,
        "📤 CSV faylni hujjat sifatida yuboring.\n\n" + CSV_HELP,
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(AdminStates.mass_upload, F.document, HasPerm(Perm.MASS_CREATE))
async def on_upload(
    message: Message, state: FSMContext, svc: Services, admin: Admin, actor: Actor
) -> None:
    doc = message.document
    if doc is None or not (doc.file_name or "").lower().endswith(".csv"):
        await message.answer("⚠️ Faqat .csv fayl qabul qilinadi.")
        return
    if (doc.file_size or 0) > 512 * 1024:
        await message.answer("⚠️ Fayl juda katta (maks. 512 KB).")
        return
    buffer = await message.bot.download(doc)  # type: ignore[union-attr]
    if buffer is None:
        await message.answer(texts.ERROR_GENERIC)
        return
    try:
        batch = await svc.mass.create_preview(buffer.read(), doc.file_name or "file.csv", actor)
    except DomainError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await state.clear()
    text, markup = await batch_view(svc, batch, admin)
    await message.answer(
        "👁 <b>Preview tayyor.</b> Hech narsa yuborilmadi — tasdiqlash kerak.\n\n" + text,
        reply_markup=markup,
    )


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "list")), HasPerm(Perm.MASS_VIEW)
)
async def cb_list(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    page = max(callback_data.page, 0)
    batches = await svc.mass.list_page(page, PER_PAGE + 1)
    b = InlineKeyboardBuilder()
    for batch in batches[:PER_PAGE]:
        b.row(
            btn(
                f"#{batch.id} • {texts.BATCH_STATUS[batch.status]} • "
                f"{fmt_money(batch.total_amount)}",
                "mp",
                "view",
                id=batch.id,
            )
        )
    pager(b, "mp", "list", page, len(batches) > PER_PAGE)
    await call.answer()
    await edit_or_send(
        call,
        "📋 <b>Ommaviy to‘lov partiyalari</b>" if batches else "Partiyalar yo‘q.",
        b.as_markup(),
    )


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "view")), HasPerm(Perm.MASS_VIEW)
)
async def cb_view(call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin) -> None:
    text, markup = await batch_view(svc, await svc.mass.get(callback_data.id), admin)
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "approve")), HasPerm(Perm.MASS_APPROVE)
)
async def cb_approve(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    batch = await svc.mass.get(callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"⚠️ <b>Partiya #{batch.id}</b>: {batch.valid_rows} ta to‘lov, jami "
        f"<b>{fmt_money(batch.total_amount)}</b> payout navbatiga qo‘yiladi. Tasdiqlaysizmi?",
        confirm_kb("mp", "approve_do", id=batch.id),
    )


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "approve_do")), HasPerm(Perm.MASS_APPROVE)
)
async def cb_approve_do(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        batch = await svc.mass.approve(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Navbatga qo‘yildi", show_alert=True)
    text, markup = await batch_view(svc, batch, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "cancel")), HasPerm(Perm.MASS_CREATE)
)
async def cb_cancel(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        batch = await svc.mass.cancel(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("🚫 Bekor qilindi")
    text, markup = await batch_view(svc, batch, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "mp") & (F.action == "csv")), HasPerm(Perm.MASS_VIEW)
)
async def cb_csv(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    content = await svc.mass.report_csv(callback_data.id)
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.answer_document(
            BufferedInputFile(content, filename=f"mass_payout_{callback_data.id}.csv")
        )


# =========================================================================== 🤖 Avto to‘lov
async def auto_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    repo = WithdrawalRepository(svc.session)
    provider_lines = []
    for code in svc.providers.codes:
        provider = svc.providers.get(code)
        h = await svc.health.status(code)
        enabled = code in rt.enabled_providers
        provider_lines.append(
            f"{'🟢' if h.available else '🔴'} <b>{provider.title}</b> "
            f"({'faol' if enabled else 'o‘chirilgan'}, payout: "
            f"{'✅' if provider.supports_payout else '—'})\n"
            f"   ketma-ket xato: {h.failures}"
            + (f", oxirgi xato: {esc(h.last_error)}" if h.last_error else "")
        )
    text = (
        "🤖 <b>Avto to‘lov</b>\n\n"
        f"Holat: {'✅ Yoqilgan' if rt.auto_payout_enabled else '⛔ O‘chirilgan'}\n"
        f"Avto limit: {fmt_money(rt.auto_payout_max)} (undan katta — manual)\n"
        f"Maksimal urinishlar: {rt.payout_max_attempts} (eksponensial backoff)\n\n"
        f"<b>Navbat:</b>\n"
        f"🟢 Kutilmoqda: {await repo.count_by_status(WithdrawalStatus.APPROVED)}\n"
        f"🔄 Jarayonda: {await repo.count_by_status(WithdrawalStatus.PROCESSING)}\n"
        f"🧑‍💼 Manual navbat: {await repo.count_manual_pending()}\n"
        f"⚠️ Bajarilmagan: {await repo.count_by_status(WithdrawalStatus.FAILED)}\n\n"
        "<b>Provayderlar:</b>\n" + "\n".join(provider_lines)
    )
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.AUTO_MANAGE):
        b.row(btn("🔁 Avto to‘lovni yoqish/o‘chirish", "s", "edit", arg="auto_payout_enabled"))
        b.row(
            btn("💵 Avto limit", "s", "edit", arg="auto_payout_max"),
            btn("🔢 Urinishlar", "s", "edit", arg="payout_max_attempts"),
        )
        b.row(btn("♻️ Manual → avto navbat", "ap", "requeue"))
        b.row(
            btn("🩺 Provayderni tekshirish", "ap", "health"),
            btn("🔄 Reconciliation", "ap", "reconcile"),
        )
    b.row(btn("🔄 Yangilash", "ap", "view"))
    return text, b.as_markup()


@router.message(F.text == texts.ADM_AUTO, HasPerm(Perm.AUTO_VIEW))
async def show_auto(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await auto_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "ap") & (F.action == "view")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_auto_view(call: CallbackQuery, svc: Services, admin: Admin) -> None:
    text, markup = await auto_view(svc, admin)
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ap") & (F.action == "health")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_health(call: CallbackQuery, svc: Services, admin: Admin) -> None:
    for code in svc.providers.codes:
        ok = await svc.providers.get(code).health_check()
        if ok:
            await svc.health.record_success(code)
        else:
            await svc.health.record_failure(code, "health_check muvaffaqiyatsiz")
    text, markup = await auto_view(svc, admin)
    await call.answer("🩺 Tekshirildi")
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "ap") & (F.action == "reconcile")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_reconcile(call: CallbackQuery, svc: Services, admin: Admin, actor: Actor) -> None:
    await call.answer("🔄 Reconciliation boshlandi…")
    deposits = await svc.deposits.reconcile_pending(timedelta(seconds=0), limit=200)
    for outcome in deposits:
        await svc.notifier.deposit(outcome)
    payouts = await svc.withdrawals.poll_processing(timedelta(seconds=0))
    for event in payouts:
        await svc.notifier.withdrawal(event)
    await svc.audit.log(
        actor,
        "reconcile.manual",
        "system",
        None,
        after={"deposits": len(deposits), "payouts": len(payouts)},
    )
    await svc.session.commit()
    text, markup = await auto_view(svc, admin)
    await edit_or_send(
        call,
        f"✅ Reconciliation: {len(deposits)} ta to‘lov, {len(payouts)} ta payout yangilandi.\n\n"
        + text,
        markup,
    )


@router.callback_query(
    AdmCb.filter((F.section == "ap") & (F.action == "requeue")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_requeue(call: CallbackQuery) -> None:
    await call.answer()
    await edit_or_send(
        call,
        "♻️ Avto to‘lovdan manual navbatga tushgan arizalar qayta avto navbatga qo‘yilsinmi?\n"
        "(Operator hali ko‘rmagan yangi arizalar o‘zgarmaydi.)",
        confirm_kb("ap", "requeue_do"),
    )


@router.callback_query(
    AdmCb.filter((F.section == "ap") & (F.action == "requeue_do")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_requeue_do(call: CallbackQuery, svc: Services, admin: Admin, actor: Actor) -> None:
    count = await svc.withdrawals.requeue_manual(actor)
    await call.answer(f"✅ {count} ta ariza navbatga qo‘yildi", show_alert=True)
    text, markup = await auto_view(svc, admin)
    await edit_or_send(call, text, markup)


# =========================================================================== 💸 Ruchnoy yechish
_WD_FILTERS = {
    "pending": WithdrawalStatus.PENDING,
    "approved": WithdrawalStatus.APPROVED,
    "processing": WithdrawalStatus.PROCESSING,
    "failed": WithdrawalStatus.FAILED,
}


async def withdrawals_list(
    svc: Services, status_key: str, page: int
) -> tuple[str, InlineKeyboardMarkup]:
    status = _WD_FILTERS.get(status_key, WithdrawalStatus.PENDING)
    repo = WithdrawalRepository(svc.session)
    items = await repo.list_by_status(status, PER_PAGE + 1, page * PER_PAGE)
    b = InlineKeyboardBuilder()
    b.row(
        *[
            btn(
                ("• " if k == status_key else "") + texts.WITHDRAW_STATUS[v].split(" ", 1)[0],
                "wd",
                "list",
                arg=k,
            )
            for k, v in _WD_FILTERS.items()
        ]
    )
    for w in items[:PER_PAGE]:
        icon = (
            "🧑‍💼" if w.manual_required else ("📦" if w.source == WithdrawalSource.MASS else "👤")
        )
        b.row(btn(f"{icon} #{w.id} • {fmt_money(w.amount)} • {w.card_mask}", "wd", "view", id=w.id))
    pager(b, "wd", "list", page, len(items) > PER_PAGE, arg=status_key)
    total = await repo.count_by_status(status)
    text = (
        f"💸 <b>Yechish arizalari</b> — {texts.WITHDRAW_STATUS[status]} ({total})\n\n"
        "🧑‍💼 — manual navbat, 👤 — foydalanuvchi, 📦 — ommaviy"
    )
    return text, b.as_markup()


async def withdrawal_view(
    svc: Services, wid: int, admin: Admin
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    w = await svc.withdrawals.get(wid)
    user = await UserRepository(svc.session).get(w.user_id)
    history = await svc.withdrawals.history(w.id)
    hist = "\n".join(
        f"• {fmt_dt(h.created_at, rt.timezone)} {h.to_status} [{h.actor_role}"
        f"{':' + str(h.actor_telegram_id) if h.actor_telegram_id else ''}]"
        + (f" — {esc(h.comment)}" if h.comment else "")
        for h in history
    )
    pan = await svc.cards.manual_pan(w.card_id)
    card_line = (
        f"💳 Karta: <b>{pretty_card(pan)}</b> • {w.provider} (qo‘lda o‘tkazish)"
        if pan
        else f"💳 Karta (token): {w.card_mask} • {w.provider}"
    )
    text = (
        f"💸 <b>Ariza #{w.id}</b> ({w.source.value}) — {texts.WITHDRAW_STATUS[w.status]}\n\n"
        f"👤 Foydalanuvchi: <code>{user.telegram_id if user else '?'}</code> (#{w.user_id})\n"
        f"💵 Summa: {fmt_money(w.amount)} | 💸 Komissiya: {fmt_money(w.fee)}\n"
        f"✅ Kartaga: <b>{fmt_money(w.net_amount)}</b>\n"
        f"{card_line}\n"
        f"🔁 Urinishlar: {w.attempts}"
        + (f" | ⚠️ {esc(w.last_error)}" if w.last_error else "")
        + (f"\n🧾 Provayder ID: <code>{esc(w.external_id)}</code>" if w.external_id else "")
        + f"\n🕒 {fmt_dt(w.created_at, rt.timezone)}\n\n<b>Tarix:</b>\n{hist or '—'}"
    )
    provider = svc.providers.find(w.provider)
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.WITHDRAW_PROCESS):
        if (
            w.status == WithdrawalStatus.PENDING
            and provider is not None
            and provider.supports_payout
        ):
            b.row(btn("✅ Tasdiqlash (payout)", "wd", "act", id=w.id, arg="approve"))
        if w.status in (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED):
            b.row(btn("💵 To‘landi deb belgilash", "wd", "act", id=w.id, arg="paid"))
            b.row(btn("❌ Rad etish", "wd", "act", id=w.id, arg="reject"))
    b.row(btn(texts.BTN_BACK, "wd", "list", arg="pending"))
    return text, b.as_markup()


@router.message(F.text == texts.ADM_MANUAL, HasPerm(Perm.WITHDRAW_VIEW))
async def show_manual(message: Message, state: FSMContext, svc: Services) -> None:
    await state.clear()
    text, markup = await withdrawals_list(svc, "pending", 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "wd") & (F.action == "list")), HasPerm(Perm.WITHDRAW_VIEW)
)
async def cb_wd_list(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services
) -> None:
    await state.clear()
    text, markup = await withdrawals_list(
        svc, callback_data.arg or "pending", max(callback_data.page, 0)
    )
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "wd") & (F.action == "view")), HasPerm(Perm.WITHDRAW_VIEW)
)
async def cb_wd_view(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin
) -> None:
    text, markup = await withdrawal_view(svc, callback_data.id, admin)
    await call.answer()
    await edit_or_send(call, text, markup)


_ACT_TITLES = {
    "approve": "✅ Tasdiqlash izohi",
    "paid": "💵 To‘lov izohi (o‘tkazma vaqti, chek raqami yoki izoh)",
    "reject": "❌ Rad etish sababi",
}


@router.callback_query(
    AdmCb.filter((F.section == "wd") & (F.action == "act")), HasPerm(Perm.WITHDRAW_PROCESS)
)
async def cb_wd_act(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    if callback_data.arg not in _ACT_TITLES:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await state.set_state(AdminStates.wd_comment)
    await state.update_data(wd_id=callback_data.id, wd_act=callback_data.arg)
    await call.answer()
    await edit_or_send(
        call,
        f"{_ACT_TITLES[callback_data.arg]} — majburiy. Yozing:",
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(
    AdminStates.wd_comment, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.WITHDRAW_PROCESS)
)
async def on_wd_comment(message: Message, state: FSMContext) -> None:
    comment = (message.text or "").strip()[:500]
    if len(comment) < 3:
        await message.answer("Izoh kamida 3 belgi bo‘lsin.")
        return
    data = await state.get_data()
    await state.update_data(wd_comment=comment)
    await state.set_state(None)
    await message.answer(
        f"Ariza #{data['wd_id']}: <b>{_ACT_TITLES[data['wd_act']].split(' (')[0]}</b>\n"
        f"💬 {esc(comment)}\n\nTasdiqlaysizmi?",
        reply_markup=confirm_kb("wd", "do", id=data["wd_id"]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "wd") & (F.action == "do")), HasPerm(Perm.WITHDRAW_PROCESS)
)
async def cb_wd_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    data = await state.get_data()
    await state.clear()
    if data.get("wd_id") != callback_data.id or not data.get("wd_comment"):
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    action, comment = data["wd_act"], data["wd_comment"]
    try:
        event: WithdrawalEvent
        if action == "approve":
            event = await svc.withdrawals.approve(callback_data.id, actor, comment)
        elif action == "paid":
            event = await svc.withdrawals.mark_paid_manually(callback_data.id, actor, comment)
        else:
            event = await svc.withdrawals.reject(callback_data.id, actor, comment)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await svc.notifier.withdrawal(event)
    await call.answer("✅ Bajarildi")
    text, markup = await withdrawal_view(svc, callback_data.id, admin)
    await edit_or_send(call, text, markup)
