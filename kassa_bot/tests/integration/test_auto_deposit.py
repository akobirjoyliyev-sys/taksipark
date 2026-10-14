"""🤖 Avto to‘lov: ID ro‘yxatiga kassadan ommaviy depozit (servis, worker va admin oqimi)."""

from __future__ import annotations

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
from app.bot.keyboards.callbacks import AdmCb
from app.core.enums import AdminRole, AutoBatchStatus, AutoItemStatus
from app.core.errors import DomainError
from app.jobs import tasks
from app.mobcash import MobCashError, MobCashErrorKind
from app.models import AutoDepositBatch, AutoDepositItem
from app.services.admins import AdminService
from app.services.auto_deposit import AUTO_PAUSE_ERRORS, parse_ids
from app.services.container import Services
from tests.integration.helpers import ADMIN
from tests.integration.test_bot_flows import Driver, FakeSession
from tests.integration.test_mobcash_bot_flow import detach_module_routers, joined
from tests.integration.test_p2p import FakeMobCash, svc_for

pytestmark = pytest.mark.integration

ADMIN_ID = 7000001


class FakeKassa(FakeMobCash):
    """Balans va ID bo‘yicha xatolarni sozlash mumkin bo‘lgan soxta kassa."""

    def __init__(self) -> None:
        super().__init__()
        self.nick_calls: list[str] = []
        self.errors_for: dict[str, list[MobCashError]] = {}
        self.cash = Decimal("1000000")

    async def payer_nickname(self, payer_id: str) -> str:
        self.nick_calls.append(payer_id)
        return await super().payer_nickname(payer_id)

    async def deposit(self, payer_id: str, amount: Decimal) -> dict[str, Any]:
        queue = self.errors_for.get(payer_id)
        if queue:
            raise queue.pop(0)
        if amount > self.cash:
            raise MobCashError("Депозит: Недостаточно средств", MobCashErrorKind.REJECTED)
        self.cash -= amount
        return await super().deposit(payer_id, amount)

    async def balance(self) -> tuple[Decimal, Decimal]:
        return self.cash, Decimal(0)


async def _draft(svc: Services, text: str, amount: str | None = "10000") -> AutoDepositBatch:
    return await svc.auto.create_draft(
        bookmaker_id=None,
        parsed=parse_ids(text),
        default_amount=Decimal(amount) if amount else None,
        actor=ADMIN,
    )


async def _items(svc: Services, batch_id: int) -> dict[str, AutoDepositItem]:
    rows = await svc.session.scalars(
        select(AutoDepositItem)
        .where(AutoDepositItem.batch_id == batch_id)
        .execution_options(populate_existing=True)
    )
    return {it.payer_id: it for it in rows}


async def test_full_batch_is_processed_automatically(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config
) -> None:
    kassa = FakeKassa()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, kassa)
        assert await svc.auto.kassa_choices() == [(None, "Mob-Cash kassa")]
        ids = "\n".join(str(100000000 + i) for i in range(30))
        batch = await _draft(svc, ids + "\n404404\n555555555 - 25000")
        assert batch.total_count == 32
        assert batch.total_amount == Decimal(31 * 10000 + 25000)

        pv = await svc.auto.preview(batch)
        assert pv.balance == Decimal("1000000")
        assert pv.recent_ids == 0
        assert not kassa.deposits  # preview pul yubormaydi

        await svc.auto.start(batch.id, ADMIN, chat_id=1, message_id=2)
        with pytest.raises(DomainError):
            await svc.auto.start(batch.id, ADMIN, chat_id=1, message_id=2)

        progress: list[str] = []

        async def on_progress(event: Any) -> None:
            progress.append(event.kind)

        events = await svc.auto.run_step(delay=0, on_progress=on_progress, progress_every=0)
        assert [e.kind for e in events] == ["finished"]
        assert progress  # jonli progress chaqirilgan

        st = await svc.auto.stats(batch.id)
        assert (st.success, st.failed, st.review, st.pending) == (31, 1, 0, 0)
        assert st.success_amount == Decimal(30 * 10000 + 25000)
        assert ("555555555", Decimal("25000")) in kassa.deposits
        assert len(kassa.deposits) == 31
        items = await _items(svc, batch.id)
        assert items["404404"].status == AutoItemStatus.FAILED
        assert "Akkaunt topilmadi" in (items["404404"].error or "")
        assert items["100000000"].nickname == "nick_100000000"

        batch = await svc.auto.get(batch.id)
        assert batch.status == AutoBatchStatus.COMPLETED
        report = (await svc.auto.report_csv(batch.id)).decode("utf-8-sig")
        assert "555555555,25000.00,success" in report

        # Ikkinchi partiya — so‘nggi 24 soatda pul olganlar ogohlantiriladi.
        second = await _draft(svc, "100000000\n100000001\n999999999")
        assert (await svc.auto.preview(second)).recent_ids == 2
        assert await svc.auto.list_page(0) == [batch]  # qoralama tarixda ko‘rinmaydi

        # Hech narsa qolmagan — keyingi qadam bo‘sh.
        assert await svc.auto.run_step(delay=0) == []


