"""🤖 Avto to‘lov markazi: ID lar ro‘yxatiga kassadan avtomatik ommaviy depozit.

Ekranlar: markaz (hub) → 🚀 yangi (kassa → ID lar → summa → preview → tasdiq) →
jonli progress (worker tahrirlaydi) → hisobot / xatolarni qayta yuborish / tekshiruv.
"""

from __future__ import annotations

from contextlib import suppress
from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, kb, pager
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.enums import AutoBatchStatus, AutoItemStatus
from app.core.errors import DomainError
from app.core.money import fmt_money, parse_amount
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt, get_tz, utcnow
from app.mobcash import MobCashError
from app.models import Admin, AutoDepositBatch, AutoDepositItem
from app.services.audit import Actor
from app.services.auto_deposit import (
    AUTO_HELP,
    MAX_IDS,
    BatchStats,
    ParsedIds,
    Preview,
    StepEvent,
    parse_file,
    parse_ids,
)
from app.services.container import Services

router = Router(name="admin_auto_deposit")

LINE = "━━━━━━━━━━━━━━━━━━"
QUICK_AMOUNTS = (5_000, 10_000, 20_000, 50_000, 100_000, 200_000)
PER_PAGE = 8
LIST_PAGE = 15
HEARTBEAT_KEY = "auto:worker:heartbeat"
_STATUS_ICON = {
    AutoBatchStatus.DRAFT: "📝",
    AutoBatchStatus.RUNNING: "🚀",
    AutoBatchStatus.PAUSED: "⏸",
    AutoBatchStatus.COMPLETED: "✅",
    AutoBatchStatus.CANCELLED: "⛔",
}
_ITEM_ICON = {
    AutoItemStatus.PENDING: "⏳",
    AutoItemStatus.PROCESSING: "🔄",
    AutoItemStatus.SUCCESS: "✅",
    AutoItemStatus.FAILED: "❌",
    AutoItemStatus.REVIEW: "🕵️",
    AutoItemStatus.SKIPPED: "⏭",
}


# =========================================================================== render
def progress_bar(percent: int, width: int = 12) -> str:
    filled = round(width * max(0, min(percent, 100)) / 100)
    return "▰" * filled + "▱" * (width - filled)


def _money(value: Decimal | int | None) -> str:
    return fmt_money(value)


