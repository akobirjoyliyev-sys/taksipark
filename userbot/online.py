"""Akkauntni 24/7 "onlayn" holatda ushlab turadi.

Faqat account.updateStatus(offline=False) yuboradi: xabarlarni o'qimaydi,
yozmaydi, kontaktlarga tegmaydi.
"""
import asyncio
import logging
import os
import random
import sys

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl.functions.account import UpdateStatusRequest

from config import API_HASH, API_ID, DEVICE_MODEL, require

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("online")
logging.getLogger("telethon").setLevel(logging.WARNING)

INTERVAL = min(max(int(os.environ.get("INTERVAL", "60")), 30), 240)


async def main():
    client = TelegramClient(
        StringSession(require("SESSION_STRING")),
        API_ID,
        API_HASH,
        device_model=DEVICE_MODEL,
        receive_updates=False,  # kiruvchi xabarlar umuman olinmaydi
        connection_retries=None,  # internet uzilsa cheksiz qayta ulanadi
        retry_delay=10,
    )
    await client.connect()
    if not await client.is_user_authorized():
        sys.exit("Seans yaroqsiz. `python login.py` ni qayta ishga tushiring.")

    me = await client.get_me()
    log.info("Ishga tushdi: %s (id %s), har ~%s s", me.first_name, me.id, INTERVAL)

    try:
        while True:
            try:
                await client(UpdateStatusRequest(offline=False))
            except errors.FloodWaitError as e:
                log.warning("Telegram %s s kutishni so'radi", e.seconds)
                await asyncio.sleep(e.seconds + 5)
                continue
            except (errors.AuthKeyUnregisteredError, errors.SessionRevokedError,
                    errors.UserDeactivatedError):
                sys.exit("Seans bekor qilingan (Aktiv seanslardan o'chirilgan). login.py ni qayta bajaring.")
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                log.warning("Ulanish xatosi: %s — 15 s dan keyin qayta urinadi", e)
                await asyncio.sleep(15)
                continue
            # Bir xil ritmda emas, biroz tasodifiy oraliq bilan
            await asyncio.sleep(INTERVAL + random.uniform(-10, 10))
    finally:
        try:
            await client(UpdateStatusRequest(offline=True))
        except Exception:
            pass
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("To'xtatildi")
