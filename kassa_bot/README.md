# Kassa — Telegram hamyon va to‘lov boshqaruvi boti

O‘zbek (lotin) tilidagi Telegram bot: hamyon, hisob to‘ldirish, kartaga pul
chiqarish, bonuslar (promokod, VIP, referal), majburiy obuna va to‘liq `/admin` panel.

> **MobCash integratsiyasi yangilandi (2026-10-09).** API va ishga tushirish tafsilotlari:
> [docs/MOBCASH_SETUP_UZ.md](docs/MOBCASH_SETUP_UZ.md).
>
> Ichki hamyonning **Sandbox** adapteri test uchun. MobCash alohida ishlaydi:
> haqiqiy kassa ulangan va `MOBCASH_ENABLED=true` bo‘lsa, `PAYMENT_MODE=test` holatida ham
> MobCash so‘rovlari real hisobga ta’sir qiladi. Avtomatik testlar tashqi API'ga ulanmaydi.
> Sandbox karta bog‘lashda token ishlatiladi; P2P/MobCash oqimida karta raqami bazada
> saqlanadi. CVV va PIN talab qilinmaydi.

## Texnologiyalar

Python 3.12+, aiogram 3, PostgreSQL 16, SQLAlchemy 2 (async) + Alembic, Redis (FSM, kesh, rate
limit, lock), FastAPI (webhooklar), Docker Compose, pytest, ruff/black/mypy.

## Arxitektura

```
app/
├── bot/            # aiogram: handlers/, keyboards/, states/, middlewares/, factory
│   └── handlers/   # start, wallet, deposit, withdraw, bonus, info, common (fallback/xatolar)
├── admin/          # /admin panel: dashboard, stats, users, settings, payouts, join, bonus, channels
├── services/       # biznes mantiq (ledger, deposits, withdrawals, bonus, settings, stats, ...)
├── repositories/   # SQL so‘rovlar
├── models/         # SQLAlchemy modellari
├── payments/       # provayder interfeysi (base.py), sandbox adapteri, registry
├── webhooks/       # FastAPI: provayder webhooklari, Telegram webhook, sandbox sahifalari
├── jobs/           # background worker: payout navbati, retry, expiry, reconciliation, hisobot
├── core/           # enums, ruxsatlar (RBAC), pul formatlash, xavfsiz logging, utils
├── texts.py        # barcha UI matnlari
└── seed.py         # boshlang‘ich/demo ma’lumotlar
migrations/         # Alembic
tests/unit, tests/integration
docs/               # API.md, DB_SCHEMA.md, CHECKLIST.md
```

**Jarayonlar** (har biri alohida konteyner):

| Xizmat   | Buyruq                         | Vazifasi                                                       |
|----------|--------------------------------|----------------------------------------------------------------|
| `bot`    | `python -m app.bot`            | Telegram long-polling (`BOT_MODE=polling`)                     |
| `api`    | `uvicorn app.webhooks.app:app` | provayder webhooklari, sandbox sahifalari, Telegram webhook    |
| `worker` | `python -m app.jobs`           | payout navbati, retry/backoff, expiry, reconciliation, hisobot |
| `userbot`| `python -m app.userbot`        | bank xabarlarini o‘qib P2P to‘lovlarni tasdiqlaydi (1 nusxa)   |
| `migrate`| `alembic upgrade head && python -m app.seed` | sxema + boshlang‘ich ma’lumotlar                 |

**Asosiy tamoyillar**

- **Provayder adapteri:** `PaymentProvider` interfeysi — `create_payment`, `verify_webhook`,
  `create_payout`, `check_status` (+ `create_card_binding`). Handlerlarda provayderga xos kod yo‘q.
- **Immutable ledger:** balans faqat `ledger_entries` yozuvi orqali o‘zgaradi; har yozuvda
  `idempotency_key` (UNIQUE). `ledger_entries`, `audit_logs`, `withdrawal_status_history`
  jadvallarida UPDATE/DELETE PostgreSQL triggeri bilan taqiqlangan.
- **Atomarlik:** hamyon `SELECT … FOR UPDATE` bilan bloklanadi; payout navbati
  `FOR UPDATE SKIP LOCKED` — bir nechta worker xavfsiz.
- **Idempotent webhook:** `(provider, event_id)` UNIQUE + to‘lov qatori lock; balans bir marta oshadi.
  Imzo HMAC-SHA256 + timestamp (replay himoyasi, 5 daqiqa).
