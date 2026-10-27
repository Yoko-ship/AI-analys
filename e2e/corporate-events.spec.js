import { test, expect } from '@playwright/test';
const doc = (id, code, ticker, category, stage, priority) => ({
  id, source_url: `https://openinfo.uz/ru/facts/${code}/${id}`, code, tickers: [ticker], isins: ['UZ7011340005'],
  security_types: ['stock'],
  organization: ticker === 'HMKB' ? 'Hamkorbank' : 'O‘zbekgeofizika', category, stage, priority,
  title: { ru: stage === 'proposed' ? 'Набсовет рекомендовал дивиденды' : 'Компания утратила лицензию', en: 'Board recommended dividends', uz: 'Kuzatuv kengashi dividendlarni tavsiya qildi' },
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
test('payment totals and approved resolutions are explained separately from per-share amounts',async({page})=>{
 await setup(page);
 const paid={...a,stage:'paid',amounts:[],payment:{calculated:6060825,paid:6060825,debt:0,paid_percent:100,unit:'thousand_uzs'},summary:{ru:'Общие суммы в тысячах сум'},evidence:['Dividendlar to‘liq to‘langan'],record_date:null};
 await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{...payload,items:[{...paid,story_id:paid.id,documents:[paid],document_count:1}]}}));
 await page.reload();await expect(page.locator('.ce-story')).toContainText('Выплачено');
 await page.locator('.ce-story').getByRole('button',{name:/Документы и история/}).click();
 await expect(page.getByRole('dialog')).toContainText('тыс. сум');
 await expect(page.getByRole('dialog')).toContainText('6 060 825');
 await expect(page.getByRole('dialog')).toContainText('Dividendlar to‘liq to‘langan');
});

test('meeting documents distinguish publication from the date supported by source text', async ({ page }) => {
  await setup(page);
  const meeting = { ...b, id: '21404', source_url: 'https://openinfo.uz/ru/announce/21404',
    organization: 'Issiqlik Elektr Stansiyalari', stage: 'announced',
    title: {ru:'Объявлено собрание акционеров'}, published_at:'2026-10-02T17:33:06',
    event_date:'2026-10-23', decision_date:null, meeting_time:'11:00', date_source:'announcement_body',
    date_conflict:true, date_evidence:'2026-yil 23-oktabr kuni soat 11:00da yig‘ilishi bo‘lib o‘tishi ma’lum qilinadi.' };
  await page.route('**/api/news/corporate-events?**', r => r.fulfill({json:{...payload,items:[{...meeting,story_id:'21404',documents:[meeting],document_count:1}]}}));
  await page.reload();
  const card = page.locator('.ce-story');
  await expect(card.locator('time').first()).toHaveAttribute('datetime','2026-10-02T17:33:06');
  await card.getByRole('button',{name:/Документы/}).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('11:00');
  await expect(dialog).toContainText('Дата собрания взята из текста объявления');
  await expect(dialog.locator('.ce-date-evidence')).toContainText(meeting.date_evidence);
});

for (const prefix of ['', '/uz']) test(`corporate headlines open reloadable detail pages at ${prefix || '/'}`, async ({ page }, info) => {
  await page.setViewportSize({ width: prefix ? 390 : 1440, height: 900 });
  await setup(page);
  await page.route('**/api/news/corporate-events?**', route => {
    const query = new URL(route.request().url()).searchParams;
    const matching = query.get('start') === '2026-07-01' && query.get('end') === '2026-07-31';
    return route.fulfill({ json: { ...payload, items: matching ? payload.items : [] } });
  });
  await page.goto(`${prefix}/news?tab=corporate&instrument=stock&start=2026-07-01&end=2026-07-31`);
  const card = page.locator('.ce-story').filter({ hasText: 'O‘zbekgeofizika' });
  const headline = card.getByRole('link', { name: prefix ? 'Kuzatuv kengashi dividendlarni tavsiya qildi' : a.title.ru, exact: true });
  await expect(headline).toHaveAttribute('href', /event=577/);
  const detailURL = await headline.getAttribute('href');
  await headline.click();
  await expect(page).toHaveURL(detailURL);
  const detail = page.getByTestId('corporate-event-detail');
  await expect(detail.getByRole('heading', { level: 1 })).toHaveText('O‘zbekgeofizika');
  await expect(detail).toContainText(prefix ? '8.01' : '8,01');
  await expect(detail.getByRole('link', { name: /OpenInfo/ }).first()).toHaveAttribute('href', a.source_url);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.ce-story')).toHaveCount(0);
  await page.reload();
  await expect(detail).toContainText(prefix ? '71.5' : '71,5');
  for (const theme of ['light', 'dark']) {
    await page.evaluate(t => { document.documentElement.dataset.theme = document.body.dataset.theme = t; }, theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`detail-${theme}.png`), fullPage: true });
  }
  await page.goBack();
  await expect(page.locator('.ce-story')).toHaveCount(2);
  await expect(page).toHaveURL(/tab=corporate&instrument=stock&start=2026-07-01&end=2026-07-31$/);
  await page.goForward();
  await expect(detail).toBeVisible();
  await detail.locator('.led-back').click();
  await expect(page.locator('.ce-story')).toHaveCount(2);
  await expect(page).toHaveURL(/tab=corporate&instrument=stock$/);
});

test('a missing corporate detail has a clear state and a working return link', async ({ page }) => {
  await setup(page);
  await page.goto('/news?tab=corporate&event=missing&start=2026-07-01&end=2026-07-31');
  const detail = page.getByTestId('corporate-event-detail');
  await expect(detail).toContainText('Событие не найдено');
  await detail.getByRole('link', { name: /К корпоративным новостям/ }).click();
  await expect(page.locator('.ce-story')).toHaveCount(2);
});


test('changing the corporate instrument exits the detail view', async ({ page }) => {
  await setup(page);
  await page.locator('.ce-story').filter({hasText:'O‘zbekgeofizika'}).getByRole('link',{name:a.title.ru,exact:true}).click();
  await expect(page.getByTestId('corporate-event-detail')).toBeVisible();
  await page.locator('.newsdesk-subtabs').getByRole('button',{name:'Акции',exact:true}).click();
  await expect(page.getByTestId('corporate-event-detail')).toHaveCount(0);
  await expect(page.locator('.ce-story')).toHaveCount(2);
});
