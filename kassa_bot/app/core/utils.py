from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")


def utcnow() -> datetime:
    return datetime.now(UTC)


def get_tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def fmt_dt(value: datetime | None, tz_name: str = "Asia/Tashkent") -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(get_tz(tz_name)).strftime("%d.%m.%Y %H:%M")


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def hmac_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def mask_phone(phone: str | None) -> str:
    if not phone:
        return "—"
    digits = re.sub(r"\D", "", phone)
    if len(digits) < 7:
        return "***"
    return f"+{digits[:5]}***{digits[-4:]}"


def mask_name(name: str | None) -> str:
    if not name:
        return "Foydalanuvchi"
    name = name.strip()
    if len(name) <= 2:
        return name[0] + "*"
    return name[:2] + "***"


def normalize_link(value: str) -> str:
    """`@username`, `t.me/x` yoki `https://...` ni to‘liq URLga aylantiradi."""
    value = value.strip()
    if not value:
        return ""
    m = _USERNAME_RE.match(value)
    if m and value.startswith("@"):
        return f"https://t.me/{m.group(1)}"
    if value.startswith(("t.me/", "telegram.me/")):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Havola `@username` yoki `https://...` ko‘rinishida bo‘lishi kerak.")
    return value


def is_public_url(url: str) -> bool:
    """Telegram URL-tugma sifatida qabul qiladigan ommaviy havolami."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname
    if host in {"localhost", "0.0.0.0"} or host.endswith(  # noqa: S104
        (".local", ".localhost", ".test")
    ):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "." in host
    return not (ip.is_private or ip.is_loopback or ip.is_link_local)
