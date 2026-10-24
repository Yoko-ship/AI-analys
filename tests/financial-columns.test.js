import test from 'node:test';
import assert from 'node:assert/strict';
import { financialGroup } from '../frontend/src/features/company/financialColumnGroups.js';
import { financialChartRows } from '../frontend/src/features/company/financialColumnChart.js';
import { readFileSync } from 'node:fs';

test('HMKB compound overview cells retain distinct chart series and source values', () => {
  const data=JSON.parse(readFileSync('e2e/fixtures/hmkb-recent-reports.json','utf8'));
  const charts=financialChartRows(data.overview_rows,data.columns);
  const loans=charts.find(r=>r.label==='Кредиты и лизинговые операции, брутто · 7а');
  const leases=charts.find(r=>r.label==='Кредиты и лизинговые операции, брутто · 7б');
  assert.equal(loans.cells['2026-09-30'].value,'30361825389');
  assert.equal(leases.cells['2026-09-30'].value,'1056352067');
  assert.equal(loans.cells['2025'].value,'23274799997');
  assert.equal(data.overview_rows.find(r=>r.id==='reference:gross_loans').cells['2025'].value,null);
  assert.ok(!charts.some(r=>r.id==='reference:gross_loans'));
});

test('chart components match source identities across periods, retaining zero but excluding blocked data',()=>{
  const part=(code,value,quality='valid')=>({source_form:'BS',source_code:code,value,quality});
  const rows=[{id:'r',label:'Assets',cells:{
    a:{display_parts:[part('a','10'),part('b','20')]},
    b:{display_parts:[part('b','0'),part('a','100','blocked'),part('c','40','blocked')]},
  }}];
  const result=financialChartRows(rows,[{key:'a'},{key:'b'}]);
  assert.deepEqual(result.map(r=>r.label),['Assets · a','Assets · b']);
  assert.equal(result[1].cells.b.value,'0');
  assert.equal(result[0].cells.b.quality,'blocked');
  assert.deepEqual(financialChartRows(rows,[{key:'z'}]),[]);
});

test('summary separates assets, equity and debt using each source form namespace', () => {
  assert.equal(financialGroup({ source_form: 'F1', source_code: '490' }, 'summary'), 'DEBT');
  assert.equal(financialGroup({ source_form: 'INSURANCE_BS', source_code: '490' }, 'summary'), 'ASSETS');
  assert.equal(financialGroup({ source_form: 'INSURANCE_BS', source_code: '570' }, 'summary'), 'EQUITY');
  assert.equal(financialGroup({ source_form: 'BANK_BS', source_code: '26б' }, 'summary'), 'EQUITY');
  assert.equal(financialGroup({ source_form: 'BS', metric_id: 'preferred_share_liability' }, 'summary'), 'DEBT');
  assert.equal(financialGroup({ source_form: 'F1', source_code: '490' }, 'original'), 'F1');
});
