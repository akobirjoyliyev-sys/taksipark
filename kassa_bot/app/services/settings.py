"""Runtime sozlamalari: standart qiymat ENV'dan, o‘zgartirish admin paneldan (DB + Redis kesh)."""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, fields
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from cryptography.fernet import Fernet
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.core.money import fmt_money, q
from app.core.utils import get_tz, normalize_link
from app.models import SystemSetting
from app.payments.registry import ProviderRegistry
from app.repositories.admins import SettingRepository
from app.services.audit import Actor, AuditService
from app.userbot.crypto import is_valid_fernet_key

log = logging.getLogger(__name__)

Kind = Literal[
    "money",
    "percent",
    "int",
    "bool",
    "link",
    "tz",
    "mode",
    "providers",
    "usernames",
    "text",
    "secret",
]

_TG_USERNAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


@dataclass(frozen=True, slots=True)
class SettingDef:
    key: str
    label: str
    kind: Kind
    default: Callable[[Config], Any]
    critical: bool = False
    group: str = "system"
    min_int: int = 0
    max_int: int = 10_000


SETTING_DEFS: tuple[SettingDef, ...] = (
    SettingDef("deposit_min", "Depozit minimum", "money", lambda c: c.deposit_min),
    SettingDef("deposit_max", "Depozit maksimum", "money", lambda c: c.deposit_max),
    SettingDef("withdraw_min", "Yechish minimum", "money", lambda c: c.withdraw_min),
    SettingDef("withdraw_max", "Yechish maksimum", "money", lambda c: c.withdraw_max),
    SettingDef(
        "deposit_fee_percent", "Depozit komissiyasi %", "percent", lambda c: c.deposit_fee_percent
    ),
    SettingDef(
        "withdraw_fee_percent", "Yechish komissiyasi %", "percent", lambda c: c.withdraw_fee_percent
    ),
    SettingDef("support_url", "Support URL", "link", lambda c: c.support_url),
    SettingDef("cashbox_url", "Kassa URL", "link", lambda c: c.cashbox_url),
    SettingDef("maintenance", "Texnik ishlar rejimi", "bool", lambda c: False),
    SettingDef("timezone", "Vaqt zonasi", "tz", lambda c: c.timezone),
    SettingDef(
        "payment_mode",
        "To‘lov rejimi (test/production)",
        "mode",
        lambda c: c.payment_mode,
        critical=True,
    ),
    SettingDef(
        "enabled_providers",
        "Faol provayderlar",
        "providers",
        lambda c: c.provider_codes,
        critical=True,
    ),
    SettingDef(
        "payment_expiry_minutes",
        "To‘lov muddati (daqiqa)",
        "int",
        lambda c: c.payment_expiry_minutes,
        min_int=5,
        max_int=1440,
    ),
    SettingDef(
        "auto_payout_enabled",
        "Avto to‘lov",
        "bool",
        lambda c: c.auto_payout_enabled,
        group="payout",
    ),
    SettingDef(
        "auto_payout_max",
        "Avto to‘lov limiti",
        "money",
        lambda c: c.auto_payout_max,
        group="payout",
    ),
    SettingDef(
        "payout_max_attempts",
        "Payout urinishlar soni",
        "int",
        lambda c: c.payout_max_attempts,
        min_int=1,
        max_int=20,
        group="payout",
    ),
    SettingDef("contact_required", "Kontakt majburiy", "bool", lambda c: c.contact_required),
    SettingDef(
        "subscription_enabled",
        "Majburiy obuna",
        "bool",
        lambda c: c.subscription_enabled,
        group="channels",
    ),
    SettingDef(
        "referral_enabled", "Referal dasturi", "bool", lambda c: c.referral_enabled, group="bonus"
    ),
    SettingDef(
        "referral_percent",
        "Referal foizi %",
        "percent",
        lambda c: c.referral_percent,
        group="bonus",
    ),
    SettingDef(
        "referral_withdraw_min",
        "Referal yechish minimumi",
        "money",
        lambda c: c.referral_withdraw_min,
        group="bonus",
    ),
    SettingDef(
        "vip_bonus_enabled", "VIP bonus", "bool", lambda c: c.vip_bonus_enabled, group="bonus"
    ),
    SettingDef(
        "vip_section_enabled",
        "🏆 VIP bo‘limi (foydalanuvchilarga ko‘rinadi)",
        "bool",
        lambda c: c.vip_section_enabled,
        group="bonus",
    ),
    SettingDef(
        "webapp_enabled",
        "🌐 Web App (kassa ilovasi)",
        "bool",
        lambda c: c.webapp_enabled,
        group="system",
    ),
    SettingDef(
        "max_bonus_per_deposit",
        "Bir depozitga bonus limiti (0=cheksiz)",
        "money",
        lambda c: c.max_bonus_per_deposit,
        group="bonus",
    ),
    SettingDef(
        "mobcash_enabled",
        "Mob-Cash rejimi (to‘ldirish/yechish)",
        "bool",
        lambda c: c.mobcash_enabled,
        critical=True,
        group="mobcash",
    ),
    SettingDef(
        "p2p_sources",
        "Bank xabarlari manbalari (userbot)",
        "usernames",
        lambda c: c.p2p_sources,
        critical=True,
        group="mobcash",
    ),
    SettingDef(
        "mobcash_cashbox_code",
        "🏦 Kassa kodi",
        "int",
        lambda c: c.mobcash_cashbox_code,
        critical=True,
        group="mobcash",
        min_int=0,
        max_int=10**15,
    ),
    SettingDef(
        "mobcash_login",
        "👤 Kassa logini",
        "text",
        lambda c: c.mobcash_login,
        critical=True,
        group="mobcash",
    ),
    SettingDef(
        "mobcash_password",
        "🔑 Kassa paroli",
        "secret",
        lambda c: c.mobcash_password.get_secret_value(),
        critical=True,
        group="mobcash",
    ),
    SettingDef(
        "tg_api_id",
        "🆔 Telegram API ID",
        "int",
        lambda c: c.tg_api_id,
        critical=True,
        group="userbot",
        min_int=0,
        max_int=10**15,
    ),
    SettingDef(
        "tg_api_hash",
        "🔑 Telegram API HASH",
        "secret",
        lambda c: c.tg_api_hash.get_secret_value(),
        critical=True,
        group="userbot",
    ),
    SettingDef(
        "userbot_session_key",
        "🔐 Userbot kaliti (shifrlash)",
        "secret",
        lambda c: c.userbot_session_key.get_secret_value(),
        critical=True,
        group="userbot",
    ),
)
DEFS_BY_KEY = {d.key: d for d in SETTING_DEFS}


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    deposit_min: Decimal
    deposit_max: Decimal
    withdraw_min: Decimal
    withdraw_max: Decimal
    deposit_fee_percent: Decimal
    withdraw_fee_percent: Decimal
    support_url: str
    cashbox_url: str
    maintenance: bool
    timezone: str
    payment_mode: str
    enabled_providers: list[str]
    payment_expiry_minutes: int
    auto_payout_enabled: bool
    auto_payout_max: Decimal
    payout_max_attempts: int
    contact_required: bool
    subscription_enabled: bool
    referral_enabled: bool
    referral_percent: Decimal
    referral_withdraw_min: Decimal
    vip_bonus_enabled: bool
    vip_section_enabled: bool
    webapp_enabled: bool
    max_bonus_per_deposit: Decimal
    mobcash_enabled: bool
    p2p_sources: list[str]
    mobcash_cashbox_code: int
    mobcash_login: str
    mobcash_password: str
    tg_api_id: int
    tg_api_hash: str
    userbot_session_key: str

    @property
    def mobcash_configured(self) -> bool:
        return bool(self.mobcash_cashbox_code and self.mobcash_login and self.mobcash_password)

    @property
    def userbot_configured(self) -> bool:
        return bool(self.tg_api_id and self.tg_api_hash and self.userbot_session_key)


