"""Telegram Web App initData imzosini tekshirish."""

from __future__ import annotations

import json
import time

import pytest

from app.webapp.auth import InitDataError, sign_init_data, validate_init_data

TOKEN = "123456:TEST_TOKEN"


def fields(**extra: str) -> dict[str, str]:
    return {
        "auth_date": str(int(time.time())),
        "query_id": "AAH",
        "user": json.dumps({"id": 42, "first_name": "Ali", "username": "ali"}),
        **extra,
    }


def test_valid_init_data() -> None:
    user = validate_init_data(sign_init_data(fields(), TOKEN), TOKEN)
    assert user.id == 42 and user.first_name == "Ali" and user.username == "ali"


def test_tampered_or_foreign_token_rejected() -> None:
    signed = sign_init_data(fields(), TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(signed.replace("Ali", "Vali"), TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(signed, "999:OTHER")
    with pytest.raises(InitDataError):
        validate_init_data("", TOKEN)


def test_expired_init_data_rejected() -> None:
    old = sign_init_data(fields(auth_date=str(int(time.time()) - 2 * 86400)), TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(old, TOKEN)
