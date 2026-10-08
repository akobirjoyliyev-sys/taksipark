#!/data/data/com.termux/files/usr/bin/bash
# Kassa botini Termux'da TEST uchun ishga tushirish.
# Foydalanish:  curl -fsSL <url>/termux.sh | bash -s PAROL
set -e
PW="$1"
[ -z "$PW" ] && { echo "Parol berilmadi: bash -s PAROL"; exit 1; }
say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

termux-wake-lock 2>/dev/null || true

say "1/7 Paketlar yangilanmoqda"
yes | pkg update -y >/dev/null 2>&1 || true
pkg install -y python postgresql redis unzip curl openssl-tool build-essential binutils libffi >/dev/null

say "2/7 Kod yuklab olinmoqda"
cd "$HOME"
curl -fsSL -o kb.enc https://raw.githubusercontent.com/akobirjoyliyev-sys/taksipark/kassa-transfer/kb.enc
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in kb.enc -out kassa_bot_full.zip -pass pass:"$PW"
rm -rf kassa_bot && unzip -q -o kassa_bot_full.zip
cd kassa_bot

say "3/7 Python kutubxonalari (10-20 daqiqa ketishi mumkin)"
pkg install -y python-cryptography >/dev/null 2>&1 || true
say "    Rust o'rnatilmoqda (pydantic-core uchun kerak)"
pkg install -y rust >/dev/null
pkg install -y maturin >/dev/null 2>&1 || true
export ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null || echo 24)"
export CARGO_BUILD_TARGET=aarch64-linux-android
[ "$(uname -m)" = "aarch64" ] || unset CARGO_BUILD_TARGET
export AIOHTTP_NO_EXTENSIONS=1 MULTIDICT_NO_EXTENSIONS=1 YARL_NO_EXTENSIONS=1 \
       FROZENLIST_NO_EXTENSIONS=1 PROPCACHE_NO_EXTENSIONS=1
pip install "aiogram>=3.15,<4" "SQLAlchemy[asyncio]>=2.0.36,<2.1" "asyncpg>=0.30" "alembic>=1.14" \
  "redis>=5.2" "pydantic>=2.9" "pydantic-settings>=2.6" "httpx>=0.27" tzdata "telethon>=1.36,<2"

say "4/7 PostgreSQL ishga tushirilmoqda"
PGD="$PREFIX/var/lib/postgresql"
if [ ! -f "$PGD/PG_VERSION" ]; then mkdir -p "$PGD" && initdb "$PGD" >/dev/null; fi
pg_ctl -D "$PGD" status >/dev/null 2>&1 || pg_ctl -D "$PGD" -l "$PGD/log" start >/dev/null
sleep 3
psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='kassa'" | grep -q 1 \
  || psql -d postgres -c "CREATE USER kassa SUPERUSER PASSWORD 'kassa'" >/dev/null
psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='kassa'" | grep -q 1 \
  || createdb -O kassa kassa

say "5/7 Redis ishga tushirilmoqda"
redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes >/dev/null

say "6/7 Baza sxemasi yaratilmoqda"
alembic upgrade head
python -m app.seed

say "7/7 Worker va bot ishga tushirilmoqda"
nohup python -m app.jobs > worker.log 2>&1 &
echo "Bot ishlayapti. Telegram'da /start yozing. To'xtatish: Ctrl+C"
python -m app.bot
