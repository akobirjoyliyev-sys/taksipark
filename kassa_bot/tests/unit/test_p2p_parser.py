"""Bank bildirishnomalari parseri: CardXabar/HUMO kirim xabarlari, chiqimlar rad etiladi."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.p2p.parser import parse_bank_message, parse_number

CARDXABAR_RU = """🟢 Пополнение
➕ 50 437.00 UZS
💳 UZCARD *4321
📍 PAYNET P2P>TASHKENT
🕓 14:05 08.10.2026
💰 1 250 437.00 UZS"""

CARDXABAR_UZ = """🎉 To‘ldirish
➕ 125 017,00 UZS
💳 ***4321
📍 UZCARD P2P
🕓 08.10.26 14:05
💵 3 120 000,00 UZS"""

HUMO_RU = """💸 Пополнение
➕ 75 250,00 UZS
📍 HUMO2HUMO>P2P
💳 HUMOCARD *9876
🕓 14:05 08.10.2026
💰 300 000,00 UZS"""

HUMO_LATIN = """Popolnenie
Karta: HUMO *9876
Summa: 100 333.00 UZS
Balans: 1 000 000.00 UZS"""

DEBIT = """🔴 Оплата
➖ 20 000.00 UZS
💳 UZCARD *4321
📍 KORZINKA
💰 1 230 437.00 UZS"""

DEBIT_WORD_ONLY = """Списание
Сумма: 15 000,00 UZS
Карта: *4321
Баланс: 1 000 000,00 UZS"""


@pytest.mark.parametrize(
    ("text", "amount", "last4"),
    [
        (CARDXABAR_RU, Decimal("50437.00"), "4321"),
        (CARDXABAR_UZ, Decimal("125017.00"), "4321"),
        (HUMO_RU, Decimal("75250.00"), "9876"),
        (HUMO_LATIN, Decimal("100333.00"), "9876"),
    ],
)
def test_credit_messages(text: str, amount: Decimal, last4: str) -> None:
    parsed = parse_bank_message(text)
    assert parsed is not None
    assert parsed.amount == amount
    assert parsed.card_last4 == last4


@pytest.mark.parametrize("text", [DEBIT, DEBIT_WORD_ONLY, "", "Salom!", "Kod: 12345"])
def test_non_credit_messages_ignored(text: str) -> None:
    assert parse_bank_message(text) is None


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("50 437.00", Decimal("50437.00")),
        ("50 437,00", Decimal("50437.00")),
        ("1,234,567.89", Decimal("1234567.89")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("50000", Decimal("50000.00")),
        ("50.000", Decimal("50000.00")),
        ("500.5", Decimal("500.50")),
        ("08.10.2026", None),
        ("0", None),
    ],
)
def test_parse_number(token: str, expected: Decimal | None) -> None:
    assert parse_number(token) == expected
