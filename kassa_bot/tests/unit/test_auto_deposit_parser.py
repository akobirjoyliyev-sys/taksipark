"""🤖 Avto to‘lov: ID ro‘yxatini o‘qish (parser) va progress ko‘rinishi."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.admin.auto_deposit import progress_bar
from app.core.errors import DomainError
from app.services.auto_deposit import (
    MAX_FILE_BYTES,
    ParsedIds,
    looks_like_low_balance,
    parse_file,
    parse_ids,
)


def test_one_id_per_line() -> None:
    parsed = parse_ids("123456789\n987654321\n\n555666777\n")
    assert list(parsed.entries) == ["123456789", "987654321", "555666777"]
    assert parsed.without_amount == 3
    assert not parsed.invalid


def test_many_ids_in_one_line_and_duplicates() -> None:
    parsed = parse_ids("111111111, 222222222 333333333;444444444\n111111111")
    assert list(parsed.entries) == ["111111111", "222222222", "333333333", "444444444"]
    assert parsed.duplicates == 1


@pytest.mark.parametrize(
    ("line", "amount"),
    [
        ("123456789 - 15000", "15000"),
        ("123456789 — 15 000", "15000"),
        ("123456789: 20000 so‘m", "20000"),
        ("123456789 | 25k", "25000"),
        ("123456789 = 50.000", "50000"),
        ("123456789\t7500", "7500"),
        ("123456789 => 12 ming", "12000"),
        ("ID 123456789 - 1000", "1000"),
    ],
)
def test_id_with_amount(line: str, amount: str) -> None:
    parsed = parse_ids(line)
    assert parsed.entries == {"123456789": Decimal(amount)}
    assert parsed.with_amount == 1


def test_numbering_and_comments_are_ignored() -> None:
    text = "1) 123456789\n2. 987654321 - 5000\nAli 555666777\n• 444555666"
    parsed = parse_ids(text)
    assert parsed.entries == {
        "123456789": None,
        "987654321": Decimal("5000"),
        "555666777": None,
        "444555666": None,
    }


def test_invalid_lines_are_reported() -> None:
    parsed = parse_ids("salom\n1234\n123456789\n12345678901234567890")
    assert list(parsed.entries) == ["123456789"]
    assert len(parsed.invalid) == 3


def test_merge_and_state_roundtrip() -> None:
    first = parse_ids("111111111\n222222222 - 3000")
    second = parse_ids("222222222\n333333333")
    first.merge(second)
    assert list(first.entries) == ["111111111", "222222222", "333333333"]
    assert first.entries["222222222"] == Decimal("3000")  # birinchi kelgan saqlanadi
    assert first.duplicates == 1
    restored = ParsedIds.from_state(first.to_state())
    assert restored.entries == first.entries
    assert restored.duplicates == 1
    assert ParsedIds.from_state(None).count == 0


def test_parse_file_csv_and_txt() -> None:
    csv_bytes = "﻿id,amount\n123456789,15000\n987654321,20000\n".encode()
    parsed = parse_file(csv_bytes)
    assert parsed.entries == {"123456789": Decimal("15000"), "987654321": Decimal("20000")}

    # Ikki ustun ham ID bo‘lsa — summa emas, ikkita ID.
    parsed = parse_file(b"111111111,222222222\n333333333\n")
    assert list(parsed.entries) == ["111111111", "222222222", "333333333"]
    assert parsed.with_amount == 0

    # Sarlavhasiz, lekin 1-ustun uzun ID, 2-ustun qisqa son — summa.
    parsed = parse_file(b"123456789;15000\n987654321;20 000\n")
    assert parsed.entries == {"123456789": Decimal("15000"), "987654321": Decimal("20000")}

    with pytest.raises(DomainError):
        parse_file(b"1" * (MAX_FILE_BYTES + 1))


def test_three_hundred_ids() -> None:
    ids = [str(100000000 + i) for i in range(300)]
    parsed = parse_ids("\n".join(ids))
    assert parsed.count == 300
    assert list(parsed.entries) == ids


def test_low_balance_detection() -> None:
    assert looks_like_low_balance("Депозит: Недостаточно средств на балансе кассы")
    assert looks_like_low_balance("Insufficient funds")
    assert not looks_like_low_balance("Akkaunt topilmadi")


def test_progress_bar() -> None:
    assert progress_bar(0, 10) == "▱" * 10
    assert progress_bar(50, 10) == "▰" * 5 + "▱" * 5
    assert progress_bar(100, 10) == "▰" * 10
    assert progress_bar(150, 10) == "▰" * 10
