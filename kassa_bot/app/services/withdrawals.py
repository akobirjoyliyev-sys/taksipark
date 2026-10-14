from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.core.enums import (
    LedgerAccount,
    LedgerDirection,
    LedgerReason,
    MassBatchStatus,
    MassItemStatus,
    ProviderEventKind,
    ProviderStatus,
    WithdrawalSource,
    WithdrawalStatus,
)
from app.core.errors import DomainError, InsufficientFundsError, NotFoundError
from app.core.money import ZERO, fmt_money, percent_of, q
from app.core.utils import utcnow
from app.models import MassPayoutBatch, MassPayoutItem, PayoutCard, User, Withdrawal
from app.models.withdrawal import WithdrawalStatusHistory
from app.payments.base import PaymentProviderError
from app.payments.manual import MANUAL_CODE
from app.payments.registry import ProviderRegistry
from app.repositories.payments import CardRepository
from app.repositories.users import UserRepository
from app.repositories.wallets import WalletRepository
from app.repositories.withdrawals import WithdrawalRepository
from app.services.audit import Actor, AuditService
from app.services.ledger import LedgerService
from app.services.mobcash_withdrawals import mask_card
from app.services.provider_health import ProviderHealthService
from app.services.settings import RuntimeSettings, SettingsService

log = logging.getLogger(__name__)

FINAL_STATUSES = (WithdrawalStatus.PAID, WithdrawalStatus.REJECTED, WithdrawalStatus.FAILED)


def backoff_seconds(attempt: int) -> int:
    """30s, 60s, 120s, ... maksimal 30 daqiqa."""
    return int(min(30 * 2 ** max(attempt - 1, 0), 1800))


def quote(amount: Decimal, fee_percent: Decimal) -> tuple[Decimal, Decimal]:
    fee = percent_of(amount, fee_percent)
    return fee, q(amount - fee)


@dataclass(frozen=True, slots=True)
class WithdrawalEvent:
    """Bildirishnoma uchun: holat o‘zgargan ariza."""

    withdrawal: Withdrawal
    user_telegram_id: int
    to_manual: bool = False


