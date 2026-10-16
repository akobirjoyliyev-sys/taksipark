# Telegram 24/7 onlayn userbot

Akkauntingizni doim **"online"** ko'rsatib turadi. Faqat bitta ish qiladi —
har ~60 soniyada Telegramga "men onlaynman" (`account.updateStatus`) signalini yuboradi.

## Nega xavfsiz

- Xabarlarni **o'qimaydi, yozmaydi**, kontakt/guruhlarga tegmaydi (`receive_updates=False`).
- Rasmiy Telegram API va o'zingizning `api_id`/`api_hash` ishlatiladi — parol hech qayerga yuborilmaydi.
- Seans "Aktiv seanslar"da **Online Keeper** nomi bilan ko'rinadi — xohlagan payt
  *Sozlamalar → Qurilmalar* dan o'chirib tashlaysiz, bot darhol ishlamay qoladi.
- So'rovlar kam (daqiqada 1 ta) va tasodifiy oraliq bilan — spam/ban xavfi juda past.
- FloodWait, internet uzilishi, seans bekor qilinishi to'g'ri ishlanadi.

## O'rnatish

1. **API kalit**: https://my.telegram.org → *API development tools* → `api_id` va `api_hash` oling.
2. `.env.example` ni `.env` ga nusxalang va `API_ID`, `API_HASH` ni yozing.
3. Bir marta login qiling (kompyuteringizda):
   ```bash
   pip install -r requirements.txt
   python login.py
   ```
   Telefon raqam, SMS/Telegram kodi va (bo'lsa) 2FA parolni so'raydi.
   Chiqqan uzun satrni `.env` dagi `SESSION_STRING=` ga qo'ying.
4. Ishga tushiring:
   ```bash
   python online.py
   ```

## 24/7 ishlatish (server / VPS)

Kompyuter o'chsa bot ham to'xtaydi, shuning uchun doim yoniq server kerak
(istalgan arzon VPS, masalan 1 vCPU / 512 MB yetadi).

**Docker bilan** (tavsiya):
```bash
docker compose up -d --build
docker compose logs -f      # loglarni ko'rish
```
`restart: unless-stopped` tufayli server qayta yonsa ham o'zi ishga tushadi.

**Docker'siz (systemd)**:
```bash
sudo useradd -r userbot
sudo cp -r . /opt/userbot && sudo chown -R userbot /opt/userbot
cd /opt/userbot && sudo -u userbot python3 -m venv venv && sudo -u userbot venv/bin/pip install -r requirements.txt
sudo cp online.service /etc/systemd/system/ && sudo systemctl enable --now online
journalctl -u online -f
```

## Muhim ogohlantirishlar

- `SESSION_STRING` = akkauntingiz kaliti. **Hech kimga bermang**, GitHub'ga yuklamang
  (`.env` allaqachon `.gitignore` da).
- Akkauntga **2 bosqichli tasdiqlash (2FA)** ni yoqib qo'ying.
- Boshqa odamlarning "tayyor userbot"lariga seans bermang — ular akkauntingizni o'g'irlashi mumkin.
- Doim onlayn turish Telegram tomonidan taqiqlanmagan, lekin har qanday avtomatlashtirish
  kabi 100% kafolat yo'q. Yangi ochilgan akkauntlarda ehtiyot bo'ling.