- **RBAC:** superadmin, admin, operator, auditor (`app/core/permissions.py`). Har admin amali
  `audit_logs`ga yoziladi (kim, qachon, oldin/keyin).
- **Himoya:** Redis rate limit (soniya/daqiqa), parametrlangan SQL (SQLAlchemy), kiritmalarni
  validatsiya, HTML escape, loglarda karta/token/sirlar avtomatik yashiriladi.

## Mob-Cash + P2P avto to‘lov + Userbot

`MOBCASH_ENABLED=true` bo‘lsa «➕ Hisob to‘ldirish» va «➖ Pul chiqarish» tugmalari to‘g‘ridan-
to‘g‘ri o‘yin hisobi (Mob-Cash kassa API) bilan ishlaydi; botdagi ichki hamyon ishlatilmaydi.

### Oqimlar

**➕ To‘ldirish (P2P noyob summa):**
1. Foydalanuvchi o‘yin ID sini yuboradi → bot Mob-Cash `payerNickname` bilan tekshiradi.
2. Summa kiritiladi (masalan 50 000) → bot **noyob summa** beradi: `50 437` va kassir kartasi.
3. Foydalanuvchi aynan shu summani kartaga o‘tkazadi.
4. **Userbot** kartaning bank xabarini (@CardXabarBot / HUMO) o‘qiydi: `➕ 50 437.00 UZS`.
5. Summa kutilayotgan to‘lovga mos keladi → Mob-Cash `deposit` → foydalanuvchiga «✅ tushirildi».

**➖ Yechish:** ID → ilovadagi yechish kodi (xabar darhol o‘chiriladi) → Mob-Cash
`getWithdrawalAmount` (summa + komissiya ko‘rsatiladi) → karta raqami → tasdiq → Mob-Cash
`withdrawal` → adminlarga ariza → admin kartaga o‘tkazib «✅ Kartaga o‘tkazdim» bosadi.

**↩️ Qaytarish:** kartaga o‘tkazish imkonsiz bo‘lsa, admin hisobga qaytarishni tanlaydi.
`payerNickname` har bir `deposit` oldidan, jumladan qaytarishda ham bajariladi.
Qaytarish natijasi noma’lum qolsa, ariza `refund_review` holatiga o‘tadi. Admin
«Yechishlar → Tekshiruvda» bo‘limida MobCash panelini tekshirib, «qaytarilgan» yoki
«qaytarilmagan»ni belgilaydi. Tekshiruv tugamaguncha qayta yuborish va kartaga
to‘langan deb belgilash bloklanadi.

### Xavfsizlik qoidalari (nima uchun shunday)

| Qoida | Sabab |
|---|---|
| Bir vaqtda ikki kutilayotgan to‘lov bir xil summaga ega bo‘lmaydi (DB partial unique index) | Bank xabarini aniq bitta foydalanuvchiga bog‘lash |
| Muddati o‘tgan summa `P2P_LATE_GRACE_HOURS` davomida qayta berilmaydi | Kechikkan to‘lov boshqa odamga tushib qolmasin |
| Depozit yaratilishidan **oldingi** bank xabari mos kelmaydi | Eski o‘tkazma yangi to‘lovni «to‘lamasin» |
| Faqat manba botning o‘zi yozgan, forward qilinmagan xabarlar | Soxta «➕ 50 000 UZS» xabari ishlamaydi |
| Bank xabari bir marta qayta ishlanadi (akkaunt TG ID + chat + xabar ID) | Restart/poll takrorlari |
| Mob-Cash javobi **noaniq** (timeout/5xx) bo‘lsa avtomatik qayta yuborilmaydi → «🕵️ tekshiruv» | Pulni ikki marta tushirib/yechib yubormaslik |
| Ulanish xatosi (so‘rov yetib bormagan) — 5 martagacha avtomatik qayta urinish | Vaqtinchalik tarmoq uzilishlari |
| Mob-Cash tokeni Redis’da umumiy | Jarayonlar bir-birining sessiyasini bekor qilmasin |
| Userbot sessiyasi Fernet bilan shifrlangan, kod/parol xabarlari o‘chiriladi | Akkauntga to‘liq kirish huquqi |

### Sozlash

1. `.env`: `MOBCASH_CASHBOX_CODE`, `MOBCASH_LOGIN`, `MOBCASH_PASSWORD` (Mob-Cash beradi).
2. `.env`: `TG_API_ID`, `TG_API_HASH` — https://my.telegram.org → API development tools;
   `USERBOT_SESSION_KEY` — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