if {f.name for f in fields(RuntimeSettings)} != set(DEFS_BY_KEY):  # pragma: no cover
    raise RuntimeError("RuntimeSettings va SETTING_DEFS mos emas")

_TRUE = {"1", "true", "ha", "yes", "on", "yoqish", "✅"}
_FALSE = {"0", "false", "yo‘q", "yo'q", "yoq", "no", "off", "o‘chirish", "ochirish", "❌"}


def parse_value(d: SettingDef, raw: Any, registry_codes: list[str] | None = None) -> Any:
    """Kiritilgan qiymatni turiga moslab tekshiradi. Xato bo‘lsa ValueError (o‘zbekcha)."""
    if d.kind in ("money", "percent"):
        try:
            value = q(Decimal(str(raw).replace(" ", "").replace(",", ".")))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Raqam kiriting, masalan: 50000 yoki 1.5") from exc
        if value < 0:
            raise ValueError("Manfiy qiymat bo‘lmaydi.")
        if d.kind == "percent" and value > 100:
            raise ValueError("Foiz 0 dan 100 gacha bo‘lishi kerak.")
        return value
    if d.kind == "int":
        try:
            ivalue = int(str(raw).strip())
        except ValueError as exc:
            raise ValueError("Butun son kiriting.") from exc
        if not d.min_int <= ivalue <= d.max_int:
            raise ValueError(f"Qiymat {d.min_int} — {d.max_int} oralig‘ida bo‘lishi kerak.")
        return ivalue
    if d.kind == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE:
            return False
        raise ValueError("«ha» yoki «yo‘q» deb yozing.")
    if d.kind == "link":
        s = str(raw).strip()
        return "" if s in {"", "-"} else normalize_link(s)
    if d.kind == "tz":
        s = str(raw).strip()
        if get_tz(s).key != s:
            raise ValueError("Vaqt zonasi noto‘g‘ri. Masalan: Asia/Tashkent")
        return s
    if d.kind == "mode":
        s = str(raw).strip().lower()
        if s not in {"test", "production"}:
            raise ValueError("Faqat «test» yoki «production».")
        return s
    if d.kind == "providers":
        if isinstance(raw, list):
            items = raw
        else:
            s = str(raw).strip()
            items = [] if s in {"", "-"} else s.replace(" ", "").split(",")
        codes = [c.strip().lower() for c in items if c and c.strip()]
        if registry_codes is not None and codes:
            unknown = [c for c in codes if c not in registry_codes]
            if unknown:
                raise ValueError(f"Ulanmagan provayder: {', '.join(unknown)}")
        return codes
    if d.kind == "usernames":
        items = raw if isinstance(raw, list) else str(raw).replace(" ", "").split(",")
        names = [n.strip().lstrip("@") for n in items if n and n.strip()]
        bad = [n for n in names if not _TG_USERNAME.match(n)]
        if bad:
            raise ValueError(f"Noto‘g‘ri username: {', '.join(bad)}")
        if not names:
            raise ValueError("Kamida bitta bot username kerak, masalan: CardXabarBot")
        return list(dict.fromkeys(names))
    if d.kind in ("text", "secret"):
        s = str(raw).strip()
        return "" if s == "-" else s
    raise ValueError("Noma’lum sozlama turi")


