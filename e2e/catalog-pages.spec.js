import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import {catalogPages,setupCatalogPages,openCatalogPage} from './helpers/catalog-pages.js';

// This sweep covers presentation and page boundaries. Feature specs retain
// their existing financial calculations, filters, exports and navigation cases.
for(const [theme,width] of [['light',1440],['dark',390]])for(const [code,selector]of catalogPages){
 test(`${code} has readable content and contained layout (${theme}, ${width}px)`,async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await setupCatalogPages(page,{theme,width});await openCatalogPage(page,code);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  const body=page.locator(code.startsWith('ADM-')?'.terminal-market-screen':selector).first();
  const cells=body.locator('table.terminal-table tbody th,table.terminal-table tbody td,.catalog-report-table tbody td');
  const sizes=await cells.evaluateAll(els=>els.filter(e=>e.getClientRects().length).map(e=>({text:e.textContent.slice(0,50),size:parseFloat(getComputedStyle(e).fontSize)})));
  expect(sizes.filter(x=>x.size<14),'data cells must be at least 14px').toEqual([]);
  if(code==='SUM')expect(await body.locator('.terminal-summary-kpis small').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(12);
  if(code==='CF'){
   expect(await body.locator('thead th').first().evaluate(e=>getComputedStyle(e).textTransform)).toBe('none');
   expect(await body.locator('.catalog-report-select small').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(12);
   const scroll=body.getByRole('region',{name:'Финансовые отчёты'});
   await expect(scroll).toHaveAttribute('tabindex','0');
   if(width<600){
    await expect(body.getByText('Прокрутите вправо, чтобы увидеть даты, источники и файлы')).toBeVisible();
    await scroll.focus();await page.keyboard.press('ArrowRight');
    await expect.poll(()=>scroll.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);
   }
  }
  if(['CN','DQ'].includes(code))await expect(page.locator('.catalog-main').getByRole('heading',{name:code==='CN'?'Новости':'Качество данных',exact:true})).toBeVisible();
  if(code==='HELP'){
   for(const button of await body.locator('.terminal-code').all())expect((await button.boundingBox()).height).toBeGreaterThanOrEqual(44);
   expect(await body.locator('kbd').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(12);
  }
  if(code==='EQS')expect(await body.locator('.terminal-valuation-meta code').evaluate(e=>parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(12);
  if(code==='LAST')expect((await body.locator('button').first().boundingBox()).height).toBeGreaterThanOrEqual(44);
  if(code==='ADM-coverage')expect((await body.locator('.terminal-coverage-cell').first().boundingBox()).height).toBeGreaterThanOrEqual(44);
  if(code==='ADM-templates'){
   const tables=body.locator('table:not([data-own-export])');
   await expect(body.locator('.terminal-csv')).toHaveCount(await tables.count());
  }
  expect(errors).toEqual([]);
 });
}

test('nested catalog admin tables have one export with the selected scope after tab changes',async({page})=>{
 await setupCatalogPages(page);await openCatalogPage(page,'ADM-coverage');
 const screen=page.locator('.terminal-market-screen');
 await screen.getByRole('combobox',{name:'Стандарт',exact:true}).selectOption('MSFO');
 await expect(screen.locator('.terminal-csv')).toHaveCount(1);
 const pending=page.waitForEvent('download');await screen.getByRole('button',{name:'CSV',exact:true}).click();
 const csv=readFile(await (await pending).path());expect(csv).toContain('Standard,MSFO');
 await screen.locator('.terminal-admin-tabs').getByRole('button',{name:'Сводка',exact:true}).click();
 await expect(screen.locator('.terminal-csv')).toHaveCount(1);
 await screen.locator('.terminal-admin-tabs').getByRole('button',{name:'Покрытие',exact:true}).click();
 await expect(screen.locator('.terminal-csv')).toHaveCount(1);
});
const readFile=path=>readFileSync(path,'utf8');
