"""Dispatcher orqali uchidan-uchigacha: middleware, FSM, menyular va admin bo‘limlari.

Telegram API soxta sessiya bilan almashtirilgan — chiquvchi so‘rovlar yozib olinadi.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    GetChat,
    GetChatMember,
    GetMe,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import ErrorEvent, Update
from sqlalchemy import select

from app import texts
from app.bootstrap import AppContext
from app.bot.factory import create_dispatcher
from app.bot.keyboards.callbacks import AdmCb, BonusCb, CardCb, HistoryCb, MenuCb, WdCb
from app.core.enums import AdminRole, PaymentStatus, WithdrawalStatus
from app.models import (
    JoinRequest,
    Payment,
    PayoutCard,
    PromoCode,
    SystemSetting,
    User,
    VipLevel,
    Wallet,
    Withdrawal,
)
from app.services.admins import AdminService

pytestmark = pytest.mark.integration

ADMIN_ID = 5000001
USER_ID = 5000002


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.sent: list[str] = []
        self.calls: list[str] = []
        self._ids = itertools.count(100)

    async def make_request(  # BaseSession imzosi
        self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None
    ) -> Any:
        if isinstance(method, GetMe):
            return method.__returning__.model_validate(
                {"id": 1, "is_bot": True, "first_name": "Kassa", "username": "kassa_test_bot"}
            )
        if isinstance(method, SendMessage | EditMessageText):
            self.sent.append(method.text)
            return (
                method.__returning__.model_validate(  # type: ignore[union-attr]
                    {
                        "message_id": next(self._ids),
                        "date": 0,
                        "chat": {"id": method.chat_id or 0, "type": "private"},
                        "text": method.text,
                    },
                    context={"bot": bot},
                )
                if isinstance(method, SendMessage)
                else True
            )
        if isinstance(method, AnswerCallbackQuery):
            if method.text:
                self.sent.append(method.text)
            return True
        if isinstance(method, GetChat | GetChatMember):
            raise TelegramBadRequest(method=method, message="Bad Request: chat not found")
        self.calls.append(type(method).__name__)
        return True

    async def close(self) -> None:
        return None

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


class Driver:
    def __init__(self, dp: Any, bot: Bot, session: FakeSession) -> None:
        self.dp, self.bot, self.session = dp, bot, session
        self.ids = itertools.count(1)

    def _user(self, uid: int) -> dict[str, Any]:
        return {"id": uid, "is_bot": False, "first_name": f"U{uid}"}

    async def text(self, uid: int, text: str) -> list[str]:
        start = len(self.session.sent)
        n = next(self.ids)
        update = Update.model_validate(
            {
                "update_id": n,
                "message": {
                    "message_id": n,
                    "date": int(datetime.now(UTC).timestamp()),
                    "chat": {"id": uid, "type": "private"},
                    "from": self._user(uid),
                    "text": text,
                },
            },
            context={"bot": self.bot},
        )
        await self.dp.feed_update(self.bot, update)
        return self.session.sent[start:]

    async def click(self, uid: int, data: str) -> list[str]:
        start = len(self.session.sent)
        n = next(self.ids)
        update = Update.model_validate(
            {
                "update_id": n,
                "callback_query": {
                    "id": str(n),
                    "from": self._user(uid),
                    "chat_instance": "ci",
                    "data": data,
                    "message": {
                        "message_id": n,
                        "date": int(datetime.now(UTC).timestamp()),
                        "chat": {"id": uid, "type": "private"},
                        "text": "x",
                    },
                },
            },
            context={"bot": self.bot},
        )
        await self.dp.feed_update(self.bot, update)
        return self.session.sent[start:]

    async def join_request(self, uid: int, chat_id: int) -> None:
        n = next(self.ids)
        update = Update.model_validate(
            {
                "update_id": n,
                "chat_join_request": {
                    "chat": {"id": chat_id, "type": "channel", "title": "Kassa News"},
                    "from": self._user(uid),
                    "user_chat_id": uid,
                    "date": int(datetime.now(UTC).timestamp()),
                },
            },
            context={"bot": self.bot},
        )
        await self.dp.feed_update(self.bot, update)


ERRORS: list[BaseException] = []


def joined(out: list[str]) -> str:
    assert texts.ERROR_GENERIC not in out, [repr(e) for e in ERRORS]
    return "\n".join(out)


async def test_user_and_admin_flows(sessionmaker, redis, registry, config) -> None:  # type: ignore[no-untyped-def]
    config.rate_limit_per_second = 1000
    config.rate_limit_per_minute = 10000
    fake = FakeSession()
    bot = Bot("123456:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", session=fake)
    ctx = AppContext(config, None, sessionmaker, redis, registry, bot)  # type: ignore[arg-type]
    async with sessionmaker() as s:
        await AdminService(s).sync_from_env({ADMIN_ID: AdminRole.SUPERADMIN})
    dp = create_dispatcher(ctx)
    errors = ERRORS
    errors.clear()

    @dp.errors()
    async def _capture(event: ErrorEvent) -> Any:
        errors.append(event.exception)
        return UNHANDLED

    d = Driver(dp, bot, fake)

    # ---------------- foydalanuvchi
    assert texts.CONTACT_PROMPT_OPTIONAL in joined(await d.text(USER_ID, "/start"))
    assert "xush kelibsiz" in joined(await d.text(USER_ID, texts.BTN_SKIP_CONTACT))
    assert "Hamyon" in joined(await d.text(USER_ID, texts.BTN_WALLET))
    assert "Summani" in joined(await d.text(USER_ID, texts.BTN_DEPOSIT))
    assert "dan" in joined(await d.text(USER_ID, "5"))  # limitdan past
    # FSM holatida menyu tugmasi bosilsa summa sifatida qabul qilinmaydi
    assert "Bonus" in joined(await d.text(USER_ID, texts.BTN_BONUS))
    await d.text(USER_ID, texts.BTN_DEPOSIT)
    assert "To‘lov #" in joined(await d.text(USER_ID, "50 000"))
    async with sessionmaker() as s:
        payment = await s.scalar(select(Payment))
        assert payment is not None and payment.status == PaymentStatus.PENDING

    assert "Referal" in joined(await d.click(USER_ID, BonusCb(action="ref").pack()))
    assert "TOP10" in joined(await d.click(USER_ID, BonusCb(action="top").pack()))
    assert "VIP" in joined(await d.click(USER_ID, BonusCb(action="vip").pack()))
    assert "Tranzaksiyalar" in joined(
        await d.click(USER_ID, HistoryCb(kind="dep", status="pending").pack())
    )
    assert "Pul chiqarish" in joined(await d.click(USER_ID, MenuCb(action="withdraw").pack()))
    joined(await d.text(USER_ID, texts.BTN_SUPPORT))
    joined(await d.text(USER_ID, texts.BTN_CASHBOX))
    # Oddiy foydalanuvchi uchun admin panel yo‘q
    assert texts.UNKNOWN in await d.text(USER_ID, "/admin")
    assert texts.UNKNOWN in await d.text(USER_ID, texts.ADM_STATS)

    # ---------------- admin
    assert "Admin panel" in joined(await d.text(ADMIN_ID, "/admin"))
    for section in (
        texts.ADM_STATS,
        texts.ADM_USERS,
        texts.ADM_SETTINGS,
        texts.ADM_MASS,
        texts.ADM_AUTO,
        texts.ADM_MANUAL,
        texts.ADM_JOIN,
        texts.ADM_BONUS,
        texts.ADM_CHANNELS,
    ):
        out = joined(await d.text(ADMIN_ID, section))
        assert out and texts.ADMIN_NO_PERM not in out, section

    for data in (
        AdmCb(section="st", action="period", arg="week"),
        AdmCb(section="st", action="audit"),
        AdmCb(section="mp", action="list"),
        AdmCb(section="ap", action="view"),
        AdmCb(section="wd", action="list", arg="pending"),
        AdmCb(section="jr", action="list", arg="pending.0"),
        AdmCb(section="pr", action="list"),
        AdmCb(section="vp", action="list"),
        AdmCb(section="ch", action="list"),
        AdmCb(section="ad", action="list"),
        AdmCb(section="dash", action="refresh"),
    ):
        joined(await d.click(ADMIN_ID, data.pack()))

    # Foydalanuvchi qidiruvi va kartochkasi
    await d.click(ADMIN_ID, AdmCb(section="u", action="search").pack())
    assert "Foydalanuvchi #" in joined(await d.text(ADMIN_ID, str(USER_ID)))

    # Sozlama: ikki bosqichli tasdiq
    await d.click(ADMIN_ID, AdmCb(section="s", action="edit", arg="deposit_min").pack())
    assert "preview" in joined(await d.text(ADMIN_ID, "20000"))
    assert "Yakuniy tasdiq" in joined(
        await d.click(ADMIN_ID, AdmCb(section="s", action="step2", arg="deposit_min").pack())
    )
    joined(await d.click(ADMIN_ID, AdmCb(section="s", action="apply", arg="deposit_min").pack()))
    async with sessionmaker() as s:
        row = await s.get(SystemSetting, "deposit_min")
        assert row is not None and row.value == "20000.00"

    # Operator bo‘lmagan auditor sozlamani o‘zgartira olmaydi
    async with sessionmaker() as s:
        await AdminService(s).sync_from_env(
            {ADMIN_ID: AdminRole.SUPERADMIN, 5000003: AdminRole.AUDITOR}
        )
    out = await d.click(5000003, AdmCb(section="s", action="edit", arg="deposit_min").pack())
    assert texts.ADMIN_NO_PERM in out

    # ---------------- ma’lumotli admin oqimlari
    async with sessionmaker() as s:
        user = await s.scalar(select(User).where(User.telegram_id == USER_ID))
        assert user is not None
        uid = user.id
        s.add(
            PayoutCard(
                user_id=uid,
                provider="sandbox",
                token="sbx_tok_e2e",
                masked_pan="8600 **** **** 0001",
            )
        )
        await s.commit()
        card_id = await s.scalar(select(PayoutCard.id))

    # Balans krediti: summa → sabab → tasdiq
    await d.click(ADMIN_ID, AdmCb(section="u", action="bal", id=uid, arg="credit").pack())
    await d.text(ADMIN_ID, "100000")
    assert "Tasdiqlang" in joined(await d.text(ADMIN_ID, "e2e test krediti"))
    joined(await d.click(ADMIN_ID, AdmCb(section="u", action="bal_do", id=uid).pack()))
    async with sessionmaker() as s:
        wallet = await s.scalar(select(Wallet).where(Wallet.user_id == uid))
        assert wallet is not None and wallet.available == Decimal("100000")

    # Foydalanuvchi pul chiqaradi
    joined(await d.click(USER_ID, CardCb(action="pick", id=card_id).pack()))  # type: ignore[arg-type]
    assert "tasdiqlang" in joined(await d.text(USER_ID, "30000"))
    assert "qabul qilindi" in joined(await d.click(USER_ID, WdCb(action="confirm").pack()))
    async with sessionmaker() as s:
        wd = await s.scalar(select(Withdrawal))
        assert wd is not None and wd.status == WithdrawalStatus.PENDING
        wd_id = wd.id

    # Operator tasdiqlaydi (izoh majburiy)
    assert "Ariza #" in joined(
        await d.click(ADMIN_ID, AdmCb(section="wd", action="view", id=wd_id).pack())
    )
    await d.click(ADMIN_ID, AdmCb(section="wd", action="act", id=wd_id, arg="approve").pack())
    joined(await d.text(ADMIN_ID, "e2e tekshirildi"))
    joined(await d.click(ADMIN_ID, AdmCb(section="wd", action="do", id=wd_id).pack()))
    async with sessionmaker() as s:
        wd = await s.get(Withdrawal, wd_id)
        assert wd is not None and wd.status == WithdrawalStatus.APPROVED
    assert any("Tasdiqlangan" in t for t in fake.sent)  # foydalanuvchiga bildirishnoma

    # Promokod va VIP yaratish
    await d.click(ADMIN_ID, AdmCb(section="pr", action="new").pack())
    assert "Preview" in joined(await d.text(ADMIN_ID, "E2E | fixed | 1000 | 0 | 10 | 1 | - | -"))
    joined(await d.click(ADMIN_ID, AdmCb(section="pr", action="save").pack()))
    await d.click(ADMIN_ID, AdmCb(section="vp", action="new").pack())
    assert "Saqlandi" in joined(await d.text(ADMIN_ID, "Diamond | 50000000 | 2 | 9"))
    async with sessionmaker() as s:
        assert await s.scalar(select(PromoCode.code)) == "E2E"
        assert await s.scalar(select(VipLevel.name)) == "Diamond"

    # Foydalanuvchi promokodni ishlatadi
    await d.click(USER_ID, BonusCb(action="promo").pack())
    assert "+1 000" in joined(await d.text(USER_ID, "e2e"))

    # Kanal qo‘shish (bot admin emas — ogohlantirish)
    await d.click(ADMIN_ID, AdmCb(section="ch", action="add").pack())
    assert "admin emas" in joined(await d.text(ADMIN_ID, "@kassa_news | Kassa yangiliklari"))

    # Join request → admin qabul qiladi
    await d.join_request(USER_ID, -1001234567890)
    async with sessionmaker() as s:
        jr = await s.scalar(select(JoinRequest))
        assert jr is not None
        jr_id = jr.id
    joined(await d.click(ADMIN_ID, AdmCb(section="jr", action="view", id=jr_id).pack()))
    joined(await d.click(ADMIN_ID, AdmCb(section="jr", action="decide", id=jr_id, arg="1").pack()))
    assert "ApproveChatJoinRequest" in fake.calls

    # Ban → foydalanuvchi bloklanadi, unban → qaytadi
    await d.click(ADMIN_ID, AdmCb(section="u", action="ban", id=uid).pack())
    await d.text(ADMIN_ID, "e2e qoidabuzarlik")
    joined(await d.click(ADMIN_ID, AdmCb(section="u", action="ban_do", id=uid).pack()))
    assert texts.BANNED in await d.text(USER_ID, texts.BTN_WALLET)
    joined(await d.click(ADMIN_ID, AdmCb(section="u", action="unban_do", id=uid).pack()))
    assert "Hamyon" in joined(await d.text(USER_ID, texts.BTN_WALLET))

    assert not ERRORS, [repr(e) for e in ERRORS]
