from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core.enums import (
    LedgerAccount,
    LedgerDirection,
    LedgerReason,
    PaymentStatus,
    PromoActivationStatus,
    ProviderEventKind,
    ProviderStatus,
)
from app.core.errors import DomainError, NotFoundError, ProviderUnavailableError
from app.core.money import ZERO, fmt_money, percent_of, q
from app.core.utils import utcnow
from app.models import Payment, ReferralReward, User
from app.payments.base import PaymentProviderError
from app.payments.registry import ProviderRegistry
from app.repositories.bonus import PromoRepository, VipRepository
from app.repositories.payments import PaymentRepository
from app.repositories.users import UserRepository
from app.repositories.wallets import WalletRepository
from app.services.audit import Actor, AuditService
from app.services.bonus import compute_promo_bonus, promo_still_usable, vip_level_for
from app.services.ledger import LedgerService
from app.services.settings import SettingsService

log = logging.getLogger(__name__)


@dataclass(slots=True)
class BonusLine:
    label: str
    amount: Decimal


@dataclass(slots=True)
class DepositOutcome:
    payment: Payment
    user_telegram_id: int
    status: PaymentStatus
    net: Decimal = ZERO
    bonuses: list[BonusLine] = field(default_factory=list)
    referrer_telegram_id: int | None = None
    referral_amount: Decimal = ZERO
    amount_mismatch: bool = False