def _eta(batch: AutoDepositBatch, st: BatchStats) -> str | None:
    if batch.status != AutoBatchStatus.RUNNING or not batch.started_at or not st.done:
        return None
    left = st.pending + st.processing
    if not left:
        return None
    elapsed = (utcnow() - batch.started_at).total_seconds()
    if elapsed <= 0:
        return None
    seconds = int(left * elapsed / st.done)
    if seconds < 60:
        return f"~{seconds} s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"~{minutes} daq {sec:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"~{hours} soat {minutes} daq"


def _amount_line(batch: AutoDepositBatch) -> str:
    if batch.default_amount is not None:
        return f"💵 Har biriga: <b>{_money(batch.default_amount)}</b>"
    return "💵 Summalar: <b>har bir ID uchun alohida</b>"


def render_batch(
    batch: AutoDepositBatch,
    st: BatchStats,
    last: AutoDepositItem | None,
    tz: str,
) -> str:
    lines = [
        f"🤖 <b>AVTO TO‘LOV #{batch.id}</b> • {texts.AUTO_BATCH_STATUS[batch.status]}",
        LINE,
        f"🏢 Kassa: <b>{esc(batch.kassa_name)}</b>",
        _amount_line(batch),
        "",
        f"<code>{progress_bar(st.percent)}</code> <b>{st.percent}%</b>",
        f"📦 Bajarildi: <b>{st.done}</b> / {st.total}",
        "",
        f"✅ O‘tkazildi: <b>{st.success}</b> • {_money(st.success_amount)}",
        f"❌ Xato: <b>{st.failed}</b>    🕵️ Tekshiruv: <b>{st.review}</b>",
    ]
    if st.pending or st.processing:
        lines.append(f"⏳ Navbatda: <b>{st.pending + st.processing}</b>")
    if st.skipped:
        lines.append(f"⏭ O‘tkazib yuborildi: <b>{st.skipped}</b>")
    eta = _eta(batch, st)
    if eta:
        lines.append(f"⏱ Taxminan qoldi: <b>{eta}</b>")
    if batch.status == AutoBatchStatus.PAUSED and batch.pause_reason:
        lines.append(f"\n⚠️ <b>Pauza sababi:</b> {esc(batch.pause_reason)}")
    lines.append(LINE)
    if last is not None:
        who = f" ({esc((last.nickname or '')[:24])})" if last.nickname else ""
        lines.append(
            f"🔸 Oxirgi: <code>{esc(last.payer_id)}</code>{who} — "
            f"{_ITEM_ICON[last.status]} {_money(last.amount)}"
        )
        if last.error and last.status != AutoItemStatus.SUCCESS:
            lines.append(f"     <i>{esc(last.error[:120])}</i>")
    if batch.status == AutoBatchStatus.COMPLETED:
        lines.append(f"🏁 Yakunlandi: {fmt_dt(batch.finished_at, tz)}")
        if st.review:
            lines.append(
                "\n🕵️ <b>Tekshiruvdagi ID lar</b> — natija noma’lum. Kassa panelida tekshirib "
                "belgilang (qayta yuborilmaydi, pul ikki marta ketmasin)."
            )
    else:
        lines.append(f"🕒 Yangilandi: {utcnow().astimezone(get_tz(tz)).strftime('%H:%M:%S')}")
    return "\n".join(lines)


def batch_kb(batch: AutoDepositBatch, st: BatchStats, manage: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if manage:
        if batch.status == AutoBatchStatus.RUNNING:
            b.row(
                btn("⏸ Pauza", "au", "pause", id=batch.id),
                btn("⛔ To‘xtatish", "au", "stop", id=batch.id),
            )
        elif batch.status == AutoBatchStatus.PAUSED:
            b.row(
                btn("▶️ Davom ettirish", "au", "resume", id=batch.id),
                btn("⛔ To‘xtatish", "au", "stop", id=batch.id),
            )
        if st.failed and batch.status in (
            AutoBatchStatus.COMPLETED,
            AutoBatchStatus.PAUSED,
        ):
            b.row(btn(f"🔁 Xatolarni qayta yuborish ({st.failed})", "au", "retry", id=batch.id))
        if st.review:
            b.row(btn(f"🕵️ Tekshiruv ({st.review})", "au", "rv", id=batch.id))
    row = []
    if st.failed:
        row.append(btn(f"❌ Xatolar ({st.failed})", "au", "fl", id=batch.id))
    if st.done:
        row.append(btn("📄 Hisobot (CSV)", "au", "csv", id=batch.id))
    if row:
        b.row(*row)
    if batch.status in (AutoBatchStatus.RUNNING, AutoBatchStatus.PAUSED):
        b.row(btn("🔄 Yangilash", "au", "view", id=batch.id))
    b.row(btn("📋 Tarix", "au", "list"), btn("🤖 Markaz", "au", "hub"))
    return b.as_markup()


async def batch_screen(
    svc: Services, batch_id: int, admin: Admin | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    batch = await svc.auto.get(batch_id)
    st = await svc.auto.stats(batch.id)
    last = await svc.auto.last_processed(batch.id)
    manage = admin is None or has_perm(admin.role, Perm.AUTO_MANAGE)
    return render_batch(batch, st, last, rt.timezone), batch_kb(batch, st, manage)


async def hub_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    batches, ok_count, ok_amount = await svc.auto.today_summary()
    active = await svc.auto.active_batches()
    kassas = await svc.auto.kassa_choices()
    lines = [
        "🤖 <b>AVTO TO‘LOV MARKAZI</b>",
        LINE,
        "ID lar ro‘yxatini yuborasiz → summani <b>bir marta</b> kiritasiz → bot har bir ID ga "
        "o‘zi o‘tkazadi va natijani jonli ko‘rsatadi.",
        "",
        "📊 <b>So‘nggi 24 soat</b>",
        f"• 📦 Partiyalar: <b>{batches}</b>",
        f"• ✅ O‘tkazildi: <b>{ok_count}</b> ID • <b>{_money(ok_amount)}</b>",
        f"• 🏦 Faol kassalar: <b>{len(kassas)}</b>",
    ]
    b = InlineKeyboardBuilder()
    if active:
        lines += ["", "⚡ <b>Faol partiyalar</b>"]
        for batch in active:
            st = await svc.auto.stats(batch.id)
            lines.append(
                f"{_STATUS_ICON[batch.status]} #{batch.id} • {esc(batch.kassa_name)}\n"
                f"   <code>{progress_bar(st.percent, 10)}</code> {st.percent}% "
                f"({st.done}/{st.total})"
            )
            b.row(
                btn(
                    f"{_STATUS_ICON[batch.status]} #{batch.id} • {st.percent}% • "
                    f"{batch.kassa_name[:20]}",
                    "au",
                    "view",
                    id=batch.id,
                )
            )
        if any(x.status == AutoBatchStatus.RUNNING for x in active) and not await svc.redis.get(
            HEARTBEAT_KEY
        ):
            lines.append(
                "\n⚠️ <b>Worker ishlamayapti!</b> Avto to‘lov aynan worker jarayonida bajariladi: "
                "<code>python -m app.jobs</code>"
            )
    lines.append(LINE)
    if has_perm(admin.role, Perm.AUTO_MANAGE):
        b.row(btn("🚀 Yangi avto to‘lov", "au", "new"))
    b.row(btn("📋 Tarix", "au", "list"), btn("💳 Karta payout", "ap", "view"))
    b.row(btn("🔄 Yangilash", "au", "hub"))
    return "\n".join(lines), b.as_markup()


def _intake_text(parsed: ParsedIds, added: int | None = None) -> str:
    lines = []
    if added is not None:
        lines.append(f"📥 Qabul qilindi: <b>+{added}</b> ta ID")
    lines.append(f"📦 Jami: <b>{parsed.count}</b> ta ID")
    if parsed.with_amount:
        lines.append(f"💵 Summasi bilan: <b>{parsed.with_amount}</b> ta")
    if parsed.duplicates:
        lines.append(f"♻️ Takroriylar olib tashlandi: <b>{parsed.duplicates}</b>")
    if parsed.invalid:
        sample = ", ".join(f"<code>{esc(x)}</code>" for x in parsed.invalid[:5])
        lines.append(f"⚠️ Tanilmadi: <b>{len(parsed.invalid)}</b> ({sample})")
    if parsed.count > MAX_IDS:
        lines.append(f"\n⛔ Maksimal {MAX_IDS} ta ID. Ortiqchasini olib tashlang.")
    else:
        lines.append("\nYana yuborishingiz yoki «➡️ Davom etish» ni bosishingiz mumkin.")
    return "\n".join(lines)


def _intake_kb(parsed: ParsedIds) -> InlineKeyboardMarkup:
    rows = []
    if 0 < parsed.count <= MAX_IDS:
        rows.append([btn(f"➡️ Davom etish ({parsed.count} ta ID)", "au", "next")])
    rows.append([btn("🧹 Tozalash", "au", "clear"), btn("❌ Bekor", "au", "hub")])
    return kb(*rows)


def _amount_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in QUICK_AMOUNTS:
        b.button(
            text=f"{value:,}".replace(",", " "),
            callback_data=AdmCb(section="au", action="amt", id=value).pack(),
        )
    b.adjust(3)
    b.row(btn("❌ Bekor", "au", "hub"))
    return b.as_markup()


async def preview_screen(svc: Services, pv: Preview) -> tuple[str, InlineKeyboardMarkup]:
    batch = pv.batch
    items = await svc.auto.items(batch.id, limit=10)
    lines = [
        f"👁 <b>AVTO TO‘LOV — TEKSHIRUV</b> #{batch.id}",
        LINE,
        f"🏢 Kassa: <b>{esc(batch.kassa_name)}</b>",
        f"👥 ID lar: <b>{batch.total_count} ta</b>",
        _amount_line(batch),
        f"💰 Jami: <b>{_money(batch.total_amount)}</b>",
    ]
    if pv.balance is not None:
        enough = pv.balance >= batch.total_amount
        lines.append(
            f"🏦 Kassa balansi: <b>{_money(pv.balance)}</b> "
            + (
                "✅ yetadi"
                if enough
                else f"⚠️ yetmaydi (kam: {_money(batch.total_amount - pv.balance)})"
            )
        )
    elif pv.balance_error:
        lines.append(f"🏦 Kassa balansi: ⚠️ {esc(pv.balance_error[:120])}")
    else:
        lines.append("🏦 Kassa balansi: <i>bu kassa turi balans ko‘rsatmaydi</i>")
    if pv.recent_ids:
        lines.append(
            f"♻️ <b>{pv.recent_ids}</b> ta ID so‘nggi 24 soatda shu kassadan allaqachon pul olgan"
        )
    lines += [LINE, "<b>Ro‘yxat boshi:</b>"]
    lines += [
        f"{it.position}. <code>{esc(it.payer_id)}</code> — {_money(it.amount)}" for it in items
    ]
    if batch.total_count > len(items):
        lines.append(f"… va yana <b>{batch.total_count - len(items)}</b> ta")
    lines += [
        "",
        "🔒 Har bir ID oldin kassada tekshiriladi; topilmasa pul yuborilmaydi. "
        "Natija noma’lum bo‘lsa — qayta yuborilmaydi, tekshiruvga tushadi.",
    ]
    markup = kb(
        [btn("🚀 Boshlash", "au", "start", id=batch.id)],
        [btn("✏️ Summani o‘zgartirish", "au", "reamt", id=batch.id)],
        [btn("❌ Bekor qilish", "au", "drop", id=batch.id)],
    )
    return "\n".join(lines), markup


# =========================================================================== worker uchun
async def push_progress(bot: Bot | None, svc: Services, event: StepEvent) -> None:
    """Worker: progress xabarini tahrirlaydi; yakun/pauzada alohida xabar + CSV yuboradi."""
    batch = event.batch
    if bot is None or not batch.chat_id:
        return
    text, markup = await batch_screen(svc, batch.id)
    edited = False
    if batch.message_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=batch.chat_id,
                message_id=batch.message_id,
                reply_markup=markup,
            )
            edited = True
        except TelegramBadRequest as exc:
            edited = "not modified" in str(exc)
        except TelegramAPIError:
            edited = False
    if not edited and event.kind == "progress":
        try:
            msg = await bot.send_message(batch.chat_id, text, reply_markup=markup)
        except TelegramAPIError:
            return
        await svc.auto.set_progress_message(batch.id, msg.chat.id, msg.message_id)
    if event.kind == "finished":
        st = await svc.auto.stats(batch.id)
        caption = (
            f"🏁 <b>Avto to‘lov #{batch.id} yakunlandi</b>\n"
            f"🏢 {esc(batch.kassa_name)}\n"
            f"✅ {st.success} ta • {_money(st.success_amount)}\n"
            f"❌ {st.failed} ta xato • 🕵️ {st.review} ta tekshiruvda"
        )
        with suppress(TelegramAPIError):
            await bot.send_document(
                batch.chat_id,
                BufferedInputFile(
                    await svc.auto.report_csv(batch.id), filename=f"avto_tolov_{batch.id}.csv"
                ),
                caption=caption,
            )
    elif event.kind == "paused":
        with suppress(TelegramAPIError):
            await bot.send_message(
                batch.chat_id,
                f"⏸ <b>Avto to‘lov #{batch.id} pauzaga qo‘yildi</b>\n"
                f"⚠️ {esc(batch.pause_reason or '')}\n\n"
                "Muammoni hal qilib «▶️ Davom ettirish» ni bosing.",
                reply_markup=kb([btn("👁 Ochish", "au", "view", id=batch.id)]),
            )


# =========================================================================== hub
@router.message(F.text == texts.ADM_AUTO, HasPerm(Perm.AUTO_VIEW))
async def show_hub(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await hub_view(svc, admin)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "hub")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_hub(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    await call.answer()
    text, markup = await hub_view(svc, admin)
    await edit_or_send(call, text, markup)


# =========================================================================== yangi partiya
async def _ask_ids(
    call: CallbackQuery, state: FSMContext, svc: Services, bookmaker_id: int | None, name: str
) -> None:
    await state.set_state(AdminStates.auto_ids)
    await state.update_data(auto_bm=bookmaker_id or 0, auto_bm_name=name, auto_ids=None)
    balance_line = ""
    try:
        balance = await svc.auto.kassa_balance(bookmaker_id)
        if balance is not None:
            balance_line = f"\n💰 Balans: <b>{_money(balance)}</b>"
    except (DomainError, MobCashError) as exc:
        balance_line = f"\n⚠️ Balansni olib bo‘lmadi: {esc(exc.message[:100])}"
    await edit_or_send(
        call,
        f"🚀 <b>Yangi avto to‘lov</b>\n{LINE}\n🏢 Kassa: <b>{esc(name)}</b>{balance_line}\n"
        f"{LINE}\n{AUTO_HELP}",
        kb([btn("❌ Bekor", "au", "hub")]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "new")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_new(call: CallbackQuery, state: FSMContext, svc: Services) -> None:
    await state.clear()
    choices = await svc.auto.kassa_choices()
    if not choices:
        await call.answer(
            "Faol kassa yo‘q. «🏢 Kantoralar» bo‘limida kassa qo‘shing yoki yoqing.",
            show_alert=True,
        )
        return
    await call.answer()
    if len(choices) == 1:
        bookmaker_id, name = choices[0]
        await _ask_ids(call, state, svc, bookmaker_id, name)
        return
    rows = [[btn(f"🏢 {name}", "au", "kassa", id=bm_id or 0)] for bm_id, name in choices]
    rows.append([btn("❌ Bekor", "au", "hub")])
    await edit_or_send(
        call,
        f"🚀 <b>Yangi avto to‘lov</b>\n{LINE}\n🏢 Qaysi kassadan o‘tkazamiz?",
        kb(*rows),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "kassa")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_kassa(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services
) -> None:
    wanted = callback_data.id or None
    choices = dict(await svc.auto.kassa_choices())
    if wanted not in choices:
        await call.answer("Kassa topilmadi yoki o‘chirilgan.", show_alert=True)
        return
    await call.answer()
    await _ask_ids(call, state, svc, wanted, choices[wanted])


async def _accept(message: Message, state: FSMContext, new: ParsedIds) -> None:
    data = await state.get_data()
    parsed = ParsedIds.from_state(data.get("auto_ids"))
    before = parsed.count
    parsed.merge(new)
    await state.update_data(auto_ids=parsed.to_state())
    if parsed.count == 0:
        await message.answer(
            "⚠️ Xabarda o‘yin ID topilmadi (ID — 5–15 xonali raqam).\n\n" + AUTO_HELP,
            reply_markup=kb([btn("❌ Bekor", "au", "hub")]),
        )
        return
    await message.answer(
        _intake_text(parsed, parsed.count - before), reply_markup=_intake_kb(parsed)
    )


@router.message(AdminStates.auto_ids, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.AUTO_MANAGE))
async def on_ids_text(message: Message, state: FSMContext) -> None:
    await _accept(message, state, parse_ids(message.text or ""))


@router.message(AdminStates.auto_ids, F.document, HasPerm(Perm.AUTO_MANAGE))
async def on_ids_file(message: Message, state: FSMContext) -> None:
    doc = message.document
    name = (doc.file_name or "").lower() if doc else ""
    if doc is None or not name.endswith((".txt", ".csv")):
        await message.answer("⚠️ Faqat .txt yoki .csv fayl qabul qilinadi.")
        return
    if (doc.file_size or 0) > 256 * 1024:
        await message.answer("⚠️ Fayl juda katta (maks. 256 KB).")
        return
    buffer = await message.bot.download(doc)  # type: ignore[union-attr]
    if buffer is None:
        await message.answer(texts.ERROR_GENERIC)
        return
    try:
        parsed = parse_file(buffer.read())
    except DomainError as exc:
        await message.answer(f"⚠️ {exc.message}")
        return
    await _accept(message, state, parsed)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "clear")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_clear(call: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != AdminStates.auto_ids.state:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await state.update_data(auto_ids=None)
    await call.answer("🧹 Tozalandi")
    await edit_or_send(
        call, "🧹 Ro‘yxat tozalandi.\n\n" + AUTO_HELP, kb([btn("❌ Bekor", "au", "hub")])
    )


async def _create_and_preview(
    target: Message | CallbackQuery,
    state: FSMContext,
    svc: Services,
    actor: Actor,
    amount: Decimal | None,
) -> None:
    data = await state.get_data()
    parsed = ParsedIds.from_state(data.get("auto_ids"))
    try:
        batch = await svc.auto.create_draft(
            bookmaker_id=int(data.get("auto_bm") or 0) or None,
            parsed=parsed,
            default_amount=amount,
            actor=actor,
        )
    except DomainError as exc:
        warn = f"⚠️ {esc(exc.message)}"
        if isinstance(target, CallbackQuery):
            await target.answer(exc.message[:190], show_alert=True)
        else:
            await target.answer(warn, reply_markup=_amount_kb())
        return
    await state.set_state(None)
    await state.update_data(auto_draft=batch.id)
    text, markup = await preview_screen(svc, await svc.auto.preview(batch))
    if isinstance(target, CallbackQuery):
        await target.answer()
        await edit_or_send(target, text, markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "next")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_next(call: CallbackQuery, state: FSMContext, svc: Services, actor: Actor) -> None:
    data = await state.get_data()
    parsed = ParsedIds.from_state(data.get("auto_ids"))
    if await state.get_state() != AdminStates.auto_ids.state or not parsed.count:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    if parsed.count > MAX_IDS:
        await call.answer(f"Maksimal {MAX_IDS} ta ID.", show_alert=True)
        return
    if not parsed.without_amount:
        await _create_and_preview(call, state, svc, actor, None)
        return
    await state.set_state(AdminStates.auto_amount)
    await call.answer()
    note = (
        f"\n(Summasi yozilgan {parsed.with_amount} ta ID o‘z summasi bilan ketadi.)"
        if parsed.with_amount
        else ""
    )
    await edit_or_send(
        call,
        f"💰 <b>Har bir ID ga qanchadan o‘tkazilsin?</b>\n{LINE}\n"
        f"📦 Summasiz ID lar: <b>{parsed.without_amount} ta</b>{note}\n\n"
        "Summani yozing (masalan <code>10000</code>, <code>15 000</code>, <code>20k</code>) "
        "yoki tanlang 👇",
        _amount_kb(),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "amt")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_amount(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, actor: Actor
) -> None:
    if await state.get_state() != AdminStates.auto_amount.state:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    await _create_and_preview(call, state, svc, actor, Decimal(callback_data.id))


@router.message(AdminStates.auto_amount, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.AUTO_MANAGE))
async def on_amount(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    raw = (message.text or "").strip().lower()
    multiplier = Decimal(1)
    for suffix in ("ming", "k"):
        if raw.endswith(suffix):
            raw, multiplier = raw[: -len(suffix)].strip(), Decimal(1000)
            break
    amount = parse_amount(raw)
    if amount is None:
        await message.answer(
            "⚠️ Summa noto‘g‘ri. Masalan: <code>10000</code> yoki <code>15 000</code>",
            reply_markup=_amount_kb(),
        )
        return
    await _create_and_preview(message, state, svc, actor, amount * multiplier)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action.in_({"reamt", "drop"}))),
    HasPerm(Perm.AUTO_MANAGE),
)
async def cb_reamount_or_drop(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    try:
        batch = await svc.auto.get(callback_data.id)
        if batch.status == AutoBatchStatus.DRAFT:
            await svc.auto.cancel(batch.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    data = await state.get_data()
    if callback_data.action == "drop" or not data.get("auto_ids"):
        await state.clear()
        await call.answer("❌ Bekor qilindi")
        text, markup = await hub_view(svc, admin)
        await edit_or_send(call, text, markup)
        return
    parsed = ParsedIds.from_state(data.get("auto_ids"))
    await state.set_state(AdminStates.auto_amount)
    await call.answer()
    await edit_or_send(
        call,
        f"💰 <b>Yangi summa</b>\n{LINE}\n📦 Summasiz ID lar: <b>{parsed.without_amount} ta</b>\n\n"
        "Har biriga qanchadan o‘tkazilsin?",
        _amount_kb(),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "start")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_start_ask(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    batch = await svc.auto.get(callback_data.id)
    if batch.status != AutoBatchStatus.DRAFT:
        await call.answer("Bu partiya allaqachon boshlangan.", show_alert=True)
        return
    await call.answer()
    await edit_or_send(
        call,
        f"⚠️ <b>DIQQAT — TASDIQLANG</b>\n{LINE}\n"
        f"🏢 {esc(batch.kassa_name)}\n"
        f"👥 <b>{batch.total_count}</b> ta ID ga jami <b>{_money(batch.total_amount)}</b> "
        "o‘tkaziladi.\n\n"
        "Boshlangach bot hammasini o‘zi bajaradi. O‘tkazilgan pulni ortga qaytarib bo‘lmaydi; "
        "jarayonni istalgan payt ⏸ pauza yoki ⛔ to‘xtatish mumkin.",
        kb(
            [btn("✅ Ha, boshlash", "au", "go", id=batch.id)],
            [btn("🔙 Orqaga", "au", "pv", id=batch.id)],
        ),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "pv")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_preview(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    batch = await svc.auto.get(callback_data.id)
    if batch.status != AutoBatchStatus.DRAFT:
        await call.answer("Bu partiya allaqachon boshlangan.", show_alert=True)
        return
    await call.answer()
    text, markup = await preview_screen(svc, await svc.auto.preview(batch))
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "go")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_go(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    msg = call.message if isinstance(call.message, Message) else None
    try:
        await svc.auto.start(
            callback_data.id,
            actor,
            msg.chat.id if msg else call.from_user.id,
            msg.message_id if msg else None,
        )
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await state.clear()
    await call.answer("🚀 Boshlandi! Bot o‘zi o‘tkazadi.", show_alert=False)
    text, markup = await batch_screen(svc, callback_data.id, admin)
    await edit_or_send(call, text, markup)


# =========================================================================== partiya
@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "view")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_view(call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin) -> None:
    try:
        text, markup = await batch_screen(svc, callback_data.id, admin)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer()
    await edit_or_send(call, text, markup)
    batch = await svc.auto.get(callback_data.id)
    msg = call.message
    if (
        batch.status in (AutoBatchStatus.RUNNING, AutoBatchStatus.PAUSED)
        and isinstance(msg, Message)
        and has_perm(admin.role, Perm.AUTO_MANAGE)
    ):
        # Worker endi shu xabarni jonli yangilaydi.
        await svc.auto.set_progress_message(batch.id, msg.chat.id, msg.message_id)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action.in_({"pause", "resume"}))),
    HasPerm(Perm.AUTO_MANAGE),
)
async def cb_pause_resume(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        if callback_data.action == "pause":
            await svc.auto.pause(callback_data.id, actor)
            note = "⏸ Pauza — joriy ID tugagach to‘xtaydi"
        else:
            await svc.auto.resume(callback_data.id, actor)
            note = "▶️ Davom etmoqda"
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(note)
    text, markup = await batch_screen(svc, callback_data.id, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "stop")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_stop_ask(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    st = await svc.auto.stats(callback_data.id)
    await call.answer()
    await edit_or_send(
        call,
        f"⛔ <b>Avto to‘lov #{callback_data.id} to‘xtatilsinmi?</b>\n\n"
        f"Navbatdagi <b>{st.pending}</b> ta ID ga pul yuborilmaydi. "
        f"O‘tkazilgan {st.success} ta o‘zgarmaydi.",
        kb(
            [btn("✅ Ha, to‘xtatish", "au", "stop_ok", id=callback_data.id)],
            [btn("🔙 Orqaga", "au", "view", id=callback_data.id)],
        ),
    )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "stop_ok")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_stop(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        await svc.auto.cancel(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("⛔ To‘xtatildi")
    text, markup = await batch_screen(svc, callback_data.id, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "retry")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_retry(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        count = await svc.auto.retry_failed(callback_data.id, actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    msg = call.message
    if isinstance(msg, Message):
        await svc.auto.set_progress_message(callback_data.id, msg.chat.id, msg.message_id)
    await call.answer(f"🔁 {count} ta ID qayta navbatga qo‘yildi")
    text, markup = await batch_screen(svc, callback_data.id, admin)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "csv")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_csv(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    content = await svc.auto.report_csv(callback_data.id)
    await call.answer()
    if isinstance(call.message, Message):
        await call.message.answer_document(
            BufferedInputFile(content, filename=f"avto_tolov_{callback_data.id}.csv")
        )


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "fl")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_failed(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    page = max(callback_data.page, 0)
    items = await svc.auto.items(
        callback_data.id, (AutoItemStatus.FAILED,), LIST_PAGE + 1, page * LIST_PAGE
    )
    lines = [f"❌ <b>Avto to‘lov #{callback_data.id} — xatolar</b>", LINE]
    for it in items[:LIST_PAGE]:
        lines.append(
            f"{it.position}. <code>{esc(it.payer_id)}</code> — {_money(it.amount)}\n"
            f"     <i>{esc((it.error or '—')[:100])}</i>"
        )
    if not items:
        lines.append("Xato yo‘q 🎉")
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(btn("◀️", "au", "fl", id=callback_data.id, page=page - 1))
    if len(items) > LIST_PAGE:
        nav.append(btn("▶️", "au", "fl", id=callback_data.id, page=page + 1))
    if nav:
        b.row(*nav)
    b.row(btn(texts.BTN_BACK, "au", "view", id=callback_data.id))
    await call.answer()
    await edit_or_send(call, "\n".join(lines), b.as_markup())


async def _review_screen(svc: Services, batch_id: int) -> tuple[str, InlineKeyboardMarkup]:
    items = await svc.auto.items(batch_id, (AutoItemStatus.REVIEW,), PER_PAGE)
    lines = [
        f"🕵️ <b>Avto to‘lov #{batch_id} — tekshiruv</b>",
        LINE,
        "Bu ID larga so‘rov yuborilgan, lekin kassa javobi kelmagan. Kassa panelida "
        "tekshiring va belgilang:\n✅ — pul tushgan, ❌ — tushmagan (keyin qayta yuborish mumkin).",
        "",
    ]
    b = InlineKeyboardBuilder()
    for it in items:
        lines.append(
            f"{it.position}. <code>{esc(it.payer_id)}</code> — {_money(it.amount)}\n"
            f"     <i>{esc((it.error or '')[:100])}</i>"
        )
        b.row(
            btn(f"✅ {it.payer_id}", "au", "rvok", id=it.id),
            btn("❌ tushmagan", "au", "rvno", id=it.id),
        )
    if not items:
        lines.append("Tekshiruvda ID qolmadi ✅")
    b.row(btn(texts.BTN_BACK, "au", "view", id=batch_id))
    return "\n".join(lines), b.as_markup()


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "rv")), HasPerm(Perm.AUTO_MANAGE)
)
async def cb_review(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    await call.answer()
    text, markup = await _review_screen(svc, callback_data.id)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action.in_({"rvok", "rvno"}))),
    HasPerm(Perm.AUTO_MANAGE),
)
async def cb_review_mark(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, actor: Actor
) -> None:
    try:
        item = await svc.auto.resolve_review(
            callback_data.id, callback_data.action == "rvok", actor
        )
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Belgilandi")
    text, markup = await _review_screen(svc, item.batch_id)
    await edit_or_send(call, text, markup)


# =========================================================================== tarix
@router.callback_query(
    AdmCb.filter((F.section == "au") & (F.action == "list")), HasPerm(Perm.AUTO_VIEW)
)
async def cb_list(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    page = max(callback_data.page, 0)
    batches = await svc.auto.list_page(page, PER_PAGE + 1)
    b = InlineKeyboardBuilder()
    for batch in batches[:PER_PAGE]:
        b.row(
            btn(
                f"{_STATUS_ICON[batch.status]} #{batch.id} • {batch.kassa_name[:14]} • "
                f"{batch.total_count} ID • {fmt_money(batch.total_amount)}",
                "au",
                "view",
                id=batch.id,
            )
        )
    pager(b, "au", "list", page, len(batches) > PER_PAGE)
    b.row(btn("🤖 Markaz", "au", "hub"))
    await call.answer()
    await edit_or_send(
        call,
        f"📋 <b>Avto to‘lov tarixi</b>\n{LINE}"
        + ("" if batches else "\nHozircha partiyalar yo‘q."),
        b.as_markup(),
    )
