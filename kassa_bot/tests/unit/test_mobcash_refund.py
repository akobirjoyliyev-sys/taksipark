"""Qaytarish uzilganda ikki marta to‘lov ketmasligi (DB/HTTP o‘rniga sinov adapterlari)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import fakeredis
import pytest

from app.bot.keyboards.admin_mobcash import mcwd_kb
from app.core.enums import MobcashWithdrawalStatus
from app.core.errors import DomainError
from app.mobcash import MobCashError, MobCashErrorKind
from app.models import MobcashWithdrawal
from app.services.audit import Actor
from app.services.mobcash_withdrawals import MobcashWithdrawalService

ADMIN = Actor(telegram_id=10001, role="superadmin")


@pytest.fixture
async def refund_case(config):
    wd = MobcashWithdrawal(
        id=7,
        user_id=1,
        bookmaker_id=None,
        payer_id="777001",
        code_mask="Sec***st",
        amount=Decimal("100000"),
        fee=Decimal("1000"),
        payout_amount=Decimal("99000"),
        card_number="8600123456781234",
        status=MobcashWithdrawalStatus.AWAITING_PAYOUT,
        mobcash_result={"success": True},
    )
    committed = []

    async def commit():
        committed.append(wd.status)

    session = SimpleNamespace(
        commit=AsyncMock(side_effect=commit),
        add=Mock(),
        flush=AsyncMock(),
        get=AsyncMock(return_value=SimpleNamespace(telegram_id=10002)),
    )
    redis = fakeredis.FakeAsyncRedis()
    client = SimpleNamespace(deposit=AsyncMock(return_value={"success": True, "amount": "100000"}))
    svc = MobcashWithdrawalService(
        session,
        redis,
        SimpleNamespace(config=config),
        client,
        SimpleNamespace(client=AsyncMock(return_value=client)),
    )
    svc.get = AsyncMock(return_value=wd)
    yield SimpleNamespace(svc=svc, client=client, wd=wd, committed=committed, redis=redis)
    await redis.aclose()


async def test_refund_is_persisted_before_api_and_cannot_repeat(refund_case):
    c = refund_case

    async def deposit(*args):
        assert c.committed == [MobcashWithdrawalStatus.REFUND_REVIEW]
        assert c.wd.status == MobcashWithdrawalStatus.REFUND_REVIEW
        with pytest.raises(DomainError):
            await c.svc.mark_paid(c.wd.id, ADMIN)
        with pytest.raises(DomainError):
            await c.svc.confirm_refund(c.wd.id, ADMIN, refunded=True)
        return {"success": True, "amount": "100000"}

    c.client.deposit.side_effect = deposit
    event = await c.svc.refund(c.wd.id, ADMIN, "karta ishlamayapti")
    assert event.withdrawal.status == MobcashWithdrawalStatus.REFUNDED
    assert c.wd.last_error is None
    with pytest.raises(DomainError):
        await c.svc.refund(c.wd.id, ADMIN, "takror")
    assert c.client.deposit.await_count == 1


@pytest.mark.parametrize("refunded", [True, False])
async def test_unknown_refund_needs_manual_resolution(refund_case, refunded):
    c = refund_case
    c.client.deposit.side_effect = MobCashError("timeout", MobCashErrorKind.UNKNOWN)
    with pytest.raises(DomainError, match="noma’lum"):
        await c.svc.refund(c.wd.id, ADMIN, "qaytarish")
    assert c.wd.status == MobcashWithdrawalStatus.REFUND_REVIEW
    assert c.committed[-1] == MobcashWithdrawalStatus.REFUND_REVIEW
    with pytest.raises(DomainError):
        await c.svc.refund(c.wd.id, ADMIN, "takror")
    with pytest.raises(DomainError):
        await c.svc.mark_paid(c.wd.id, ADMIN)
    with pytest.raises(DomainError):
        await c.svc.confirm_review(c.wd.id, ADMIN, withdrawn=True)

    keys = mcwd_kb(c.wd)
    actions = [button.callback_data for row in keys.inline_keyboard for button in row]
    assert any("rf_ok" in action for action in actions)
    assert any("rf_fail" in action for action in actions)
    assert not any(":paid:" in action or ":refund:" in action for action in actions)

    event = await c.svc.confirm_refund(c.wd.id, ADMIN, refunded=refunded)
    expected = (
        MobcashWithdrawalStatus.REFUNDED if refunded else MobcashWithdrawalStatus.AWAITING_PAYOUT
    )
    assert event.withdrawal.status == expected
    assert c.client.deposit.await_count == 1  # admin tasdig‘i pul so‘rovi yubormaydi


@pytest.mark.parametrize("kind", [MobCashErrorKind.REJECTED, MobCashErrorKind.NETWORK])
async def test_known_unapplied_refund_restores_payout_state(refund_case, kind):
    c = refund_case
    c.client.deposit.side_effect = MobCashError("not applied", kind)
    with pytest.raises(DomainError):
        await c.svc.refund(c.wd.id, ADMIN, "qaytarish")
    assert c.wd.status == MobcashWithdrawalStatus.AWAITING_PAYOUT
    assert c.committed == [
        MobcashWithdrawalStatus.REFUND_REVIEW,
        MobcashWithdrawalStatus.AWAITING_PAYOUT,
    ]


async def test_cancelled_refund_keeps_durable_review_state(refund_case):
    c = refund_case
    c.client.deposit.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await c.svc.refund(c.wd.id, ADMIN, "qaytarish")
    assert c.committed == [MobcashWithdrawalStatus.REFUND_REVIEW]
    assert c.wd.status == MobcashWithdrawalStatus.REFUND_REVIEW
    with pytest.raises(DomainError):
        await c.svc.refund(c.wd.id, ADMIN, "takror")
    assert c.client.deposit.await_count == 1
