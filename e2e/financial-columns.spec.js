import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';

const fixture = JSON.parse(readFileSync('e2e/fixtures/financial-columns.json', 'utf8'));
const templateFixture = JSON.parse(readFileSync('e2e/fixtures/financial-columns-template.json', 'utf8'));
const original = JSON.parse(readFileSync('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json', 'utf8'));
const hmkbFixture = JSON.parse(readFileSync('e2e/fixtures/hmkb-overview.json', 'utf8'));
const hmkbLabels = JSON.parse(readFileSync('tests/fixtures/financial_columns/hmkb_overview_labels.json', 'utf8'));
const recentReports = JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json', 'utf8'));

test('HMKB chart includes the separate loan and lease values already shown in the table', async ({page}, testInfo) => {
  await setup(page, {ticker:'HMKB', func:'SUM', reports:recentReports});
  const terminal=page.getByTestId('financial-columns');
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  const select=terminal.locator('.fc-chart select');
  await expect(select.locator('option').filter({hasText:'Кредиты и лизинговые операции, брутто · 7а'})).toHaveCount(1);
  await select.selectOption({label:'Кредиты и лизинговые операции, брутто · 7а'});
  await expect(terminal.locator('.fc-chart svg rect')).toHaveCount(3);
  await expect(terminal.locator('.fc-chart')).toContainText('30,361,825,389');
  await select.selectOption({label:'Кредиты и лизинговые операции, брутто · 7б'});
  await expect(terminal.locator('.fc-chart')).toContainText('1,056,352,067');
  await expect(terminal.locator('.fc-chart')).not.toContainText('31,418,177,456');
  await terminal.locator('.fc-chart').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('hmkb-component-chart.png')});
  await page.setViewportSize({width:390,height:844});
  await terminal.locator('.fc-chart').scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('hmkb-component-chart-mobile.png')});
});

test('annual income gaps explain why a comparative balance can still be populated', async ({page},testInfo) => {
  const reports=structuredClone(recentReports);
  reports.columns=[{key:'2023',label:'2023',end:'2023-12-31',basis:'annual'},
    {key:'2025',label:'2025',end:'2025-12-31',basis:'annual',notice:'ANNUAL_INCOME_NOT_IMPORTED',balance_source:'comparative'},
    {key:'2026-06-30',label:'2026 · 6M',end:'2026-06-30',basis:'ytd'}];
  const observations=JSON.parse(readFileSync('tests/fixtures/financial_columns/agmkp_comparative_balance.json','utf8'));
  reports.rows=['revenue','ppe'].map(metric=>{
    const cells=observations.filter(c=>c.metric_id===metric), sample=cells[0];
    return {id:metric,metric_id:metric,label:sample.raw_label,source_form:sample.source_form,source_code:sample.source_code,
      cells:Object.fromEntries(reports.columns.map(c=>[c.key,cells.find(v=>v.period_end===c.end)||{value:null,quality:'missing'}]))};
  });
  reports.overview_rows=reports.rows;
  await setup(page,{ticker:'AGMKP',func:'SUM',reports});
  const terminal=page.getByTestId('financial-columns');
  await expect(terminal.locator('.fc-period-notice')).toContainText('2025');
  await expect(terminal.locator('.fc-period-notice')).toContainText('Annual income statement is not available');
  await expect(terminal.locator('.fc-period-notice')).toContainText('comparative');
  await expect(terminal.locator('tr[data-metric="revenue"] td').nth(1)).toHaveText('—');
  await expect(terminal.locator('tr[data-metric="ppe"] td').nth(1)).toHaveText('13,358,866,945');
  await terminal.locator('.fc-period-notice').scrollIntoViewIfNeeded();
  await page.screenshot({path:testInfo.outputPath('agmkp-annual-income-notice.png')});
});

