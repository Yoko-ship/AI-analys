import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';

test('IPTB balance shows the total from its three filed deposit lines', async ({page}) => {
  const python = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python';
  const report = JSON.parse(execFileSync(python, ['-c', `
import json, os, tempfile
from pathlib import Path
from catalogue.storage import get_catalog_conn
from financial_columns import service, source_store
with tempfile.TemporaryDirectory() as folder:
    os.environ['CATALOG_DB_PATH'] = str(Path(folder) / 'catalog.db')
    db = get_catalog_conn()
    with db:
        db.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('IPTB','Ipoteka bank','217')")
    db.close()
    book = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json').read_text())
    source_store.record_nsbu(ticker='IPTB', issuer_id='217', year=2026, quarter=3, template='bank',
                             data={'ok': True, 'balance': book, 'income': book},
                             urls={'excel_url': book['source_url'], 'published_at': '2026-10-20'})
    print(json.dumps(service.load('IPTB', view='template', statement='balance', include_sources=False)))
`], {encoding:'utf8', maxBuffer:8 * 1024 * 1024}));
  await page.addInitScript(() => {
    sessionStorage.setItem('uz_sponsor_seen','1');
    localStorage.setItem('uz_stock_analyzer_language','en');
    localStorage.setItem('uz_stock_analyzer_token','columns-admin');
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/financials/columns')) return route.fulfill({json:report});
    if (path === '/api/auth/me') return route.fulfill({json:{user:{id:1,is_admin:true}}});
    if (path === '/api/catalog/index/IPTB') return route.fulfill({json:{ok:true,company_name:'Ipoteka bank',availability:{NSBU:{annual:[{year:2025}]}}}});
    return route.fulfill({json:{ok:true,rows:[],companies:[],items:[]}});
  });
  await page.goto('/catalog?t=IPTB&f=BS');
  const row = page.getByTestId('financial-columns').locator('tr[data-metric="customer_funds"]');
  await expect(row).toContainText('29,321,578,637');
});