class DepositService:
    MAX_PENDING_PER_USER = 3

    def __init__(
        self,
        session: AsyncSession,
        providers: ProviderRegistry,
        settings: SettingsService,
        currency: str,
    ) -> None:
        self.session = session
        self.providers = providers
        self.settings = settings
        self.currency = currency
        self.repo = PaymentRepository(session)
        self.wallets = WalletRepository(session)
        self.users = UserRepository(session)
        self.ledger = LedgerService(session)

    # ------------------------------------------------------------------ yaratish
    async def create(self, user: User, amount: Decimal) -> Payment:
        s = await self.settings.snapshot()
        amount = q(amount)
        if not s.deposit_min <= amount <= s.deposit_max:
            raise DomainError(
                texts.AMOUNT_OUT_OF_RANGE.format(
                    min=fmt_money(s.deposit_min), max=fmt_money(s.deposit_max)
                )
            )
        if await self.repo.count_pending_for_user(user.id) >= self.MAX_PENDING_PER_USER:
            raise DomainError(texts.DEPOSIT_TOO_MANY_PENDING)
        enabled = self.providers.enabled(s.enabled_providers)
        if not enabled:
            raise ProviderUnavailableError(texts.DEPOSIT_PROVIDER_DOWN)
        provider = enabled[0]

        payment = Payment(
            user_id=user.id,
            provider=provider.code,
            amount=amount,
            fee=percent_of(amount, s.deposit_fee_percent),
            currency=self.currency,
            status=PaymentStatus.PENDING,
            is_test=provider.is_sandbox or s.payment_mode != "production",
            expires_at=utcnow() + timedelta(minutes=s.payment_expiry_minutes),
        )
        self.session.add(payment)
        await self.session.commit()  # avval pending yozuv, keyin provayder chaqiruvi

        try:
            checkout = await provider.create_payment(
                reference=str(payment.ref),
                amount=amount,
                currency=self.currency,
                description=f"Hamyonni to‘ldirish #{payment.id}",
                expires_at=payment.expires_at,
            )
        except PaymentProviderError as exc:
            log.warning("create_payment xatosi provider=%s: %s", provider.code, exc)
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "provider_error"
            await self.session.commit()
            raise ProviderUnavailableError(texts.DEPOSIT_PROVIDER_DOWN) from exc
        payment.external_id = checkout.external_id
        payment.checkout_url = checkout.checkout_url
        await self.session.commit()
        return payment

    async def get_for_user(self, user: User, payment_id: int) -> Payment:
        payment = await self.repo.get(payment_id)
        if payment is None or payment.user_id != user.id:
            raise NotFoundError("To‘lov topilmadi.")
        return payment

    async def set_message_id(self, payment: Payment, message_id: int) -> None:
        payment.chat_message_id = message_id
        await self.session.commit()

    async def cancel(self, user: User, payment_id: int) -> Payment:
        payment = await self.repo.get(payment_id, for_update=True)
        if payment is None or payment.user_id != user.id:
            raise NotFoundError("To‘lov topilmadi.")
        if payment.status != PaymentStatus.PENDING:
            raise DomainError(
                texts.DEPOSIT_CANNOT_CANCEL.format(status=texts.PAYMENT_STATUS[payment.status])
            )
        payment.status = PaymentStatus.CANCELLED
        payment.failure_reason = "cancelled_by_user"
        await self.session.commit()
        return payment

    # ------------------------------------------------------------------ holat
    async def apply_status(
        self,
        *,
        provider_code: str,
        reference: str,
        status: ProviderStatus,
        external_id: str | None = None,
        amount: Decimal | None = None,
    ) -> DepositOutcome | None:
        """Provayder holatini qo‘llaydi. Commit qilmaydi — chaqiruvchi tranzaksiyani yopadi.

        Idempotent: to‘langan to‘lov qayta kelsa hech narsa o‘zgarmaydi.
        """
        payment = await self.repo.get_by_ref(reference, for_update=True)
        if payment is None or payment.provider != provider_code:
            log.warning("Noma’lum to‘lov reference=%s provider=%s", reference, provider_code)
            return None
        if external_id and not payment.external_id:
            payment.external_id = external_id
        if payment.status == PaymentStatus.PAID:
            return None
        user = await self.users.get(payment.user_id)
        if user is None:  # pragma: no cover
            return None

        if status == ProviderStatus.PAID:
            if amount is not None and q(amount) != q(payment.amount):
                log.error(
                    "Summa mos emas payment=%s kutilgan=%s kelgan=%s",
                    payment.id,
                    payment.amount,
                    amount,
                )
                payment.status = PaymentStatus.FAILED
                payment.failure_reason = "amount_mismatch"
                await AuditService(self.session).log(
                    Actor.system(),
                    "payment.amount_mismatch",
                    "payment",
                    payment.id,
                    after={"expected": payment.amount, "received": amount},
                )
                return DepositOutcome(
                    payment, user.telegram_id, PaymentStatus.FAILED, amount_mismatch=True
                )
            if payment.status != PaymentStatus.PENDING:
                # Muddati o‘tgan/bekor qilingan to‘lov provayderda to‘langan — pul olingan,
                # demak hamyonga qo‘shilishi shart.
                await AuditService(self.session).log(
                    Actor.system(),
                    "payment.late_paid",
                    "payment",
                    payment.id,
                    before={"status": payment.status},
                )
            return await self._mark_paid(payment, user)

        if payment.status != PaymentStatus.PENDING:
            return None
        if status == ProviderStatus.FAILED:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = "provider_failed"
        elif status == ProviderStatus.EXPIRED:
            payment.status = PaymentStatus.EXPIRED
        else:
            return None
        return DepositOutcome(payment, user.telegram_id, payment.status)

    async def _mark_paid(self, payment: Payment, user: User) -> DepositOutcome:
        s = await self.settings.snapshot()
        wallet = await self.wallets.get_for_update(user.id)
        payment.status = PaymentStatus.PAID
        payment.paid_at = utcnow()
        net = q(payment.amount - payment.fee)
        payment.credited_amount = net
        outcome = DepositOutcome(payment, user.telegram_id, PaymentStatus.PAID, net=net)

        await self.ledger.post(
            wallet=wallet,
            account=LedgerAccount.MAIN,
            direction=LedgerDirection.CREDIT,
            amount=net,
            reason=LedgerReason.DEPOSIT,
            idempotency_key=f"payment:{payment.id}:deposit",
            reference_type="payment",
            reference_id=payment.id,
            external_tx_id=payment.external_id,
        )
        wallet.total_deposit += payment.amount

        cap_left: Decimal | None = s.max_bonus_per_deposit if s.max_bonus_per_deposit > 0 else None

        def capped(value: Decimal) -> Decimal:
            nonlocal cap_left
            if cap_left is None:
                return value
            value = min(value, cap_left)
            cap_left -= value
            return value

        # VIP bonus
        if s.vip_bonus_enabled:
            levels = await VipRepository(self.session).list_active()
            level = vip_level_for(levels, wallet.total_deposit)
            if level and level.bonus_percent > 0:
                bonus = capped(percent_of(payment.amount, level.bonus_percent, round_down=True))
                if bonus > 0:
                    await self.ledger.post(
                        wallet=wallet,
                        account=LedgerAccount.MAIN,
                        direction=LedgerDirection.CREDIT,
                        amount=bonus,
                        reason=LedgerReason.VIP_BONUS,
                        idempotency_key=f"payment:{payment.id}:vip",
                        reference_type="payment",
                        reference_id=payment.id,
                        comment=level.name,
                    )
                    outcome.bonuses.append(BonusLine(f"VIP {level.name}", bonus))

        # Promokod (depozit sharti bilan)
        promo_repo = PromoRepository(self.session)
        activation = await promo_repo.pending_activation(user.id)
        if activation is not None:
            promo = await promo_repo.get(activation.promo_id)
            # Limit aktivatsiya paytida band qilingan, shu sabab bu yerda faqat
            # faollik va muddat tekshiriladi.
            if promo is None or not promo_still_usable(promo, utcnow()):
                activation.status = PromoActivationStatus.EXPIRED
            elif payment.amount >= promo.min_deposit:
                bonus = capped(compute_promo_bonus(promo, payment.amount))
                activation.status = PromoActivationStatus.APPLIED
                activation.payment_id = payment.id
                activation.bonus_amount = bonus
                activation.applied_at = utcnow()
                if bonus > 0:
                    await self.ledger.post(
                        wallet=wallet,
                        account=LedgerAccount.MAIN,
                        direction=LedgerDirection.CREDIT,
                        amount=bonus,
                        reason=LedgerReason.PROMO_BONUS,
                        idempotency_key=f"payment:{payment.id}:promo",
                        reference_type="promo_activation",
                        reference_id=activation.id,
                        comment=promo.code,
                    )
                    outcome.bonuses.append(BonusLine(f"promokod {promo.code}", bonus))

        # Referal bonus — faqat tasdiqlangan to‘lovdan keyin
        if s.referral_enabled and user.referrer_id and s.referral_percent > 0:
            reward = percent_of(payment.amount, s.referral_percent, round_down=True)
            referrer = await self.users.get(user.referrer_id)
            if reward > 0 and referrer is not None and not referrer.is_banned:
                ref_wallet = await self.wallets.get_for_update(referrer.id)
                await self.ledger.post(
                    wallet=ref_wallet,
                    account=LedgerAccount.BONUS,
                    direction=LedgerDirection.CREDIT,
                    amount=reward,
                    reason=LedgerReason.REFERRAL_BONUS,
                    idempotency_key=f"payment:{payment.id}:referral",
                    reference_type="payment",
                    reference_id=payment.id,
                )
                ref_wallet.referral_earned += reward
                self.session.add(
                    ReferralReward(
                        referrer_id=referrer.id,
                        referred_id=user.id,
                        payment_id=payment.id,
                        deposit_amount=payment.amount,
                        percent=s.referral_percent,
                        amount=reward,
                    )
                )
                outcome.referrer_telegram_id = referrer.telegram_id
                outcome.referral_amount = reward
        await self.session.flush()
        return outcome

    # ------------------------------------------------------------------ reconciliation
    async def refresh(self, payment_id: int) -> DepositOutcome | None:
        """Provayderdan holatni so‘rab, kerak bo‘lsa qo‘llaydi (webhook yo‘qolgan holat)."""
        payment = await self.repo.get(payment_id)
        if payment is None or payment.status != PaymentStatus.PENDING:
            return None
        provider = self.providers.find(payment.provider)
        if provider is None:
            return None
        try:
            result = await provider.check_status(
                kind=ProviderEventKind.PAYMENT,
                reference=str(payment.ref),
                external_id=payment.external_id,
            )
        except PaymentProviderError as exc:
            log.warning("check_status xatosi payment=%s: %s", payment.id, exc)
            return None
        if result.status not in (
            ProviderStatus.PAID,
            ProviderStatus.FAILED,
            ProviderStatus.EXPIRED,
        ):
            return None
        outcome = await self.apply_status(
            provider_code=payment.provider,
            reference=str(payment.ref),
            status=result.status,
            external_id=result.external_id,
            amount=result.amount,
        )
        await self.session.commit()
        return outcome

    async def expire_due(
        self, now: datetime | None = None, limit: int = 100
    ) -> list[DepositOutcome]:
        now = now or utcnow()
        outcomes: list[DepositOutcome] = []
        for payment_id in await self.repo.pending_ids(expires_before=now, limit=limit):
            outcome = await self.refresh(payment_id)
            if outcome is not None:
                outcomes.append(outcome)
                continue
            payment = await self.repo.get(payment_id, for_update=True)
            if payment is None or payment.status != PaymentStatus.PENDING:
                await self.session.rollback()
                continue
            payment.status = PaymentStatus.EXPIRED
            payment.failure_reason = "timeout"
            user = await self.users.get(payment.user_id)
            await self.session.commit()
            if user is not None:
                outcomes.append(DepositOutcome(payment, user.telegram_id, PaymentStatus.EXPIRED))
        return outcomes

    async def reconcile_pending(
        self, older_than: timedelta, limit: int = 100
    ) -> list[DepositOutcome]:
        outcomes = []
        ids = await self.repo.pending_ids(created_before=utcnow() - older_than, limit=limit)
        for payment_id in ids:
            outcome = await self.refresh(payment_id)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes
