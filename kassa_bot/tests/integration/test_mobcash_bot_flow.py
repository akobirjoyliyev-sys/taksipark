"""Dispatcher orqali Mob-Cash oqimi: to‘ldirish → bank xabari → tushirish → yechish → admin."""

from __future__ import annotations

import gc
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from aiogram import Bot, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import ErrorEvent
from sqlalchemy import select

from app import texts
from app.bootstrap import AppContext
from app.bot.factory import create_dispatcher
from app.bot.keyboards.callbacks import AdmCb, McCb
from app.core.enums import AdminRole, MobcashWithdrawalStatus, P2PDepositStatus
from app.core.utils import utcnow
from app.models import MobcashWithdrawal, P2PDeposit
from app.p2p.parser import ParsedTx
from app.services.admins import AdminService
from tests.integration.helpers import ADMIN
from tests.integration.test_bot_flows import Driver, FakeSession
from tests.integration.test_p2p import FakeMobCash

pytestmark = pytest.mark.integration

ADMIN_ID = 6000001
USER_ID = 6000002


def detach_module_routers() -> None:
    """Modul darajasidagi routerlar bir jarayonda faqat bitta dispatcherga ulanadi.

    Productionda dispatcher bir marta yaratiladi; testlar esa bir nechta yaratadi.
    """
    for obj in gc.get_objects():
        if isinstance(obj, Router):
            obj._parent_router = None


def joined(out: list[str], errors: list[BaseException]) -> str:
    assert texts.ERROR_GENERIC not in out, [repr(e) for e in errors]
    return "\n".join(out)


async def test_mobcash_bot_flow(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    config.rate_limit_per_second = 1000
    config.rate_limit_per_minute = 10000
    config.mobcash_enabled = True
    session = FakeSession()
    bot = Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    mobcash = FakeMobCash()
    ctx = AppContext(config, None, sessionmaker, redis, registry, bot, mobcash)  # type: ignore[arg-type]
    async with sessionmaker() as s:
        await AdminService(s).sync_from_env({ADMIN_ID: AdminRole.SUPERADMIN})
        await ctx.services(s).p2p.add_card("8600123456781234", "Kassir Test", "Uzcard", ADMIN)
    detach_module_routers()
    dp = create_dispatcher(ctx)
    errors: list[BaseException] = []

    @dp.errors()
    async def _capture(event: ErrorEvent) -> Any:
        errors.append(event.exception)
        return UNHANDLED

    d = Driver(dp, bot, session)

    def out(lines: list[str]) -> str:
        return joined(lines, errors)

    await d.text(USER_ID, "/start")
    await d.text(USER_ID, texts.BTN_SKIP_CONTACT)

    # ---------------- ➕ to‘ldirish
    assert "ID raqamini" in out(await d.text(USER_ID, texts.BTN_DEPOSIT))
    assert texts.MC_ID_INVALID in out(await d.text(USER_ID, "12"))
    assert texts.MC_PAYER_NOT_FOUND in out(await d.text(USER_ID, "404404"))
    assert "nick_123456" in out(await d.text(USER_ID, "123 456"))
    created = out(await d.text(USER_ID, "50 000"))
    assert "Aynan shu summani" in created and "8600 1234 5678 1234" in created

    async with sessionmaker() as s:
        deposit = await s.scalar(select(P2PDeposit))
        assert deposit is not None and deposit.status == P2PDepositStatus.PENDING
    # Yakunlanmagan to‘lov bor — qayta bosilsa o‘sha to‘lov ko‘rsatiladi
    assert f"To‘lov #{deposit.id}" in out(await d.text(USER_ID, texts.BTN_DEPOSIT))

    # Userbot bank xabarini o‘qidi → Mob-Cash'ga tushirildi
    async with sessionmaker() as s:
        svc = ctx.services(s)
        match = await svc.p2p.handle_bank_message(
            account_id=None,
            owner_tg_id=1,
            source_chat_id=777,
            source_name="CardXabarBot",
            message_id=1,
            text="➕",
            message_date=utcnow() + timedelta(seconds=5),
            parsed=ParsedTx(amount=deposit.unique_amount, card_last4="1234"),
        )
        assert match is not None and match.deposit is not None
        outcome = await svc.p2p.credit(deposit.id)
        assert outcome is not None
        await svc.notifier.p2p_deposit(outcome)
    assert any("tasdiqlandi" in m for m in session.sent[-2:])
    assert mobcash.deposits == [("123456", deposit.unique_amount)]
    status = out(await d.click(USER_ID, McCb(action="dep_check", id=deposit.id).pack()))
    assert "Hisobga tushirildi" in status

    # ---------------- ➖ yechish (oxirgi ID eslab qolingan)
    assert "123456" in out(await d.text(USER_ID, texts.BTN_WITHDRAW))
    assert "Yechish kodini" in out(await d.click(USER_ID, McCb(action="wd_same").pack()))
    assert "Kartangizga" in out(await d.text(USER_ID, "Secret_abc"))
    assert "Tasdiqlang" in out(await d.text(USER_ID, "8600 1234 1234 9999"))
    sent_before = len(session.sent)
    assert "qabul qilindi" in out(await d.click(USER_ID, McCb(action="wd_confirm").pack()))
    assert any("Yangi yechish" in m for m in session.sent[sent_before:])  # adminga xabar
    assert mobcash.withdrawals == [("123456", "Secret_abc", Decimal("100000.00"))]
    # Tasdiq qayta bosilsa — eskirgan amal, ikkinchi yechish yo‘q
    await d.click(USER_ID, McCb(action="wd_confirm").pack())
    assert len(mobcash.withdrawals) == 1

    async with sessionmaker() as s:
        wd = await s.scalar(select(MobcashWithdrawal))
        assert wd is not None and wd.status == MobcashWithdrawalStatus.AWAITING_PAYOUT

    # ---------------- admin
    assert "Mob-Cash kassa" in out(
        await d.text(ADMIN_ID, "/admin") + await d.text(ADMIN_ID, texts.ADM_MOBCASH)
    )
    paid = out(await d.click(ADMIN_ID, AdmCb(section="mcw", action="paid", id=wd.id).pack()))
    assert "kartangizga o‘tkazildi" in paid
    async with sessionmaker() as s:
        wd = await s.scalar(select(MobcashWithdrawal).execution_options(populate_existing=True))
        assert wd is not None and wd.status == MobcashWithdrawalStatus.PAID

    assert "Userbot" in out(await d.text(ADMIN_ID, texts.ADM_USERBOT))
    await d.click(ADMIN_ID, AdmCb(section="card", action="add").pack())
    added = out(await d.text(ADMIN_ID, "9860 1111 2222 3333 | Ali Valiyev | Humo"))
    assert "*3333 qo‘shildi" in added
    history = out(await d.click(USER_ID, McCb(action="history").pack()))
    assert f"#{deposit.id}" in history and f"#{wd.id}" in history
    assert not errors, errors
