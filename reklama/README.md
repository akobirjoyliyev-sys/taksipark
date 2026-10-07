# Instagram reklama videosi (Reels, 9:16)

Taksopark xizmatlari uchun 22 soniyalik reklama: brend ranglari, animatsiyali matnlar, fon musiqasi va ovoz qo‘shish imkoniyati.

| Soniya | Sahna | Ekrandagi matn |
|---|---|---|
| 0–4 | Ilmoq (hook) | Taksi kerakmi? · Bir necha daqiqada yetib boramiz |
| 4–8 | Brend | Logotip · Taksopark · Shahar bo‘ylab qulay va xavfsiz safarlar |
| 8–14 | Tariflar | Ekonom · Komfort · Biznes |
| 14–18 | Afzalliklar | Narx oldindan ma’lum · Tajribali haydovchilar · Safarni real vaqtda kuzating · Qulay mobil ilova |
| 18–22 | Chaqiriq | Hoziroq buyurtma bering · Ilovani yuklab oling · telefon raqami |

## Fayllar

- `video.html` — barcha sahnalar va animatsiyalar. Park nomi va telefon raqami fayl boshidagi `CONFIG` ichida.
- `render.cjs` — HTMLni kadrma-kadr yozib, `chiqish/video-ovozsiz.mp4` yaratadi (Playwright + FFmpeg).
- `music.py` — fon musiqasini noldan sintez qiladi (`chiqish/musiqa.wav`), mualliflik huquqi muammosi yo‘q.
- `ovoz_qosh.py` — video, musiqa va ovozni birlashtirib `chiqish/reklama-instagram.mp4` chiqaradi.

## Qayta yig‘ish

```sh
npm i playwright        # bir marta
python3 -m pip install numpy scipy
node render.cjs
python3 music.py
python3 ovoz_qosh.py                    # faqat musiqa bilan
python3 ovoz_qosh.py --edge             # + o'zbekcha AI ovoz (pip install edge-tts, internet kerak)
python3 ovoz_qosh.py --fayl ovozim.m4a  # + o'zingiz yozib olgan ovoz
```

## Ovoz uchun matn (diktor)

| Boshlanish | Matn |
|---|---|
| 0:00 | Taksi kerakmi? Bir necha daqiqada yetib boramiz! |
| 0:04 | Taksopark — shahar bo‘ylab qulay va xavfsiz safarlar. |
| 0:08 | Ekonom, Komfort yoki Biznes — o‘zingizga mos tarifni tanlang. |
| 0:14 | Narx oldindan ma’lum, haydovchilar tajribali. |
| 0:18 | Hoziroq ilovani yuklab oling yoki qo‘ng‘iroq qiling! |
