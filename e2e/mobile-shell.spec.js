import { test, expect } from '@playwright/test';

// Phone layout of the shell and the quotes board, as measured on prod at 390px
// (2026-10-10): the topbar ran 25px off the right edge once «Войти» joined it,
// the «Колонки» label spilled out of its icon box, the period chips folded into
// two ragged rows and the ticker cell (a flex <td>) stopped matching its row.

async function mockBoard(page, theme = 'dark') {
  const stocks = Array.from({ length: 12 }, (_, i) => ({
    ticker: `TST${i}`, name: `Test company ${i}`, isin: `UZ00000000${i}`, type: 'stock',
    share_type: i % 3 ? 'ordinary' : 'preferred', price: 1000 + i, last_price: 1000 + i,
    change: 10, changePercent: 1, volume: 100000,
  }));
  const securities = Object.fromEntries(stocks.map(s => [s.ticker, { ...s, sector: 'finance', security_type: 'stock' }]));
  await page.route('**/api/**', route => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, json: body });
    if (p === '/api/securities') return json({ ok: true, securities });
    if (p === '/api/market/stocks') return json({ ok: true, stocks });
    if (p === '/api/auth/me') return json({ user: null }, 401);
    return json({});
  });
  await page.addInitScript((t) => { try { sessionStorage.setItem('uz_sponsor_seen', '1'); localStorage.setItem('uz_stock_analyzer_theme', t); } catch (e) { /* ignore */ } }, theme);
}

// The light theme is its own case: its select brought back the native arrow.
for (const [width, theme] of [[320, 'dark'], [360, 'dark'], [390, 'dark'], [390, 'light']]) {
  test(`phone shell and board fit ${width}px (${theme})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await mockBoard(page, theme);
    await page.goto('/market');
    await expect(page.locator('.market-table-wrap tbody tr').first()).toBeVisible();

    // Every visible topbar control lies inside the screen.
    const overhang = await page.evaluate(() => [...document.querySelectorAll('.topbar > *, .topbar-controls > *')]
      .map(el => el.getBoundingClientRect())
      .filter(r => r.width > 0 && r.right > 0)
      .filter(r => r.left < 0 || r.right > document.documentElement.clientWidth).length);
    expect(overhang).toBe(0);
    if (width >= 360) expect((await page.locator('.topbar-brand').boundingBox()).width).toBeGreaterThanOrEqual(30);
    await expect(page.locator('.theme-toggle')).toBeInViewport({ ratio: 1 });

    // Toolbar buttons are icon-only on a phone.
    const colsBox = await page.locator('.market-cols-btn').boundingBox();
    expect(colsBox.width).toBeLessThanOrEqual(40);
    await expect(page.locator('.market-cols-btn .market-btn-label')).toBeHidden();

    // The period chips stay on one line.
    const tops = await page.locator('.market-period-control button').evaluateAll(bs => bs.map(b => Math.round(b.getBoundingClientRect().top)));
    expect(new Set(tops).size).toBe(1);

    // The pinned ticker cell is as tall as its row.
    const [rowH, cellH] = await page.locator('.market-table-wrap tbody tr').first().evaluate(r => [r.getBoundingClientRect().height, r.cells[0].getBoundingClientRect().height]);
    expect(Math.abs(rowH - cellH)).toBeLessThanOrEqual(1);
  });
}

test('phone drawer carries the text-size control', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBoard(page);
  await page.goto('/market');
  await expect(page.locator('.topbar-controls .topbar-textsize')).toBeHidden();
  await page.locator('.topbar-burger').click();
  const drawerSize = page.locator('.topbar-nav-textsize');
  await expect(drawerSize).toBeVisible();
  await drawerSize.getByRole('button', { name: 'Увеличить шрифт' }).click();
  await expect(drawerSize.locator('.topbar-textsize-now')).not.toHaveText('100%');
  await drawerSize.locator('.topbar-textsize-now').click();
  await expect(drawerSize.locator('.topbar-textsize-now')).toHaveText('100%');
});
