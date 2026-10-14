"""Barcha UI matnlari (o‘zbek, lotin). Boshqa botlardan nusxa emas — original matnlar."""

from __future__ import annotations

from app.core.enums import (
    LedgerReason,
    MassBatchStatus,
    MassItemStatus,
    MobcashWithdrawalStatus,
    P2PDepositStatus,
    P2PDepositTarget,
    PaymentStatus,
    WithdrawalStatus,
)

# --------------------------------------------------------------------------- tugmalar
BTN_DEPOSIT = "➕ Hisob to‘ldirish"
BTN_WITHDRAW = "➖ Pul chiqarish"
BTN_WALLET = "💠 Hamyon"
BTN_SUPPORT = "👨‍💻 Aloqa"
BTN_BONUS = "🎁 Bonus"
BTN_CASHBOX = "🌐 Kassa manzili"

BTN_SHARE_CONTACT = "📱 Kontaktni ulashish"
BTN_SKIP_CONTACT = "⏭ O‘tkazib yuborish"

BTN_W_WGAME = "🎮 Hisobga o‘tkazish"
BTN_W_TOPUP = "➕ Hamyonni to‘ldirish"
BTN_W_WITHDRAW = "📤 Kartaga yechish"
BTN_W_HISTORY = "📜 Tranzaksiyalar"
BTN_W_CARDS = "💳 Kartalarim"
BTN_BACK = "🔙 Orqaga"
BTN_CANCEL = "❌ Bekor qilish"
BTN_CONFIRM = "✅ Tasdiqlash"
BTN_PAY = "💳 To‘lash"
BTN_CHECK_STATUS = "🔄 Holatni tekshirish"
BTN_BIND_CARD = "➕ Karta ulash"
BTN_MY_REQUESTS = "📋 Arizalarim"
BTN_WITHDRAW_ALL = "💯 Barchasini yechish"
BTN_CHECK_SUB = "✅ Obunani tekshirish"
BTN_CUSTOM_AMOUNT = "✍️ Boshqa summa"
BTN_OPEN_SUPPORT = "✉️ Yozish"
BTN_OPEN_CASHBOX = "🌐 Ochish"

BTN_PROMO = "🎟 Promokod"
BTN_VIP = "🏆 VIP hisob"
VIP_DISABLED = "🏆 VIP bo‘limi vaqtincha o‘chirilgan."
BTN_REFERRAL = "🤝 Referal"
BTN_REF_SHARE = "📨 Do‘stlarga ulashish"
BTN_REF_TOP = "🏆 TOP10"
BTN_REF_TOP_10D = "📅 So‘nggi 10 kun TOP10"
BTN_REF_FRIENDS = "👥 Mening do‘stlarim"
BTN_REF_WITHDRAW = "💸 Bonusni yechib olish"

MAIN_MENU_ROWS = (
    (BTN_DEPOSIT, BTN_WITHDRAW),
    (BTN_WALLET, BTN_SUPPORT),
    (BTN_BONUS, BTN_CASHBOX),
)
MAIN_MENU_TEXTS = frozenset(t for row in MAIN_MENU_ROWS for t in row)

# --------------------------------------------------------------------------- umumiy
WELCOME = (
    "👋 <b>Assalomu alaykum! Kassa’ga xush kelibsiz</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "⚡️ Tez  •  🔒 Xavfsiz  •  🕐 24/7\n\n"
    "➕ <b>Hisob to‘ldirish</b> — o‘yin hisobingizga\n"
    "➖ <b>Pul chiqarish</b> — kartangizga\n"
    "💠 <b>Hamyon</b> va 🎁 <b>bonuslar</b>\n\n"
    "Kerakli bo‘limni menyudan tanlang 👇"
)
MAIN_MENU = "🏠 Asosiy menyu"
CONTACT_PROMPT_OPTIONAL = (
    "📱 Xavfsizlik va tezkor yordam uchun telefon raqamingizni ulashishingiz mumkin.\n"
    "Bu ixtiyoriy — o‘tkazib yuborsangiz ham bo‘ladi."
)
CONTACT_PROMPT_REQUIRED = (
    "📱 Davom etish uchun telefon raqamingizni tasdiqlang.\n"
    "Pastdagi «📱 Kontaktni ulashish» tugmasini bosing."
)
CONTACT_SAVED = "✅ Raqamingiz tasdiqlandi. Rahmat!"
CONTACT_FOREIGN = "⚠️ Iltimos, faqat o‘zingizning kontaktingizni yuboring."
BANNED = "⛔ Hisobingiz bloklangan. Savollar bo‘lsa, qo‘llab-quvvatlash xizmatiga murojaat qiling."
MAINTENANCE = "🔧 Hozir texnik ishlar olib borilmoqda. Birozdan so‘ng qayta urinib ko‘ring."
FLOOD = "⏳ Juda tez yuboryapsiz. Bir necha soniya kuting."
UNKNOWN = "🤔 Buyruq tushunilmadi. Iltimos, menyudan foydalaning."
CANCELLED = "❌ Amal bekor qilindi."
ERROR_GENERIC = "⚠️ Kutilmagan xatolik yuz berdi. Birozdan so‘ng qayta urinib ko‘ring."
EXPIRED_ACTION = "⌛ Bu amal eskirgan. Iltimos, qaytadan boshlang."
NOT_CONFIGURED = "ℹ️ Bu bo‘lim hali sozlanmagan. Keyinroq urinib ko‘ring."
REFERRAL_JOINED = "🤝 Havolangiz orqali yangi do‘stingiz qo‘shildi: <b>{name}</b>"

