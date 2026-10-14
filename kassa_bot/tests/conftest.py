from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

import fakeredis
import pytest
from pydantic import SecretStr

# Testlarda .env o‘qilmasin va real token talab qilinmasin.
os.environ.setdefault("BOT_TOKEN", "")
os.environ.setdefault("ADMIN_IDS", "")

from app.config import Config
from app.payments.registry import ProviderRegistry
from app.payments.sandbox import SandboxProvider

SANDBOX_SECRET = "test-sandbox-secret"


@pytest.fixture
def config() -> Config:
    return Config(
        _env_file=None,  # type: ignore[call-arg]
        bot_token=SecretStr(""),
        bot_username="kassa_test_bot",
        sandbox_webhook_secret=SecretStr(SANDBOX_SECRET),
        sandbox_payout_delay_seconds=0,
        public_base_url="https://kassa.example.com",
        subscription_enabled=False,
        # Eski hamyon oqimi testlari uchun; Mob-Cash oqimi alohida testlarda yoqiladi.
        mobcash_enabled=False,
    )


@pytest.fixture
def redis() -> fakeredis.FakeAsyncRedis:
    return fakeredis.FakeAsyncRedis()


@pytest.fixture
def sandbox(redis: fakeredis.FakeAsyncRedis) -> SandboxProvider:
    return SandboxProvider(
        redis=redis,
        secret=SANDBOX_SECRET,
        public_base_url="https://kassa.example.com",
        payout_delay_seconds=0,
    )


@pytest.fixture
def registry(sandbox: SandboxProvider) -> ProviderRegistry:
    return ProviderRegistry([sandbox])


@dataclass
class TgUser:
    """aiogram.types.User o‘rnini bosuvchi minimal obyekt."""

    id: int
    first_name: str = "Test"
    last_name: str | None = None
    username: str | None = None


# --------------------------------------------------------------------------- integratsiya
TEST_DB_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL berilmagan — integratsiya testlari o‘tkazib yuborildi")
    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DB_URL


@pytest.fixture
async def sessionmaker(migrated_db: str) -> AsyncIterator[object]:
    from sqlalchemy import text

    from app.db import Base, create_engine, create_sessionmaker

    engine = create_engine(migrated_db)
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    yield create_sessionmaker(engine)
    await engine.dispose()
