import { execFileSync } from 'node:child_process';
import { test, expect } from '@playwright/test';

test('UZTL financial tables and charts use billions while source passports keep original amounts', async ({ page }, testInfo) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    let data = { ok: true, items: [], companies: [], securities: {} };
    if (url.pathname === '/api/company/UZTL/financials') data = {
      ok: true, periods: ['2025', '2024'], series: {
        net_revenue: { money: true, unit: 'UZS', values: { 2024: 8964716518000, 2025: 10512797471000 } },
        net_profit: { money: true, unit: 'UZS', values: { 2024: 41629721000, 2025: 590906080000 } },
        net_margin: { money: false, unit: '%', values: { 2024: 0.46, 2025: 5.62 } },
      },
    };
    if (url.pathname.endsWith('/financials/passport')) data = { ok: true, status: 'SOURCED', source: {
      normalized_value: 590906080000, raw_value: 590906080, unit_scale: 1000, currency: 'UZS', period_year: 2025,
    } };
    return route.fulfill({ json: data });
  });
  await page.goto('/company/UZTL?tab=financials');
  await page.getByRole('button', { name: 'Table', exact: true }).click();
  const view = page.locator('.company-financials');
  await expect(view.getByRole('button', { name: '10,512.8', exact: true })).toBeVisible();
  await expect(view.getByRole('button', { name: '590.91', exact: true })).toBeVisible();
  await expect(view.locator('.fin-note')).toContainText('billions of UZS');
  await expect(view.locator('.fin-table thead th').first()).toContainText('billion UZS');
  await expect(view.locator('.fin-table')).toContainText('5.62%');
  await expect(view.locator('.fin-table')).toContainText('+17.27%');
  await view.getByRole('button', { name: '590.91', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('590906080000');
  await expect(page.getByRole('dialog')).toContainText('×1000');
  await page.getByRole('button', { name: 'Close source passport' }).click();
  await page.screenshot({ path: testInfo.outputPath('uztl-thousands.png'), fullPage: true });
  await view.getByRole('button', { name: 'Bars', exact: true }).click();
  await expect(view.locator('svg')).toBeVisible();
  await expect(view.locator('.fin-note')).toContainText('billions of UZS');
  await page.setViewportSize({ width: 390, height: 844 });
  await view.getByRole('button', { name: 'Table', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('uztl-thousands-mobile.png'), fullPage: true });
});

test('AGBA 2025 balance keeps the same scale when switching from UZS to USD and back', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('uz_stock_analyzer_language', 'en'));
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/company/AGBA/financials') return route.fulfill({json: {
      ok: true, periods: ['2025'], series: {
        total_assets: { money: true, unit: 'UZS', values: {2025: 103596612644000} },
      },
    }});
    if (url.pathname === '/api/currency/rates' && url.searchParams.get('as_of') === '2025-12-31') {
      return route.fulfill({json: {as_of: '2025-12-31', rates: [{ccy: 'USD', per_unit: 12025.33, effective_date: '2025-12-30'}]}});
    }
    return route.fulfill({json: {ok: true, items: [], companies: [], securities: {}}});
  });
  await page.goto('/company/AGBA?tab=financials');
  await page.getByRole('button', {name: 'Table', exact: true}).click();
  const table = page.locator('.fin-table');
  const unit = table.locator('thead th').first();
  const amount = table.locator('tbody td').first();
  const currency = page.getByRole('combobox', {name: 'Currency', exact: true});
  await expect(unit).toContainText('billion UZS');
  await expect(amount).toHaveText('103,596.61');
  await currency.click();
  await page.getByRole('option', {name: 'US dollar'}).click();
  await expect(unit).toContainText('billion USD');
  await expect(amount).toHaveText('8.61');
  await currency.click();
  await page.getByRole('option', {name: 'Uzbek som'}).click();
  await expect(amount).toHaveText('103,596.61');
});

test('ABKZ public income table displays verified gross margin with its calculation', async ({page}) => {
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language', 'en');
    sessionStorage.setItem('uz_sponsor_seen', '1');
  });
  await page.route('**/api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/company/ABKZ/financials') return route.fulfill({json:{
      ok:true, periods:['2025'], series:{
        net_revenue:{money:true, unit:'UZS', values:{2025:142434170000}},
        gross_profit:{money:true, unit:'UZS', values:{2025:28355210000}},
        gross_profit_margin:{money:false, unit:null, values:{2025:0.26}},
        gross_margin:{money:false, unit:'%', derived:true, values:{2025:19.90758959}},
      },
    }});
    if (url.pathname.endsWith('/financials/passport') && url.searchParams.get('field') === 'gross_margin') {
      return route.fulfill({json:{ok:true, status:'DERIVED', formula:'gross_profit / net_revenue * 100'}});
    }
    return route.fulfill({json:{ok:true, items:[], companies:[], securities:{}}});
  });
  await page.goto('/company/ABKZ?tab=financials');
  await page.getByRole('button',{name:'Table',exact:true}).click();
  const row = page.locator('.fin-table tr').filter({hasText:'Gross Margin'});
  await row.getByRole('button',{name:'19.91%'}).click();
  await expect(page.getByRole('dialog')).toContainText('gross_profit / net_revenue * 100');
});

