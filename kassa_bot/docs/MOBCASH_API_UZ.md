# Mob-Cash API — to‘liq qo‘llanma (bizning nusxa)

Dasturchi yozgan Uzbekcha dokumentatsiya asosida tuzilgan va 2026-10-09 da real
serverda o‘tkazilgan tekshiruvlar bilan to‘ldirilgan. Dasturchi dokumentatsiyasida
yo‘q bo‘limlar: **kassani birinchi marta ulash (bir martalik kalit)** va
**xatolar lug‘ati**.

Botni sozlash, ishga tushirish va bot ichki qoidalari uchun `MOBCASH_SETUP_UZ.md`ga qarang.

## 1. Umumiy ma’lumot

API asosiy manzillari:

- Avtorizatsiya: `https://admin.mob-cash.com/api/v2/cashbox/`
- Qolgan metodlar: `https://admin.mob-cash.com/api/v1/mobile/`

Har bir so‘rov uchun umumiy qoidalar:

- `Content-Type: application/json`, `Accept: application/json, text/plain, */*`
- 2–5 metodlarda qo‘shimcha: `Authorization: Bearer <accessToken>`
- Tana (body) to‘g‘ri JSON bo‘lishi shart; `cashboxCode` **JSON son** bo‘lishi
  shart (satr bo‘lsa `validationErr` qaytadi).
- `sign` va `confirm` maydonlari hech qaysi so‘rovda shart emas.
- Mobile metodlar javobi JSON-RPC **massiv** ko‘rinishida keladi:
  `[{ "id": 5, "jsonrpc": "2.0", "result": { ... } }]`

Har bir login javobidagi uchta qiymat — `accessToken`, `sessionID`, `userID` —
keyingi barcha metodlarda kerak. `accessToken` muddati tugashi mumkin; xatolik
bo‘lsa qayta login qilinadi.

## 2. 1-metod: Avtorizatsiya (login)

```
POST https://admin.mob-cash.com/api/v2/cashbox/login
```

Body:

```json
{
  "cashboxCode": 1000042,
  "login": "cashier_JuliaPavlova",
  "password": "SoftCorp_1234"
}
```

> Hujjatdagi bu kredensiallar — **namuna**. Ular real serverda ishlamaydi.
> Real login/parol G&S qo‘llab-quvvatlash xizmatidan yoki kassa egasidan olinadi.

Muvaffaqiyatli javob:

```json
{
  "sessionID": "string",
  "userID": "string",
  "accessToken": "string",
  "expiresAt": "2026-06-10T13:30:45.738Z",
  "cashbox": {
    "id": "string",
    "code": 0,
    "currencyID": "string",
    "isDeposit": true,
    "isWithdrawal": true
  }
}
```

Xato kredensial yoki o‘chirilgan kassa: HTTP 403
`{"tr":"unauthorized","msg":"unauthorized error"}`.

## 3. 2-metod: Akkauntni tekshirish (payerNickname)

```
POST https://admin.mob-cash.com/api/v1/mobile/payerNickname
Authorization: Bearer <accessToken>
```

Body (JSON-RPC):

```json
{
  "id": 1,
  "jsonrpc": "2.0",
  "params": {
    "payerID": "1000016167",
    "sessionID": "2070115378001948672",
    "userID": "2029461258370469888"
  }
}
```

Javob: `[{"id": 5, "jsonrpc": "2.0", "result": {"nickname": "string"}}]`

Bu qadam depozit oldidan **majburiy**: akkaunt topilmasa xato qaytadi va pul
yuborilmaydi.

## 4. 3-metod: Depozit (deposit)

```
POST https://admin.mob-cash.com/api/v1/mobile/deposit
Authorization: Bearer <accessToken>
```

Body (JSON-RPC):

```json
{
  "id": 12,
  "jsonrpc": "2.0",
  "params": {
    "deposit": {
      "amount": "10",
      "payerID": "1000016167"
    },
    "sessionID": "2070115378001948672",
    "userID": "2029461258370469888"
  }
}
```

**Diqqat:** depositda `amount` — **satr** (`"10"`).

Javob: `[{"id": 12, "jsonrpc": "2.0", "result": {"success": true, "amount": "string"}}]`

## 5. 4-metod: Yechish summasi (getWithdrawalAmount)

```
POST https://admin.mob-cash.com/api/v1/mobile/getWithdrawalAmount
Authorization: Bearer <accessToken>
```

Body (JSON-RPC):

```json
{
  "id": 16,
  "jsonrpc": "2.0",
  "params": {
    "sessionID": "2070115378001948672",
    "userID": "2029461258370469888",
    "withdraw": {
      "payerID": "1000016167",
      "withdrawalCode": "Secret_tmpfjngkhj578ygmmfd"
    }
  }
}
```

Javob: `[{"id": 16, "jsonrpc": "2.0", "result": {"amount": "string"}}]`

`withdrawalCode` kassaga kelgan yechish so‘rovining kodi.

## 6. 5-metod: Yechishni bajarish (withdrawal)

```
POST https://admin.mob-cash.com/api/v1/mobile/withdrawal
Authorization: Bearer <accessToken>
```

Body (JSON-RPC):

```json
{
  "id": 17,
  "jsonrpc": "2.0",
  "params": {
    "sessionID": "2070115378001948672",
    "userID": "2029461258370469888",
    "withdraw": {
      "amount": 101,
      "payerID": "1000016167",
      "withdrawalCode": "Secret_tmpfjngkhj578ygmmfd"
    }
  }
}
```

**Diqqat:** withdrawalda `amount` — **JSON son** (`101`), satr emas.