3. `alembic upgrade head`.
4. `/admin → 🏦 Mob-Cash kassa → 🔌 Ulanishni tekshirish` — kassa ulanganini tekshiring.
5. `/admin → 🏦 Mob-Cash kassa → 💳 P2P kartalar → ➕` — `8600123412341234 | Ism Familiya | Uzcard`.
6. Karta bank xabarlari keladigan Telegram akkauntda @CardXabarBot / HUMO botini ulang.
7. `/admin → 🛰 Userbot → ➕ Userbot qo‘shish` (faqat superadmin): telefon → kod
   (**raqamlar orasiga bo‘sh joy qo‘yib**: `1 2 3 4 5`, aks holda Telegram kodni bloklaydi) → 2FA.
8. `python -m app.userbot` (yoki `scripts/run_local.py` — hammasi bitta jarayonda).

### Admin bo‘limlari

- **🏦 Mob-Cash kassa** — holat va bugungi statistika; 📤 yechishlar (to‘lash / o‘yin hisobiga
  qaytarish / noaniqlarni tasdiqlash); 🧾 depozitlar (qayta yuborish, qo‘lda tasdiqlash, rad);
  ❓ mos kelmagan kirimlar (noto‘g‘ri summa o‘tkazilsa depozitga qo‘lda bog‘lash); 💳 kartalar.
- **🛰 Userbot** — akkauntlar holati, qo‘shish/o‘chirish, kuzatiladigan bank botlari.
- Ruxsatlar: `mobcash.view` (hamma), `mobcash.process` (operator+), `mobcash.manage` (admin+),
  `userbot.manage` (faqat superadmin).

Bank xabari formati o‘zgarsa — `app/p2p/parser.py` va `tests/unit/test_p2p_parser.py`ga yangi
namunani qo‘shing. Mos kelmagan kirimlar admin panelda xom matni bilan ko‘rinadi.

## 🏢 Bir nechta bukmeker (kantoralar)

Har bir bukmeker (1xBet, Melbet, Betwinner ...) Mob-Cash’da **alohida kassa** — o‘z kodi, logini
va paroli bor. Ular admin paneldan boshqariladi:

`/admin → 🏢 Kantoralar`
- **➕ Mobcash kassa qo‘shish** — nom, keyin `kassa_kodi | login | parol` (xabar darhol
  o‘chiriladi). Bot avval kassaga ulanib ko‘radi, faqat ulanish muvaffaqiyatli bo‘lsa saqlaydi.
- Kantora ustiga bosish — 🟢 yoqish / 🔴 o‘chirish; **⚙️** — batafsil: ulanishni tekshirish,
  nomini o‘zgartirish, kassa ma’lumotlarini yangilash, o‘chirib tashlash.
- **📊 Tartiblash** — foydalanuvchilarga ko‘rinish tartibi.

Qoidalar:
- Foydalanuvchi to‘ldirish/yechishda kantorani tanlaydi; faol kantora bitta bo‘lsa — o‘zi tanlanadi.
- Har bir kantora uchun o‘yin ID alohida eslab qolinadi.
- Pul faqat tanlangan kantora kassasiga boradi; u ishlamasa boshqa kassaga o‘tib ketmaydi.
- Kassa paroli bazada shifrlangan (Fernet) saqlanadi.
- Tarixi bor kantorani o‘chirib bo‘lmaydi — faqat 🔴 o‘chirib qo‘yiladi (eski arizalarni
  qaytarish/tekshirish uchun kerak).
- Kantora qo‘shilmagan bo‘lsa, «🏦 Mob-Cash» dagi yagona kassa (eski rejim) ishlaydi.

## 🌐 Telegram Web App (kassa ilovasi)

Bot ichida ochiladigan to‘liq kassa: hisob to‘ldirish (kantora → ID → summa → to‘lov sahifasi,
summa/karta nusxalash, taymer, avtomatik holat yangilanishi), pul chiqarish, hamyonni
to‘ldirish, tarix, VIP/referal/promokod. Telegram mavzusiga (yorug‘/qorong‘i) moslashadi.

- Manzil: `{PUBLIC_BASE_URL}/webapp/`, API: `/api/webapp/*`.
- Har bir so‘rov Telegram imzolagan `initData` bilan tekshiriladi (HMAC, 24 soat).
- Bot startda chat menyusiga **«💳 Kassa»** tugmasini qo‘yadi, `/start` dan keyin
  «💳 Kassa ilovasini ochish» tugmasi chiqadi.
