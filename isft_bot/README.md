# ISFT LMS Bot

**my.isft.uz** platformasidagi vazifalarni avtomatik bajaruvchi bot.

## O'rnatish

```bash
cd isft_bot
pip install -r requirements.txt
playwright install chromium
```

## Sozlash

```bash
cp .env.example .env
```

`.env` faylini oching va ma'lumotlaringizni kiriting:
```
ISFT_USERNAME=login_nomingiz
ISFT_PASSWORD=parolingiz
ANTHROPIC_API_KEY=sk-ant-...   # ixtiyoriy, test savollari uchun
```

> **ANTHROPIC_API_KEY** olmak uchun: https://console.anthropic.com → API Keys

## Foydalanish

### 1. Vazifalarni ko'rish
```bash
python main.py list
```

### 2. Barcha vazifalarni avtomatik bajarish
```bash
python main.py run
```

### 3. Faqat bitta fanning vazifalarini bajarish
```bash
python main.py run --subject "Fizika 1"
```

### 4. To'g'ridan-to'g'ri bitta vazifa URL i bilan
```bash
python main.py run --task-url "https://my.isft.uz/task/123"
```

### 5. Topshirmasdan faqat ko'rish (test rejimi)
```bash
python main.py run --dry-run
```

### 6. Vazifa tuzilmasini ko'rish (agar bot topshira olmasa)
```bash
python main.py inspect "https://my.isft.uz/task/123" 
```

## Eslatmalar

- Bot birinchi marta ishga tushganda brauzer ochilib platformaga kiradi
- Test savollarini hal qilish uchun `ANTHROPIC_API_KEY` kerak
- `--show-browser` bilan ishga tushirsangiz, nima qilayotganini ko'rasiz
- Agar platforma strukturasi o'zgarsa, `inspect` buyrug'i bilan tekshiring
