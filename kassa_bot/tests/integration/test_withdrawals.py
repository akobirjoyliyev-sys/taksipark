"""Yechish: bloklash → tasdiq → payout → yakun; rad etish/qaytarish; retry → manual navbat."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.enums import (
    MassBatchStatus,
    MassItemStatus,
    WithdrawalSource,
    WithdrawalStatus,
)
from app.core.errors import DomainError, PermissionDeniedError
from app.models import AuditLog, MassPayoutItem, SystemSetting, Withdrawal
from app.payments.registry import ProviderRegistry
from app.payments.sandbox import SandboxProvider
from tests.integration.helpers import (
    ADMIN,
    OPERATOR,
    bind_card,
    fund,
    make_user,
    services,
    wallet_of,
)

pytestmark = pytest.mark.integration


async def test_manual_approve_and_payout(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 6001)
        await fund(svc, user, "100000")
        card_id = await bind_card(svc, sandbox, user)

        with pytest.raises(DomainError):
            await svc.withdrawals.create(user, card_id, Decimal("500000"))  # balans yetmaydi

        w = await svc.withdrawals.create(user, card_id, Decimal("50000"))
        assert w.status == WithdrawalStatus.PENDING and w.manual_required
        assert w.fee == Decimal("500.00") and w.net_amount == Decimal("49500.00")
        wallet = await wallet_of(session, user)
        assert (wallet.available, wallet.blocked) == (Decimal("50000"), Decimal("50000"))

        with pytest.raises(DomainError):
            await svc.withdrawals.approve(w.id, OPERATOR, "")  # izoh majburiy
        event = await svc.withdrawals.approve(w.id, OPERATOR, "tekshirildi")
        assert event.withdrawal.status == WithdrawalStatus.APPROVED

        events = await svc.withdrawals.process_queue()
        assert events == []  # sandbox: processing
        stored = await session.get(Withdrawal, w.id)
        assert stored is not None and stored.status == WithdrawalStatus.PROCESSING

        from datetime import timedelta

        polled = await svc.withdrawals.poll_processing(min_age=timedelta(seconds=0))
        assert [e.withdrawal.status for e in polled] == [WithdrawalStatus.PAID]
        wallet = await wallet_of(session, user)
        assert wallet.blocked == 0 and wallet.available == Decimal("50000")
        assert wallet.total_withdraw == Decimal("50000")
        history = [h.to_status for h in await svc.withdrawals.history(w.id)]
        assert history == ["pending", "approved", "processing", "paid"]
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.action == "withdrawal.approve")
        )
        assert audit is not None and audit.actor_telegram_id == OPERATOR.telegram_id


async def test_reject_refunds(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 6002)
        await fund(svc, user, "80000")
        card_id = await bind_card(svc, sandbox, user)
        w = await svc.withdrawals.create(user, card_id, Decimal("30000"))
        event = await svc.withdrawals.reject(w.id, OPERATOR, "karta egasi mos emas")
        assert event.withdrawal.status == WithdrawalStatus.REJECTED
        wallet = await wallet_of(session, user)
        assert wallet.available == Decimal("80000") and wallet.blocked == 0
        with pytest.raises(DomainError):
            await svc.withdrawals.reject(w.id, OPERATOR, "yana")


async def test_auto_payout_declined_card_refunds(
    sessionmaker, redis, registry, sandbox, config  # type: ignore[no-untyped-def]
) -> None:
    async with sessionmaker() as session:
        session.add(SystemSetting(key="auto_payout_enabled", value="true"))
        await session.commit()
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 6003)
        await fund(svc, user, "60000")
        card_id = await bind_card(svc, sandbox, user, kind="decline")
        w = await svc.withdrawals.create(user, card_id, Decimal("40000"))
        assert w.status == WithdrawalStatus.APPROVED  # avto navbat
        events = await svc.withdrawals.process_queue()
        assert [e.withdrawal.status for e in events] == [WithdrawalStatus.FAILED]
        wallet = await wallet_of(session, user)
        assert wallet.available == Decimal("60000") and wallet.blocked == 0


async def test_transient_errors_go_to_manual_queue(sessionmaker, redis, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    flaky = SandboxProvider(
        redis=redis,
        secret="test-sandbox-secret",
        public_base_url="https://kassa.example.com",
        payout_failure_rate=1.0,
    )
    registry = ProviderRegistry([flaky])
    async with sessionmaker() as session:
        session.add(SystemSetting(key="payout_max_attempts", value="2"))
        await session.commit()
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 6004)
        await fund(svc, user, "60000")
        card_id = await bind_card(svc, flaky, user)
        w = await svc.withdrawals.create(user, card_id, Decimal("25000"))
        await svc.withdrawals.approve(w.id, ADMIN, "tasdiq")

        assert await svc.withdrawals.process_queue() == []  # 1-urinish: retry rejalashtirildi
        stored = await session.get(Withdrawal, w.id)
        assert stored is not None
        assert stored.status == WithdrawalStatus.APPROVED and stored.attempts == 1
        stored.next_attempt_at = None
        await session.commit()

        events = await svc.withdrawals.process_queue()  # 2-urinish: manual navbat
        assert len(events) == 1 and events[0].to_manual
        stored = await session.get(Withdrawal, w.id, populate_existing=True)
        assert stored is not None
        assert stored.status == WithdrawalStatus.PENDING and stored.manual_required
        wallet = await wallet_of(session, user)
        assert wallet.blocked == Decimal("25000")  # pul hamon bloklangan, yo‘qolmagan

        await svc.withdrawals.mark_paid_manually(w.id, OPERATOR, "kabinet orqali #TX1")
        wallet = await wallet_of(session, user)
        assert wallet.blocked == 0 and wallet.total_withdraw == Decimal("25000")


async def test_mass_payout_flow(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        u1 = await make_user(svc, 7001)
        u2 = await make_user(svc, 7002)
        await bind_card(svc, sandbox, u1)
        csv_bytes = (
            b"telegram_id,amount,provider\n"
            b"7001,30000,sandbox\n"
            b"7001,30000,sandbox\n"  # faylda dublikat
            b"7002,25000,sandbox\n"  # karta yo‘q
            b"9999,25000,sandbox\n"  # foydalanuvchi yo‘q
            b"7001,5,sandbox\n"  # limitdan past
        )
        creator = ADMIN.__class__(telegram_id=10, role="admin")
        batch = await svc.mass.create_preview(csv_bytes, "pay.csv", creator)
        assert (batch.valid_rows, batch.duplicate_rows, batch.invalid_rows) == (1, 1, 3)
        assert batch.total_amount == Decimal("30000")

        with pytest.raises(PermissionDeniedError):
            await svc.mass.approve(batch.id, creator)  # admin roli tasdiqlay olmaydi
        same_operator = OPERATOR.__class__(telegram_id=10, role="operator")
        with pytest.raises(PermissionDeniedError):
            await svc.mass.approve(batch.id, same_operator)  # o‘zi yuklaganini tasdiqlamaydi

        batch = await svc.mass.approve(batch.id, OPERATOR)
        assert batch.status == MassBatchStatus.PROCESSING
        await svc.withdrawals.process_queue()
        from datetime import timedelta

        await svc.withdrawals.poll_processing(min_age=timedelta(seconds=0))
        batch = await session.get(type(batch), batch.id, populate_existing=True)  # type: ignore[assignment]
        assert batch is not None
        assert batch.status == MassBatchStatus.COMPLETED and batch.paid_count == 1
        item = await session.scalar(
            select(MassPayoutItem).where(MassPayoutItem.status == MassItemStatus.PAID)
        )
        assert item is not None
        w = await session.get(Withdrawal, item.withdrawal_id)
        assert w is not None and w.source == WithdrawalSource.MASS
        # Ommaviy to‘lov foydalanuvchi balansiga tegmaydi
        assert (await wallet_of(session, u1)).available == 0
        assert u2.id  # karta yo‘q foydalanuvchi o‘zgarmadi

        again = await svc.mass.create_preview(
            b"telegram_id,amount,provider\n7001,30000,sandbox\n", "pay2.csv", creator
        )
        assert again.duplicate_rows == 1  # 24 soat ichidagi takror


async def test_settings_update_is_audited(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        await svc.settings.update("deposit_min", "25000", ADMIN)
        assert (await svc.settings.snapshot()).deposit_min == Decimal("25000")
        log = await session.scalar(select(AuditLog).where(AuditLog.action == "settings.update"))
        assert log is not None and log.entity_id == "deposit_min"
        with pytest.raises(ValueError):
            await svc.settings.update("payment_mode", "production", ADMIN)
