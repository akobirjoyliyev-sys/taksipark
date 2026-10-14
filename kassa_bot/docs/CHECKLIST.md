# Qo‘lda tekshirish ro‘yxati (sandbox)

Oldindan: `docker compose up -d`, `.env`da `ADMIN_IDS` sizning ID, ikkinchi Telegram akkaunt
(oddiy foydalanuvchi), `python -m app.seed` bajarilgan.

## Onboarding
- [ ] `/start` → (majburiy kanallar bo‘lsa) kanal ro‘yxati + `✅ Obunani tekshirish`
- [ ] Obunasiz «Tekshirish» → «Hali barcha kanallarga obuna bo‘lmagansiz»
- [ ] Kontakt so‘rovi: `📱 Kontaktni ulashish` → «Raqamingiz tasdiqlandi»; `⏭ O‘tkazib yuborish` ishlaydi
- [ ] Boshqa odamning kontaktini yuborish → rad etiladi
- [ ] `CONTACT_REQUIRED=true` (⚙️) bo‘lsa o‘tkazib yuborish tugmasi yo‘q, menyu bloklangan
- [ ] Asosiy menyu tartibi: ➕ Hisob to‘ldirish | ➖ Pul chiqarish / 💠 Hamyon | 👨‍💻 Aloqa / 🎁 Bonus | 🌐 Kassa manzili
- [ ] `/start ref_<ID>` (yangi akkaunt) → taklif qiluvchiga «yangi do‘stingiz qo‘shildi»; o‘z ID si bilan — e’tiborsiz

## 💠 Hamyon
- [ ] Balanslar, VIP daraja, test rejimi belgisi
- [ ] `📥 Hisob to‘ldirish` → summa so‘raladi; `➕ Hamyonni to‘ldirish` → tezkor summalar
- [ ] `📤 Kartaga yechish` → yechish oqimi; `💳 Kartalarim` → o‘chirish
- [ ] `📜 Tranzaksiyalar`: To‘ldirish/Yechish/Hammasi + ⏳/✅/❌ filterlari, sahifalash
- [ ] `🔙 Orqaga` → asosiy menyu

## ➕ Hisob to‘ldirish
- [ ] Limitdan past/yuqori summa, harf, manfiy → aniq xato
- [ ] To‘g‘ri summa → to‘lov kartochkasi (summa, komissiya, muddat, `💳 To‘lash`)
- [ ] Sandbox sahifasida `✅ To‘lash` → botda «To‘lov qabul qilindi», balans oshdi
- [ ] Sahifani qayta yuborish / webhookni takrorlash → balans ikkinchi marta oshmaydi
- [ ] `❌ Rad etish` → «amalga oshmadi»; `❌ Bekor qilish` → «bekor qilindi»
- [ ] `PAYMENT_EXPIRY_MINUTES` o‘tgach worker «muddati tugadi» xabarini yuboradi
- [ ] 3 ta pending to‘lovdan keyin yangisi rad etiladi

## ➖ Pul chiqarish
- [ ] Karta yo‘q → `➕ Karta ulash` → sandbox sahifasi → «Karta ulandi: 8600 **** 0001»
- [ ] Karta tanlash → summa → tasdiq oynasi (komissiya, kartaga tushadi)
- [ ] Balansdan katta summa → xato; `💯 Barchasini yechish` ishlaydi
- [ ] Tasdiq → «Ariza qabul qilindi», hamyonda summa «Bloklangan»ga o‘tdi
- [ ] `📋 Arizalarim` → ariza → status tarixi

