import { test, expect } from '@playwright/test';

let dataRequests;
const COMPANIES = [
  {ticker:'HMKB',name:'Hamkorbank',family:'bank'}, {ticker:'IPKY',name:'Ipak Yo‘li Bank',family:'bank'},
  {ticker:'SQBN',name:'SQB',family:'bank'}, {ticker:'TRSB',name:'Trastbank',family:'bank'},
  {ticker:'UZTL',name:'O‘zbektelekom',family:'corporate'}, {ticker:'UZMK',name:'O‘zmetkombinat',family:'corporate'},
];
function responseFor(url) {
  const period=url.searchParams.get('period')==='latest' ? '2026Q3' : url.searchParams.get('period')||'2026Q3';
  const standard=url.searchParams.get('standard')||'NSBU', scope=url.searchParams.get('scope')||'separate';
  const available=standard==='NSBU'&&scope==='separate';
  const source={url:'https://openinfo.uz/ru/reports/to_pdf31438/',period,scope,publication_date:'2026-10-19'};
  return {ok:true,period,standard,scope,companies:(url.searchParams.get('tickers')||'').split(',').filter(Boolean).map(ticker=>{
    const c=COMPANIES.find(c=>c.ticker===ticker)||{ticker,name:ticker,family:'corporate'};
    const profit=period==='2025'?1704969118000:period==='2024'?1426604717000:1480422343000;
    return {...c,status:available?'available':'unavailable',source,market_as_of:'2026-10-22',metrics:{
      net_profit:{value:available?profit:null,status:available?'reported':'unavailable',period,change:null,source},
      interest_income:{value:available&&c.family==='bank'?4645444343000:null,status:available?'reported':'unavailable',period,source},
      assets:{value:available?44389278550000:null,status:available?'reported':'unavailable',period,source},
    }};
  })};
}

test.beforeEach(async ({ page }) => {
  dataRequests = [];
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (/\/api\/(compare|analyze)|ai-report/.test(path)) dataRequests.push(path);
    if (path==='/api/company-comparison/options') return route.fulfill({json:{ok:true,companies:COMPANIES,periods:['2026Q3','2026Q2','2025','2024','2023']}});
    if (path==='/api/company-comparison') return route.fulfill({json:responseFor(url)});
    if (path.endsWith('/export.xlsx')) return route.fulfill({body:'excel',headers:{'Content-Type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','Content-Disposition':'attachment; filename="uzstock-comparison.xlsx"'}});
    return route.fulfill({ json: { ok: true, user: null, companies: [], securities: {}, stocks: [], items: [], stats: {} } });
  });
});

for (const { role, language, label } of [
  { role: 'guest', language: 'ru', label: 'Сравнить компании' },
  { role: 'member', language: 'uz', label: 'Kompaniyalarni solishtirish' },
  { role: 'admin', language: 'en', label: 'Compare companies' },
]) {
  test(`homepage comparison button is hidden for ${role}`, async ({ page }, testInfo) => {
    await page.addInitScript(({ role, language }) => {
      localStorage.setItem('uz_stock_analyzer_language', language);
      if (role !== 'guest') localStorage.setItem('uz_stock_analyzer_token', 'homepage-session');
    }, { role, language });
    await page.route('**/api/auth/me', route => route.fulfill({ json: {
      user: { id: 1, email: 'homepage@example.test', is_admin: role === 'admin' },
    } }));
    await page.goto(language === 'uz' ? '/uz' : '/');
    await expect(page.locator('.lv-h1')).toBeVisible();
    if (role !== 'guest') await expect(page.locator('.account-button')).toBeVisible();
    await expect(page.locator('.landing-view').getByRole('button', { name: label, exact: true })).toHaveCount(0);
    await expect(page.locator('.lv-actions button')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath('homepage-desktop.png'), animations: 'disabled' });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.locator('.landing-view').getByRole('button', { name: label, exact: true })).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath('homepage-mobile.png'), animations: 'disabled' });
    await page.locator('.lv-actions button').click();
    await expect(page).toHaveURL(/\/market$/);
  });
}

test('comparison displays backend figures without requesting analysis', async ({ page }) => {
  await page.goto('/compare');
  await expect(page).toHaveURL(/\/compare/);
  const screen = page.getByTestId('company-comparison');
  await expect(screen.getByRole('heading', { name: 'Compare companies', level: 1 })).toBeVisible();
  await expect(screen.getByText('Reported financials', { exact: true })).toBeVisible();
  await expect(screen.getByRole('table')).toBeVisible();
  await expect(screen).not.toContainText(/\bAI\b|winner|recommendation/i);
  await expect(screen).toContainText('1,480.422');
  await expect(screen).not.toContainText('Sample data');
  expect(dataRequests).toEqual([]);
});

