# MobCash API integratsiyasi — 2026-10-09

Bu yangilanish buyurtmachi yuborgan v2 login / v1 mobile hujjati asosida tayyorlandi.
Avvalgi botdagi admin panel, P2P, Web App va ko‘p kassa imkoniyatlari saqlangan.
Haqiqiy kassa paroli va Telegram tokeni distributivga kiritilmagan.

## API mosligi

| Amal | Manzil | So‘rovdagi asosiy ma’lumot |
|---|---|---|
| Avtorizatsiya | `https://admin.mob-cash.com/api/v2/cashbox/login` | `cashboxCode`, `login`, `password` |
| Akkauntni tekshirish | `https://admin.mob-cash.com/api/v1/mobile/payerNickname` | `payerID`, `sessionID`, `userID` |
| Pul kiritish | `https://admin.mob-cash.com/api/v1/mobile/deposit` | `deposit.amount` — satr, `deposit.payerID`, sessiya |
| Yechish summasi | `https://admin.mob-cash.com/api/v1/mobile/getWithdrawalAmount` | `withdraw.payerID`, `withdraw.withdrawalCode`, sessiya |
| Yechishni bajarish | `https://admin.mob-cash.com/api/v1/mobile/withdrawal` | `withdraw.amount` — JSON son, ID, kod va sessiya |

Barcha so‘rovlar POST va JSON. Mobile metodlarida `Authorization: Bearer <accessToken>`
bor; tana `id`, `jsonrpc: "2.0"`, `params` shaklida yuboriladi. `sign` va `confirm`
qo‘shilmaydi. Bir elementli JSON-RPC massiv javobi qabul qilinadi. Hujjatdagi misollarda
so‘rov/javob ID'lari farqli bo‘lgani sababli bitta javobda ID tengligi majburiy emas;
ko‘p elementli javobda esa so‘rov ID'si bo‘yicha yagona natija tanlanadi.

## O‘zgargan joylar

- Har bir `deposit` oldidan, shu jumladan admin qaytarishi va token yangilangandan
  keyin ham, aynan ishlatilayotgan sessiyada `payerNickname` bajariladi.
- Login javobida token, sessionID va userID tekshiriladi. Muddati o‘tgan token
  yangilanadi; 401/403 javobidan keyin ko‘pi bilan bir marta qayta avtorizatsiya qilinadi.
- Token keshi API manzillari, kassa, login va parolga bog‘langan. Redis ishlamasa yoki
  boshqa jarayon login qilayotgan bo‘lsa, parallel yangi sessiya ochilmaydi.
- `success: true` aniq kelmasa, bo‘sh/buzilgan javob muvaffaqiyat deb belgilanmaydi.
  Timeout, 5xx, 408 va buzilgan pul amali javobi tekshiruvga yuboriladi; pul so‘rovi
  o‘z-o‘zidan qaytarilmaydi. Login/akkaunt tekshiruvidagi uzilish esa depozit hali
  yuborilmagan holat sifatida ajratiladi.
- Manfiy, nol, NaN/Infinity, 2 tadan ortiq kasrli yoki 1 trln dan katta yuboriladigan
  summa rad etiladi. Bu botning mavjud `Numeric(18, 2)` pul formatiga mos.
- Kassada `isDeposit=false` yoki `isWithdrawal=false` bo‘lsa, tegishli pul so‘rovi
  yuborilmaydi.
- Admin qaytarishi HTTP so‘rovidan oldin `refund_review` holatida saqlanadi.
  Natija noaniq yoki jarayon uzilgan bo‘lsa, takroriy qaytarish va kartaga to‘langan
  deb belgilash bloklanadi. Tekshiruv uchun admin tugmalari qo‘shildi.

## Sozlash

1. Python 3.12+, PostgreSQL va Redis o‘rnating yoki loyihadagi Docker Compose'dan
   foydalaning. `.env.example` nusxasini `.env` nomi bilan yarating.
2. `.env` ichida `BOT_TOKEN`, `ADMIN_IDS`, ma’lumotlar bazasi va Redis manzillarini
   o‘zingizning serveringizda to‘ldiring. Maxfiy qiymatlarni chatga yuborish kerak emas.
