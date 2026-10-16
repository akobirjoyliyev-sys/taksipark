import os
import sys
from pathlib import Path


def load_env(path=Path(__file__).with_name(".env")):
    """.env faylini o'qiydi (docker compose env_file bilan ham ishlaydi)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"Xato: {name} .env faylida ko'rsatilmagan.")
    return value


load_env()
API_ID = int(require("API_ID"))
API_HASH = require("API_HASH")
# Aktiv seanslar ro'yxatida shu nom bilan ko'rinadi — kerak bo'lsa o'sha yerdan o'chirasiz
DEVICE_MODEL = "Online Keeper"
