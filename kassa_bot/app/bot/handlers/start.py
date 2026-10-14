from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatJoinRequest, Message

from app import texts
from app.bot.keyboards.callbacks import SubCb
from app.bot.keyboards.user import contact_kb, main_menu_kb, subscription_kb, webapp_kb
from app.bot.utils import esc, safe_delete
from app.models import Admin, User
from app.services.container import Services
from app.services.settings import RuntimeSettings
from app.webapp.telegram import webapp_url

router = Router(name="start")


async def _continue_onboarding(
    message: Message, user: User, svc: Services, rt: RuntimeSettings, admin: Admin | None
) -> None:
    """Obuna → kontakt → asosiy menyu."""
    if admin is None and rt.subscription_enabled:
        missing = await svc.subscription.missing_channels(user.telegram_id, use_cache=False)
        if missing:
            await message.answer(texts.SUB_REQUIRED, reply_markup=subscription_kb(missing))
            return
    if not user.onboarding_done or (rt.contact_required and not user.contact_verified):
        prompt = (
            texts.CONTACT_PROMPT_REQUIRED if rt.contact_required else texts.CONTACT_PROMPT_OPTIONAL
        )
        await message.answer(prompt, reply_markup=contact_kb(rt.contact_required))
        return
    await message.answer(texts.WELCOME, reply_markup=main_menu_kb())
    url = webapp_url(svc.config) if rt.webapp_enabled else None
    if url:
        await message.answer(texts.WEBAPP_PROMO, reply_markup=webapp_kb(url))


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    svc: Services,
    user: User,
    is_new_user: bool,
    rt: RuntimeSettings,
    admin: Admin | None,
) -> None:
    await state.clear()
    if is_new_user and command.args:
        referrer = await svc.users.attach_referrer(user, command.args.strip()[:64])
        if referrer is not None:
            await svc.notifier.send(
                referrer.telegram_id, texts.REFERRAL_JOINED.format(name=esc(user.first_name))
            )
    await _continue_onboarding(message, user, svc, rt, admin)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.MAIN_MENU, reply_markup=main_menu_kb())


@router.message(F.contact)
async def on_contact(
    message: Message, svc: Services, user: User, rt: RuntimeSettings, admin: Admin | None
) -> None:
    contact = message.contact
    if contact is None or contact.user_id != message.from_user.id:  # type: ignore[union-attr]
        await message.answer(texts.CONTACT_FOREIGN, reply_markup=contact_kb(rt.contact_required))
        return
    await svc.users.save_contact(user, contact.phone_number)
    await message.answer(texts.CONTACT_SAVED)
    await _continue_onboarding(message, user, svc, rt, admin)


@router.message(F.text == texts.BTN_SKIP_CONTACT)
async def on_skip_contact(
    message: Message, svc: Services, user: User, rt: RuntimeSettings, admin: Admin | None
) -> None:
    if rt.contact_required:
        await message.answer(texts.CONTACT_PROMPT_REQUIRED, reply_markup=contact_kb(True))
        return
    await svc.users.finish_onboarding(user)
    await _continue_onboarding(message, user, svc, rt, admin)


@router.callback_query(SubCb.filter(F.action == "check"))
async def on_sub_check(
    call: CallbackQuery, svc: Services, user: User, rt: RuntimeSettings, admin: Admin | None
) -> None:
    missing = await svc.subscription.missing_channels(user.telegram_id, use_cache=False)
    if missing:
        await call.answer(texts.SUB_STILL_MISSING, show_alert=True)
        return
    await call.answer(texts.SUB_OK)
    if isinstance(call.message, Message):
        await safe_delete(call.message)
        await _continue_onboarding(call.message, user, svc, rt, admin)


@router.chat_join_request()
async def on_join_request(event: ChatJoinRequest, svc: Services) -> None:
    await svc.join_requests.store(event)
