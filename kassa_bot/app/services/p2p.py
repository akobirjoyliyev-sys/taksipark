"""P2P depozit: noyob summa → foydalanuvchi kartaga o‘tkazadi → userbot bank xabarini o‘qiydi →
summa mos kelsa → manzilga tushiriladi.

Manzillar (`target`): `game` — Mob-Cash `deposit` orqali o‘yin hisobiga; `wallet` — Mob-Cash
ishtirokisiz, to‘g‘ridan-to‘g‘ri bot hamyoniga (ledger yozuvi bilan).

Xavfsizlik qoidalari:
* bir vaqtda kutilayotgan ikki to‘lov bir xil summaga ega bo‘lmaydi (DB partial unique index);
  muddati o‘tgan summalar ham `P2P_LATE_GRACE_HOURS` davomida qayta berilmaydi —
  kechikib kelgan to‘lov boshqa foydalanuvchiga tushib qolmasin;
* bank xabari bir marta qayta ishlanadi (UNIQUE account+chat+message);
* Mob-Cash javobi noaniq bo‘lsa (timeout) depozit qayta yuborilmaydi — `review` holatiga
  o‘tadi va admin Mob-Cash panelida tekshiradi (ikki marta tushirib yubormaslik uchun).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import texts
from app.config import Config
from app.core.enums import (
    ACTIVE_P2P_STATUSES,
    BankTxStatus,
    LedgerAccount,
    LedgerDirection,
    LedgerReason,
    P2PDepositStatus,
    P2PDepositTarget,
)
from app.core.errors import DomainError, InsufficientFundsError, NotFoundError
from app.core.money import fmt_money, percent_of, q
from app.core.utils import utcnow
from app.mobcash import AgentClient, MobCashClient, MobCashError, MobCashErrorKind
from app.models import BankTransaction, P2PCard, P2PDeposit, User
from app.p2p.parser import ParsedTx
from app.repositories.wallets import WalletRepository
from app.services.audit import Actor, AuditService, jsonable
from app.services.bookmakers import BookmakerService
from app.services.ledger import LedgerService
from app.services.settings import SettingsService

log = logging.getLogger(__name__)

IN_PROGRESS = "in_progress"
MAX_CREDIT_ATTEMPTS = 5
CLOCK_SKEW = timedelta(minutes=2)


@dataclass(slots=True)
class P2POutcome:
    """Foydalanuvchiga xabar berish kerak bo‘lgan holat o‘zgarishi."""

    deposit: P2PDeposit
    user_telegram_id: int
    event: str  # credited | review | retry | expired
    late: bool = False
    late_grace_hours: int = 24


@dataclass(slots=True)
class BankMatch:
    tx: BankTransaction
    deposit: P2PDeposit | None
    late: bool = False


def mobcash_user_error(exc: MobCashError) -> str:
    """Mob-Cash xatosini foydalanuvchiga ko‘rsatiladigan xavfsiz matnga aylantiradi."""
    if exc.kind == MobCashErrorKind.REJECTED:
        return texts.MC_PAYER_NOT_FOUND
    return texts.MC_UNAVAILABLE


class P2PService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        settings: SettingsService,
        mobcash: MobCashClient | None,
        config: Config,
        bookmakers: BookmakerService | None = None,
    ) -> None:
        self.session = session
        self.redis = redis
        self.settings = settings
        self.mobcash = mobcash
        self.config = config
        self.bookmakers = bookmakers or BookmakerService(session, redis, config, settings, mobcash)
        self.wallets = WalletRepository(session)
        self.ledger = LedgerService(session)

    async def _client(self, bookmaker_id: int | None) -> MobCashClient | AgentClient:
        return await self.bookmakers.money_client(bookmaker_id)

    # ================================================================== kartalar
    async def list_cards(self) -> list[P2PCard]:
        return list(await self.session.scalars(select(P2PCard).order_by(P2PCard.id)))

    async def active_cards(self) -> list[P2PCard]:
        stmt = select(P2PCard).where(P2PCard.is_active.is_(True)).order_by(P2PCard.id)
        return list(await self.session.scalars(stmt))

    async def get_card(self, card_id: int) -> P2PCard:
        card = await self.session.get(P2PCard, card_id)
        if card is None:
            raise NotFoundError("Karta topilmadi.")
        return card

    async def add_card(self, number: str, holder: str, bank: str, actor: Actor) -> P2PCard:
        digits = "".join(ch for ch in number if ch.isdigit())
        if len(digits) != 16:
            raise DomainError("Karta raqami 16 ta raqamdan iborat bo‘lishi kerak.")
        exists = await self.session.scalar(select(P2PCard).where(P2PCard.number == digits))
        if exists is not None:
            raise DomainError("Bu karta allaqachon qo‘shilgan.")
        card = P2PCard(number=digits, holder=holder.strip()[:128], bank=bank.strip()[:32])
        self.session.add(card)
        await self.session.flush()
        await AuditService(self.session).log(
            actor, "p2p.card_add", "p2p_card", card.id, after={"last4": card.last4}
        )
        await self.session.commit()
        return card

    async def toggle_card(self, card_id: int, actor: Actor) -> P2PCard:
        card = await self.get_card(card_id)
        card.is_active = not card.is_active
        await AuditService(self.session).log(
            actor, "p2p.card_toggle", "p2p_card", card.id, after={"is_active": card.is_active}
        )
        await self.session.commit()
        return card

    async def delete_card(self, card_id: int, actor: Actor) -> None:
        card = await self.get_card(card_id)
        await AuditService(self.session).log(
            actor, "p2p.card_delete", "p2p_card", card.id, before={"last4": card.last4}
        )
        await self.session.delete(card)
        await self.session.commit()

    # ================================================================== foydalanuvchi oqimi
    async def check_payer(self, payer_id: str, bookmaker_id: int | None = None) -> str:
        """O‘yin akkauntini Mob-Cash'da tekshiradi (depozitdan oldin majburiy)."""
        if bookmaker_id is not None:
            await self.bookmakers.get_active(bookmaker_id)
        client = await self._client(bookmaker_id)
        try:
            return await client.payer_nickname(payer_id)
        except MobCashError as exc:
            log.info("payerNickname xato payer=%s: %s", payer_id, exc.message)
            raise DomainError(mobcash_user_error(exc)) from exc

    async def pending_for_user(
        self, user: User, target: P2PDepositTarget = P2PDepositTarget.GAME
    ) -> P2PDeposit | None:
        stmt = (
            select(P2PDeposit)
            .where(
                P2PDeposit.user_id == user.id,
                P2PDeposit.status == P2PDepositStatus.PENDING,
                P2PDeposit.target == target,
            )
            .order_by(P2PDeposit.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def _used_amounts(self, low: Decimal, high: Decimal) -> set[Decimal]:
        grace_from = utcnow() - timedelta(hours=self.config.p2p_late_grace_hours)
        stmt = select(P2PDeposit.unique_amount).where(
            P2PDeposit.unique_amount >= low,
            P2PDeposit.unique_amount <= high,
            or_(
                P2PDeposit.status == P2PDepositStatus.PENDING,
                and_(
                    P2PDeposit.status.in_((P2PDepositStatus.EXPIRED, P2PDepositStatus.CANCELLED)),
                    P2PDeposit.expires_at > grace_from,
                ),
            ),
        )
        return {q(v) for v in await self.session.scalars(stmt)}

    async def pick_unique_amount(self, base: Decimal) -> Decimal:
        """`base`ga 1..P2P_UNIQUE_MAX so‘m qo‘shib, hozir band bo‘lmagan summani tanlaydi."""
        span = max(self.config.p2p_unique_max, 1)
        used = await self._used_amounts(base + 1, base + span)
        free = [base + k for k in range(1, span + 1) if q(base + k) not in used]
        if not free:
            raise DomainError(texts.MC_AMOUNT_BUSY)
        return q(secrets.choice(free))

    async def create(
        self,
        user: User,
        payer_id: str,
        nickname: str,
        amount: Decimal,
        *,
        target: P2PDepositTarget = P2PDepositTarget.GAME,
        bookmaker_id: int | None = None,
    ) -> P2PDeposit:
        s = await self.settings.snapshot()
        if target == P2PDepositTarget.WALLET:
            bookmaker_id = None
        elif bookmaker_id is not None:
            await self.bookmakers.get_active(bookmaker_id)
        base = amount.quantize(Decimal(1), rounding=ROUND_DOWN)
        if not s.deposit_min <= base <= s.deposit_max:
            raise DomainError(
                texts.AMOUNT_OUT_OF_RANGE.format(
                    min=fmt_money(s.deposit_min), max=fmt_money(s.deposit_max)
                )
            )
        pending = await self.pending_for_user(user, target)
        if pending is not None:
            raise DomainError(texts.MC_DEP_HAS_PENDING.format(id=pending.id))
        cards = await self.active_cards()
        if not cards:
            raise DomainError(texts.MC_NO_CARDS)
        # Rollback sessiyadagi obyektlarni eskirtiradi — idlarni oldindan olib qo‘yamiz.
        user_id, card_id = user.id, secrets.choice(cards).id

        for _ in range(3):
            unique = await self.pick_unique_amount(base)
            deposit = P2PDeposit(
                user_id=user_id,
                bookmaker_id=bookmaker_id,
                target=target,
                payer_id=payer_id,
                payer_nickname=nickname[:128],
                amount=q(base),
                unique_amount=unique,
                card_id=card_id,
                status=P2PDepositStatus.PENDING,
                expires_at=utcnow() + timedelta(minutes=s.payment_expiry_minutes),
            )
            self.session.add(deposit)
            try:
                await self.session.commit()
            except IntegrityError:
                # Parallel so‘rov xuddi shu summani band qildi — boshqasini tanlaymiz.
                await self.session.rollback()
                await self.session.refresh(user)
                continue
            if target == P2PDepositTarget.GAME:
                user.remember_payer_id(bookmaker_id, payer_id)
                await self.session.commit()
            return deposit
        raise DomainError(texts.MC_AMOUNT_BUSY)

    def expected_credit(self, deposit: P2PDeposit, fee_percent: Decimal) -> Decimal:
        return q(deposit.unique_amount - percent_of(deposit.unique_amount, fee_percent))

    async def create_wallet_funded(
        self,
        user: User,
        payer_id: str,
        nickname: str,
        amount: Decimal,
        *,
        bookmaker_id: int | None = None,
    ) -> P2PDeposit:
        """Hamyon balansidan o‘yin hisobini to‘ldirish (kartasiz, darhol tushiriladi).

        Karta kutilmaydi: pul hamyondan darhol yechiladi (ledger DEBIT), depozit `paid`
        holatida yaratiladi va chaqiruvchi `credit()` orqali Mob-Cash'ga tushiradi.
        Hamyon parol bilan bloklanadi — balans tekshiruvi va yechish atomar.
        """
        s = await self.settings.snapshot()
        await self.bookmakers.get_active(bookmaker_id)
        base = q(amount)
        if not s.deposit_min <= base <= s.deposit_max:
            raise DomainError(
                texts.AMOUNT_OUT_OF_RANGE.format(
                    min=fmt_money(s.deposit_min), max=fmt_money(s.deposit_max)
                )
            )
        wallet = await self.wallets.get_for_update(user.id)
        if wallet.available < base:
            raise InsufficientFundsError(
                texts.WITHDRAW_INSUFFICIENT.format(available=fmt_money(wallet.available))
            )
        deposit = P2PDeposit(
            user_id=user.id,
            bookmaker_id=bookmaker_id,
            target=P2PDepositTarget.GAME,
            payer_id=payer_id,
            payer_nickname=nickname[:128],
            amount=base,
            unique_amount=base,
            credit_amount=base,
            status=P2PDepositStatus.PAID,
            expires_at=utcnow(),
            paid_at=utcnow(),
        )
        self.session.add(deposit)
        await self.session.flush()
        await self.ledger.post(
            wallet=wallet,
            account=LedgerAccount.MAIN,
            direction=LedgerDirection.DEBIT,
            amount=base,
            reason=LedgerReason.GAME_DEPOSIT,
            idempotency_key=f"p2p:{deposit.id}:wallet_fund",
            reference_type="p2p_deposit",
            reference_id=deposit.id,
            actor_telegram_id=user.telegram_id,
        )
        user.remember_payer_id(bookmaker_id, payer_id)
        await AuditService(self.session).log(
            Actor.user(user.telegram_id),
            "p2p.wallet_funded",
            "p2p_deposit",
            deposit.id,
            after={"amount": base, "payer_id": payer_id, "bookmaker_id": bookmaker_id},
        )
        await self.session.commit()
        return deposit

    async def get(self, deposit_id: int, *, for_update: bool = False) -> P2PDeposit | None:
        stmt = select(P2PDeposit).where(P2PDeposit.id == deposit_id)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(stmt)

    async def get_for_user(self, user: User, deposit_id: int) -> P2PDeposit:
        deposit = await self.get(deposit_id)
        if deposit is None or deposit.user_id != user.id:
            raise NotFoundError("To‘lov topilmadi.")
        return deposit

    async def cancel(self, user: User, deposit_id: int) -> P2PDeposit:
        deposit = await self.get(deposit_id, for_update=True)
        if deposit is None or deposit.user_id != user.id:
            raise NotFoundError("To‘lov topilmadi.")
        if deposit.status != P2PDepositStatus.PENDING:
            raise DomainError(
                texts.MC_DEP_CANNOT_CANCEL.format(
                    status=texts.mc_status(deposit.target, deposit.status)
                )
            )
        deposit.status = P2PDepositStatus.CANCELLED
        deposit.last_error = "cancelled_by_user"
        await self.session.commit()
        return deposit

    async def set_message_id(self, deposit: P2PDeposit, message_id: int) -> None:
        deposit.chat_message_id = message_id
        await self.session.commit()

    async def list_for_user(self, user: User, limit: int = 10) -> list[P2PDeposit]:
        stmt = (
            select(P2PDeposit)
            .where(P2PDeposit.user_id == user.id)
            .order_by(P2PDeposit.id.desc())
            .limit(limit)
        )
        return list(await self.session.scalars(stmt))

    async def card_for(self, deposit: P2PDeposit) -> P2PCard | None:
        return await self.session.get(P2PCard, deposit.card_id) if deposit.card_id else None

    # ================================================================== bank xabari
    async def _card_filter(self, card_last4: str | None) -> list[int] | None:
        """Xabardagi karta bizning kartalarimizdan biri bo‘lsa — faqat o‘sha karta depozitlari.

        Karta noma’lum (yo‘q yoki bank formati boshqa kartani ko‘rsatadi) bo‘lsa — cheklov yo‘q,
        aks holda format o‘zgarganda barcha to‘lovlar avtomatik tasdiqlanmay qoladi.
        """
        if not card_last4:
            return None
        ids = [c.id for c in await self.list_cards() if c.number.endswith(card_last4)]
        return ids or None

    async def _find_match(
        self, amount: Decimal, message_date: datetime, card_last4: str | None = None
    ) -> tuple[P2PDeposit | None, bool]:
        # Xabar depozit yaratilishidan oldin kelgan bo‘lsa — bu boshqa (eski) o‘tkazma.
        not_before = message_date + CLOCK_SKEW
        card_ids = await self._card_filter(card_last4)
        card_cond = P2PDeposit.card_id.in_(card_ids) if card_ids else true()
        stmt = (
            select(P2PDeposit)
            .where(
                P2PDeposit.status == P2PDepositStatus.PENDING,
                P2PDeposit.unique_amount == q(amount),
                P2PDeposit.created_at <= not_before,
                card_cond,
            )
            .order_by(P2PDeposit.id)
            .limit(1)
            .with_for_update()
        )
        deposit = await self.session.scalar(stmt)
        if deposit is not None:
            return deposit, False
        grace_from = utcnow() - timedelta(hours=self.config.p2p_late_grace_hours)
        stmt = (
            select(P2PDeposit)
            .where(
                P2PDeposit.status.in_((P2PDepositStatus.EXPIRED, P2PDepositStatus.CANCELLED)),
                P2PDeposit.unique_amount == q(amount),
                P2PDeposit.expires_at > grace_from,
                P2PDeposit.created_at <= not_before,
                card_cond,
            )
            .order_by(P2PDeposit.id.desc())
            .limit(1)
            .with_for_update()
        )
        deposit = await self.session.scalar(stmt)
        return deposit, deposit is not None

    async def _mark_paid(
        self, deposit: P2PDeposit, received: Decimal, tx: BankTransaction | None
    ) -> None:
        s = await self.settings.snapshot()
        deposit.status = P2PDepositStatus.PAID
        deposit.paid_at = utcnow()
        deposit.credit_amount = q(received - percent_of(received, s.deposit_fee_percent))
        deposit.last_error = None
        if tx is not None:
            deposit.bank_tx_id = tx.id
            tx.status = BankTxStatus.MATCHED
            tx.deposit_id = deposit.id

    async def handle_bank_message(
        self,
        *,
        account_id: int | None,
        owner_tg_id: int,
        source_chat_id: int,
        source_name: str,
        message_id: int,
        text: str,
        message_date: datetime | None,
        parsed: ParsedTx,
    ) -> BankMatch | None:
        """Kirim xabarini saqlaydi va kutilayotgan depozitga bog‘laydi. Takroriy xabar — None."""
        when = message_date or utcnow()
        stmt = (
            insert(BankTransaction)
            .values(
                account_id=account_id,
                owner_tg_id=owner_tg_id,
                source_chat_id=source_chat_id,
                source_name=source_name[:64],
                message_id=message_id,
                amount=q(parsed.amount),
                card_last4=parsed.card_last4,
                raw_text=text[:4000],
                status=BankTxStatus.UNMATCHED,
                message_date=when,
            )
            .on_conflict_do_nothing(constraint="uq_bank_transactions_message")
            .returning(BankTransaction.id)
        )
        tx_id = await self.session.scalar(stmt)
        if tx_id is None:
            # Hech narsa yozilmadi; rollback emas — u sessiyadagi obyektlarni eskirtiradi.
            await self.session.commit()
            return None
        tx = await self.session.get(BankTransaction, tx_id)
        assert tx is not None  # noqa: S101
        deposit, late = await self._find_match(parsed.amount, when, parsed.card_last4)
        if deposit is not None:
            before = deposit.status
            await self._mark_paid(deposit, tx.amount, tx)
            await AuditService(self.session).log(
                Actor.system("userbot"),
                "p2p.late_paid" if late else "p2p.paid",
                "p2p_deposit",
                deposit.id,
                before={"status": before},
                after={"amount": tx.amount, "bank_tx": tx.id},
            )
        await self.session.commit()
        return BankMatch(tx=tx, deposit=deposit, late=late)

    # ================================================================== Mob-Cash'ga tushirish
    async def user_telegram_id(self, deposit: P2PDeposit) -> int:
        user = await self.session.get(User, deposit.user_id)
        return user.telegram_id if user else 0

    async def credit(self, deposit_id: int) -> P2POutcome | None:
        """To‘langan depozitni manziliga tushiradi: o‘yin hisobi (Mob-Cash) yoki bot hamyoni."""
        lock_key = f"lock:p2p:credit:{deposit_id}"
        if not await self.redis.set(lock_key, "1", nx=True, ex=180):
            return None  # boshqa jarayon hozir shu depozit ustida ishlayapti
        try:
            return await self._credit_locked(deposit_id)
        finally:
            await self.redis.delete(lock_key)

    async def _credit_locked(self, deposit_id: int) -> P2POutcome | None:
        deposit = await self.get(deposit_id, for_update=True)
        if deposit is None or deposit.status != P2PDepositStatus.PAID:
            await self.session.commit()  # FOR UPDATE lockni bo‘shatish (o‘zgarish yo‘q)
            return None
        tg_id = await self.user_telegram_id(deposit)
        if deposit.target == P2PDepositTarget.WALLET:
            return await self._credit_wallet(deposit, tg_id)
        if deposit.last_error == IN_PROGRESS:
            # Oldingi urinish jarayon to‘xtab qolganda uzilgan: natija noma’lum, takrorlamaymiz.
            deposit.status = P2PDepositStatus.REVIEW
            deposit.last_error = "Oldingi Mob-Cash so‘rovi natijasi noma’lum — panelda tekshiring"
            await self.session.commit()
            return P2POutcome(deposit, tg_id, "review")
        try:
            client = await self._client(deposit.bookmaker_id)
        except DomainError as exc:
            deposit.last_error = exc.message[:500]
            await self.session.commit()
            return None

        amount = deposit.credit_amount or deposit.unique_amount
        deposit.credit_attempts += 1
        deposit.last_error = IN_PROGRESS
        await self.session.commit()
        try:
            result = await client.deposit(deposit.payer_id, amount)
        except MobCashError as exc:
            deposit = await self.get(deposit_id, for_update=True)
            assert deposit is not None  # noqa: S101
            retryable = exc.kind in (
                MobCashErrorKind.NETWORK,
                MobCashErrorKind.AUTH,
                MobCashErrorKind.CONFIG,
            )
            deposit.last_error = exc.message[:500]
            if retryable and deposit.credit_attempts < MAX_CREDIT_ATTEMPTS:
                event = "retry"
            else:
                deposit.status = P2PDepositStatus.REVIEW
                event = "review"
            log.warning(
                "Mob-Cash deposit xato dep=%s kind=%s: %s", deposit.id, exc.kind, exc.message
            )
            await self.session.commit()
            return P2POutcome(deposit, tg_id, event)

        deposit = await self.get(deposit_id, for_update=True)
        assert deposit is not None  # noqa: S101
        deposit.status = P2PDepositStatus.CREDITED
        deposit.credited_at = utcnow()
        deposit.mobcash_result = jsonable(result)
        deposit.last_error = None
        await AuditService(self.session).log(
            Actor.system("mobcash"),
            "p2p.credited",
            "p2p_deposit",
            deposit.id,
            after={"payer_id": deposit.payer_id, "amount": amount},
        )
        await self.session.commit()
        return P2POutcome(deposit, tg_id, "credited")

    async def _credit_wallet(self, deposit: P2PDeposit, tg_id: int) -> P2POutcome:
        """Hamyon to‘ldirishni Mob-Cash ishtirokisiz to‘g‘ridan-to‘g‘ri hamyonga yozadi.

        Ledger `idempotency_key` takroriy tushirishdan himoya qiladi; status va balans
        bitta tranzaksiyada commit qilinadi.
        """
        amount = deposit.credit_amount or deposit.unique_amount
        wallet = await self.wallets.get_for_update(deposit.user_id)
        await self.ledger.post(
            wallet=wallet,
            account=LedgerAccount.MAIN,
            direction=LedgerDirection.CREDIT,
            amount=amount,
            reason=LedgerReason.DEPOSIT,
            idempotency_key=f"p2p:{deposit.id}:wallet",
            reference_type="p2p_deposit",
            reference_id=deposit.id,
        )
        wallet.total_deposit += amount
        deposit.status = P2PDepositStatus.CREDITED
        deposit.credited_at = utcnow()
        deposit.last_error = None
        await AuditService(self.session).log(
            Actor.system("wallet"),
            "p2p.credited",
            "p2p_deposit",
            deposit.id,
            after={"target": deposit.target.value, "amount": amount},
        )
        await self.session.commit()
        return P2POutcome(deposit, tg_id, "credited")

    async def credit_due(self, limit: int = 20) -> list[P2POutcome]:
        stmt = (
            select(P2PDeposit.id)
            .where(P2PDeposit.status == P2PDepositStatus.PAID)
            .order_by(P2PDeposit.id)
            .limit(limit)
        )
        outcomes = []
        for deposit_id in list(await self.session.scalars(stmt)):
            outcome = await self.credit(deposit_id)
            if outcome is not None:
                outcomes.append(outcome)
        return outcomes

    async def expire_due(self, limit: int = 100) -> list[P2POutcome]:
        stmt = (
            select(P2PDeposit)
            .where(
                P2PDeposit.status == P2PDepositStatus.PENDING,
                P2PDeposit.expires_at < utcnow(),
            )
            .order_by(P2PDeposit.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        expired = list(await self.session.scalars(stmt))
        for deposit in expired:
            deposit.status = P2PDepositStatus.EXPIRED
            deposit.last_error = "timeout"
        await self.session.commit()
        hours = self.config.p2p_late_grace_hours
        return [
            P2POutcome(d, await self.user_telegram_id(d), "expired", late_grace_hours=hours)
            for d in expired
        ]

    # ================================================================== admin
    async def list_by_status(
        self, statuses: tuple[P2PDepositStatus, ...], limit: int, offset: int = 0
    ) -> list[P2PDeposit]:
        stmt = (
            select(P2PDeposit)
            .where(P2PDeposit.status.in_(statuses))
            .order_by(P2PDeposit.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(stmt))

    async def counts(self) -> dict[P2PDepositStatus, int]:
        stmt = (
            select(P2PDeposit.status, func.count(P2PDeposit.id))
            .where(P2PDeposit.status.in_(ACTIVE_P2P_STATUSES))
            .group_by(P2PDeposit.status)
        )
        return {status: int(n) for status, n in (await self.session.execute(stmt)).all()}

    async def credited_since(self, since: datetime) -> tuple[int, Decimal]:
        stmt = select(
            func.count(P2PDeposit.id), func.coalesce(func.sum(P2PDeposit.credit_amount), 0)
        ).where(P2PDeposit.status == P2PDepositStatus.CREDITED, P2PDeposit.credited_at >= since)
        count, total = (await self.session.execute(stmt)).one()
        return int(count), Decimal(total)

    async def _admin_get(self, deposit_id: int) -> P2PDeposit:
        deposit = await self.get(deposit_id, for_update=True)
        if deposit is None:
            raise NotFoundError("To‘lov topilmadi.")
        return deposit

    async def admin_confirm_paid(self, deposit_id: int, actor: Actor) -> P2PDeposit:
        """Userbot ko‘rmagan to‘lovni admin qo‘lda tasdiqlaydi (bank ilovasida ko‘rgach)."""
        deposit = await self._admin_get(deposit_id)
        allowed = (P2PDepositStatus.PENDING, P2PDepositStatus.EXPIRED, P2PDepositStatus.CANCELLED)
        if deposit.status not in allowed:
            raise DomainError(f"Holat mos emas: {texts.mc_status(deposit.target, deposit.status)}")
        before = deposit.status
        await self._mark_paid(deposit, deposit.unique_amount, None)
        deposit.reviewed_by = actor.telegram_id
        await AuditService(self.session).log(
            actor, "p2p.manual_paid", "p2p_deposit", deposit.id, before={"status": before}
        )
        await self.session.commit()
        return deposit

    async def admin_retry(self, deposit_id: int, actor: Actor) -> P2PDeposit:
        """Admin Mob-Cash panelida pul tushmaganini tekshirgach, qayta yuborish."""
        deposit = await self._admin_get(deposit_id)
        if deposit.status != P2PDepositStatus.REVIEW:
            raise DomainError("Faqat tekshiruvdagi to‘lovni qayta yuborish mumkin.")
        deposit.status = P2PDepositStatus.PAID
        deposit.last_error = None
        deposit.reviewed_by = actor.telegram_id
        await AuditService(self.session).log(actor, "p2p.retry", "p2p_deposit", deposit.id)
        await self.session.commit()
        return deposit

    async def admin_mark_credited(self, deposit_id: int, actor: Actor) -> P2PDeposit:
        deposit = await self._admin_get(deposit_id)
        if deposit.status not in (P2PDepositStatus.REVIEW, P2PDepositStatus.PAID):
            raise DomainError(f"Holat mos emas: {texts.mc_status(deposit.target, deposit.status)}")
        deposit.status = P2PDepositStatus.CREDITED
        deposit.credited_at = utcnow()
        deposit.last_error = None
        deposit.reviewed_by = actor.telegram_id
        await AuditService(self.session).log(
            actor, "p2p.manual_credited", "p2p_deposit", deposit.id
        )
        await self.session.commit()
        return deposit

    async def admin_reject(self, deposit_id: int, actor: Actor, comment: str) -> P2PDeposit:
        deposit = await self._admin_get(deposit_id)
        if deposit.status == P2PDepositStatus.CREDITED:
            raise DomainError("Hisobga tushirilgan to‘lovni rad etib bo‘lmaydi.")
        before = deposit.status
        deposit.status = P2PDepositStatus.REJECTED
        deposit.last_error = comment[:500] or "rejected"
        deposit.reviewed_by = actor.telegram_id
        if self._wallet_funded(deposit):
            # Hamyondan moliyalashtirilgan: pul foydalanuvchiga qaytarilmasa yo‘qoladi.
            wallet = await self.wallets.get_for_update(deposit.user_id)
            await self.ledger.post(
                wallet=wallet,
                account=LedgerAccount.MAIN,
                direction=LedgerDirection.CREDIT,
                amount=deposit.credit_amount or deposit.unique_amount,
                reason=LedgerReason.GAME_DEPOSIT_REFUND,
                idempotency_key=f"p2p:{deposit.id}:wallet_refund",
                reference_type="p2p_deposit",
                reference_id=deposit.id,
                actor_telegram_id=actor.telegram_id,
                comment=comment[:200] or None,
            )
        await AuditService(self.session).log(
            actor,
            "p2p.reject",
            "p2p_deposit",
            deposit.id,
            before={"status": before},
            comment=comment,
        )
        await self.session.commit()
        return deposit

    @staticmethod
    def _wallet_funded(deposit: P2PDeposit) -> bool:
        """O‘yin depoziti karta kutilmasdan hamyondan moliyalashtirilganmi."""
        return deposit.target == P2PDepositTarget.GAME and deposit.card_id is None

    # ---------------------------------------------------------------- mos kelmagan kirimlar
    async def unmatched(self, limit: int, offset: int = 0) -> list[BankTransaction]:
        stmt = (
            select(BankTransaction)
            .where(BankTransaction.status == BankTxStatus.UNMATCHED)
            .order_by(BankTransaction.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(await self.session.scalars(stmt))

    async def get_tx(self, tx_id: int) -> BankTransaction:
        tx = await self.session.get(BankTransaction, tx_id)
        if tx is None:
            raise NotFoundError("Tranzaksiya topilmadi.")
        return tx

    async def link_transaction(self, tx_id: int, deposit_id: int, actor: Actor) -> P2PDeposit:
        """Mos kelmagan kirimni (masalan, noto‘g‘ri summa) depozitga qo‘lda bog‘lash.

        Mob-Cash'ga haqiqatda kelgan summa (komissiyasiz) tushiriladi.
        """
        stmt = (
            select(BankTransaction)
            .where(BankTransaction.id == tx_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tx = await self.session.scalar(stmt)
        if tx is None or tx.status != BankTxStatus.UNMATCHED:
            raise DomainError("Tranzaksiya topilmadi yoki allaqachon bog‘langan.")
        deposit = await self._admin_get(deposit_id)
        allowed = (P2PDepositStatus.PENDING, P2PDepositStatus.EXPIRED, P2PDepositStatus.CANCELLED)
        if deposit.status not in allowed:
            raise DomainError(
                f"Depozit holati mos emas: {texts.mc_status(deposit.target, deposit.status)}"
            )
        before = deposit.status
        await self._mark_paid(deposit, tx.amount, tx)
        deposit.reviewed_by = actor.telegram_id
        await AuditService(self.session).log(
            actor,
            "p2p.link_tx",
            "p2p_deposit",
            deposit.id,
            before={"status": before, "unique_amount": deposit.unique_amount},
            after={"bank_tx": tx.id, "received": tx.amount},
        )
        await self.session.commit()
        return deposit

    async def ignore_transaction(self, tx_id: int, actor: Actor) -> None:
        tx = await self.get_tx(tx_id)
        if tx.status != BankTxStatus.UNMATCHED:
            raise DomainError("Tranzaksiya allaqachon qayta ishlangan.")
        tx.status = BankTxStatus.IGNORED
        await AuditService(self.session).log(actor, "p2p.tx_ignore", "bank_tx", tx.id)
        await self.session.commit()
