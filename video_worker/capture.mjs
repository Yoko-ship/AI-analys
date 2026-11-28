import { chromium } from 'playwright';
import { readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';

const folder = path.resolve(process.argv[2]);
const { scenes } = JSON.parse(await readFile(path.join(folder, 'storyboard.json'), 'utf8'));
const pages = { home: '/', news: '/news', market: '/market', catalog: '/catalog' };
const browser = await chromium.launch({ headless: true });
try {
  for (const [index, scene] of scenes.entries()) {
    if (!Object.hasOwn(pages, scene.page)) throw new Error('Unknown public website page');
    const context = await browser.newContext({ viewport: { width: 720, height: 776 }, locale: 'ru-RU',
      recordVideo: { dir: folder, size: { width: 720, height: 776 } } });
    await context.addInitScript(() => localStorage.setItem('uz_stock_analyzer_language', 'ru'));
    const page = await context.newPage();
    const response = await page.goto(`https://uzstock.uz${pages[scene.page]}`, { waitUntil: 'networkidle', timeout: 60000 });
    if (!response?.ok() || new URL(page.url()).hostname !== 'uzstock.uz') throw new Error('Website recording unavailable');
    await page.evaluate(() => document.fonts.ready);
    const body = await page.locator('body').innerText();
    if (body.length < 200 || /just a moment|verify you are human/i.test(body)) throw new Error('Website not ready to record');
    const readyAt = await page.evaluate(() => performance.now() / 1000);
    await page.screenshot({ path: path.join(folder, `site-${index}.png`) });
    await page.evaluate(async () => {
      const maximum = Math.min(700, document.documentElement.scrollHeight - innerHeight);
      const started = performance.now();
      await new Promise(resolve => {
        function frame(now) {
          const t = Math.min(1, (now - started) / 8000);
          const progress = (1 - Math.cos(t * Math.PI * 2)) / 2;
          scrollTo(0, Math.max(0, maximum) * progress);
          if (t < 1) requestAnimationFrame(frame); else resolve();
        }
        requestAnimationFrame(frame);
      });
    });
    const video = page.video();
    await context.close();
    await rename(await video.path(), path.join(folder, `capture-${index}.webm`));
    await writeFile(path.join(folder, `capture-${index}.json`), JSON.stringify({ readyAt, url: `https://uzstock.uz${pages[scene.page]}` }));
  }
} finally { await browser.close(); }
