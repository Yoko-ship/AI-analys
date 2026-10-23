import test from 'node:test';
import assert from 'node:assert/strict';
import { register } from 'node:module';
register('data:text/javascript,' + encodeURIComponent(`export async function load(url, context, next) {
  return url.endsWith('.jsx') ? next(url, { ...context, format: 'module' }) : next(url, context);
}`));
const model = () => import('../frontend/src/features/comparison/model.js');
const {pathToView, viewToPath} = await import('../frontend/src/app/routing.jsx');
const state = {tickers:['HMKB'],period:'2025',standard:'NSBU',scope:'separate',unit:'billion'};
const data = {ok:true,period:'2025',standard:'NSBU',scope:'separate',companies:[{ticker:'HMKB',family:'bank',metrics:{net_profit:{value:1704969118000,status:'reported',source:{url:'https://openinfo.uz/ru/reports/to_pdf31438/'},change:19.5}}}]};

test('comparison routes are public and localized',()=>{
 assert.equal(pathToView('/compare').view,'companyCompare');assert.equal(pathToView('/uz/compare').view,'companyCompare');
 assert.equal(viewToPath('companyCompare',null,null,null,'uz'),'/uz/compare');
});
test('URLs accept the real issuer universe and arbitrary valid historical periods',async()=>{
 const {readComparison,comparisonQuery}=await model();
 const s=readComparison('?companies=UZMK,HMKB,UZMK,IPKY,SQBN,TRSB&period=2023Q1');
 assert.deepEqual(s.tickers,['UZMK','HMKB','IPKY','SQBN']);assert.equal(s.period,'2023Q1');
 assert.deepEqual(readComparison(comparisonQuery(s)),s);
 assert.equal(readComparison('').period,'latest');assert.deepEqual(readComparison('?companies=').tickers,[]);
});
test('only a matching backend response supplies figures; fixtures never fill a gap',async()=>{
 const {comparisonValue}=await model();
 assert.equal(comparisonValue('HMKB','net_profit',state,data).value,1704969118000);
 assert.equal(comparisonValue('HMKB','net_profit',state,null).value,null);
 assert.equal(comparisonValue('HMKB','net_profit',{...state,period:'2024'},data).value,null);
 assert.equal(comparisonValue('HMKB','net_profit',{...state,standard:'IFRS'},data).value,null);
 assert.equal(comparisonValue('HMKB','net_profit',{...state,scope:'consolidated'},data).value,null);
});
test('export uses backend values and source evidence, with one display-unit conversion',async()=>{
 const {comparisonCsv,formatComparisonValue,METRICS}=await model();
 assert.equal(formatComparisonValue(1704969118000,METRICS.find(m=>m.key==='net_profit'),state,'en'),'1,704.969');
 const csv=comparisonCsv(state,'en',data);
 assert.match(csv,/HMKB/);assert.match(csv,/openinfo\.uz/);assert.match(csv,/2025/);
 assert.doesNotMatch(csv,/Sample|undefined|NaN|Infinity/);
 assert.equal(comparisonCsv(state,'en',null),'');
});
