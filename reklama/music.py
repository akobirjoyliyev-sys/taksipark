"""Reklama uchun fon musiqasi va effektlarni noldan sintez qiladi (mualliflik huquqi muammosiz).

120 BPM, 22 soniya; sahna almashinuvlari (4, 8, 14, 18 s) taktga mos.
Natija: chiqish/musiqa.wav
"""
import os
import wave

import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve

SR = 48000
BPM = 120
BEAT = 60 / BPM
DUR = 22.0
N = int(SR * DUR)
rng = np.random.default_rng(7)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chiqish')


def t_axis(sec):
    return np.arange(int(sec * SR)) / SR


def lp(x, hz, order=2):
    return sosfilt(butter(order, hz, 'low', fs=SR, output='sos'), x)


def hp(x, hz, order=2):
    return sosfilt(butter(order, hz, 'high', fs=SR, output='sos'), x)


def bp(x, lo, hi, order=2):
    return sosfilt(butter(order, [lo, hi], 'band', fs=SR, output='sos'), x)


def place(buf, sig, at, gain=1.0):
    i = int(at * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def saw(f, t, detune=0.0):
    ph = (f * (1 + detune) * t) % 1.0
    return 2 * ph - 1


# ---------- Cholg'ular ----------
def kick():
    t = t_axis(0.45)
    f = 45 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7)
    click = hp(rng.standard_normal(len(t)), 3000) * np.exp(-t * 300) * 0.25
    return np.tanh((body + click) * 1.6)


def clap():
    t = t_axis(0.3)
    n = bp(rng.standard_normal(len(t)), 900, 4000)
    env = np.exp(-t * 18)
    for d in (0.0, 0.011, 0.022):
        env += np.where(t >= d, np.exp(-(t - d) * 160), 0) * 0.6
    return n * env * 0.5


def hat(open_=False):
    t = t_axis(0.25 if open_ else 0.06)
    n = hp(rng.standard_normal(len(t)), 8000)
    return n * np.exp(-t * (14 if open_ else 70)) * 0.25


def bass_note(note, dur):
    t = t_axis(dur)
    f = midi(note)
    x = saw(f, t) * 0.6 + np.sin(2 * np.pi * f * t) * 0.8
    x = lp(x, 400)
    env = np.minimum(1, t / 0.005) * np.exp(-t * 5)
    return x * env


def pad_chord(notes, dur):
    t = t_axis(dur)
    x = np.zeros_like(t)
    for n in notes:
        for dt in (-0.006, 0.0, 0.007):
            x += saw(midi(n), t, dt) / 3
    x = lp(x / len(notes), 1400)
    env = np.minimum(1, t / 0.25) * np.minimum(1, (dur - t) / 0.3)
    return x * env


def pluck(note):
    t = t_axis(0.35)
    f = midi(note)
    x = np.sign(np.sin(2 * np.pi * f * t)) * 0.5 + np.sin(2 * np.pi * f * 2 * t) * 0.3
    x = lp(x, 2600)
    return x * np.exp(-t * 14)


def whoosh(length=0.6, rev=False):
    t = t_axis(length)
    n = rng.standard_normal(len(t))
    k = t / length
    if rev:
        k = 1 - k
    # Chastota ko'tariladigan shovqin (riser)
    out = np.zeros_like(t)
    segs = 24
    for s in range(segs):
        a, b = s * len(t) // segs, (s + 1) * len(t) // segs
        c = 400 + 7000 * (s / segs) ** 2
        out[a:b] = bp(n, c * 0.7, min(c * 1.4, 20000))[a:b]
    env = np.sin(np.pi * np.clip(k, 0, 1)) ** 2 if not rev else np.exp(-t * 6)
    return out * env


def impact():
    t = t_axis(1.6)
    boom = np.sin(2 * np.pi * np.cumsum(30 + 60 * np.exp(-t * 10)) / SR) * np.exp(-t * 3)
    crash = hp(rng.standard_normal(len(t)), 5000) * np.exp(-t * 2.5) * 0.35
    return boom * 0.9 + crash


