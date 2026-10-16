"""Bir marta ishga tushiriladi: Telegramga kirib SESSION_STRING beradi."""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

from config import API_HASH, API_ID, DEVICE_MODEL

with TelegramClient(StringSession(), API_ID, API_HASH, device_model=DEVICE_MODEL) as client:
    me = client.get_me()
    print(f"\nKirildi: {me.first_name} (id {me.id})")
    print("\nQuyidagi satrni .env dagi SESSION_STRING= ga qo'ying.")
    print("DIQQAT: bu satr akkauntingizga TO'LIQ kirish beradi, hech kimga bermang!\n")
    print(client.session.save())
