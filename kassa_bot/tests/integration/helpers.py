from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Config
from app.core.enums import AdminRole, LedgerDirection
from app.models import LedgerEntry, User, Wallet
from app.payments.registry import ProviderRegistry
from app.payments.sandbox import SandboxProvider
from app.services.audit import Actor
from app.services.container import Services
from app.webhooks.processor import WebhookResult, process_provider_event
from tests.conftest import TgUser

ADMIN = Actor(telegram_id=1, role=AdminRole.SUPERADMIN.value)
OPERATOR = Actor(telegram_id=2, role=AdminRole.OPERATOR.value)


def services(
    session: AsyncSession, redis: object, registry: ProviderRegistry, config: Config
) -> Services:
    return Services(session=session, redis=redis, providers=registry, config=config)  # type: ignore[arg-type]


async def make_user(svc: Services, tg_id: int, name: str = "Test") -> User:
    user, _ = await svc.users.get_or_create(TgUser(id=tg_id, first_name=name))
    return user


async def fund(svc: Services, user: User, amount: str) -> None:
    await svc.users.adjust_balance(
        user.id, Decimal(amount), LedgerDirection.CREDIT, "test funding", ADMIN
    )


async def wallet_of(session: AsyncSession, user: User) -> Wallet:
    stmt = select(Wallet).where(Wallet.user_id == user.id).execution_options(populate_existing=True)
    wallet = await session.scalar(stmt)
    assert wallet is not None
    return wallet


async def ledger_count(session: AsyncSession, user: User) -> int:
    stmt = select(func.count(LedgerEntry.id)).where(LedgerEntry.user_id == user.id)
    return int(await session.scalar(stmt) or 0)


async def deliver(svc: Services, sandbox: SandboxProvider, payload: dict) -> WebhookResult:  # type: ignore[type-arg]
    headers, body = sandbox.build_webhook(payload)
    event = sandbox.verify_webhook(headers, body)
    return await process_provider_event(svc, sandbox.code, event)


async def bind_card(svc: Services, sandbox: SandboxProvider, user: User, kind: str = "ok") -> int:
    url = await svc.cards.start_binding(user)
    reference = url.split("/sandbox/cards/")[1].split("?")[0]
    payload = await sandbox.complete_card_binding(reference, kind)
    assert payload is not None
    result = await deliver(svc, sandbox, payload)
    assert result.card_owner == user.telegram_id
    cards = await svc.cards.list_page(user)
    return cards[-1].id