SUB_REQUIRED = (
    "📢 Botdan foydalanish uchun quyidagi kanallarga obuna bo‘ling, so‘ng "
    "«✅ Obunani tekshirish» tugmasini bosing."
)
SUB_STILL_MISSING = "⚠️ Hali barcha kanallarga obuna bo‘lmagansiz."
SUB_OK = "✅ Obuna tasdiqlandi!"

SUPPORT_TEXT = (
    "👨‍💻 <b>Aloqa</b>\n\nSavol yoki muammo bo‘lsa, qo‘llab-quvvatlash xizmatiga yozing:"
)
CASHBOX_TEXT = "🌐 <b>Kassa manzili</b>\n\nRasmiy manzilimiz:"
LINK_FALLBACK = "\n\n🔗 {url}"

# --------------------------------------------------------------------------- hamyon
WALLET = (
    "💠 <b>Hamyon</b>\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "💰 Mavjud balans: <b>{available}</b>\n"
    "🔒 Bloklangan: {blocked}\n"
    "🎁 Bonus balansi: {bonus}\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "📥 Jami to‘ldirilgan: {total_deposit}\n"
    "📤 Jami yechilgan: {total_withdraw}\n"
    "🏆 VIP daraja: <b>{vip}</b>\n"
    "{vip_progress}"
    "━━━━━━━━━━━━━━━━━━\n"
    "👇 Kerakli amalni tanlang:"
)
TEST_MODE_NOTE = "\n\n🧪 <i>Test rejimi: real pul harakatlanmaydi.</i>"

# --------------------------------------------------------------------------- depozit
DEPOSIT_ASK_AMOUNT = (
    "➕ <b>Hisob to‘ldirish</b>\n\n"
    "Summani so‘mda kiriting.\n"
    "Minimal: <b>{min}</b>\nMaksimal: <b>{max}</b>"
)
TOPUP_CHOOSE = "➕ <b>Hamyonni to‘ldirish</b>\n\nTezkor summani tanlang yoki o‘zingiz kiriting:"
AMOUNT_INVALID = "⚠️ Summa noto‘g‘ri. Faqat raqam kiriting, masalan: <code>50000</code>"
AMOUNT_OUT_OF_RANGE = "⚠️ Summa {min} dan {max} gacha bo‘lishi kerak."
DEPOSIT_TOO_MANY_PENDING = (
    "⚠️ Sizda yakunlanmagan to‘lovlar bor. Avval ularni yakunlang yoki bekor qiling."
)
DEPOSIT_PROVIDER_DOWN = "⚠️ To‘lov tizimi vaqtincha ishlamayapti. Birozdan so‘ng urinib ko‘ring."
DEPOSIT_CREATED = (
    "🧾 <b>To‘lov #{id}</b>\n\n"
    "💵 Summa: <b>{amount}</b>\n"
    "💸 Komissiya: {fee}\n"
    "💰 Hamyonga tushadi: <b>{net}</b>\n"
    "⏳ Amal qilish muddati: <b>{expires}</b> gacha\n\n"
    "«💳 To‘lash» tugmasi orqali to‘lovni rasmiy to‘lov sahifasida yakunlang. "
    "To‘lov tasdiqlangach, balans avtomatik to‘ldiriladi."
)
DEPOSIT_STATUS = "🧾 To‘lov #{id}: {status}"
DEPOSIT_PAID = "✅ <b>To‘lov #{id} qabul qilindi!</b>\n\n💰 Hamyonga qo‘shildi: <b>{net}</b>{bonus}"
DEPOSIT_BONUS_LINE = "\n🎁 Bonus: +{amount} ({kind})"
DEPOSIT_FAILED = "❌ To‘lov #{id} amalga oshmadi. Qayta urinib ko‘rishingiz mumkin."
DEPOSIT_EXPIRED = "⌛ To‘lov #{id} muddati tugadi. Kerak bo‘lsa, yangi to‘lov yarating."
DEPOSIT_CANCELLED = "🚫 To‘lov #{id} bekor qilindi."
DEPOSIT_CANNOT_CANCEL = "ℹ️ Bu to‘lovni bekor qilib bo‘lmaydi — holati: {status}"

# --------------------------------------------------------------------------- yechish
WITHDRAW_CHOOSE_CARD = (
    "➖ <b>Pul chiqarish</b>\n\n"
    "💰 Mavjud: <b>{available}</b>\n"
    "Limit: {min} — {max}\nKomissiya: {fee}%\n\n"
    "Pul tushadigan kartani tanlang:"
)
WITHDRAW_NO_CARDS = (
    "➖ <b>Pul chiqarish</b>\n\n"
    "Sizda ulangan karta yo‘q. «➕ Karta ulash» tugmasini bosing va karta raqamini kiriting."
)
WITHDRAW_LOW_BALANCE = "⚠️ Pul chiqarish uchun minimal summa {min}. Mavjud balans: {available}"
WITHDRAW_ASK_CARD = "💳 Pul o‘tkaziladigan karta raqamini yuboring (16 ta raqam):"
WITHDRAW_CARD_INVALID = "⚠️ Karta raqami noto‘g‘ri — 16 ta raqamdan iborat bo‘lishi kerak."
WITHDRAW_ASK_AMOUNT = (
    "💳 Karta: <b>{card}</b>\n💰 Mavjud: <b>{available}</b>\n\n"
    "Yechiladigan summani kiriting ({min} — {max}):"
)
WITHDRAW_CONFIRM = (
    "📤 <b>Pul chiqarishni tasdiqlang</b>\n\n"
    "💳 Karta: {card}\n"
    "💵 Summa: <b>{amount}</b>\n"
    "💸 Komissiya: {fee}\n"
    "✅ Kartaga tushadi: <b>{net}</b>"
)
WITHDRAW_CREATED = (
    "📨 Ariza #{id} qabul qilindi.\nHolati: {status}\n\n" "Holat o‘zgarganda sizga xabar beramiz."
)
WITHDRAW_CREATED_MANUAL = (
    "📨 Ariza #{id} qabul qilindi.\n"
    "💳 {net} kartangizga o‘tkaziladi — operator bajarishi bilan xabar beramiz."
)
WD_ADMIN_NEW = (
    "🆕 <b>Yangi yechish arizasi #{id}</b> — kartaga o‘tkazing\n\n"
    "👤 Foydalanuvchi: <code>{user}</code>\n"
    "💵 Summa: {amount}\n"
    "✅ Kartaga tushadi: <b>{net}</b>\n"
    "💳 Karta: <code>{card}</code>\n\n"
    "«💸 Ruchnoy yechish» bo‘limidan to‘lab, «💵 To‘landi deb belgilash»ni bosing."
)
WITHDRAW_INSUFFICIENT = "⚠️ Balans yetarli emas. Mavjud: {available}"
WITHDRAW_TOO_MANY = "⚠️ Sizda ko‘rib chiqilayotgan arizalar ko‘p. Ularning yakunlanishini kuting."
WITHDRAW_STATUS_CHANGED = "📤 Ariza #{id}: {status}\n💵 {amount}{comment}"
WITHDRAW_DETAILS = (
    "📤 <b>Ariza #{id}</b>\n\n"
    "💵 Summa: {amount}\n💸 Komissiya: {fee}\n✅ Kartaga: {net}\n"
    "💳 Karta: {card}\nHolati: {status}\n🕒 Yaratilgan: {created}\n\n"
    "<b>Status tarixi:</b>\n{history}"
)
NO_WITHDRAWALS = "📋 Sizda hali pul chiqarish arizalari yo‘q."
MY_REQUESTS_TITLE = "📋 <b>So‘nggi arizalaringiz</b>"
CARD_BIND_TEXT = (
    "💳 <b>Karta ulash</b>\n\n"
    "Kartani to‘lov provayderining xavfsiz sahifasida ulang. Bot karta raqami, CVV yoki "
    "PIN-kodni hech qachon so‘ramaydi va saqlamaydi.\n\nHavola 15 daqiqa amal qiladi."
)
CARD_BOUND = "✅ Karta ulandi: <b>{mask}</b>"
CARD_LIMIT = "⚠️ Ko‘pi bilan {limit} ta karta ulash mumkin."
CARDS_TITLE = "💳 <b>Ulangan kartalar</b>\n\nO‘chirish uchun kartani tanlang."
CARD_REMOVED = "🗑 Karta o‘chirildi."
NO_PAYOUT_PROVIDER = "⚠️ Hozircha kartaga yechish imkoniyati mavjud emas."

# --------------------------------------------------------------------------- tarix
HISTORY_TITLE = "📜 <b>Tranzaksiyalar</b> — {kind}, {status}"
HISTORY_EMPTY = "Hozircha yozuvlar yo‘q."
HISTORY_KIND = {"dep": "to‘ldirishlar", "wd": "yechishlar", "led": "hamyon harakatlari"}
HISTORY_STATUS = {
    "all": "barchasi",
    "pending": "kutilmoqda",
    "ok": "muvaffaqiyatli",
    "fail": "xato",
}

# --------------------------------------------------------------------------- bonus
BONUS_MENU = "🎁 <b>Bonus</b>\n\nBonus imkoniyatlaridan birini tanlang:"
PROMO_ASK = "🎟 Promokodni kiriting:"
PROMO_INVALID = "⚠️ Promokod topilmadi yoki faol emas."
PROMO_EXPIRED = "⌛ Promokod muddati tugagan."
PROMO_NOT_STARTED = "⏳ Promokod hali kuchga kirmagan."
PROMO_LIMIT = "⚠️ Promokoddan foydalanish limiti tugagan."
PROMO_USER_LIMIT = "⚠️ Siz bu promokoddan allaqachon foydalangansiz."
PROMO_HAS_PENDING = "ℹ️ Sizda hali qo‘llanmagan promokod bor. Avval depozit qiling."
PROMO_APPLIED_NOW = "✅ Promokod faollashtirildi! Hamyoningizga +{amount} qo‘shildi."
PROMO_RESERVED = (
    "✅ Promokod qabul qilindi!\n"
    "Bonus keyingi kamida {min} lik tasdiqlangan depozitingizga qo‘shiladi ({value})."
)
VIP_TEXT = (
    "🏆 <b>VIP hisob</b>\n\n"
    "Joriy daraja: <b>{level}</b>\n"
    "Depozit bonusi: {percent}%\n"
    "Jami depozit: {total}\n\n"
    "{progress}\n\n<b>Darajalar:</b>\n{levels}"
)
VIP_NEXT = "Keyingi daraja: <b>{name}</b> — yana {left} kerak\n{bar} {pct}%"
VIP_MAX = "🎉 Siz eng yuqori darajadasiz!"
VIP_NONE = "—"
REFERRAL_TEXT = (
    "🤝 <b>Referal dasturi</b>\n\n"
    "Do‘stlaringizni taklif qiling va ularning har bir tasdiqlangan depozitidan "
    "<b>{percent}%</b> bonus oling.\n\n"
    "🔗 Shaxsiy havolangiz:\n<code>{link}</code>\n\n"
    "👥 Taklif qilinganlar: <b>{count}</b>\n"
    "💰 Jami referal bonus: {earned}\n"
    "📤 Yechib olingan: {withdrawn}\n"
    "💎 Joriy bonus balans: <b>{balance}</b>"
)
REFERRAL_DISABLED = "ℹ️ Referal dasturi hozircha to‘xtatilgan."
REFERRAL_SHARE_TEXT = "Kassa — qulay hamyon va tezkor to‘lovlar. Havola orqali qo‘shiling:"
REF_TOP_TITLE = "🏆 <b>TOP10 — eng faol taklif qiluvchilar</b>"
REF_TOP_10D_TITLE = "📅 <b>So‘nggi 10 kun TOP10</b>"
REF_TOP_ROW = "{pos}. {name} — {count} ta do‘st, {amount}"
REF_TOP_EMPTY = "Hali reyting shakllanmagan."
REF_FRIENDS_TITLE = "👥 <b>Mening do‘stlarim</b> ({total} ta)"
REF_FRIENDS_ROW = "• {name} — {date} — depozit: {deposit}"
REF_FRIENDS_EMPTY = "Siz hali hech kimni taklif qilmagansiz."
REF_WITHDRAW_LOW = "⚠️ Yechib olish uchun minimal bonus: {min}. Joriy: {balance}"
REF_WITHDRAW_OK = "✅ {amount} bonus asosiy balansga o‘tkazildi."
REFERRAL_REWARD = "🎉 Do‘stingiz depoziti uchun +{amount} referal bonus oldingiz!"

# --------------------------------------------------------------------------- status nomlari
PAYMENT_STATUS = {
    PaymentStatus.PENDING: "⏳ Kutilmoqda",
    PaymentStatus.PAID: "✅ To‘langan",
    PaymentStatus.FAILED: "❌ Muvaffaqiyatsiz",
    PaymentStatus.EXPIRED: "⌛ Muddati tugagan",
    PaymentStatus.CANCELLED: "🚫 Bekor qilingan",
}
WITHDRAW_STATUS = {
    WithdrawalStatus.PENDING: "⏳ Ko‘rib chiqilmoqda",
    WithdrawalStatus.APPROVED: "🟢 Tasdiqlangan",
    WithdrawalStatus.PROCESSING: "🔄 To‘lanmoqda",
    WithdrawalStatus.PAID: "✅ To‘langan",
    WithdrawalStatus.REJECTED: "❌ Rad etilgan",
    WithdrawalStatus.FAILED: "⚠️ Bajarilmadi",
}
LEDGER_REASON = {
    LedgerReason.DEPOSIT: "📥 Depozit",
    LedgerReason.WITHDRAW_HOLD: "🔒 Yechish uchun bloklandi",
    LedgerReason.WITHDRAW_RELEASE: "🔓 Blokdan qaytarildi",
    LedgerReason.WITHDRAW_PAID: "📤 Kartaga yechildi",
    LedgerReason.PROMO_BONUS: "🎟 Promokod bonusi",
    LedgerReason.VIP_BONUS: "🏆 VIP bonus",
    LedgerReason.REFERRAL_BONUS: "🤝 Referal bonus",
    LedgerReason.REFERRAL_TRANSFER: "💸 Referal bonus o‘tkazmasi",
    LedgerReason.MANUAL_CREDIT: "➕ Admin krediti",
    LedgerReason.MANUAL_DEBIT: "➖ Admin debeti",
    LedgerReason.MASS_PAYOUT: "📦 Ommaviy to‘lov",
    LedgerReason.GAME_DEPOSIT: "🎮 O‘yin hisobiga o‘tkazildi",
    LedgerReason.GAME_DEPOSIT_REFUND: "↩️ O‘yin depoziti qaytarildi",
    LedgerReason.GAME_WITHDRAW: "🎮 Hisobdan hamyonga",
}
BATCH_STATUS = {
    MassBatchStatus.PREVIEW: "👁 Preview",
    MassBatchStatus.PROCESSING: "🔄 Jarayonda",
    MassBatchStatus.COMPLETED: "✅ Yakunlangan",
    MassBatchStatus.CANCELLED: "🚫 Bekor qilingan",
}
ITEM_STATUS = {
    MassItemStatus.VALID: "✅ to‘g‘ri",
    MassItemStatus.INVALID: "❌ xato",
    MassItemStatus.DUPLICATE: "♻️ dublikat",
    MassItemStatus.QUEUED: "⏳ navbatda",
    MassItemStatus.PAID: "✅ to‘landi",
    MassItemStatus.FAILED: "⚠️ bajarilmadi",
    MassItemStatus.SKIPPED: "⏭ o‘tkazildi",
}

