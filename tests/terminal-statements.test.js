import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {profitBridge,assetComposition} from '../frontend/src/lib/terminalStatements.js';
const report=JSON.parse(readFileSync(new URL('./fixtures/sector_ui_report.json',import.meta.url),'utf8'));

test('UZNF bridge separates dividends from revaluation and shows the investment portfolio in assets',()=>{
  const fund=JSON.parse(readFileSync(new URL('./fixtures/terminal_sector_reports.json',import.meta.url),'utf8')).reports.UZNF;
  const steps=profitBridge(fund,'fund');
  assert.equal(steps[0]?.key,'dividend_income');
  assert.equal(steps.find(step=>step.key==='unrealized_fair_value_gain')?.value,1662300000000);
  assert.equal(steps.at(-1)?.value,1403150000000);
  assert.equal(steps.filter(step=>!step.total).reduce((sum,step)=>sum+step.value,steps[0].value),steps.at(-1).value);
  const assets=assetComposition(fund,'fund');
  assert.ok(assets.rows.find(row=>row.key==='portfolio_fair_value').share>99);
  assert.equal(assets.reason,null);
  const missing={...fund,verified_facts:fund.verified_facts.filter(f=>f.metric_code!=='management_expenses')};
  assert.equal(profitBridge(missing,'fund').find(step=>step.derived).value,null);
});

test('UZAS insurance bridge reconciles earned premiums, claims, expenses and profit',()=>{
  const insurer=JSON.parse(readFileSync(new URL('./fixtures/terminal_sector_reports.json',import.meta.url),'utf8')).reports.UZAS;
  const steps=profitBridge(insurer,'insurance');
  assert.equal(steps[0]?.value,111891908500);
  assert.equal(steps.find(step=>step.key==='insurance_service_cost').value,-50911399200);
  let running=0;
  for(const step of steps){
    assert.notEqual(step.value,null);
    if(step.total){assert.ok(Math.abs(running-step.value)<1||running===0);running=step.value;}
    else running+=step.value;
  }
  assert.equal(running,294295900);
});

test('UZMK revenue-to-profit bridge reconciles to published profit and labels residuals',()=>{
  const steps=profitBridge(report,'industry');
  assert.equal(steps[0].value,3205904736000);
  assert.equal(steps.at(-1).value,315887100000);
  let running=0;
  for(const step of steps){
    assert.notEqual(step.value,null);
    if(step.total){assert.ok(Math.abs(running-step.value)<1||running===0);running=step.value;}
    else running+=step.value;
  }
  assert.ok(steps.some(step=>step.derived));
});

test('missing bridge inputs break the bridge rather than fabricating zero expenses',()=>{
  const partial={status:'available',period:'2025',verified_facts:[{metric_code:'revenue',value:100,unit:'UZS'},{metric_code:'net_income',value:10,unit:'UZS'}]};
  const steps=profitBridge(partial,'industry');
  assert.equal(steps.find(step=>step.key==='cost_of_sales').value,null);
  assert.equal(steps.find(step=>step.key==='other_operating').value,null);
  assert.equal(steps.at(-1).value,10);
});

test('asset composition includes an explicit residual but never a negative other-assets slice',()=>{
  const result=assetComposition(report,'industry');
  assert.ok(result.rows.some(row=>row.key==='construction_in_progress'));
  assert.ok(Math.abs(result.rows.reduce((total,row)=>total+row.share,0)-100)<.00001);
  const bad={...report,verified_facts:report.verified_facts.map(f=>f.metric_code==='total_assets'?{...f,current:1,value:1}:f)};
  assert.equal(assetComposition(bad,'industry').reason,'COMPONENTS_EXCEED_ASSETS');
  assert.equal(assetComposition(bad,'industry').rows.some(row=>row.key==='other'),false);
});
