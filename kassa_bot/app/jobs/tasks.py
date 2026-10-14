"""Background vazifalar: muddati o‘tgan to‘lovlar, payout navbati, reconciliation, hisobot."""

from __future__ import annotations

import logging
from datetime import timedelta

from app.admin.stats import render_report
from app.bootstrap import AppContext
from app.core.permissions import Perm
from app.core.utils import fmt_dt, get_tz, utcnow
from app.services.stats import period_bounds

log = logging.getLogger(__name__)


async def expire_payments(ctx: AppContext) -> int:
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        outcomes = await svc.deposits.expire_due()
        for outcome in outcomes:
            await svc.notifier.deposit(outcome)
        return len(outcomes)


async def reconcile_payments(ctx: AppContext) -> int:
    """Webhook kelmay qolgan pending to‘lovlarni provayderdan tekshiradi."""
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        outcomes = await svc.deposits.reconcile_pending(older_than=timedelta(minutes=2))
        for outcome in outcomes:
            await svc.notifier.deposit(outcome)
        return len(outcomes)


async def expire_p2p(ctx: AppContext) -> int:
    """Muddati o‘tgan P2P to‘lovlar (kechikib kelsa ham userbot ularni topadi)."""
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        outcomes = await svc.p2p.expire_due()
        for outcome in outcomes:
            await svc.notifier.p2p_deposit(outcome)
        return len(outcomes)


async def credit_p2p(ctx: AppContext) -> int:
    """To‘langan, lekin Mob-Cash'ga hali tushmagan depozitlar (tarmoq xatosidan keyin)."""
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        outcomes = await svc.p2p.credit_due()
        if outcomes:
            admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
            for outcome in outcomes:
                bm = await svc.bookmakers.name_of(outcome.deposit.bookmaker_id)
                await svc.notifier.p2p_deposit(outcome, admins, bm)
        return len(outcomes)


async def process_payouts(ctx: AppContext) -> int:
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        events = await svc.withdrawals.process_queue(limit=20)
        if events:
            admins = await svc.admins.telegram_ids_with(Perm.WITHDRAW_PROCESS)
            for event in events:
                await svc.notifier.withdrawal(event, admins)
        return len(events)


async def poll_payouts(ctx: AppContext) -> int:
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        events = await svc.withdrawals.poll_processing()
        if events:
            admins = await svc.admins.telegram_ids_with(Perm.WITHDRAW_PROCESS)
            for event in events:
                await svc.notifier.withdrawal(event, admins)
        return len(events)


async def provider_health(ctx: AppContext) -> int:
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        for code in ctx.providers.codes:
            try:
                ok = await ctx.providers.get(code).health_check()
            except Exception:
                ok = False
            if ok:
                await svc.health.record_success(code)
            else:
                await svc.health.record_failure(code, "health_check")
    return len(ctx.providers.codes)


USERBOT_STALE = timedelta(minutes=5)


async def userbot_watchdog(ctx: AppContext) -> int:
    """Faol userbot 5 daqiqadan beri bank xabarlarini o‘qimayapti — adminlarga ogohlantirish.

    Userbot jarayoni to‘xtab qolsa P2P to‘lovlar avtomatik tasdiqlanmaydi; bu holat
    o‘zicha hech qayerda ko‘rinmaydi. Ogohlantirish har akkaunt uchun soatiga bir marta.
    """
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        rt = await svc.settings.snapshot()
        if not (rt.mobcash_enabled and rt.userbot_configured):
            return 0
        now = utcnow()
        stale = [
            a
            for a in await svc.userbots.active_accounts()
            if a.last_seen_at is None or now - a.last_seen_at > USERBOT_STALE
        ]
        if not stale:
            return 0
        admins = await svc.admins.telegram_ids_with(Perm.MOBCASH_PROCESS)
        sent = 0
        for account in stale:
            if not await ctx.redis.set(f"userbot:stale_alert:{account.id}", "1", nx=True, ex=3600):
                continue
            seen = fmt_dt(account.last_seen_at, rt.timezone) if account.last_seen_at else "—"
            sent += await svc.notifier.send_many(
                admins,
                f"🟠 <b>Userbot #{account.id} javob bermayapti</b>\n\n"
                f"Oxirgi faollik: {seen}\n"
                "P2P to‘lovlar avtomatik tasdiqlanmayapti. «python -m app.userbot» jarayoni "
                "ishlayotganini tekshiring.",
            )
        return sent


async def refresh_channels(ctx: AppContext) -> int:
    async with ctx.sessionmaker() as session:
        await ctx.services(session).channels.refresh_all()
    return 0


async def daily_report(ctx: AppContext) -> int:
    """Har kuni REPORT_HOUR da (mahalliy vaqt) kechagi hisobot adminlarga yuboriladi."""
    async with ctx.sessionmaker() as session:
        svc = ctx.services(session)
        rt = await svc.settings.snapshot()
        local_now = utcnow().astimezone(get_tz(rt.timezone))
        if local_now.hour < ctx.config.report_hour:
            return 0
        key = f"daily_report:{local_now.date().isoformat()}"
        if not await ctx.redis.set(key, "1", nx=True, ex=2 * 24 * 3600):
            return 0
        today_start, _ = period_bounds("day", rt.timezone)
        start = today_start - timedelta(days=1)
        report = await svc.stats.period_report(start, today_start, rt.timezone)
        admins = await svc.admins.telegram_ids_with(Perm.STATS_VIEW)
        text = "🗓 <b>Kunlik hisobot</b>\n\n" + render_report(report, rt.timezone)
        return await svc.notifier.send_many(admins, text)