Javob: `[{"id": 17, "jsonrpc": "2.0", "result": {"success": true, "amount": "string"}}]`

## 7. Tezkor ketma-ketlik

1. Login — `accessToken`, `sessionID`, `userID` olish.
2. `payerNickname` — akkauntni tekshirish (depozit oldidan majburiy).
3. Depozit bo‘lsa → `deposit`.
4. Aks holda yechish bo‘lsa → avval `getWithdrawalAmount`, keyin `withdrawal`.
5. `accessToken` muddati chiqsa → qayta login.

## 8. Kassani birinchi marta ulash — bir martalik kalit (HASH)

Kassaning login/paroli qo‘lda yozib olinmaydi: G&S qo‘llab-quvvatlash xizmati
(yoki Mob-Cash kabineti) **bir martalik kalit** yuboradi — 64 belgili hex satr.
Bu kalit orqali vaqtinchalik kredensiallar olinib, doimiy parol o‘rnatiladi.
Dasturchi dokumentatsiyasida bu oqim yozilmagan; quyidagi manzillar Mob-Cash’ning
o‘z kabinet (admin.mob-cash.com) va kassachi ilovasi (app.mob-cash.com) kodidan
olindi va real serverda tekshirildi.

1-qadam. Kalitni vaqtinchalik kredensiallarga almashtirish:

```
POST https://admin.mob-cash.com/api/v2/public/cashier/one-time-login
Content-Type: application/json

{"token": "<64 belgili kalit>"}
```

Javob:

```json
{"login": "...", "password": "...", "cashboxCode": 1234567}
```

Bu parol **vaqtinchalik**. Kalit **bir martalik**: bir marta ishlagandan keyin
yoki kassachi paroli o‘zgarganda bekor bo‘ladi. Muddati ham qisqa — olingan
kalitni darhol ishlatish kerak.

2-qadam. Vaqtinchalik kredensial bilan oddiy login (1-metod).

3-qadam. Doimiy parol o‘rnatish:

```
POST https://admin.mob-cash.com/api/v1/public/hydra/password
Authorization: Bearer <2-qadam accessToken>

{"newPassword": "<yangi doimiy parol>"}
```

Eslatma: parol o‘zgarishi shu kassachining boshqa barcha ulanishlarini uzadi
(masalan, zkassa botini).

4-qadam. Yangi parol bilan qayta login — oqim to‘g‘ri ishlaganini tasdiqlash.

Botda buni qo‘lda qilish shart emas: `.local/activate_hash.py <KALIT>` skripti
4 qadamni avtomatik bajaradi, kuchli parol generatsiya qiladi va uni bazaga
yozadi (`system_settings`: `mobcash_cashbox_code`, `mobcash_login`,
`mobcash_password`). Skript ishlagach botni qayta ishga tushirish kifoya.
Yoki admin panelda: `🏦 Mob-Cash → ⚙️ Kassa ulash` — bitta xabarda
`kassa_kodi | login | parol`.

Kalitni chatda uzoq saqlamang va hech kimga yubormang — u kassaga to‘liq kirish
imkonini beradi.

## 9. Xatolar lug‘ati (real serverda tekshirilgan)

| Javob | Ma’nosi | Nima qilish |
|---|---|---|
| HTTP 403 `{"tr":"unauthorized"}` | Kassa kodi xato yoki kassa o‘chirilgan | G&S orqali kassani tiklash, so‘ng yangi kredensial/kalit olish |
| HTTP 400 `{"tr":"tokenExpired"}` | Kalit eskirgan, ishlatilgan yoki bekor qilingan. Javob **generik**: noto‘g‘ri kalit ham shu javobni beradi | G&S’dan yangi kalit so‘rash; olish bilan darhol ishlatish |
| HTTP 400 `validationErr` … `token (field required)` | So‘rov body’sida `token` maydoni yo‘q | Body aynan `{"token": "..."}` bo‘lishini tekshirish |
| HTTP 400 `validationErr` (login’da) | `cashboxCode` satr yuborilgan | `cashboxCode` ni JSON son qilib yuborish |
| HTTP 401 (mobile metodlarda) | `accessToken` eskirgan | Qayta login, yangi token bilan davom etish |
| HTTP 5xx / 504 | Mob-Cash serverida muammo | Biroz kutib qayta urinish; pul so‘rovini ko‘r-ko‘rona takrorlamaslik |

Qo‘shimcha fakt: Mob-Cash kassachi ilovasining o‘z izohiga ko‘ra, bir martalik
link kalit **parol o‘zgartirilganda ham o‘chadi** — ya’ni kalit yaratilgandan
keyin kassachi paroli kimdir tomonidan o‘zgartirilgan bo‘lsa, yangi, ishlatilmagan
kalit ham `tokenExpired` beradi.

## 10. Tekshirilgan faktlar (2026-10-09)

- `one-time-login` endpoint faqat **v2**da bor: `POST /api/v1/public/cashier/one-time-login`
  → 404. Kassachi ilovasi kodi aynan shu manzil va `{"token": ...}` body’sini tasdiqlaydi.
- Kalitni bekor qilish uchun alohida metod bor:
  `DELETE /api/v2/public/cashier/one-time-login`.
- Kabinet tomonidan kalit yaratish metodi:
  `POST /api/v2/cashiers/{id}/one-time-login-token`.
- Hujjatdagi kredensiallar (1000042 / cashier_JuliaPavlova / SoftCorp_1234) va
  misollardagi `payerID`/`withdrawalCode` — namuna, real emas.
- Yaroqsiz kalitga qilingan urinish hech narsani buzmaydi: server faqat
  `tokenExpired` qaytaradi, kassaga ta’sir qilmaydi.
