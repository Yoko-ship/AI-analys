import {test, expect} from '@playwright/test';
import {setupCatalogPages} from './helpers/catalog-pages.js';

const tab = (page, code) => page.locator('.terminal-tab').filter({has:page.locator('strong', {hasText:new RegExp(`^${code}$`)})});
const ready = page => expect(page.locator('.catalog-layout [role="status"]').filter({hasText:/Загрузка/})).toHaveCount(0);

test('company search leaves the loaded HMKB financial table alone and metric filtering reuses its formatter', async ({page}) => {
  await page.addInitScript(() => {
    window.numberWork = {construct:0, format:0};
    Intl.NumberFormat = new Proxy(Intl.NumberFormat, {
      construct(target, args) {
        window.numberWork.construct++;
        const formatter = Reflect.construct(target, args);
        return new Proxy(formatter, {get(target, key) {
          if (key === 'format') return value => {window.numberWork.format++; return formatter.format(value);};
          return Reflect.get(target, key, target);
        }});
      },
    });
  });
  await setupCatalogPages(page);
  await expect(page.locator('.financial-columns')).toHaveAttribute('aria-busy', 'false');
  await ready(page);
  const before = await page.evaluate(() => ({...window.numberWork}));
  const table = await page.locator('.fc-table').innerText();
  await page.getByRole('combobox', {name:'Поиск компании', exact:true}).pressSequentially('Hamkorbank');
  await expect(page.locator('.catalog-company-item')).toHaveCount(1);
  expect(await page.locator('.fc-table').innerText()).toBe(table);
  expect(await page.evaluate(() => window.numberWork)).toEqual(before);
  await page.getByRole('searchbox', {name:'Поиск показателя', exact:true}).fill('Итого процентных доходов');
  await expect(page.locator('.fc-table tbody tr:not(.fc-group)')).toHaveCount(1);
  expect(await page.evaluate(() => window.numberWork.construct)).toBe(before.construct);
});

test('sync invalidates displayed financial data and a failed read remains retryable', async ({page}) => {
  let calls = 0, fail = true;
  await setupCatalogPages(page, {beforeNavigate:() => page.route('**/financials/columns?*', async route => {
    calls++;
    if (fail) {fail = false; return route.fulfill({status:503, json:{detail:'Unavailable'}});}
    await route.fallback();
  })});
  await page.getByRole('button', {name:'Повторить', exact:true}).click();
  await expect(page.locator('.fc-table')).toBeVisible();
  expect(calls).toBe(2);
  await page.getByRole('button', {name:'Обновить', exact:true}).click();
  await expect(page.getByText('Обновлено', {exact:true})).toBeVisible();
  await expect(page.locator('.financial-columns')).toHaveAttribute('aria-busy', 'false');
  await expect(page.locator('.fc-table')).toBeVisible();
  expect(calls).toBe(3);
});

test('a late index response cannot replace the newly selected issuer', async ({page}) => {
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  try {
    await setupCatalogPages(page, {beforeNavigate:() => page.route('**/api/catalog/index/HMKB', async route => {
      await gate; await route.fallback();
    })});
    await page.locator('.catalog-company-item').filter({hasText:'AGBA'}).click();
    await expect(page.locator('.catalog-company-identity h2')).toHaveText('Агробанк');
    const oldResponse = page.waitForResponse('**/api/catalog/index/HMKB');
    release(); await oldResponse;
    await ready(page);
    await expect(page.locator('.catalog-company-identity h2')).toHaveText('Агробанк');
    await expect(page).toHaveURL(/t=AGBA/);
  } finally {release();}
});

test('SUM and RAT reuse analytics and returning to SUM reuses financial data', async ({page}) => {
  const requests = [];
  page.on('request', r => {if(r.url().includes('/api/')) requests.push(new URL(r.url()).pathname);});
  await setupCatalogPages(page);
  await ready(page);
  for (const code of ['SUM','RAT','SUM']) {await tab(page, code).click(); await ready(page);}
  expect(requests.filter(p => p.endsWith('/analytics'))).toHaveLength(1);
  expect(requests.filter(p => p.endsWith('/financials/columns'))).toHaveLength(1);
  expect(requests.filter(p => p.endsWith('/ai-report'))).toHaveLength(1);
  expect(requests.filter(p => p === '/api/catalog/status')).toHaveLength(1);
});

test('a slow filing index and analytics do not block independent financial and summary requests', async ({page}) => {
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  const requests = [];
  page.on('request', r => requests.push(new URL(r.url()).pathname));
  try {
    await setupCatalogPages(page, {func:'SUM', beforeNavigate:async () => {
      await page.route('**/api/catalog/index/**', async route => {await gate; await route.fallback();});
      await page.route('**/analytics?*', async route => {await gate; await route.fallback();});
    }});
    await expect(page.locator('.financial-columns')).toHaveAttribute('aria-busy', 'false');
    await expect.poll(() => requests.some(p => p.endsWith('/ai-report'))).toBe(true);
    await expect.poll(() => requests.some(p => p.endsWith('/financials'))).toBe(true);
  } finally {release();}
  await ready(page);
});

test('issuer browsing bounds mounted rows while keeping every company searchable and reachable', async ({page}) => {
  const companies = Array.from({length:125}, (_, i) => ({ticker:i ? `ISS${String(i).padStart(3,'0')}` : 'HMKB', company_name:i ? `Issuer ${i}` : 'Hamkorbank', sector:'finance', total_count:125-i}));
  await setupCatalogPages(page, {beforeNavigate:() => page.route('**/api/catalog/companies', route => route.fulfill({json:{ok:true, companies}}))});
  await expect(page.locator('.catalog-toolbar-count')).toHaveText('Результаты: 125');
  expect(await page.locator('.catalog-company-item').count()).toBeLessThanOrEqual(50);
  await page.getByRole('button', {name:'Следующие эмитенты'}).click();
  await expect(page.locator('.catalog-company-item').first()).toContainText('ISS050');
  await page.getByRole('button', {name:'Следующие эмитенты'}).click();
  await expect(page.locator('.catalog-company-item').last()).toContainText('ISS124');
  await expect(page.getByRole('button', {name:'Следующие эмитенты'})).toBeDisabled();
  const search = page.getByRole('combobox', {name:'Поиск компании', exact:true});
  await search.fill('HMKB');
  await expect(page.locator('.catalog-company-item')).toHaveCount(1);
  await search.fill('ISS124');
  await expect(page.locator('.catalog-company-item')).toHaveCount(1);
  await page.locator('.catalog-company-item').click();
  await expect(page).toHaveURL(/t=ISS124/);
  await search.fill('');
  await expect(page.locator('.catalog-company-item').first()).toContainText('HMKB');
});
