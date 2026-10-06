import { test, expect } from '@playwright/test';

for (const [ticker, width, price] of [['UZMK', 320, 6800], ['UNVB', 390, 8200], ['IPTB', 430, 3.23]]) {
  test(`${ticker}: mobile chart fits ${width}px and keeps its menus usable`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const history = Array.from({ length: 260 }, (_, i) => {
      const day = new Date(Date.now() - (260 - i) * 864e5).toISOString().slice(0, 10);
      const close = price * (1 + Math.sin(i / 12) * 0.05);
      return { date: day, open: close * 0.99, close, high: close * 1.01, low: close * 0.98, value: 1000000 + i * 1000 };
    });
    const security = { name: `${ticker} company`, company_name: `${ticker} company`, security_type: 'stock', sector: 'finance', last_price: price, close_price: price };
    const stocks = Array.from({ length: 16 }, (_, i) => ({ ...security, ticker: `PEER${i}`, price }));
    const securities = Object.fromEntries(stocks.map(s => [s.ticker, s]));
    securities[ticker] = security;
    await page.route('**/api/**', route => {
      const p = new URL(route.request().url()).pathname;
      const json = (body, status = 200) => route.fulfill({ status, json: body });
      if (p === '/api/securities') return json({ ok: true, securities });
      if (p === '/api/market/stocks') return json({ ok: true, stocks });
      if (p === `/api/price-history/${ticker}`) return json({ ok: true, points: history, adjustments: [] });
      if (p === `/api/company/${ticker}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
      if (p === `/api/securities/${ticker}/info`) return json({ ok: true, security });
      if (p === '/api/auth/me') return json({ user: null }, 401);
      return json({});
    });
    await page.goto(`/chart/${ticker}?type=candle&range=1y`);
    const chart = page.locator('.ac-canvas');
    await expect(chart).toBeVisible();
    await expect(chart).toHaveAttribute('data-panes', '2');
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect((await page.locator('.ac-toolbar').boundingBox()).height).toBeLessThanOrEqual(150);
    // Price is the primary pane; volume must not consume half the phone chart.
    const paneHeights = await chart.locator('tr').evaluateAll(rows => rows.map(r => r.getBoundingClientRect().height).filter(h => h > 40));
    expect(paneHeights).toHaveLength(2);
    expect(paneHeights[0]).toBeGreaterThan(paneHeights[1] * 2.5);
    await expect.poll(async () => Number(await chart.getAttribute('data-visible-bars'))).toBeGreaterThan(200);
    // A long collapsed watchlist must not leave a blank area below the plot.
    await expect.poll(() => page.locator('.ac-rail-row').count()).toBeGreaterThan(8);
    const plotBox = await page.locator('.ac-plot').boundingBox();
    const detailsBox = await page.locator('.ac-details').boundingBox();
    expect(detailsBox.y - plotBox.y - plotBox.height).toBeLessThanOrEqual(12);
    await page.locator('.ac-rail-toggle').click();
    await expect(page.locator('.ac-rail-search')).toBeVisible();
    await page.locator('.ac-rail-toggle').click();

    for (const label of ['Индикаторы', 'Паттерны', 'Финансы']) {
      await page.locator('.ac-menus').getByRole('button', { name: label }).click();
      const menu = page.locator('.ac-toolbar .ac-menu');
      await expect(menu).toBeVisible();
      const box = await menu.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      await page.keyboard.press('Escape');
    }
    // The duplicate icon row is hidden, but all chart types remain selectable.
    await page.getByTestId('advanced-chart-tool-strip').getByRole('button', { name: 'Вид графика' }).click();
    await page.locator('.ac-menu').getByRole('button', { name: 'Линия', exact: true }).click();
    await expect(chart).toHaveAttribute('data-chart-type', 'line');
    await page.keyboard.press('Escape');
    await page.locator('.ac-range-custom').click();
    await expect(page.locator('.ac-span-menu input')).toHaveCount(2);
    const dateBox = await page.locator('.ac-span-menu').boundingBox();
    expect(dateBox.x + dateBox.width).toBeLessThanOrEqual(width);
    await page.keyboard.press('Escape');

    await page.getByRole('button', { name: 'Развернуть график на весь экран' }).click();
    await expect(page.locator('.advanced-chart')).toHaveClass(/is-fullscreen/);
    await expect(chart).toBeVisible();
    const fullBox = await chart.boundingBox();
    expect(fullBox.width).toBeLessThanOrEqual(width);
    expect(fullBox.height).toBeGreaterThanOrEqual(295);
    await page.keyboard.press('Escape');
    await expect(page.locator('.advanced-chart')).not.toHaveClass(/is-fullscreen/);
    await page.screenshot({ path: testInfo.outputPath(`mobile-${ticker}-${width}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