test('public bank balance displays deposits in billions and opens the original filing', async ({page}) => {
  const original = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=annual&org_type=bank&report_id=438&lang=ru';
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language','en');
    sessionStorage.setItem('uz_sponsor_seen','1');
  });
  await page.route('**/api/**', route => {
    const {pathname} = new URL(route.request().url());
    if (pathname === '/api/company/HMKB/financials') return route.fulfill({json:{
      ok:true, organization_type:'bank', periods:['2025'], series:{
        total_assets:{money:true,unit:'UZS',values:{2025:35834699447000}},
        customer_funds:{money:true,unit:'UZS',derived:true,values:{2025:15115801873000}},
        loans_to_deposits:{money:false,unit:'ratio',derived:true,values:{2025:1.5}},
      },
    }});
    if (pathname.endsWith('/financials/passport')) return route.fulfill({json:{
      ok:true,status:'DERIVED',formula:'BANK_BS:15 + BANK_BS:16 + BANK_BS:17',source:{excel_url:original},
    }});
    return route.fulfill({json:{ok:true,items:[],companies:[],securities:{}}});
  });
  await page.goto('/company/HMKB?tab=financials');
  await page.getByRole('button',{name:'Balance Sheet',exact:true}).click();
  await page.getByRole('button',{name:'Table',exact:true}).first().click();
  const table=page.locator('.company-financials table.fin-table').first();
  const cell=table.locator('tbody tr').filter({has:page.getByRole('button',{name:'Customer deposits',exact:true})}).getByRole('button',{name:'15,115.8',exact:true});
  await cell.click();
  await expect(page.getByRole('dialog')).toContainText('BANK_BS:15 + BANK_BS:16 + BANK_BS:17');
  await expect(page.getByRole('dialog').getByRole('link')).toHaveAttribute('href',original);
});

test('a public microfinance balance line opens its structured Openinfo filing', async ({page}) => {
  const source = 'https://openinfo.uz/reports/microfinance/quarter/56';
  const label = '5. Кредиты (микрокредит, микрозайм, потребительский), брутто';
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language','en');
    sessionStorage.setItem('uz_sponsor_seen','1');
  });
  await page.route('**/api/**', route => {
    const {pathname} = new URL(route.request().url());
    if (pathname.endsWith('/financials')) return route.fulfill({json:{ok:true, organization_type:'financial',periods:['2026Q2'],series:{
      total_assets:{unit:'UZS',money:true,values:{'2026Q2':363831945000}},
      mfi_bs_050:{unit:'UZS',money:true,statement_section:'balance',filed_label:label,values:{'2026Q2':265400717000}},
    }}});
    if (pathname.endsWith('/financials/passport')) return route.fulfill({json:{ok:true,status:'SOURCED',filed_label:label,
      filing_links:[{url:source,period:'2026Q2',code:'050'}]}});
    return route.fulfill({json:{ok:true,items:[],companies:[],securities:{}}});
  });
  await page.goto('/company/ACMT1B2?tab=financials');
  await page.getByRole('button',{name:'Balance Sheet',exact:true}).click();
  await page.getByRole('button',{name:'Table',exact:true}).first().click();
  const row = page.locator('.company-financials .fin-table tr').filter({hasText:label});
  await row.getByRole('button',{name:'265.4',exact:true}).click({timeout:6000});
  await expect(page.getByRole('dialog').getByRole('link')).toHaveAttribute('href',source);
});

test('Biznes Finans annual profit and its source are shared by its bonds', async ({page}) => {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const fixture = JSON.parse(execFileSync(python, ['-c', `
import asyncio, json, os, tempfile
from catalogue.storage import get_catalog_conn
from catalogue.facts import upsert_facts
from server.company.financials import financial_series, financial_passport
with tempfile.TemporaryDirectory() as scratch:
    os.environ['CATALOG_DB_PATH'] = scratch + '/catalog.db'
    c = get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('BFMT2B5','Biznes Finans','922')")
    c.close()
    upsert_facts([{'entity_id':'922','dataset':'financial_indicators','field':'net_profit','value':10998939.67,
                   'period':'2025','unit':'UZS','source':'nsbu_derived_indicators','source_url':'nsbu-excel:BFMT2B5:2025'}])
    print(json.dumps({'series':asyncio.run(financial_series('BFMT2B5')), 'passport':asyncio.run(financial_passport('BFMT2B5','2025','net_profit'))}))
`], {encoding:'utf8'}));
  await page.addInitScript(() => {
    localStorage.setItem('uz_stock_analyzer_language','en');
    sessionStorage.setItem('uz_sponsor_seen','1');
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/financials')) return route.fulfill({json:fixture.series});
    if (path.endsWith('/financials/passport')) return route.fulfill({json:fixture.passport});
    return route.fulfill({json:{ok:true,items:[],companies:[],securities:{}}});
  });
  await page.goto('/company/BFMT2B5?tab=financials');
  await page.getByRole('button',{name:'Table',exact:true}).click();
  const profit = page.locator('.fin-table tr').filter({hasText:'Net Profit'}).first();
  await expect(profit).toContainText('34.14');
  await profit.getByRole('button',{name:'54.72',exact:true}).click();
  await expect(page.getByRole('dialog').getByRole('link',{name:/PDF/i})).toHaveAttribute(
    'href', 'https://openinfo.uz/media/audition/271f1719-cd04-470b-b834-e503925cb0c3.pdf');
});
