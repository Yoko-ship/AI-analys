import { test, expect } from '@playwright/test';
const doc = (id, code, ticker, category, stage, priority) => ({
  id, source_url: `https://openinfo.uz/ru/facts/${code}/${id}`, code, tickers: [ticker], isins: ['UZ7011340005'],
  security_types: ['stock'],
  organization: ticker === 'HMKB' ? 'Hamkorbank' : 'O‘zbekgeofizika', category, stage, priority,
  title: { ru: stage === 'proposed' ? 'Набсовет рекомендовал дивиденды' : 'Компания утратила лицензию', en: 'Board recommended dividends' },
  published_at: '2026-07-06T15:01:18', decision_date: '2026-06-22', confidence: 'confirmed',
  amounts: [{ security: 'ordinary', amount: 8.01 }, { security: 'preferred', amount: 71.5 }],
});
const a = doc('577', 41, 'UZGF', 'dividends', 'proposed', 1);
const b = {...doc('1', 23, 'HMKB', 'risks', 'disclosed', 0), amounts: []};
const payload = { ok: true, sources: { facts: { ok: true } },
  categories: { dividends: { ru: 'Дивиденды и выплаты' }, risks: { ru: 'Риски и лицензии' } },
  facts: { 41: { title: { ru: 'Набсовет рекомендовал дивиденды' } }, 23: { title: { ru: 'Компания утратила лицензию' } } },
  items: [a, b].map(d => ({ ...d, story_id: d.id, documents: [d], document_count: 1 })) };
async function setup(page) {
  await page.addInitScript(() => { sessionStorage.setItem('uz_sponsor_seen', '1'); localStorage.setItem('uz_stock_analyzer_token', 'test'); });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path === '/api/news/corporate-events' ? payload
      : path === '/api/auth/me' ? { user: { id: 1, email: 'reader@example.test' } }
      : path === '/api/profile' ? { user: { id: 1, email: 'reader@example.test' }, favorites: [{ ticker: 'HMKB' }] }
      : { ok: true, items: [] } });
  });
  await page.goto('/news?tab=corporate');
}
test('corporate feed has categories, evidence, stages, filters and source history', async ({ page }) => {
  await setup(page);
  const feed = page.getByTestId('corporate-events');
  await expect(feed.getByRole('heading', { name: 'Корпоративные события' })).toBeVisible();
  await expect(feed.locator('.ce-story')).toHaveCount(2);
  await feed.getByLabel('Компания, тикер или ISIN').fill('UZ7011340005');
  await expect(feed.locator('.ce-story')).toHaveCount(2);
  await feed.getByLabel('Компания, тикер или ISIN').fill('UZGF');
  await expect(feed.locator('.ce-story')).toHaveCount(1);
  await feed.getByRole('button', { name: /Документы и история/ }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Предложение');
  await expect(dialog).toContainText('8,01');
  await expect(dialog).toContainText('71,5');
  await expect(dialog.getByRole('link', { name: /OpenInfo/ }).first()).toHaveAttribute('href', a.source_url);
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await feed.getByLabel('Компания, тикер или ISIN').fill('');
  await feed.getByRole('button', { name: 'Мои компании', exact: true }).click();
  await expect(feed.locator('.ce-story')).toHaveCount(1);
  await expect(feed.locator('.ce-story')).toContainText('Hamkorbank');
});
for (const width of [390, 1440]) test(`corporate feed fits ${width}px in both themes`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 900 });
  await setup(page);
  for (const theme of ['light', 'dark']) {
    await page.evaluate(t => { document.documentElement.dataset.theme = document.body.dataset.theme = t; }, theme);
    await expect(page.locator('.ce-story')).toHaveCount(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`events-${width}-${theme}.png`), fullPage: true });
  }
});

test('stock filter retains non-payment disclosures for registered shares', async ({page}) => {
 await setup(page);
 await page.locator('.newsdesk-subtabs').getByRole('button', {name:'Акции',exact:true}).click();
 await expect(page.locator('.ce-story')).toHaveCount(2);
 await page.locator('.newsdesk-subtabs').getByRole('button', {name:'Облигации',exact:true}).click();
 await expect(page.locator('.ce-story')).toHaveCount(0);
});
