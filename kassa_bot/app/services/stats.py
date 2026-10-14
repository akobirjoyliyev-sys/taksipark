from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    AdminRole,
    LedgerDirection,
    LedgerReason,
    MobcashWithdrawalStatus,
    P2PDepositStatus,
    PaymentStatus,
    WithdrawalStatus,
)
from app.core.errors import DomainError
from app.core.utils import get_tz, utcnow
from app.models import LedgerEntry, MobcashWithdrawal, P2PDeposit, Payment, User, Withdrawal
from app.payments.registry import ProviderRegistry
from app.repositories.admins import AdminRepository
from app.repositories.payments import CardRepository, PaymentRepository
from app.repositories.users import UserRepository
from app.repositories.withdrawals import WithdrawalRepository
from app.services.provider_health import ProviderHealthService
from app.services.settings import RuntimeSettings


def period_bounds(
    kind: str, tz_name: str, now: datetime | None = None
) -> tuple[datetime, datetime]:
    tz = get_tz(tz_name)
    now = (now or utcnow()).astimezone(tz)
    today = datetime.combine(now.date(), time.min, tzinfo=tz)
    days = {"day": 0, "week": 6, "month": 29}.get(kind)
    if days is None:
        raise ValueError(kind)
    return (today - timedelta(days=days)).astimezone(UTC), now.astimezone(UTC)


