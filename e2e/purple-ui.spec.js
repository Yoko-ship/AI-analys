import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { expectPlainActiveNavigation } from './header-navigation.js';

const investorReport = JSON.parse(readFileSync('e2e/fixtures/ifrs-investor.json', 'utf8'));

async function setup(page, theme = 'light') {
  await page.emulateMedia({reducedMotion: 'reduce'});
  await page.addInitScript(theme => {
    localStorage.setItem('uz_stock_analyzer_token', 'purple-ui-test');
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    localStorage.setItem('uz_stock_analyzer_theme', theme);
    sessionStorage.setItem('uz_sponsor_seen', '1');
  }, theme);
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url()), path = url.pathname;
    const user = {id: 1, is_admin: true, email: 'reader@example.test'};
    const company = {ticker: 'UZMK', company_name: 'Uzmetkombinat', name: 'Uzmetkombinat', sector: 'manufacturing', total_count: 24, type: 'stock', last_price: 100, close_price: 90};
    const payload = path === '/api/auth/me' ? {user}
      : path === '/api/profile' ? {user, preferences: {}, favorites: [], notes: [], security: {}}
      : path === '/api/companies' || path === '/api/catalog/companies' ? {ok: true, companies: [company]}
      : path === '/api/market/stocks' ? {ok: true, stocks: [company]}
      : path === '/api/securities' ? {ok: true, securities: {UZMK: company}}
      : path.startsWith('/api/catalog/index/') ? {ok: true, company_name: company.name, availability: {NSBU: {annual: [{year: 2025, quarter: 0}], quarter: []}}}
      : path.endsWith('/financials/columns') && url.searchParams.get('view') === 'investor' ? investorReport
      : path.endsWith('/financials') ? {ok: true, standard: 'NSBU', scope: 'separate', periods: ['2025'], series: {net_profit: {money: true, values: {'2025': 1000000000}}}}
      : path.endsWith('/ai-report') ? {ok: true, ticker: 'UZMK', company_name: company.name, sections: {}, metrics: {}}
      : {ok: true, items: [], rows: [], stats: {}, companies_synced: 1, total_reports: 24};
    return route.fulfill({json: payload});
  });
}

for (const theme of ['light', 'dark']) {
  test(`catalog uses Purple surfaces, violet controls and semantic chart colors in ${theme}`, async ({page}, testInfo) => {
    await setup(page, theme);
    await page.goto('/catalog?t=UZMK&f=SUM&std=NSBU');
    const catalog = page.locator('.catalog-terminal-ui');
    await expect(catalog).toBeVisible();
    await expectPlainActiveNavigation(page, theme);
    const tokens = await catalog.evaluate(el => {
      const s = getComputedStyle(el), root = getComputedStyle(document.body);
      return {accent: s.getPropertyValue('--accent').trim(), pageAccent: root.getPropertyValue('--accent').trim(),
        panel: s.getPropertyValue('--panel').trim(), pagePanel: root.getPropertyValue('--panel').trim(),
        font: s.fontFamily, chart: s.getPropertyValue('--terminal-chart').trim(), positive: s.getPropertyValue('--positive').trim(), success: root.getPropertyValue('--success').trim()};
    });
    expect(tokens.accent).toBe(tokens.pageAccent);
    expect(tokens.panel).toBe(tokens.pagePanel);
    expect(tokens.chart).toBe(tokens.pageAccent);
    expect(tokens.positive).toBe(tokens.success);
    expect(tokens.font).toContain('Inter');
    await expect(catalog.locator('.catalog-company-item.active')).toHaveCSS('background-color',
      theme === 'light' ? 'rgba(98, 87, 217, 0.1)' : 'rgba(139, 124, 255, 0.14)');
    const control = catalog.locator('.terminal-tab').first();
    await expect(control).toBeVisible();
    // Root zoom can leave a fractional pixel below the 40px minimum.
    expect((await control.boundingBox()).height).toBeGreaterThanOrEqual(39.99);
    expect(await catalog.locator('.catalog-sidebar').evaluate(el => getComputedStyle(el).borderRadius)).toBe('16px');
    await page.screenshot({path: testInfo.outputPath(`catalog-${theme}.png`)});
    await page.setViewportSize({width:390, height:1000});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await expect(catalog.locator('.catalog-company-item.active')).toContainText('UZMK');
    await page.screenshot({path: testInfo.outputPath(`catalog-${theme}-mobile.png`)});
  });
}

test('workspace cards retain their layout and share the landing header color', async ({page}) => {
  await setup(page);
  for (const path of ['/issuers', '/currency', '/news', '/profile', '/catalog?t=UZMK']) {
    await page.goto(path);
    await expect(page.locator('.app-shell-wrap')).toHaveAttribute('data-ui', 'purple');
    const header = page.locator('.topbar');
    await expect(header).toBeVisible();
    await expectPlainActiveNavigation(page, 'light');
    await expect(header).toHaveCSS('background-color', 'rgb(241, 239, 234)');
  }
  await page.goto('/market');
  await expect(page.locator('.app-shell-wrap')).not.toHaveAttribute('data-ui', 'purple');
  await expect(page.locator('.market-table-wrap')).toBeVisible();
  await expect(page.locator('.topbar')).toHaveCSS('background-color', 'rgb(241, 239, 234)');
});

for (const theme of ['light','dark']) {
  test(`embedded financial screens and primary actions follow Purple in ${theme}`, async ({page}) => {
    await setup(page, theme);
    await page.goto('/catalog?t=UZMK&f=SUM&std=NSBU');
    const run = page.locator('.terminal-run');
    await expect(run).toBeVisible();
    await expect(run).toHaveCSS('background-color', theme === 'light' ? 'rgb(98, 87, 217)' : 'rgb(139, 124, 255)');
    await run.hover();
    await expect(run).toHaveCSS('background-color', theme === 'light' ? 'rgb(81, 71, 196)' : 'rgb(157, 145, 255)');
    const period = page.locator('.fc-segment button').first();
    await expect(period).toBeVisible();
    expect((await period.boundingBox()).height).toBeGreaterThanOrEqual(40);
    // IFRS is exposed on company reports; the catalog deliberately hides it.
    await page.goto('/company/HMKB?tab=financials');
    await page.getByRole('button', {name: 'МСФО', exact: true}).click();
    const investor = page.getByTestId('ifrs-investor');
    await expect(investor).toBeVisible();
    const palette = await investor.evaluate(el => {
      const s = getComputedStyle(el), page = getComputedStyle(document.body);
      return ['--iv-panel','--iv-text','--iv-line','--iv-purple'].map((token,i) => [s.getPropertyValue(token).trim(),page.getPropertyValue(['--panel','--text','--border','--accent'][i]).trim()]);
    });
    for (const [actual, expected] of palette) expect(actual).toBe(expected);
  });
}