def reverb(x, sec=1.8, mix=0.22):
    t = t_axis(sec)
    ir = rng.standard_normal(len(t)) * np.exp(-t * 4)
    ir = lp(ir, 5000)
    wet = fftconvolve(x, ir)[: len(x)]
    wet /= np.max(np.abs(wet)) + 1e-9
    return x * (1 - mix) + wet * mix * np.max(np.abs(x))


# ---------- Aranjirovka ----------
# Akkordlar: Am - F - C - G (har biri 1 takt = 2 s)
CHORDS = [(57, [57, 60, 64, 69]), (53, [53, 57, 60, 65]), (48, [52, 55, 60, 64]), (55, [55, 59, 62, 67])]
BAR = 4 * BEAT
END_GROOVE = 20.0  # 20 s dan keyin yakuniy akkord

drums, bass, pad, arp, fx = (np.zeros(N) for _ in range(5))
duck = np.ones(N)  # kick bo'yicha "sidechain"

for bar in range(int(DUR / BAR) + 1):
    t0 = bar * BAR
    root, notes = CHORDS[bar % 4]
    if t0 < END_GROOVE:
        place(pad, pad_chord(notes, BAR + 0.05), t0)
    for b in range(4):
        tb = t0 + b * BEAT
        if tb >= END_GROOVE:
            break
        intro = tb < 4.0
        place(drums, kick(), tb, 0.55 if intro else 0.9)
        i = int(tb * SR)
        dl = int(0.3 * SR)
        tt = np.arange(min(dl, N - i)) / SR
        duck[i:i + len(tt)] = np.minimum(duck[i:i + len(tt)], 1 - 0.65 * np.exp(-tt * 12))
        if not intro:
            if b in (1, 3):
                place(drums, clap(), tb, 0.8)
            place(drums, hat(open_=(b % 2 == 1)), tb + BEAT / 2, 0.8)
            place(drums, hat(), tb + BEAT / 4, 0.35)
            place(drums, hat(), tb + 3 * BEAT / 4, 0.35)
            place(bass, bass_note(root - 12, BEAT / 2 - 0.02), tb + BEAT / 2, 0.9)
        # Arpedjio: 16-liklar
        for s in range(4):
            ts = tb + s * BEAT / 4
            n = notes[(b * 4 + s) % len(notes)] + 12
            place(arp, pluck(n), ts, 0.18 if intro else 0.26)

# Yakuniy akkord (20 s): katta, cho'ziluvchan
root, notes = CHORDS[0]
place(pad, pad_chord(notes + [notes[0] + 12], 2.0), END_GROOVE, 1.3)
place(bass, bass_note(root - 12, 1.8) * 1.2, END_GROOVE)
place(drums, kick(), END_GROOVE, 1.0)
place(fx, impact(), END_GROOVE, 0.5)

# Effektlar: 4 s dan oldin riser, keyin impact; boshqa o'tishlarda whoosh
place(fx, whoosh(1.5), 4.0 - 1.5, 0.45)
place(fx, impact(), 4.0, 0.7)
for at in (8.0, 14.0, 18.0):
    place(fx, whoosh(0.55), at - 0.45, 0.5)

# Arp uchun 3/16 echo
d = int(0.375 * SR)
echo = np.zeros(N)
echo[d:] = arp[:-d] * 0.35
arp_full = lp(arp + echo, 6000)

pad = pad * duck
bass = bass * (0.6 + 0.4 * duck)

left = drums * 0.9 + bass * 0.9 + pad * 0.55 + arp_full * 0.75 + fx * 0.8
right = drums * 0.9 + bass * 0.9 + pad * 0.55 + np.roll(arp_full, int(0.012 * SR)) * 0.75 + fx * 0.8
left, right = reverb(left), reverb(right)

# Oxirida silliq so'nish
tail = np.ones(N)
fade = int(1.2 * SR)
tail[-fade:] = np.linspace(1, 0, fade) ** 2
mix = np.stack([left, right], axis=1) * tail[:, None]
mix = np.tanh(mix / np.max(np.abs(mix)) * 1.3)
mix = mix / np.max(np.abs(mix)) * 0.89

os.makedirs(OUT, exist_ok=True)
with wave.open(os.path.join(OUT, 'musiqa.wav'), 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype('<i2').tobytes())
print('Tayyor: chiqish/musiqa.wav')
