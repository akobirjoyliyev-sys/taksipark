"""Runtime integratsiyalar: admin panelda saqlangan sozlamalarni jonli klientlarga qo‘llash."""

from __future__ import annotations

import logging

from app.services.container import Services

log = logging.getLogger(__name__)


async def apply_runtime_integrations(svc: Services) -> None:
    """Joriy DB sozlamalarini Mob-Cash klienti kabi jonli obyektlarga o‘tkazadi.

    Sozlama admin panelda o‘zgargan zahoti chaqiriladi (+ fon rejimida 60 sekundda bir marta),
    shu sababli jarayonni qayta ishga tushirish talab qilinmaydi.
    """
    rt = await svc.settings.snapshot()
    if svc.mobcash is not None:
        await svc.mobcash.set_credentials(
            rt.mobcash_cashbox_code, rt.mobcash_login, rt.mobcash_password
        )
