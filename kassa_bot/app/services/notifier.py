"""Foydalanuvchi va adminlarga xabar yuborish (handlerlardan tashqarida ham ishlaydi)."""

from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from app import texts
from app.bot.keyboards.admin_mobcash import bank_tx_kb, mcwd_kb, p2p_kb
from app.core.enums import MobcashWithdrawalStatus, P2PDepositTarget
from app.core.money import fmt_money
from app.models import BankTransaction, MobcashWithdrawal, P2PDeposit, Withdrawal
from app.services.deposits import DepositOutcome
from app.services.mobcash_withdrawals import WithdrawEvent, mask_card, pretty_card
from app.services.p2p import P2POutcome
from app.services.withdrawals import WithdrawalEvent

log = logging.getLogger(__name__)


def _bm(bookmaker: str | None) -> str:
    return f"🏢 Kantora: <b>{html.escape(bookmaker)}</b>\n" if bookmaker else ""


def p2p_admin_text(d: P2PDeposit, title: str, bookmaker: str | None = None) -> str:
    if d.target == P2PDepositTarget.WALLET:
        who = "🏠 Maqsad: <b>Hamyonni to‘ldirish</b>"
    else:
        nick = html.escape(d.payer_nickname or "—")
        who = f"🆔 ID: <code>{html.escape(d.payer_id)}</code> ({nick})"
        if d.card_id is None:
            who += "\n🏠 Manba: <b>Hamyondan</b> (karta kutilmaydi)"
    return (
        f"{title}\n\n"
        f"🧾 Depozit <b>#{d.id}</b> — {texts.mc_status(d.target, d.status)}\n"
        f"{_bm(bookmaker)}"
        f"{who}\n"
        f"💰 Kutilgan: {fmt_money(d.unique_amount)}"
        + (f" • Tushiriladi: {fmt_money(d.credit_amount)}" if d.credit_amount else "")
        + (f"\n⚠️ {html.escape(d.last_error)}" if d.last_error else "")
    )


def mcwd_admin_text(w: MobcashWithdrawal, title: str, bookmaker: str | None = None) -> str:
    if w.card_number:
        payout = (
            f"💸 Kartaga: <b>{fmt_money(w.payout_amount)}</b>\n"
            f"💳 <code>{pretty_card(w.card_number)}</code>"
        )
    else:
        payout = f"💎 Hamyonga: <b>{fmt_money(w.payout_amount)}</b> (avtomatik)"
    return (
        f"{title}\n\n"
        f"{_bm(bookmaker)}"
        f"🆔 ID: <code>{html.escape(w.payer_id)}</code>\n"
        f"💵 Yechildi: {fmt_money(w.amount)} • Komissiya: {fmt_money(w.fee)}\n"
        f"{payout}"
        + (f"\n⚠️ {html.escape(w.last_error)}" if w.last_error else "")
    )