class WithdrawalService:
    MAX_ACTIVE_PER_USER = 3

    def __init__(
        self,
        session: AsyncSession,
        providers: ProviderRegistry,
        settings: SettingsService,
        health: ProviderHealthService,
        currency: str,
    ) -> None:
        self.session = session
        self.providers = providers
        self.settings = settings
        self.health = health
        self.currency = currency
        self.repo = WithdrawalRepository(session)
        self.cards = CardRepository(session)
        self.wallets = WalletRepository(session)
        self.users = UserRepository(session)
        self.ledger = LedgerService(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ foydalanuvchi
    async def validate_amount(self, user: User, amount: Decimal) -> tuple[Decimal, Decimal]:
        s = await self.settings.snapshot()
        if not s.withdraw_min <= amount <= s.withdraw_max:
            raise DomainError(
                texts.AMOUNT_OUT_OF_RANGE.format(
                    min=fmt_money(s.withdraw_min), max=fmt_money(s.withdraw_max)
                )
            )
        wallet = await self.wallets.get_by_user(user.id)
        available = wallet.available if wallet else ZERO
        if amount > available:
            raise DomainError(texts.WITHDRAW_INSUFFICIENT.format(available=fmt_money(available)))
        fee, net = quote(amount, s.withdraw_fee_percent)
        if net <= 0:
            raise DomainError(texts.AMOUNT_INVALID)
        return fee, net

    async def create(self, user: User, card_id: int, amount: Decimal) -> Withdrawal:
        s = await self.settings.snapshot()
        amount = q(amount)
        card = await self.cards.get_active(card_id, user.id)
        if card is None:
            raise NotFoundError("Karta topilmadi.")
        if await self.repo.count_active_for_user(user.id) >= self.MAX_ACTIVE_PER_USER:
            raise DomainError(texts.WITHDRAW_TOO_MANY)
        fee, net = await self.validate_amount(user, amount)
        provider = self.providers.find(card.provider)

        wallet = await self.wallets.get_for_update(user.id)
        # Qulf ostida qayta tekshiruv: parallel so‘rovlar bir balansni ikki marta ishlata olmaydi
        # va xato bo‘lsa sessiyada yarim yozuv qolmaydi.
        if wallet.available < amount:
            raise InsufficientFundsError(
                texts.WITHDRAW_INSUFFICIENT.format(available=fmt_money(wallet.available))
            )
        withdrawal = Withdrawal(
            user_id=user.id,
            source=WithdrawalSource.USER,
            provider=card.provider,
            card_id=card.id,
            card_mask=card.masked_pan,
            amount=amount,
            fee=fee,
            net_amount=net,
            status=WithdrawalStatus.PENDING,
            is_test=(provider is None or provider.is_sandbox or s.payment_mode != "production"),
        )
        self.session.add(withdrawal)
        await self.session.flush()
        await self.ledger.transfer(
            wallet=wallet,
            source=LedgerAccount.MAIN,
            target=LedgerAccount.BLOCKED,
            amount=amount,
            reason=LedgerReason.WITHDRAW_HOLD,
            key_prefix=f"wd:{withdrawal.id}:hold",
            reference_type="withdrawal",
            reference_id=withdrawal.id,
            actor_telegram_id=user.telegram_id,
        )
        self._history(withdrawal, None, WithdrawalStatus.PENDING, Actor.user(user.telegram_id))

        if (
            s.auto_payout_enabled
            and amount <= s.auto_payout_max
            and provider is not None
            and provider.supports_payout
            and card.provider in s.enabled_providers
            and await self.health.is_available(card.provider)
        ):
            self._queue(withdrawal, Actor.system("auto"), "Avto to‘lov navbatiga qo‘yildi")
        else:
            withdrawal.manual_required = True
        await self.session.commit()
        return withdrawal

    async def list_for_user(self, user: User, limit: int = 10) -> list[Withdrawal]:
        return await self.repo.list_for_user(user.id, None, limit)

    async def get_for_user(self, user: User, withdrawal_id: int) -> Withdrawal:
        w = await self.repo.get(withdrawal_id)
        if w is None or w.user_id != user.id:
            raise NotFoundError("Ariza topilmadi.")
        return w

    async def history(self, withdrawal_id: int) -> list[WithdrawalStatusHistory]:
        return await self.repo.history(withdrawal_id)

    # ------------------------------------------------------------------ admin amallari
    async def get(self, withdrawal_id: int) -> Withdrawal:
        w = await self.repo.get(withdrawal_id)
        if w is None:
            raise NotFoundError("Ariza topilmadi.")
        return w

    async def approve(self, withdrawal_id: int, actor: Actor, comment: str) -> WithdrawalEvent:
        """Tasdiqlash: ariza payout navbatiga qo‘yiladi (worker provayder orqali to‘laydi)."""
        _require_comment(comment)
        w = await self._lock(withdrawal_id)
        if w.status != WithdrawalStatus.PENDING:
            raise DomainError(f"Ariza holati: {texts.WITHDRAW_STATUS[w.status]}")
        provider = self.providers.find(w.provider)
        if provider is None or not provider.supports_payout:
            raise DomainError(
                "Bu provayder avtomatik payoutni qo‘llamaydi — «💵 To‘landi» dan foydalaning."
            )
        w.processed_by, w.processed_at, w.reason = actor.telegram_id, utcnow(), comment
        w.attempts = 0
        self._queue(w, actor, comment)
        await self.audit.log(
            actor, "withdrawal.approve", "withdrawal", w.id, after={"comment": comment}
        )
        await self.session.commit()
        return await self._event(w)

    async def mark_paid_manually(
        self, withdrawal_id: int, actor: Actor, comment: str
    ) -> WithdrawalEvent:
        """Operator pulni provayder kabinetidan o‘zi o‘tkazgan holat."""
        _require_comment(comment)
        w = await self._lock(withdrawal_id)
        if w.status not in (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED):
            raise DomainError(f"Ariza holati: {texts.WITHDRAW_STATUS[w.status]}")
        w.processed_by, w.processed_at, w.reason = actor.telegram_id, utcnow(), comment
        await self._finalize_paid(w, actor, f"Qo‘lda to‘landi: {comment}")
        await self.audit.log(
            actor, "withdrawal.mark_paid", "withdrawal", w.id, after={"comment": comment}
        )
        await self.session.commit()
        return await self._event(w)

    async def reject(self, withdrawal_id: int, actor: Actor, reason: str) -> WithdrawalEvent:
        _require_comment(reason)
        w = await self._lock(withdrawal_id)
        if w.status not in (WithdrawalStatus.PENDING, WithdrawalStatus.APPROVED):
            raise DomainError(f"Ariza holati: {texts.WITHDRAW_STATUS[w.status]}")
        w.processed_by, w.processed_at, w.reason = actor.telegram_id, utcnow(), reason
        await self._finalize_failed(w, actor, WithdrawalStatus.REJECTED, reason)
        await self.audit.log(
            actor, "withdrawal.reject", "withdrawal", w.id, after={"reason": reason}
        )
        await self.session.commit()
        return await self._event(w)

    async def requeue_manual(self, actor: Actor) -> int:
        """Manual navbatdagi (avto to‘lovdan qaytgan) arizalarni qayta avto navbatga qo‘yadi."""
        count = 0
        for wid in await self.repo.manual_ids():
            w = await self.repo.get(wid, for_update=True)
            if w is None or w.status != WithdrawalStatus.PENDING or w.attempts == 0:
                continue  # hali ko‘rib chiqilmagan yangi arizalar operator tasdig‘ini kutadi
            provider = self.providers.find(w.provider)
            if provider is None or not provider.supports_payout:
                continue
            w.attempts = 0
            self._queue(w, actor, "Manual navbatdan qayta avtoga qo‘yildi")
            count += 1
        await self.audit.log(
            actor, "withdrawal.requeue_manual", "withdrawal", None, after={"count": count}
        )
        await self.session.commit()
        return count

    # ------------------------------------------------------------------ worker
    async def process_queue(self, limit: int = 20) -> list[WithdrawalEvent]:
        s = await self.settings.snapshot()
        due = await self.repo.lock_due_for_payout(utcnow(), limit)
        events: list[WithdrawalEvent] = []
        to_send: list[tuple[int, str]] = []
        for w in due:
            provider = self.providers.find(w.provider)
            card = await self.session.get(PayoutCard, w.card_id) if w.card_id else None
            if (
                provider is None
                or not provider.supports_payout
                or w.provider not in s.enabled_providers
                or not await self.health.is_available(w.provider)
            ):
                self._to_manual(w, "Provayder mavjud emas yoki vaqtincha ishlamayapti")
                events.append(await self._event(w, to_manual=True))
                continue
            if card is None or not card.is_active:
                self._to_manual(w, "Karta topilmadi yoki o‘chirilgan")
                events.append(await self._event(w, to_manual=True))
                continue
            w.attempts += 1
            self._set_status(
                w,
                WithdrawalStatus.PROCESSING,
                Actor.system("worker"),
                f"Payout urinish #{w.attempts}",
            )
            to_send.append((w.id, card.token))
        await self.session.commit()

        for wid, token in to_send:
            w = await self.get(wid)
            provider = self.providers.get(w.provider)
            try:
                result = await provider.create_payout(
                    reference=str(w.ref),
                    amount=w.net_amount,
                    currency=self.currency,
                    card_token=token,
                )
            except PaymentProviderError as exc:
                await self.health.record_failure(w.provider, str(exc))
                event = await self._after_error(wid, str(exc), exc.retryable, s)
            except Exception as exc:  # tarmoq/kutilmagan xato — qayta urinish mumkin
                log.exception("create_payout kutilmagan xato withdrawal=%s", wid)
                await self.health.record_failure(w.provider, type(exc).__name__)
                event = await self._after_error(wid, type(exc).__name__, True, s)
            else:
                await self.health.record_success(w.provider)
                event = await self._apply_result(
                    wid, result.status, result.external_id, result.error
                )
            if event is not None:
                events.append(event)
        return events

    async def poll_processing(
        self, min_age: timedelta = timedelta(seconds=5)
    ) -> list[WithdrawalEvent]:
        events: list[WithdrawalEvent] = []
        for wid in await self.repo.processing_ids(updated_before=utcnow() - min_age):
            w = await self.get(wid)
            provider = self.providers.find(w.provider)
            if provider is None:
                continue
            try:
                result = await provider.check_status(
                    kind=ProviderEventKind.PAYOUT, reference=str(w.ref), external_id=w.external_id
                )
            except PaymentProviderError as exc:
                log.warning("Payout holatini olishda xato withdrawal=%s: %s", wid, exc)
                continue
            if result.status == ProviderStatus.NOT_FOUND:
                # Provayderga yetib bormagan (masalan worker to‘xtagan) — qayta yuborish.
                if utcnow() - w.updated_at > timedelta(minutes=2):
                    event = await self._resend(wid)
                    if event:
                        events.append(event)
                continue
            event = await self._apply_result(wid, result.status, result.external_id, result.error)
            if event is not None:
                events.append(event)
        return events

    async def apply_payout_status(
        self, reference: str, status: ProviderStatus, external_id: str | None, error: str | None
    ) -> WithdrawalEvent | None:
        """Webhookdan kelgan payout holati. Commit chaqiruvchida."""
        w = await self.repo.get_by_ref(reference)
        if w is None:
            log.warning("Noma’lum payout reference=%s", reference)
            return None
        return await self._apply_result(w.id, status, external_id, error, commit=False)

    # ------------------------------------------------------------------ ichki
    async def _lock(self, withdrawal_id: int) -> Withdrawal:
        w = await self.repo.get(withdrawal_id, for_update=True)
        if w is None:
            raise NotFoundError("Ariza topilmadi.")
        return w

    async def _event(self, w: Withdrawal, to_manual: bool = False) -> WithdrawalEvent:
        user = await self.users.get(w.user_id)
        return WithdrawalEvent(w, user.telegram_id if user else 0, to_manual)

    def _history(
        self,
        w: Withdrawal,
        old: WithdrawalStatus | None,
        new: WithdrawalStatus,
        actor: Actor,
        comment: str | None = None,
    ) -> None:
        self.session.add(
            WithdrawalStatusHistory(
                withdrawal_id=w.id,
                from_status=old.value if old else None,
                to_status=new.value,
                actor_telegram_id=actor.telegram_id,
                actor_role=actor.role,
                comment=comment,
            )
        )

    def _set_status(
        self, w: Withdrawal, new: WithdrawalStatus, actor: Actor, comment: str | None = None
    ) -> None:
        old = w.status
        w.status = new
        w.updated_at = utcnow()
        self._history(w, old, new, actor, comment)

    def _queue(self, w: Withdrawal, actor: Actor, comment: str | None) -> None:
        w.manual_required = False
        w.next_attempt_at = utcnow()
        self._set_status(w, WithdrawalStatus.APPROVED, actor, comment)

    def _to_manual(self, w: Withdrawal, reason: str) -> None:
        w.manual_required = True
        w.last_error = reason
        w.next_attempt_at = None
        self._set_status(
            w,
            WithdrawalStatus.PENDING,
            Actor.system("worker"),
            f"Manual navbatga o‘tkazildi: {reason}",
        )

    async def _after_error(
        self, wid: int, error: str, retryable: bool, s: RuntimeSettings
    ) -> WithdrawalEvent | None:
        w = await self._lock(wid)
        if w.status != WithdrawalStatus.PROCESSING:
            await self.session.rollback()
            return None
        w.last_error = error[:500]
        if retryable and w.attempts < s.payout_max_attempts:
            w.next_attempt_at = utcnow() + timedelta(seconds=backoff_seconds(w.attempts))
            self._set_status(
                w,
                WithdrawalStatus.APPROVED,
                Actor.system("worker"),
                f"Xato: {error[:100]}. Qayta urinish rejalashtirildi",
            )
            await self.session.commit()
            return None
        self._to_manual(w, error[:200])
        await self.session.commit()
        return await self._event(w, to_manual=True)

    async def _resend(self, wid: int) -> WithdrawalEvent | None:
        w = await self._lock(wid)
        if w.status != WithdrawalStatus.PROCESSING:
            await self.session.rollback()
            return None
        s = await self.settings.snapshot()
        if w.attempts >= s.payout_max_attempts:
            self._to_manual(w, "Provayder payoutni tasdiqlamadi")
            await self.session.commit()
            return await self._event(w, to_manual=True)
        w.next_attempt_at = utcnow()
        self._set_status(
            w,
            WithdrawalStatus.APPROVED,
            Actor.system("worker"),
            "Provayderda topilmadi — qayta yuboriladi",
        )
        await self.session.commit()
        return None

    async def _apply_result(
        self,
        wid: int,
        status: ProviderStatus,
        external_id: str | None,
        error: str | None,
        commit: bool = True,
    ) -> WithdrawalEvent | None:
        w = await self._lock(wid)
        if w.status not in (WithdrawalStatus.PROCESSING, WithdrawalStatus.APPROVED):
            if commit:
                await self.session.rollback()
            return None
        if external_id:
            w.external_id = external_id
        event: WithdrawalEvent | None = None
        if status == ProviderStatus.PAID:
            await self._finalize_paid(w, Actor.system("provider"), "Provayder to‘lovni tasdiqladi")
            event = await self._event(w)
        elif status == ProviderStatus.FAILED:
            w.last_error = error
            await self._finalize_failed(
                w,
                Actor.system("provider"),
                WithdrawalStatus.FAILED,
                f"Provayder rad etdi: {error or 'noma’lum'}",
            )
            event = await self._event(w)
        if commit:
            await self.session.commit()
        return event

    async def _finalize_paid(self, w: Withdrawal, actor: Actor, comment: str) -> None:
        if w.source == WithdrawalSource.USER:
            wallet = await self.wallets.get_for_update(w.user_id)
            await self.ledger.post(
                wallet=wallet,
                account=LedgerAccount.BLOCKED,
                direction=LedgerDirection.DEBIT,
                amount=w.amount,
                reason=LedgerReason.WITHDRAW_PAID,
                idempotency_key=f"wd:{w.id}:paid",
                reference_type="withdrawal",
                reference_id=w.id,
                external_tx_id=w.external_id,
                actor_telegram_id=actor.telegram_id,
                comment=f"komissiya {w.fee}",
            )
            wallet.total_withdraw += w.amount
        else:
            await self.ledger.post(
                wallet=None,
                user_id=w.user_id,
                account=LedgerAccount.SYSTEM,
                direction=LedgerDirection.DEBIT,
                amount=w.net_amount,
                reason=LedgerReason.MASS_PAYOUT,
                idempotency_key=f"wd:{w.id}:paid",
                reference_type="withdrawal",
                reference_id=w.id,
                external_tx_id=w.external_id,
                actor_telegram_id=actor.telegram_id,
                comment=f"batch {w.batch_id}",
            )
        w.paid_at = utcnow()
        w.manual_required = False
        self._set_status(w, WithdrawalStatus.PAID, actor, comment)
        await self._sync_mass_item(w)

    async def _finalize_failed(
        self, w: Withdrawal, actor: Actor, status: WithdrawalStatus, comment: str
    ) -> None:
        if w.source == WithdrawalSource.USER:
            wallet = await self.wallets.get_for_update(w.user_id)
            await self.ledger.transfer(
                wallet=wallet,
                source=LedgerAccount.BLOCKED,
                target=LedgerAccount.MAIN,
                amount=w.amount,
                reason=LedgerReason.WITHDRAW_RELEASE,
                key_prefix=f"wd:{w.id}:release",
                reference_type="withdrawal",
                reference_id=w.id,
                actor_telegram_id=actor.telegram_id,
                comment=comment,
            )
        w.manual_required = False
        self._set_status(w, status, actor, comment)
        await self._sync_mass_item(w)

    async def _sync_mass_item(self, w: Withdrawal) -> None:
        if w.batch_id is None:
            return
        item = await self.session.scalar(
            select(MassPayoutItem).where(MassPayoutItem.withdrawal_id == w.id)
        )
        batch = await self.session.get(MassPayoutBatch, w.batch_id, with_for_update=True)
        if item is None or batch is None:
            return
        if w.status == WithdrawalStatus.PAID:
            item.status = MassItemStatus.PAID
            batch.paid_count += 1
        else:
            item.status = (
                MassItemStatus.SKIPPED
                if w.status == WithdrawalStatus.REJECTED
                else MassItemStatus.FAILED
            )
            item.error = (w.reason or w.last_error or "")[:255]
            batch.failed_count += 1
        if batch.paid_count + batch.failed_count >= batch.valid_rows:
            batch.status = MassBatchStatus.COMPLETED
            batch.completed_at = utcnow()


def _require_comment(comment: str) -> None:
    if not comment or len(comment.strip()) < 3:
        raise DomainError("Sabab/izoh majburiy (kamida 3 belgi).")


# --------------------------------------------------------------------------- kartalar
class CardService:
    MAX_CARDS = 5
    BINDING_TTL = 900

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        providers: ProviderRegistry,
        settings: SettingsService,
    ) -> None:
        self.session = session
        self.redis = redis
        self.providers = providers
        self.settings = settings
        self.repo = CardRepository(session)

    async def binding_providers(self) -> list[str]:
        s = await self.settings.snapshot()
        return [
            p.code for p in self.providers.enabled(s.enabled_providers) if p.supports_card_binding
        ]

    async def list_page(self, user: User) -> list[PayoutCard]:
        return await self.repo.list_active(user.id)

    async def start_binding(self, user: User) -> str:
        codes = await self.binding_providers()
        if not codes:
            raise DomainError(texts.NO_PAYOUT_PROVIDER)
        if len(await self.repo.list_active(user.id)) >= self.MAX_CARDS:
            raise DomainError(texts.CARD_LIMIT.format(limit=self.MAX_CARDS))
        provider = self.providers.get(codes[0])
        reference = uuid.uuid4().hex
        await self.redis.set(
            f"card_binding:{reference}", f"{user.id}:{provider.code}", ex=self.BINDING_TTL
        )
        return await provider.create_card_binding(reference=reference)

    async def add_manual_card(self, user: User, pan: str) -> PayoutCard:
        """Chatda kiritilgan kartani saqlaydi (qo‘lda o‘tkazish rejimi, provayder yo‘q)."""
        full = re.sub(r"\D", "", pan or "")
        if len(full) != 16:
            raise DomainError(texts.WITHDRAW_CARD_INVALID)
        card = await self.repo.get_by_token(MANUAL_CODE, full)
        if card is not None and card.user_id != user.id:
            raise DomainError("Bu karta boshqa foydalanuvchiga ulangan.")
        if card is None:
            if len(await self.repo.list_active(user.id)) >= self.MAX_CARDS:
                raise DomainError(texts.CARD_LIMIT.format(limit=self.MAX_CARDS))
            card = PayoutCard(
                user_id=user.id, provider=MANUAL_CODE, token=full, masked_pan=mask_card(full)
            )
            self.session.add(card)
        else:
            card.is_active = True
        await self.session.commit()
        return card

    async def manual_pan(self, card_id: int | None) -> str | None:
        """Qo‘lda rejimdagi kartaning to‘liq raqami — faqat admin o‘tkazmasi uchun."""
        if card_id is None:
            return None
        card = await self.session.get(PayoutCard, card_id)
        if card is None or card.provider != MANUAL_CODE:
            return None
        return card.token

    async def complete_binding(
        self, provider_code: str, reference: str, token: str | None, mask: str | None
    ) -> tuple[PayoutCard, int] | None:
        """Provayder webhookidan: token va maskani saqlaydi. Commit chaqiruvchida."""
        raw = await self.redis.getdel(f"card_binding:{reference}")
        if raw is None or not token or not mask:
            return None
        user_id_str, _, expected_provider = (
            raw.decode() if isinstance(raw, bytes) else raw
        ).partition(":")
        if expected_provider != provider_code:
            return None
        user = await UserRepository(self.session).get(int(user_id_str))
        if user is None:
            return None
        card = await self.repo.get_by_token(provider_code, token)
        if card is None:
            card = PayoutCard(
                user_id=user.id, provider=provider_code, token=token, masked_pan=mask[:32]
            )
            self.session.add(card)
        elif card.user_id == user.id:
            card.is_active = True
        else:
            log.warning("Karta tokeni boshqa foydalanuvchiga tegishli — rad etildi")
            return None
        await self.session.flush()
        return card, user.telegram_id

    async def remove(self, user: User, card_id: int) -> None:
        card = await self.repo.get_active(card_id, user.id)
        if card is None:
            raise NotFoundError("Karta topilmadi.")
        card.is_active = False
        await self.session.commit()
