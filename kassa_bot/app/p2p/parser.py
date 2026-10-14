"""Bank bildirishnomalarini (CardXabar, HUMO) tahlil qilish: faqat kirim summasi kerak.

Namuna (CardXabar)::

    🟢 Пополнение
    ➕ 50 437.00 UZS
    💳 UZCARD *4321
    📍 PAYNET P2P>TASHKENT
    🕓 14:05 08.10.2026
    💰 1 250 437.00 UZS          ← balans, summa emas

Formatlar vaqt o‘tib o‘zgarishi mumkin, shuning uchun qoidalar ataylab tolerant:
avval ``➕`` qatori, keyin «summa» qatori, keyin valyutali birinchi (balans bo‘lmagan) qator.
Chiqim (``➖``, «списание», «oplata» …) xabarlari ``None`` qaytaradi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.money import q

_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'", "´": "'"})
_SPACES = re.compile(r"[   ]")

CREDIT_WORDS = (
    "пополнение",
    "popolnenie",
    "зачисление",
    "zachislenie",
    "поступление",
    "postuplenie",
    "перевод на карту",
    "perevod na kartu",
    "входящий перевод",
    "to'ldirish",
    "toldirish",
    "kirim",
    "kelib tushdi",
    "qabul qilindi",
    "hisobga tushdi",
    "credit",
    "received",
)
DEBIT_WORDS = (
    "списание",
    "spisanie",
    "оплата",
    "oplata",
    "покупка",
    "pokupka",
    "снятие",
    "snyatie",
    "перевод с карты",
    "perevod s karty",
    "chiqim",
    "yechib olindi",
    "to'lov",
    "xarid",
    "debit",
)
BALANCE_WORDS = ("баланс", "balans", "остаток", "ostatok", "qoldiq", "balance", "💰", "💵")
AMOUNT_LABELS = ("сумма", "summa", "miqdor", "amount")
CURRENCY = r"\b(?:uzs|сум|so'm|som|sum|soum)\b"

# Raqam: 1 234 567.89 | 1,234,567.89 | 1.234.567,89 | 50000 | 50 000,00
_NUMBER = re.compile(r"(?<![\d*•xX])(\d[\d .,]*\d|\d)(?![\d])")
_CARD_LAST4 = re.compile(r"(?:\*+|•+|[xX]{2,})\s?(\d{4})\b")
_PLUS_LINE = re.compile(r"^\s*(?:➕|\+)")
_MINUS_LINE = re.compile(r"^\s*(?:➖|-|−)\s*\d")


@dataclass(frozen=True, slots=True)
class ParsedTx:
    amount: Decimal
    card_last4: str | None


def _normalize(text: str) -> str:
    return _SPACES.sub(" ", text.translate(_APOSTROPHES))


def parse_number(token: str) -> Decimal | None:
    """Mahalliy formatdagi summani Decimal'ga aylantiradi. Sana/vaqt kabi qiymatlar — None."""
    s = token.replace(" ", "")
    if not s or not s[0].isdigit():
        return None
    decimal_part = ""
    if "," in s and "." in s:
        dec_sep = "," if s.rfind(",") > s.rfind(".") else "."
        int_part, decimal_part = s.rsplit(dec_sep, 1)
        groups = re.split(r"[.,]", int_part)
    else:
        sep = "," if "," in s else "." if "." in s else ""
        groups = s.split(sep) if sep else [s]
        if sep and len(groups[-1]) in (1, 2):  # 500.00 / 50,5 — kasr qismi
            decimal_part = groups.pop()
    if decimal_part and (len(decimal_part) > 2 or not decimal_part.isdigit()):
        return None
    if len(groups) > 1 and (len(groups[0]) > 3 or any(len(g) != 3 for g in groups[1:])):
        return None  # 08.10.2026 kabi sanalar
    try:
        value = Decimal("".join(groups) + (f".{decimal_part}" if decimal_part else ""))
    except InvalidOperation:
        return None
    return q(value) if value > 0 else None


def _first_amount(line: str, *, after: int = 0) -> Decimal | None:
    for match in _NUMBER.finditer(line, after):
        value = parse_number(match.group(1))
        if value is not None:
            return value
    return None


def _has_currency(line: str) -> bool:
    return re.search(CURRENCY, line, re.IGNORECASE) is not None


def parse_bank_message(text: str | None) -> ParsedTx | None:
    """Kirim xabaridan summa va karta oxirgi 4 raqamini ajratadi. Kirim bo‘lmasa — None."""
    if not text:
        return None
    norm = _normalize(text)
    lower = norm.lower()
    lines = [ln.strip() for ln in norm.splitlines() if ln.strip()]

    has_plus = "➕" in norm or any(_PLUS_LINE.match(ln) for ln in lines)
    has_minus = "➖" in norm or any(_MINUS_LINE.match(ln) for ln in lines)
    credit_word = any(w in lower for w in CREDIT_WORDS)
    debit_word = any(w in lower for w in DEBIT_WORDS)
    if has_minus and not has_plus:
        return None
    if not has_plus and (debit_word or not credit_word):
        return None

    amount: Decimal | None = None
    # 1) ➕ qatori: summa belgidan keyin keladi
    for ln in lines:
        if _PLUS_LINE.match(ln) or "➕" in ln:
            pos = ln.find("➕") + 1 if "➕" in ln else ln.find("+") + 1
            amount = _first_amount(ln, after=pos)
            if amount is not None:
                break
    # 2) «Summa: …» qatori
    if amount is None:
        for ln in lines:
            low = ln.lower()
            if any(lbl in low for lbl in AMOUNT_LABELS) and not any(
                w in low for w in BALANCE_WORDS
            ):
                amount = _first_amount(ln, after=ln.find(":") + 1 if ":" in ln else 0)
                if amount is not None:
                    break
    # 3) valyutasi bor birinchi balans bo‘lmagan qator
    if amount is None:
        for ln in lines:
            low = ln.lower()
            if _has_currency(ln) and not any(w in low for w in BALANCE_WORDS):
                amount = _first_amount(ln)
                if amount is not None:
                    break
    if amount is None:
        return None

    card = _CARD_LAST4.search(norm)
    return ParsedTx(amount=amount, card_last4=card.group(1) if card else None)
