from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.bot.keyboards.callbacks import CardCb, HistoryCb, MenuCb
from app.bot.keyboards.user import cards_manage_kb, history_kb, main_menu_kb, wallet_kb
from app.bot.utils import edit_or_send, safe_delete
from app.core.enums import PaymentStatus, WithdrawalStatus
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.utils import fmt_dt
from app.models import User
from app.repositories.payments import PaymentRepository
from app.repositories.wallets import LedgerRepository
from app.repositories.withdrawals import WithdrawalRepository
from app.services.bonus import VipProgress
from app.services.container import Services
from app.services.settings import RuntimeSettings

router = Router(name="wallet")
PER_PAGE = 8

_DEP_FILTERS: dict[str, tuple[PaymentStatus, ...] | None] = {
    "all": None,
    "pending": (PaymentStatus.PENDING,),
    "ok": (PaymentStatus.PAID,),
    "fail": (PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED),
}
_WD_FILTERS: dict[str, tuple[WithdrawalStatus, ...] | None] = {
    "all": None,
    "pending": (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED, WithdrawalStatus.PROCESSING),
    "ok": (WithdrawalStatus.PAID,),
    "fail": (WithdrawalStatus.REJECTED, WithdrawalStatus.FAILED),
}


def is_test_mode(rt: RuntimeSettings) -> bool:
    return rt.payment_mode != "production"


def vip_lines(progress: VipProgress) -> tuple[str, str]:
    """(VIP daraja matni, keyingi darajagacha progress qatori)."""
    if progress.current:
        vip = progress.current.name
        if progress.current.bonus_percent:
            vip += f" (+{progress.current.bonus_percent.normalize():f}%)"
    else:
        vip = texts.VIP_NONE
    if progress.next is None:
        return vip, "🎉 Eng yuqori VIP darajadasiz!\n"
    filled = progress.percent // 10
    line = (
        f"📈 {progress.next.name} darajaga: {'▰' * filled}{'▱' * (10 - filled)} "
        f"{progress.percent}% (yana {fmt_money(progress.left)})\n"
    )
    return vip, line


async def wallet_text(svc: Services, user: User, rt: RuntimeSettings) -> str:
    wallet = await svc.users.get_wallet(user.id)
    progress = await svc.vip.progress(wallet.total_deposit)
    vip, vip_progress = vip_lines(progress)
    text = texts.WALLET.format(
        available=fmt_money(wallet.available),
        blocked=fmt_money(wallet.blocked),
        bonus=fmt_money(wallet.bonus_balance),
        total_deposit=fmt_money(wallet.total_deposit),
        total_withdraw=fmt_money(wallet.total_withdraw),
        vip=vip,
        vip_progress=vip_progress,
    )
    return text + (texts.TEST_MODE_NOTE if is_test_mode(rt) else "")


@router.message(F.text == texts.BTN_WALLET)
async def show_wallet(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    await message.answer(await wallet_text(svc, user, rt), reply_markup=wallet_kb())


@router.callback_query(MenuCb.filter(F.action == "wallet"))
async def cb_wallet(
    call: CallbackQuery, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    await state.clear()
    await call.answer()
    await edit_or_send(call, await wallet_text(svc, user, rt), wallet_kb())


@router.callback_query(MenuCb.filter(F.action == "wgame"))
async def cb_wgame_unavailable(call: CallbackQuery) -> None:
    # MobCash o‘chiq rejimida mobcash routeri bu callbackni ushlamaydi.
    await call.answer("⚠️ Bu funksiya hozircha mavjud emas.", show_alert=True)


@router.callback_query(MenuCb.filter(F.action.in_({"back", "cancel"})))
async def cb_back(call: CallbackQuery, callback_data: MenuCb, state: FSMContext) -> None:
    await state.clear()
    await call.answer(texts.CANCELLED if callback_data.action == "cancel" else None)
    if isinstance(call.message, Message):
        await safe_delete(call.message)
        await call.message.answer(texts.MAIN_MENU, reply_markup=main_menu_kb())


@router.callback_query(HistoryCb.filter())
async def cb_history(
    call: CallbackQuery, callback_data: HistoryCb, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    kind, status, page = callback_data.kind, callback_data.status, max(callback_data.page, 0)
    lines: list[str] = []
    has_next = False
    if kind == "dep":
        payments = await PaymentRepository(svc.session).list_for_user(
            user.id, _DEP_FILTERS.get(status), PER_PAGE + 1, page * PER_PAGE
        )
        has_next = len(payments) > PER_PAGE
        lines = [
            f"#{p.id} • {fmt_money(p.amount)} • {texts.PAYMENT_STATUS[p.status]}\n"
            f"   🕒 {fmt_dt(p.created_at, rt.timezone)}"
            for p in payments[:PER_PAGE]
        ]
    elif kind == "wd":
        items = await WithdrawalRepository(svc.session).list_for_user(
            user.id, _WD_FILTERS.get(status), PER_PAGE + 1, page * PER_PAGE
        )
        has_next = len(items) > PER_PAGE
        lines = [
            f"#{w.id} • {fmt_money(w.amount)} • {texts.WITHDRAW_STATUS[w.status]}\n"
            f"   💳 {w.card_mask} • 🕒 {fmt_dt(w.created_at, rt.timezone)}"
            for w in items[:PER_PAGE]
        ]
    else:
        kind, status = "led", "all"
        entries = await LedgerRepository(svc.session).list_for_user(
            user.id, limit=PER_PAGE + 1, offset=page * PER_PAGE
        )
        has_next = len(entries) > PER_PAGE
        lines = [
            f"{'➕' if e.direction.value == 'credit' else '➖'} {fmt_money(e.amount)} — "
            f"{texts.LEDGER_REASON.get(e.reason, e.reason)}\n"
            f"   🕒 {fmt_dt(e.created_at, rt.timezone)}"
            for e in entries[:PER_PAGE]
        ]
    header = texts.HISTORY_TITLE.format(
        kind=texts.HISTORY_KIND[kind], status=texts.HISTORY_STATUS.get(status, "barchasi")
    )
    body = "\n\n".join(lines) if lines else texts.HISTORY_EMPTY
    await call.answer()
    await edit_or_send(call, f"{header}\n\n{body}", history_kb(kind, status, page, has_next))


@router.callback_query(CardCb.filter(F.action == "list"))
async def cb_cards(call: CallbackQuery, svc: Services, user: User) -> None:
    cards = await svc.cards.list_page(user)
    await call.answer()
    await edit_or_send(call, texts.CARDS_TITLE, cards_manage_kb(cards))


@router.callback_query(CardCb.filter(F.action == "del"))
async def cb_card_delete(
    call: CallbackQuery, callback_data: CardCb, svc: Services, user: User
) -> None:
    try:
        await svc.cards.remove(user, callback_data.id)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(texts.CARD_REMOVED)
    await edit_or_send(call, texts.CARDS_TITLE, cards_manage_kb(await svc.cards.list_page(user)))
