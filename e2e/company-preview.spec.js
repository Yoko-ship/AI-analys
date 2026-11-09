import { test, expect } from '@playwright/test';
import { setupLanding } from './landing-fixtures.js';

// Real board tickers, deterministic prices: these fixtures exercise the preview,
// not the market's current quote or the issuer's financial results.
const stocks = [
  { ticker: 'UNVB', name: 'Universal bank', last_price: 13200.12, close_price: 13000, sector: 'finance', logo_url: '/logos/UNVB.png' },
  { ticker: 'UPOSP', name: "O‘zbekiston pochtasi", last_price: 49600, close_price: 51000, sector: 'logistics', is_preferred: true },
].map(r => ({ ...r, type: 'stock', security_type: 'stock', isin: `UZ${r.ticker}`, volume: 4e7,
  quantity: 3000, trade_count: 12, last_trade_date: '2026-11-05', market_cap: 137e9 }));

const history = Array.from({ length: 110 }, (_, i) => {
  const close = 11000 + i * 20 + Math.sin(i / 8) * 1200;
  const open = close + Math.cos(i) * 180;
  return { date: new Date(Date.UTC(2026, 6, 1 + i)).toISOString().slice(0, 10),
    open, close, high: Math.max(open, close) + 120, low: Math.min(open, close) - 150,
    value: 2e7 + (i % 11) * 3e6, volume: 2000 };
}).reverse();

async function setupPreviewSession(page, { role = 'administrator', authenticate } = {}) {
  await page.addInitScript(role => {
    if (role) localStorage.setItem('uz_stock_analyzer_token', `preview-${role}`);
  }, role);
  await page.route('**/api/auth/me', async route => {
    await authenticate?.();
    return route.fulfill({ status: role ? 200 : 401, json: { user: role ? {
      id: 1, email: `${role}@example.test`, is_admin: role === 'legacy-admin',
      admin_role: role === 'reader' ? null : role, pro_access: true,
    } : null } });
  });
}

async function openBoard(page, { theme = 'dark', mode = 'ready', ...session } = {}) {
  const requests = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(theme => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_track_internal', '1');
    localStorage.setItem('uz_stock_analyzer_theme', theme);
    localStorage.setItem('uz_market_cols_v3', JSON.stringify(['change', 'volume', 'date']));
  }, theme);
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/companies') return json({ companies: stocks.map(r => ({ ...r, company_name: r.name })) });
    if (path === '/api/securities') return json({ ok: true, securities: Object.fromEntries(stocks.map(r => [r.ticker, r])) });
    if (path === '/api/market/stocks') return json({ stocks });
    if (path === '/api/market/trade-stats') return json({ ok: true, stats: {} });
    if (path === '/api/market/financials') return json({ ok: true, financials: {} });
    if (path === '/api/market/multiples') return json({ ok: true, items: [] });
    if (path.startsWith('/api/price-history/')) {
      requests.push(url.pathname + url.search);
      if (mode === 'error') return route.fulfill({ status: 503, json: { ok: false } });
      return json({ ok: true, points: mode === 'empty' ? [] : history, as_of: '2026-11-05', adjustments: [] });
    }
    if (path.startsWith('/api/news/ticker/')) return json({ ok: true, items: mode === 'ready' ? [{
      id: 701, title: `${path.split('/').at(-1)}: опубликованы итоги квартала`,
      lang: 'ru', source: 'OpenInfo', published_at: '2026-11-05T10:00:00',
    }] : [] });
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: { user: null } });
    return json({ ok: true });
  });
  await setupPreviewSession(page, session);
  await page.goto('/market');
  await expect(page.locator('.market-table tbody tr')).toHaveCount(2);
  return { requests, errors };
}

const rowFor = (page, ticker) => page.locator('.market-table tbody tr').filter({ has: page.getByRole('button', { name: ticker, exact: true }) });
const logoFor = (page, ticker) => rowFor(page, ticker).locator('.chip-logo, .chip-logo-fallback');
const preview = page => page.getByRole('dialog', { name: /Обзор компании/ });

