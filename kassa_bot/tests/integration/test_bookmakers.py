"""Bir nechta bukmeker (kantora): har biri alohida Mob-Cash kassa."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from aiogram import Bot
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.types import ErrorEvent
from sqlalchemy import select

from app import texts
from app.bootstrap import AppContext
from app.bot.factory import create_dispatcher
from app.bot.keyboards.callbacks import AdmCb, McCb
from app.core.enums import AdminRole
from app.core.errors import DomainError
from app.core.utils import utcnow
from app.mobcash.client import CashboxInfo
from app.models import Bookmaker, P2PDeposit
from app.p2p.parser import ParsedTx
from app.services import bookmakers as bm_module
from app.services.admins import AdminService
from app.services.mobcash_withdrawals import WithdrawQuote
from tests.integration.helpers import ADMIN, make_user
from tests.integration.test_bot_flows import Driver, FakeSession
from tests.integration.test_mobcash_bot_flow import detach_module_routers, joined
from tests.integration.test_p2p import FakeMobCash, svc_for

pytestmark = pytest.mark.integration


class FakeKassa(FakeMobCash):
    def __init__(self, code: int, login: str, password: str) -> None:
        super().__init__()
        self.cashbox_code = code
        self.login = login
        self.password = password

    async def check_connection(self) -> CashboxInfo:
        if self.password == "wrong":
            from app.mobcash import MobCashError, MobCashErrorKind

            raise MobCashError("login rad etildi", MobCashErrorKind.AUTH)
        return CashboxInfo(str(self.cashbox_code), "UZS", True, True, None)

    async def close(self) -> None:
        return None


@pytest.fixture
def kassalar(monkeypatch) -> dict[int, FakeKassa]:  # type: ignore[no-untyped-def]
    made: dict[int, FakeKassa] = {}

    def make(self, code: int, login: str, password: str) -> FakeKassa:  # type: ignore[no-untyped-def]
        kassa = made.get(code)
        if kassa is None or kassa.password != password:
            kassa = made[code] = FakeKassa(code, login, password)
        return kassa

    monkeypatch.setattr(bm_module.BookmakerService, "_make_client", make)
    monkeypatch.setattr(bm_module, "_CLIENTS", {})
    return made


async def test_bookmaker_routing_and_admin_rules(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config, kassalar
) -> None:
    legacy = FakeMobCash()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, legacy)
        await svc.p2p.add_card("8600 1234 5678 1234", "Kassir", "Uzcard", ADMIN)
        assert await svc.bookmakers.legacy_available()  # kantora yo‘q — eski yagona kassa

        with pytest.raises(DomainError):
            await svc.bookmakers.create("Xato", "1 | a | wrong", ADMIN)
        with pytest.raises(DomainError):
            await svc.bookmakers.create("Format", "faqat-matn", ADMIN)
        xbet = await svc.bookmakers.create("1xBet UZS", "1001 | kassir | p1", ADMIN)
        melbet = await svc.bookmakers.create("Melbet", "2002:kassir2:p:2", ADMIN)  # parolda «:»
        assert kassalar[2002].password == "p:2"
        with pytest.raises(DomainError):  # dublikat
            await svc.bookmakers.create("Yana", "1001 | kassir | p1", ADMIN)
        assert not await svc.bookmakers.legacy_available()
        # parol bazada ochiq turmaydi
        row = await session.scalar(select(Bookmaker).where(Bookmaker.id == xbet.id))
        assert row is not None and "p1" not in row.password_encrypted

        assert [b.name for b in await svc.bookmakers.list_active()] == ["1xBet UZS", "Melbet"]
        await svc.bookmakers.move(melbet.id, -1, ADMIN)
        assert [b.name for b in await svc.bookmakers.list_all()] == ["Melbet", "1xBet UZS"]

        user = await make_user(svc, 7101)
        assert await svc.p2p.check_payer("555", melbet.id) == "nick_555"
        dep = await svc.p2p.create(user, "555", "nick", Decimal("40000"), bookmaker_id=melbet.id)
        assert dep.bookmaker_id == melbet.id
        assert user.payer_id_for(melbet.id) == "555" and user.payer_id_for(xbet.id) is None

        await svc.p2p.handle_bank_message(
            account_id=None,
            owner_tg_id=1,
            source_chat_id=777,
            source_name="CardXabarBot",
            message_id=71,
            text="➕",
            message_date=utcnow() + timedelta(seconds=5),
            parsed=ParsedTx(amount=dep.unique_amount, card_last4=None),
        )
        outcome = await svc.p2p.credit(dep.id)
        assert outcome is not None and outcome.event == "credited"
        # Pul aynan tanlangan kantoraga tushdi
        assert kassalar[2002].deposits == [("555", dep.unique_amount)]
        assert kassalar[1001].deposits == [] and legacy.deposits == []

        # Yechish ham tanlangan kantoradan
        quote = await svc.mcwd.quote("777", "CODE1", xbet.id)
        wd = await svc.mcwd.execute(
            user, "777", "CODE1", quote, "8600111122223333", bookmaker_id=xbet.id
        )
        assert wd.bookmaker_id == xbet.id
        assert kassalar[1001].withdrawals == [("777", "CODE1", quote.amount)]

        # O‘chirilgan kantora — yangi amallar yo‘q
        await svc.bookmakers.toggle(xbet.id, ADMIN)
        with pytest.raises(DomainError):
            await svc.p2p.create(user, "1", "n", Decimal("40000"), bookmaker_id=xbet.id)
        with pytest.raises(DomainError):
            await svc.mcwd.quote("777", "CODE2", xbet.id)
        q = WithdrawQuote(Decimal("100000"), Decimal(0), Decimal("100000"))
        with pytest.raises(DomainError):
            await svc.mcwd.execute(user, "777", "C3", q, "8600111122223333", bookmaker_id=xbet.id)
        # ...lekin eski arizani o‘sha kantora orqali qaytarish mumkin (refund)
        event = await svc.mcwd.refund(wd.id, ADMIN, "test")
        assert event.withdrawal.status.value == "refunded"
        assert kassalar[1001].deposits == [("777", quote.amount)]

        # Tarixi bor kantorani o‘chirib bo‘lmaydi, bo‘shini — mumkin
        with pytest.raises(DomainError):
            await svc.bookmakers.delete(melbet.id, ADMIN)
        empty = await svc.bookmakers.create("Bo‘sh", "3003 | k | p", ADMIN)
        await svc.bookmakers.delete(empty.id, ADMIN)
        assert len(await svc.bookmakers.list_all()) == 2


async def test_bookmaker_bot_flow(sessionmaker, redis, registry, config, kassalar) -> None:  # type: ignore[no-untyped-def]
    config.rate_limit_per_second = 1000
    config.rate_limit_per_minute = 10000
    config.mobcash_enabled = True
    admin_id, user_id = 6100001, 6100002
    session = FakeSession()
    bot = Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=session)
    ctx = AppContext(config, None, sessionmaker, redis, registry, bot, FakeMobCash())  # type: ignore[arg-type]
    async with sessionmaker() as s:
        await AdminService(s).sync_from_env({admin_id: AdminRole.SUPERADMIN})
        svc = ctx.services(s)
        await svc.p2p.add_card("8600123456781234", "Kassir", "Uzcard", ADMIN)
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

    # ---------------- admin: Kantoralar ekrani orqali ikkita kantora qo‘shish
    await d.text(admin_id, "/admin")
    assert "Kantoralar Sozlamalari" in out(await d.text(admin_id, texts.ADM_BOOKMAKERS))
    for name, creds in (("1xBet UZS", "1001 | k1 | p1"), ("Melbet", "2002 | k2 | p2")):
        await d.click(admin_id, AdmCb(section="bm", action="add").pack())
        assert name in out(await d.text(admin_id, name))
        assert "ulandi va saqlandi" in out(await d.text(admin_id, creds))
    listing = out(await d.click(admin_id, AdmCb(section="bm", action="list").pack()))
    assert "1xBet UZS" in listing or "Kantoralar" in listing

    async with sessionmaker() as s:
        boxes = list(await s.scalars(select(Bookmaker).order_by(Bookmaker.id)))
    assert [b.name for b in boxes] == ["1xBet UZS", "Melbet"]
    melbet = boxes[1]

    # ---------------- foydalanuvchi: kantorani tanlab to‘ldirish
    await d.text(user_id, "/start")
    await d.text(user_id, texts.BTN_SKIP_CONTACT)
    assert "Qaysi kantora" in out(await d.text(user_id, texts.BTN_DEPOSIT))
    asked = out(await d.click(user_id, McCb(action="dep_bm", id=melbet.id).pack()))
    assert "Melbet" in asked and "ID raqamini" in asked
    assert "nick_123456" in out(await d.text(user_id, "123456"))
    created = out(await d.text(user_id, "50 000"))
    assert "Melbet" in created and "8600 1234 5678 1234" in created
    async with sessionmaker() as s:
        dep = await s.scalar(select(P2PDeposit))
    assert dep is not None and dep.bookmaker_id == melbet.id

    # ---------------- admin kantorani o‘chirdi — foydalanuvchiga ko‘rinmaydi
    await d.click(admin_id, AdmCb(section="bm", action="toggle", id=melbet.id).pack())
    await d.click(user_id, McCb(action="dep_cancel", id=dep.id).pack())
    single = out(await d.text(user_id, texts.BTN_WITHDRAW))
    assert "1xBet UZS" in single and "Qaysi kantora" not in single  # bitta qoldi — o‘zi tanlandi
    assert not errors, errors
    detach_module_routers()  # keyingi testlar o‘z dispatcherini yaratadi
