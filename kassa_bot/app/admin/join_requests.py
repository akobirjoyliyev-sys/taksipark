from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import HasPerm, btn, confirm_kb, pager
from app.bot.keyboards.callbacks import AdmCb
from app.bot.utils import edit_or_send, esc
from app.core.enums import JoinRequestStatus
from app.core.errors import DomainError
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt
from app.models import Admin
from app.services.audit import Actor
from app.services.container import Services

router = Router(name="admin_join")
PER_PAGE = 8
STATUS_LABELS = {
    "pending": ("⏳ Kutilmoqda", JoinRequestStatus.PENDING),
    "approved": ("✅ Qabul", JoinRequestStatus.APPROVED),
    "declined": ("❌ Rad", JoinRequestStatus.DECLINED),
}


def _arg(status: str, chat_index: int) -> str:
    return f"{status}.{chat_index}"


def _parse_arg(arg: str) -> tuple[str, int]:
    status, _, idx = (arg or "pending.0").partition(".")
    return (status if status in STATUS_LABELS else "pending"), int(idx) if idx.isdigit() else 0


async def list_view(
    svc: Services, admin: Admin, arg: str, page: int
) -> tuple[str, InlineKeyboardMarkup]:
    status_key, chat_index = _parse_arg(arg)
    chats = await svc.join_requests.chats()
    chat_options: list[tuple[int | None, str]] = [(None, "Barcha kanallar"), *chats]
    chat_index = chat_index % len(chat_options)
    chat_id, chat_title = chat_options[chat_index]
    label, status = STATUS_LABELS[status_key]
    rows, total = await svc.join_requests.list_page(status, chat_id, page, PER_PAGE)

    b = InlineKeyboardBuilder()
    b.row(
        *[
            btn(("• " if k == status_key else "") + v[0], "jr", "list", arg=_arg(k, chat_index))
            for k, v in STATUS_LABELS.items()
        ]
    )
    next_chat = (chat_index + 1) % len(chat_options)
    b.row(btn(f"📢 {chat_title[:30]} ⟳", "jr", "list", arg=_arg(status_key, next_chat)))
    for r in rows:
        b.row(
            btn(
                f"#{r.id} • {r.full_name or r.user_telegram_id} • {(r.chat_title or '')[:15]}"[:60],
                "jr",
                "view",
                id=r.id,
                arg=_arg(status_key, chat_index),
            )
        )
    pager(b, "jr", "list", page, (page + 1) * PER_PAGE < total, arg=_arg(status_key, chat_index))
    if status == JoinRequestStatus.PENDING and total and has_perm(admin.role, Perm.JOIN_PROCESS):
        b.row(
            btn(
                "✅ Barchasini qabul qilish (50 tagacha)",
                "jr",
                "all",
                arg=_arg(status_key, chat_index),
            )
        )
    text = f"📋 <b>Join Requestlar</b>\n\nFilter: {label} • {esc(chat_title)}\n" f"Jami: {total}"
    return text, b.as_markup()


@router.message(F.text == texts.ADM_JOIN, HasPerm(Perm.JOIN_VIEW))
async def show_join(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await list_view(svc, admin, "pending.0", 0)
    await message.answer(text, reply_markup=markup)


@router.callback_query(
    AdmCb.filter((F.section == "jr") & (F.action == "list")), HasPerm(Perm.JOIN_VIEW)
)
async def cb_list(call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin) -> None:
    text, markup = await list_view(svc, admin, callback_data.arg, max(callback_data.page, 0))
    await call.answer()
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "jr") & (F.action == "view")), HasPerm(Perm.JOIN_VIEW)
)
async def cb_view(call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin) -> None:
    rt = await svc.settings.snapshot()
    r = await svc.join_requests.get(callback_data.id)
    text = (
        f"📋 <b>So‘rov #{r.id}</b>\n\n"
        f"📢 Kanal: {esc(r.chat_title)} (<code>{r.chat_id}</code>)\n"
        f"👤 {esc(r.full_name)}"
        + (f" (@{esc(r.username)})" if r.username else "")
        + f" — <code>{r.user_telegram_id}</code>\n"
        f"🕒 {fmt_dt(r.created_at, rt.timezone)}\n"
        f"Holat: {STATUS_LABELS[r.status.value][0]}"
        + (
            f"\nKo‘rib chiqqan: <code>{r.processed_by}</code> • "
            f"{fmt_dt(r.processed_at, rt.timezone)}"
            if r.processed_by
            else ""
        )
    )
    b = InlineKeyboardBuilder()
    if r.status == JoinRequestStatus.PENDING and has_perm(admin.role, Perm.JOIN_PROCESS):
        b.row(
            btn("✅ Qabul qilish", "jr", "decide", id=r.id, arg="1"),
            btn("❌ Rad etish", "jr", "decide", id=r.id, arg="0"),
        )
    b.row(btn(texts.BTN_BACK, "jr", "list", arg=callback_data.arg or "pending.0"))
    await call.answer()
    await edit_or_send(call, text, b.as_markup())


@router.callback_query(
    AdmCb.filter((F.section == "jr") & (F.action == "decide")), HasPerm(Perm.JOIN_PROCESS)
)
async def cb_decide(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    try:
        await svc.join_requests.decide(callback_data.id, callback_data.arg == "1", actor)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer("✅ Bajarildi")
    text, markup = await list_view(svc, admin, "pending.0", 0)
    await edit_or_send(call, text, markup)


@router.callback_query(
    AdmCb.filter((F.section == "jr") & (F.action == "all")), HasPerm(Perm.JOIN_PROCESS)
)
async def cb_all(call: CallbackQuery, callback_data: AdmCb) -> None:
    await call.answer()
    await edit_or_send(
        call,
        "✅ Filterdagi barcha kutilayotgan so‘rovlar qabul qilinsinmi?",
        confirm_kb("jr", "all_do", arg=callback_data.arg),
    )


@router.callback_query(
    AdmCb.filter((F.section == "jr") & (F.action == "all_do")), HasPerm(Perm.JOIN_PROCESS)
)
async def cb_all_do(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    _, chat_index = _parse_arg(callback_data.arg)
    chats = await svc.join_requests.chats()
    options: list[int | None] = [None, *[c[0] for c in chats]]
    chat_id = options[chat_index % len(options)]
    count = await svc.join_requests.approve_all(chat_id, actor)
    await call.answer(f"✅ {count} ta so‘rov qabul qilindi", show_alert=True)
    text, markup = await list_view(svc, admin, callback_data.arg, 0)
    await edit_or_send(call, text, markup)