for (const theme of ['light', 'dark']) test(`company logo opens a chart preview without navigating (${theme})`, async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const { requests, errors } = await openBoard(page, { theme });
  expect(requests).toEqual([]);
  await logoFor(page, 'UNVB').hover();
  const card = preview(page);
  await expect(card).toBeVisible();
  await expect(card).toContainText('Universal bank');
  await expect(card).toContainText('2026-11-05');
  await expect(card).toContainText(/13\s*200,12/);
  await expect(card).toContainText('+1,54%');
  await expect(card.getByRole('img', { name: /График цены UNVB/ })).toBeVisible();
  await expect(card.locator('[data-candle]')).toHaveCount(110);
  await expect(card.getByRole('link', { name: /UNVB: опубликованы/ })).toHaveAttribute('href', '/news/701');
  expect(requests).toEqual(['/api/price-history/UNVB?months=6']);
  expect(new URL(page.url()).pathname).toBe('/market');
  // A body portal escapes the board's horizontal clipping and pinned columns.
  expect(await card.evaluate(el => el.parentElement === document.body)).toBe(true);
  await card.hover();
  await page.screenshot({ path: testInfo.outputPath(`company-preview-${theme}.png`) });
  await card.screenshot({ path: testInfo.outputPath(`company-preview-card-${theme}.png`) });
  await expect(card).toBeVisible();
  await page.mouse.move(1420, 5);
  await expect(card).toBeHidden();
  await logoFor(page, 'UNVB').hover();
  await expect(card).toBeVisible();
  await expect(card.locator('[data-candle]')).toHaveCount(110);
  expect(requests).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('keyboard users can open, dismiss and follow the company preview', async ({ page }) => {
  await openBoard(page);
  const trigger = rowFor(page, 'UNVB').getByRole('button', { name: 'Обзор компании UNVB' });
  await trigger.focus();
  await expect(preview(page)).toBeVisible();
  await expect(trigger).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(preview(page)).toBeHidden();
  await expect(trigger).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(preview(page)).toBeVisible();
  const link = preview(page).getByRole('link', { name: 'Открыть компанию' });
  await expect(link).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/company\/UNVB/);
  await expect(preview(page)).toBeHidden();
});

test('switching logos never shows the previous company response', async ({ page }) => {
  const { errors } = await openBoard(page);
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  await page.route('**/api/price-history/UNVB?*', async route => {
    await waiting;
    await route.fulfill({ json: { ok: true, points: history } });
  });
  await logoFor(page, 'UNVB').hover();
  await expect(preview(page).getByRole('status')).toContainText('Загружаем график');
  await logoFor(page, 'UPOSP').hover();
  await expect(preview(page)).toContainText('O‘zbekiston pochtasi');
  await expect(preview(page).getByRole('img', { name: /График цены UPOSP/ })).toBeVisible();
  release();
  await expect(preview(page)).toHaveCount(1);
  await expect(preview(page)).not.toContainText('Universal bank');
  await expect(preview(page)).toContainText('Привилегированные');
  expect(errors).toEqual([]);
});

for (const mode of ['empty', 'error']) test(`preview handles ${mode} history without inventing a chart`, async ({ page }) => {
  await openBoard(page, { mode });
  await logoFor(page, 'UNVB').hover();
  const card = preview(page);
  await expect(card).toContainText(mode === 'empty' ? 'Нет истории торгов за 6 месяцев' : 'Не удалось загрузить график');
  await expect(card.locator('[data-candle]')).toHaveCount(0);
  await expect(card).toContainText('Universal bank');
  await expect(card).toContainText('Нет новостей за последние 90 дней');
  await expect(card.getByRole('link', { name: 'Открыть компанию' })).toBeVisible();
});

test.describe('touch preview', () => {
test.use({ hasTouch: true });
test('tapping a logo opens a preview inside a small viewport and outside tap closes it', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openBoard(page);
  const trigger = rowFor(page, 'UPOSP').getByRole('button', { name: 'Обзор компании UPOSP' });
  await trigger.tap();
  const card = preview(page);
  await expect(card).toBeVisible();
  await expect(card.getByRole('img', { name: /График цены UPOSP/ })).toBeVisible();
  const box = await card.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(8);
  expect(box.x + box.width).toBeLessThanOrEqual(382);
  expect(box.y).toBeGreaterThanOrEqual(8);
  expect(box.y + box.height).toBeLessThanOrEqual(836);
  await page.screenshot({ path: testInfo.outputPath('company-preview-mobile.png') });
  await page.touchscreen.tap(3, 3);
  await expect(card).toBeHidden();
});
});

test('crossing a logo briefly does not fetch history or leave a card behind', async ({ page }) => {
  const { requests } = await openBoard(page);
  const now = new Date('2026-11-07T10:00:00Z');
  await page.clock.install({time:now});
  await page.clock.pauseAt(new Date(now.getTime()+10000));
  await logoFor(page, 'UNVB').hover();
  await page.mouse.move(3, 3);
  await page.clock.runFor(1000);
  await expect(preview(page)).toBeHidden();
  expect(requests).toEqual([]);
});

