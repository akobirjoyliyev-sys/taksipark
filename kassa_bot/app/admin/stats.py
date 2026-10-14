from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, pager
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt
from app.models import Admin
from app.repositories.admins import AuditRepository
from app.services.container import Services
from app.services.stats import PeriodReport, parse_range, period_bounds

router = Router(name="admin_stats")
AUDIT_PER_PAGE = 10

_DEP = (
    ("paid", "✅ To‘langan"),
    ("pending", "⏳ Pending"),
    ("failed", "❌ Xato"),
    ("expired", "⌛ Muddati o‘tgan"),
    ("cancelled", "🚫 Bekor"),
)
_WD = (
    ("pending", "⏳ Pending"),
    ("approved", "🟢 Tasdiqlangan"),
    ("processing", "🔄 Jarayonda"),
    ("paid", "✅ To‘langan"),
    ("rejected", "❌ Rad etilgan"),
    ("failed", "⚠️ Xato"),
)


def stats_kb(admin: Admin) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        btn("📅 Bugun", "st", "period", arg="day"),
        btn("🗓 7 kun", "st", "period", arg="week"),
        btn("📆 30 kun", "st", "period", arg="month"),
    )
    b.row(btn("🔎 Sana oralig‘i", "st", "range"), btn("📥 CSV eksport", "st", "csv"))
    if has_perm(admin.role, Perm.AUDIT_VIEW):
        b.row(btn("📜 Audit log", "st", "audit"))
    return b.as_markup()


def render_report(r: PeriodReport, tz: str) -> str:
    def agg_line(items: tuple[tuple[str, str], ...], data: dict) -> str:
        parts = []
        for key, label in items:
            agg = data.get(key)
            if agg and agg.count:
                parts.append(f"   {label}: {agg.count} ta / {fmt_money(agg.amount)}")
        return "\n".join(parts) or "   —"

    growth = "\n".join(f"   {d.strftime('%d.%m')}: +{n}" for d, n in r.growth[-10:]) or "   —"
    return (
        f"📊 <b>Hisobot</b>: {fmt_dt(r.start, tz)} — {fmt_dt(r.end, tz)}\n\n"
        f"📥 <b>To‘ldirishlar</b> (tasdiqlangan): {r.deposits_paid.count} ta / "
        f"{fmt_money(r.deposits_paid.amount)}\n"
        f"{agg_line(_DEP, r.deposit_status)}\n\n"
        f"📤 <b>Yechishlar</b> (to‘langan): {r.withdrawals_paid.count} ta / "
        f"{fmt_money(r.withdrawals_paid.amount)}\n"
        f"{agg_line(_WD, r.withdrawal_status)}\n\n"
        f"🏦 <b>Mob-Cash</b>\n"
        f"   📥 P2P tushirilgan: {r.p2p_credited.count} ta / {fmt_money(r.p2p_credited.amount)}\n"
        f"   📤 Kartaga to‘langan: {r.mcwd_paid.count} ta / {fmt_money(r.mcwd_paid.amount)}\n\n"
        f"🎁 Bonuslar: {fmt_money(r.bonuses)}\n"
        f"👥 Yangi foydalanuvchilar: {r.new_users} (jami: {r.total_users})\n"
        f"📈 Kunlik o‘sish:\n{growth}"
    )


async def _report(svc: Services, start: datetime, end: datetime, state: FSMContext) -> str:
    rt = await svc.settings.snapshot()
    await state.update_data(st_range=[start.isoformat(), end.isoformat()])
    return render_report(await svc.stats.period_report(start, end, rt.timezone), rt.timezone)


@router.message(F.text == texts.ADM_STATS, HasPerm(Perm.STATS_VIEW))
async def show_stats(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    rt = await svc.settings.snapshot()
    start, end = period_bounds("day", rt.timezone)
    await message.answer(await _report(svc, start, end, state), reply_markup=stats_kb(admin))


@router.callback_query(
    AdmCb.filter((F.section == "st") & (F.action == "period")), HasPerm(Perm.STATS_VIEW)
)
async def cb_period(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    rt = await svc.settings.snapshot()
    start, end = period_bounds(callback_data.arg, rt.timezone)
    await call.answer()
    await edit_or_send(call, await _report(svc, start, end, state), stats_kb(admin))


@router.callback_query(
    AdmCb.filter((F.section == "st") & (F.action == "range")), HasPerm(Perm.STATS_VIEW)
)
async def cb_range(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.stats_range)
    await call.answer()
    await edit_or_send(call, "🔎 Sana oralig‘ini kiriting:\n<code>2026-10-01 2026-10-06</code>")


@router.message(AdminStates.stats_range, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.STATS_VIEW))
async def on_range(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    rt = await svc.settings.snapshot()
    try:
        start, end = parse_range(message.text or "", rt.timezone)
    except DomainError as exc:
        await message.answer(exc.message)
        return
    await state.set_state(None)
    await message.answer(await _report(svc, start, end, state), reply_markup=stats_kb(admin))


@router.callback_query(
    AdmCb.filter((F.section == "st") & (F.action == "csv")), HasPerm(Perm.STATS_VIEW)
)
async def cb_csv(call: CallbackQuery, state: FSMContext, svc: Services) -> None:
    rt = await svc.settings.snapshot()
    data = await state.get_data()
    if data.get("st_range"):
        start, end = (datetime.fromisoformat(x) for x in data["st_range"])
    else:
        start, end = period_bounds("month", rt.timezone)
    content = await svc.stats.export_csv(start, end, rt.timezone)
    await call.answer()
    name = f"kassa_{start.date().isoformat()}_{end.date().isoformat()}.csv"
    if call.message is not None:
        await call.message.answer_document(
            BufferedInputFile(content, filename=name),
            caption=f"📥 Tranzaksiyalar: {fmt_dt(start, rt.timezone)} — {fmt_dt(end, rt.timezone)}",
        )


@router.callback_query(
    AdmCb.filter((F.section == "st") & (F.action == "audit")), HasPerm(Perm.AUDIT_VIEW)
)
async def cb_audit(call: CallbackQuery, callback_data: AdmCb, svc: Services) -> None:
    rt = await svc.settings.snapshot()
    page = max(callback_data.page, 0)
    rows = await AuditRepository(svc.session).latest(AUDIT_PER_PAGE + 1, page * AUDIT_PER_PAGE)
    lines = [
        f"• {fmt_dt(r.created_at, rt.timezone)} | {esc(r.actor_role)} "
        f"<code>{r.actor_telegram_id or '-'}</code>\n  {esc(r.action)} → "
        f"{esc(r.entity_type)}:{esc(r.entity_id or '-')}"
        + (f"\n  💬 {esc(r.comment[:80])}" if r.comment else "")
        for r in rows[:AUDIT_PER_PAGE]
    ]
    b = InlineKeyboardBuilder()
    pager(b, "st", "audit", page, len(rows) > AUDIT_PER_PAGE)
    b.row(btn(texts.BTN_BACK, "st", "period", arg="day"))
    await call.answer()
    await edit_or_send(call, "📜 <b>Audit log</b>\n\n" + ("\n".join(lines) or "—"), b.as_markup())
