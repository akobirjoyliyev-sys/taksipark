"""Depozit oqimi: checkout → imzolangan webhook → balans faqat bir marta oshadi."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.enums import PaymentStatus, PromoType
from app.core.errors import DomainError
from app.core.utils import utcnow
from app.models import LedgerEntry, Payment, PromoCode, ReferralReward, VipLevel
from tests.integration.helpers import deliver, fund, ledger_count, make_user, services, wallet_of

pytestmark = pytest.mark.integration


async def test_deposit_paid_once(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 1001)
        payment = await svc.deposits.create(user, Decimal("100000"))
        assert payment.status == PaymentStatus.PENDING
        assert payment.checkout_url and payment.is_test

        payload = await sandbox.complete_payment(str(payment.ref), success=True)
        assert payload is not None
        result = await deliver(svc, sandbox, payload)
        assert result.status == "ok"
        assert result.deposit is not None and result.deposit.net == Decimal("100000")

        # Aynan shu webhook qayta keldi — dublikat
        again = await deliver(svc, sandbox, payload)
        assert again.status == "duplicate"
        # Boshqa event_id bilan qayta "paid" — baribir balans o‘zgarmaydi
        replay = await deliver(svc, sandbox, {**payload, "event_id": str(uuid.uuid4())})
        assert replay.status == "ok" and replay.deposit is None

        wallet = await wallet_of(session, user)
        assert wallet.available == Decimal("100000")
        assert wallet.total_deposit == Decimal("100000")
        entries = list(
            await session.scalars(
                select(LedgerEntry).where(LedgerEntry.reference_id == str(payment.id))
            )
        )
        assert len(entries) == 1


async def test_deposit_limits_and_amount_mismatch(
    sessionmaker, redis, registry, sandbox, config  # type: ignore[no-untyped-def]
) -> None:
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 1002)
        with pytest.raises(DomainError):
            await svc.deposits.create(user, Decimal("1"))
        payment = await svc.deposits.create(user, Decimal("50000"))
        payload = await sandbox.complete_payment(str(payment.ref), success=True)
        assert payload is not None
        result = await deliver(svc, sandbox, {**payload, "amount": "60000"})
        assert result.deposit is not None and result.deposit.amount_mismatch
        wallet = await wallet_of(session, user)
        assert wallet.available == 0


async def test_failed_and_expired(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 1003)
        p1 = await svc.deposits.create(user, Decimal("20000"))
        payload = await sandbox.complete_payment(str(p1.ref), success=False)
        result = await deliver(svc, sandbox, payload)  # type: ignore[arg-type]
        assert result.deposit is not None and result.deposit.status == PaymentStatus.FAILED

        p2 = await svc.deposits.create(user, Decimal("20000"))
        p2.expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()
        await redis.hset(f"sandbox:pay:{p2.ref}", "expires_at", "0")
        outcomes = await svc.deposits.expire_due()
        assert [o.payment.id for o in outcomes] == [p2.id]
        assert outcomes[0].status == PaymentStatus.EXPIRED
        assert (await wallet_of(session, user)).available == 0


async def test_reconcile_credits_when_webhook_lost(
    sessionmaker, redis, registry, sandbox, config  # type: ignore[no-untyped-def]
) -> None:
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 1004)
        payment = await svc.deposits.create(user, Decimal("30000"))
        await sandbox.complete_payment(str(payment.ref), success=True)  # webhook yuborilmadi
        outcomes = await svc.deposits.reconcile_pending(timedelta(seconds=0))
        assert len(outcomes) == 1 and outcomes[0].status == PaymentStatus.PAID
        assert (await wallet_of(session, user)).available == Decimal("30000")


async def test_bonuses_referral_vip_promo(sessionmaker, redis, registry, sandbox, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        session.add(
            VipLevel(name="Silver", min_total_deposit=Decimal("100000"), bonus_percent=Decimal("1"))
        )
        session.add(
            PromoCode(
                code="DEP10",
                bonus_type=PromoType.PERCENT,
                bonus_value=Decimal("10"),
                min_deposit=Decimal("100000"),
                per_user_limit=1,
            )
        )
        await session.commit()

        referrer = await make_user(svc, 2001, "Ali")
        friend, created = await svc.users.get_or_create(
            type("U", (), {"id": 2002, "first_name": "Vali", "last_name": None, "username": None})()
        )
        assert created
        assert await svc.users.attach_referrer(friend, f"ref_{referrer.telegram_id}") is not None
        # O‘zini taklif qilish mumkin emas
        assert await svc.users.attach_referrer(referrer, f"ref_{referrer.telegram_id}") is None

        promo = await svc.promo.activate(friend, "dep10")
        assert not promo.applied_now

        payment = await svc.deposits.create(friend, Decimal("250000"))
        payload = await sandbox.complete_payment(str(payment.ref), success=True)
        result = await deliver(svc, sandbox, payload)  # type: ignore[arg-type]
        assert result.deposit is not None
        labels = {b.label: b.amount for b in result.deposit.bonuses}
        assert labels["VIP Silver"] == Decimal("2500")
        assert labels["promokod DEP10"] == Decimal("25000")
        assert result.deposit.referral_amount == Decimal("5000")  # 2%

        friend_wallet = await wallet_of(session, friend)
        assert friend_wallet.available == Decimal("277500")
        ref_wallet = await wallet_of(session, referrer)
        assert ref_wallet.bonus_balance == Decimal("5000")
        assert await session.scalar(select(ReferralReward.amount)) == Decimal("5000")

        moved = await svc.referral.withdraw_bonus(referrer)
        assert moved == Decimal("5000")
        ref_wallet = await wallet_of(session, referrer)
        assert ref_wallet.available == Decimal("5000") and ref_wallet.bonus_balance == 0
        assert ref_wallet.referral_withdrawn == Decimal("5000")
        top = await svc.referral.top()
        assert top[0].telegram_id == referrer.telegram_id and top[0].friends == 1


async def test_promo_fixed_applies_immediately(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        session.add(
            PromoCode(
                code="WELCOME",
                bonus_type=PromoType.FIXED,
                bonus_value=Decimal("5000"),
                total_limit=1,
                per_user_limit=1,
            )
        )
        await session.commit()
        u1 = await make_user(svc, 3001)
        u2 = await make_user(svc, 3002)
        result = await svc.promo.activate(u1, "welcome")
        assert result.applied_now and result.bonus == Decimal("5000")
        assert (await wallet_of(session, u1)).available == Decimal("5000")
        with pytest.raises(DomainError):
            await svc.promo.activate(u1, "WELCOME")  # user limiti
        with pytest.raises(DomainError):
            await svc.promo.activate(u2, "WELCOME")  # umumiy limit
        assert await ledger_count(session, u2) == 0


async def test_ledger_is_append_only(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 4001)
        await fund(svc, user, "1000")  # ledger + audit yozuvi
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE ledger_entries SET amount = 999"))
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM ledger_entries"))
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("UPDATE audit_logs SET action = 'x'"))
        await session.rollback()


async def test_cancel_then_late_payment_is_credited(
    sessionmaker, redis, registry, sandbox, config  # type: ignore[no-untyped-def]
) -> None:
    async with sessionmaker() as session:
        svc = services(session, redis, registry, config)
        user = await make_user(svc, 5001)
        payment = await svc.deposits.create(user, Decimal("15000"))
        await svc.deposits.cancel(user, payment.id)
        payload = await sandbox.complete_payment(str(payment.ref), success=True)
        result = await deliver(svc, sandbox, payload)  # type: ignore[arg-type]
        assert result.deposit is not None and result.deposit.status == PaymentStatus.PAID
        stored = await session.get(Payment, payment.id)
        assert stored is not None and stored.status == PaymentStatus.PAID
        assert (await wallet_of(session, user)).available == Decimal("15000")