## 🎁 Bonus
- [ ] `🎟 Promokod`: `WELCOME` → darhol +5 000; qayta — «allaqachon foydalangansiz»
- [ ] `BONUS10` → «keyingi kamida 50 000 lik depozitga»; depozitdan so‘ng bonus qatori
- [ ] `🏆 VIP hisob`: joriy daraja, progress bar, darajalar ro‘yxati
- [ ] `🤝 Referal`: havola, soni, jami/yechilgan/joriy bonus, `📨 Ulashish`
- [ ] Do‘st depozit qilgach referal bonus (faqat tasdiqlangan to‘lovdan keyin)
- [ ] `🏆 TOP10`, `📅 So‘nggi 10 kun TOP10` (ismlar maskalangan), `👥 Mening do‘stlarim` sahifalash
- [ ] `💸 Bonusni yechib olish`: minimumdan kam → xato; yetarli → asosiy balansga o‘tadi

## 👨‍💻 Aloqa / 🌐 Kassa manzili
- [ ] Sozlangan havola tugmasi; sozlanmagan bo‘lsa «hali sozlanmagan»
- [ ] ⚙️ dan o‘zgartirilgach yangi havola darhol ishlaydi

## /admin
- [ ] Oddiy foydalanuvchi `/admin` → «Buyruq tushunilmadi» (panel oshkor qilinmaydi)
- [ ] Dashboard: tizim holati, rejim, foydalanuvchilar, kontakt tasdiqlaganlar, faol kassalar,
      kartalar, operatorlar, pending to‘lov/yechishlar, limitlar; `🔄 Yangilash`

### 📊 Statistika & Hisobot
- [ ] Bugun / 7 kun / 30 kun; `🔎 Sana oralig‘i` (`2026-10-01 2026-10-06`); noto‘g‘ri format xatosi
- [ ] `📥 CSV eksport` → fayl (deposit + withdrawal qatorlari)
- [ ] `📜 Audit log` (superadmin/admin/auditor), sahifalash

### 👥 Foydalanuvchilar & Boshqaruv
- [ ] ID / @username / telefon bo‘yicha qidiruv; telefon maskalangan
- [ ] `📞 To‘liq raqam` (superadmin/admin) → audit yozuvi
- [ ] Ban (sabab majburiy → tasdiq) → foydalanuvchi botga yozganda «bloklangan» xabarini oladi; Unban
- [ ] Kredit/Debet: summa → sabab → tasdiq → ledger + audit; balansdan katta debet rad etiladi
- [ ] Xabar: matn → preview → tasdiq → yuborildi
- [ ] `🛡 Adminlar`: `ID rol` qo‘shish, o‘chirish/yoqish; ENV adminlar o‘zgartirilmaydi

### ⚙️ Tizim Sozlamalari
- [ ] Guruhlar: Tizim / Payout / Bonus / Obuna
- [ ] Har o‘zgarish: qiymat → 1️⃣ preview → 2️⃣ yakuniy tasdiq → audit
- [ ] min > max, foiz > 100, noto‘g‘ri timezone → xato
- [ ] `payment_mode=production` sandbox faol bo‘lsa yoki real yo‘l (Mob-Cash) o‘chiq bo‘lsa → rad etiladi
- [ ] Texnik ishlar rejimi: oddiy foydalanuvchi «texnik ishlar» xabarini oladi, admin ishlaydi
- [ ] Admin roli «To‘lov rejimi» / «Faol provayderlar»ni ko‘rmaydi (faqat superadmin)

### 📦 Ommaviy to‘lov
- [ ] Format yordami; `.csv` dan boshqa fayl rad etiladi
- [ ] Preview: to‘g‘ri / xato / dublikat qatorlar, jami summa — hech narsa yuborilmagan
- [ ] Yuklagan admin tasdiqlay olmaydi; operator/superadmin tasdiqlaydi (ikki bosqich)
- [ ] Progress (`🔄 Yangilash`), yakunda «Yakunlangan», `📄 To‘liq hisobot (CSV)`
- [ ] Shu faylni 24 soat ichida qayta yuklash → dublikat

