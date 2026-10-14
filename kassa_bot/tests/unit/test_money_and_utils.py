from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.logging import redact
from app.core.money import fmt_money, parse_amount, percent_of
from app.core.utils import is_public_url, mask_name, mask_phone, normalize_link
from app.services.withdrawals import backoff_seconds, quote


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("50000", Decimal("50000.00")),
        ("50 000", Decimal("50000.00")),
        ("50,000", Decimal("50000.00")),
        ("1 250 000 so‘m", Decimal("1250000.00")),
        ("100.5", Decimal("100.50")),
        ("100,25", Decimal("100.25")),
        ("12000 uzs", Decimal("12000.00")),
    ],
)
def test_parse_amount_valid(raw: str, expected: Decimal) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "abc", "-100", "0", "1e5", "100.123", "99999999999999999", "1; DROP TABLE"]
)
def test_parse_amount_invalid(raw: str) -> None:
    assert parse_amount(raw) is None


def test_fmt_money() -> None:
    assert fmt_money(Decimal("1250000")) == "1 250 000 so‘m"
    assert fmt_money(Decimal("10.5")) == "10.50 so‘m"
    assert fmt_money(None) == "0 so‘m"


def test_percent_of_rounding() -> None:
    assert percent_of(Decimal("333"), Decimal("1")) == Decimal("3.33")
    assert percent_of(Decimal("100.55"), Decimal("1"), round_down=True) == Decimal("1.00")
    assert percent_of(Decimal("100.55"), Decimal("1")) == Decimal("1.01")


def test_quote_and_backoff() -> None:
    fee, net = quote(Decimal("100000"), Decimal("1.5"))
    assert fee == Decimal("1500.00")
    assert net == Decimal("98500.00")
    assert [backoff_seconds(i) for i in (1, 2, 3)] == [30, 60, 120]
    assert backoff_seconds(50) == 1800


def test_redaction_hides_secrets() -> None:
    text = (
        "card 8600 1234 5678 9012 token=abc123 "
        "bot 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw password: hunter2"
    )
    out = redact(text)
    assert "8600 1234 5678 9012" not in out
    assert "****9012" in out
    assert "abc123" not in out
    assert "AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw" not in out
    assert "hunter2" not in out
    # Telegram ID (9-10 raqam) karta deb hisoblanmaydi
    assert redact("user 1234567890") == "user 1234567890"


def test_links_and_masks() -> None:
    assert normalize_link("@kassa_support") == "https://t.me/kassa_support"
    assert normalize_link("t.me/kassa") == "https://t.me/kassa"
    assert normalize_link("https://example.com/a") == "https://example.com/a"
    with pytest.raises(ValueError, match="Havola"):
        normalize_link("javascript:alert(1)")
    assert is_public_url("https://example.com")
    assert not is_public_url("http://localhost:8000/x")
    assert not is_public_url("http://127.0.0.1:8000/x")
    assert not is_public_url("http://192.168.1.10/x")
    assert mask_phone("+998901234567") == "+99890***4567"
    assert mask_name("Akmal") == "Ak***"