test('audit: phone comparison puts figures before secondary controls',async({page},info)=>{
  await page.setViewportSize({width:390,height:844});
  await page.goto('/compare');
  const figure=page.locator('.cc-value').first();
  await expect(figure).toBeVisible();
  expect((await figure.boundingBox()).y).toBeLessThan(700);
  await page.getByText('Reporting settings',{exact:true}).click();
  await page.getByLabel('Reporting period',{exact:true}).selectOption('2024');
  await expect(page.locator('.cc-preview-note')).toContainText('2024');
  await page.screenshot({path:info.outputPath('comparison-phone-fixed.png'),fullPage:true});
});

for (const locale of [
  {language: 'ru', path: '/compare', market: 'Рынок', profit: 'Чистая прибыль', removed: ['Цена акции', 'Капитализация', 'Оборот за сессию']},
  {language: 'uz', path: '/uz/compare', market: 'Bozor', profit: 'Sof foyda', removed: ['Aksiya narxi', 'Kapitallashuv', 'Sessiya aylanmasi']},
  {language: 'en', path: '/compare', market: 'Market', profit: 'Net profit', removed: ['Share price', 'Market capitalization', 'Session turnover']},
]) {
  test(`comparison omits the market section with populated quotes (${locale.language})`, async ({page}, testInfo) => {
    await page.addInitScript(language => localStorage.setItem('uz_stock_analyzer_language', language), locale.language);
    await page.route('**/api/company-comparison?**', route => {
      const response = responseFor(new URL(route.request().url()));
      for (const company of response.companies) Object.assign(company.metrics, {
        price: {value: 107.01, status: 'reported'},
        market_cap: {value: 13880391000000, status: 'reported'},
        turnover: {value: 48000000, status: 'reported'},
        pe: {value: 8.14, status: 'calculated'},
        pb: {value: 1.2, status: 'calculated'},
      });
      return route.fulfill({json: response});
    });
    await page.goto(locale.path);
    const screen = page.getByTestId('company-comparison');
    const table = screen.getByRole('table');
    await expect(table.getByRole('rowheader', {name: locale.profit, exact: true})).toBeVisible();
    await expect(table.getByRole('row').filter({has: page.getByRole('rowheader', {name: /P\/E/})})).toContainText(locale.language === 'en' ? '8.14' : '8,14');
    for (const name of locale.removed) await expect(table.getByRole('rowheader', {name, exact: true})).toHaveCount(0);
    await expect(screen.locator('.cc-categories').getByRole('button', {name: locale.market, exact: true})).toHaveCount(0);
    await expect(table.locator('.cc-section')).toHaveCount(3);
    await expect(table.getByRole('rowheader', {name: /P\/E/})).toBeVisible();
    await expect(table.getByRole('rowheader', {name: /P\/B/})).toBeVisible();
    await page.evaluate(() => {document.body.dataset.theme = document.documentElement.dataset.theme = 'dark';});
    await screen.locator('.cc-table-wrap').evaluate(element => {element.scrollTop = element.scrollHeight;});
    await page.screenshot({path: testInfo.outputPath(`comparison-financials-${locale.language}.png`), fullPage: true});
  });
}

test('backend failure shows retry and never falls back to sample figures', async ({ page }) => {
  const requests = [];
  page.on('request', request => { if (request.url().includes('/api/')) requests.push(new URL(request.url()).pathname); });
  await page.route('**/api/**', route => route.abort('connectionrefused'));
  await page.goto('/compare');
  await expect(page.getByRole('alert')).toContainText('Could not load the comparison');
  await expect(page.getByRole('button',{name:'Export CSV',exact:true})).toBeDisabled();
  await expect(page.getByTestId('company-comparison')).not.toContainText('Sample data');
  expect(requests.filter(path => ['/api/companies', '/api/securities', '/api/catalog/status'].includes(path))).toEqual([]);
  await expect(page.locator('.toast')).toHaveCount(0);
});

