"""🤖 Avto to‘lov: o‘yin ID lari ro‘yxatiga kassadan ommaviy depozit.

Oqim (admin panel):
1. Kassa (kantora) tanlanadi.
2. ID lar yuboriladi — bitta yoki bir nechta xabar / .txt / .csv fayl (100, 300, 1000 ta).
   Qatorda summa ham bo‘lishi mumkin: ``123456789 - 15000``.
3. Summasiz ID lar uchun bot «har biriga qanchadan?» deb so‘raydi (bir marta).
4. Preview → tasdiq → **worker** har bir ID ga ketma-ket o‘tkazadi va progress xabarini
   jonli yangilaydi. Admin hech narsani qo‘lda bosib o‘tirmaydi.

Xavfsizlik (P2P depozit bilan bir xil qoidalar):
* har bir ID oldin ``payer_nickname`` bilan tekshiriladi (topilmasa — pul yuborilmaydi);
* ``deposit`` natijasi **noma’lum** (timeout/5xx) bo‘lsa avtomatik qayta yuborilmaydi →
  «🕵️ tekshiruv», admin kassa panelida tekshirib belgilaydi;
* ulanish xatolari (so‘rov yetib bormagan) — ``MAX_ATTEMPTS`` martagacha qayta urinish;
* jarayon to‘xtab qolib ``processing`` holatida qolgan ID — tekshiruvga (qayta yuborilmaydi);
* kassada mablag‘ yetmasa yoki ketma-ket xatolar ko‘paysa partiya avtomatik pauzaga o‘tadi;
* bitta partiyada bir ID ikki marta bo‘lmaydi (DB UNIQUE).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ACTIVE_AUTO_BATCH_STATUSES,
    AutoBatchStatus,
    AutoItemStatus,
)
from app.core.errors import DomainError, NotFoundError
from app.core.money import parse_amount
from app.core.utils import utcnow
from app.mobcash import MobCashError, MobCashErrorKind
from app.models import AutoDepositBatch, AutoDepositItem
from app.services.audit import Actor, AuditService, jsonable
from app.services.bookmakers import BookmakerService
from app.services.settings import SettingsService

log = logging.getLogger(__name__)

MAX_IDS = 1000
MIN_ID_LEN = 5
MAX_ID_LEN = 15
MAX_ATTEMPTS = 3  # faqat «so‘rov bajarilmagan» xatolar uchun
AUTO_PAUSE_ERRORS = 10  # ketma-ket shuncha xato — partiya pauzaga
RECENT_WINDOW = timedelta(hours=24)
STEP_DELAY_SECONDS = 0.3  # kassa API'ni bosib yubormaslik uchun
LOW_BALANCE_MARK = "💸 Kassa mablag‘i yetarli emas:"
MAX_FILE_BYTES = 256 * 1024

_NUMBERING = re.compile(r"^\s*(?:\d{1,4}\s*[.)]|[-•*№#]+)\s*")
_PAIR = re.compile(
    r"^\D{0,12}?(?P<id>\d{" + f"{MIN_ID_LEN},{MAX_ID_LEN}" + r"})\s*(?:=>|->|[|;:=\t]|[-–—]+)\s*"
    r"(?P<amount>[\d\s.,']+(?:\s*(?:so‘m|so'm|som|sum|uzs|k|ming))?)\s*$",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d+")
_LOW_BALANCE_HINTS = (
    "недостат",
    "insufficient",
    "not enough",
    "no money",
    "баланс",
    "balance",
    "balans",
    "yetarli emas",
    "лимит",
    "limit",
)

AUTO_HELP = (
    "📥 <b>ID larni yuboring</b> — har birini yangi qatorga yoki vergul/bo‘sh joy bilan:\n"
    "<code>123456789\n987654321\n555666777</code>\n\n"
    "💡 Har bir ID ga alohida summa kerak bo‘lsa:\n"
    "<code>123456789 - 15000\n987654321 - 25000</code>\n\n"
    "• Bir nechta xabar yoki <b>.txt / .csv</b> fayl yuborish mumkin (maks. "
    f"{MAX_IDS} ta ID).\n"
    "• Takroriy ID lar avtomatik olib tashlanadi.\n"
    "• Hammasi yuborilgach «➡️ Davom etish» ni bosing."
)


# =========================================================================== parser
@dataclass(slots=True)
class ParsedIds:
    """Admin yuborgan matndan ajratilgan ID lar (tartib saqlanadi)."""

    entries: dict[str, Decimal | None] = field(default_factory=dict)
    duplicates: int = 0
    invalid: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.entries)

    @property
    def with_amount(self) -> int:
        return sum(1 for a in self.entries.values() if a is not None)

    @property
    def without_amount(self) -> int:
        return self.count - self.with_amount

    def add(self, payer_id: str, amount: Decimal | None) -> None:
        if payer_id in self.entries:
            self.duplicates += 1
            return
        self.entries[payer_id] = amount

    def merge(self, other: ParsedIds) -> None:
        for payer_id, amount in other.entries.items():
            self.add(payer_id, amount)
        self.duplicates += other.duplicates
        self.invalid.extend(other.invalid)

    # FSM (Redis) da saqlash uchun
    def to_state(self) -> dict[str, Any]:
        return {
            "e": [[k, str(v) if v is not None else None] for k, v in self.entries.items()],
            "d": self.duplicates,
            "i": self.invalid[:50],
        }

    @classmethod
    def from_state(cls, data: dict[str, Any] | None) -> ParsedIds:
        parsed = cls()
        if not data:
            return parsed
        for payer_id, amount in data.get("e", []):
            parsed.entries[str(payer_id)] = Decimal(amount) if amount is not None else None
        parsed.duplicates = int(data.get("d", 0))
        parsed.invalid = list(data.get("i", []))
        return parsed


def _parse_line_amount(raw: str) -> Decimal | None:
    text = raw.strip().lower()
    multiplier = Decimal(1)
    for suffix in ("ming", "k"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            multiplier = Decimal(1000)
            break
    # «50.000» / «50,000» — minglik ajratgich sifatida
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", text):
        text = text.replace(".", "").replace(",", "")
    amount = parse_amount(text)
    return amount * multiplier if amount is not None else None


def parse_ids(text: str) -> ParsedIds:
    """Matndan o‘yin ID larini (va ixtiyoriy summani) ajratadi.

    * ``123456789`` — faqat ID (summa keyin so‘raladi);
    * ``123456789 - 15000`` / ``123456789: 15 000`` / ``123456789 | 15k`` — ID + summa;
    * bir qatorda bir nechta ID: ``111111111, 222222222 333333333``;
    * raqamlash (``1) …``, ``2. …``) va izohlar (``Ali 123456789``) e’tiborsiz qoldiriladi.
    """
    parsed = ParsedIds()
    for raw_line in text.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        body = _NUMBERING.sub("", line, count=1)
        pair = _PAIR.match(body)
        if pair:
            amount = _parse_line_amount(pair.group("amount"))
            if amount is None:
                parsed.invalid.append(line[:40])
                continue
            parsed.add(pair.group("id"), amount)
            continue
        tokens = _DIGITS.findall(body)
        found = False
        for token in tokens:
            if MIN_ID_LEN <= len(token) <= MAX_ID_LEN:
                parsed.add(token, None)
                found = True
            elif len(token) > MAX_ID_LEN:
                parsed.invalid.append(token[:40])
        if not found and not any(len(t) > MAX_ID_LEN for t in tokens):
            parsed.invalid.append(line[:40])
    return parsed


_AMOUNT_HEADERS = ("amount", "summa", "sum", "сумма", "miqdor")


def parse_file(content: bytes) -> ParsedIds:
    """.txt yoki .csv fayl. CSV da 2-ustun summa deb olinadi, agar sarlavhada
    ``amount``/``summa`` bo‘lsa yoki barcha qatorlarda 1-ustun uzun ID (8+ xona), 2-ustun esa
    qisqa son (≤ 7 xona) bo‘lsa. Aks holda har ikki ustun ham ID hisoblanadi."""
    if len(content) > MAX_FILE_BYTES:
        raise DomainError("Fayl juda katta (maks. 256 KB).")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1251", errors="replace")
    rows = [
        cells
        for line in text.splitlines()
        if (cells := [c.strip() for c in re.split(r"[;,\t]", line) if c.strip()])
    ]
    if not rows:
        return ParsedIds()
    header = [c.lower() for c in rows[0]]
    has_header = not any(c.replace(" ", "").isdigit() for c in header)
    data = rows[1:] if has_header else rows
    amount_column = has_header and len(header) >= 2 and header[1] in _AMOUNT_HEADERS
    if not has_header and data and all(len(r) == 2 for r in data):
        amount_column = all(
            r[0].isdigit()
            and len(r[0]) >= 8
            and r[1].replace(" ", "").isdigit()
            and len(r[1].replace(" ", "")) <= 7
            for r in data
        )
    if amount_column:
        lines = [f"{r[0]} | {r[1]}" if len(r) >= 2 else r[0] for r in data]
    else:
        lines = [" ".join(r) for r in data]
    return parse_ids("\n".join(lines))


def looks_like_low_balance(message: str) -> bool:
    low = message.lower()
    return any(hint in low for hint in _LOW_BALANCE_HINTS)


# =========================================================================== natijalar
@dataclass(slots=True)
class BatchStats:
    total: int = 0
    pending: int = 0
    processing: int = 0
    success: int = 0
    failed: int = 0
    review: int = 0
    skipped: int = 0
    success_amount: Decimal = Decimal(0)
    planned_amount: Decimal = Decimal(0)

    @property
    def done(self) -> int:
        return self.success + self.failed + self.review + self.skipped

    @property
    def percent(self) -> int:
        return int(self.done * 100 / self.total) if self.total else 0


@dataclass(slots=True)
class StepEvent:
    """Worker qadami natijasi — progress xabarini yangilash va yakuniy hisobot uchun."""

    batch: AutoDepositBatch
    kind: str  # "progress" | "finished" | "paused"
    last_item: AutoDepositItem | None = None


@dataclass(slots=True)
class Preview:
    batch: AutoDepositBatch
    recent_ids: int  # so‘nggi 24 soatda shu kassadan to‘lov olgan ID lar
    balance: Decimal | None
    balance_error: str | None = None


ProgressCallback = Callable[[StepEvent], Awaitable[None]]


class AutoDepositService:
    def __init__(
        self,
        session: AsyncSession,
        settings: SettingsService,
        bookmakers: BookmakerService,
    ) -> None:
        self.session = session
        self.settings = settings
        self.bookmakers = bookmakers
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ kassalar
    async def kassa_choices(self) -> list[tuple[int | None, str]]:
        """Avto to‘lov uchun tanlanadigan kassalar: faol kantoralar yoki eski yagona kassa."""
        choices: list[tuple[int | None, str]] = [
            (bm.id, bm.name) for bm in await self.bookmakers.list_active()
        ]
        if not choices and await self.bookmakers.legacy_available():
            choices.append((None, "Mob-Cash kassa"))
        return choices

    async def kassa_balance(self, bookmaker_id: int | None) -> Decimal | None:
        """Kassa balansi (gateway qo‘llasa). Mob-Cash v2 balans bermaydi — None."""
        client = await self.bookmakers.client(bookmaker_id)
        balance_fn = getattr(client, "balance", None)
        if balance_fn is None:
            return None
        balance, _ = await balance_fn()
        return Decimal(balance)

    # ------------------------------------------------------------------ yaratish
    async def create_draft(
        self,
        *,
        bookmaker_id: int | None,
        parsed: ParsedIds,
        default_amount: Decimal | None,
        actor: Actor,
    ) -> AutoDepositBatch:
        if parsed.count == 0:
            raise DomainError("Birorta ham to‘g‘ri ID topilmadi.")
        if parsed.count > MAX_IDS:
            raise DomainError(f"Bir partiyada {MAX_IDS} tadan ko‘p ID bo‘lmasin.")
        if parsed.without_amount and default_amount is None:
            raise DomainError("Har bir ID uchun summa kiritilmagan.")
        rt = await self.settings.snapshot()
        if bookmaker_id is not None:
            kassa_name = (await self.bookmakers.get_active(bookmaker_id)).name
        elif await self.bookmakers.legacy_available():
            kassa_name = "Mob-Cash kassa"
        else:
            raise DomainError("Kassa tanlanmagan yoki o‘chirilgan.")

        items: list[tuple[str, Decimal]] = []
        for payer_id, amount in parsed.entries.items():
            value = amount if amount is not None else default_amount
            assert value is not None  # noqa: S101 — yuqorida tekshirilgan
            if value <= 0:
                raise DomainError(f"ID {payer_id}: summa musbat bo‘lishi kerak.")
            if value > rt.deposit_max:
                raise DomainError(
                    f"ID {payer_id}: summa {value} limitdan katta (maks. {rt.deposit_max}). "
                    "Xato yozilmaganini tekshiring yoki «⚙️ Tizim Sozlamalari»da "
                    "depozit limitini oshiring."
                )
            items.append((payer_id, value))

        batch = AutoDepositBatch(
            bookmaker_id=bookmaker_id,
            kassa_name=kassa_name[:64],
            status=AutoBatchStatus.DRAFT,
            default_amount=default_amount,
            total_count=len(items),
            total_amount=sum((a for _, a in items), Decimal(0)),
            created_by=actor.telegram_id or 0,
        )
        self.session.add(batch)
        await self.session.flush()
        self.session.add_all(
            AutoDepositItem(
                batch_id=batch.id,
                position=pos,
                payer_id=payer_id,
                amount=amount,
                status=AutoItemStatus.PENDING,
            )
            for pos, (payer_id, amount) in enumerate(items, 1)
        )
        await self.audit.log(
            actor,
            "auto.draft",
            "auto_batch",
            batch.id,
            after={
                "kassa": kassa_name,
                "count": batch.total_count,
                "total": batch.total_amount,
                "default_amount": default_amount,
            },
        )
        await self.session.commit()
        return batch

    async def preview(self, batch: AutoDepositBatch) -> Preview:
        balance: Decimal | None = None
        balance_error: str | None = None
        try:
            balance = await self.kassa_balance(batch.bookmaker_id)
        except (DomainError, MobCashError) as exc:
            balance_error = exc.message
        return Preview(batch, await self.recent_count(batch), balance, balance_error)

    async def recent_count(self, batch: AutoDepositBatch) -> int:
        """Shu partiyadagi ID lardan qanchasi so‘nggi 24 soatda shu kassadan pul olgan."""
        other = AutoDepositItem.__table__.alias("other")
        other_batch = AutoDepositBatch.__table__.alias("other_batch")
        stmt = (
            select(func.count(func.distinct(AutoDepositItem.payer_id)))
            .select_from(AutoDepositItem)
            .join(other, other.c.payer_id == AutoDepositItem.payer_id)
            .join(other_batch, other_batch.c.id == other.c.batch_id)
            .where(
                AutoDepositItem.batch_id == batch.id,
                other.c.batch_id != batch.id,
                other.c.status == AutoItemStatus.SUCCESS.value,
                other.c.processed_at >= utcnow() - RECENT_WINDOW,
                (
                    other_batch.c.bookmaker_id.is_(None)
                    if batch.bookmaker_id is None
                    else other_batch.c.bookmaker_id == batch.bookmaker_id
                ),
            )
        )
        return int(await self.session.scalar(stmt) or 0)

    # ------------------------------------------------------------------ boshqaruv
    async def get(self, batch_id: int, *, for_update: bool = False) -> AutoDepositBatch:
        batch = await self.session.get(
            AutoDepositBatch, batch_id, with_for_update=for_update, populate_existing=True
        )
        if batch is None:
            raise NotFoundError("Avto to‘lov partiyasi topilmadi.")
        return batch

    async def start(
        self, batch_id: int, actor: Actor, chat_id: int | None, message_id: int | None
    ) -> AutoDepositBatch:
        batch = await self.get(batch_id, for_update=True)
        if batch.status != AutoBatchStatus.DRAFT:
            raise DomainError("Bu partiya allaqachon boshlangan yoki bekor qilingan.")
        if batch.bookmaker_id is not None:
            await self.bookmakers.get_active(batch.bookmaker_id)
        batch.status = AutoBatchStatus.RUNNING
        batch.started_by = actor.telegram_id
        batch.started_at = utcnow()
        batch.chat_id, batch.message_id = chat_id, message_id
        batch.pause_reason = None
        await self.audit.log(
            actor,
            "auto.start",
            "auto_batch",
            batch.id,
            after={"count": batch.total_count, "total": batch.total_amount},
        )
        await self.session.commit()
        return batch

    async def set_progress_message(self, batch_id: int, chat_id: int, message_id: int) -> None:
        await self.session.execute(
            update(AutoDepositBatch)
            .where(AutoDepositBatch.id == batch_id)
            .values(chat_id=chat_id, message_id=message_id)
        )
        await self.session.commit()

    async def pause(self, batch_id: int, actor: Actor) -> AutoDepositBatch:
        batch = await self.get(batch_id, for_update=True)
        if batch.status != AutoBatchStatus.RUNNING:
            raise DomainError("Partiya hozir ishlamayapti.")
        batch.status = AutoBatchStatus.PAUSED
        batch.pause_reason = "Admin pauzaga qo‘ydi"
        await self.audit.log(actor, "auto.pause", "auto_batch", batch.id)
        await self.session.commit()
        return batch

    async def resume(self, batch_id: int, actor: Actor) -> AutoDepositBatch:
        batch = await self.get(batch_id, for_update=True)
        if batch.status != AutoBatchStatus.PAUSED:
            raise DomainError("Faqat pauzadagi partiyani davom ettirish mumkin.")
        if batch.bookmaker_id is not None:
            await self.bookmakers.get_active(batch.bookmaker_id)
        batch.status = AutoBatchStatus.RUNNING
        batch.pause_reason = None
        batch.consecutive_errors = 0
        await self.audit.log(actor, "auto.resume", "auto_batch", batch.id)
        await self.session.commit()
        return batch

    async def cancel(self, batch_id: int, actor: Actor) -> AutoDepositBatch:
        """Navbatdagi ID lar o‘tkazib yuboriladi; allaqachon o‘tkazilganlar o‘zgarmaydi."""
        batch = await self.get(batch_id, for_update=True)
        if batch.status in (AutoBatchStatus.COMPLETED, AutoBatchStatus.CANCELLED):
            raise DomainError("Partiya allaqachon yakunlangan.")
        result = await self.session.execute(
            update(AutoDepositItem)
            .where(
                AutoDepositItem.batch_id == batch.id,
                AutoDepositItem.status == AutoItemStatus.PENDING,
            )
            .values(status=AutoItemStatus.SKIPPED, error="Partiya to‘xtatildi")
        )
        batch.status = AutoBatchStatus.CANCELLED
        batch.finished_at = utcnow()
        await self.audit.log(
            actor,
            "auto.cancel",
            "auto_batch",
            batch.id,
            after={"skipped": getattr(result, "rowcount", None)},
        )
        await self.session.commit()
        return batch

    async def retry_failed(self, batch_id: int, actor: Actor) -> int:
        """Bajarilmagan (pul yechilmagani aniq) ID larni qayta navbatga qo‘yadi."""
        batch = await self.get(batch_id, for_update=True)
        if batch.status in (AutoBatchStatus.DRAFT, AutoBatchStatus.CANCELLED):
            raise DomainError("Bu partiyani qayta ishga tushirib bo‘lmaydi.")
        if batch.bookmaker_id is not None:
            await self.bookmakers.get_active(batch.bookmaker_id)
        result = await self.session.execute(
            update(AutoDepositItem)
            .where(
                AutoDepositItem.batch_id == batch.id,
                AutoDepositItem.status == AutoItemStatus.FAILED,
            )
            .values(status=AutoItemStatus.PENDING, attempts=0, error=None)
        )
        count = int(getattr(result, "rowcount", 0) or 0)
        if not count:
            await self.session.rollback()
            raise DomainError("Qayta yuboriladigan xato ID yo‘q.")
        batch.status = AutoBatchStatus.RUNNING
        batch.finished_at = None
        batch.pause_reason = None
        batch.consecutive_errors = 0
        await self.audit.log(actor, "auto.retry", "auto_batch", batch.id, after={"count": count})
        await self.session.commit()
        return count

    async def resolve_review(self, item_id: int, credited: bool, actor: Actor) -> AutoDepositItem:
        """Admin kassa panelida tekshirgach: pul tushgan (✅) yoki tushmagan (❌)."""
        item = await self.session.get(
            AutoDepositItem, item_id, with_for_update=True, populate_existing=True
        )
        if item is None:
            raise NotFoundError("ID topilmadi.")
        if item.status != AutoItemStatus.REVIEW:
            raise DomainError("Bu ID tekshiruvda emas.")
        item.status = AutoItemStatus.SUCCESS if credited else AutoItemStatus.FAILED
        item.error = None if credited else "Admin: kassa panelida tushmagan"
        item.processed_at = utcnow()
        await self.audit.log(
            actor,
            "auto.review",
            "auto_item",
            item.id,
            after={"credited": credited, "payer_id": item.payer_id, "amount": item.amount},
        )
        await self.session.commit()
        return item

    # ------------------------------------------------------------------ ko‘rish
    async def stats(self, batch_id: int) -> BatchStats:
        stmt = (
            select(
                AutoDepositItem.status,
                func.count(AutoDepositItem.id),
                func.coalesce(func.sum(AutoDepositItem.amount), 0),
            )
            .where(AutoDepositItem.batch_id == batch_id)
            .group_by(AutoDepositItem.status)
        )
        st = BatchStats()
        for status, count, amount in (await self.session.execute(stmt)).all():
            n = int(count)
            st.total += n
            st.planned_amount += Decimal(amount)
            setattr(st, AutoItemStatus(status).value, n)
            if status == AutoItemStatus.SUCCESS:
                st.success_amount = Decimal(amount)
        return st

    async def list_page(self, page: int, per_page: int = 8) -> list[AutoDepositBatch]:
        stmt = (
            select(AutoDepositBatch)
            .where(AutoDepositBatch.started_at.is_not(None))  # boshlanmagan qoralamalar emas
            .order_by(AutoDepositBatch.id.desc())
            .limit(per_page)
            .offset(page * per_page)
        )
        return list(await self.session.scalars(stmt))

    async def active_batches(self) -> list[AutoDepositBatch]:
        stmt = (
            select(AutoDepositBatch)
            .where(AutoDepositBatch.status.in_(ACTIVE_AUTO_BATCH_STATUSES))
            .order_by(AutoDepositBatch.id)
        )
        return list(await self.session.scalars(stmt))

    async def items(
        self,
        batch_id: int,
        statuses: tuple[AutoItemStatus, ...] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[AutoDepositItem]:
        stmt = select(AutoDepositItem).where(AutoDepositItem.batch_id == batch_id)
        if statuses:
            stmt = stmt.where(AutoDepositItem.status.in_(statuses))
        stmt = stmt.order_by(AutoDepositItem.position).offset(offset)
        if limit:
            stmt = stmt.limit(limit)
        return list(await self.session.scalars(stmt))

    async def last_processed(self, batch_id: int) -> AutoDepositItem | None:
        stmt = (
            select(AutoDepositItem)
            .where(
                AutoDepositItem.batch_id == batch_id,
                AutoDepositItem.processed_at.is_not(None),
            )
            .order_by(AutoDepositItem.processed_at.desc(), AutoDepositItem.id.desc())
            .limit(1)
        )
        return await self.session.scalar(stmt)

    async def today_summary(self) -> tuple[int, int, Decimal]:
        """Bugungi (24 soat) avto to‘lovlar: partiyalar, muvaffaqiyatli ID lar, summa."""
        since = utcnow() - timedelta(hours=24)
        batches = await self.session.scalar(
            select(func.count(AutoDepositBatch.id)).where(AutoDepositBatch.started_at >= since)
        )
        count, amount = (
            await self.session.execute(
                select(
                    func.count(AutoDepositItem.id),
                    func.coalesce(func.sum(AutoDepositItem.amount), 0),
                ).where(
                    AutoDepositItem.status == AutoItemStatus.SUCCESS,
                    AutoDepositItem.processed_at >= since,
                )
            )
        ).one()
        return int(batches or 0), int(count), Decimal(amount)

    async def report_csv(self, batch_id: int) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["#", "payer_id", "amount", "status", "nickname", "error", "processed_at"])
        for item in await self.items(batch_id):
            writer.writerow(
                [
                    item.position,
                    item.payer_id,
                    item.amount,
                    item.status.value,
                    item.nickname or "",
                    item.error or "",
                    item.processed_at.isoformat() if item.processed_at else "",
                ]
            )
        return buf.getvalue().encode("utf-8-sig")

    # ------------------------------------------------------------------ worker
    async def _batch_status(self, batch_id: int) -> AutoBatchStatus | None:
        status = await self.session.scalar(
            select(AutoDepositBatch.status).where(AutoDepositBatch.id == batch_id)
        )
        return AutoBatchStatus(status) if status is not None else None

    async def _recover_stale(self, batch: AutoDepositBatch) -> None:
        """Worker job lock ostida chaqiriladi: «processing» qolgan ID — oldingi jarayon
        so‘rov o‘rtasida to‘xtagan. Natija noma’lum — qayta yubormaymiz, tekshiruvga."""
        await self.session.execute(
            update(AutoDepositItem)
            .where(
                AutoDepositItem.batch_id == batch.id,
                AutoDepositItem.status == AutoItemStatus.PROCESSING,
            )
            .values(
                status=AutoItemStatus.REVIEW,
                error="Jarayon to‘xtab qolgan — natija noma’lum, kassa panelida tekshiring",
                processed_at=utcnow(),
            )
        )
        await self.session.commit()

    async def _pause(self, batch_id: int, reason: str) -> AutoDepositBatch:
        batch = await self.get(batch_id, for_update=True)
        if batch.status == AutoBatchStatus.RUNNING:
            batch.status = AutoBatchStatus.PAUSED
            batch.pause_reason = reason[:255]
            await self.audit.log(
                Actor.system("auto"),
                "auto.autopause",
                "auto_batch",
                batch.id,
                after={"reason": reason[:255]},
            )
        await self.session.commit()
        return batch

    async def _finish_if_done(self, batch_id: int) -> AutoDepositBatch | None:
        left = await self.session.scalar(
            select(func.count(AutoDepositItem.id)).where(
                AutoDepositItem.batch_id == batch_id,
                AutoDepositItem.status.in_((AutoItemStatus.PENDING, AutoItemStatus.PROCESSING)),
            )
        )
        if left:
            return None
        batch = await self.get(batch_id, for_update=True)
        if batch.status != AutoBatchStatus.RUNNING:
            await self.session.commit()
            return None
        batch.status = AutoBatchStatus.COMPLETED
        batch.finished_at = utcnow()
        st = await self.stats(batch_id)
        await self.audit.log(
            Actor.system("auto"),
            "auto.completed",
            "auto_batch",
            batch.id,
            after={
                "success": st.success,
                "failed": st.failed,
                "review": st.review,
                "amount": st.success_amount,
            },
        )
        await self.session.commit()
        return batch

    async def _next_item(self, batch_id: int) -> AutoDepositItem | None:
        stmt = (
            select(AutoDepositItem)
            .where(
                AutoDepositItem.batch_id == batch_id,
                AutoDepositItem.status == AutoItemStatus.PENDING,
            )
            .order_by(AutoDepositItem.attempts, AutoDepositItem.position)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return await self.session.scalar(stmt)

    async def _save(
        self,
        item_id: int,
        batch_id: int,
        *,
        status: AutoItemStatus,
        error: str | None = None,
        nickname: str | None = None,
        result: Any = None,
        count_error: bool = False,
        undo_attempt: bool = False,
    ) -> AutoDepositItem:
        item = await self.session.get(
            AutoDepositItem, item_id, with_for_update=True, populate_existing=True
        )
        assert item is not None  # noqa: S101
        item.status = status
        if undo_attempt:
            item.attempts = max(0, item.attempts - 1)
        item.error = error[:500] if error else None
        if nickname is not None:
            item.nickname = nickname[:128]
        if result is not None:
            item.result = jsonable(result) if isinstance(result, dict) else {"raw": str(result)}
        if status != AutoItemStatus.PENDING:
            item.processed_at = utcnow()
        batch = await self.get(batch_id, for_update=True)
        if status == AutoItemStatus.SUCCESS:
            batch.consecutive_errors = 0
        elif count_error:
            batch.consecutive_errors += 1
        await self.session.commit()
        return item

    async def _process_item(self, batch: AutoDepositBatch, item: AutoDepositItem) -> str | None:
        """Bitta ID ga o‘tkazma. Qaytaradi: partiyani pauzaga qo‘yish sababi (yoki None)."""
        item_id, batch_id = item.id, batch.id
        payer_id, amount, prev_error = item.payer_id, item.amount, item.error
        item.status = AutoItemStatus.PROCESSING
        item.attempts += 1
        attempts = item.attempts
        await self.session.commit()

        try:
            client = await self.bookmakers.client(batch.bookmaker_id)
        except DomainError as exc:
            await self._save(
                item_id,
                batch_id,
                status=AutoItemStatus.PENDING,
                error=exc.message,
                undo_attempt=True,
            )
            return f"Kassa ishlamayapti: {exc.message}"

        # 1) Akkauntni tekshirish (faqat o‘qish — qayta urinish xavfsiz).
        try:
            nickname = await client.payer_nickname(payer_id)
        except MobCashError as exc:
            if exc.kind == MobCashErrorKind.REJECTED:
                await self._save(
                    item_id,
                    batch_id,
                    status=AutoItemStatus.FAILED,
                    error=f"Akkaunt topilmadi: {exc.message}",
                )
                return None
            return await self._retry_or_fail(item_id, batch_id, attempts, exc)

        # 2) Depozit — pul harakatlanadi.
        try:
            result = await client.deposit(payer_id, amount)
        except MobCashError as exc:
            log.warning(
                "Avto to‘lov deposit xato batch=%s payer=%s kind=%s: %s",
                batch_id,
                payer_id,
                exc.kind,
                exc.message,
            )
            if exc.kind == MobCashErrorKind.UNKNOWN:
                await self._save(
                    item_id,
                    batch_id,
                    status=AutoItemStatus.REVIEW,
                    nickname=nickname,
                    error=f"Natija noma’lum: {exc.message}",
                    count_error=True,
                )
                return None
            if exc.kind == MobCashErrorKind.REJECTED:
                if looks_like_low_balance(exc.message) and not (prev_error or "").startswith(
                    LOW_BALANCE_MARK
                ):
                    # Pul yechilmagan — ID navbatga qaytadi, partiya pauzaga. Shu ID da ikkinchi
                    # marta takrorlansa — bu kassa emas, o‘yinchining o‘z limiti: xato deb olamiz.
                    await self._save(
                        item_id,
                        batch_id,
                        status=AutoItemStatus.PENDING,
                        nickname=nickname,
                        error=f"{LOW_BALANCE_MARK} {exc.message}",
                        undo_attempt=True,
                    )
                    return f"Kassada mablag‘ yoki limit yetarli emas: {exc.message}"
                await self._save(
                    item_id,
                    batch_id,
                    status=AutoItemStatus.FAILED,
                    nickname=nickname,
                    error=exc.message,
                    count_error=True,
                )
                return None
            return await self._retry_or_fail(item_id, batch_id, attempts, exc, nickname)

        await self._save(
            item_id, batch_id, status=AutoItemStatus.SUCCESS, nickname=nickname, result=result
        )
        return None

    async def _retry_or_fail(
        self,
        item_id: int,
        batch_id: int,
        attempts: int,
        exc: MobCashError,
        nickname: str | None = None,
    ) -> str | None:
        if attempts < MAX_ATTEMPTS:
            await self._save(
                item_id,
                batch_id,
                status=AutoItemStatus.PENDING,
                nickname=nickname,
                error=f"Qayta urinish ({attempts}/{MAX_ATTEMPTS}): {exc.message}",
                count_error=True,
            )
        else:
            await self._save(
                item_id,
                batch_id,
                status=AutoItemStatus.FAILED,
                nickname=nickname,
                error=exc.message,
                count_error=True,
            )
        return None

    async def run_step(
        self,
        *,
        time_budget: float = 25.0,
        delay: float = STEP_DELAY_SECONDS,
        on_progress: ProgressCallback | None = None,
        progress_every: float = 3.0,
    ) -> list[StepEvent]:
        """Worker: faol partiyalarni navbat bilan qayta ishlaydi (vaqt chegarasi ichida).

        Worker job lock ostida chaqirilishi shart — bir vaqtda faqat bitta jarayon.
        """
        events: list[StepEvent] = []
        deadline = time.monotonic() + time_budget
        stmt = (
            select(AutoDepositBatch.id)
            .where(AutoDepositBatch.status == AutoBatchStatus.RUNNING)
            .order_by(AutoDepositBatch.id)
        )
        for batch_id in list(await self.session.scalars(stmt)):
            if time.monotonic() >= deadline:
                break
            batch = await self.get(batch_id)
            await self._recover_stale(batch)
            last_item: AutoDepositItem | None = None
            last_report = time.monotonic()
            paused_reason: str | None = None
            while time.monotonic() < deadline:
                if await self._batch_status(batch_id) != AutoBatchStatus.RUNNING:
                    break
                item = await self._next_item(batch_id)
                if item is None:
                    await self.session.commit()
                    break
                paused_reason = await self._process_item(batch, item)
                last_item = await self.session.get(AutoDepositItem, item.id, populate_existing=True)
                if paused_reason is None:
                    batch = await self.get(batch_id)
                    if batch.consecutive_errors >= AUTO_PAUSE_ERRORS:
                        paused_reason = (
                            f"Ketma-ket {batch.consecutive_errors} ta xato — kassa holatini "
                            "tekshiring"
                        )
                if paused_reason:
                    break
                if on_progress is not None and time.monotonic() - last_report >= progress_every:
                    last_report = time.monotonic()
                    await on_progress(StepEvent(await self.get(batch_id), "progress", last_item))
                if delay:
                    await asyncio.sleep(delay)

            if paused_reason:
                batch = await self._pause(batch_id, paused_reason)
                events.append(StepEvent(batch, "paused", last_item))
                continue
            finished = await self._finish_if_done(batch_id)
            if finished is not None:
                events.append(StepEvent(finished, "finished", last_item))
            elif last_item is not None:
                events.append(StepEvent(await self.get(batch_id), "progress", last_item))
        return events