async function setup(page, { fail = false, theme = 'light', func = 'PL', ticker = 'IPTB', reports } = {}) {
  await page.addInitScript(theme => localStorage.setItem('uz_stock_analyzer_theme', theme), theme);
  await page.addInitScript(() => {
    sessionStorage.setItem('uz_sponsor_seen', '1');
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    localStorage.setItem('uz_stock_analyzer_token', 'columns-admin');
  });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const json = value => route.fulfill({ json: value });
    if (path === '/api/auth/me') return json({ user: { id: 1, is_admin: true } });
    if (path === '/api/catalog/companies') return json({ ok: true, total: 1, companies: [{ ticker, company_name: ticker === 'HMKB' ? 'Hamkorbank' : 'Ipoteka bank', sector: 'finance' }] });
    if (path === `/api/catalog/index/${ticker}`) return json({ ok: true, company_name: ticker === 'HMKB' ? 'Hamkorbank' : 'Ipoteka bank', availability: { NSBU: { annual: [{ year: 2025 }], quarter: [{ year: 2026, quarter: 3 }] } } });
    if (path.endsWith('/financials/columns')) {
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Source temporarily unavailable' } });
      const data = reports || (ticker === 'HMKB' ? hmkbFixture : (url.searchParams.get('view') === 'template' ? templateFixture : fixture)[url.searchParams.get('freq') || 'annual']);
      if (url.searchParams.get('form') === 'MSFO') return json({ ...data, standard: 'MSFO', rows: [], overview_rows: [], ratios: [], source_forms: [], coverage: { complete: false, notes: 'missing', issues: ['NOTES_MISSING'] } });
      return json({ ...data, source_forms: [{ period_end: '2026-09-30', documents: [original] }] });
    }
    return json({ ok: true, companies_synced: 1, total_reports: 2, companies: [], rows: [], items: [], series: {}, periods: [], rates: [], availability: {} });
  });
  await page.goto(`/catalog?t=${ticker}&f=${func}`);
}

for (const theme of ['light', 'dark']) test(`two annual reports and the current report appear together (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme, reports: recentReports });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.locator('.fc-table thead th')).toHaveText(['Metric', '2024', '2025', '2026 · 9MYTD']);
  await expect(terminal.locator('.fc-table tbody tr[data-metric]')).toHaveCount(24);
  await expect(terminal.locator('.fc-stats > div').filter({ hasText: 'Net profit' })).toContainText('1,480,422,343');
  const income = terminal.locator('.fc-table tr[data-metric="interest_income"]');
  await expect(income.locator('td')).toHaveCount(3);
  await expect(income.locator('td').last()).not.toHaveText('—');
  await income.locator('td').last().getByRole('button').click();
  await expect(page.getByRole('dialog')).toContainText('2026-01-01 — 2026-09-30');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.locator('.fc-table').evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.evaluate(() => window.scrollBy(0, -130));
  await page.screenshot({ path: testInfo.outputPath(`recent-reports-${theme}.png`), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await terminal.locator('.fc-scroll').evaluate(el => { el.scrollLeft = el.scrollWidth; });
  await expect(terminal.getByRole('columnheader', { name: /2026 · 9M/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath(`recent-reports-${theme}-mobile.png`), animations: 'disabled' });
});

for (const theme of ['light', 'dark']) test(`HMKB overview matches the HTML's exact 24 fields (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme });
  const terminal = page.getByTestId('financial-columns');
  const rows = terminal.locator('.fc-table tbody tr[data-metric]');
  await expect(rows).toHaveCount(24);
  expect(await rows.locator('th').evaluateAll(nodes => nodes.map(n => n.firstChild.textContent))).toEqual(hmkbLabels);
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=overview/);
  const loans = rows.filter({ hasText: 'Кредиты и лизинговые операции, брутто' });
  await expect(loans).toHaveCount(1);
  await expect(loans.getByRole('button')).toHaveCount(2);
  await loans.getByRole('button').first().click();
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toContainText('7а');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.locator('.fc-subnav').scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath(`hmkb-overview-${theme}.png`), animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(rows).toHaveCount(24);
  await terminal.locator('.fc-table').evaluate(el => el.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: testInfo.outputPath(`hmkb-overview-${theme}-mobile.png`), animations: 'disabled' });
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(rows).toHaveCount(42);
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=template/);
  await terminal.getByRole('tab', { name: 'Overview', exact: true }).click();
  await expect(rows).toHaveCount(24);
});

