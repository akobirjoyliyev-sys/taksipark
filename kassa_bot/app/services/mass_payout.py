"""Ommaviy to‘lov: CSV → preview/validatsiya → tasdiq → payout navbati."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    MassBatchStatus,
    MassItemStatus,
    WithdrawalSource,
    WithdrawalStatus,
)
from app.core.errors import DomainError, NotFoundError, PermissionDeniedError
from app.core.money import q
from app.core.permissions import Perm, has_perm
from app.core.utils import utcnow
from app.models import MassPayoutBatch, MassPayoutItem, Withdrawal
from app.models.withdrawal import WithdrawalStatusHistory
from app.payments.registry import ProviderRegistry
from app.repositories.payments import CardRepository
from app.repositories.users import UserRepository
from app.services.audit import Actor, AuditService
from app.services.settings import SettingsService

MAX_FILE_BYTES = 512 * 1024
MAX_ROWS = 1000
DUPLICATE_WINDOW = timedelta(hours=24)
REQUIRED_COLUMNS = ("telegram_id", "amount", "provider")

CSV_HELP = (
    "CSV fayl ustunlari (birinchi qator sarlavha):\n"
    "<code>telegram_id,amount,provider</code>\n"
    "<code>123456789,50000,sandbox</code>\n\n"
    "• Pul oluvchining botda ulangan (tokenlashtirilgan) kartasi bo‘lishi shart.\n"
    "• Maksimal 1000 qator, 512 KB.\n"
    "• Fayl avval preview qilinadi, tasdiqsiz hech narsa yuborilmaydi."
)


@dataclass(slots=True)
class ParsedRow:
    line_no: int
    telegram_id: int | None
    amount: Decimal | None
    provider: str | None
    error: str | None


def parse_csv(content: bytes) -> list[ParsedRow]:
    if len(content) > MAX_FILE_BYTES:
        raise DomainError("Fayl juda katta (maks. 512 KB).")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DomainError("Fayl UTF-8 formatida bo‘lishi kerak.") from exc
    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    if any(col not in headers for col in REQUIRED_COLUMNS):
        raise DomainError("Sarlavha noto‘g‘ri. Kerak: telegram_id,amount,provider")
    reader.fieldnames = headers
    rows: list[ParsedRow] = []
    for index, raw in enumerate(reader, start=2):
        if len(rows) >= MAX_ROWS:
            raise DomainError(f"Qatorlar soni {MAX_ROWS} dan oshmasin.")
        tg_raw = (raw.get("telegram_id") or "").strip()
        amount_raw = (raw.get("amount") or "").strip().replace(" ", "")
        provider = (raw.get("provider") or "").strip().lower() or None
        error = None
        telegram_id = int(tg_raw) if tg_raw.isdigit() else None
        if telegram_id is None:
            error = "telegram_id noto‘g‘ri"
        try:
            amount: Decimal | None = q(Decimal(amount_raw))
            if amount is not None and amount <= 0:
                error = error or "summa musbat bo‘lishi kerak"
        except InvalidOperation:
            amount = None
            error = error or "summa noto‘g‘ri"
        if not provider:
            error = error or "provider ko‘rsatilmagan"
        rows.append(ParsedRow(index, telegram_id, amount, provider, error))
    if not rows:
        raise DomainError("Faylda ma’lumot yo‘q.")
    return rows


def fingerprint(telegram_id: int, amount: Decimal, provider: str) -> str:
    return hashlib.sha256(f"{telegram_id}|{amount}|{provider}".encode()).hexdigest()[:40]


class MassPayoutService:
    def __init__(
        self, session: AsyncSession, providers: ProviderRegistry, settings: SettingsService
    ) -> None:
        self.session = session
        self.providers = providers
        self.settings = settings
        self.audit = AuditService(session)

    async def create_preview(self, content: bytes, file_name: str, actor: Actor) -> MassPayoutBatch:
        rows = parse_csv(content)
        s = await self.settings.snapshot()
        users = UserRepository(self.session)
        cards = CardRepository(self.session)
        batch = MassPayoutBatch(file_name=file_name[:128], created_by=actor.telegram_id or 0)
        self.session.add(batch)
        await self.session.flush()

        seen: set[str] = set()
        since = utcnow() - DUPLICATE_WINDOW
        total = Decimal(0)
        counts = {MassItemStatus.VALID: 0, MassItemStatus.INVALID: 0, MassItemStatus.DUPLICATE: 0}
        for row in rows:
            item = MassPayoutItem(
                batch_id=batch.id,
                line_no=row.line_no,
                recipient_telegram_id=row.telegram_id,
                amount=row.amount,
                provider=row.provider,
                status=MassItemStatus.VALID,
            )
            error = row.error
            if error is None and row.telegram_id and row.amount and row.provider:
                provider = self.providers.find(row.provider)
                user = await users.get_by_telegram_id(row.telegram_id)
                if provider is None or row.provider not in s.enabled_providers:
                    error = "provayder faol emas"
                elif not provider.supports_payout:
                    error = "provayder payoutni qo‘llamaydi"
                elif user is None:
                    error = "foydalanuvchi topilmadi"
                elif user.is_banned:
                    error = "foydalanuvchi bloklangan"
                elif not s.withdraw_min <= row.amount <= s.withdraw_max:
                    error = "summa limitdan tashqarida"
                elif await cards.first_active_for_provider(user.id, row.provider) is None:
                    error = "ulangan karta yo‘q"
                else:
                    item.user_id = user.id
                    fp = fingerprint(row.telegram_id, row.amount, row.provider)
                    item.fingerprint = fp
                    recent_dup = await self.session.scalar(
                        select(func.count(MassPayoutItem.id))
                        .join(MassPayoutBatch, MassPayoutBatch.id == MassPayoutItem.batch_id)
                        .where(
                            MassPayoutItem.fingerprint == fp,
                            MassPayoutItem.created_at >= since,
                            MassPayoutBatch.status != MassBatchStatus.CANCELLED,
                            MassPayoutItem.status.in_(
                                (MassItemStatus.VALID, MassItemStatus.QUEUED, MassItemStatus.PAID)
                            ),
                        )
                    )
                    if fp in seen:
                        item.status = MassItemStatus.DUPLICATE
                        error = "faylda takrorlangan"
                    elif recent_dup:
                        item.status = MassItemStatus.DUPLICATE
                        error = "so‘nggi 24 soatda shu to‘lov bor"
                    seen.add(fp)
            if error and item.status == MassItemStatus.VALID:
                item.status = MassItemStatus.INVALID
            item.error = error
            counts[item.status] += 1
            if item.status == MassItemStatus.VALID and row.amount:
                total += row.amount
            self.session.add(item)

        batch.total_rows = len(rows)
        batch.valid_rows = counts[MassItemStatus.VALID]
        batch.invalid_rows = counts[MassItemStatus.INVALID]
        batch.duplicate_rows = counts[MassItemStatus.DUPLICATE]
        batch.total_amount = total
        await self.audit.log(
            actor,
            "mass.preview",
            "mass_batch",
            batch.id,
            after={"file": file_name, "rows": len(rows), "valid": batch.valid_rows, "total": total},
        )
        await self.session.commit()
        return batch

    async def get(self, batch_id: int, *, for_update: bool = False) -> MassPayoutBatch:
        batch = await self.session.get(MassPayoutBatch, batch_id, with_for_update=for_update)
        if batch is None:
            raise NotFoundError("Partiya topilmadi.")
        return batch

    async def list_page(self, page: int, per_page: int = 8) -> list[MassPayoutBatch]:
        stmt = (
            select(MassPayoutBatch)
            .order_by(MassPayoutBatch.id.desc())
            .limit(per_page)
            .offset(page * per_page)
        )
        return list(await self.session.scalars(stmt))

    async def items(self, batch_id: int, limit: int | None = None) -> list[MassPayoutItem]:
        stmt = (
            select(MassPayoutItem)
            .where(MassPayoutItem.batch_id == batch_id)
            .order_by(MassPayoutItem.line_no)
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(await self.session.scalars(stmt))

    async def item_counts(self, batch_id: int) -> dict[MassItemStatus, int]:
        stmt = (
            select(MassPayoutItem.status, func.count(MassPayoutItem.id))
            .where(MassPayoutItem.batch_id == batch_id)
            .group_by(MassPayoutItem.status)
        )
        return {r[0]: int(r[1]) for r in await self.session.execute(stmt)}

    async def approve(self, batch_id: int, actor: Actor) -> MassPayoutBatch:
        """Operator yoki superadmin tasdig‘i; yaratuvchi o‘z partiyasini tasdiqlay olmaydi
        (superadmin bundan mustasno)."""
        if not has_perm(actor.role, Perm.MASS_APPROVE):
            raise PermissionDeniedError("Tasdiqlash faqat operator yoki superadmin uchun.")
        batch = await self.get(batch_id, for_update=True)
        if batch.status != MassBatchStatus.PREVIEW:
            raise DomainError("Partiya allaqachon ko‘rib chiqilgan.")
        if batch.created_by == actor.telegram_id and actor.role != "superadmin":
            raise PermissionDeniedError(
                "O‘zingiz yuklagan partiyani boshqa xodim tasdiqlashi kerak."
            )
        if batch.valid_rows == 0:
            raise DomainError("Yuboriladigan to‘g‘ri qator yo‘q.")
        s = await self.settings.snapshot()
        cards = CardRepository(self.session)
        now = utcnow()
        queued = 0
        for item in await self.items(batch.id):
            if item.status != MassItemStatus.VALID or not item.user_id or not item.amount:
                continue
            card = await cards.first_active_for_provider(item.user_id, item.provider or "")
            if card is None:
                item.status = MassItemStatus.INVALID
                item.error = "karta o‘chirilgan"
                batch.valid_rows -= 1
                batch.invalid_rows += 1
                batch.total_amount -= item.amount
                continue
            provider = self.providers.get(card.provider)
            withdrawal = Withdrawal(
                user_id=item.user_id,
                source=WithdrawalSource.MASS,
                provider=card.provider,
                card_id=card.id,
                card_mask=card.masked_pan,
                amount=item.amount,
                fee=Decimal(0),
                net_amount=item.amount,
                status=WithdrawalStatus.APPROVED,
                next_attempt_at=now,
                batch_id=batch.id,
                processed_by=actor.telegram_id,
                processed_at=now,
                is_test=provider.is_sandbox or s.payment_mode != "production",
            )
            self.session.add(withdrawal)
            await self.session.flush()
            self.session.add(
                WithdrawalStatusHistory(
                    withdrawal_id=withdrawal.id,
                    to_status=WithdrawalStatus.APPROVED.value,
                    actor_telegram_id=actor.telegram_id,
                    actor_role=actor.role,
                    comment=f"Ommaviy to‘lov #{batch.id}",
                )
            )
            item.withdrawal_id = withdrawal.id
            item.status = MassItemStatus.QUEUED
            queued += 1
        batch.status = MassBatchStatus.PROCESSING if queued else MassBatchStatus.COMPLETED
        batch.approved_by = actor.telegram_id
        batch.approved_at = now
        if not queued:
            batch.completed_at = now
        await self.audit.log(
            actor,
            "mass.approve",
            "mass_batch",
            batch.id,
            after={"queued": queued, "total": batch.total_amount},
        )
        await self.session.commit()
        return batch

    async def cancel(self, batch_id: int, actor: Actor) -> MassPayoutBatch:
        batch = await self.get(batch_id, for_update=True)
        if batch.status != MassBatchStatus.PREVIEW:
            raise DomainError("Faqat preview holatidagi partiyani bekor qilish mumkin.")
        batch.status = MassBatchStatus.CANCELLED
        await self.audit.log(actor, "mass.cancel", "mass_batch", batch.id)
        await self.session.commit()
        return batch

    async def report_csv(self, batch_id: int) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["line", "telegram_id", "amount", "provider", "status", "error", "withdrawal_id"]
        )
        for item in await self.items(batch_id):
            writer.writerow(
                [
                    item.line_no,
                    item.recipient_telegram_id or "",
                    item.amount or "",
                    item.provider or "",
                    item.status.value,
                    item.error or "",
                    item.withdrawal_id or "",
                ]
            )
        return buf.getvalue().encode("utf-8-sig")