test('company picker searches, excludes duplicates, and caps the selection at four', async ({ page }) => {
  await page.goto('/compare');
  await page.getByRole('button', { name: 'Add company', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Choose a company' });
  await expect(dialog.getByRole('button', { name: /HMKB/ })).toBeDisabled();
  await dialog.getByRole('searchbox').fill('Trast');
  await dialog.getByRole('button', { name: /TRSB/ }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Add company', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Remove TRSB' }).click();
  await expect(page.getByRole('button', { name: 'Add company', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Add company', exact: true }).click();
  await page.getByRole('dialog').getByRole('searchbox').fill('no such issuer');
  await expect(page.getByRole('dialog')).toContainText('No companies found');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button', { name: 'Add company', exact: true })).toBeFocused();
});

test('period controls change figures and unavailable standards clear them', async ({ page }) => {
  await page.goto('/compare');
  const row = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Net profit', exact: true }) });
  await expect(row).toContainText('1,480.422');
  const before = await row.innerText();
  await page.getByLabel('Reporting period', { exact: true }).selectOption('2025');
  await expect(row).not.toHaveText(before);
  await expect(row).toContainText('1,704.969');
  await expect(page).toHaveURL(/period=2025/);
  await page.getByLabel('Accounting standard', { exact: true }).selectOption('IFRS');
  await expect(page.getByRole('status')).toContainText('Some statements are unavailable');
  for (const cell of await row.getByRole('cell').all()) await expect(cell).not.toContainText(/\d/);
  await page.reload();
  await expect(page.getByLabel('Reporting period', { exact: true })).toHaveValue('2025');
  await expect(page.getByLabel('Accounting standard', { exact: true })).toHaveValue('IFRS');
});

test('comparisons save in this browser and export an honestly labelled CSV', async ({ page }) => {
  await page.goto('/compare');
  await page.getByRole('button', { name: 'Save comparison', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Save comparison' });
  await dialog.getByLabel('Comparison name').fill('My bank coverage');
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await page.reload();
  await page.getByText('Saved comparisons', { exact: true }).click();
  await expect(page.getByRole('button', { name: 'My bank coverage', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export CSV', exact: true })).toBeEnabled();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export CSV', exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/^uzstock-comparison-.*\.csv$/);
  expect(dataRequests).toEqual([]);
});

async function accountSaves(page, account) {
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_token', 'comparison-test'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({json: body, status});
    if (path === '/api/auth/me') return json({user: account.user});
    if (path === '/api/profile') return json({ok: true, user: account.user, favorites: [], preferences: {language: 'en'}, stats: {}, security: {}});
    if (path.startsWith('/api/saved-comparisons')) {
      expect(route.request().headers().authorization).toBe('Bearer comparison-test');
      const method = route.request().method();
      if (path.endsWith('/updates')) {
        account.inspections = (account.inspections || 0) + 1;
        const entry = account.entries.find(e => e.id === path.split('/').at(-2));
        const url = new URL('http://example.test/?' + new URLSearchParams({...entry.selection, tickers:entry.selection.tickers.join(',')}));
        return json({ok:true,comparison_id:entry.id,comparison:responseFor(url),changes:account.changes||[],updated:Boolean(account.changes?.length),
          tracking_started:!entry.has_baseline,last_seen_at:entry.has_baseline?'2026-10-21T12:00:00Z':null,
          snapshot_key:'1'.repeat(64),baseline_key:'0'.repeat(64)});
      }
      if (path.endsWith('/seen')) {
        account.seenCalls = (account.seenCalls || 0) + 1;
        if (account.failSeen) return json({detail:'Data changed'},409);
        account.changes=[];return json({ok:true,last_seen_at:'2026-10-23T12:00:00Z'});
      }
      if (method === 'GET') return account.failRead ? json({detail: 'Unavailable'}, 503) : json({ok: true, comparisons: account.entries});
      if (account.failWrite) return json({detail: 'Unavailable'}, 503);
      if (method === 'POST') {
        const {name, ...selection} = route.request().postDataJSON();
        const comparison = {id: String(account.entries.length + 1), name, selection};
        account.entries.unshift(comparison);return json({ok: true, comparison});
      }
      account.entries = account.entries.filter(entry => entry.id !== path.split('/').pop());
      return json({ok: true});
    }
    return route.fallback();
  });
}

const reader = {id: 17, full_name: 'Research analyst', email: 'analyst@example.test', tier: 'free', pro_access: false};

test('update badges remain unread until the saved comparison is opened', async ({page}) => {
  const account={user:reader,entries:[{id:'7',name:'Bank updates',has_baseline:true,selection:{tickers:['HMKB','IPKY'],period:'2025',standard:'NSBU',scope:'separate',unit:'billion'}}],
    changes:[{ticker:'HMKB',kind:'market_change',metric:'price',before:100,after:110,percent_change:10,before_date:'2026-10-21',after_date:'2026-10-22',source:{url:'https://uzse.uz'}}]};
  await accountSaves(page,account);await page.goto('/compare');
  await page.getByText('Saved comparisons',{exact:true}).click();
  await expect(page.locator('.cc-update-badge')).toContainText('Updated');
  expect(account.seenCalls||0).toBe(0);
  await page.getByRole('button',{name:'Bank updates',exact:true}).click();
  const panel=page.getByRole('region',{name:'What changed since your last visit'});
  await expect(panel).toContainText('100');await expect(panel).toContainText('110');
  await expect(panel).toContainText('+10%');
  await page.screenshot({path:'/tmp/uzstock-updates-desktop.png',fullPage:true});
  await expect.poll(()=>account.seenCalls||0).toBe(1);
  await page.getByText('Saved comparisons',{exact:true}).click();
  await expect(page.locator('.cc-update-badge')).toHaveCount(0);
});

test('legacy saves establish tracking without inventing past activity', async ({page}) => {
  const account={user:reader,entries:[{id:'7',name:'Old coverage',selection:{tickers:['HMKB','IPKY'],period:'2025',standard:'NSBU',scope:'separate',unit:'billion'}}]};
  await accountSaves(page,account);await page.goto('/compare');
  await page.getByText('Saved comparisons',{exact:true}).click();
  await page.getByRole('button',{name:'Old coverage',exact:true}).click();
  const panel=page.getByRole('region',{name:'What changed since your last visit'});
  await expect(panel).toContainText('Tracking starts with this visit');
  await expect(panel).not.toContainText('No changes since');
});

test('new reporting periods have no misleading profit growth and update cards fit a phone', async ({page}) => {
  await page.setViewportSize({width:360,height:780});
  const account={user:reader,entries:[{id:'7',name:'New filing',has_baseline:true,selection:{tickers:['HMKB','IPKY'],period:'2025',standard:'NSBU',scope:'separate',unit:'billion'}}],
    failSeen:true,changes:[{ticker:'HMKB',kind:'new_period',before_period:'2025',after_period:'2026Q3',source:{url:'https://openinfo.uz/filing.pdf'}}]};
  await accountSaves(page,account);await page.goto('/compare');
  await page.getByText('Actions',{exact:true}).click();
  await page.getByText('Saved comparisons',{exact:true}).click();
  await page.getByRole('button',{name:'New filing',exact:true}).click();
  const panel=page.getByRole('region',{name:'What changed since your last visit'});await panel.scrollIntoViewIfNeeded();
  await expect(panel).toContainText('New reporting period');await expect(panel).toContainText('9M 2026');
  await expect(panel).not.toContainText('%');
  await expect(panel.getByRole('alert')).toContainText('Refresh');
  const box=await panel.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(360);
  await page.screenshot({path:'/tmp/uzstock-updates-mobile.png',fullPage:true});
});
test('account import actions fit the saved menu on narrow Uzbek screens', async ({page}) => {
  await page.setViewportSize({width: 360, height: 780});
  await page.addInitScript(() => localStorage.setItem('uzstock_comparisons_v1', JSON.stringify([
    {id: 'local-1', name: 'Banklar', query: '?companies=HMKB,IPKY&period=latest'},
  ])));
  await accountSaves(page, {user: reader, entries: []});
  await page.goto('/uz/compare');
  await page.locator('.cc-actions-disclosure > summary').click();
  await page.locator('.cc-saved summary').click();
  const action = page.getByRole('button', {name: /Brauzerdagi solishtirishlarni import qilish/});
  await expect(action).toBeVisible();
  const box = await action.boundingBox();
  const menu = await page.locator('.cc-saved-menu').boundingBox();
  expect(box.x + box.width).toBeLessThanOrEqual(menu.x + menu.width);
  expect(box.x + box.width).toBeLessThanOrEqual(360);
});

test('account saves survive cleared browser storage and can be deleted on another session', async ({page}) => {
  const account = {user: reader, entries: []};
  await accountSaves(page, account);
  await page.goto('/compare');
  await expect(page.getByTestId('company-comparison')).toContainText('Saved to your account');
  await page.getByLabel('Reporting period', {exact: true}).selectOption('2025');
  await page.getByRole('button', {name: 'Save comparison', exact: true}).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Comparison name').fill('Account bank coverage');
  await dialog.getByRole('button', {name: 'Save', exact: true}).click();
  await expect(dialog).not.toBeVisible();
  expect(account.entries[0].selection.period).toBe('2025');
  expect(await page.evaluate(() => localStorage.getItem('uzstock_comparisons_v1'))).toBeNull();
  await page.evaluate(() => {localStorage.clear();sessionStorage.clear();});
  await page.goto('/compare');
  await page.getByText('Saved comparisons', {exact: true}).click();
  await page.getByRole('button', {name: 'Account bank coverage', exact: true}).click();
  await expect(page.getByLabel('Reporting period', {exact: true})).toHaveValue('2025');
  await page.getByText('Saved comparisons', {exact: true}).click();
  await page.getByRole('button', {name: 'Delete Account bank coverage', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Account bank coverage', exact: true})).toHaveCount(0);
  expect(account.entries).toEqual([]);
});

test('failed account save keeps the dialog open and never claims success', async ({page}) => {
  const account = {user: reader, entries: [], failWrite: true};
  await accountSaves(page, account);await page.goto('/compare');
  await expect(page.getByTestId('company-comparison')).toContainText('Saved to your account');
  await page.getByRole('button', {name: 'Save comparison', exact: true}).click();
  const dialog=page.getByRole('dialog');
  await dialog.getByLabel('Comparison name').fill('Retry me');
  await dialog.getByRole('button', {name: 'Save', exact: true}).click();
  await expect(dialog.getByRole('alert')).toContainText('Could not save');
  await expect(dialog).toBeVisible();expect(account.entries).toEqual([]);
  account.failWrite=false;
  await dialog.getByRole('button', {name: 'Save', exact: true}).click();
  await expect(dialog).not.toBeVisible();expect(account.entries).toHaveLength(1);
});

test('browser saves are imported only when the signed-in user explicitly asks', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('uzstock_comparisons_v1', JSON.stringify([
    {id: 'local-1', name: 'Old browser coverage', query: '?companies=HMKB,IPKY&period=2024&standard=NSBU&scope=separate&unit=million'},
  ])));
  const account = {user: reader, entries: []};await accountSaves(page, account);
  await page.goto('/compare');
  await page.getByText('Saved comparisons', {exact: true}).click();
  await expect(page.getByRole('button', {name: 'Old browser coverage', exact: true})).toHaveCount(0);
  expect(account.entries).toEqual([]);
  await page.getByRole('button', {name: /Import browser comparisons/}).click();
  await expect(page.getByRole('button', {name: 'Old browser coverage', exact: true})).toBeVisible();
  expect(account.entries[0].selection.period).toBe('2024');
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('uzstock_comparisons_v1')))).toEqual([]);
});

test('failed account list shows retry without substituting browser saves', async ({page}) => {
  const account = {user: reader, entries: [], failRead: true};await accountSaves(page, account);
  await page.goto('/compare');
  await expect(page.getByTestId('company-comparison').getByRole('alert')).toContainText('Could not load saved comparisons');
  account.failRead=false;
  await page.getByRole('button', {name: 'Retry saved comparisons', exact: true}).click();
  await expect(page.getByTestId('company-comparison').getByRole('alert')).toHaveCount(0);
});

test('failed account deletion keeps the comparison available for retry', async ({page}) => {
  const account = {user: reader, failWrite: true, entries: [{id: '8', name: 'Protected coverage', selection: {
    tickers: ['HMKB', 'IPKY'], period: 'latest', standard: 'NSBU', scope: 'separate', unit: 'billion',
  }}]};
  await accountSaves(page, account);await page.goto('/compare');
  await page.getByText('Saved comparisons', {exact: true}).click();
  await page.getByRole('button', {name: 'Delete Protected coverage', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('Could not delete');
  await expect(page.getByRole('button', {name: 'Protected coverage', exact: true})).toBeVisible();
  account.failWrite=false;
  await page.getByRole('button', {name: 'Delete Protected coverage', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Protected coverage', exact: true})).toHaveCount(0);
});

test('sign-out clears account saves even if a delayed account request completes', async ({page}) => {
  const account = {user: reader, entries: [{id: '3', name: 'Private coverage', selection: {
    tickers: ['HMKB', 'IPKY'], period: 'latest', standard: 'NSBU', scope: 'separate', unit: 'billion',
  }}]};
  await accountSaves(page, account);
  let release;
  const pending = new Promise(resolve => {release = resolve;});
  await page.route('**/api/saved-comparisons', async route => {
    await pending;
    await route.fulfill({json: {ok: true, comparisons: account.entries}}).catch(() => {});
  });
  await page.goto('/compare');
  await expect(page.getByTestId('company-comparison')).toContainText('Saved to your account');
  await page.locator('.topbar').getByRole('button', {name: /Account:/}).click();
  await page.getByRole('menuitem', {name: 'Log out', exact: true}).click();
  release();
  // Sign-out opens login; browser back must not restore private state.
  await page.goBack();
  await page.getByText('Saved comparisons', {exact: true}).click();
  await expect(page.getByRole('button', {name: 'Private coverage', exact: true})).toHaveCount(0);
  await expect(page.getByTestId('company-comparison')).toContainText('In this browser');
  expect(await page.evaluate(() => localStorage.getItem('uzstock_comparisons_v1'))).toBeNull();
});

test('an empty selection offers a clear way to start', async ({ page }) => {
  await page.goto('/compare?companies=');
  await expect(page.getByRole('heading', { name: 'Start with two companies' })).toBeVisible();
  await page.getByRole('button', { name: 'Add company', exact: true }).click();
  await page.getByRole('dialog').getByRole('button', { name: /HMKB/ }).click();
  await expect(page.getByRole('table')).toBeVisible();
  await expect(page.getByTestId('company-comparison')).toContainText('Add another company');
});

test('the narrow Uzbek layout fits its search and a complete company column', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 844 });
  await page.goto('/uz/compare');
  await expect(page.getByRole('heading', { name: 'Kompaniyalarni solishtirish', level: 1 })).toBeVisible();
  for (const selector of ['.cc-table-options', '.cc-table-options .cc-search', '.cc-company-column']) {
    const box = await page.locator(selector).first().boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(360);
  }
});

for (const theme of ['light', 'dark']) {
  test(`phone comparison keeps metrics readable with contained scrolling (${theme})`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/compare');
    await page.evaluate(value => { document.body.dataset.theme = document.documentElement.dataset.theme = value; }, theme);
    await expect(page.getByRole('heading', { name: 'Compare companies', level: 1 })).toBeVisible();
    await page.getByText('Reporting settings',{exact:true}).click();
    await page.getByText('Actions',{exact:true}).click();
    await expect(page.getByLabel('Reporting period', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    // Clipping the shell can hide an oversized child without changing scrollWidth.
    // Check the actual controls, not only the document's overflow.
    for (const control of [
      page.getByLabel('Accounting standard', { exact: true }),
      page.getByLabel('Display units', { exact: true }),
      page.getByRole('button', { name: 'Save comparison', exact: true }),
    ]) {
      const box = await control.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(390);
    }
    const region = page.getByRole('region', { name: 'Company comparison table' });
    const label = page.getByRole('rowheader', { name: 'Net profit', exact: true });
    const firstX = (await label.boundingBox()).x;
    await region.evaluate(node => { node.scrollLeft = 240; });
    expect(Math.abs((await label.boundingBox()).x - firstX)).toBeLessThan(2);
    await page.screenshot({ path: testInfo.outputPath(`comparison-phone-${theme}.png`), fullPage: true });
  });
}

test('source links and Excel export use the selected backend context', async ({page})=>{
  await page.goto('/compare?companies=HMKB,IPKY&period=2025');
  await expect(page.getByRole('button',{name:'Export Excel',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'About the sources',exact:true}).first().click();
  await expect(page.getByRole('dialog').getByRole('link').first()).toHaveAttribute('href',/openinfo\.uz/);
  await page.keyboard.press('Escape');
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Export Excel',exact:true}).click();
  expect((await download).suggestedFilename()).toBe('uzstock-comparison.xlsx');
});

test('a late response for a previous period cannot overwrite the new selection',async({page})=>{
  await page.route('**/api/company-comparison?**',async route=>{
    const url=new URL(route.request().url());
    if(url.searchParams.get('period')==='2025')await new Promise(resolve=>setTimeout(resolve,500));
    try{await route.fulfill({json:responseFor(url)});}catch{/* browser cancelled the old request */}
  });
  await page.goto('/compare');
  const row=page.getByRole('row').filter({has:page.getByRole('rowheader',{name:'Net profit',exact:true})});
  await expect(row).toContainText('1,480.422');
  await page.getByLabel('Reporting period',{exact:true}).selectOption('2025');
  await page.getByLabel('Reporting period',{exact:true}).selectOption('2024');
  await expect(row).toContainText('1,426.605');
  await page.waitForTimeout(600);
  await expect(row).toContainText('1,426.605');
  await expect(row).not.toContainText('1,704.969');
});