# --------------------------------------------------------------------------- Mob-Cash: depozit
BTN_MC_SAME_ID = "✅ Shu ID bilan davom etish"
BTN_MC_OTHER_ID = "✏️ Boshqa ID kiritish"
BTN_MC_HISTORY = "📋 Tarixim"
BTN_MC_OTHER_CARD = "✏️ Boshqa karta"

MC_DEP_ASK_ID = "➕ <b>Hisob to‘ldirish</b>\n\n🆔 O‘yin hisobingiz ID raqamini yuboring:"
MC_DEP_SAVED_ID = (
    "➕ <b>Hisob to‘ldirish</b>\n\n🆔 Oxirgi ishlatilgan ID: <code>{payer_id}</code>\n"
    "Shu ID bilan davom etasizmi yoki boshqa ID yuborasizmi?"
)
MC_ID_INVALID = "⚠️ ID faqat raqamlardan iborat bo‘lishi kerak (5–15 ta raqam)."
MC_PAYER_NOT_FOUND = "❌ Bunday ID topilmadi. Raqamni tekshirib, qaytadan yuboring."
MC_UNAVAILABLE = "⚠️ Kassa vaqtincha ishlamayapti. Birozdan so‘ng urinib ko‘ring."
MC_DEP_ASK_AMOUNT = (
    "✅ Akkaunt topildi: <b>{nickname}</b>\n🆔 ID: <code>{payer_id}</code>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💰 O‘zingiz istagan summani kiriting:\n"
    "▫️ Minimal: <b>{min}</b>\n▫️ Maksimal: <b>{max}</b>\n\n"
    "✍️ Summani yozib yuboring yoki pastdan tanlang:"
)
MC_DEP_CREATED = (
    "🧾 <b>To‘lov #{id}</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💳 Karta: <code>{card}</code>\n"
    "👤 Egasi: <b>{holder}</b>\n\n"
    "💰 O‘tkazish summasi:\n"
    "        <code>{amount}</code> <b>so‘m</b>\n\n"
    "❗️ <b>Aynan shu summani o‘tkazing</b> — bir so‘m farq bo‘lsa ham avtomatik "
    "tasdiqlanmaydi. <i>(Summa va karta ustiga bossangiz nusxalanadi.)</i>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code> ({nickname})\n"
    "📥 Hisobga tushadi: <b>{credit}</b>\n"
    "⏳ Muddat: <b>{expires}</b> gacha\n\n"
    "✅ O‘tkazgandan so‘ng hech narsa qilish shart emas — tizim to‘lovni avtomatik "
    "tasdiqlaydi va hisobingizga tushiradi."
)
MC_DEP_HAS_PENDING = (
    "⚠️ Sizda yakunlanmagan to‘lov bor (#{id}). Avval uni to‘lang yoki bekor qiling."
)
MC_NO_CARDS = "⚠️ Hozircha to‘lov qabul qilinmayapti. Birozdan so‘ng urinib ko‘ring."
MC_AMOUNT_BUSY = "⚠️ Bu summa hozir band. Boshqa summa kiriting yoki birozdan so‘ng urinib ko‘ring."
MC_DEP_CANNOT_CANCEL = "⚠️ Bu to‘lovni bekor qilib bo‘lmaydi: {status}"
MC_DEP_CANCELLED = "🚫 To‘lov #{id} bekor qilindi."
MC_DEP_STATUS_LINE = "🧾 To‘lov #{id}: {status}"
MC_DEP_CREDITED = (
    "🎉 <b>To‘lov #{id} tasdiqlandi!</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💰 <b>{amount}</b> — ID <code>{payer_id}</code> hisobiga tushirildi.\n\n"
    "Omad tilaymiz! 🍀"
)
MC_DEP_LATE_NOTE = "\n\n<i>To‘lov muddatdan keyin kelgan bo‘lsa ham qabul qilindi.</i>"
MC_DEP_REVIEW = (
    "🕵️ To‘lov #{id} qabul qilindi, lekin hisobga avtomatik tushirib bo‘lmadi.\n"
    "Operator tez orada tekshiradi — pulingiz xavfsiz."
)
MC_DEP_EXPIRED = (
    "⌛ To‘lov #{id} muddati tugadi.\n\n"
    "Agar pulni o‘tkazgan bo‘lsangiz — xavotir olmang: {hours} soat ichida kelgan to‘lov "
    "avtomatik tasdiqlanadi. Aks holda «👨‍💻 Aloqa» orqali operatorga yozing."
)
MC_DEP_REJECTED = "❌ To‘lov #{id} rad etildi.{comment}"
MC_DEP_STATUS = {
    P2PDepositStatus.PENDING: "⏳ To‘lov kutilmoqda",
    P2PDepositStatus.PAID: "🔄 Qabul qilindi, hisobga tushirilmoqda",
    P2PDepositStatus.CREDITED: "✅ Hisobga tushirildi",
    P2PDepositStatus.REVIEW: "🕵️ Operator tekshiruvida",
    P2PDepositStatus.EXPIRED: "⌛ Muddati tugagan",
    P2PDepositStatus.CANCELLED: "🚫 Bekor qilingan",
    P2PDepositStatus.REJECTED: "❌ Rad etilgan",
}