### 🤖 Avto to‘lov markazi (ID lar ro‘yxatiga ommaviy depozit)
- [ ] Markaz: 24 soatlik statistika, faol partiyalar progressi; worker o‘chiq bo‘lsa ogohlantirish
- [ ] `🚀 Yangi avto to‘lov` → kassa tanlash (bitta bo‘lsa avtomatik) → balans ko‘rinadi
- [ ] 300 ta ID ikki xabarda + .txt/.csv fayl → jami, takroriylar, tanilmaganlar ko‘rinadi
- [ ] `123456789 - 15000` qatorlari o‘z summasi bilan; summasizlar uchun «qanchadan?» so‘raladi
- [ ] Tezkor summa tugmalari va `20k`, `15 000` kiritish; `deposit_max` dan katta summa rad etiladi
- [ ] Preview: jami, kassa balansi (yetadi/yetmaydi), 24 soatda pul olganlar soni; pul ketmaydi
- [ ] `🚀 Boshlash` → tasdiq → worker o‘zi o‘tkazadi, progress xabari jonli yangilanadi
- [ ] `⏸ Pauza` / `▶️ Davom ettirish` / `⛔ To‘xtatish` (navbatdagilar ⏭)
- [ ] Topilmagan ID → ❌ (pul ketmaydi); timeout → 🕵️ tekshiruv (qayta yuborilmaydi)
- [ ] Kassada mablag‘ yetmasa → avtomatik pauza + xabar; to‘ldirib davom ettirish
- [ ] Yakunda CSV hisobot keladi; `🔁 Xatolarni qayta yuborish`, `🕵️ Tekshiruv` (✅/❌ belgilash)

### 💳 Karta payout (Avto to‘lov markazi → «💳 Karta payout»)
- [ ] Holat, limit, urinishlar, navbat statistikasi, provayder holati
- [ ] Yoqish/o‘chirish va limit ⚙️ ning ikki bosqichli oqimi orqali
- [ ] Avto yoqilgan + limit ichidagi ariza → avtomatik to‘lanadi
- [ ] `SANDBOX_PAYOUT_FAILURE_RATE=1` → retry/backoff → manual navbat + adminlarga xabar
- [ ] `🩺 Provayderni tekshirish`, `🔄 Reconciliation`, `♻️ Manual → avto navbat`

### 💸 Ruchnoy yechish
- [ ] Holat filterlari (pending/tasdiqlangan/jarayonda/xato), sahifalash
- [ ] Ariza kartochkasi: summa, komissiya, maskalangan karta, urinishlar, tarix
- [ ] Tasdiqlash / To‘landi deb belgilash / Rad etish — izoh majburiy, foydalanuvchiga xabar
- [ ] Rad etishda summa foydalanuvchi balansiga qaytadi

### 📋 Join Requestlar
- [ ] Kanalda «join request» yoqilgan, bot admin → so‘rov ro‘yxatda paydo bo‘ladi
- [ ] Holat va kanal filterlari; Qabul / Rad → Telegramda ham bajariladi, audit
- [ ] `✅ Barchasini qabul qilish`

### 🎁 Bonus tizimi
- [ ] Promokod qo‘shish (format), preview, saqlash; tahrirlash; deaktivatsiya; o‘chirish
- [ ] VIP daraja qo‘shish/tahrirlash/yoqish-o‘chirish/o‘chirish
- [ ] Referal foizi va bonus qoidalari (⚙️ oqimi)

### 📢 Majburiy Obuna Kanallari
- [ ] `@username | Kanal nomi` bilan qo‘shish; noto‘g‘ri format xatosi
- [ ] Bot admin emas → ogohlantirish; `🔍 Adminlikni tekshirish`
- [ ] Aktiv/deaktiv, ⬆️⬇️ tartib, o‘chirish, majburiy obunani yoqish/o‘chirish

## Xavfsizlik
- [ ] Juda tez xabar yuborish → «Juda tez yuboryapsiz»
- [ ] Noto‘g‘ri imzoli webhook → `401`; eski timestamp → `401`
- [ ] Loglarda token / karta raqami ko‘rinmaydi
- [ ] `ledger_entries`da `UPDATE` → DB xatosi (append-only)
