from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import AdminRole


class Config(BaseSettings):
    """ENV orqali sozlanadigan parametrlar.

    Runtime'da o‘zgaradigan biznes sozlamalari (limitlar, URLlar, foizlar) bu yerda faqat
    standart qiymat sifatida beriladi; keyin ular admin paneldan `system_settings`
    jadvali orqali boshqariladi.
    """

    # env_ignore_empty: `.env`dagi bo‘sh qiymat (`MOBCASH_CASHBOX_CODE=`) standartga tushadi.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # Telegram
    bot_token: SecretStr = SecretStr("")
    bot_username: str = ""
    bot_mode: Literal["polling", "webhook"] = "polling"
    admin_ids: str = ""
    telegram_webhook_secret: SecretStr = SecretStr("")

    # Infra
    database_url: str = "postgresql+asyncpg://kassa:kassa@localhost:5432/kassa"
    redis_url: str = "redis://localhost:6379/0"
    public_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"
    log_json: bool = False
    # /api/kassa/* REST endpointlari uchun token (X-Token sarlavhasi); bo'sh bo'lsa API o'chiq.
    api_token: SecretStr = SecretStr("")

    # To‘lov provayderlari
    payment_providers: str = "sandbox"
    payment_mode: Literal["test", "production"] = "test"
    sandbox_webhook_secret: SecretStr = SecretStr("change-me-sandbox-secret")
    sandbox_payout_failure_rate: float = 0.0
    sandbox_payout_delay_seconds: int = 3

    # Biznes sozlamalari (standart qiymatlar)
    currency: str = "UZS"
    timezone: str = "Asia/Tashkent"
    support_url: str = ""
    cashbox_url: str = ""
    deposit_min: Decimal = Decimal("10000")
    deposit_max: Decimal = Decimal("10000000")
    withdraw_min: Decimal = Decimal("20000")
    withdraw_max: Decimal = Decimal("5000000")
    deposit_fee_percent: Decimal = Decimal("0")
    withdraw_fee_percent: Decimal = Decimal("1")
    referral_percent: Decimal = Decimal("2")
    referral_withdraw_min: Decimal = Decimal("5000")
    max_bonus_per_deposit: Decimal = Decimal("0")
    payment_expiry_minutes: int = 15
    auto_payout_enabled: bool = False
    auto_payout_max: Decimal = Decimal("500000")
    payout_max_attempts: int = 5
    contact_required: bool = False
    subscription_enabled: bool = True
    vip_bonus_enabled: bool = True
    vip_section_enabled: bool = True
    webapp_enabled: bool = True
    referral_enabled: bool = True

    # Mob-Cash kassa API
    mobcash_enabled: bool = True
    mobcash_cashbox_code: int = 0
    mobcash_login: str = ""
    mobcash_password: SecretStr = SecretStr("")
    mobcash_auth_url: str = "https://admin.mob-cash.com/api/v2/cashbox"
    mobcash_api_url: str = "https://admin.mob-cash.com/api/v1/mobile"
    mobcash_timeout_seconds: int = 30
    cashdesk_api_url: str = "https://partners.servcul.com/CashdeskBotAPI"
    agent_api_base: str = "https://fg4fd7d5t6.com"
    # 🤖 Avto to‘lov: ketma-ket depozitlar orasidagi pauza (kassa API'ni bosib yubormaslik uchun)
    auto_deposit_delay_ms: int = 300

    # P2P (karta → karta) noyob summa bilan to‘lov
    p2p_sources: str = "CardXabarBot,HUMOcardbot"
    p2p_unique_max: int = 999
    p2p_late_grace_hours: int = 24

    # Userbot (Telethon) — https://my.telegram.org dan olinadi
    tg_api_id: int = 0
    tg_api_hash: SecretStr = SecretStr("")
    userbot_session_key: SecretStr = SecretStr("")

    # Himoya
    rate_limit_per_second: int = 3
    rate_limit_per_minute: int = 40
    report_hour: int = 9

    @property
    def provider_codes(self) -> list[str]:
        return [c.strip().lower() for c in self.payment_providers.split(",") if c.strip()]

    @property
    def mobcash_configured(self) -> bool:
        return bool(
            self.mobcash_cashbox_code
            and self.mobcash_login
            and self.mobcash_password.get_secret_value()
        )

    @property
    def userbot_configured(self) -> bool:
        return bool(
            self.tg_api_id
            and self.tg_api_hash.get_secret_value()
            and self.userbot_session_key.get_secret_value()
        )

    @property
    def admin_roles(self) -> dict[int, AdminRole]:
        """`ADMIN_IDS=123:superadmin,456:operator` — rol ko‘rsatilmasa superadmin."""
        result: dict[int, AdminRole] = {}
        for chunk in self.admin_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            raw_id, _, raw_role = chunk.partition(":")
            try:
                tg_id = int(raw_id.strip())
            except ValueError as exc:
                raise ValueError(f"ADMIN_IDS noto‘g‘ri: {chunk!r}") from exc
            role = AdminRole(raw_role.strip().lower()) if raw_role.strip() else AdminRole.SUPERADMIN
            result[tg_id] = role
        return result


@lru_cache
def get_config() -> Config:
    return Config()
