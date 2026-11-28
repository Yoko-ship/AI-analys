import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const story = JSON.parse(readFileSync(new URL('../tests/fixtures/news-search.json', import.meta.url), 'utf8'));
const security = { ticker: 'UZTL', name: 'Uzbektelecom', company_name: 'Uzbektelecom', type: 'stock', last_price: 5000, close_price: 4900, trade_count: 2 };
const report = { ok: true, status: 'available', headline: 'UZTL verified analysis', paragraphs: ['A loaded analysis of the issuer.'],
  standard: 'nsbu', scope: 'separate', period: '2025Q4', language: 'en', version: 'report-v2', number_references: [] };

async function setup(page, { signedIn = false, receiptSink } = {}) {
  const actions = [], errors = [], state = { content: false, newsError: false, receiptRetries: 0, favorited: false, favoriteError: true };
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => { localStorage.setItem('uz_stock_analyzer_language', 'en'); sessionStorage.setItem('uz_sponsor_seen', '1'); });
  if (signedIn) await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'synthetic-token'));
  const user = { id: 23, full_name: 'Reader', email: 'reader@example.test' };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/track/actions') {
      actions.push(JSON.parse(route.request().postData()));
      if (receiptSink) return route.fulfill(receiptSink(actions.at(-1)));
      if (state.receiptRetries-- > 0) return route.fulfill({ status: 503, json: { detail: 'Retry later' } });
      return route.fulfill({ json: { ok: true } });
    }
    if (path === '/api/track') return route.fulfill({ status: 204 });
    if (path === '/api/auth/me') return route.fulfill(signedIn ? { json: { user } } : { status: 401, json: {} });
    if (path === '/api/profile') return route.fulfill({ json: { user, preferences: { language: 'en' }, stats: {}, security: {}, notes: [],
      favorites: state.favorited ? [{ ticker: 'HMKB', company_name: 'Hamkorbank' }] : [] } });
    if (path === '/api/favorites/toggle') {
      if (state.favoriteError) return route.fulfill({ status: 503, json: { detail: 'Could not save favourite' } });
      state.favorited = !state.favorited;
      return route.fulfill({ json: { ok: true, favorited: state.favorited } });
    }
    if (path === '/api/securities') return route.fulfill({ json: { ok: true, securities: { UZTL: security } } });
    if (path === '/api/securities/UZTL/info') return route.fulfill({ json: { ok: true, security } });
    if (path === '/api/market/stocks') return route.fulfill({ json: { stocks: [security, { ...security, ticker: 'HMKB', name: 'Hamkorbank' }] } });
    if (path.includes('/ai-report')) return route.fulfill(state.content ? { json: report } : { status: 503, json: { ok: false } });
    if (path === '/api/price-history/UZTL') return route.fulfill({ json: { ok: true, as_of: '2026-11-23', points: state.content ? [
      { date: '2026-11-20', open: 4800, high: 5000, low: 4700, close: 4900, volume: 100 },
      { date: '2026-11-23', open: 4900, high: 5100, low: 4800, close: 5000, volume: 200 }] : [] } });
    if (path === '/api/news/feed') return route.fulfill(state.newsError ? { status: 503, json: {} } : { json: { ok: true, items: [story] } });
    if (path.startsWith('/api/news/item/')) return route.fulfill(state.content ? { json: { ok: true, item: story, related: [] } } : { status: 404, json: { ok: false } });
    return route.fulfill({ json: { ok: true, items: [], companies: [], points: [], rows: [] } });
  });
  return { actions, errors, state };
}

test('tagged landings survive routing, retry once, and retain every new arrival in a session', async ({ page }) => {
  const { actions, errors, state } = await setup(page);
  state.content = true;
  const token = 'a'.repeat(32);
  state.receiptRetries = 1;
  await page.goto(`/company/UZTL?scope=separate&uz_pub=${token}&version=report-v2&utm_source=telegram#report`);
  await expect.poll(() => actions.filter(a => a.kind === 'publication_visit').length).toBeGreaterThan(0);
  const first = actions.find(a => a.kind === 'publication_visit');
  expect(first).toMatchObject({ publication_token: token,
    route_fingerprint: createHash('sha256').update(JSON.stringify(['/company/UZTL', [['scope', 'separate'], ['version', 'report-v2']], '#report'])).digest('hex') });
  expect(JSON.stringify(first)).not.toMatch(/utm_source|channel|destination_url/);
  await page.goto(`/company/UZTL?uz_pub=${'b'.repeat(32)}`);
  await expect.poll(() => actions.filter(a => a.publication_token === 'b'.repeat(32)).length).toBe(1);
  await page.goto(`/company/UZTL?uz_pub=${token}`);
  await expect.poll(() => new Set(actions.filter(a => a.publication_token === token).map(a => a.event_id)).size).toBe(2);
  expect(new Set(actions.filter(a => a.kind === 'publication_visit').map(a => a.session_id)).size).toBe(1);
  const before = actions.filter(a => a.kind === 'publication_visit').length;
  await page.goto(`/company/UZTL?uz_pub=invalid&email=private%40example.test`);
  await expect(page.locator('.company-price-chart')).toBeVisible();
  expect(actions.filter(a => a.kind === 'publication_visit')).toHaveLength(before);
  expect(errors).toEqual([]);
});

for (const width of [1440, 390]) test(`loaded product objects are observed after success at ${width}px`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 950 });
  const { actions, errors, state } = await setup(page);
  await page.goto('/company/UZTL?report=ai');
  await expect(page.getByText('The short AI insight is currently unavailable.')).toBeVisible();
  await expect.poll(() => actions.filter(a => a.kind === 'issuer_open').length).toBe(1);
  expect(actions.filter(a => ['report_open', 'chart_open'].includes(a.kind))).toEqual([]);
  state.content = true;
  state.receiptRetries = 1;
  await page.goto('/company/UZTL?report=ai');
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect.poll(() => actions.filter(a => a.kind === 'report_open').length).toBeGreaterThan(0);
  const opened = actions.find(a => a.kind === 'report_open');
  expect(opened).toMatchObject({ ticker: 'UZTL', standard: 'nsbu', scope: 'separate', period: '2025Q4', language: 'en', version: 'report-v2' });
  await page.getByRole('button', { name: 'Close AI financial report', exact: true }).click();
  await page.locator('.company-price-chart').scrollIntoViewIfNeeded();
  await expect.poll(() => actions.filter(a => a.kind === 'chart_open').length).toBe(1);
  await page.locator('.company-chart-wrap').screenshot({ path: info.outputPath(`product-chart-${width}.png`) });
  await page.goto(`/news/${story.id}`);
  await expect(page.locator('.led-art-title')).toBeVisible();
  await expect.poll(() => actions.filter(a => a.kind === 'news_open').length).toBe(1);
  expect(actions.find(a => a.kind === 'news_open').news_id).toBe(story.id);
  expect(actions.every(a => a.event_id && a.observed_at && a.visitor_id && a.session_id && !('uid' in a))).toBe(true);
  expect(errors).toEqual([]);
});

test('favourites are observed only after a successful add, never failure or removal', async ({ page }) => {
  const { actions, state } = await setup(page, { signedIn: true });
  await page.goto('/company/UZTL');
  const favorite = page.locator('.rail-row').filter({ hasText: 'HMKB' }).getByTitle('Add to favourites', { exact: true }).first();
  await favorite.click();
  await expect(page.getByText('Could not save favourite', { exact: true })).toBeVisible();
  expect(actions.filter(a => a.kind === 'favorite')).toEqual([]);
  state.favoriteError = false;
  await favorite.click();
  await expect.poll(() => actions.filter(a => a.kind === 'favorite').length).toBe(1);
  expect(actions.find(a => a.kind === 'favorite').ticker).toBe('HMKB');
  await page.locator('.rail-row').filter({ hasText: 'HMKB' }).getByTitle('Remove from favourites', { exact: true }).first().click();
  await expect(favorite).toBeVisible();
  expect(actions.filter(a => a.kind === 'favorite')).toHaveLength(1);
});