- **HTTPS shart.** Domen bo‘lmasa, test uchun:
  ```bash
  docker compose --profile tunnel up -d tunnel
  docker compose logs tunnel | grep trycloudflare     # https://xxxx.trycloudflare.com
  # .env: PUBLIC_BASE_URL=https://xxxx.trycloudflare.com
  docker compose up -d                                 # bot/api qayta ishga tushadi
  ```
  Docker’siz: `cloudflared tunnel --url http://localhost:8000`.
- Admin panel: `⚙️ Tizim Sozlamalari → 🌐 Web App` (yoqish/o‘chirish; menyu tugmasi bot
  qayta ishga tushganda yangilanadi).

## 🏆 VIP bo‘limi

`/admin → 🎁 Bonus tizimi` — **🏆 VIP bo‘limi** (foydalanuvchilarga ko‘rinadimi), **🎁 VIP
bonus** va **🤝 Referal** bitta bosish bilan yoqiladi/o‘chiriladi (audit logga yoziladi).

## Lokal ishga tushirish (Docker’siz)

Talablar: Python 3.12+, PostgreSQL 14+, Redis 6.2+.

```bash
python -m venv .venv
.venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # BOT_TOKEN, ADMIN_IDS, URLlarni to‘ldiring
alembic upgrade head
python -m app.seed --demo     # --demo: 2 ta demo foydalanuvchi (sandbox)
```

Uchta terminalda:

```bash
python -m app.bot
uvicorn app.webhooks.app:app --port 8000
python -m app.jobs
```

## Docker bilan

```bash
cp .env.example .env          # kamida BOT_TOKEN va ADMIN_IDS
docker compose up -d --build
docker compose logs -f bot api worker
```

Testlar konteynerda: `docker compose --profile test run --rm tests`

## ENV o‘zgaruvchilari

To‘liq ro‘yxat va izohlar — `.env.example`. Asosiylari:

| O‘zgaruvchi | Tavsif |
|---|---|
| `BOT_TOKEN` | @BotFather tokeni (faqat `.env`da) |
| `ADMIN_IDS` | `id:rol` ro‘yxati, masalan `123:superadmin,456:operator` (rol yozilmasa — superadmin) |
| `BOT_MODE` | `polling` yoki `webhook` |
| `PUBLIC_BASE_URL` | API tashqi manzili (productionda HTTPS domen) |
| `PAYMENT_PROVIDERS` | ulangan adapterlar (`sandbox`) |
| `PAYMENT_MODE` | `test`/`production` (rasmiy provaydersiz production taqiqlangan) |
| `SANDBOX_WEBHOOK_SECRET` | sandbox webhook imzosi kaliti |
| `SUPPORT_URL`, `CASHBOX_URL` | 👨‍💻 Aloqa va 🌐 Kassa manzili (keyin admin paneldan o‘zgaradi) |
| `DEPOSIT_*`, `WITHDRAW_*`, `*_FEE_PERCENT`, `REFERRAL_*` | standart limitlar va foizlar |

Biznes sozlamalari ENVdan **standart qiymat** sifatida olinadi, keyin `/admin → ⚙️ Tizim
Sozlamalari`dan ikki bosqichli tasdiq bilan o‘zgartiriladi (DB + Redis kesh, audit log).

## Admin ID va rollar

