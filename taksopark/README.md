# NAVO TAXI — Taksopark — Android APK, admin paneli va server

**Muallif va egasi:** Akobir Joyliyev · © 2026 · Barcha huquqlar himoyalangan. Foydalanish shartlari: [LICENSE](LICENSE).

**v0.1: ishlaydigan boshlang‘ich versiya. Ishlab chiqarish darajasidagi yakuniy taksi tizimi emas.**

Park nomi admin panelidagi **Sozlamalar → Taksopark nomi** orqali o‘zgartiriladi. Nom yo‘lovchi, haydovchi va admin ekranlarida yangilanadi. Android bosh ekranidagi ilova nomini almashtirish uchun APKni qayta yig‘ish kerak.

## Serverga tez joylashtirish — Linux VPS + domen

Talab: Docker Engine + Compose o‘rnatilgan Linux VPS, o‘zingizga tegishli domen. Oddiy PHP/static hosting bu Node.js serverini ishlatmaydi.

1. ZIPni serverga yuklang, oching va `taksopark` papkasiga kiring.
2. Domenning DNS A yozuvini VPS IPv4 manziliga yo‘naltiring. AAAA yozuvi bo‘lsa u ham to‘g‘ri serverga borishi kerak.
3. VPS xavfsizlik devorida 80 va 443 portlarni oching. Bu portlarda boshqa xizmat bo‘lsa avval o‘z reverse proxy sozlamangizga moslang.
4. Terminalda:

```sh
cp .env.example .env
nano .env
```

`DOMAIN` qiymatiga o‘z domeningizni yozing — `https://` qo‘shmang. `ADMIN_PHONE`ni o‘zingizning +998 telefoningizga almashtiring.

```sh
docker compose up -d --build
docker compose logs --tail=50 app caddy
docker compose exec app cat /app/data/first-login.txt
```

Oxirgi buyruq admin login va tasodifiy yaratilgan parolni ko‘rsatadi. Ularni shaxsiy saqlang. Brauzerda `https://SIZNING_DOMENINGIZ`ni ochib shu telefon/parol bilan kiring. Admin panelidan parolni yangilang va serverdagi `first-login.txt` boshlang‘ich parol faylini olib tashlang.

Caddy uchun domen DNSi va 80/443 portlar to‘g‘ri ishlasa HTTPS sertifikati olinadi. Ushbu paket masofaviy VPSda hali sinovdan o‘tkazilmagan; serverdagi loglarni tekshiring.

### Telefonni ulash

APKni o‘rnating → **Server manzilini sozlash** → `https://SIZNING_DOMENINGIZ` → tekshirish va saqlash. Oxiriga `/api` qo‘shmang. Namunadagi domenni aynan ko‘chirmang: o‘zingizning haqiqiy domeningiz kerak.

Yo‘lovchi telefon va parol bilan ro‘yxatdan o‘tadi. Haydovchini admin **Haydovchilar → Haydovchi qo‘shish** orqali yaratadi va boshlang‘ich parol beradi. Haydovchi shu telefon/parol bilan kiradi. Bir serverga ulangan qurilmalar buyurtmalarni almashadi; yangilanish har 5 soniyada.

### Ma’lumotlar va zaxira

SQLite ma’lumotlari `park_data` Docker volume ichida saqlanadi. `docker compose down -v` volume va ma’lumotlarni o‘chiradi — ishlatmang. Zaxiralashning oddiy usuli: `docker compose stop app`, so‘ng `/app/data` papkasini `docker compose cp app:/app/data ./backup-data` bilan nusxalang va `docker compose start app` bilan qayta yoqing. Zaxira papkasida shaxsiy ma’lumotlar bor; ommaga bermang.

## Kompyuterda ishlatish

Node.js 24 yoki yangi versiya kerak. `START.cmd`ni oching yoki:

```sh
node server.mjs
```

Brauzer: http://localhost:4317 . Login/parol birinchi ishga tushishda `data/first-login.txt`da yaratiladi. npm kutubxonalarini o‘rnatish shart emas. Ushbu lokal manzil telefon uchun internet serveri emas.

## Serversiz sinash

