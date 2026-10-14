from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts
from app.admin.common import NOT_MENU, HasPerm, btn, confirm_kb, kb, pager
from app.bot.keyboards.callbacks import AdmCb
from app.bot.states import AdminStates
from app.bot.utils import edit_or_send, esc
from app.core.enums import PromoType
from app.core.errors import DomainError
from app.core.money import fmt_money
from app.core.permissions import Perm, has_perm
from app.core.utils import fmt_dt
from app.models import Admin, PromoCode
from app.repositories.bonus import ReferralRepository
from app.services.audit import Actor, jsonable
from app.services.bonus import PROMO_FORM_HELP, VIP_FORM_HELP, parse_promo_form, parse_vip_form
from app.services.container import Services
from app.services.settings import DEFS_BY_KEY, RuntimeSettings, display_value

router = Router(name="admin_bonus")
PER_PAGE = 8


def _onoff(value: bool) -> str:
    return "🟢 Yoqilgan" if value else "🔴 O‘chirilgan"


def bonus_menu_kb(
    rt: RuntimeSettings | None = None, can_edit: bool = False
) -> InlineKeyboardMarkup:
    toggles = []
    if rt is not None and can_edit:
        toggles = [
            [
                btn(
                    f"🏆 VIP bo‘limi: {_onoff(rt.vip_section_enabled)}",
                    "bq",
                    "toggle",
                    arg="vip_section_enabled",
                )
            ],
            [
                btn(
                    f"🎁 VIP bonus: {_onoff(rt.vip_bonus_enabled)}",
                    "bq",
                    "toggle",
                    arg="vip_bonus_enabled",
                )
            ],
            [
                btn(
                    f"🤝 Referal: {_onoff(rt.referral_enabled)}",
                    "bq",
                    "toggle",
                    arg="referral_enabled",
                )
            ],
        ]
    return kb(
        *toggles,
        [btn("🎟 Promokodlar", "pr", "list")],
        [btn("🏆 VIP darajalar", "vp", "list")],
        [btn("🤝 Referal foizi", "s", "edit", arg="referral_percent")],
        [btn("📏 Bonus qoidalari va limitlari", "s", "list", arg="bonus")],
    )


