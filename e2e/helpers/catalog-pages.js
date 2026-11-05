import {readFileSync} from 'node:fs';
import {expect} from '@playwright/test';
const read=path=>JSON.parse(readFileSync(new URL(path,import.meta.url),'utf8'));
const columns=read('../fixtures/hmkb-recent-reports.json');
const bank=read('../../tests/fixtures/terminal_hmkb_bank_2025.json');
const overview=read('../fixtures/hmkb-overview.json');
export const catalogPages=[
 ['SUM','.terminal-summary'],['PL','.financial-columns'],['BS','.financial-columns'],['RAT','.terminal-annual-ratios'],['FV','.terminal-fv-detail'],['RV','.terminal-peers-screen'],
 ['DVD','.terminal-dividend-comparison'],['CF','.catalog-report-section'],['CN','.terminal-news'],['DQ','.terminal-dq'],['REC','.terminal-reconciliation'],
 ['EQS','.terminal-market-screen'],['MON','.terminal-monitor'],['PNL','.terminal-work-panel'],['HELP','.terminal-help-grid'],['LAST','.terminal-last'],
 ...['summary','templates','fv','coverage','journal','usage'].map(tab=>[`ADM-${tab}`,'.terminal-admin-tabs']),
];
const adminNames={summary:'Сводка',templates:'Шаблоны',fv:'FV',coverage:'Покрытие',journal:'Ошибки и журнал',usage:'Использование'};
const params={key_rate:14,default_spread:3.06,equity_premium:8.89,growth:9.8};
const configuration={values:params,as_of:'2026-10-15',version:'reviewed-v2',reference_only:false};
const companies=[{ticker:'HMKB',company_name:'Hamkorbank',sector:'finance',nsbu_count:45,total_count:46},{ticker:'AGBA',company_name:'Агробанк',sector:'finance',nsbu_count:42,total_count:42}];
const rows=companies.map((company,i)=>({...company,name:company.company_name,kind:'bank',standard:'NSBU',scope:'separate',period:'2025',roe:i?20:25.43,roa:3.1,pb:1.36,pe:8.38,ep:11.93,dy:12,cg5:10,de:null,price:97.44,market_date:'2026-10-15',issues:[]}));
export async function setupCatalogPages(page,{theme='light',width=1440,lang='ru',func='PL',beforeNavigate}={}){
 await page.setViewportSize({width,height:900});
 await page.addInitScript(({theme,lang})=>{
  localStorage.setItem('uz_stock_analyzer_theme',theme);localStorage.setItem('uz_stock_analyzer_language',lang);localStorage.setItem('uz_stock_analyzer_token','catalog-fixture');
  localStorage.setItem('uz_track_internal','1');sessionStorage.setItem('uz_sponsor_seen','1');
 },{theme,lang});
 let preferences={terminal_layout:[{ticker:'HMKB',func:'PL',form:'NSBU',scope:'separate'},{ticker:'AGBA',func:'FV',form:'NSBU',scope:'separate'}]};
 await page.route('**/api/**',route=>{
  const url=new URL(route.request().url()),p=url.pathname,json=body=>route.fulfill({json:body});
  if(p==='/api/auth/me')return json({user:{id:1,is_admin:true,email:'catalog@example.test'}});
  if(p==='/api/profile')return json({preferences});
  if(p==='/api/profile/preferences'){preferences=route.request().postDataJSON();return json({ok:true,preferences});}
  if(p==='/api/catalog/companies')return json({ok:true,companies});
  if(p.startsWith('/api/catalog/index/'))return json({ok:true,company_name:companies.find(c=>p.endsWith(c.ticker))?.company_name,availability:{NSBU:{annual:[2025,2024,2023].map(year=>({year,quarter:0,published_at:`${year+1}-04-12`,excel_url:'https://openinfo.uz/reports/fixture.xlsx'})),quarter:[{year:2026,quarter:3,published_at:'2026-10-28',pdf_url:'https://openinfo.uz/reports/fixture.pdf'}]},Audition:{annual:[{year:2025,quarter:0,published_at:'2026-06-01',pdf_url:'https://openinfo.uz/reports/audit.pdf'}]}}});
  if(p.endsWith('/financials/columns'))return json({...columns,published_ratios:overview.published_ratios});
  if(p.endsWith('/financials'))return json({ok:true,...bank.financial_series,data_gaps:[{period:'2024Q3',code:'REPORT_UNAVAILABLE'}]});
  if(p.endsWith('/ai-report'))return json({...bank.report,ok:true});
  if(p==='/api/terminal/screener')return json({ok:true,rows,years:[2025,2024],standard:'NSBU',scope:'separate'});
  if(p.endsWith('/analytics'))return json({ok:true,snapshot:rows[0],growth:[],quarters:{rows:[]},deposit:{value:20.6,period:'2026-09',source_url:'https://cbu.uz'},dividend:{decision:{decision_date:'2026-05-12'}}});
  if(p.endsWith('/reconciliation'))return json({ok:true,same_scope:false,nsbu_scope:'separate',ifrs_scope:'consolidated',rows:[{field:'net_profit',period:'2025',nsbu:1704e9,ifrs:1820e9,difference:116e9}]});
  if(p.startsWith('/api/audit/badge/'))return json({ok:true,status:'warning',blocking:0,warnings:1,last_run_at:'2026-11-03T12:00:00',metrics_withheld:[],reasons:['Отчёт за третий квартал 2024 года не найден в реестре']});
  if(p.startsWith('/api/news/ticker/'))return json({ok:true,items:[{id:501,title:'Hamkorbank опубликовал отчёт за девять месяцев 2026 года',title_ru:'Hamkorbank опубликовал отчёт за девять месяцев 2026 года',published_at:'2026-10-28T08:00:00',source_name:'openinfo.uz',url:'https://openinfo.uz'},{id:502,title:'Решения общего собрания акционеров Hamkorbank',title_ru:'Решения общего собрания акционеров Hamkorbank',published_at:'2026-05-12T08:00:00',source_name:'openinfo.uz',url:'https://openinfo.uz'}]});
  if(p.startsWith('/api/dividends/'))return json({ok:true,items:[]});
  if(p.startsWith('/api/admin/terminal/valuation/')){
   const band=(value,low,high)=>({value,low,high,unit:'UZS/share'});
   return json({ok:true,ticker:p.split('/').at(-1),period:'2025',standard:'NSBU',scope:'separate',configuration,parameters:params,required_return:19.83,current_price:97.44,market_date:'2026-10-15',summary:{value:80,low:70,high:110,price_to_value_pct:121.8,method_count:3},models:{peers_pb:{per_share:band(70,60,90),peer_count:5,multiple:1.36},peers_pe:{per_share:band(110,90,130),peer_count:4,multiple:8.38},justified_pb:{per_share:band(80,72,89),value:1.55},gordon:{per_share:{value:null,reason:'RECENT_DIVIDEND_UNAVAILABLE'}}},inputs:{roe:25.43}});
  }
  if(p==='/api/admin/terminal/valuations')return json({ok:true,rows:[],configuration});
  if(p==='/api/admin/terminal/templates')return json({ok:true,version:'nsbu-core-2.5',assignments:[{ticker:'HMKB',selected_template:'bank',reason_code:'filing_form',rule_version:'2.5'}],formulas:[{code:'P1',name_ru:'Доходность активов на конец периода',numerators:['form2:c270'],denominators:['form1:c400']}],valuation:configuration});
  if(p==='/api/admin/control/rules')return json({items:[{id:'ratio-review',version:2,title:'Проверка годовых показателей',category:'formula',status:'DRAFT',config:{code:'P1'}}]});
  if(p==='/api/admin/terminal/dashboard')return json({ok:true,summary:{quarantine:2,verdict_conflicts:0,ai_published:18,ai_published_change:3,hour_error_pct:.4,slow_pct:2.3},usage:{commands:86,unknown:2,unknown_pct:2.3,functions:[{name:'PL',count:32},{name:'SUM',count:26},{name:'FV',count:18}],tickers:[{name:'HMKB',count:42},{name:'AGBA',count:31}]}});
  if(p==='/api/admin/terminal/coverage')return json({ok:true,annual_coverage_pct:95,periods:['2023','2024','2025','2026Q3'],rows:companies.map(c=>({ticker:c.ticker,name:c.company_name,cells:{2023:'backfill',2024:'loaded',2025:'loaded','2026Q3':'gap'}}))});
  if(p==='/api/admin/terminal/events')return json({ok:true,total:1,items:[{id:1,ts:'2026-11-03 17:00',level_label:'Внимание',event:'source_unavailable',ticker:'HMKB',standard:'NSBU',period:'2026Q3',duration_ms:1430,error_id:'source-2026-11-03',message:'Исходный отчёт временно недоступен',source_url:'https://openinfo.uz'}]});
  return json({ok:true,items:[],rows:[],points:[],companies:[],rates:[],total_reports:88,companies_synced:2});
 });
 await beforeNavigate?.();
 await page.goto(`/catalog?t=HMKB&f=${func}`);
 await expect(page.locator('.financial-columns')).toBeVisible();
}
export async function openCatalogPage(page,code){
 if(code==='LAST'){const search=page.locator('.terminal-command').getByRole('combobox');await search.fill('HMKB BS');await search.press('Enter');await expect(page).toHaveURL(/f=BS/);}
 const command=code.startsWith('ADM-')?'ADM':(['EQS','MON','PNL','HELP','LAST'].includes(code)?code:`HMKB ${code}`);
 const search=page.locator('.terminal-command').getByRole('combobox');
 await search.fill(command);await search.press('Enter');
 if(code.startsWith('ADM-'))await page.locator('.terminal-admin-tabs').getByRole('button',{name:adminNames[code.slice(4)],exact:true}).click();
 const selector=catalogPages.find(([name])=>name===code)[1];await expect(page.locator(selector).first()).toBeVisible();
 // The selected tab precedes its request; wait for its content before measuring.
 await expect(page.locator('.catalog-layout [role="status"]').filter({hasText:/Загрузка|Расчёт оценки/})).toHaveCount(0);
 await page.evaluate(()=>document.fonts.ready);
}
