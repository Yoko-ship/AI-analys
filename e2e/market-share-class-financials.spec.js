import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

async function openBoard(page, columns, theme = 'light') {
  const fixture = JSON.parse(readFileSync('tests/fixtures/uztl_share_classes.json', 'utf8'));
  // Exercise the real cache reader and API scaling; the browser receives their
  // output, not a fixture that already assumes the share classes agree.
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const financials = JSON.parse(execFileSync(python, ['-c', `
import asyncio, dbx, json, os, tempfile
from pathlib import Path
from unittest.mock import patch
from catalogue import financial_store, read_batch
from server.market.routes import api_market_financials, api_market_ratios
fixture = json.loads(Path('tests/fixtures/uztl_share_classes.json').read_text())
with tempfile.TemporaryDirectory() as directory:
    os.environ['CATALOG_DB_PATH'] = directory + '/catalog.db'
    os.environ['FINANCIALS_ENRICH_ON_READ'] = '0'
    financial_store.bulk_upsert_financials(fixture['rows'])
    with patch.object(read_batch, 'securities', return_value=fixture['securities']), \\
         patch.object(financial_store, '_maybe_seed_financials'), \\
         patch('catalogue.refresh.refresh_financials_cache'):
        print(json.dumps({'financials': asyncio.run(api_market_financials()),
                          'ratios': asyncio.run(api_market_ratios())}))
    # Release pooled SQLite handles before Windows removes the temporary DB.
    dbx.reset_pools()
`], { encoding: 'utf8' }));
  const stocks = Object.entries(fixture.securities).map(([ticker, security]) => ({
    ...security, ticker, name: 'Uzbektelecom', last_price: ticker === 'UZTL' ? 20980 : 12680,
    close_price: 12000, volume: 1000000, quantity: 1000, trade_count: 4,
    last_trade_date: '2026-10-28', industry: 'telecom',
  }));
  await page.addInitScript(({ columns, theme }) => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_track_internal', '1');
    localStorage.setItem('uz_market_cols_v3', JSON.stringify(columns));
    localStorage.setItem('uz_stock_analyzer_theme', theme);
  }, { columns, theme });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/companies') return json({ companies: stocks.map(r => ({ ...r, company_name: r.name })) });
    if (path === '/api/securities') return json({ ok: true, securities: fixture.securities });
    if (path === '/api/market/stocks') return json({ stocks });
    if (path === '/api/market/financials') return json(financials.financials);
    if (path === '/api/market/ratios') return json(financials.ratios);
    if (path === '/api/market/trade-stats') return json({ ok: true, stats: {} });
    if (path === '/api/market/multiples') return json({ ok: true, items: [] });
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: { user: null } });
    return json({ ok: true });
  });
  await page.goto('/market');
  const rows = page.locator('.market-table tbody tr');
  await expect(rows).toHaveCount(2);
  return rows;
}

test('ordinary and preferred shares show the latest issuer filing with their own prices', async ({ page }) => {
  const rows = await openBoard(page, ['finRevenue', 'finCash']);
  for (const ticker of ['UZTL', 'UZTLP']) {
    const row = rows.filter({ has: page.getByText(ticker, { exact: true }) });
    await expect(row).toContainText('2026 Q3');
    await expect(row).not.toContainText('2026 Q2');
    await expect(row).toContainText(/8[,.]8\s*трлн/);
    await expect(row).toContainText(/4[,.]5\s*млрд/);
    await expect(row).toContainText(ticker === 'UZTL' ? /20\s*980/ : /12\s*680/);
  }
});

for (const theme of ['light', 'dark']) test(`issuer coefficients have no help markers beside values (${theme})`, async ({ page }, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const columns = ['currentRatio', 'quickRatio', 'debtAssets', 'assetTurnover', 'roce'];
  const rows = await openBoard(page, columns, theme);
  for (const ticker of ['UZTL', 'UZTLP']) {
    const row = rows.filter({ has: page.getByText(ticker, { exact: true }) });
    await expect(row).toContainText(/0[,.]78/);
    await expect(row).toContainText(/0[,.]55/);
    await expect(row).toContainText(/75[,.]7%/);
    await expect(row).toContainText(/0[,.]65/);
    await expect(row).toContainText(/0[,.]18/);
    await expect(row.locator('.fin-cell-period')).toHaveCount(5);
    for (const cell of await row.locator('.fin-cell-period').all()) await expect(cell).toContainText('2026Q3');
    await expect(row).toContainText('год.');
    await expect(row.locator('.term-info-btn')).toHaveCount(0);
    await expect(row).not.toContainText('!');
  }
  for (const column of columns) {
    await expect(page.locator(`.market-table th[data-sort-key="${column}"] .term-info-btn`)).toHaveCount(1);
  }
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('button', { name: /Экспорт CSV/ }).click(),
  ]);
  const csv = readFileSync(await download.path(), 'utf8');
  expect(csv).toContain('2026Q3');
  expect(csv).toContain('× 12 / 9');
  expect(csv).toContain('Операционная прибыль / (Активы - Текущие обязательства)');
  expect(csv).toContain('тыс. сум');
  await rows.first().locator('td').last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('coefficients-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(rows.locator('.term-info-btn')).toHaveCount(0);
  const marker = page.locator('.market-table th[data-sort-key="roce"] .term-info-btn');
  await marker.scrollIntoViewIfNeeded();
  await marker.click();
  const tip = page.getByRole('tooltip');
  await expect(tip).toBeVisible();
  await expect(tip).toHaveCSS('opacity', '1');
  const box = await tip.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  await page.keyboard.press('Escape');
  await expect(tip).toBeHidden();
  await page.screenshot({ path: testInfo.outputPath('coefficients-mobile.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});