test('the terminal displays and exports only the reference field list', async ({ page }) => {
  await setup(page, { func: 'SUM' });
  const terminal = page.getByTestId('financial-columns');
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="interest_income"]')).toHaveCount(1);
  await expect(terminal.getByRole('button', { name: '▾ Баланс банка · активы', exact: true })).toBeVisible();
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await expect(terminal.locator('tr[data-metric="travel_expense"]')).toHaveCount(0);
  await expect(terminal.getByRole('link', { name: 'CSV', exact: true })).toHaveAttribute('href', /view=overview/);
  await expect(terminal.getByRole('link', { name: 'XLSX', exact: true })).toHaveAttribute('href', /view=overview/);
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await expect(terminal.locator('.fc-documents')).toHaveCount(0);
  await terminal.getByRole('searchbox').fill('7а');
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
});

for (const theme of ['light','dark']) test(`financial statements share the catalog theme and controls (${theme})`, async ({page},testInfo) => {
  await setup(page,{theme});
  const terminal=page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="cash"]')).toBeVisible();
  const styles=await terminal.evaluate(el=>{
    const own=getComputedStyle(el), catalog=getComputedStyle(el.closest('.catalog-terminal-ui'));
    return {ownColor:own.color,catalogColor:catalog.color,ownFont:own.fontFamily,catalogFont:catalog.fontFamily};
  });
  expect(styles.ownColor).toBe(styles.catalogColor);
  expect(styles.ownFont).toBe(styles.catalogFont);
  await expect(page.getByRole('button',{name:'NSBU',exact:true})).toHaveCount(1);
  await expect(terminal.locator('.fc-toolbar').getByRole('button',{name:'IFRS',exact:true})).toHaveCount(0);
  await page.screenshot({path:testInfo.outputPath(`financial-integrated-${theme}.png`),fullPage:true,animations:'disabled'});
  await page.setViewportSize({width:390,height:844});
  await terminal.getByRole('button',{name:'Chart',exact:true}).click();
  await expect(terminal.getByRole('img',{name:'Financial history'})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath(`financial-integrated-${theme}-mobile.png`),fullPage:true,animations:'disabled'});
});

