import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {normalizeHistory, periodReturn, buildReturns, rankReturns, readReturns, returnsQuery} from '../frontend/src/features/comparison/returnsModel.js';

const points = [
  {date:'2025-12-30',close:100}, {date:'2026-01-15',close:110},
  {date:'2026-01-30',close:120}, {date:'2026-02-27',close:90},
  {date:'2026-04-30',close:99}, {date:'2026-05-12',close:108.9},
];
test('calendar returns use the preceding close and compound totals, never sum percentages', () => {
  const result = buildReturns(points,'2026-01','2026-02','2026-05-12');
  assert.ok(Math.abs(result.months['2026-01'].value - 20) < 1e-9);
  assert.equal(result.months['2026-02'].value,-25);
  assert.ok(Math.abs(result.total.value + 10) < 1e-9);
  assert.deepEqual(result.years['2026'],result.total);
  assert.equal(result.total.base.date,'2025-12-30');
});
test('missing months stay missing, stale bases are disclosed, partial years respect selected months', () => {
  const result = buildReturns(points,'2026-02','2026-05','2026-05-12');
  assert.equal(result.months['2026-03'].status,'no_trades');
  assert.equal(result.months['2026-03'].value,null);
  assert.equal(result.months['2026-04'].stale,true);
  assert.equal(result.months['2026-04'].base.date,'2026-02-27');
  assert.equal(result.months['2026-05'].partial,true);
  assert.ok(Math.abs(result.years['2026'].value + 9.25) < 1e-9);
  assert.equal(result.years['2026'].partial,true);
  assert.equal(periodReturn(points,'2025-12','2025-12','2026-05-12').status,'no_base');
  assert.equal(periodReturn(points,'2026-06','2026-06','2026-05-12').status,'future');
});
test('unsorted histories normalize dates, discard invalid prices and ignore data after the market anchor', () => {
  const messy = [...points].reverse().concat([{date:'2026-02-31',close:1},{date:'20260601',close:500},
    {date:'2026-01-31',close:0},{date:'2026-02-28',close:null},{date:'2026-02-26',close:Infinity}]);
  const normalized = normalizeHistory(messy,'2026-05-12');
  assert.deepEqual(normalized.filter(p=>p.close!==null),points);
  assert.equal(periodReturn(normalized,'2026-02','2026-02','2026-05-12').value,null);
});
test('MIQE real archive cannot imply a monthly return without a prior-month baseline', () => {
  const miqe=JSON.parse(readFileSync(new URL('./fixtures/miqe_price_history.json',import.meta.url),'utf8')).results;
  const cell=periodReturn(miqe,'2026-09','2026-09','2026-09-11');
  assert.equal(cell.value,null); assert.equal(cell.status,'no_base');
});
test('relative view ranks returns without changing their values, with missing observations last', () => {
  const rows=[{ticker:'HMKB',value:-10},{ticker:'IPKY',value:0},{ticker:'SQBN',value:null},{ticker:'UZTL',value:20}];
  assert.deepEqual(rankReturns(rows).map(x=>x.ticker),['UZTL','IPKY','HMKB','SQBN']);
  assert.equal(rows[0].ticker,'HMKB');
});
test('a total whose last quote precedes the ending month discloses the stale endpoint', () => {
  const cell=periodReturn(points,'2026-01','2026-11','2026-11-13');
  assert.equal(cell.staleEnd,true);
  assert.equal(cell.end.date,'2026-05-12');
  assert.equal(periodReturn(points,'2026-01','2026-05','2026-05-12').staleEnd,false);
});
test('returns URLs round trip and validate dates, duplicate tickers and display modes', () => {
  const state=readReturns('?companies=HMKB,IPKY,HMKB&from=2026-01&to=2026-05&layout=relative&frequency=annual');
  assert.deepEqual(readReturns(returnsQuery(state)),state);
  assert.deepEqual(state.tickers,['HMKB','IPKY']);
  assert.equal(readReturns('?from=2026-13&to=garbage').from,'');
  assert.equal(readReturns('?layout=evil').layout,'heatmap');
});

test('conflicting same-day prices withhold affected returns in either order, while identical duplicates are safe', () => {
  const conflict=[...points,{date:'20260130',close:125}];
  for(const rows of [conflict,[...conflict].reverse()]) {
    const normalized=normalizeHistory(rows);
    assert.equal(normalized.find(p=>p.date==='2026-01-30').close,null);
    assert.equal(periodReturn(normalized,'2026-01','2026-01','2026-05-12').status,'ambiguous');
    assert.equal(periodReturn(normalized,'2026-02','2026-02','2026-05-12').value,null);
    assert.ok(Math.abs(periodReturn(normalized,'2026-05','2026-05','2026-05-12').value-10)<1e-9);
  }
  assert.deepEqual(normalizeHistory([...points,{date:'20260130',close:120}]),points);
});

test('HMKB conflicting March 17 archive entries cannot hide clear recent returns',()=>{
  const archive=[30.49,30.83,30.9,29.21,30.5,31.19].map(close=>({date:'2024-03-17',close}));
  for(const rows of [archive,[...archive].reverse()]) {
    const normalized=normalizeHistory([...rows,...points]);
    assert.equal(normalized[0].close,null);
    assert.ok(Math.abs(periodReturn(normalized,'2026-01','2026-01','2026-05-12').value-20)<1e-9);
  }
});

test('dated invalid closes remain unknown endpoints and baselines instead of using an older quote',()=>{
  for(const close of [null,0,-1,NaN,Infinity,'120']) {
    const rows=[...points,{date:'2026-01-31',close}];
    for(const month of ['2026-01','2026-02']) {
      const result=periodReturn(rows,month,month,'2026-05-12');
      assert.equal(result.value,null);
      assert.equal(result.status,'ambiguous');
    }
  }
});

test('a carry-forward-only month is missing and cannot refresh the baseline age',()=>{
  const rows=[{date:'2026-02-27',close:90,volume:10,value:900},
    {date:'2026-03-31',close:90,volume:0,value:0},
    {date:'2026-04-30',close:99,volume:10,value:990}];
  assert.equal(periodReturn(rows,'2026-03','2026-03','2026-04-30').status,'no_trades');
  const april=periodReturn(rows,'2026-04','2026-04','2026-04-30');
  assert.equal(april.base.date,'2026-02-27');
  assert.equal(april.stale,true);
});
