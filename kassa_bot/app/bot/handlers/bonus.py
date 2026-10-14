from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import texts
from app.bot.keyboards.callbacks import BonusCb
from app.bot.keyboards.user import bonus_back_kb, bonus_kb, referral_kb
from app.bot.states import PromoStates
from app.bot.utils import edit_or_send, esc
from app.core.enums import PromoType
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.utils import fmt_dt, mask_name
from app.models import User
from app.services.container import Services
from app.services.settings import RuntimeSettings

router = Router(name="bonus")
FRIENDS_PER_PAGE = 10


@router.message(F.text == texts.BTN_BONUS)
async def show_bonus(message: Message, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.clear()
    await message.answer(texts.BONUS_MENU, reply_markup=bonus_kb(rt.vip_section_enabled))


@router.callback_query(BonusCb.filter(F.action == "menu"))
async def cb_menu(call: CallbackQuery, state: FSMContext, rt: RuntimeSettings) -> None:
    await state.clear()
    await call.answer()
    await edit_or_send(call, texts.BONUS_MENU, bonus_kb(rt.vip_section_enabled))


# --------------------------------------------------------------------------- promokod
@router.callback_query(BonusCb.filter(F.action == "promo"))
async def cb_promo(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoStates.code)
    await call.answer()
    await edit_or_send(call, texts.PROMO_ASK, bonus_back_kb())


@router.message(PromoStates.code, F.text, ~F.text.in_(texts.MAIN_MENU_TEXTS))
async def on_promo_code(
    message: Message, state: FSMContext, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    try:
        result = await svc.promo.activate(user, message.text or "")
    except DomainError as exc:
        await message.answer(exc.message, reply_markup=bonus_back_kb())
        return
    await state.clear()
    if result.applied_now:
        await message.answer(
            texts.PROMO_APPLIED_NOW.format(amount=fmt_money(result.bonus)),
            reply_markup=bonus_kb(rt.vip_section_enabled),
        )
        return
    promo = result.promo
    value = (
        fmt_money(promo.bonus_value)
        if promo.bonus_type == PromoType.FIXED
        else f"{promo.bonus_value}%"
    )
    await message.answer(
        texts.PROMO_RESERVED.format(min=fmt_money(promo.min_deposit), value=value),
        reply_markup=bonus_kb(rt.vip_section_enabled),
    )


# --------------------------------------------------------------------------- VIP
@router.callback_query(BonusCb.filter(F.action == "vip"))
async def cb_vip(call: CallbackQuery, svc: Services, user: User, rt: RuntimeSettings) -> None:
    if not rt.vip_section_enabled:
        await call.answer(texts.VIP_DISABLED, show_alert=True)
        return
    wallet = await svc.users.get_wallet(user.id)
    levels = await svc.vip.levels()
    progress = await svc.vip.progress(wallet.total_deposit)
    if progress.next is not None:
        filled = progress.percent // 10
        progress_text = texts.VIP_NEXT.format(
            name=esc(progress.next.name),
            left=fmt_money(progress.left),
            bar="▰" * filled + "▱" * (10 - filled),
            pct=progress.percent,
        )
    else:
        progress_text = texts.VIP_MAX if levels else ""
    level_lines = (
        "\n".join(
            f"{'✅' if progress.current and lv.id == progress.current.id else '▫️'} "
            f"{esc(lv.name)} — {fmt_money(lv.min_total_deposit)} dan, +{lv.bonus_percent}%"
            for lv in levels
        )
        or "—"
    )
    await call.answer()
    await edit_or_send(
        call,
        texts.VIP_TEXT.format(
            level=esc(progress.current.name) if progress.current else texts.VIP_NONE,
            percent=progress.current.bonus_percent if progress.current else 0,
            total=fmt_money(wallet.total_deposit),
            progress=progress_text,
            levels=level_lines,
        ),
        bonus_back_kb(),
    )


# --------------------------------------------------------------------------- referal
@router.callback_query(BonusCb.filter(F.action == "ref"))
async def cb_referral(call: CallbackQuery, svc: Services, user: User, rt: RuntimeSettings) -> None:
    if not rt.referral_enabled:
        await call.answer(texts.REFERRAL_DISABLED, show_alert=True)
        return
    stats = await svc.referral.stats(user)
    await call.answer()
    await edit_or_send(
        call,
        texts.REFERRAL_TEXT.format(
            percent=stats.percent,
            link=stats.link,
            count=stats.count,
            earned=fmt_money(stats.earned),
            withdrawn=fmt_money(stats.withdrawn),
            balance=fmt_money(stats.balance),
        ),
        referral_kb(stats.link),
    )


@router.callback_query(BonusCb.filter(F.action.in_({"top", "top10d"})))
async def cb_top(call: CallbackQuery, callback_data: BonusCb, svc: Services) -> None:
    last_days = callback_data.action == "top10d"
    rows = await svc.referral.top(days=10 if last_days else None)
    title = texts.REF_TOP_10D_TITLE if last_days else texts.REF_TOP_TITLE
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [
        texts.REF_TOP_ROW.format(
            pos=medals.get(i, f"{i}."),
            name=esc(mask_name(r.name)),
            count=r.friends,
            amount=fmt_money(r.earned),
        )
        for i, r in enumerate(rows, start=1)
    ]
    await call.answer()
    await edit_or_send(
        call, f"{title}\n\n" + ("\n".join(lines) or texts.REF_TOP_EMPTY), bonus_back_kb("ref")
    )


@router.callback_query(BonusCb.filter(F.action == "friends"))
async def cb_friends(
    call: CallbackQuery, callback_data: BonusCb, svc: Services, user: User, rt: RuntimeSettings
) -> None:
    page = max(callback_data.page, 0)
    rows, total = await svc.referral.friends(user, page, FRIENDS_PER_PAGE)
    lines = [
        texts.REF_FRIENDS_ROW.format(
            name=esc(mask_name(r.name)),
            date=fmt_dt(r.joined_at, rt.timezone)[:10],
            deposit="✅" if r.total_deposit > 0 else "—",
        )
        for r in rows
    ]
    body = "\n".join(lines) if lines else texts.REF_FRIENDS_EMPTY
    has_next = (page + 1) * FRIENDS_PER_PAGE < total
    await call.answer()
    await edit_or_send(
        call,
        texts.REF_FRIENDS_TITLE.format(total=total) + "\n\n" + body,
        bonus_back_kb("ref", page=page, has_next=has_next),
    )


@router.callback_query(BonusCb.filter(F.action == "refwd"))
async def cb_ref_withdraw(call: CallbackQuery, svc: Services, user: User) -> None:
    try:
        amount = await svc.referral.withdraw_bonus(user)
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    await call.answer(texts.REF_WITHDRAW_OK.format(amount=fmt_money(amount)), show_alert=True)
    await cb_referral(call, svc, user, await svc.settings.snapshot())
