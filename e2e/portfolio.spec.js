import { test, expect } from '@playwright/test';

const user = { id: 99, full_name: 'Portfolio Investor', email: 'portfolio@example.test', pro_access: true, tier: 'pro' };
const empty = { ok: true, items: [], transactions: [], instruments: [{ ticker: 'AGBA', name: 'Agrobank' }],
  count: 0, priced_count: 0, valuation_complete: true, market_value: '0', cost_value: '0',
  unrealized_pnl: '0', realized_pnl: '0', dividend_income: '0', total_pnl: '0',
  checked_at: '2026-10-22T06:00:00Z', refresh_interval_seconds: 30 };
const transaction = { id: 'one', sequence: 1, ticker: 'AGBA', kind: 'buy', trade_date: '2026-10-20',
  quantity: '100', price: '500', fees: '100', amount: '0', note: '', version: 1 };
function held(price = '589') {
  return { ...empty, count: 1, priced_count: 1, market_value: String(Number(price) * 100), cost_value: '50100',
    unrealized_pnl: String(Number(price) * 100 - 50100), total_pnl: String(Number(price) * 100 - 50100),
    transactions: [transaction], items: [{ ticker: 'AGBA', company_name: 'Agrobank', quantity: '100',
      average_cost: '501', cost_value: '50100', last_price: price, price_date: '2026-10-21', days_since_trade: 1,
      market_value: String(Number(price) * 100), unrealized_pnl: String(Number(price) * 100 - 50100),
      unrealized_pnl_pct: '17.56', allocation_pct: '100', valuation_status: 'AVAILABLE' }] };
}
async function setup(page, initial = empty, { pro = true, signedIn = true } = {}) {
  const state = { data: initial, writes: [], reads: 0, marketReads: 0, failRead: false, failWrite: false };
  await page.addInitScript(({ signedIn }) => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    if (signedIn) localStorage.setItem('uz_stock_analyzer_token', 'portfolio-test');
  }, { signedIn });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const send = (body, status = 200) => route.fulfill({ status, json: body });
    if (path === '/api/auth/me') return send({ user: { ...user, pro_access: pro } });
    if (path === '/api/profile') return send({ ok: true, user: { ...user, pro_access: pro }, stats: {},
      preferences: { language: 'en' }, favorites: [], recent_analyses: [], security: {} });
    if (path === '/api/portfolio') {
      state.reads++;
      return state.failRead ? send({ detail: 'Unavailable' }, 503) : send(state.data);
    }
    if (path.startsWith('/api/portfolio/transactions')) {
      const body = route.request().postDataJSON();
      state.writes.push({ method: route.request().method(), body });
      if (state.failWrite) return send({ detail: { code: 'INSUFFICIENT_SHARES' } }, 422);
      state.data = route.request().method() === 'DELETE' ? empty : held();
      return send({ ok: true, transaction: { ...transaction, ...body } });
    }
    if (path === '/api/market/stocks') { state.marketReads++; return send({ stocks: [] }); }
    if (path === '/api/companies') return send({ companies: [] });
    return send({ ok: true, items: [] });
  });
  return state;
}