# --------------------------------------------------------------------- Mob-Cash: hamyon to‘ldirish
MC_TOPUP_ASK_AMOUNT = (
    "➕ <b>Hamyonni to‘ldirish</b>\n\n"
    "💰 O‘zingiz istagan summani kiriting:\nMinimal: <b>{min}</b>\nMaksimal: <b>{max}</b>\n\n"
    "✍️ Summani yozib yuboring yoki pastdan tanlang:"
)
MC_TOPUP_CREATED = (
    "🧾 <b>To‘lov #{id}</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💳 Karta: <code>{card}</code>\n"
    "👤 Egasi: <b>{holder}</b>\n\n"
    "💰 O‘tkazish summasi:\n"
    "        <code>{amount}</code> <b>so‘m</b>\n\n"
    "❗️ <b>Aynan shu summani o‘tkazing</b> — bir so‘m farq bo‘lsa ham avtomatik "
    "tasdiqlanmaydi.\n"
    "━━━━━━━━━━━━━━━━\n"
    "🏠 Hamyoningizga tushadi: <b>{credit}</b>\n"
    "⏳ Muddat: <b>{expires}</b> gacha\n\n"
    "✅ O‘tkazgandan so‘ng hech narsa qilish shart emas — tizim to‘lovni avtomatik "
    "tasdiqlaydi va hamyoningizga tushiradi."
)
MC_TOPUP_CREDITED = (
    "🎉 <b>To‘lov #{id} tasdiqlandi!</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💰 <b>{amount}</b> — hamyoningizga tushirildi."
)
MC_TOPUP_STATUS = {
    P2PDepositStatus.PENDING: "⏳ To‘lov kutilmoqda",
    P2PDepositStatus.PAID: "🔄 Qabul qilindi, hamyonga tushirilmoqda",
    P2PDepositStatus.CREDITED: "✅ Hamyonga tushirildi",
    P2PDepositStatus.REVIEW: "🕵️ Operator tekshiruvida",
    P2PDepositStatus.EXPIRED: "⌛ Muddati tugagan",
    P2PDepositStatus.CANCELLED: "🚫 Bekor qilingan",
    P2PDepositStatus.REJECTED: "❌ Rad etilgan",
}

# --------------------------------------------------------------------- Mob-Cash: hamyondan hisobga
MC_CHOOSE_BOOKMAKER_WGAME = (
    "🎮 <b>Hisobga o‘tkazish</b>\n\nHamyoningizdagi puldan o‘yin hisobingizni to‘ldirasiz.\n"
    "Qaysi kantora hisobiga o‘tkazamiz?"
)
MC_WGAME_SAVED_ID = (
    "🎮 <b>Hisobga o‘tkazish</b>\n\n🆔 Oxirgi ishlatilgan ID: <code>{payer_id}</code>\n"
    "Shu ID bilan davom etasizmi yoki boshqa ID yuborasizmi?"
)
MC_WGAME_ASK_ID = "🎮 <b>Hisobga o‘tkazish</b>\n\n🆔 O‘yin hisobingiz ID raqamini yuboring:"
MC_WGAME_ASK_AMOUNT = (
    "✅ Akkaunt topildi: <b>{nickname}</b>\n🆔 ID: <code>{payer_id}</code>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💰 Hamyoningiz: <b>{balance}</b>\n\n"
    "✍️ O‘tkaziladigan summani kiriting yoki pastdan tanlang:\n"
    "▫️ Minimal: <b>{min}</b>\n▫️ Maksimal: <b>{max}</b>"
)
MC_WGAME_LOW_BALANCE = (
    "⚠️ Hamyoningizda yetarli pul yo‘q.\n💰 Mavjud: <b>{available}</b>\n"
    "Minimal o‘tkazma: <b>{min}</b>"
)
MC_WGAME_CONFIRM = (
    "🎮 <b>Tasdiqlang</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code> ({nickname})\n"
    "💵 O‘tkazma: <b>{amount}</b>\n"
    "💰 Hamyonda qoladi: {balance}\n"
    "━━━━━━━━━━━━━━━━\n"
    "Tasdiqlasangiz, summa hamyoningizdan yechilib, o‘yin hisobingizga tushiriladi."
)
MC_WGAME_PROCESSING = "⏳ O‘tkazilmoqda..."
MC_WGAME_DONE = (
    "✅ <b>#{id} — o‘tkazma bajarildi!</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💰 <b>{amount}</b> — ID <code>{payer_id}</code> hisobiga tushirildi.\n"
    "💰 Hamyoningiz: <b>{balance}</b>\n\n"
    "Omad tilaymiz! 🍀"
)
MC_WGAME_PENDING = (
    "🔄 <b>#{id} — o‘tkazma boshlandi</b>\n\n"
    "Kassa sekin javob berdi — summa tez orada hisobingizga tushadi, "
    "qayta urinishingiz shart emas."
)
MC_WGAME_REVIEW = (
    "🕵️ <b>#{id} — o‘tkazma tekshiruvda</b>\n\n"
    "Operator tez orada tekshiradi — pulingiz xavfsiz."
)


