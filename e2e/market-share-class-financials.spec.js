import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

test('ordinary and preferred shares show the latest issuer filing with their own prices', async ({ page }) => {
  const fixture = JSON.parse(readFileSync('tests/fixtures/uztl_share_classes.json', 'utf8'));
  // Exercise the real cache reader and API scaling; the browser receives their
  // output, not a fixture that already assumes the share classes agree.
  const financials = JSON.parse(execFileSync('.venv/bin/python', ['-c', `
import asyncio, json, os, tempfile
from pathlib import Path
from unittest.mock import patch
from catalogue import financial_store, read_batch
from server.market.routes import api_market_financials
fixture = json.loads(Path('tests/fixtures/uztl_share_classes.json').read_text())
with tempfile.TemporaryDirectory() as directory:
    os.environ['CATALOG_DB_PATH'] = directory + '/catalog.db'
    os.environ['FINANCIALS_ENRICH_ON_READ'] = '0'
    financial_store.bulk_upsert_financials(fixture['rows'])
    with patch.object(read_batch, 'securities', return_value=fixture['securities']), \\
         patch.object(financial_store, '_maybe_seed_financials'), \\
         patch('catalogue.refresh.refresh_financials_cache'):
        print(json.dumps(asyncio.run(api_market_financials())))
`], { encoding: 'utf8' }));
  const stocks = Object.entries(fixture.securities).map(([ticker, security]) => ({
    ...security, ticker, name: 'Uzbektelecom', last_price: ticker === 'UZTL' ? 20980 : 12680,
    close_price: 12000, volume: 1000000, quantity: 1000, trade_count: 4,
    last_trade_date: '2026-10-28', industry: 'telecom',
  }));
  await page.addInitScript(() => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_track_internal', '1');
    localStorage.setItem('uz_market_cols_v3', JSON.stringify(['finRevenue', 'finCash']));
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    const json = body => route.fulfill({ json: body });
    if (path === '/api/companies') return json({ companies: stocks.map(r => ({ ...r, company_name: r.name })) });
    if (path === '/api/securities') return json({ ok: true, securities: fixture.securities });
    if (path === '/api/market/stocks') return json({ stocks });
    if (path === '/api/market/financials') return json(financials);
    if (path === '/api/market/trade-stats') return json({ ok: true, stats: {} });
    if (path === '/api/market/multiples') return json({ ok: true, items: [] });
    if (path === '/api/auth/me') return route.fulfill({ status: 401, json: { user: null } });
    return json({ ok: true });
  });
  await page.goto('/market');
  const rows = page.locator('.market-table tbody tr');
  await expect(rows).toHaveCount(2);
  for (const ticker of ['UZTL', 'UZTLP']) {
    const row = rows.filter({ has: page.getByText(ticker, { exact: true }) });
    await expect(row).toContainText('2026 Q3');
    await expect(row).not.toContainText('2026 Q2');
    await expect(row).toContainText(/8[,.]8\s*трлн/);
    await expect(row).toContainText(/4[,.]5\s*млрд/);
    await expect(row).toContainText(ticker === 'UZTL' ? /20\s*980/ : /12\s*680/);
  }
});
