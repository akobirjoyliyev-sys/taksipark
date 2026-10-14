"""Botga Web App tugmasini ulash (chat menyu tugmasi + /start dagi inline tugma)."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, WebAppInfo

from app.config import Config

log = logging.getLogger(__name__)

WEBAPP_PATH = "/webapp/"
MENU_TEXT = "💳 Kassa"


def webapp_url(config: Config) -> str | None:
    """Telegram Web App faqat HTTPS manzilda ochiladi."""
    base = config.public_base_url.rstrip("/")
    return base + WEBAPP_PATH if base.startswith("https://") else None


async def setup_menu_button(bot: Bot, config: Config, enabled: bool) -> None:
    url = webapp_url(config) if enabled else None
    try:
        if url:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text=MENU_TEXT, web_app=WebAppInfo(url=url))
            )
            log.info("Web App menyu tugmasi o‘rnatildi: %s", url)
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonDefault())
            if enabled:
                log.warning(
                    "Web App o‘chiq: PUBLIC_BASE_URL https:// bilan boshlanishi kerak (hozir: %s)",
                    config.public_base_url,
                )
    except Exception:
        log.warning("Web App menyu tugmasini o‘rnatib bo‘lmadi", exc_info=True)