APKning kirish ekranida **Yo‘lovchi**, **Haydovchi**, **Admin paneli** tugmalari bor. Parol va server manzili kiritish shart emas. Demo ma’lumotlar har bir qurilmada alohida saqlanadi; boshqa telefonlarga yuborilmaydi.

Sinov: Yo‘lovchi → yo‘nalish va tarif → Taksi chaqirish → Haydovchi roliga o‘tish → Qabul qilish → Yetib keldim → Safarni boshlash → Safarni yakunlash → Yo‘lovchi safarlar tarixi. Admin sozlamalaridan nomni o‘zgartirib barcha rollarda natijani ko‘rish mumkin.

## Tayyor funksiyalar

- Yo‘lovchi: kirish, ro‘yxatdan o‘tish, yo‘nalish/tarif tanlash, taxminiy narx, buyurtma, holat, ruxsat etilgan bosqichda bekor qilish, safarlar tarixi.
- Haydovchi: kirish, onlayn/oflayn, yangi buyurtma qabul qilish, kelish/boshlash/yakunlash, safar va daromad tarixi.
- Admin: umumiy ko‘rsatkichlar, buyurtma yaratish/qidirish/filtrlash/biriktirish, safar holati, haydovchi yaratish/tahrirlash/bloklash, tarif, komissiya, park nomi, hisobot, CSV eksport, faollik jurnali.
- Server: SQLite, parol xeshi, 12 soatlik sessiya, rollar bo‘yicha ruxsat, server hisoblaydigan narx, parallel buyurtma qabulini tekshirish.
- Android: internet bo‘lmaganda demo rejim, HTTPS API ulanishi, ilova ichiga joylangan interfeys. Android 8+ va yangilangan Android System WebView kerak.

## Hali ulanmagan qismlar

Haqiqiy GPS kuzatuv, manzil qidiruvi/geokoding va yo‘l marshruti, haydovchini avtomatik yaqinlik bo‘yicha topish, SMS/OTP, push va fondagi bildirishnomalar, Click/Payme/karta to‘lovlari, hujjat tekshiruvi, telefon/parolni tiklash va katta yuklama uchun arxitektura hali yo‘q. Login telefon + parol orqali; telefon egasi SMS bilan tasdiqlanmaydi. Naqd pul hisobotlari bank/inkassatsiya bilan solishtirilmaydi.

Xarita **sxematik demo**. 8 ta Toshkent manzili mavjud. Masofa koordinatalardan 1.35 koeffitsiyent bilan taxminan hisoblanadi; aniq yo‘l va tirbandlik hisoblanmaydi. Serverga qo‘yilgandan keyin ham GPS avtomatik ishga tushmaydi. Haqiqiy yo‘lovchilar bilan ish boshlashdan oldin bu integratsiyalar, monitoring, zaxiralash va yuklama sinovlari yakunlanishi kerak.

## Tekshiruv

```sh
npm test
```

16 ta test o‘tdi: ruxsatlar, buyurtma bosqichlari, narxni soxtalashtirishdan himoya, parallel qabul, ma’lumot maxfiyligi, sozlamalar, API kirish va server qayta ishga tushganda saqlanish. Brauzerda nomni o‘zgartirish va yo‘lovchi → haydovchi → yakunlangan safar jarayoni sinovdan o‘tkazildi. Android APK yig‘ildi, v2/v3 imzolari tekshirildi. Haqiqiy Android qurilmada o‘rnatish va uzoq muddatli ish sinovi bajarilmagan.

## APKni qayta yig‘ish

JDK 17 va Android SDK platform/build-tools 34 kerak. Windows PowerShell:

```powershell
./android/build.ps1 -SdkRoot 'D:\Android\sdk' -JdkRoot 'D:\dev\jdk-17.0.20.1+1'
```

Berilgan APK test imzosi bilan yig‘ilgan. Do‘kon yoki ommaviy tarqatish uchun o‘zingizga tegishli release signing kaliti, yangi SDK talablari va alohida qurilma sinovlari zarur. APK ichida server paroli yoki admin kirish kaliti yo‘q.

Texnik ma’lumot: [Node.js SQLite](https://nodejs.org/download/release/latest-v24.x/docs/api/sqlite.html), [Android WebView local content](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content).