test('record a purchase with fees, inspect holdings, edit and remove the record', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/portfolio');
  await expect(page.getByRole('heading', { name: 'Portfolio', exact: true })).toBeVisible();
  await expect(page.getByText('No investments recorded yet')).toBeVisible();
  expect(state.marketReads).toBe(0);
  await page.getByRole('button', { name: 'Record transaction', exact: true }).click();
  await page.getByLabel('Ticker', { exact: true }).fill('AGBA');
  await page.getByLabel('Quantity', { exact: true }).fill('100');
  await page.getByLabel('Price per share, UZS', { exact: true }).fill('500');
  await page.getByLabel('Fees, UZS', { exact: true }).fill('100');
  await page.getByRole('button', { name: 'Save transaction', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Holdings' }).getByText('AGBA', { exact: true })).toBeVisible();
  expect(state.writes[0].body).toMatchObject({ kind: 'buy', quantity: '100', price: '500', fees: '100' });
  await expect(page.getByTestId('portfolio-market-value')).toContainText('58,900');
  await expect(page.getByRole('table', { name: 'Holdings' })).toContainText('2026-10-21');
  await page.getByRole('button', { name: 'Edit AGBA transaction' }).click();
  await expect(page.getByLabel('Fees, UZS', { exact: true })).toHaveValue('100');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Delete AGBA transaction' }).click();
  await page.getByRole('button', { name: 'Confirm deletion' }).click();
  await expect(page.getByText('No investments recorded yet')).toBeVisible();
});

test('prices update automatically and a failed refresh retains the last snapshot', async ({ page }) => {
  const state = await setup(page, held());
  await page.clock.install();
  await page.goto('/portfolio');
  await expect(page.getByTestId('portfolio-market-value')).toContainText('58,900');
  state.data = held('600');
  await page.clock.runFor(31_000);
  await expect(page.getByTestId('portfolio-market-value')).toContainText('60,000');
  state.failRead = true;
  await page.clock.runFor(31_000);
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByTestId('portfolio-market-value')).toContainText('60,000');
  await page.getByRole('button', { name: 'Record transaction', exact: true }).click();
  await page.getByLabel('Ticker', { exact: true }).fill('AG');
  state.failRead = false;
  await page.clock.runFor(31_000);
  await expect(page.getByLabel('Ticker', { exact: true })).toHaveValue('AG');
});

test('unknown valuations remain missing and do not look like a zero-valued portfolio', async ({ page }) => {
  const data = held();
  Object.assign(data, { market_value: null, total_pnl: null, unrealized_pnl: null, priced_count: 0, valuation_complete: false });
  Object.assign(data.items[0], { last_price: null, market_value: null, unrealized_pnl: null, unrealized_pnl_pct: null,
    valuation_status: 'NO_DATA', price_date: null, allocation_pct: null });
  await setup(page, data);
  await page.goto('/portfolio');
  await expect(page.getByTestId('portfolio-market-value')).toHaveText('—');
  await expect(page.getByText('No confirmed price', { exact: true })).toBeVisible();
  await expect(page.getByText('Some holdings have no confirmed price. Portfolio totals are incomplete.')).toBeVisible();
});

test('failed writes keep the form and show a helpful validation error', async ({ page }) => {
  const state = await setup(page, held());
  state.failWrite = true;
  await page.goto('/portfolio');
  await page.getByRole('button', { name: 'Record transaction', exact: true }).click();
  await page.getByLabel('Transaction type').selectOption('sell');
  await page.getByLabel('Ticker', { exact: true }).fill('AGBA');
  await page.getByLabel('Quantity', { exact: true }).fill('200');
  await page.getByLabel('Price per share, UZS', { exact: true }).fill('500');
  await page.getByRole('button', { name: 'Save transaction', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Not enough shares on that date');
  await expect(page.getByLabel('Quantity', { exact: true })).toHaveValue('200');
});

for (const [name, viewport] of [['desktop', { width: 1440, height: 1000 }], ['phone', { width: 390, height: 844 }]]) {
  test(`portfolio is accessible from the account menu and fits ${name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await setup(page, held());
    await page.goto('/market');
    await page.getByRole('button', { name: /Account:/ }).click();
    await page.getByRole('menuitem', { name: 'Portfolio', exact: true }).click();
    await expect(page).toHaveURL(/\/portfolio$/);
    await expect(page.getByTestId('portfolio-market-value')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: `test-results/portfolio-${name}.png`, fullPage: true });
  });
}

test('free and signed-out accounts do not fetch private holdings', async ({ page }) => {
  const state = await setup(page, empty, { pro: false });
  await page.goto('/portfolio');
  await expect(page.getByRole('heading', { name: 'Portfolio', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Record transaction', exact: true })).toHaveCount(0);
  expect(state.reads).toBe(0);
});
