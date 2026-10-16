#!/usr/bin/env bash
# Ubuntu serverga o'rnatish:
#   sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/akobirjoyliyev-sys/taksipark/claude/vigilant-rubin-p5a6wd/userbot/install.sh)"
set -euo pipefail

BASE="https://raw.githubusercontent.com/akobirjoyliyev-sys/taksipark/claude/vigilant-rubin-p5a6wd/userbot"
DIR=/opt/userbot

[ "$(id -u)" -eq 0 ] || { echo "sudo bilan ishga tushiring"; exit 1; }

echo "==> Paketlar o'rnatilmoqda..."
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl >/dev/null

id userbot &>/dev/null || useradd -r -s /usr/sbin/nologin -d "$DIR" userbot
mkdir -p "$DIR"

echo "==> Fayllar yuklanmoqda..."
for f in config.py login.py online.py requirements.txt online.service; do
  curl -fsSL "$BASE/$f" -o "$DIR/$f"
done

python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q -r "$DIR/requirements.txt"

if ! grep -qE '^SESSION_STRING=.+' "$DIR/.env" 2>/dev/null; then
  echo
  echo "==> https://my.telegram.org -> API development tools dan oling:"
  read -rp "API_ID: " API_ID </dev/tty
  read -rp "API_HASH: " API_HASH </dev/tty
  printf 'API_ID=%s\nAPI_HASH=%s\nINTERVAL=60\n' "$API_ID" "$API_HASH" > "$DIR/.env"
  chmod 600 "$DIR/.env"
  echo
  echo "==> Telegramga kirish (telefon raqamni +998... ko'rinishida yozing):"
  (cd "$DIR" && venv/bin/python login.py </dev/tty)
fi

chown -R userbot:userbot "$DIR"
cp "$DIR/online.service" /etc/systemd/system/online.service
systemctl daemon-reload
systemctl enable online >/dev/null 2>&1
systemctl restart online
sleep 5
echo
systemctl --no-pager --lines=5 status online || true
echo
echo "Tayyor! Loglar:   sudo journalctl -u online -f"
echo "To'xtatish:      sudo systemctl stop online"
