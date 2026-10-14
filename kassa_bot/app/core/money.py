from __future__ import annotations

import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal("0")
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1000000000000")  # 1 trln — himoya chegarasi

_THOUSANDS_COMMA = re.compile(r"^\d{1,3}(,\d{3})+(\.\d{1,2})?$")
_PLAIN = re.compile(r"^\d{1,13}([.,]\d{1,2})?$")
_SUFFIXES = ("so‘m", "so'm", "som", "sum", "uzs")


def q(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_amount(text: str | None) -> Decimal | None:
    """Foydalanuvchi kiritgan summani xavfsiz o‘qiydi. Noto‘g‘ri bo‘lsa None."""
    if not text:
        return None
    cleaned = text.strip().lower()
    for suffix in _SUFFIXES:
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    cleaned = cleaned.replace(" ", "").replace(" ", "").replace("_", "").replace("'", "")
    if _THOUSANDS_COMMA.match(cleaned):
        cleaned = cleaned.replace(",", "")
    if not _PLAIN.match(cleaned):
        return None
    try:
        value = Decimal(cleaned.replace(",", "."))
    except InvalidOperation:
        return None
    if value <= ZERO or value > MAX_AMOUNT:
        return None
    return q(value)


def percent_of(amount: Decimal, percent: Decimal, *, round_down: bool = False) -> Decimal:
    raw = amount * percent / Decimal(100)
    return raw.quantize(CENT, rounding=ROUND_DOWN if round_down else ROUND_HALF_UP)


def fmt_money(value: Decimal | int | None, currency: str = "so‘m") -> str:
    v = q(Decimal(value or 0))
    if v == v.to_integral_value():
        body = f"{int(v):,}".replace(",", " ")
    else:
        body = f"{v:,.2f}".replace(",", " ")
    return f"{body} {currency}"