for (const theme of ['light', 'dark']) test(`SUM shows financial year columns directly in the overview (${theme})`, async ({ page }, testInfo) => {
  await setup(page, { func: 'SUM', theme });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal).toHaveCount(1);
  await expect(terminal.locator('.fc-table thead')).toContainText('2025');
  await expect(terminal.locator('tr[data-metric="cash"]')).toBeVisible();
  await expect(page.getByRole('button', { name: 'NSBU', exact: true })).toHaveCount(1);
  const summary = page.locator('.terminal-summary');
  await expect(summary).toBeVisible();
  expect((await terminal.boundingBox()).y).toBeLessThan((await summary.boundingBox()).y);
  await terminal.locator(".fc-stats").evaluate(el => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: testInfo.outputPath(`sum-columns-${theme}.png`), animations: "disabled" });
  await page.setViewportSize({ width: 390, height: 844 });
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  const income = terminal.locator('tr[data-metric="interest_income"]').filter({ hasText: 'Итого' });
  await expect(income).toContainText('9,447,836,814');
  await income.getByRole('button').last().click();
  const passport = page.getByRole('dialog', { name: 'Source passport' });
  await expect(passport.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /openinfo/);
  await passport.getByRole('button', { name: 'Close', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await terminal.locator(".fc-stats").evaluate(el => el.scrollIntoView({ block: "start" }));
  await page.screenshot({ path: testInfo.outputPath(`sum-columns-${theme}-mobile.png`), animations: "disabled" });
  await page.getByRole('group', { name: 'Accounting standard' }).getByRole('button', { name: 'MSFO', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="cash"]')).toHaveCount(0);
  await expect(terminal.getByText('No verified source rows in this accounting scope.')).toBeVisible();
});

test('SUM workspace panels include the same year columns', async ({ page }) => {
  await setup(page, { func: 'SUM' });
  await page.getByRole('button', { name: 'PNL · Panels', exact: true }).click();
  const panel = page.locator('.terminal-work-panel').first();
  await expect(panel).toHaveAttribute('data-terminal-function', 'SUM');
  await expect(panel.getByTestId('financial-columns').locator('.fc-table thead')).toContainText('2025');
  await expect(panel.locator('tr[data-metric="cash"]')).toBeVisible();
  await expect(panel.locator('.terminal-summary')).toBeVisible();
});

for (const fallback of [false, true]) test(`report panels expand and restore without losing state (fallback=${fallback})`, async ({ page }, testInfo) => {
  if (fallback) await page.addInitScript(() => {
    Element.prototype.requestFullscreen = () => Promise.reject(new Error('Fullscreen unavailable'));
  });
  await setup(page, { ticker: 'HMKB', func: 'SUM', theme: fallback ? 'light' : 'dark', reports: recentReports });
  await page.getByRole('button', { name: 'PNL · Panels', exact: true }).click();
  const panels = page.locator('.terminal-work-panel'), first = panels.first();
  await expect(panels).toHaveCount(1);
  const grid = await page.locator('.terminal-panel-grid').boundingBox();
  expect((await first.boundingBox()).width).toBeGreaterThan(grid.width - 2);
  await page.getByRole('button', { name: 'Add panel', exact: true }).click();
  await expect(panels).toHaveCount(2);
  const second = panels.nth(1);
  const search = second.getByRole('searchbox');
  await search.fill('процентных доходов');
  const assertExpanded = async () => {
    await expect(second).toHaveClass(/is-expanded/);
    const box = await second.boundingBox(), viewport = page.viewportSize();
    expect(Math.abs(box.width - viewport.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(box.height - viewport.height)).toBeLessThanOrEqual(1);
    expect(Math.abs(box.x) + Math.abs(box.y)).toBeLessThanOrEqual(1);
    await expect(second.getByRole('button', { name: 'Restore', exact: true })).toBeInViewport();
    await expect(second.locator('.fc-table thead')).toContainText('2026 · 9M');
  };
  await second.getByRole('button', { name: 'Full screen', exact: true }).click();
  await assertExpanded();
  if (fallback) {
    await page.evaluate(() => {
      const overlay = document.createElement('aside');
      overlay.className = 'sponsor-overlay'; overlay.dataset.fullscreenTest = 'true';
      overlay.style.height = '390px'; overlay.textContent = 'Advertisement';
      document.body.append(overlay);
    });
    await expect(page.locator('[data-fullscreen-test]')).toBeHidden();
  }
  if (!fallback) await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
  await second.locator('.fc-table tbody td').last().getByRole('button').click();
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Source passport' })).toHaveCount(0);
  await assertExpanded();
  await page.screenshot({ path: testInfo.outputPath(`panel-fullscreen-${fallback}.png`), animations: 'disabled' });
  await second.getByRole('button', { name: 'Restore', exact: true }).click();
  await expect(second).not.toHaveClass(/is-expanded/);
  if (fallback) await page.locator('[data-fullscreen-test]').evaluate(el => el.remove());
  await expect(search).toHaveValue('процентных доходов');
  await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
  expect((await second.boundingBox()).width).toBeLessThan(grid.width * .6);
  if (!fallback) {
    await second.getByRole('button', { name: 'Full screen', exact: true }).click();
    await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
    await page.evaluate(() => document.exitFullscreen());
    await expect(second).not.toHaveClass(/is-expanded/);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await second.getByRole('button', { name: 'Full screen', exact: true }).click();
  await assertExpanded();
  await page.screenshot({ path: testInfo.outputPath(`panel-fullscreen-${fallback}-mobile.png`), animations: 'disabled' });
  await page.keyboard.press('Escape');
  await expect(second).not.toHaveClass(/is-expanded/);
  await expect(search).toHaveValue('процентных доходов');
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
  await first.getByRole('button', { name: 'Full screen', exact: true }).click();
  await first.getByRole('button', { name: 'Remove panel', exact: true }).click();
  await expect(panels).toHaveCount(1);
  await expect(panels.first()).not.toHaveClass(/is-expanded/);
  expect(await page.evaluate(() => document.body.style.overflow)).not.toBe('hidden');
});

test('source columns preserve units, periods and passports at desktop and mobile sizes', async ({ page }, testInfo) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal).toBeVisible();
  await terminal.getByRole('button', { name: '6M / 9M', exact: true }).click();
  await expect(terminal.locator('.fc-stats > div').filter({ hasText: 'Assets' })).toContainText('2026-09-30');
  const income = terminal.locator('tr[data-metric="interest_income"]').filter({ hasText: 'Итого' });
  await expect(income).toContainText('9,447,836,814');
  await expect(terminal.getByText('Amounts: thousands UZS', { exact: false })).toBeVisible();
  await expect(income.locator('th')).toHaveText('Итого процентных доходовОтчёт о финансовых результатах: 1.л');
  await income.getByRole('button').last().click();
  const passport = page.getByRole('dialog', { name: 'Source passport' });
  await expect(passport.locator('h4').first()).toHaveText('Итого процентных доходов');
  await expect(passport).toContainText('л. Итого процентных доходов');
  await expect(passport).toContainText('1л');
  await expect(passport).toContainText('separate');
  await expect(passport.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', /openinfo/);
  await passport.getByRole('button', { name: 'Close', exact: true }).click();
  await terminal.getByRole('button', { name: 'Chart', exact: true }).click();
  await expect(terminal.getByRole('img', { name: 'Financial history' })).toBeVisible();
  await terminal.getByRole('button', { name: 'Table', exact: true }).click();
  await terminal.getByRole('tab', { name: 'Original forms', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="staff_expense"]')).toHaveCount(0);
  await terminal.getByRole('searchbox').fill('1л');
  await expect(terminal.locator('tbody tr[data-metric]')).toHaveCount(1);
  await terminal.getByRole('button', { name: 'Reset', exact: true }).click();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-desktop.png'), fullPage: true, animations: 'disabled' });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(terminal.getByRole('button', { name: '6M / 9M', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath('financial-columns-mobile.png'), fullPage: true, animations: 'disabled' });
});

test('changing standard clears source rows and gives an explicit missing-data state', async ({ page }) => {
  await setup(page);
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.locator('tr[data-metric="cash"]')).toBeVisible();
  await page.getByRole('group', { name: 'Accounting standard' }).getByRole('button', { name: 'MSFO', exact: true }).click();
  await expect(terminal.locator('tr[data-metric="cash"]')).toHaveCount(0);
  await expect(terminal.getByText('No verified source rows in this accounting scope.')).toBeVisible();
  await expect(terminal.getByText('Notes are missing or have not been verified.')).toBeVisible();
  await expect(terminal.locator('.fc-legacy')).toHaveCount(0);
  await terminal.getByRole('tab', { name: 'Data quality', exact: true }).click();
  await expect(terminal.locator('.fc-quality')).toContainText('Notes are missing or have not been verified.');
});

test('a failed financial source request can be retried without showing stale amounts', async ({ page }) => {
  await setup(page, { fail: true });
  const terminal = page.getByTestId('financial-columns');
  await expect(terminal.getByRole('alert')).toContainText('Could not load financial statements');
  await expect(terminal.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  await expect(terminal.locator('tr[data-metric]')).toHaveCount(0);
});
