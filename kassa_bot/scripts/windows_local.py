"""Docker’siz ishga tushirish (Windows/macOS/Linux): o‘rnatilgan PostgreSQL + xotiradagi Redis.

PostgreSQL `pgserver` paketi bilan `.local/pgdata` papkasida ishga tushadi (o‘rnatish shart
emas), keyin migratsiya + seed, so‘ng bot, API, worker va userbot bitta jarayonda
(`scripts/run_local.py`). START_WINDOWS.cmd shu skriptni chaqiradi.

    python scripts/windows_local.py

Faqat sinov / kichik hajm uchun. Productionda Docker Compose ishlating.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def start_postgres() -> object:
    import pgserver

    data = ROOT / ".local" / "pgdata"
    data.parent.mkdir(parents=True, exist_ok=True)
    server = pgserver.get_server(data, cleanup_mode="stop")
    uri = server.get_uri()  # postgresql://postgres:@127.0.0.1:PORT/postgres (Windows)
    os.environ["DATABASE_URL"] = uri.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgres:@", "postgres@", 1
    )
    return server


def main() -> None:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    print("🐘 PostgreSQL ishga tushirilmoqda…", flush=True)
    server = start_postgres()
    os.environ["REDIS_URL"] = "memory://"
    os.environ.setdefault("BOT_MODE", "polling")

    print("🗄  Migratsiya va boshlang‘ich ma’lumotlar…", flush=True)
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
    subprocess.run([sys.executable, "-m", "app.seed"], check=True)

    print("🤖 Bot ishga tushmoqda. Telegramda /admin yozing. To‘xtatish: Ctrl+C", flush=True)
    sys.path.insert(0, str(ROOT / "scripts"))
    from run_local import main as run_all

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        pass
    finally:
        del server  # cleanup_mode="stop" — PostgreSQL to‘xtatiladi


if __name__ == "__main__":
    main()