async def test_errors_review_retry_and_limits(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config
) -> None:
    kassa = FakeKassa()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, kassa)
        with pytest.raises(DomainError):
            await _draft(svc, "123456789", amount="99999999")  # deposit_max dan katta
        with pytest.raises(DomainError):
            await _draft(svc, "123456789", amount=None)  # summa yo‘q
        with pytest.raises(DomainError):
            await _draft(svc, "salom")

        kassa.errors_for = {
            # natija noma’lum — qayta yuborilmaydi
            "111111111": [MobCashError("timeout", MobCashErrorKind.UNKNOWN)],
            # tarmoq — qayta urinib, keyin muvaffaqiyat
            "222222222": [MobCashError("conn reset", MobCashErrorKind.NETWORK)],
            # 3 marta tarmoq xatosi — bajarilmadi
            "333333333": [MobCashError("down", MobCashErrorKind.NETWORK)] * 3,
            # kassa rad etdi
            "444444444": [MobCashError("Игрок заблокирован", MobCashErrorKind.REJECTED)],
        }
        batch = await _draft(svc, "111111111 222222222 333333333 444444444 555555555")
        await svc.auto.start(batch.id, ADMIN, None, None)
        await svc.auto.run_step(delay=0)
        items = await _items(svc, batch.id)
        assert items["111111111"].status == AutoItemStatus.REVIEW
        assert items["222222222"].status == AutoItemStatus.SUCCESS
        assert items["333333333"].status == AutoItemStatus.FAILED
        assert items["333333333"].attempts == 3
        assert items["444444444"].status == AutoItemStatus.FAILED
        assert items["555555555"].status == AutoItemStatus.SUCCESS
        assert [p for p, _ in kassa.deposits].count("111111111") == 0
        assert (await svc.auto.get(batch.id)).status == AutoBatchStatus.COMPLETED

        # Tekshiruv: admin panelda ko‘rdi — tushgan.
        await svc.auto.resolve_review(items["111111111"].id, True, ADMIN)
        with pytest.raises(DomainError):
            await svc.auto.resolve_review(items["111111111"].id, False, ADMIN)

        # Xatolarni qayta yuborish — faqat FAILED lar, REVIEW/SUCCESS emas.
        assert await svc.auto.retry_failed(batch.id, ADMIN) == 2
        await svc.auto.run_step(delay=0)
        items = await _items(svc, batch.id)
        assert items["333333333"].status == AutoItemStatus.SUCCESS
        assert items["444444444"].status == AutoItemStatus.SUCCESS
        st = await svc.auto.stats(batch.id)
        assert (st.success, st.failed, st.review) == (5, 0, 0)
        with pytest.raises(DomainError):
            await svc.auto.retry_failed(batch.id, ADMIN)


async def test_low_balance_pauses_and_resume_continues(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config
) -> None:
    kassa = FakeKassa()
    kassa.cash = Decimal("25000")
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, kassa)
        batch = await _draft(svc, "111111111 222222222 333333333 444444444")
        await svc.auto.start(batch.id, ADMIN, None, None)
        events = await svc.auto.run_step(delay=0)
        assert [e.kind for e in events] == ["paused"]
        batch = await svc.auto.get(batch.id)
        assert batch.status == AutoBatchStatus.PAUSED
        assert "yetarli emas" in (batch.pause_reason or "")
        st = await svc.auto.stats(batch.id)
        assert (st.success, st.pending, st.failed) == (2, 2, 0)

        # Pauzada worker hech narsa qilmaydi.
        assert await svc.auto.run_step(delay=0) == []

        kassa.cash = Decimal("1000000")  # kassa to‘ldirildi
        await svc.auto.resume(batch.id, ADMIN)
        events = await svc.auto.run_step(delay=0)
        assert [e.kind for e in events] == ["finished"]
        assert len(kassa.deposits) == 4