test('sparse history keeps dated closes and omits invalid prices without invented ranges', async ({ page }) => {
  await openBoard(page);
  await page.route('**/api/price-history/UNVB?*', route => route.fulfill({ json: {
    ok: true, points: [
      { date: '20261105', close: '13200.12' },
      { date: '2026-11-04', close: null },
      { date: '2026-11-03', close: 0 },
      { date: '2026-11-02', close: 13000, open: 12900, low: 12800, high: 13100 },
      { date: 'invalid', close: 99999 },
    ], adjustments: [{ ex_date: '2026-10-15' }],
  } }));
  await logoFor(page, 'UNVB').hover();
  const bars = preview(page).locator('[data-candle]');
  await expect(bars).toHaveCount(2);
  await expect(bars.first()).toHaveAttribute('data-candle', '2026-11-02');
  await expect(bars.last()).toHaveAttribute('data-candle', '2026-11-05');
  expect(await bars.last().locator('line').evaluate(el => el.getAttribute('y1') === el.getAttribute('y2'))).toBe(true);
  await expect(preview(page)).toContainText('История: 2026-11-02 — 2026-11-05');
  await expect(preview(page)).toContainText('История скорректирована на корпоративные действия');
});

async function openHomepage(page, options = {}) {
  await setupLanding(page, options);
  await setupPreviewSession(page, options);
  const requests = [], errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/price-history/*?*', route => {
    requests.push(new URL(route.request().url()).pathname + new URL(route.request().url()).search);
    return route.fulfill({ json: { ok: true, points: history, adjustments: [] } });
  });
  await page.route('**/api/news/ticker/*?*', route => route.fulfill({ json: { ok: true, items: [] } }));
  await page.goto('/');
  await expect(page.locator('.landing-market tbody tr')).toHaveCount(5);
  return { requests, errors };
}

for (const theme of ['dark', 'light']) test(`homepage logos share the market chart preview (${theme})`, async ({ page }, testInfo) => {
  const { requests, errors } = await openHomepage(page, { theme });
  expect(requests).toEqual([]);
  const tableLogo = page.locator('.landing-market').getByRole('button', { name: 'Обзор компании HMKB', exact: true });
  const featuredLogo = page.locator('.landing-company-example').getByRole('button', { name: 'Обзор компании HMKB', exact: true });
  await tableLogo.hover();
  const card = preview(page);
  await expect(card.getByRole('img', { name: /График цены HMKB/ })).toBeVisible();
  await expect(card.locator('[data-candle]')).toHaveCount(110);
  await expect(card.locator('.company-preview-quote')).toContainText('118');
  await expect(card).toContainText('Хамкорбанк');
  await expect(tableLogo).toHaveAttribute('aria-expanded', 'true');
  await expect(featuredLogo).toHaveAttribute('aria-expanded', 'false');
  await expect(page).toHaveURL(/\/$/);
  expect(await card.evaluate(el => el.parentElement === document.body)).toBe(true);
  await card.hover();
  await page.screenshot({ path: testInfo.outputPath(`homepage-table-preview-${theme}.png`) });
  await page.mouse.move(3, 3);
  await expect(card).toBeHidden();
  await featuredLogo.hover();
  await expect(card.getByRole('img', { name: /График цены HMKB/ })).toBeVisible();
  await expect(featuredLogo).toHaveAttribute('aria-expanded', 'true');
  await expect(tableLogo).toHaveAttribute('aria-expanded', 'false');
  await page.screenshot({ path: testInfo.outputPath(`homepage-featured-preview-${theme}.png`) });
  expect(requests).toEqual(['/api/price-history/HMKB?months=6']);
  await card.getByRole('link', { name: 'Открыть компанию', exact: true }).click();
  await expect(page).toHaveURL(/\/company\/HMKB$/);
  await expect(card).toBeHidden();
  expect(errors).toEqual([]);
});

test('homepage preview supports keyboard access and keeps company name navigation separate', async ({ page }) => {
  await openHomepage(page);
  const table = page.locator('.landing-market');
  const trigger = table.getByRole('button', { name: 'Обзор компании GRBK', exact: true });
  await trigger.focus();
  await expect(preview(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(preview(page)).toBeHidden();
  await expect(trigger).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(preview(page).getByRole('link', { name: 'Открыть компанию', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await table.locator('.landing-company').filter({ hasText: 'GRBK' }).click();
  await expect(page).toHaveURL(/\/company\/GRBK$/);
  await expect(preview(page)).toBeHidden();
});

test('homepage preview shows failed history and retries on reopening', async ({ page }) => {
  await openHomepage(page);
  await page.route('**/api/price-history/MIQE?*', route => route.fulfill({ status: 503, json: { ok: false } }));
  const trigger = page.locator('.landing-market').getByRole('button', { name: 'Обзор компании MIQE', exact: true });
  await trigger.hover();
  await expect(preview(page)).toContainText('Не удалось загрузить график');
  await expect(preview(page).locator('[data-candle]')).toHaveCount(0);
  await expect(preview(page).locator('.company-preview-quote')).toContainText(/2\s*401/);
  await page.mouse.move(3, 3);
  await expect(preview(page)).toBeHidden();
  await page.unroute('**/api/price-history/MIQE?*');
  await trigger.hover();
  await expect(preview(page).getByRole('img', { name: /График цены MIQE/ })).toBeVisible();
});

