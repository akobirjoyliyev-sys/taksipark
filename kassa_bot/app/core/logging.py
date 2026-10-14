from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_CARD_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")
_BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_SECRET_KV_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|cvv|cvc|pin|signature|authorization)"
    r"(\"?\s*[:=]\s*\"?|\s+)([^\s\"',&}]+)"
)


def _mask_card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"****{digits[-4:]}"


def redact(text: str) -> str:
    """Logga tushishi mumkin bo‘lgan maxfiy qiymatlarni yashiradi."""
    text = _BOT_TOKEN_RE.sub("<bot-token>", text)
    text = _CARD_RE.sub(_mask_card, text)
    return _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # formatlashdagi xato logni to‘xtatmasin
            return True
        record.msg = redact(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_format: bool = False) -> None:
    for stream in (
        sys.stdout,
        sys.stderr,
    ):  # Windows: faylga yo‘naltirilganda cp1252 emojini yoza olmaydi
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