def mc_status(target: P2PDepositTarget, status: P2PDepositStatus) -> str:
    table = MC_TOPUP_STATUS if target == P2PDepositTarget.WALLET else MC_DEP_STATUS
    return table[status]


# --------------------------------------------------------------------------- Mob-Cash: yechish
MC_WD_INTRO = (
    "➖ <b>Pul chiqarish</b>\n\n"
    "1️⃣ O‘yin ilovasida «Pul chiqarish» → kassa orqali naqd pul usulini tanlang.\n"
    "2️⃣ Summani kiriting va <b>yechish kodini</b> oling.\n"
    "3️⃣ Shu yerga ID va kodni yuboring — pul kartangizga o‘tkaziladi.\n\n"
)
MC_WD_ASK_ID = MC_WD_INTRO + "🆔 O‘yin hisobingiz ID raqamini yuboring:"
MC_WD_SAVED_ID = (
    MC_WD_INTRO + "🆔 Oxirgi ishlatilgan ID: <code>{payer_id}</code>\n"
    "Shu ID bilan davom etasizmi yoki boshqa ID yuborasizmi?"
)
MC_WD_ASK_CODE = (
    "🔐 Yechish kodini yuboring\n🆔 ID: <code>{payer_id}</code>\n\n"
    "<i>Xavfsizlik uchun kod yozilgan xabar darhol o‘chiriladi.</i>"
)
MC_WD_CODE_INVALID = "⚠️ Kod noto‘g‘ri formatda. Ilovadagi kodni aynan ko‘chirib yuboring."
MC_WD_NOT_FOUND = (
    "❌ Yechish arizasi topilmadi yoki kod noto‘g‘ri.\n"
    "Ilovada arizani va kodni tekshirib, qaytadan yuboring."
)
MC_WD_NO_PREVIEW = (
    "⚠️ Bu kassa (1xBet Cashdesk) to‘lov kodini oldindan tekshirmaydi — summa faqat "
    "yechish bajarilganda ma’lum bo‘ladi. Bunday kassada yechishni kassa operatori "
    "summani ko‘rsatib o‘tkazadi."
)
MC_WD_OUT_OF_RANGE = "⚠️ Yechish summasi {min} dan {max} gacha bo‘lishi kerak. Arizangiz: {amount}"
MC_WD_ASK_DEST = (
    "💵 Yechish summasi: <b>{amount}</b>\n💸 Komissiya: {fee}\n✅ Qo‘lingizga tegadi: <b>{payout}</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "Pul qayerga tushsin?\n\n"
    "💳 <b>Kartaga</b> — karta raqamingizni kiritasiz, operator o‘tkazadi\n"
    "💎 <b>Hamyonga</b> — summa bot hamyoniga darhol tushadi"
)
BTN_WD_DEST_CARD = "💳 Kartaga"
BTN_WD_DEST_WALLET = "💎 Hamyonga"
MC_WD_ASK_DEST_ANY = (
    "Pul qayerga tushsin?\n\n"
    "💳 <b>Kartaga</b> — karta raqamingizni kiritasiz, operator o‘tkazadi\n"
    "💎 <b>Hamyonga</b> — summa bot hamyoniga darhol tushadi"
)
MC_WD_ASK_CARD = (
    "💵 Yechish summasi: <b>{amount}</b>\n💸 Komissiya: {fee}\n✅ Kartangizga: <b>{payout}</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💳 Pul o‘tkaziladigan karta raqamini yuboring (16 ta raqam):"
)
MC_WD_ASK_CARD_ANY = "💳 Pul o‘tkaziladigan karta raqamini yuboring (16 ta raqam):"
MC_WD_CARD_INVALID = "⚠️ Karta raqami 16 ta raqamdan iborat bo‘lishi kerak."
MC_WD_CONFIRM = (
    "📤 <b>Tasdiqlang</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code>\n"
    "💵 Summa: {amount}\n💸 Komissiya: {fee}\n✅ Kartaga: <b>{payout}</b>\n"
    "💳 Karta: <code>{card}</code>\n"
    "━━━━━━━━━━━━━━━━\n"
    "Tasdiqlasangiz, summa o‘yin hisobingizdan yechiladi va kartangizga o‘tkaziladi."
)
MC_WD_CONFIRM_WALLET = (
    "📤 <b>Tasdiqlang</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code>\n"
    "💵 Summa: {amount}\n💸 Komissiya: {fee}\n💎 Hamyonga: <b>{payout}</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "Tasdiqlasangiz, summa o‘yin hisobingizdan yechiladi va bot hamyoningizga tushadi."
)
MC_WD_CONFIRM_ANY = (
    "📤 <b>Tasdiqlang</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code>\n"
    "💳 Karta: <code>{card}</code>\n"
    "━━━━━━━━━━━━━━━━\n"
    "Tasdiqlasangiz, arizadagi summa o‘yin hisobingizdan yechilib, kartangizga o‘tkaziladi."
)
MC_WD_CONFIRM_WALLET_ANY = (
    "📤 <b>Tasdiqlang</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "🆔 ID: <code>{payer_id}</code>\n"
    "💎 Manzil: Hamyonga\n"
    "━━━━━━━━━━━━━━━━\n"
    "Tasdiqlasangiz, arizadagi summa o‘yin hisobingizdan yechilib, bot hamyoningizga tushadi."
)
MC_WD_PROCESSING = "⏳ Bajarilmoqda..."
MC_WD_BUSY = "⏳ Oldingi so‘rovingiz bajarilmoqda, biroz kuting."
MC_WD_CREATED = (
    "✅ <b>Ariza #{id} qabul qilindi!</b>\n"
    "━━━━━━━━━━━━━━━━\n"
    "💸 <b>{payout}</b> kartangizga (<code>{card}</code>) tez orada o‘tkaziladi.\n"
    "O‘tkazilganda sizga xabar beramiz."
)
MC_WD_REVIEW = (
    "🕵️ Ariza #{id} qabul qilindi, kassa javobi tekshirilmoqda.\n"
    "Operator tez orada tasdiqlaydi — qayta urinmang."
)
MC_WD_FAILED = "❌ Yechish amalga oshmadi: {reason}\n\nKodni tekshirib, qaytadan urinib ko‘ring."
MC_WD_PAID = "✅ <b>Ariza #{id}: {payout} kartangizga o‘tkazildi!</b>\n💳 <code>{card}</code>"
MC_WD_WALLET_DONE = "✅ <b>Ariza #{id} bajarildi!</b>\n💎 <b>{payout}</b> hamyoningizga tushdi."
MC_WD_WALLET_PAID_STATUS = "✅ Hamyonga o‘tkazildi"
MC_WD_REFUNDED = "↩️ Ariza #{id}: {amount} o‘yin hisobingizga qaytarildi.{comment}"
MC_WD_FAILED_USER = "❌ Ariza #{id} bajarilmadi.{comment}\n\nQaytadan urinib ko‘rishingiz mumkin."
MC_WD_STATUS = {
    MobcashWithdrawalStatus.AWAITING_PAYOUT: "⏳ Kartaga o‘tkazilmoqda",
    MobcashWithdrawalStatus.PAID: "✅ Kartaga o‘tkazildi",
    MobcashWithdrawalStatus.REVIEW: "🕵️ Tekshirilmoqda",
    MobcashWithdrawalStatus.REFUND_REVIEW: "🕵️ Qaytarish tekshirilmoqda",
    MobcashWithdrawalStatus.REFUNDED: "↩️ Hisobga qaytarildi",
    MobcashWithdrawalStatus.REJECTED: "❌ Rad etilgan",
    MobcashWithdrawalStatus.FAILED: "⚠️ Bajarilmadi",
}