@router.message(F.text == texts.ADM_BONUS, HasPerm(Perm.BONUS_VIEW))
async def show_bonus(message: Message, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    text, markup = await _bonus_view(svc, admin)
    await message.answer(text, reply_markup=markup)


QUICK_TOGGLES = ("vip_section_enabled", "vip_bonus_enabled", "referral_enabled")


@router.callback_query(
    AdmCb.filter((F.section == "bq") & (F.action == "toggle")), HasPerm(Perm.SETTINGS_EDIT)
)
async def cb_quick_toggle(
    call: CallbackQuery, callback_data: AdmCb, svc: Services, admin: Admin, actor: Actor
) -> None:
    key = callback_data.arg
    if key not in QUICK_TOGGLES:
        await call.answer(texts.ADMIN_NO_PERM, show_alert=True)
        return
    rt = await svc.settings.snapshot()
    new_value = not getattr(rt, key)
    await svc.settings.update(key, "true" if new_value else "false", actor)
    await svc.settings.invalidate()
    await call.answer(f"{DEFS_BY_KEY[key].label}: {_onoff(new_value)}")
    text, markup = await _bonus_view(svc, admin)
    await edit_or_send(call, text, markup)


async def _bonus_view(svc: Services, admin: Admin) -> tuple[str, InlineKeyboardMarkup]:
    rt = await svc.settings.snapshot()
    paid = await ReferralRepository(svc.session).total_paid()
    return (
        "🎁 <b>Bonus tizimi</b>\n\n"
        f"🤝 Referal: {display_value(DEFS_BY_KEY['referral_enabled'], rt.referral_enabled)}, "
        f"{rt.referral_percent}%\n"
        f"💰 Jami to‘langan referal bonus: {fmt_money(paid)}\n"
        f"🏆 VIP bo‘limi: {_onoff(rt.vip_section_enabled)}\n"
        f"🎁 VIP bonus: {_onoff(rt.vip_bonus_enabled)}\n"
        f"📏 Bir depozitga bonus limiti: "
        f"{fmt_money(rt.max_bonus_per_deposit) if rt.max_bonus_per_deposit else 'cheksiz'}",
        bonus_menu_kb(rt, has_perm(admin.role, Perm.SETTINGS_EDIT)),
    )


# --------------------------------------------------------------------------- promokodlar
def promo_text(p: PromoCode, tz: str) -> str:
    value = fmt_money(p.bonus_value) if p.bonus_type == PromoType.FIXED else f"{p.bonus_value}%"
    return (
        f"🎟 <b>{esc(p.code)}</b> — {'✅ faol' if p.is_active else '⏸ nofaol'}\n\n"
        f"Bonus: {value}" + (f" (maks. {fmt_money(p.max_bonus)})" if p.max_bonus else "") + "\n"
        f"Minimal depozit: {fmt_money(p.min_deposit)}\n"
        f"Foydalanilgan: {p.used_count} / {p.total_limit or '∞'}\n"
        f"Bir foydalanuvchiga: {p.per_user_limit}\n"
        f"Amal qilish: {fmt_dt(p.valid_from, tz) if p.valid_from else 'hozirdan'} — "
        f"{fmt_dt(p.valid_until, tz) if p.valid_until else 'muddatsiz'}"
    )


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action == "list")), HasPerm(Perm.BONUS_VIEW)
)
async def cb_promo_list(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    await state.clear()
    page = max(callback_data.page, 0)
    promos = await svc.promo.list_page(page, PER_PAGE + 1)
    b = InlineKeyboardBuilder()
    for p in promos[:PER_PAGE]:
        b.row(
            btn(
                f"{'✅' if p.is_active else '⏸'} {p.code} • {p.used_count}/"
                f"{p.total_limit or '∞'}",
                "pr",
                "view",
                id=p.id,
            )
        )
    pager(b, "pr", "list", page, len(promos) > PER_PAGE)
    if has_perm(admin.role, Perm.BONUS_MANAGE):
        b.row(btn("➕ Yangi promokod", "pr", "new"))
    await call.answer()
    await edit_or_send(call, "🎟 <b>Promokodlar</b>", b.as_markup())


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action == "view")), HasPerm(Perm.BONUS_VIEW)
)
async def cb_promo_view(
    call: CallbackQuery, callback_data: AdmCb, state: FSMContext, svc: Services, admin: Admin
) -> None:
    await state.clear()
    rt = await svc.settings.snapshot()
    promo = await svc.promo.get(callback_data.id)
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.BONUS_MANAGE):
        b.row(
            btn(
                "⏸ Deaktivatsiya" if promo.is_active else "▶️ Aktivlashtirish",
                "pr",
                "toggle",
                id=promo.id,
            ),
            btn("✏️ Tahrirlash", "pr", "edit", id=promo.id),
        )
        b.row(btn("🗑 O‘chirish", "pr", "del", id=promo.id))
    b.row(btn(texts.BTN_BACK, "pr", "list"))
    await call.answer()
    await edit_or_send(call, promo_text(promo, rt.timezone), b.as_markup())


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action.in_({"new", "edit"}))), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_promo_form(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.promo_form)
    await state.update_data(promo_id=callback_data.id if callback_data.action == "edit" else 0)
    await call.answer()
    await edit_or_send(
        call,
        "🎟 Promokod ma’lumotlarini yuboring.\n\n" + PROMO_FORM_HELP,
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(AdminStates.promo_form, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.BONUS_MANAGE))
async def on_promo_form(message: Message, state: FSMContext, svc: Services) -> None:
    rt = await svc.settings.snapshot()
    try:
        data = parse_promo_form(message.text or "", rt.timezone)
    except DomainError as exc:
        await message.answer(exc.message)
        return
    await state.update_data(promo_data=jsonable(data))
    await state.set_state(AdminStates.promo_confirm)
    preview = PromoCode(**data, used_count=0, is_active=True)
    await message.answer(
        "👁 <b>Preview</b>\n\n" + promo_text(preview, rt.timezone),
        reply_markup=confirm_kb("pr", "save"),
    )


def _restore_promo(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": raw["code"],
        "bonus_type": PromoType(raw["bonus_type"]),
        "bonus_value": Decimal(raw["bonus_value"]),
        "min_deposit": Decimal(raw["min_deposit"]),
        "total_limit": raw["total_limit"],
        "per_user_limit": raw["per_user_limit"],
        "valid_until": datetime.fromisoformat(raw["valid_until"]) if raw["valid_until"] else None,
        "max_bonus": Decimal(raw["max_bonus"]) if raw["max_bonus"] else None,
    }