1. Telegram ID ingizni bilish: [@userinfobot](https://t.me/userinfobot).
2. `.env`: `ADMIN_IDS=123456789:superadmin`.
3. Botni qayta ishga tushiring → `/admin`.

ENV adminlar har startda sinxronlanadi (ENV ustun). Qo‘shimcha xodimlarni superadmin
`/admin → 👥 Foydalanuvchilar → 🛡 Adminlar` bo‘limidan qo‘shadi.

| Rol | Imkoniyatlar |
|---|---|
| superadmin | hammasi, jumladan adminlar, kritik sozlamalar (to‘lov rejimi, provayderlar), ommaviy to‘lov tasdig‘i |
| admin | foydalanuvchilar, balans, sozlamalar, bonus, kanallar, ommaviy to‘lov yuklash |
| operator | yechish arizalari, join requestlar, xabar yuborish, ommaviy to‘lovni tasdiqlash |
| auditor | faqat ko‘rish + audit log |

## Webhooklar

- Provayder: `POST {PUBLIC_BASE_URL}/webhooks/payments/{provider}` — imzo tekshiriladi, takroriy
  hodisa `{"status":"duplicate"}` qaytaradi.
- Telegram (`BOT_MODE=webhook`): API startda `setWebhook` qiladi —
  `{PUBLIC_BASE_URL}/telegram/webhook`, `TELEGRAM_WEBHOOK_SECRET` sarlavhasi tekshiriladi.
  Bu rejimda `bot` xizmati avtomatik chiqadi, yangilanishlarni `api` qabul qiladi.
- Batafsil: [docs/API.md](docs/API.md).

## Sandbox bilan sinash

1. `➕ Hisob to‘ldirish` → summa → `💳 To‘lash` (yoki localhostda matndagi havola).
2. Sandbox sahifasida `✅ To‘lash (test)` → imzolangan webhook → balans oshadi, botda xabar.
3. `➖ Pul chiqarish` → `➕ Karta ulash` → test kartani tanlang → summa → tasdiq.
4. `/admin → 💸 Ruchnoy yechish` → arizani tasdiqlang → worker sandbox payoutini bajaradi.
   `8600 **** 0002` test kartasi payout rad etilishini, `SANDBOX_PAYOUT_FAILURE_RATE` esa
   retry/backoff va manual navbatni sinash uchun.

> Telegram `localhost` havolalarni tugma sifatida qabul qilmaydi — bunday holda havola xabar
> matnida beriladi. Tashqi test uchun `PUBLIC_BASE_URL`ga ngrok/cloudflared HTTPS manzilini qo‘ying.

## Yangi provayder qo‘shish

1. `app/payments/<provider>.py` — `PaymentProvider`dan meros: `create_payment`,
   `verify_webhook` (provayder imzo sxemasi), `create_payout` (provayder idempotentlik kaliti
   sifatida `reference`), `check_status`, kerak bo‘lsa `create_card_binding`.
2. `app/payments/registry.py → build_registry` ga ro‘yxatdan o‘tkazing; kalitlar — ENV.
3. `PAYMENT_PROVIDERS=sandbox,<provider>` → superadmin `⚙️ Faol provayderlar`ni yangilaydi.
4. Faqat rasmiy shartnoma va merchant kalitlari bilan; avval provayderning test muhitida sinang.
5. Shundan keyingina `PAYMENT_MODE=production`.

## Production deploy

- HTTPS reverse proxy (nginx/Caddy/Traefik) → `api:8000`; `PUBLIC_BASE_URL=https://domen`;
  `BOT_MODE=webhook`, kuchli `TELEGRAM_WEBHOOK_SECRET`.
- Barcha sirlarni (token, DB parol, provayder kalitlari) secret manager yoki faqat `.env`da
  saqlang; `.env`ni repoga qo‘shmang.
- PostgreSQL: muntazam backup (`pg_dump`/PITR); ilova foydalanuvchisiga `TRUNCATE`/`DROP` huquqi
  bermang. Redis: AOF yoqilgan (compose’da bor).
- Masshtab: `api` va `worker` replikalari xavfsiz (SKIP LOCKED + Redis lock); polling `bot` —
  bitta nusxa.
- Monitoring: `GET /health`, JSON loglar (`LOG_JSON=true`), kunlik hisobot adminlarga.
- Yangilash: `docker compose build && docker compose up -d` (`migrate` avtomatik ishlaydi).

## Sifat tekshiruvi

```bash
ruff check app tests migrations
black --check app tests migrations
mypy app
pytest -q                                   # unit testlar
TEST_DATABASE_URL=postgresql+asyncpg://kassa:kassa@localhost:5432/kassa_test pytest -q
```

Integratsiya testlari haqiqiy PostgreSQL’da migratsiyalarni qo‘llaydi va depozit/webhook
idempotentligi, bonuslar, yechish (tasdiq, rad, retry → manual), ommaviy to‘lov, ledger
o‘zgarmasligi va HTTP oqimini tekshiradi.

## Hujjatlar

- [docs/API.md](docs/API.md) — HTTP endpointlar, webhook formati, imzo
- [docs/DB_SCHEMA.md](docs/DB_SCHEMA.md) — jadvallar va bog‘lanishlar
- [docs/CHECKLIST.md](docs/CHECKLIST.md) — har bir menyu oqimini qo‘lda tekshirish ro‘yxati