def mc_wd_status(status: MobcashWithdrawalStatus, card_number: str) -> str:
    """Kartasiz (hamyon yo‘nalishli) yechimlar tarixda boshqacha ko‘rsatiladi."""
    if status == MobcashWithdrawalStatus.PAID and not card_number:
        return MC_WD_WALLET_PAID_STATUS
    return MC_WD_STATUS[status]

MC_HISTORY_TITLE = "📋 <b>Oxirgi amallaringiz</b>"
MC_HISTORY_EMPTY = "📋 Hali amallar yo‘q."

# --------------------------------------------------------------------------- admin tugmalari
ADM_STATS = "📊 Statistika & Hisobot"
ADM_USERS = "👥 Foydalanuvchilar & Boshqaruv"
ADM_SETTINGS = "⚙️ Tizim Sozlamalari"
ADM_MASS = "📦 Ommaviy to‘lov"
ADM_AUTO = "🤖 Avto to‘lov"
ADM_MANUAL = "💸 Ruchnoy yechish"
ADM_JOIN = "📋 Join Requestlar"
ADM_BONUS = "🎁 Bonus tizimi"
ADM_CHANNELS = "📢 Majburiy Obuna Kanallari"
ADM_MOBCASH = "🏦 Mob-Cash kassa"
ADM_USERBOT = "🛰 Userbot"
ADM_BOOKMAKERS = "🏢 Kantoralar"
ADM_EXIT = "🏠 Foydalanuvchi menyusi"
ADMIN_MENU_ROWS = (
    (ADM_MOBCASH, ADM_BOOKMAKERS),
    (ADM_USERBOT, ADM_STATS),
    (ADM_USERS, ADM_SETTINGS),
    (ADM_MASS, ADM_AUTO),
    (ADM_MANUAL, ADM_JOIN),
    (ADM_BONUS, ADM_CHANNELS),
    (ADM_EXIT,),
)
ADMIN_NO_PERM = "⛔ Bu amal uchun ruxsatingiz yo‘q yoki amal eskirgan."

# --------------------------------------------------------------------------- kantoralar
MC_NO_BOOKMAKERS = "🏢 <b>Kantoralar</b>\n\n❌ Hozircha faol kantora yo‘q. Tez orada ishga tushadi."
MC_CHOOSE_BOOKMAKER_DEP = "➕ <b>Hisob to‘ldirish</b>\n\nQaysi kantora hisobini to‘ldirasiz? 👇"
MC_CHOOSE_BOOKMAKER_WD = "➖ <b>Pul chiqarish</b>\n\nQaysi kantoradan pul chiqarasiz? 👇"

# --------------------------------------------------------------------------- Web App
BTN_WEBAPP = "💳 Kassa ilovasini ochish"
WEBAPP_PROMO = (
    "✨ <b>Kassa ilovasi</b>\n\n"
    "Hisob to‘ldirish, pul chiqarish, hamyon va bonuslar — hammasi bitta qulay oynada. 👇"
)
