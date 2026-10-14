from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core.enums import (
    LedgerAccount,
    LedgerDirection,
    LedgerReason,
    PromoActivationStatus,
    PromoType,
)
from app.core.errors import DomainError, NotFoundError
from app.core.money import ZERO, fmt_money, percent_of, q
from app.core.utils import get_tz, utcnow
from app.models import PromoActivation, PromoCode, User, VipLevel
from app.repositories.bonus import PromoRepository, VipRepository
from app.repositories.users import FriendRow, ReferrerRow, UserRepository
from app.repositories.wallets import WalletRepository
from app.services.audit import Actor, AuditService
from app.services.ledger import LedgerService
from app.services.settings import SettingsService


# --------------------------------------------------------------------------- promo
@dataclass(frozen=True, slots=True)
class PromoResult:
    applied_now: bool
    promo: PromoCode
    bonus: Decimal


def compute_promo_bonus(promo: PromoCode, deposit_amount: Decimal | None) -> Decimal:
    if promo.bonus_type == PromoType.FIXED:
        bonus = promo.bonus_value
    else:
        bonus = percent_of(deposit_amount or ZERO, promo.bonus_value, round_down=True)
    if promo.max_bonus is not None and promo.max_bonus > 0:
        bonus = min(bonus, promo.max_bonus)
    return q(bonus)


def promo_still_usable(promo: PromoCode, now: datetime) -> bool:
    return (
        promo.is_active
        and not promo.is_deleted
        and (promo.valid_until is None or promo.valid_until >= now)
    )


def check_promo_validity(promo: PromoCode | None, now: datetime) -> None:
    if promo is None or not promo.is_active or promo.is_deleted:
        raise DomainError(texts.PROMO_INVALID)
    if promo.valid_from and promo.valid_from > now:
        raise DomainError(texts.PROMO_NOT_STARTED)
    if promo.valid_until and promo.valid_until < now:
        raise DomainError(texts.PROMO_EXPIRED)
    if promo.total_limit is not None and promo.used_count >= promo.total_limit:
        raise DomainError(texts.PROMO_LIMIT)


PROMO_FORM_HELP = (
    "Format (| bilan ajrating):\n"
    "<code>KOD | turi | qiymat | min depozit | umumiy limit | user limiti | tugash sanasi"
    " | max bonus</code>\n\n"
    "• turi: <code>fixed</code> (so‘m) yoki <code>percent</code> (%)\n"
    "• umumiy limit / tugash sanasi / max bonus: <code>-</code> = cheksiz\n"
    "• sana: <code>YYYY-MM-DD</code>\n\n"
    "Misol: <code>WELCOME | fixed | 10000 | 0 | 500 | 1 | 2026-12-31 | -</code>\n"
    "Misol: <code>BONUS20 | percent | 20 | 50000 | - | 1 | - | 100000</code>"
)


