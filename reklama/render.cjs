// Videoni kadrma-kadr yozib oladi va FFmpeg orqali MP4 ga aylantiradi.
// Ishlatish:
//   node render.cjs                 -> chiqish/video-ovozsiz.mp4
//   node render.cjs --stills 1,5,10 -> chiqish/kadr-1.png ... (tekshirish uchun)
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const FPS = 30;
const OUT = path.join(__dirname, 'chiqish');
fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'video.html'));
  await page.evaluate(() => document.fonts.ready);
  const duration = await page.evaluate(() => window.DURATION);

  const stillsArg = process.argv.indexOf('--stills');
  if (stillsArg !== -1) {
    for (const s of process.argv[stillsArg + 1].split(',').map(Number)) {
      await page.evaluate(t => window.seek(t), s);
      await page.screenshot({ path: path.join(OUT, `kadr-${s}.png`) });
    }
    await browser.close();
    return;
  }

  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
    path.join(OUT, 'video-ovozsiz.mp4')], { stdio: ['pipe', 'inherit', 'inherit'] });

  const frames = Math.round(duration * FPS);
  for (let i = 0; i < frames; i++) {
    await page.evaluate(t => window.seek(t), i / FPS);
    const buf = await page.screenshot({ type: 'png' });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (i % 60 === 0) process.stdout.write(`kadr ${i}/${frames}\n`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  await browser.close();
  console.log('Tayyor: chiqish/video-ovozsiz.mp4');
})();
