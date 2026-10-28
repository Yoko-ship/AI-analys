import {test,expect} from '@playwright/test';
const user={id:19,email:'reader@example.test',full_name:'Reader',email_verified:false};
async function account(page,state){
 await page.addInitScript(()=>{localStorage.setItem('uz_stock_analyzer_token','workspace-test');localStorage.setItem('uz_stock_analyzer_language','en');localStorage.setItem('uz_stock_analyzer_theme','light');sessionStorage.setItem('uz_sponsor_seen','1');});
 await page.route('**/api/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/api/profile/preferences'&&route.request().method()==='PATCH'){
   if(state.fail)return route.fulfill({status:503,json:{detail:'Unavailable'}});
   Object.assign(state.preferences,route.request().postDataJSON());return route.fulfill({json:{ok:true,preferences:state.preferences}});
  }
  return route.fulfill({json:path==='/api/auth/me'?{user}:path==='/api/profile'?{user,preferences:state.preferences,favorites:[],notes:[],security:{email_verified:false,two_factor_enabled:false}}:path==='/api/portfolio'?{ok:true,items:[],transactions:[],count:0,priced_count:0,instruments:[],valuation_complete:true}:path==='/api/market/stocks'?{stocks:[]}:{ok:true,items:[],companies:[],securities:{}}});
 });
}
test('account screeners are available in a second browser without local storage',async({page,browser})=>{
 const state={preferences:{}};await account(page,state);await page.goto('/market');
 const panel=page.getByTestId('saved-screeners');await panel.locator('summary').click();
 await panel.getByLabel('Filter name').fill('My banks');await panel.getByRole('button',{name:'Save filter',exact:true}).click();
 await expect.poll(()=>state.preferences.saved_screeners?.length).toBe(1);
 expect(await page.evaluate(()=>localStorage.getItem('uzstock:screeners:v1'))).toBeNull();
 await page.locator('.account-button').click();
 await page.getByRole('menuitem',{name:'Profile',exact:true}).click();
 await expect(page.getByTestId('profile-workspace-stats').locator('article').filter({hasText:'Saved screeners'}).locator('strong')).toHaveText('1');
 const other=await browser.newPage();await account(other,state);await other.goto('/market');
 await other.getByTestId('saved-screeners').locator('summary').click();
 await expect(other.getByLabel('Saved screeners', {exact:true}).locator('option')).toContainText(['Select…','My banks']);
 await other.close();
});
test('interests persist and security badges report the account state',async({page})=>{
 const state={preferences:{}};await account(page,state);await page.goto('/profile');
 await page.getByRole('button',{name:'Edit interests',exact:true}).click();
 await page.getByRole('dialog').getByLabel('Banks',{exact:true}).check();
 await page.getByRole('dialog').getByRole('button',{name:'Save interests',exact:true}).click();
 await expect.poll(()=>state.preferences.investment_interests).toEqual(['banks']);
 await page.reload();await expect(page.getByTestId('investment-interests')).toContainText('Banks');
 await expect(page.getByTestId('account-security-summary')).toContainText('Email not verified');
 await expect(page.getByTestId('account-security-summary')).toContainText('Two-factor off');
});
test('failed account save stays visible and is retryable',async({page})=>{
 const state={preferences:{},fail:true};await account(page,state);await page.goto('/market');
 const panel=page.getByTestId('saved-screeners');await panel.locator('summary').click();
 await panel.getByLabel('Filter name').fill('Retry');await panel.getByRole('button',{name:'Save filter',exact:true}).click();
 await expect(panel.getByRole('alert')).toBeVisible();await expect(panel.getByLabel('Filter name')).toHaveValue('Retry');
 expect(state.preferences.saved_screeners).toBeUndefined();
 state.fail=false;await panel.getByRole('button',{name:'Save filter',exact:true}).click();
 await expect.poll(()=>state.preferences.saved_screeners?.length).toBe(1);
});
test('profile retains the shared palette and complete investor workspace',async({page})=>{
 const state={preferences:{}};await account(page,state);await page.goto('/profile');
 expect(await page.evaluate(()=>getComputedStyle(document.body).getPropertyValue('--accent').trim())).toBe('#6257d9');
 await expect(page.getByTestId('profile-workspace-stats').locator('article')).toHaveCount(4);
 await page.getByRole('button',{name:'My portfolio',exact:true}).click();await expect(page.getByTestId('portfolio-market-value')).toBeVisible();
});
test('legacy personal feed links show all corporate events and retain optional sorting',async({page})=>{
 const state={preferences:{investment_interests:['banks']}};await account(page,state);
 await page.route('**/api/securities',r=>r.fulfill({json:{ok:true,securities:{HMKB:{sector:'banks'}}}}));
 await page.route('**/api/portfolio',r=>r.fulfill({json:{ok:true,items:[{ticker:'UZMK'}]}}));
 const story=(id,ticker)=>({story_id:id,id,source_url:'https://openinfo.uz/ru/facts/6/1',category:'governance',priority:2,published_at:'2026-10-26',title:{en:'Board changed'},organization:ticker,tickers:[ticker],stage:'disclosed',documents:[],document_count:1});
 await page.route('**/api/news/corporate-events?**',r=>r.fulfill({json:{ok:true,items:[story('1','HMKB'),story('2','UZMK'),story('3','OTHER')],categories:{governance:{en:'Governance'}},facts:{}}}));
 await page.goto('/news?tab=corporate&mode=personal');
 await expect(page.locator('.ce-story')).toHaveCount(3);
 await expect(page.getByRole('button',{name:/^(All events|Important|My companies|For you)$/})).toHaveCount(0);
 await page.reload();
 await expect(page.locator('.ce-story')).toHaveCount(3);
 await page.getByLabel('Event order').selectOption('subscriptions');
 await expect(page.locator('.ce-story')).toHaveCount(3);
 await expect(page.locator('.ce-story').first()).toContainText('UZMK');
});
