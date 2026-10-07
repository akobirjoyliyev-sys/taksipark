"""Video + musiqa + ovozni birlashtirib, Instagram uchun tayyor MP4 chiqaradi.

Variantlar:
  python3 ovoz_qosh.py                     # faqat musiqa bilan (ovozsiz)
  python3 ovoz_qosh.py --edge              # Microsoft o'zbekcha AI ovozi (internet kerak: pip install edge-tts)
  python3 ovoz_qosh.py --edge --ayol       # ayol ovozi (Madina), standart: erkak (Sardor)
  python3 ovoz_qosh.py --fayl ovozim.m4a   # o'zingiz yozib olgan ovoz (0-soniyadan boshlanadi)

Ovoz yangrayotganda musiqa avtomatik pasayadi (ducking).
Natija: chiqish/reklama-instagram.mp4
"""
import argparse
import asyncio
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'chiqish')

# Matn sahnalarga mos: (boshlanish soniyasi, maksimal davomiylik, matn)
SSENARIY = [
    (0.3, 3.5, 'Taksi kerakmi? Bir necha daqiqada yetib boramiz!'),
    (4.3, 3.5, 'Taksopark — shahar bo‘ylab qulay va xavfsiz safarlar.'),
    (8.4, 5.3, 'Ekonom, Komfort yoki Biznes — o‘zingizga mos tarifni tanlang.'),
    (14.3, 3.5, 'Narx oldindan ma’lum, haydovchilar tajribali.'),
    (18.3, 3.3, 'Hoziroq ilovani yuklab oling yoki qo‘ng‘iroq qiling!'),
]


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


async def edge_segments(voice):
    import edge_tts  # pip install edge-tts
    os.makedirs(os.path.join(OUT, 'ovoz'), exist_ok=True)
    files = []
    for i, (start, maxlen, text) in enumerate(SSENARIY):
        path = os.path.join(OUT, 'ovoz', f'{i:02d}.mp3')
        rate = 0
        # Joyiga sig'maguncha biroz tezlashtiramiz
        while True:
            await edge_tts.Communicate(text, voice, rate=f'{rate:+d}%', pitch='-2Hz').save(path)
            if duration(path) <= maxlen or rate >= 30:
                break
            rate += 6
        files.append((start, path))
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--edge', action='store_true')
    ap.add_argument('--ayol', action='store_true')
    ap.add_argument('--fayl')
    a = ap.parse_args()

    video = os.path.join(OUT, 'video-ovozsiz.mp4')
    music = os.path.join(OUT, 'musiqa.wav')
    result = os.path.join(OUT, 'reklama-instagram.mp4')

    if a.edge:
        voice = 'uz-UZ-MadinaNeural' if a.ayol else 'uz-UZ-SardorNeural'
        segs = asyncio.run(edge_segments(voice))
    elif a.fayl:
        segs = [(0.0, a.fayl)]
    else:
        segs = []

    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-i', video, '-i', music]
    for _, f in segs:
        cmd += ['-i', f]

    if segs:
        parts = []
        for i, (start, _) in enumerate(segs):
            ms = int(start * 1000)
            parts.append(f'[{i + 2}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[v{i}]')
        vin = ''.join(f'[v{i}]' for i in range(len(segs)))
        fc = ';'.join(parts) + (
            f';{vin}amix=inputs={len(segs)}:normalize=0,'
            'highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=120,volume=1.6,asplit[voice][key];'
            '[1:a]volume=0.55[mus];'
            '[mus][key]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350[ducked];'
            '[ducked][voice]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=9[a]'
        )
    else:
        fc = '[1:a]loudnorm=I=-14:TP=-1.5:LRA=9[a]'

    cmd += ['-filter_complex', fc, '-map', '0:v', '-map', '[a]', '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-shortest', '-movflags', '+faststart', result]
    run(cmd)
    print('Tayyor:', result)


if __name__ == '__main__':
    main()