3. Bitta kassa uchun `MOBCASH_CASHBOX_CODE`, `MOBCASH_LOGIN`, `MOBCASH_PASSWORD`ni
   kiriting. Bir nechta kassa uchun botda `/admin → 🏢 Kantoralar → ➕ Mobcash kassa
   qo‘shish` yo‘lidan foydalaning. Hujjatdagi namuna login/parolni ishlatmang.
4. `MOBCASH_AUTH_URL` va `MOBCASH_API_URL` qiymatlarini namunadagi asosiy manzil
   ko‘rinishida qoldiring: ularga `/login` yoki `/withdrawal`ni qo‘shmang.
5. Mavjud Docker serverida loyihani yangilash uchun:

   ```bash
   docker compose up -d --build
   ```

   Docker ishlatilmasa, o‘z virtual muhitingizda:

   ```bash
   pip install -e ".[dev]"
   alembic upgrade head
   python -m app.seed
   ```

   Bot, API, worker va userbot jarayonlarini README'dagi tartibda qayta ishga tushiring.
   Barcha jarayonlar bir xil yangilangan kod bilan ishlashi kerak.
6. `/admin → 🏢 Kantoralar` ichida tegishli kassani tanlab ulanishni tekshiring;
   yagona eski kassa uchun `/admin → 🏦 Mob-Cash kassa → 🔌 Ulanishni tekshirish`.
   Bu login tekshiruvi, pul o‘tkazish amali emas.
7. P2P depozitlar uchun kassir kartasi va bank xabarlarini o‘qiydigan userbotni
   README'dagi tartibda sozlang. Web App uchun HTTPS `PUBLIC_BASE_URL` kerak.

`refund_review` mavjud VARCHAR(32) status ustuniga yoziladi; ushbu yangilanish
uchun yangi ma’lumotlar bazasi migratsiyasi yo‘q. Oldingi 0001–0004 migratsiyalar
odatdagidek talab qilinadi. Serverni yangilashdan oldin bazaning zaxira nusxasini oling.
`refund_review` yozuvlari mavjud paytda eski kodga qaytmang: eski versiya bu statusni
tanimaydi.

## Real pul va test rejimi

`PAYMENT_MODE=test` faqat ichki hamyon/Sandbox adapteriga tegishli. MobCash uchun
haqiqiy kassa ma’lumotlari qo‘yilsa va u yoqilsa, so‘rovlar real hisobga ta’sir qiladi.
Yuborilgan hujjatda MobCash sandbox manzili ko‘rsatilmagan.

MobCash `withdrawal` hisobdan kassaga yechishni tasdiqlaydi. Berilgan API'da bank
kartasiga avtomatik o‘tkazish metodi yo‘q: botda keyingi kartaga to‘lovni admin bajaradi.

## Tekshiruv natijasi va chegaralari

- `pytest tests/unit -q`: **150 ta test o‘tdi**, jumladan yangi API kontrakti va
  qaytarish uzilishi sinovlari. HTTP javoblar `httpx.MockTransport`, Redis esa
  `fakeredis` bilan sinovdan o‘tkazildi.
- O‘zgargan Python fayllarida `ruff check` xatosiz yakunlandi.
- PostgreSQL bilan integratsiya testlari bu muhitda bajarilmadi: lokal PostgreSQL
  ishga tushmadi. Qaytarish holatlari unit-testlarda DB o‘rnidagi adapter bilan tekshirildi;
  haqiqiy tranzaksiya va parallel DB locklari shu sinovga kirmaydi.
- Haqiqiy MobCash serveri, Telegram akkaunti va bank xabarlari bilan tashqi sinov
  bajarilmadi. To‘liq real tizim tayyorligi bu natijalardan kelib chiqmaydi.

O‘z serveringizda PostgreSQL testlarini faqat alohida, bo‘sh test bazasida bajaring:
`tests/conftest.py` test bazasini tozalaydi va migratsiyalarni qayta yaratadi.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://test_user:test_password@localhost:5432/kassa_test pytest -q
```

Production bazasining manzilini `TEST_DATABASE_URL`ga bermang.

Admin qaytarishi noaniq qolsa: `Mob-Cash kassa → Yechishlar → Tekshiruvda`ni oching,
MobCash panelidan tekshiring, keyin «qaytarilgan» yoki «qaytarilmagan»ni belgilang.
Jarayon kutilmaganda to‘xtagan bo‘lsa, qulf tugashi uchun 3 daqiqagacha kutish mumkin.
Bu tasdiqlash tugmalari o‘zlari pul so‘rovi yubormaydi.
