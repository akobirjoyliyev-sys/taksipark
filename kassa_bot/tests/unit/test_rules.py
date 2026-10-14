"""Biznes qoidalari: promo, VIP, ruxsatlar, sozlamalar, CSV, statistika oraliqlari."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.enums import AdminRole, MassItemStatus, PromoType
from app.core.errors import DomainError
from app.core.permissions import ROLE_PERMISSIONS, Perm, has_perm
from app.core.utils import utcnow
from app.models import PromoCode, VipLevel
from app.services.bonus import (
    check_promo_validity,
    compute_promo_bonus,
    parse_promo_form,
    parse_vip_form,
    promo_still_usable,
    vip_level_for,
    vip_progress,
)
from app.services.channels import parse_channel_form
from app.services.mass_payout import fingerprint, parse_csv
from app.services.settings import DEFS_BY_KEY, parse_value
from app.services.stats import parse_range, period_bounds


def promo(**kw: object) -> PromoCode:
    base: dict[str, object] = {
        "code": "X",
        "is_active": True,
        "is_deleted": False,
        "bonus_type": PromoType.FIXED,
        "bonus_value": Decimal("5000"),
        "max_bonus": None,
        "min_deposit": Decimal(0),
        "total_limit": None,
        "per_user_limit": 1,
        "used_count": 0,
        "valid_from": None,
        "valid_until": None,
    }
    base.update(kw)
    return PromoCode(**base)


# ---------------------------------------------------------------- promo
def test_promo_bonus_fixed_and_percent() -> None:
    assert compute_promo_bonus(promo(), Decimal("100000")) == Decimal("5000")
    p = promo(bonus_type=PromoType.PERCENT, bonus_value=Decimal("10"), max_bonus=Decimal("7000"))
    assert compute_promo_bonus(p, Decimal("50000")) == Decimal("5000")
    assert compute_promo_bonus(p, Decimal("100000")) == Decimal("7000")


def test_promo_validity() -> None:
    now = utcnow()
    check_promo_validity(promo(), now)
    with pytest.raises(DomainError):
        check_promo_validity(None, now)
    with pytest.raises(DomainError):
        check_promo_validity(promo(is_active=False), now)
    with pytest.raises(DomainError):
        check_promo_validity(promo(valid_until=now - timedelta(days=1)), now)
    with pytest.raises(DomainError):
        check_promo_validity(promo(valid_from=now + timedelta(days=1)), now)
    with pytest.raises(DomainError):
        check_promo_validity(promo(total_limit=3, used_count=3), now)
    # Band qilingan limit depozitda qayta tekshirilmaydi
    assert promo_still_usable(promo(total_limit=1, used_count=1), now)


def test_parse_promo_form() -> None:
    data = parse_promo_form("welcome | fixed | 10000 | 0 | 500 | 1 | 2026-12-31 | -", "UTC")
    assert data["code"] == "WELCOME"
    assert data["bonus_type"] == PromoType.FIXED
    assert data["total_limit"] == 500
    assert data["valid_until"].year == 2026
    assert data["max_bonus"] is None
    with pytest.raises(DomainError):
        parse_promo_form("X | fixed | 1", "UTC")
    with pytest.raises(DomainError):
        parse_promo_form("ABC | percent | 150 | 0 | - | 1 | -", "UTC")
    with pytest.raises(DomainError):
        parse_promo_form("A B | fixed | 1 | 0 | - | 1 | -", "UTC")


# ---------------------------------------------------------------- VIP
def levels() -> list[VipLevel]:
    return [
        VipLevel(id=1, name="Bronze", min_total_deposit=Decimal(0), bonus_percent=Decimal(0)),
        VipLevel(
            id=2, name="Silver", min_total_deposit=Decimal(1_000_000), bonus_percent=Decimal("0.5")
        ),
        VipLevel(id=3, name="Gold", min_total_deposit=Decimal(5_000_000), bonus_percent=Decimal(1)),
    ]


def test_vip_levels_and_progress() -> None:
    assert vip_level_for(levels(), Decimal(0)).name == "Bronze"  # type: ignore[union-attr]
    assert vip_level_for(levels(), Decimal(1_000_000)).name == "Silver"  # type: ignore[union-attr]
    p = vip_progress(levels(), Decimal(3_000_000))
    assert p.current is not None and p.current.name == "Silver"
    assert p.next is not None and p.next.name == "Gold"
    assert p.percent == 50
    assert p.left == Decimal(2_000_000)
    top = vip_progress(levels(), Decimal(9_000_000))
    assert top.next is None and top.percent == 100


def test_parse_vip_form() -> None:
    assert parse_vip_form("Gold | 5000000 | 1.5 | 3")["bonus_percent"] == Decimal("1.50")
    with pytest.raises(DomainError):
        parse_vip_form("Gold | x | 1 | 3")


# ---------------------------------------------------------------- ruxsatlar
def test_role_permissions() -> None:
    assert ROLE_PERMISSIONS[AdminRole.SUPERADMIN] == frozenset(Perm)
    assert has_perm(AdminRole.ADMIN, Perm.USERS_BALANCE)
    assert not has_perm(AdminRole.ADMIN, Perm.SETTINGS_CRITICAL)
    assert not has_perm(AdminRole.ADMIN, Perm.MASS_APPROVE)
    assert has_perm(AdminRole.OPERATOR, Perm.WITHDRAW_PROCESS)
    assert has_perm(AdminRole.OPERATOR, Perm.MASS_APPROVE)
    assert not has_perm(AdminRole.OPERATOR, Perm.USERS_BALANCE)
    assert has_perm(AdminRole.AUDITOR, Perm.AUDIT_VIEW)
    for perm in (Perm.USERS_BAN, Perm.SETTINGS_EDIT, Perm.WITHDRAW_PROCESS, Perm.MASS_CREATE):
        assert not has_perm(AdminRole.AUDITOR, perm), perm
    assert not has_perm("unknown", Perm.DASHBOARD)


# ---------------------------------------------------------------- sozlamalar
def test_setting_parsing() -> None:
    assert parse_value(DEFS_BY_KEY["deposit_min"], "15 000") == Decimal("15000.00")
    assert parse_value(DEFS_BY_KEY["maintenance"], "ha") is True
    assert parse_value(DEFS_BY_KEY["maintenance"], "yo‘q") is False
    assert parse_value(DEFS_BY_KEY["support_url"], "@help") == "https://t.me/help"
    assert parse_value(DEFS_BY_KEY["support_url"], "-") == ""
    assert parse_value(DEFS_BY_KEY["timezone"], "Asia/Tashkent") == "Asia/Tashkent"
    assert parse_value(DEFS_BY_KEY["enabled_providers"], "sandbox", ["sandbox"]) == ["sandbox"]
    assert parse_value(DEFS_BY_KEY["enabled_providers"], "-", ["sandbox"]) == []
    for key, bad in (
        ("withdraw_fee_percent", "150"),
        ("deposit_min", "-1"),
        ("payment_expiry_minutes", "1"),
        ("timezone", "Mars/Base"),
        ("payment_mode", "live"),
        ("enabled_providers", "payme"),
    ):
        with pytest.raises(ValueError):
            parse_value(DEFS_BY_KEY[key], bad, ["sandbox"])


async def test_settings_cross_validation(config, redis, registry) -> None:  # type: ignore[no-untyped-def]
    from cryptography.fernet import Fernet

    from app.services.settings import SettingsService

    await redis.set(SettingsService.CACHE_KEY, "{}")
    service = SettingsService(SimpleNamespace(), redis, config, registry)  # type: ignore[arg-type]
    _old, _new, serialized = await service.prepare_change("deposit_min", "20000")
    assert serialized == "20000.00"
    with pytest.raises(ValueError, match="minimumi"):
        await service.prepare_change("deposit_min", "999999999")
    with pytest.raises(ValueError, match="Production"):
        await service.prepare_change("payment_mode", "production")
    with pytest.raises(ValueError, match="Fernet"):
        await service.prepare_change("userbot_session_key", "2008")
    _old, _new, serialized = await service.prepare_change(
        "userbot_session_key", Fernet.generate_key().decode()
    )
    assert len(serialized) == 44
    await redis.set(
        SettingsService.CACHE_KEY, '{"enabled_providers": "", "mobcash_enabled": "true"}'
    )
    real = SettingsService(SimpleNamespace(), redis, config, registry)  # type: ignore[arg-type]
    _old, _new, serialized = await real.prepare_change("payment_mode", "production")
    assert serialized == "production"


# ---------------------------------------------------------------- CSV / kanal / sana
def test_parse_mass_csv() -> None:
    rows = parse_csv(b"telegram_id,amount,provider\n111,50000,sandbox\nabc,10,sandbox\n222,-5,\n")
    assert rows[0].error is None and rows[0].amount == Decimal("50000.00")
    assert rows[1].error == "telegram_id noto‘g‘ri"
    assert rows[2].error is not None
    with pytest.raises(DomainError):
        parse_csv(b"id,sum\n1,2\n")
    with pytest.raises(DomainError):
        parse_csv(b"telegram_id,amount,provider\n")
    with pytest.raises(DomainError):
        parse_csv(b"x" * (600 * 1024))
    assert fingerprint(1, Decimal("5.00"), "sandbox") == fingerprint(1, Decimal("5.00"), "sandbox")
    assert MassItemStatus.DUPLICATE.value == "duplicate"


def test_parse_channel_form() -> None:
    assert parse_channel_form("@kassa_news | Kassa yangiliklari") == (
        "kassa_news",
        "Kassa yangiliklari",
    )
    with pytest.raises(DomainError):
        parse_channel_form("kassa_news Kassa")


def test_stats_ranges() -> None:
    start, end = parse_range("2026-10-01 2026-10-06", "Asia/Tashkent")
    assert (end - start) == timedelta(days=6)
    assert start.hour == 19  # Toshkent (UTC+5) yarim tuni UTCda
    with pytest.raises(DomainError):
        parse_range("2026-10-06 2026-10-01", "UTC")
    s, e = period_bounds("week", "UTC")
    assert e > s and (e - s) <= timedelta(days=7)
