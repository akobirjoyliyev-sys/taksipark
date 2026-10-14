"""Telegram Web App `initData` imzosini tekshirish.

https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
secret = HMAC_SHA256(key="WebAppData", msg=bot_token); hash = HMAC_SHA256(secret, check_string)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl

MAX_AGE_SECONDS = 24 * 3600


class InitDataError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebAppUser:
    id: int
    first_name: str
    last_name: str | None
    username: str | None


def validate_init_data(
    init_data: str, bot_token: str, *, max_age: int = MAX_AGE_SECONDS, now: float | None = None
) -> WebAppUser:
    if not init_data or not bot_token:
        raise InitDataError("initData yo‘q")
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError("initData formati noto‘g‘ri") from exc
    received = pairs.pop("hash", "")
    if not received:
        raise InitDataError("hash yo‘q")
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("imzo noto‘g‘ri")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise InitDataError("auth_date noto‘g‘ri") from exc
    if (now if now is not None else time.time()) - auth_date > max_age:
        raise InitDataError("initData eskirgan — ilovani qayta oching")
    try:
        raw: dict[str, Any] = json.loads(pairs.get("user", ""))
        return WebAppUser(
            id=int(raw["id"]),
            first_name=str(raw.get("first_name") or ""),
            last_name=raw.get("last_name"),
            username=raw.get("username"),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise InitDataError("user maydoni noto‘g‘ri") from exc


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Testlar uchun: Telegram kabi imzolangan initData satrini yasaydi."""
    from urllib.parse import urlencode

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})
