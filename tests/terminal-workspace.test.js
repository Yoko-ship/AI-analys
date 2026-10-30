import test from "node:test";
import assert from "node:assert/strict";
import { tableCsv, filterRows, normalizeLayout, screenUrl, screenFromUrl } from "../frontend/src/lib/terminalWorkspace.js";

test("Excel export preserves Cyrillic, quotes, zero and missing values without formulas", () => {
  assert.equal(tableCsv([["Эмитент", "Прибыль"], ['Кварц, "АО"', 0], ["=HYPERLINK(1)", null]]),
    '\uFEFFЭмитент,Прибыль\r\n"Кварц, ""АО""",0\r\n\'=HYPERLINK(1),\r\n');
});
test("numeric screening excludes missing values and compares dividends with the supplied rate", () => {
  const rows = [{ticker:"SQBN", roe:20, dy:19, de:null}, {ticker:"QZSM", roe:9, dy:10, de:2}, {ticker:"UZMT", roe:null, dy:null}];
  assert.deepEqual(filterRows(rows, {roe_min:"10"}).map(r=>r.ticker), ["SQBN"]);
  assert.deepEqual(filterRows(rows, {above_deposit:true}, 17.2).map(r=>r.ticker), ["SQBN"]);
  assert.deepEqual(filterRows(rows, {above_deposit:true}, null), []);
  assert.deepEqual(filterRows(rows, {de_max:"3"}).map(r=>r.ticker), ["QZSM"]);
});
test("only four valid independent panel screens are restored", () => {
  const good = {ticker:"AGBA", func:"PL", form:"MSFO", scope:"consolidated"};
  assert.equal(normalizeLayout(Array(6).fill(good)).length,4);
  assert.deepEqual(normalizeLayout([{ticker:"<script>",func:"SUM"},{ticker:"SQBN",func:"BAD"}]),[]);
  assert.deepEqual(normalizeLayout([good])[0],{...good,form:"NSBU",scope:"separate"});
});
test("market screens and history survive links while MSFO falls back to NSBU", () => {
  const screen = {ticker:"AGBA",func:"REC",form:"MSFO",scope:"consolidated",market:"EQS",fullHistory:true};
  const expected = {...screen,form:"NSBU",scope:"separate"};
  assert.deepEqual(screenFromUrl('/catalog?t=AGBA&f=REC&std=MSFO&scope=consolidated&view=EQS&h=all'),expected);
  assert.deepEqual(screenFromUrl(screenUrl(screen)),expected);
  assert.equal(screenUrl(screen).includes('MSFO'),false);
  assert.deepEqual(screenFromUrl(screenUrl(expected)),expected);
});

test("USD projection uses each report-end rate, leaves ratios intact and refuses missing rates", async () => {
  const { convertSeries, periodEnd } = await import('../frontend/src/lib/terminalCurrency.js');
  assert.equal(periodEnd('2025'), '2025-12-31');
  assert.equal(periodEnd('2026Q1'), '2026-03-31');
  assert.equal(periodEnd('2026Q2'), '2026-06-30');
  const source={profit:{money:true,values:{2024:24000,2025:26000}},roe:{money:false,values:{2025:12}}};
  const result=convertSeries(source,{'2024':{per_unit:12000}},'USD');
  assert.deepEqual(result.profit.values,{'2024':2,'2025':null});
  assert.equal(result.roe.values['2025'],12);
  assert.equal(source.profit.values['2025'],26000);
});

test("profit sparklines leave missing years disconnected and handle flat histories",async()=>{
  const { profitSparkline } = await import('../frontend/src/lib/terminalWorkspace.js');
  const chart=profitSparkline({'2020':10,'2021':null,'2022':20,'2023':20});
  assert.equal(chart.segments.length,2);
  assert.equal(chart.segments[0].length,1);
  assert.equal(chart.segments[1].length,2);
  assert.ok(profitSparkline({'2020':0,'2021':0}).segments.flat().every(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)));
});