def parse_promo_form(text: str, tz_name: str) -> dict[str, Any]:
    parts = [p.strip() for p in text.split("|")]
    if len(parts) not in (7, 8):
        raise DomainError("Maydonlar soni noto‘g‘ri.\n\n" + PROMO_FORM_HELP)
    code = parts[0].upper()
    if not code.isalnum() or not 3 <= len(code) <= 32:
        raise DomainError("Kod 3–32 ta lotin harf/raqamdan iborat bo‘lsin.")
    try:
        bonus_type = PromoType(parts[1].lower())
    except ValueError as exc:
        raise DomainError("Turi faqat fixed yoki percent.") from exc

    def money(raw: str, allow_none: bool = False) -> Decimal | None:
        if allow_none and raw in {"-", ""}:
            return None
        try:
            value = q(Decimal(raw.replace(" ", "")))
        except InvalidOperation as exc:
            raise DomainError(f"Raqam noto‘g‘ri: {raw}") from exc
        if value < 0:
            raise DomainError("Manfiy qiymat bo‘lmaydi.")
        return value

    def integer(raw: str, allow_none: bool = False) -> int | None:
        if allow_none and raw in {"-", ""}:
            return None
        if not raw.isdigit() or int(raw) < 1:
            raise DomainError(f"Butun musbat son kerak: {raw}")
        return int(raw)

    value = money(parts[2])
    if value is None or value <= 0:
        raise DomainError("Qiymat musbat bo‘lishi kerak.")
    if bonus_type == PromoType.PERCENT and value > 100:
        raise DomainError("Foiz 100 dan oshmasin.")
    valid_until = None
    if parts[6] not in {"-", ""}:
        try:
            day = datetime.strptime(parts[6], "%Y-%m-%d").replace(tzinfo=get_tz(tz_name))
        except ValueError as exc:
            raise DomainError("Sana formati: YYYY-MM-DD") from exc
        valid_until = (day + timedelta(days=1) - timedelta(seconds=1)).astimezone(UTC)
    return {
        "code": code,
        "bonus_type": bonus_type,
        "bonus_value": value,
        "min_deposit": money(parts[3]) or ZERO,
        "total_limit": integer(parts[4], allow_none=True),
        "per_user_limit": integer(parts[5]) or 1,
        "valid_until": valid_until,
        "max_bonus": money(parts[7], allow_none=True) if len(parts) == 8 else None,
    }


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PromoRepository(session)
        self.wallets = WalletRepository(session)
        self.audit = AuditService(session)

    async def activate(self, user: User, code: str) -> PromoResult:
        code = code.strip().upper()
        if not code or len(code) > 32:
            raise DomainError(texts.PROMO_INVALID)
        promo = await self.repo.get_by_code(code, for_update=True)
        check_promo_validity(promo, utcnow())
        assert promo is not None  # noqa: S101 - check_promo_validity tekshirdi
        if await self.repo.user_usage_count(promo.id, user.id) >= promo.per_user_limit:
            raise DomainError(texts.PROMO_USER_LIMIT)
        if await self.repo.pending_activation(user.id) is not None:
            raise DomainError(texts.PROMO_HAS_PENDING)

        activation = PromoActivation(promo_id=promo.id, user_id=user.id)
        self.session.add(activation)
        await self.session.flush()
        await self.repo.increment_usage(promo.id)

        if promo.bonus_type == PromoType.FIXED and promo.min_deposit <= 0:
            bonus = compute_promo_bonus(promo, None)
            wallet = await self.wallets.get_for_update(user.id)
            await LedgerService(self.session).post(
                wallet=wallet,
                account=LedgerAccount.MAIN,
                direction=LedgerDirection.CREDIT,
                amount=bonus,
                reason=LedgerReason.PROMO_BONUS,
                idempotency_key=f"promo:{activation.id}",
                reference_type="promo_activation",
                reference_id=activation.id,
                comment=promo.code,
            )
            activation.status = PromoActivationStatus.APPLIED
            activation.bonus_amount = bonus
            activation.applied_at = utcnow()
            await self.session.commit()
            return PromoResult(applied_now=True, promo=promo, bonus=bonus)

        await self.session.commit()
        return PromoResult(applied_now=False, promo=promo, bonus=ZERO)

    # ---- admin ----
    async def list_page(self, page: int, per_page: int = 8) -> list[PromoCode]:
        return await self.repo.list_page(per_page, page * per_page)

    async def get(self, promo_id: int) -> PromoCode:
        promo = await self.repo.get(promo_id)
        if promo is None or promo.is_deleted:
            raise NotFoundError("Promokod topilmadi.")
        return promo

    async def create(self, data: dict[str, Any], actor: Actor) -> PromoCode:
        if await self.repo.get_by_code(data["code"]) is not None:
            raise DomainError("Bu kod allaqachon mavjud.")
        promo = PromoCode(**data, created_by=actor.telegram_id, is_active=True)
        self.session.add(promo)
        await self.session.flush()
        await self.audit.log(actor, "promo.create", "promo", promo.id, after=data)
        await self.session.commit()
        return promo

    async def update(self, promo_id: int, data: dict[str, Any], actor: Actor) -> PromoCode:
        promo = await self.get(promo_id)
        if data["code"] != promo.code:
            other = await self.repo.get_by_code(data["code"])
            if other is not None:
                raise DomainError("Bu kod allaqachon mavjud.")
        before = {k: getattr(promo, k) for k in data}
        for key, value in data.items():
            setattr(promo, key, value)
        await self.audit.log(actor, "promo.update", "promo", promo.id, before=before, after=data)
        await self.session.commit()
        return promo

    async def set_active(self, promo_id: int, active: bool, actor: Actor) -> PromoCode:
        promo = await self.get(promo_id)
        promo.is_active = active
        await self.audit.log(
            actor,
            "promo.activate" if active else "promo.deactivate",
            "promo",
            promo.id,
            after={"is_active": active},
        )
        await self.session.commit()
        return promo

    async def delete(self, promo_id: int, actor: Actor) -> None:
        promo = await self.get(promo_id)
        promo.is_deleted = True
        promo.is_active = False
        await self.audit.log(actor, "promo.delete", "promo", promo.id, before={"code": promo.code})
        await self.session.commit()


