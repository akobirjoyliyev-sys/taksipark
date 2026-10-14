"""Provayder webhooklarini qayta ishlash — FastAPI va sandbox sahifalari uchun umumiy."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app import texts
from app.core.enums import ProviderEventKind
from app.core.permissions import Perm
from app.payments.base import ProviderEvent
from app.repositories.payments import WebhookEventRepository
from app.services.audit import jsonable
from app.services.container import Services
from app.services.deposits import DepositOutcome
from app.services.withdrawals import WithdrawalEvent

log = logging.getLogger(__name__)


@dataclass(slots=True)
class WebhookResult:
    status: str
    deposit: DepositOutcome | None = None
    withdrawal: WithdrawalEvent | None = None
    card_owner: int | None = None
    card_mask: str | None = None


async def process_provider_event(
    svc: Services, provider_code: str, event: ProviderEvent
) -> WebhookResult:
    """Bitta tranzaksiyada: hodisani yozish (idempotentlik) + holatni qo‘llash."""
    inserted = await WebhookEventRepository(svc.session).insert_if_new(
        provider=provider_code,
        event_id=event.event_id,
        kind=event.kind,
        reference=event.reference,
        status=event.status.value,
        payload=jsonable(dict(event.raw)),
    )
    if inserted is None:
        # Hech narsa yozilmagan; commit tranzaksiyani yopadi va obyektlarni eskirtirmaydi.
        await svc.session.commit()
        log.info("Takroriy webhook provider=%s event=%s", provider_code, event.event_id)
        return WebhookResult("duplicate")

    result = WebhookResult("ok")
    if event.kind == ProviderEventKind.PAYMENT:
        result.deposit = await svc.deposits.apply_status(
            provider_code=provider_code,
            reference=event.reference,
            status=event.status,
            external_id=event.external_id,
            amount=event.amount,
        )
    elif event.kind == ProviderEventKind.PAYOUT:
        result.withdrawal = await svc.withdrawals.apply_payout_status(
            event.reference, event.status, event.external_id, event.error
        )
    elif event.kind == ProviderEventKind.CARD_BINDING:
        bound = await svc.cards.complete_binding(
            provider_code, event.reference, event.card_token, event.card_mask
        )
        if bound is not None:
            result.card_owner, result.card_mask = bound[1], bound[0].masked_pan
    await svc.session.commit()
    return result


async def notify_result(svc: Services, result: WebhookResult) -> None:
    """Commitdan keyin bildirishnomalar (xato bo‘lsa ham to‘lov holatiga ta’sir qilmaydi)."""
    try:
        if result.deposit is not None:
            await svc.notifier.deposit(result.deposit)
            if result.deposit.amount_mismatch:
                admins = await svc.admins.telegram_ids_with(Perm.WITHDRAW_PROCESS)
                await svc.notifier.send_many(
                    admins, f"⚠️ To‘lov #{result.deposit.payment.id}: summa mos kelmadi."
                )
        if result.withdrawal is not None:
            await svc.notifier.withdrawal(result.withdrawal)
        if result.card_owner:
            await svc.notifier.send(
                result.card_owner, texts.CARD_BOUND.format(mask=result.card_mask)
            )
    except Exception:
        log.exception("Webhook bildirishnomasida xato")
