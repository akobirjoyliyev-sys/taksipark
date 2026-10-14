from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class DepositStates(StatesGroup):
    amount = State()


class WithdrawStates(StatesGroup):
    card = State()
    amount = State()
    confirm = State()


class PromoStates(StatesGroup):
    code = State()


class McDepositStates(StatesGroup):
    payer_id = State()
    amount = State()


class McTopupStates(StatesGroup):
    amount = State()


class McWithdrawStates(StatesGroup):
    payer_id = State()
    code = State()
    destination = State()
    card = State()
    confirm = State()


class McWalletGameStates(StatesGroup):
    """Hamyon balansidan o‘yin hisobiga o‘tkazish (Mob-Cash deposit, kartasiz)."""

    payer_id = State()
    amount = State()
    confirm = State()


class AdminStates(StatesGroup):
    user_search = State()
    balance_amount = State()
    balance_reason = State()
    balance_confirm = State()
    ban_reason = State()
    message_text = State()
    message_confirm = State()
    admin_add = State()
    setting_value = State()
    setting_confirm = State()
    stats_range = State()
    mass_upload = State()
    wd_comment = State()
    promo_form = State()
    promo_confirm = State()
    vip_form = State()
    channel_form = State()
    p2p_card_form = State()
    p2p_reject_comment = State()
    mobcash_connect = State()
    bm_name = State()
    bm_creds = State()
    bm_rename = State()
    btx_link = State()
    mcw_refund_comment = State()
    userbot_phone = State()
    userbot_code = State()
    userbot_password = State()