def parse_range(text: str, tz_name: str) -> tuple[datetime, datetime]:
    """`2026-10-01 2026-10-06` — ikkala kun ham kiradi."""
    parts = text.replace("—", " ").split()
    if len(parts) != 2:
        raise DomainError("Format: <code>YYYY-MM-DD YYYY-MM-DD</code>")
    try:
        start_d = date.fromisoformat(parts[0])
        end_d = date.fromisoformat(parts[1])
    except ValueError as exc:
        raise DomainError("Sana noto‘g‘ri. Format: <code>YYYY-MM-DD YYYY-MM-DD</code>") from exc
    if end_d < start_d:
        raise DomainError("Oxirgi sana boshlang‘ichdan oldin bo‘lmasin.")
    if (end_d - start_d).days > 366:
        raise DomainError("Oraliq 1 yildan oshmasin.")
    tz = get_tz(tz_name)
    start = datetime.combine(start_d, time.min, tzinfo=tz)
    end = datetime.combine(end_d + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


@dataclass(slots=True)
class Agg:
    count: int = 0
    amount: Decimal = Decimal(0)


@dataclass(slots=True)
class PeriodReport:
    start: datetime
    end: datetime
    deposits_paid: Agg
    deposit_status: dict[str, Agg]
    withdrawals_paid: Agg
    withdrawal_status: dict[str, Agg]
    bonuses: Decimal
    new_users: int
    total_users: int
    growth: list[tuple[date, int]] = field(default_factory=list)
    # Mob-Cash rejimi: P2P depozitlar (o‘yin hisobi + hamyon) va o‘yin hisobidan yechishlar
    p2p_credited: Agg = field(default_factory=lambda: Agg(0, Decimal(0)))
    mcwd_paid: Agg = field(default_factory=lambda: Agg(0, Decimal(0)))


@dataclass(slots=True)
class Dashboard:
    total_users: int
    contact_verified: int
    active_providers: list[tuple[str, bool]]
    active_cards: int
    active_operators: int
    active_admins: int
    pending_payments: int
    pending_withdrawals: int
    queued_withdrawals: int
    manual_withdrawals: int


class StatsService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _status_aggs(
        self, model: type[Payment] | type[Withdrawal], start: datetime, end: datetime
    ) -> dict[str, Agg]:
        stmt = (
            select(model.status, func.count(model.id), func.coalesce(func.sum(model.amount), 0))
            .where(model.created_at >= start, model.created_at < end)
            .group_by(model.status)
        )
        return {
            str(r[0].value if hasattr(r[0], "value") else r[0]): Agg(int(r[1]), Decimal(r[2]))
            for r in await self.session.execute(stmt)
        }

    async def period_report(self, start: datetime, end: datetime, tz_name: str) -> PeriodReport:
        dep_paid = (
            await self.session.execute(
                select(func.count(Payment.id), func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.status == PaymentStatus.PAID,
                    Payment.paid_at >= start,
                    Payment.paid_at < end,
                )
            )
        ).one()
        wd_paid = (
            await self.session.execute(
                select(
                    func.count(Withdrawal.id), func.coalesce(func.sum(Withdrawal.amount), 0)
                ).where(
                    Withdrawal.status == WithdrawalStatus.PAID,
                    Withdrawal.paid_at >= start,
                    Withdrawal.paid_at < end,
                )
            )
        ).one()
        bonuses = await self.session.scalar(
            select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
                LedgerEntry.reason.in_(
                    (LedgerReason.PROMO_BONUS, LedgerReason.VIP_BONUS, LedgerReason.REFERRAL_BONUS)
                ),
                LedgerEntry.direction == LedgerDirection.CREDIT,
                LedgerEntry.created_at >= start,
                LedgerEntry.created_at < end,
            )
        )
        # Soatlik guruhlab, mahalliy kunga Pythonda o‘tkazamiz — DB serverdagi tz bazasiga
        # bog‘liq bo‘lmaslik uchun.
        hour = func.date_trunc("hour", User.created_at)
        hourly = await self.session.execute(
            select(hour, func.count(User.id))
            .where(User.created_at >= start, User.created_at < end)
            .group_by(hour)
        )
        tz = get_tz(tz_name)
        by_day: dict[date, int] = {}
        for bucket, count in hourly:
            day = bucket.astimezone(tz).date()
            by_day[day] = by_day.get(day, 0) + int(count)
        p2p = (
            await self.session.execute(
                select(
                    func.count(P2PDeposit.id),
                    func.coalesce(func.sum(P2PDeposit.credit_amount), 0),
                ).where(
                    P2PDeposit.status == P2PDepositStatus.CREDITED,
                    P2PDeposit.credited_at >= start,
                    P2PDeposit.credited_at < end,
                )
            )
        ).one()
        mcwd = (
            await self.session.execute(
                select(
                    func.count(MobcashWithdrawal.id),
                    func.coalesce(func.sum(MobcashWithdrawal.payout_amount), 0),
                ).where(
                    MobcashWithdrawal.status == MobcashWithdrawalStatus.PAID,
                    MobcashWithdrawal.paid_at >= start,
                    MobcashWithdrawal.paid_at < end,
                )
            )
        ).one()
        users = UserRepository(self.session)
        return PeriodReport(
            p2p_credited=Agg(int(p2p[0]), Decimal(p2p[1])),
            mcwd_paid=Agg(int(mcwd[0]), Decimal(mcwd[1])),
            start=start,
            end=end,
            deposits_paid=Agg(int(dep_paid[0]), Decimal(dep_paid[1])),
            deposit_status=await self._status_aggs(Payment, start, end),
            withdrawals_paid=Agg(int(wd_paid[0]), Decimal(wd_paid[1])),
            withdrawal_status=await self._status_aggs(Withdrawal, start, end),
            bonuses=Decimal(bonuses or 0),
            new_users=await users.count_created_between(start, end),
            total_users=await users.count(),
            growth=sorted(by_day.items()),
        )

    async def dashboard(
        self, providers: ProviderRegistry, health: ProviderHealthService, s: RuntimeSettings
    ) -> Dashboard:
        users = UserRepository(self.session)
        admins = AdminRepository(self.session)
        wds = WithdrawalRepository(self.session)
        provider_rows = []
        for provider in providers.enabled(s.enabled_providers):
            provider_rows.append((provider.title, await health.is_available(provider.code)))
        queued = await wds.count_by_status(WithdrawalStatus.APPROVED) + await wds.count_by_status(
            WithdrawalStatus.PROCESSING
        )
        return Dashboard(
            total_users=await users.count(),
            contact_verified=await users.count_contact_verified(),
            active_providers=provider_rows,
            active_cards=await CardRepository(self.session).count_active(),
            active_operators=await admins.count_active(AdminRole.OPERATOR),
            active_admins=len(await admins.list_active()),
            pending_payments=await PaymentRepository(self.session).count_by_status(
                PaymentStatus.PENDING
            ),
            pending_withdrawals=await wds.count_by_status(WithdrawalStatus.PENDING),
            queued_withdrawals=queued,
            manual_withdrawals=await wds.count_manual_pending(),
        )

    async def export_csv(self, start: datetime, end: datetime, tz_name: str) -> bytes:
        tz = get_tz(tz_name)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "type",
                "id",
                "user_telegram_id",
                "amount",
                "fee",
                "net",
                "status",
                "provider",
                "created_at",
                "completed_at",
                "is_test",
            ]
        )
        payments = await self.session.execute(
            select(Payment, User.telegram_id)
            .join(User, User.id == Payment.user_id)
            .where(Payment.created_at >= start, Payment.created_at < end)
            .order_by(Payment.id)
        )
        for p, tg in payments:
            writer.writerow(
                [
                    "deposit",
                    p.id,
                    tg,
                    p.amount,
                    p.fee,
                    p.credited_amount,
                    p.status.value,
                    p.provider,
                    p.created_at.astimezone(tz).isoformat(),
                    p.paid_at.astimezone(tz).isoformat() if p.paid_at else "",
                    p.is_test,
                ]
            )
        withdrawals = await self.session.execute(
            select(Withdrawal, User.telegram_id)
            .join(User, User.id == Withdrawal.user_id)
            .where(Withdrawal.created_at >= start, Withdrawal.created_at < end)
            .order_by(Withdrawal.id)
        )
        for w, tg in withdrawals:
            writer.writerow(
                [
                    f"withdrawal_{w.source.value}",
                    w.id,
                    tg,
                    w.amount,
                    w.fee,
                    w.net_amount,
                    w.status.value,
                    w.provider,
                    w.created_at.astimezone(tz).isoformat(),
                    w.paid_at.astimezone(tz).isoformat() if w.paid_at else "",
                    w.is_test,
                ]
            )
        return buf.getvalue().encode("utf-8-sig")
