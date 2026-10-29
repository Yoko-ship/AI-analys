import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {chartWindow, chartScale, defaultChartMetrics} from '../frontend/src/features/company/financialChartViewport.js';

const data=JSON.parse(readFileSync('e2e/fixtures/hmkb-quarterly-chart.json','utf8'));
test('HMKB opens on recent quarters with three income totals, and earlier periods stay reachable',()=>{
  const recent=chartWindow(data.columns,0,8);
  assert.equal(recent.at(-1).label,'2026 Q3');
  assert.equal(recent[0].label,'2024 Q4');
  assert.equal(chartWindow(data.columns,999,8)[0].label,'2020 Q1');
  assert.equal(chartWindow(data.columns,0,3).length,3);
  assert.deepEqual(defaultChartMetrics(data.rows).map(r=>r.metric_id),['interest_income','interest_expense','net_interest_after_ecl']);
});
test('visible HMKB history gets a zero-based rounded scale without hidden future peaks',()=>{
  const row=data.rows.find(r=>r.metric_id==='interest_income');
  const early=data.columns.slice(0,4).map(c=>Number(row.cells[c.key].value));
  const scale=chartScale(early);
  assert.equal(scale.min,0);
  assert.equal(scale.max,500000000);
  assert.deepEqual(scale.ticks,[0,100000000,200000000,300000000,400000000,500000000]);
  for(const values of [[-310010000,670540000],[-5,-2],[0,0],[0.002,0.003],[]]) {
    const s=chartScale(values);
    assert.ok(s.min<=Math.min(0,...values));assert.ok(s.max>=Math.max(0,...values));
    assert.ok(s.max>s.min);assert.ok(s.ticks.includes(0));assert.ok(s.ticks.length<=7);
  }
});