async def test_cancel_stale_and_auto_pause(  # type: ignore[no-untyped-def]
    sessionmaker, redis, registry, config
) -> None:
    kassa = FakeKassa()
    async with sessionmaker() as session:
        svc = svc_for(session, redis, registry, config, kassa)

        # Jarayon uzilib «processing» qolgan ID — tekshiruvga, qayta yuborilmaydi.
        batch = await _draft(svc, "111111111 222222222")
        await svc.auto.start(batch.id, ADMIN, None, None)
        items = await _items(svc, batch.id)
        items["111111111"].status = AutoItemStatus.PROCESSING
        await session.commit()
        await svc.auto.run_step(delay=0)
        items = await _items(svc, batch.id)
        assert items["111111111"].status == AutoItemStatus.REVIEW
        assert items["222222222"].status == AutoItemStatus.SUCCESS
        assert [p for p, _ in kassa.deposits] == ["222222222"]

        # To‘xtatish: navbatdagilar o‘tkazib yuboriladi.
        batch = await _draft(svc, "333333333 444444444")
        await svc.auto.start(batch.id, ADMIN, None, None)
        await svc.auto.pause(batch.id, ADMIN)
        await svc.auto.cancel(batch.id, ADMIN)
        st = await svc.auto.stats(batch.id)
        assert (st.skipped, st.success) == (2, 0)
        with pytest.raises(DomainError):
            await svc.auto.resume(batch.id, ADMIN)

        # Ketma-ket xatolar — avtomatik pauza.
        ids = [str(500000000 + i) for i in range(AUTO_PAUSE_ERRORS + 3)]
        kassa.errors_for = {
            i: [MobCashError("Ошибка кассы", MobCashErrorKind.REJECTED)] for i in ids
        }
        batch = await _draft(svc, " ".join(ids))
        await svc.auto.start(batch.id, ADMIN, None, None)
        events = await svc.auto.run_step(delay=0)
        assert [e.kind for e in events] == ["paused"]
        st = await svc.auto.stats(batch.id)
        assert st.failed == AUTO_PAUSE_ERRORS
        assert st.pending == 3


async def test_admin_bot_flow_and_worker(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    config.rate_limit_per_second = 1000
    config.rate_limit_per_minute = 10000
    config.mobcash_enabled = True
    config.auto_deposit_delay_ms = 0
    tg = FakeSession()
    bot = Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=tg)
    kassa = FakeKassa()
    ctx = AppContext(config, None, sessionmaker, redis, registry, bot, kassa)  # type: ignore[arg-type]
    async with sessionmaker() as s:
        await AdminService(s).sync_from_env({ADMIN_ID: AdminRole.SUPERADMIN})
    detach_module_routers()
    dp = create_dispatcher(ctx)
    errors: list[BaseException] = []

    @dp.errors()
    async def _capture(event: ErrorEvent) -> Any:
        errors.append(event.exception)
        return UNHANDLED

    d = Driver(dp, bot, tg)

    def out(lines: list[str]) -> str:
        return joined(lines, errors)

    def cb(action: str, id: int = 0) -> str:
        return AdmCb(section="au", action=action, id=id).pack()

    await d.text(ADMIN_ID, "/admin")
    assert "AVTO TO‘LOV MARKAZI" in out(await d.text(ADMIN_ID, texts.ADM_AUTO))
    assert "ID larni yuboring" in out(await d.click(ADMIN_ID, cb("new")))

    # 300 ta ID ikki xabarda + takroriy
    first = "\n".join(str(300000000 + i) for i in range(200))
    second = "\n".join(str(300000000 + i) for i in range(195, 300))
    assert "Jami: <b>200</b>" in out(await d.text(ADMIN_ID, first))
    reply = out(await d.text(ADMIN_ID, second))
    assert "Jami: <b>300</b>" in reply
    assert "Takroriylar olib tashlandi: <b>5</b>" in reply

    assert "qanchadan" in out(await d.click(ADMIN_ID, cb("next")))
    assert "noto‘g‘ri" in out(await d.text(ADMIN_ID, "abc"))
    preview = out(await d.text(ADMIN_ID, "2k"))
    assert "TEKSHIRUV" in preview
    assert "300 ta" in preview
    assert "600 000 so‘m" in preview  # 300 × 2 000
    assert "✅ yetadi" in preview

    async with sessionmaker() as s:
        batch = (await s.scalars(select(AutoDepositBatch))).one()
    assert batch.status == AutoBatchStatus.DRAFT
    assert not kassa.deposits

    assert "TASDIQLANG" in out(await d.click(ADMIN_ID, cb("start", batch.id)))
    started = out(await d.click(ADMIN_ID, cb("go", batch.id)))
    assert "Ishlayapti" in started
    assert not errors

    # Worker vazifasi hammasini o‘zi o‘tkazadi va xabarni yangilaydi.
    while True:
        await tasks.auto_deposits(ctx)
        async with sessionmaker() as s:
            status = (await s.get(AutoDepositBatch, batch.id)).status  # type: ignore[union-attr]
        if status != AutoBatchStatus.RUNNING:
            break
    assert status == AutoBatchStatus.COMPLETED
    assert len(kassa.deposits) == 300
    assert all(amount == Decimal("2000") for _, amount in kassa.deposits)
    assert "SendDocument" in tg.calls  # yakuniy CSV hisobot
    assert any("Yakunlandi" in m for m in tg.sent)

    view = out(await d.click(ADMIN_ID, cb("view", batch.id)))
    assert "100%" in view
    assert "O‘tkazildi: <b>300</b>" in view
    assert "Avto to‘lov tarixi" in out(await d.click(ADMIN_ID, cb("list")))
    assert "Karta payout" in out(await d.click(ADMIN_ID, AdmCb(section="ap", action="view").pack()))
    assert "300 ID" in out(await d.text(ADMIN_ID, "/admin"))
    assert not errors
