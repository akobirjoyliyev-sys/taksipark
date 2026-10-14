from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="m"):
    action: str


class AmountCb(CallbackData, prefix="amt"):
    value: int


class PaymentCb(CallbackData, prefix="pay"):
    action: str
    id: int


class CardCb(CallbackData, prefix="card"):
    action: str
    id: int = 0


class WdCb(CallbackData, prefix="wd"):
    action: str
    id: int = 0


class HistoryCb(CallbackData, prefix="h"):
    kind: str
    status: str
    page: int = 0


class BonusCb(CallbackData, prefix="b"):
    action: str
    page: int = 0


class SubCb(CallbackData, prefix="sub"):
    action: str


class McCb(CallbackData, prefix="mc"):
    """Mob-Cash foydalanuvchi oqimlari: to‘ldirish (dep_*), yechish (wd_*), tarix."""

    action: str
    id: int = 0
    value: int = 0


class AdmCb(CallbackData, prefix="a"):
    """Admin panel uchun umumiy callback: bo‘lim / amal / obyekt id / sahifa / qo‘shimcha."""

    section: str
    action: str
    id: int = 0
    page: int = 0
    arg: str = ""
