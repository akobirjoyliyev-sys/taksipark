"""Boshlang‘ich va demo ma’lumotlar: `python -m app.seed [--demo]`.

Idempotent — qayta ishga tushirilsa dublikat yaratmaydi.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select

from app.config import get_config
from app.core.enums import LedgerAccount, LedgerDirection, LedgerReason, PromoType
from app.core.logging import setup_logging
from app.db import create_engine, create_sessionmaker
from app.models import PayoutCard, PromoCode, User, VipLevel, Wallet
from app.services.admins import AdminService
from app.services.ledger import LedgerService

log = logging.getLogger("app.seed")

VIP_LEVELS = (
    ("Bronze", Decimal("0"), Decimal("0"), 1),
    ("Silver", Decimal("1000000"), Decimal("0.5"), 2),
    ("Gold", Decimal("5000000"), Decimal("1"), 3),
    ("Platinum", Decimal("20000000"), Decimal("1.5"), 4),
)
PROMOS = (
    {
        "code": "WELCOME",
        "bonus_type": PromoType.FIXED,
        "bonus_value": Decimal("5000"),
        "min_deposit": Decimal("0"),
        "total_limit": 1000,
        "per_user_limit": 1,
    },
    {
        "code": "BONUS10",
        "bonus_type": PromoType.PERCENT,
        "bonus_value": Decimal("10"),
        "min_deposit": Decimal("50000"),
        "total_limit": None,
        "per_user_limit": 1,
        "max_bonus": Decimal("50000"),
    },
)
DEMO_USERS = (
    (900000001, "Demo", "demo_user"),
    (900000002, "Test", "test_user"),
)


async def seed(demo: bool) -> None:
    config = get_config()
    engine = create_engine(config.database_url)
    sessionmaker = create_sessionmaker(engine)
    async with sessionmaker() as session:
        await AdminService(session).sync_from_env(config.admin_roles)

        existing_vip = {v.name for v in await session.scalars(select(VipLevel))}
        for name, min_total, percent, order in VIP_LEVELS:
            if name not in existing_vip:
                session.add(
                    VipLevel(
                        name=name,
                        min_total_deposit=min_total,
                        bonus_percent=percent,
                        sort_order=order,
                    )
                )
        existing_promo = {p.code for p in await session.scalars(select(PromoCode))}
        for data in PROMOS:
            if data["code"] not in existing_promo:
                session.add(PromoCode(**data))
        await session.commit()

        if demo:
            ledger = LedgerService(session)
            for tg_id, name, username in DEMO_USERS:
                user = await session.scalar(select(User).where(User.telegram_id == tg_id))
                if user is None:
                    user = User(
                        telegram_id=tg_id, first_name=name, username=username, onboarding_done=True
                    )
                    session.add(user)
                    await session.flush()
                    wallet = Wallet(user_id=user.id)
                    session.add(wallet)
                    await session.flush()
                    await ledger.post(
                        wallet=wallet,
                        account=LedgerAccount.MAIN,
                        direction=LedgerDirection.CREDIT,
                        amount=Decimal("250000"),
                        reason=LedgerReason.MANUAL_CREDIT,
                        idempotency_key=f"seed:demo:{tg_id}",
                        reference_type="seed",
                        comment="Demo balans (sandbox)",
                    )
                    session.add(
                        PayoutCard(
                            user_id=user.id,
                            provider="sandbox",
                            token=f"sbx_tok_demo_{tg_id}",
                            masked_pan="8600 **** **** 0001",
                        )
                    )
            await session.commit()
    await engine.dispose()
    log.info("Seed tugadi (demo=%s)", demo)


def main() -> None:
    parser = argparse.ArgumentParser(description="Kassa seed")
    parser.add_argument("--demo", action="store_true", help="demo foydalanuvchilarni qo‘shish")
    args = parser.parse_args()
    config = get_config()
    setup_logging(config.log_level, config.log_json)
    asyncio.run(seed(args.demo))


if __name__ == "__main__":
    main()