test('published tagged links and news actions persist through PostgreSQL and the real marketing reader', async ({ page }, info) => {
  test.setTimeout(90000);
  test.skip(!process.env.MARKETING_BROWSER_POSTGRES_URL, 'Requires disposable local PostgreSQL');
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const call = request => JSON.parse(execFileSync(python,
    ['-X', 'utf8', 'e2e/helpers/marketing-api.py', info.outputPath('product.sqlite3'), JSON.stringify(request)],
    { encoding: 'utf8', env: { ...process.env, PYTHONPATH: process.cwd() } }));
  const base = '/api/admin/ai-marketing/reports';
  const start = new Date(Date.now()-86400000).toISOString().slice(0,10);
  const end = new Date(Date.now()+2*86400000).toISOString().slice(0,10);
  try {
    expect(call({ method: 'WEBSITE_CONFIGURE' }).status).toBe(200);
    expect(call({ method: 'PUT', path: `${base}/settings`, body: { expected_version: 0, data: { dataset: 'test' } } }).status).toBe(200);
    call({ method: 'TELEGRAM_CONFIGURE' });
    const root = '/api/admin/ai-marketing', expires = new Date(Date.now()+86400000).toISOString();
    expect(call({ method: 'PUT', path: `${root}/accounts/tg`, body: { expected_version: 0, data: {
      platform: 'telegram', label: 'Tagged-link test', external_id: '-100123', mode: 'automatic', rubrics: ['news'], formats: ['post'], languages: ['ru'],
      valid_until: expires, window_start: '00:00', window_end: '23:59', min_interval_minutes: 1,
    } } }).status).toBe(200);
    expect(call({ method: 'POST', path: `${root}/accounts/tg/probe`, body: { expected_version: 1 } }).status).toBe(200);
    expect(call({ method: 'PUT', path: `${root}/evidence/news`, body: { expected_version: 0, data: {
      title: 'A verified product update', url: `https://uzstock.uz/news/${story.id}`, publisher: 'UZStock',
      published_at: new Date(Date.now()-3600000).toISOString(), retrieved_at: new Date(Date.now()-60000).toISOString(), expires_at: expires,
      excerpt: 'Доступно сравнение компаний.', rights: 'owned', status: 'verified', data: { feature: 'Сравнение компаний' },
    } } }).status).toBe(200);
    const material = call({ method: 'POST', path: `${root}/candidates`, body: {
      event_id: 'tracked-publication', account_id: 'tg', mode: 'automatic', rubric: 'news', language: 'ru', track_visits: true,
      title: 'Сравнение компаний', body: 'Доступно сравнение компаний.', evidence_ids: ['news'],
      destination_url: `https://uzstock.uz/news/${story.id}`, expires_at: expires,
    } }).body.item;
    expect(call({ method: 'POST', path: `${root}/candidates/${material.id}/check` }).body.item.status).toBe('ready');
    expect(call({ method: 'POST', path: `${root}/candidates/${material.id}/schedule` }).status).toBe(200);
    expect(call({ method: 'DISPATCH_TELEGRAM', at: new Date().toISOString() }).body.delivery_work).toBe(true);
    const delivery = call({ method: 'GET', path: `${root}/workspace` }).body.deliveries.find(item => item.candidate_id === material.id);
    expect(delivery.status).toBe('published');
    expect(JSON.stringify(delivery.dispatch_payload)).toContain(material.tracking.destination);
    const persisted = [];
    const { state } = await setup(page, { receiptSink: body => {
      const response = call({ method: 'POST', path: '/api/track/actions', body, headers: { 'User-Agent': 'UZStock acceptance browser' } });
      persisted.push(response);
      return { status: response.status, json: response.body };
    } });
    state.content = true;
    const landing = new URL(material.tracking.destination);
    await page.goto(landing.pathname + landing.search);
    await expect.poll(() => persisted.length).toBe(2);
    expect(persisted.every(result => result.status === 200 && result.body.ok)).toBe(true);
    expect(call({ method: 'PUT', path: `${base}/website`, body: { expected_version: 0,
      data: { enabled: true, dataset: 'test', starts_on: start, interval_minutes: 15 } } }).status).toBe(200);
    for (let i=0; i<3; i++) expect(call({ method: 'POST', path: `${base}/website/sync`, body: { expected_version: 1 } }).status).toBe(200);
    expect(call({ method: 'GET', path: '/api/admin/ai-marketing/workspace' }).body.website.runtime).toMatchObject({ status: 'waiting', imported: 5 });
    const calculated = call({ method: 'POST', path: `${base}/calculate`, body: { starts_on: start, ends_on: end } });
    expect(calculated.status).toBe(200);
    expect(calculated.body.report.event_count).toBe(5);
    expect(calculated.body.report.metrics.visits.status).toBe('incomplete');
    expect(calculated.body.report.publication_attribution.rows).toEqual([{
      publication_id: material.id, channel: 'telegram', promotion: 'organic', observed_arrivals: 1, attributed_registrations: 0,
    }]);
  } finally { call({ method: 'WEBSITE_CLEANUP' }); }
});

