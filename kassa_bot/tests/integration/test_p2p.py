"""P2P depozit (noyob summa → bank xabari → Mob-Cash) va Mob-Cash yechish oqimlari."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.config import Config
from app.core.enums import BankTxStatus, MobcashWithdrawalStatus, P2PDepositStatus
from app.core.errors import DomainError
from app.core.utils import utcnow
from app.mobcash import MobCashError, MobCashErrorKind
from app.models import P2PDeposit
from app.p2p.parser import ParsedTx
from app.services.container import Services
from app.services.mobcash_withdrawals import WithdrawQuote
from app.services.p2p import IN_PROGRESS
from tests.integration.helpers import ADMIN, OPERATOR, make_user

pytestmark = pytest.mark.integration


class FakeMobCash:
    configured = True
    cashbox_code = 1000042

    def __init__(self) -> None:
        self.deposits: list[tuple[str, Decimal]] = []
        self.withdrawals: list[tuple[str, str, Decimal]] = []
        self.deposit_errors: list[MobCashError] = []
        self.withdraw_error: MobCashError | None = None
        self.withdraw_amount = Decimal("100000")

    async def set_credentials(self, cashbox_code: int, login: str, password: str) -> None:
        return None

    async def payer_nickname(self, payer_id: str) -> str:
        if payer_id == "404404":
            raise MobCashError("not found", MobCashErrorKind.REJECTED)
        return f"nick_{payer_id}"

    async def deposit(self, payer_id: str, amount: Decimal) -> dict[str, Any]:
        if self.deposit_errors:
            raise self.deposit_errors.pop(0)
        self.deposits.append((payer_id, amount))
        return {"success": True, "amount": str(amount)}

    async def get_withdrawal_amount(self, payer_id: str, code: str) -> Decimal:
        return self.withdraw_amount

    async def withdrawal(self, payer_id: str, code: str, amount: Decimal) -> dict[str, Any]:
        if self.withdraw_error is not None:
            raise self.withdraw_error
        self.withdrawals.append((payer_id, code, amount))
        return {"success": True}


def svc_for(session, redis, registry, config: Config, fake: FakeMobCash) -> Services:  # type: ignore[no-untyped-def]
    return Services(
        session=session,
        redis=redis,
        providers=registry,
        config=config,
        mobcash=fake,  # type: ignore[arg-type]
    )


async def bank_msg(svc: Services, amount: Decimal, message_id: int, minutes: int = 0):  # type: ignore[no-untyped-def]
    return await svc.p2p.handle_bank_message(
        account_id=None,
        owner_tg_id=999,
        source_chat_id=777,
        source_name="CardXabarBot",
        message_id=message_id,
        text=f"➕ {amount} UZS",
        message_date=utcnow() + timedelta(minutes=minutes),
        parsed=ParsedTx(amount=amount, card_last4="1234"),
    )


async def setup(svc: Services) -> None:
    await svc.p2p.add_card("8600 1234 5678 1234", "Test Kassir", "Uzcard", ADMIN)


async def test_unique_amount_match_and_credit(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        u1, u2 = await make_user(svc, 5001), await make_user(svc, 5002)
        assert await svc.p2p.check_payer("123456") == "nick_123456"
        d1 = await svc.p2p.create(u1, "123456", "nick", Decimal("50000"))
        d2 = await svc.p2p.create(u2, "654321", "nick2", Decimal("50000"))
        assert d1.unique_amount != d2.unique_amount
        for d in (d1, d2):
            assert Decimal("50001") <= d.unique_amount <= Decimal("50999")
        with pytest.raises(DomainError):  # bitta foydalanuvchi — bitta kutilayotgan to‘lov
            await svc.p2p.create(u1, "123456", "nick", Decimal("70000"))

        match = await bank_msg(svc, d1.unique_amount, message_id=1)
        assert match is not None and match.deposit is not None and match.deposit.id == d1.id
        assert match.tx.status == BankTxStatus.MATCHED
        assert await bank_msg(svc, d1.unique_amount, message_id=1) is None  # dublikat xabar

        outcome = await svc.p2p.credit(d1.id)
        assert outcome is not None and outcome.event == "credited"
        assert fake.deposits == [("123456", d1.unique_amount)]
        assert await svc.p2p.credit(d1.id) is None  # qayta tushirilmaydi
        assert len(fake.deposits) == 1

        # Shu summaning ikkinchi o‘tkazmasi — endi kutilayotgan to‘lov yo‘q
        again = await bank_msg(svc, d1.unique_amount, message_id=2)
        assert again is not None and again.deposit is None
        assert (await svc.p2p.get(d2.id)).status == P2PDepositStatus.PENDING  # type: ignore[union-attr]


async def test_old_message_does_not_match_new_deposit(
    sessionmaker, redis, registry, config  # type: ignore[no-untyped-def]
) -> None:
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        user = await make_user(svc, 5003)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("20000"))
        match = await bank_msg(svc, dep.unique_amount, message_id=10, minutes=-30)
        assert match is not None and match.deposit is None


async def test_late_payment_and_reserved_amounts(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    tight = config.model_copy(update={"p2p_unique_max": 2})
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, tight, fake)
        await setup(svc)
        a, b, c = [await make_user(svc, tg) for tg in (5101, 5102, 5103)]
        dep_a = await svc.p2p.create(a, "111111", "a", Decimal("10000"))
        await session.execute(
            update(P2PDeposit)
            .where(P2PDeposit.id == dep_a.id)
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
        await session.commit()
        expired = await svc.p2p.expire_due()
        assert [o.deposit.id for o in expired] == [dep_a.id]

        # Muddati o‘tgan summa grace davomida boshqaga berilmaydi
        dep_b = await svc.p2p.create(b, "222222", "b", Decimal("10000"))
        assert dep_b.unique_amount != dep_a.unique_amount
        with pytest.raises(DomainError):
            await svc.p2p.create(c, "333333", "c", Decimal("10000"))

        late = await bank_msg(svc, dep_a.unique_amount, message_id=20)
        assert late is not None and late.late and late.deposit is not None
        assert late.deposit.id == dep_a.id
        assert (await svc.p2p.credit(dep_a.id)).event == "credited"  # type: ignore[union-attr]


async def test_unknown_outcome_goes_to_review_without_retry(
    sessionmaker, redis, registry, config  # type: ignore[no-untyped-def]
) -> None:
    fake = FakeMobCash()
    fake.deposit_errors.append(MobCashError("timeout", MobCashErrorKind.UNKNOWN))
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        user = await make_user(svc, 5201)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("30000"))
        await bank_msg(svc, dep.unique_amount, message_id=30)

        outcome = await svc.p2p.credit(dep.id)
        assert outcome is not None and outcome.event == "review"
        assert await svc.p2p.credit_due() == []  # avtomatik qayta yuborilmaydi
        assert fake.deposits == []

        await svc.p2p.admin_retry(dep.id, OPERATOR)
        outcome = await svc.p2p.credit(dep.id)
        assert outcome is not None and outcome.event == "credited"
        assert len(fake.deposits) == 1


async def test_network_error_is_retried(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    fake.deposit_errors.append(MobCashError("refused", MobCashErrorKind.NETWORK))
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        user = await make_user(svc, 5301)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("30000"))
        await bank_msg(svc, dep.unique_amount, message_id=40)
        first = await svc.p2p.credit(dep.id)
        assert first is not None and first.event == "retry"
        assert first.deposit.status == P2PDepositStatus.PAID
        outcomes = await svc.p2p.credit_due()
        assert [o.event for o in outcomes] == ["credited"]


async def test_interrupted_credit_is_not_repeated(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        user = await make_user(svc, 5401)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("30000"))
        await bank_msg(svc, dep.unique_amount, message_id=50)
        # Jarayon Mob-Cash so‘rovi o‘rtasida to‘xtab qolgan holat
        await session.execute(
            update(P2PDeposit).where(P2PDeposit.id == dep.id).values(last_error=IN_PROGRESS)
        )
        await session.commit()
        outcome = await svc.p2p.credit(dep.id)
        assert outcome is not None and outcome.event == "review"
        assert fake.deposits == []


async def test_link_unmatched_transaction(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        user = await make_user(svc, 5501)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("50000"))
        # Foydalanuvchi noyob summa o‘rniga yaxlit 50 000 o‘tkazdi
        wrong = await bank_msg(svc, Decimal("50000"), message_id=60)
        assert wrong is not None and wrong.deposit is None
        assert [t.id for t in await svc.p2p.unmatched(10)] == [wrong.tx.id]

        linked = await svc.p2p.link_transaction(wrong.tx.id, dep.id, OPERATOR)
        assert linked.status == P2PDepositStatus.PAID
        assert linked.credit_amount == Decimal("50000.00")
        await svc.p2p.credit(dep.id)
        assert fake.deposits == [("123456", Decimal("50000.00"))]
        assert await svc.p2p.unmatched(10) == []


async def test_create_retries_on_amount_collision(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)
        u1, u2 = await make_user(svc, 5651), await make_user(svc, 5652)
        first = await svc.p2p.create(u1, "111111", "a", Decimal("40000"))
        # Parallel so‘rov xuddi shu summani band qilgandek: birinchi tanlov to‘qnashadi.
        picks = iter([first.unique_amount, Decimal("40777.00")])

        async def colliding_pick(base: Decimal) -> Decimal:
            return next(picks)

        svc.p2p.pick_unique_amount = colliding_pick  # type: ignore[method-assign]
        second = await svc.p2p.create(u2, "222222", "b", Decimal("40000"))
        assert second.unique_amount == Decimal("40777.00")
        assert u2.mobcash_payer_id == "222222"


async def test_pending_amount_unique_index(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, FakeMobCash())
        u1, u2 = await make_user(svc, 5601), await make_user(svc, 5602)
        for user in (u1, u2):
            session.add(
                P2PDeposit(
                    user_id=user.id,
                    payer_id="1",
                    amount=Decimal("10000"),
                    unique_amount=Decimal("10001"),
                    expires_at=utcnow() + timedelta(minutes=5),
                )
            )
        with pytest.raises(IntegrityError):
            await session.commit()


# =========================================================================== yechish
async def test_withdrawal_flow(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        user = await make_user(svc, 5701)
        quote = await svc.mcwd.quote("123456", "Secret_abc")
        assert quote == WithdrawQuote(Decimal("100000.00"), Decimal("1000.00"), Decimal("99000.00"))

        wd = await svc.mcwd.execute(user, "123456", "Secret_abc", quote, "8600123412349999")
        assert wd.status == MobcashWithdrawalStatus.AWAITING_PAYOUT
        assert wd.code_mask != "Secret_abc"
        assert fake.withdrawals == [("123456", "Secret_abc", Decimal("100000.00"))]
        assert user.payout_card_number == "8600123412349999"

        event = await svc.mcwd.mark_paid(wd.id, OPERATOR)
        assert event.withdrawal.status == MobcashWithdrawalStatus.PAID
        assert event.user_telegram_id == 5701
        with pytest.raises(DomainError):
            await svc.mcwd.mark_paid(wd.id, OPERATOR)


async def test_withdrawal_unknown_review_and_refund(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    fake.withdraw_error = MobCashError("timeout", MobCashErrorKind.UNKNOWN)
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        user = await make_user(svc, 5801)
        quote = await svc.mcwd.quote("123456", "Secret_abc")
        wd = await svc.mcwd.execute(user, "123456", "Secret_abc", quote, "8600123412349999")
        assert wd.status == MobcashWithdrawalStatus.REVIEW

        event = await svc.mcwd.confirm_review(wd.id, OPERATOR, withdrawn=True)
        assert event.withdrawal.status == MobcashWithdrawalStatus.AWAITING_PAYOUT
        event = await svc.mcwd.refund(wd.id, OPERATOR, "karta bloklangan")
        assert event.withdrawal.status == MobcashWithdrawalStatus.REFUNDED
        assert fake.deposits == [("123456", Decimal("100000.00"))]


async def test_withdrawal_rejected_and_limits(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    fake = FakeMobCash()
    fake.withdraw_error = MobCashError("code used", MobCashErrorKind.REJECTED)
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        user = await make_user(svc, 5901)
        quote = await svc.mcwd.quote("123456", "Secret_abc")
        with pytest.raises(DomainError):
            await svc.mcwd.execute(user, "123456", "Secret_abc", quote, "8600123412349999")
        failed = await svc.mcwd.list_for_user(user)
        assert [w.status for w in failed] == [MobcashWithdrawalStatus.FAILED]

        fake.withdraw_amount = Decimal("100")  # minimal yechishdan kam
        with pytest.raises(DomainError):
            await svc.mcwd.quote("123456", "Secret_abc")


async def test_bank_card_mismatch_does_not_match(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    """Kirim boshqa kartamizga kelgan bo‘lsa (summa tasodifan bir xil), depozitga bog‘lanmaydi."""
    fake = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, fake)
        await setup(svc)  # ...1234
        await svc.p2p.add_card("8600 0000 0000 9999", "Boshqa", "Humo", ADMIN)
        user = await make_user(svc, 5201)
        dep = await svc.p2p.create(user, "123456", "nick", Decimal("30000"))
        card = await svc.p2p.card_for(dep)
        assert card is not None
        other = "9999" if card.last4 == "1234" else "1234"

        async def msg(last4: str | None, message_id: int):  # type: ignore[no-untyped-def]
            return await svc.p2p.handle_bank_message(
                account_id=None,
                owner_tg_id=999,
                source_chat_id=777,
                source_name="CardXabarBot",
                message_id=message_id,
                text="➕",
                message_date=utcnow(),
                parsed=ParsedTx(amount=dep.unique_amount, card_last4=last4),
            )

        wrong = await msg(other, 51)
        assert wrong is not None and wrong.deposit is None
        unknown = await msg("0000", 52)  # bizning karta emas — format boshqacha, cheklanmaydi
        assert unknown is not None and unknown.deposit is not None
        assert unknown.deposit.id == dep.id


async def test_userbot_watchdog_alerts_once(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config, monkeypatch
) -> None:
    from types import SimpleNamespace

    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    from app.jobs import tasks
    from app.models import UserbotAccount
    from app.services.notifier import Notifier

    cfg = config.model_copy(
        update={
            "mobcash_enabled": True,
            "tg_api_id": 1,
            "tg_api_hash": SecretStr("hash"),
            "userbot_session_key": SecretStr(Fernet.generate_key().decode()),
        }
    )
    sent: list[str] = []

    async def fake_send_many(self, chat_ids, text, reply_markup=None):  # type: ignore[no-untyped-def]
        sent.append(text)
        return 1

    monkeypatch.setattr(Notifier, "send_many", fake_send_many)
    ctx = SimpleNamespace(
        sessionmaker=sessionmaker,
        redis=redis,
        services=lambda s: svc_for(s, redis, registry, cfg, FakeMobCash()),
    )
    async with sessionmaker() as session:
        fresh = UserbotAccount(phone="+998900000001", session_encrypted="x", last_seen_at=utcnow())
        stale = UserbotAccount(
            phone="+998900000002",
            session_encrypted="x",
            last_seen_at=utcnow() - timedelta(minutes=20),
        )
        session.add_all([fresh, stale])
        await session.commit()
        stale_id = stale.id

    assert await tasks.userbot_watchdog(ctx) == 1  # type: ignore[arg-type]
    assert len(sent) == 1 and f"#{stale_id}" in sent[0]
    assert await tasks.userbot_watchdog(ctx) == 0  # type: ignore[arg-type]  # soatiga bir marta
