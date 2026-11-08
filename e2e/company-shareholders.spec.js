import {test, expect} from '@playwright/test';

const ownership = {
  status: 'disclosed', as_of: '2025-12-31', share_class: 'ownership_interest',
  source: {url: 'https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf', page: 13},
  items: [
    {name: 'Ibragimov Ikram', share: '59.21', kind: 'individual'},
    {name: 'Nederlandse Financierings-Maatschappij Voor Ontwikkelingslanden n.v. (FMO)', share: '14.55', kind: 'entity'},
    {name: 'Others, individually owning less than 1%', share: '4.53', kind: 'aggregate'},
  ],
};
const management = {
  status: 'disclosed', as_of: '2026-10-28', source: {url: 'https://openinfo.uz/ru/facts/8/15218'},
  items: [{name: 'Сентпетери Адам', position: 'Председатель Правления', source_url: 'https://openinfo.uz/ru/facts/8/15218'},
    {name: 'Мартон Миклош Ратки', position: 'Заместитель председателя правления', source_url: 'https://openinfo.uz/ru/facts/8/15218'}],
};
const empty = {status: 'unavailable', items: []};

async function setup(page, respond = () => ({ok: true, ownership, management})) {
  const requests = [];
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_theme', 'light'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (path.endsWith('/shareholders')) {
      requests.push(path);
      const result = await respond(path, requests.length);
      return json(result, result.ok === false ? 503 : 200);
    }
    const security = {ticker: 'HMKB', name: 'Hamkorbank', security_type: 'stock', last_price: 118};
    if (path === '/api/securities') return json({ok: true, securities: {HMKB: security}});
    if (path === '/api/market/stocks') return json({stocks: [security]});
    if (path.endsWith('/info')) return json({ok: true, security, wiki: {}});
    if (path.includes('/price-history/')) return json({ok: true, points: [], adjustments: []});
    if (path.endsWith('/reports')) return json({ok: true, reports: [], ratios: {}});
    if (path === '/api/auth/me') return json({user: null}, 401);
    return json({ok: true, items: [], series: {}, quality: {}});
  });
  return requests;
}

test('direct company tab loads on demand and shows compact source-linked cards', async ({page}, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = await setup(page);
  await page.goto('/company/HMKB');
  const tab = page.getByRole('button', {name: 'Акционеры', exact: true});
  await expect(tab).toBeVisible();
  expect(requests).toHaveLength(0);
  await tab.focus();
  await page.keyboard.press('Enter');
  const panel = page.getByTestId('company-shareholders');
  await expect(panel.getByRole('heading', {name: 'Акционеры', exact: true})).toBeVisible();
  await expect(panel.getByRole('heading', {name: 'Руководство', exact: true})).toBeVisible();
  await expect(panel).toContainText('59,21%');
  await expect(panel).toContainText('31.12.2025');
  await expect(panel).toContainText('28.10.2026');
  await expect(panel.getByRole('link', {name: 'Ibragimov Ikram'})).toHaveAttribute('href', `${ownership.source.url}#page=13`);
  await expect(panel).toContainText('Председатель Правления');
  const cards = panel.locator('.shareholder-card');
  const left = await cards.nth(0).boundingBox(), right = await cards.nth(1).boundingBox();
  expect(right.x).toBeGreaterThan(left.x + left.width);
  expect(Math.abs(left.y - right.y)).toBeLessThan(2);
  await expect(page.locator('body')).toHaveAttribute('data-theme', 'light');
  await panel.screenshot({path: testInfo.outputPath('shareholders-light.png')});
  await page.evaluate(() => {document.body.dataset.theme = 'dark';});
  await panel.screenshot({path: testInfo.outputPath('shareholders-dark.png')});
  await page.setViewportSize({width: 390, height: 844});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const mobileLeft = await cards.nth(0).boundingBox(), mobileRight = await cards.nth(1).boundingBox();
  expect(mobileRight.y).toBeGreaterThan(mobileLeft.y + mobileLeft.height);
  await panel.screenshot({path: testInfo.outputPath('shareholders-mobile.png')});
  expect(requests).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('deep link shows independently missing ownership without hiding management', async ({page}) => {
  await setup(page, () => ({ok: true, ownership: empty, management: {...management, status: 'partial'}}));
  await page.goto('/company/IPTB?tab=shareholders');
  const panel = page.getByTestId('company-shareholders');
  await expect(panel).toContainText('Нет проверенных данных о долях акционеров');
  await expect(panel).toContainText('Сентпетери Адам');
  await expect(panel).toContainText('Состав может быть неполным');
  await expect(panel).not.toContainText('0%');
});

test('failed request is visible and retryable; empty management is explicit', async ({page}) => {
  await setup(page, (_path, count) => count === 1 ? {ok: false} : {ok: true, ownership, management: empty});
  await page.goto('/company/HMKB?tab=shareholders');
  const panel = page.getByTestId('company-shareholders');
  await expect(panel.getByRole('alert')).toContainText('Не удалось загрузить');
  await panel.getByRole('button', {name: 'Повторить'}).click();
  await expect(panel).toContainText('Ibragimov Ikram');
  await expect(panel).toContainText('Нет проверенных данных о руководстве');
});

test('loading state never displays fabricated data', async ({page}) => {
  let release;
  const waiting = new Promise(resolve => {release = resolve;});
  await setup(page, async () => {await waiting; return {ok: true, ownership: empty, management: empty};});
  await page.goto('/company/HMKB?tab=shareholders');
  const panel = page.getByTestId('company-shareholders');
  await expect(panel.getByRole('status')).toContainText('Загрузка');
  await expect(panel.locator('.shareholder-card')).toHaveCount(0);
  release();
  await expect(panel.locator('.shareholder-card')).toHaveCount(2);
});

test('an issuer-hosted approved report is not labelled as Openinfo', async ({page}) => {
  await setup(page, () => ({ok: true, ownership: {...ownership, source: {url: 'https://bank.example/annual.pdf', page: 13}}, management: empty}));
  await page.goto('/company/HMKB?tab=shareholders');
  const source = page.getByTestId('company-shareholders').locator('.shareholder-source a');
  await expect(source).toContainText('Источник');
  await expect(source).toHaveAttribute('href', 'https://bank.example/annual.pdf#page=13');
});