test.describe('homepage touch previews', () => {
  test.use({ hasTouch: true });
  for (const surface of ['.landing-market', '.landing-company-example']) test(`homepage logo opens a chart on tap at ${surface}`, async ({ page }, testInfo) => {
    await openHomepage(page, { width: 320, theme: 'light' });
    await page.locator(surface).getByRole('button', { name: 'Обзор компании HMKB', exact: true }).tap();
    const card = preview(page);
    await expect(card.getByRole('img', { name: /График цены HMKB/ })).toBeVisible();
    const box = await card.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(8);
    expect(box.x + box.width).toBeLessThanOrEqual(312);
    expect(box.y).toBeGreaterThanOrEqual(8);
    expect(box.y + box.height).toBeLessThanOrEqual(992);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('homepage-preview-mobile.png') });
    await page.touchscreen.tap(3, 3);
    await expect(card).toBeHidden();
    await expect(page).toHaveURL(/\/$/);
  });
});

for (const role of [null, 'reader', 'analyst']) {
  for (const surface of ['market', 'homepage']) test(`${role || 'guest'} cannot open chart previews on ${surface}`, async ({ page }) => {
    const { requests } = await (surface === 'market' ? openBoard : openHomepage)(page, { role });
    if (role) await expect(page.getByRole('button', { name: `Аккаунт и настройки: ${role}@example.test` })).toBeVisible();
    const logos = surface === 'market' ? [logoFor(page, 'UNVB')] : [
      page.locator('.landing-market .chip-logo').first(),
      page.locator('.landing-company-example .chip-logo').first(),
    ];
    await page.clock.install();
    for (const logo of logos) {
      await logo.hover();
      await page.clock.runFor(1000);
      await expect(preview(page)).toHaveCount(0);
      await logo.click();
      await expect(preview(page)).toHaveCount(0);
    }
    await expect(page.locator('.company-preview-trigger')).toHaveCount(0);
    expect(requests).toEqual([]);
    const company = surface === 'market' ? rowFor(page, 'UNVB').getByRole('button', { name: 'UNVB', exact: true })
      : page.locator('.landing-market .landing-company').filter({ hasText: 'HMKB' });
    await company.click();
    await expect(page).toHaveURL(/\/company\/(UNVB|HMKB)$/);
  });
}

for (const surface of ['market', 'homepage']) test(`preview on ${surface} waits for admin authentication and disappears after logout`, async ({ page }) => {
  let release;
  const authenticated = new Promise(resolve => { release = resolve; });
  await (surface === 'market' ? openBoard : openHomepage)(page, { authenticate: () => authenticated });
  await expect(page.locator('.company-preview-trigger')).toHaveCount(0);
  release();
  const trigger = page.getByRole('button', { name: `Обзор компании ${surface === 'market' ? 'UNVB' : 'HMKB'}`, exact: true }).first();
  await trigger.focus();
  await expect(preview(page)).toBeVisible();
  await page.getByRole('button', { name: 'Аккаунт и настройки: administrator@example.test' }).click();
  await page.getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(preview(page)).toHaveCount(0);
  await expect(page.locator('.company-preview-trigger')).toHaveCount(0);
});

test('legacy administrator flag still enables chart previews', async ({ page }) => {
  await openBoard(page, { role: 'legacy-admin' });
  await logoFor(page, 'UNVB').hover();
  await expect(preview(page)).toBeVisible();
});