@router.callback_query(
    AdminStates.promo_confirm,
    AdmCb.filter((F.section == "pr") & (F.action == "save")),
    HasPerm(Perm.BONUS_MANAGE),
)
async def cb_promo_save(
    call: CallbackQuery, state: FSMContext, svc: Services, actor: Actor
) -> None:
    data = await state.get_data()
    await state.clear()
    try:
        values = _restore_promo(data["promo_data"])
        if data.get("promo_id"):
            promo = await svc.promo.update(int(data["promo_id"]), values, actor)
        else:
            promo = await svc.promo.create(values, actor)
    except KeyError:
        await call.answer(texts.EXPIRED_ACTION, show_alert=True)
        return
    except DomainError as exc:
        await call.answer(exc.message, show_alert=True)
        return
    rt = await svc.settings.snapshot()
    await call.answer("✅ Saqlandi")
    await edit_or_send(
        call, promo_text(promo, rt.timezone), kb([btn(texts.BTN_BACK, "pr", "list")])
    )


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action == "toggle")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_promo_toggle(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    promo = await svc.promo.get(callback_data.id)
    await svc.promo.set_active(promo.id, not promo.is_active, actor)
    await cb_promo_view(call, callback_data, state, svc, admin)


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action == "del")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_promo_del(call: CallbackQuery, callback_data: AdmCb) -> None:
    await call.answer()
    await edit_or_send(
        call,
        "🗑 Promokod o‘chirilsinmi? (tarix saqlanib qoladi)",
        confirm_kb("pr", "del_do", id=callback_data.id),
    )


@router.callback_query(
    AdmCb.filter((F.section == "pr") & (F.action == "del_do")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_promo_del_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    await svc.promo.delete(callback_data.id, actor)
    await cb_promo_list(call, AdmCb(section="pr", action="list"), state, svc, admin)


# --------------------------------------------------------------------------- VIP
@router.callback_query(
    AdmCb.filter((F.section == "vp") & (F.action == "list")), HasPerm(Perm.BONUS_VIEW)
)
async def cb_vip_list(call: CallbackQuery, state: FSMContext, svc: Services, admin: Admin) -> None:
    await state.clear()
    levels = await svc.vip.all()
    lines = [
        f"{'✅' if lv.is_active else '⏸'} <b>{esc(lv.name)}</b> — {fmt_money(lv.min_total_deposit)}"
        f" dan, +{lv.bonus_percent}% (tartib {lv.sort_order})"
        for lv in levels
    ]
    b = InlineKeyboardBuilder()
    if has_perm(admin.role, Perm.BONUS_MANAGE):
        for lv in levels:
            b.row(
                btn(f"{'⏸' if lv.is_active else '▶️'} {lv.name}", "vp", "toggle", id=lv.id),
                btn("✏️", "vp", "edit", id=lv.id),
                btn("🗑", "vp", "del", id=lv.id),
            )
        b.row(btn("➕ Yangi daraja", "vp", "new"))
    await call.answer()
    await edit_or_send(
        call, "🏆 <b>VIP darajalar</b>\n\n" + ("\n".join(lines) or "—"), b.as_markup()
    )


@router.callback_query(
    AdmCb.filter((F.section == "vp") & (F.action.in_({"new", "edit"}))), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_vip_form(call: CallbackQuery, callback_data: AdmCb, state: FSMContext) -> None:
    await state.set_state(AdminStates.vip_form)
    await state.update_data(vip_id=callback_data.id if callback_data.action == "edit" else 0)
    await call.answer()
    await edit_or_send(
        call,
        "🏆 Daraja ma’lumotlarini yuboring.\n\n" + VIP_FORM_HELP,
        kb([btn("❌ Bekor", "dash", "cancel")]),
    )


@router.message(AdminStates.vip_form, F.text, ~F.text.in_(NOT_MENU), HasPerm(Perm.BONUS_MANAGE))
async def on_vip_form(message: Message, state: FSMContext, svc: Services, actor: Actor) -> None:
    try:
        values = parse_vip_form(message.text or "")
    except DomainError as exc:
        await message.answer(exc.message)
        return
    data = await state.get_data()
    await state.clear()
    if data.get("vip_id"):
        level = await svc.vip.update(int(data["vip_id"]), values, actor)
    else:
        level = await svc.vip.create(values, actor)
    await message.answer(
        f"✅ Saqlandi: <b>{esc(level.name)}</b>",
        reply_markup=kb([btn("🏆 VIP darajalar", "vp", "list")]),
    )


@router.callback_query(
    AdmCb.filter((F.section == "vp") & (F.action == "toggle")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_vip_toggle(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    await svc.vip.toggle(callback_data.id, actor)
    await cb_vip_list(call, state, svc, admin)


@router.callback_query(
    AdmCb.filter((F.section == "vp") & (F.action == "del")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_vip_del(call: CallbackQuery, callback_data: AdmCb) -> None:
    await call.answer()
    await edit_or_send(
        call, "🗑 VIP daraja o‘chirilsinmi?", confirm_kb("vp", "del_do", id=callback_data.id)
    )


@router.callback_query(
    AdmCb.filter((F.section == "vp") & (F.action == "del_do")), HasPerm(Perm.BONUS_MANAGE)
)
async def cb_vip_del_do(
    call: CallbackQuery,
    callback_data: AdmCb,
    state: FSMContext,
    svc: Services,
    admin: Admin,
    actor: Actor,
) -> None:
    await svc.vip.delete(callback_data.id, actor)
    await cb_vip_list(call, state, svc, admin)
