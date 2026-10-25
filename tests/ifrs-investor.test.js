import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {amount,columnsFor,selectedColumn,statementCsv,metricRow,ratioColumn,fundingShare} from '../frontend/src/features/company/investor/model.js';
const report=JSON.parse(readFileSync('e2e/fixtures/ifrs-investor.json','utf8'));
test('missing funding components cannot masquerade as zero capital',()=>{
  assert.equal(fundingShare(100,null,100),null);
  assert.equal(fundingShare(100,100,null),null);
  assert.equal(fundingShare(100,0,100),0);
  assert.equal(fundingShare(100,30,70),.3);
});
test('interim ratios use the same-date stock column when TTM is not applicable',()=>{
  const data={columns:[{key:'old',end:'2024-06-30',basis:'ytd'},{key:'now',end:'2025-06-30',basis:'ytd'},{key:'ttm',end:'2025-06-30',basis:'ttm'}]};
  assert.equal(ratioColumn(data,{cells:{now:{value:'30',quality:'valid'},ttm:{quality:'not_applicable'}}}).key,'now');
  assert.equal(ratioColumn(data,{cells:{old:{value:'30',quality:'valid'},ttm:{quality:'missing'}}}).key,'ttm');
});
test('investor display converts only source thousands, retaining zero and blocked values',()=>{
  assert.equal(amount({value:'5400000000',quality:'valid'},'UZS_thousand'),5400);
  assert.equal(amount({value:'0',quality:'valid'},'UZS_thousand'),0);
  assert.equal(amount({value:'100',quality:'blocked'},'UZS_thousand'),null);
  assert.equal(amount({value:'12.5',quality:'valid'},'percent'),12.5);
});
test('stock columns never include TTM, but flow columns do',()=>{
  const interim={...report,columns:[...report.columns,{key:'ttm:2026-06-30',end:'2026-06-30',basis:'ttm'}]};
  assert.ok(columnsFor(interim,'bs').every(c=>c.basis!=='ttm'));
  assert.ok(columnsFor(interim,'pl').some(c=>c.basis==='ttm'));
  assert.notEqual(selectedColumn(interim,'stock').basis,'ttm');
});
test('CSV follows the displayed detail selection and does not export another statement',()=>{
  const csv=statementCsv(report,'pl',false);
  assert.ok(csv.includes('Процентные доходы'));
  assert.ok(!csv.includes('Прибыль собственников материнской компании'));
  assert.ok(!csv.includes('ВСЕГО АКТИВЫ'));
  assert.ok(csv.includes('млрд UZS'));
  assert.equal(metricRow(report,'assets').metric_id,'total_assets');
});