# --------------------------------------------------------------------------- VIP
@dataclass(frozen=True, slots=True)
class VipProgress:
    current: VipLevel | None
    next: VipLevel | None
    percent: int
    left: Decimal


def vip_level_for(levels: list[VipLevel], total: Decimal) -> VipLevel | None:
    current = None
    for level in sorted(levels, key=lambda lv: lv.min_total_deposit):
        if total >= level.min_total_deposit:
            current = level
    return current


def vip_progress(levels: list[VipLevel], total: Decimal) -> VipProgress:
    ordered = sorted(levels, key=lambda lv: lv.min_total_deposit)
    current = vip_level_for(ordered, total)
    nxt = next((lv for lv in ordered if lv.min_total_deposit > total), None)
    if nxt is None:
        return VipProgress(current, None, 100, ZERO)
    base = current.min_total_deposit if current else ZERO
    span = nxt.min_total_deposit - base
    pct = int(((total - base) / span) * 100) if span > 0 else 0
    return VipProgress(current, nxt, max(0, min(pct, 99)), nxt.min_total_deposit - total)


VIP_FORM_HELP = (
    "Format: <code>Nomi | min jami depozit | bonus % | tartib</code>\n"
    "Misol: <code>Gold | 5000000 | 1.5 | 3</code>"
)


def parse_vip_form(text: str) -> dict[str, Any]:
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 4:
        raise DomainError("Maydonlar soni noto‘g‘ri.\n\n" + VIP_FORM_HELP)
    name = parts[0][:32]
    if not name:
        raise DomainError("Nom bo‘sh bo‘lmasin.")
    try:
        min_total = q(Decimal(parts[1].replace(" ", "")))
        percent = q(Decimal(parts[2].replace(",", ".")))
        order = int(parts[3])
    except (InvalidOperation, ValueError) as exc:
        raise DomainError("Raqamlar noto‘g‘ri.\n\n" + VIP_FORM_HELP) from exc
    if min_total < 0 or not 0 <= percent <= 100:
        raise DomainError("Qiymatlar chegaradan tashqarida.")
    return {
        "name": name,
        "min_total_deposit": min_total,
        "bonus_percent": percent,
        "sort_order": order,
    }


class VipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = VipRepository(session)
        self.audit = AuditService(session)

    async def levels(self) -> list[VipLevel]:
        return await self.repo.list_active()

    async def level_for(self, total: Decimal) -> VipLevel | None:
        return vip_level_for(await self.repo.list_active(), total)

    async def progress(self, total: Decimal) -> VipProgress:
        return vip_progress(await self.repo.list_active(), total)

    async def all(self) -> list[VipLevel]:
        return await self.repo.list_all()

    async def get(self, level_id: int) -> VipLevel:
        level = await self.repo.get(level_id)
        if level is None:
            raise NotFoundError("Daraja topilmadi.")
        return level

    async def create(self, data: dict[str, Any], actor: Actor) -> VipLevel:
        level = VipLevel(**data, is_active=True)
        self.session.add(level)
        await self.session.flush()
        await self.audit.log(actor, "vip.create", "vip_level", level.id, after=data)
        await self.session.commit()
        return level

    async def update(self, level_id: int, data: dict[str, Any], actor: Actor) -> VipLevel:
        level = await self.get(level_id)
        before = {k: getattr(level, k) for k in data}
        for key, value in data.items():
            setattr(level, key, value)
        await self.audit.log(actor, "vip.update", "vip_level", level.id, before=before, after=data)
        await self.session.commit()
        return level

    async def toggle(self, level_id: int, actor: Actor) -> VipLevel:
        level = await self.get(level_id)
        level.is_active = not level.is_active
        await self.audit.log(
            actor, "vip.toggle", "vip_level", level.id, after={"is_active": level.is_active}
        )
        await self.session.commit()
        return level

    async def delete(self, level_id: int, actor: Actor) -> None:
        level = await self.get(level_id)
        await self.audit.log(
            actor,
            "vip.delete",
            "vip_level",
            level.id,
            before={"name": level.name, "min_total_deposit": level.min_total_deposit},
        )
        await self.session.delete(level)
        await self.session.commit()


# --------------------------------------------------------------------------- referal
@dataclass(frozen=True, slots=True)
class ReferralStats:
    link: str
    percent: Decimal
    count: int
    earned: Decimal
    withdrawn: Decimal
    balance: Decimal


class ReferralService:
    def __init__(self, session: AsyncSession, settings: SettingsService, bot_username: str) -> None:
        self.session = session
        self.settings = settings
        self.bot_username = bot_username.lstrip("@")
        self.users = UserRepository(session)
        self.wallets = WalletRepository(session)

    def link_for(self, user: User) -> str:
        return f"https://t.me/{self.bot_username}?start=ref_{user.telegram_id}"

    async def stats(self, user: User) -> ReferralStats:
        s = await self.settings.snapshot()
        wallet = await self.wallets.get_by_user(user.id)
        return ReferralStats(
            link=self.link_for(user),
            percent=s.referral_percent,
            count=await self.users.referrals_count(user.id),
            earned=wallet.referral_earned if wallet else ZERO,
            withdrawn=wallet.referral_withdrawn if wallet else ZERO,
            balance=wallet.bonus_balance if wallet else ZERO,
        )

    async def top(self, days: int | None = None) -> list[ReferrerRow]:
        since = utcnow() - timedelta(days=days) if days else None
        return await self.users.top_referrers(since=since, limit=10)

    async def friends(
        self, user: User, page: int, per_page: int = 10
    ) -> tuple[list[FriendRow], int]:
        total = await self.users.referrals_count(user.id)
        rows = await self.users.friends(user.id, per_page, page * per_page)
        return rows, total

    async def withdraw_bonus(self, user: User) -> Decimal:
        """Referal bonus balansini asosiy balansga o‘tkazadi."""
        s = await self.settings.snapshot()
        wallet = await self.wallets.get_for_update(user.id)
        amount = wallet.bonus_balance
        if amount <= 0 or amount < s.referral_withdraw_min:
            raise DomainError(
                texts.REF_WITHDRAW_LOW.format(
                    min=fmt_money(s.referral_withdraw_min), balance=fmt_money(amount)
                )
            )
        op = uuid.uuid4().hex
        await LedgerService(self.session).transfer(
            wallet=wallet,
            source=LedgerAccount.BONUS,
            target=LedgerAccount.MAIN,
            amount=amount,
            reason=LedgerReason.REFERRAL_TRANSFER,
            key_prefix=f"ref_transfer:{op}",
            reference_type="referral_transfer",
            reference_id=op,
            actor_telegram_id=user.telegram_id,
        )
        wallet.referral_withdrawn += amount
        await self.session.commit()
        return amount