class Notifier:
    def __init__(self, bot: Bot | None) -> None:
        self.bot = bot

    async def send(
        self, chat_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> bool:
        if self.bot is None or not chat_id:
            return False
        for _ in range(2):
            try:
                await self.bot.send_message(chat_id, text, reply_markup=reply_markup)
                return True
            except TelegramRetryAfter as exc:
                await asyncio.sleep(min(exc.retry_after, 10))
            except TelegramForbiddenError:
                return False  # foydalanuvchi botni bloklagan
            except TelegramAPIError as exc:
                log.warning("Xabar yuborilmadi chat=%s: %s", chat_id, exc)
                return False
        return False

    async def send_many(
        self, chat_ids: list[int], text: str, reply_markup: InlineKeyboardMarkup | None = None
    ) -> int:
        sent = 0
        for chat_id in chat_ids:
            if await self.send(chat_id, text, reply_markup):
                sent += 1
            await asyncio.sleep(0.05)  # Telegram flood limitlari
        return sent

    # ------------------------------------------------------------------ Mob-Cash: depozit
    async def p2p_deposit(
        self,
        outcome: P2POutcome,
        admin_ids: list[int] | None = None,
        bookmaker: str | None = None,
    ) -> None:
        d = outcome.deposit
        if outcome.event == "credited":
            amount = fmt_money(d.credit_amount or d.unique_amount)
            if d.target == P2PDepositTarget.WALLET:
                text = texts.MC_TOPUP_CREDITED.format(id=d.id, amount=amount)
            else:
                text = texts.MC_DEP_CREDITED.format(
                    id=d.id, amount=amount, payer_id=html.escape(d.payer_id)
                )
            await self.send(
                outcome.user_telegram_id, text + (texts.MC_DEP_LATE_NOTE if outcome.late else "")
            )
        elif outcome.event == "review":
            await self.send(outcome.user_telegram_id, texts.MC_DEP_REVIEW.format(id=d.id))
            if admin_ids:
                await self.p2p_admin_review(d, admin_ids, bookmaker)
        elif outcome.event == "expired":
            await self.send(
                outcome.user_telegram_id,
                texts.MC_DEP_EXPIRED.format(id=d.id, hours=outcome.late_grace_hours),
            )

    async def p2p_admin_review(
        self, deposit: P2PDeposit, admin_ids: list[int], bookmaker: str | None = None
    ) -> None:
        """Tekshiruv kerak bo‘lgan depozitni faqat adminlarga yuboradi (foydalanuvchiga emas)."""
        await self.send_many(
            admin_ids,
            p2p_admin_text(deposit, "🕵️ Tekshiruv kerak", bookmaker),
            p2p_kb(deposit),
        )

    async def p2p_rejected(self, deposit: P2PDeposit, user_tg: int, comment: str) -> None:
        note = f"\n💬 {html.escape(comment)}" if comment else ""
        refund = (
            "\n💰 Summa hamyoningizga qaytarildi."
            if deposit.target == P2PDepositTarget.GAME and deposit.card_id is None
            else ""
        )
        await self.send(
            user_tg, texts.MC_DEP_REJECTED.format(id=deposit.id, comment=note) + refund
        )

    async def bank_unmatched(self, tx: BankTransaction, admin_ids: list[int]) -> None:
        text = (
            f"❓ <b>Mos kelmagan kirim #{tx.id}</b>\n\n"
            f"💰 {fmt_money(tx.amount)}\n"
            f"📨 @{html.escape(tx.source_name)} • 💳 *{tx.card_last4 or '????'}\n\n"
            "Bu summa bilan kutilayotgan to‘lov yo‘q. Foydalanuvchi noto‘g‘ri summa "
            "o‘tkazgan bo‘lsa — depozitga qo‘lda bog‘lang."
        )
        await self.send_many(admin_ids, text, bank_tx_kb(tx))

    # ------------------------------------------------------------------ Mob-Cash: yechish
    async def mcwd_new(
        self, wd: MobcashWithdrawal, admin_ids: list[int], bookmaker: str | None = None
    ) -> None:
        title = (
            "📤 <b>Yangi yechish #{id}</b> — kartaga o‘tkazing"
            if wd.status == MobcashWithdrawalStatus.AWAITING_PAYOUT
            else "🕵️ <b>Yechish #{id}</b> — Mob-Cash javobi noaniq, panelda tekshiring"
        )
        await self.send_many(
            admin_ids, mcwd_admin_text(wd, title.format(id=wd.id), bookmaker), mcwd_kb(wd)
        )

    async def mcwd_status(self, event: WithdrawEvent, comment: str = "") -> None:
        w = event.withdrawal
        note = f"\n💬 {html.escape(comment)}" if comment else ""
        if w.status == MobcashWithdrawalStatus.PAID:
            if w.card_number:
                text = texts.MC_WD_PAID.format(
                    id=w.id, payout=fmt_money(w.payout_amount), card=mask_card(w.card_number)
                )
            else:
                text = texts.MC_WD_WALLET_DONE.format(
                    id=w.id, payout=fmt_money(w.payout_amount)
                )
        elif w.status == MobcashWithdrawalStatus.AWAITING_PAYOUT:
            text = texts.MC_WD_CREATED.format(
                id=w.id, payout=fmt_money(w.payout_amount), card=mask_card(w.card_number)
            )
        elif w.status == MobcashWithdrawalStatus.REFUNDED:
            text = texts.MC_WD_REFUNDED.format(id=w.id, amount=fmt_money(w.amount), comment=note)
        elif w.status == MobcashWithdrawalStatus.FAILED:
            text = texts.MC_WD_FAILED_USER.format(id=w.id, comment=note)
        else:
            return
        await self.send(event.user_telegram_id, text)

    async def deposit(self, outcome: DepositOutcome) -> None:
        p = outcome.payment
        if outcome.status.value == "paid":
            bonus = "".join(
                texts.DEPOSIT_BONUS_LINE.format(amount=fmt_money(b.amount), kind=b.label)
                for b in outcome.bonuses
            )
            await self.send(
                outcome.user_telegram_id,
                texts.DEPOSIT_PAID.format(id=p.id, net=fmt_money(outcome.net), bonus=bonus),
            )
            if outcome.referrer_telegram_id and outcome.referral_amount > 0:
                await self.send(
                    outcome.referrer_telegram_id,
                    texts.REFERRAL_REWARD.format(amount=fmt_money(outcome.referral_amount)),
                )
        elif outcome.status.value == "expired":
            await self.send(outcome.user_telegram_id, texts.DEPOSIT_EXPIRED.format(id=p.id))
        elif outcome.status.value == "failed":
            await self.send(outcome.user_telegram_id, texts.DEPOSIT_FAILED.format(id=p.id))

    async def withdrawal(self, event: WithdrawalEvent, admin_ids: list[int] | None = None) -> None:
        w = event.withdrawal
        if event.to_manual:
            if admin_ids:
                await self.send_many(
                    admin_ids,
                    f"⚠️ Ariza #{w.id} ({fmt_money(w.amount)}) manual navbatga o‘tdi.\n"
                    f"Sabab: {html.escape(w.last_error or '—')}",
                )
            return
        comment = (
            f"\n💬 {html.escape(w.reason)}" if w.reason and w.status.value == "rejected" else ""
        )
        await self.send(
            event.user_telegram_id,
            texts.WITHDRAW_STATUS_CHANGED.format(
                id=w.id,
                status=texts.WITHDRAW_STATUS[w.status],
                amount=fmt_money(w.net_amount),
                comment=comment,
            ),
        )

    async def wallet_withdrawal_new(
        self, w: Withdrawal, user_tg: int, card_pan: str, admin_ids: list[int]
    ) -> None:
        """Qo‘lda o‘tkazish arizasi — adminlarga to‘liq karta raqami bilan."""
        await self.send_many(
            admin_ids,
            texts.WD_ADMIN_NEW.format(
                id=w.id,
                user=user_tg,
                amount=fmt_money(w.amount),
                net=fmt_money(w.net_amount),
                card=pretty_card(card_pan),
            ),
        )