test('search excludes entered text and confirms a result only after its content loads', async ({ page }) => {
  const { actions, state, errors } = await setup(page);
  await page.goto('/news');
  const input = page.getByRole('searchbox', { name: 'Search news' });
  await input.fill('private@example.test');
  await expect.poll(() => actions.filter(a => a.kind === 'search_empty').length).toBe(1);
  await input.fill('IMAN');
  await expect.poll(() => actions.filter(a => a.kind === 'search').length).toBe(1);
  expect(actions.find(a => a.kind === 'search')).toMatchObject({ query_type: 'other', search_area: 'news_feed', result_count: 1 });
  state.content = true;
  await page.locator('.newsdesk-rows a').first().click();
  await expect.poll(() => actions.filter(a => a.kind === 'search_open').length).toBe(1);
  expect(actions.find(a => a.kind === 'search_open').news_id).toBe(story.id);
  expect(JSON.stringify(actions)).not.toContain('private');
  state.newsError = true;
  await page.goto('/news');
  await input.fill('unmatched');
  await expect(page.locator('.led-empty')).toBeVisible();
  expect(actions.filter(a => a.kind === 'search_empty')).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('unavailable observation APIs never prevent loaded content from rendering', async ({ page }) => {
  const { state, errors } = await setup(page);
  state.content = true;
  await page.addInitScript(() => { window.IntersectionObserver = undefined; });
  await page.goto('/company/UZTL?report=ai');
  await expect(page.getByRole('dialog')).toContainText('A loaded analysis of the issuer.');
  expect(errors).toEqual([]);
});

test('a failed search destination cannot claim a later direct open', async ({ page }) => {
  const { state, actions } = await setup(page);
  await page.goto('/news');
  const input = page.getByRole('searchbox', { name: 'Search news' });
  await input.fill('IMAN');
  await expect.poll(() => actions.filter(a => a.kind === 'search').length).toBe(1);
  await page.locator('.newsdesk-rows a').first().click();
  await expect(page.locator('.led-empty')).toBeVisible();
  expect(actions.filter(a => a.kind === 'search_open')).toHaveLength(0);
  state.content = true;
  await page.locator('.led-back').click();
  await expect(input).toHaveValue('');
  await page.locator('.newsdesk-rows a').first().click();
  await expect.poll(() => actions.filter(a => a.kind === 'news_open').length).toBe(1);
  expect(actions.filter(a => a.kind === 'search_open')).toHaveLength(0);
});
