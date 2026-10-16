"""Bir marta ishga tushiriladi: Telegramga kiradi va SESSION_STRING ni .env ga yozadi."""
from pathlib import Path

from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from config import API_HASH, API_ID, DEVICE_MODEL

ENV = Path(__file__).with_name(".env")


def save_session(session, path=ENV):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith("SESSION_STRING=")]
    lines.append(f"SESSION_STRING={session}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)


if __name__ == "__main__":
    with TelegramClient(StringSession(), API_ID, API_HASH, device_model=DEVICE_MODEL) as client:
        me = client.get_me()
        save_session(client.session.save())
        print(f"\nKirildi: {me.first_name} (id {me.id})")
        print(f"Seans {ENV} fayliga saqlandi. Bu faylni hech kimga bermang!")
