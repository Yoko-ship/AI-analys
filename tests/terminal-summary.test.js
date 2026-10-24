import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {summaryKpis, historyRows} from '../frontend/src/lib/terminalSummary.js';

const report=JSON.parse(readFileSync(new URL('./fixtures/sector_ui_report.json',import.meta.url),'utf8'));
const sectorReports=JSON.parse(readFileSync(new URL('./fixtures/terminal_sector_reports.json',import.meta.url),'utf8')).reports;

test('UZNF uses NAV and only reconciled per-share values, with separate quote dates',()=>{
  const fixture=JSON.parse(readFileSync(new URL('./fixtures/terminal_sector_reports.json',import.meta.url),'utf8'));
  const blocked=summaryKpis(fixture.reports.UZNF,{kind:'fund',price:6.75});
  assert.equal(blocked.kind,'fund');
  const byKey=result=>Object.fromEntries(result.cards.map(card=>[card.key,card]));
  const missing=byKey(blocked);
  assert.deepEqual(Object.keys(missing),['nav','nav_per_share','price_to_nav','premium_to_nav','net_profit','portfolio_to_assets']);
  assert.equal(missing.nav.value,29861539000000);
  assert.equal(missing.nav_per_share.value,null);
  assert.equal(missing.price_to_nav.value,null);
  const verified=byKey(summaryKpis(fixture.fund_verified_share_basis,{}));
  assert.ok(Math.abs(verified.nav_per_share.value-5.908189140571111)<1e-10);
  assert.equal(verified.nav_per_share.unit,'UZS/share');
  assert.equal(verified.price_to_nav.period,'2026-08-28');
  assert.ok(Math.abs(verified.premium_to_nav.value-14.248204304229766)<1e-10);
  assert.equal(verified.nav.period,'2025');
  const annual=byKey(summaryKpis(null,{kind:'fund',period:'2025',equity:29861539000000,price:6.75}));
  assert.equal(annual.nav.value,29861539000000);
  assert.equal(annual.price_to_nav.value,null);
});

test('UZAS overview uses earned premiums and insurance ratios instead of industrial margins',()=>{
  const result=summaryKpis(sectorReports.UZAS,{kind:'insurance',period:'2025'});
  const values=Object.fromEntries(result.cards.map(card=>[card.key,card.value]));
  assert.deepEqual(Object.keys(values),['earned_premiums','net_profit','combined_ratio','loss_ratio','roe','equity_to_assets']);
  assert.equal(values.earned_premiums,111891908500);
  assert.ok(Math.abs(values.combined_ratio-107.19683684723279)<1e-9);
  // Report type wins when the older annual snapshot has no classification.
  assert.deepEqual(summaryKpis(sectorReports.UZAS,{}).cards,result.cards);
});

test('UZMK summary uses verified H1 facts in UZS, not the previous annual or statutory P2',()=>{
  const result=summaryKpis(report,{kind:'industry',period:'2025',net_profit:1,roe:2});
  assert.equal(result.period,'2026Q2');
  const values=Object.fromEntries(result.cards.map(c=>[c.key,c.value]));
  assert.equal(values.net_profit,315887100000);
  assert.equal(values.revenue,3205904736000);
  assert.equal(values.roe,null);
  assert.ok(Math.abs(values.net_margin-9.853295)<.0001);
});

test('summary keeps incomplete or unverified facts unavailable, and never annualises a margin',()=>{
  const facts=[{metric_code:'net_income',value:0,unit:'thousand UZS'}, {metric_code:'revenue',value:100,unit:'thousand UZS'},
    {metric_code:'total_assets',value:200,unit:'USD'}, {metric_code:'gross_profit',value:20,unit:'thousand UZS',verification_status:'quarantined'}];
  const result=summaryKpis({status:'available',period:'2026Q2',verified_facts:facts,ratios:[{metric_code:'roe',value:7.2}]},{kind:'industry'});
  const values=Object.fromEntries(result.cards.map(c=>[c.key,c.value]));
  assert.equal(values.net_profit,0);
  assert.equal(values.net_margin,0);
  assert.equal(values.gross_margin,null);
  assert.equal(values.roe,7.2);
});

test('annual chart keeps missing years and incomplete balance components as gaps',()=>{
  const history={periods:['2025','2023','2020'],series:{net_profit:{values:{2023:-5e9,2025:0}},total_liabilities:{values:{2025:30e9}},total_equity:{values:{2023:20e9}}}};
  const rows=historyRows(history,2022);
  assert.deepEqual(rows.map(r=>r.period),['2023','2024','2025']);
  assert.equal(rows[0].net_profit,-5e9);
  assert.equal(rows[1].net_profit,null);
  assert.equal(rows[2].net_profit,0);
  assert.equal(rows[2].balance_complete,false);
});