def serialize_value(d: SettingDef, value: Any) -> str:
    if d.kind in ("providers", "usernames"):
        return ",".join(value)
    if d.kind == "bool":
        return "true" if value else "false"
    return str(value)


def display_value(d: SettingDef, value: Any) -> str:
    if d.kind == "money":
        return fmt_money(value)
    if d.kind == "percent":
        return f"{value}%"
    if d.kind == "bool":
        return "✅ Yoqilgan" if value else "⛔ O‘chirilgan"
    if d.kind == "providers":
        return ", ".join(value) or "— (yo‘q)"
    if d.kind == "usernames":
        return ", ".join(f"@{n}" for n in value)
    if d.kind == "link":
        return value or "— (sozlanmagan)"
    if d.kind == "text":
        return value or "— (sozlanmagan)"
    if d.kind == "secret":
        return "✅ O‘rnatilgan" if value else "❌ O‘rnatilmagan"
    return str(value)


class SettingsService:
    CACHE_KEY = "settings:v1"
    CACHE_TTL = 60

    def __init__(
        self, session: AsyncSession, redis: Redis, config: Config, providers: ProviderRegistry
    ) -> None:
        self.session = session
        self.redis = redis
        self.config = config
        self.providers = providers
        self.repo = SettingRepository(session)
        self._snapshot: RuntimeSettings | None = None

    async def _stored(self) -> dict[str, str]:
        try:
            cached = await self.redis.get(self.CACHE_KEY)
        except Exception:
            cached = None
        if cached:
            return dict(json.loads(cached))
        stored = await self.repo.all()
        try:
            await self.redis.set(self.CACHE_KEY, json.dumps(stored), ex=self.CACHE_TTL)
        except Exception:  # Redis vaqtincha ishlamasa — DBdan o‘qishda davom etamiz
            log.warning("Sozlamalar keshiga yozib bo‘lmadi", exc_info=True)
        return stored

    def _build(self, stored: dict[str, str]) -> RuntimeSettings:
        values: dict[str, Any] = {}
        for d in SETTING_DEFS:
            default = parse_value(d, d.default(self.config))
            raw = stored.get(d.key)
            if raw is None:
                values[d.key] = default
                continue
            try:
                values[d.key] = parse_value(d, raw)
            except ValueError:
                values[d.key] = default
        return RuntimeSettings(**values)

    async def snapshot(self) -> RuntimeSettings:
        if self._snapshot is None:
            self._snapshot = self._build(await self._stored())
        return self._snapshot

    async def invalidate(self) -> None:
        self._snapshot = None
        with contextlib.suppress(Exception):
            await self.redis.delete(self.CACHE_KEY)

    async def prepare_change(self, key: str, raw: Any) -> tuple[str, str, str]:
        """Yangi qiymatni tekshiradi. Qaytaradi: (eski ko‘rinish, yangi ko‘rinish, serialize)."""
        d = DEFS_BY_KEY.get(key)
        if d is None:
            raise ValueError("Noma’lum sozlama")
        new_value = parse_value(d, raw, self.providers.codes)
        if key == "userbot_session_key" and new_value and not is_valid_fernet_key(new_value):
            raise ValueError(
                "Kalit Fernet formatida emas. Uni «🛰 Userbot → 🔐 Kalit yaratish» orqali "
                "avtomatik yarating — qo‘lda kiritish shart emas."
            )
        current = await self.snapshot()
        merged = {f.name: getattr(current, f.name) for f in fields(RuntimeSettings)}
        merged[key] = new_value
        self._validate_cross(merged)
        return (
            display_value(d, getattr(current, key)),
            display_value(d, new_value),
            serialize_value(d, new_value),
        )

    def _validate_cross(self, v: dict[str, Any]) -> None:
        if v["deposit_min"] > v["deposit_max"]:
            raise ValueError("Depozit minimumi maksimumdan katta bo‘lmasligi kerak.")
        if v["withdraw_min"] > v["withdraw_max"]:
            raise ValueError("Yechish minimumi maksimumdan katta bo‘lmasligi kerak.")
        if v["payment_mode"] == "production":
            if self.providers.has_sandbox(v["enabled_providers"]):
                raise ValueError(
                    "Production rejimida sandbox faol bo‘lishi mumkin emas — avval "
                    "«Faol provayderlar»dan sandboxni olib tashlang (bo‘sh yoki «-»)."
                )
            if not (
                self.providers.has_real_provider(v["enabled_providers"]) or v["mobcash_enabled"]
            ):
                raise ValueError(
                    "Production rejimi uchun real to‘lov yo‘li kerak: Mob-Cash rejimini "
                    "yoqing yoki rasmiy provayder adapterini qo‘shing."
                )

    async def update(self, key: str, serialized: str, actor: Actor) -> None:
        d = DEFS_BY_KEY[key]
        old_display, new_display, serialized = await self.prepare_change(key, serialized)
        row = await self.repo.get(key)
        before = row.value if row else serialize_value(d, d.default(self.config))
        if row is None:
            self.session.add(SystemSetting(key=key, value=serialized, updated_by=actor.telegram_id))
        else:
            row.value = serialized
            row.updated_by = actor.telegram_id
        hidden = d.kind == "secret"  # maxfiy qiymatlar audit logda saqlanmaydi
        await AuditService(self.session).log(
            actor,
            "settings.update",
            "setting",
            key,
            before={"value": "***" if hidden else before, "display": old_display},
            after={"value": "***" if hidden else serialized, "display": new_display},
        )
        await self.session.commit()
        await self.invalidate()

    async def ensure_userbot_key(self, actor: Actor) -> str:
        """Kalit yo‘q yoki yaroqsiz (noto‘g‘ri format) bo‘lsa — yangisini yaratib saqlaydi."""
        rt = await self.snapshot()
        if rt.userbot_session_key and is_valid_fernet_key(rt.userbot_session_key):
            return rt.userbot_session_key
        key = Fernet.generate_key().decode()
        await self.update("userbot_session_key", key, actor)
        log.info("Userbot shifrlash kaliti avtomatik yaratildi")
        return key
