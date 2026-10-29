import test from 'node:test';
import assert from 'node:assert/strict';
import { historyScale, historySegments, historySeries, mergeHistoryPoints, historyContiguousTail } from '../frontend/src/features/currency/historyChart.js';

test('a tiny daily USD or RUB move does not stretch across the whole plot', () => {
  for (const values of [[12000,12004.02], [148.8,148.81], [12004.02,12004.02]]) {
    const scale = historyScale(values);
    assert.ok(scale.max - scale.min >= values[0] * 0.01);
    assert.ok(scale.ticks.length >= 3 && scale.ticks.length <= 8);
    assert.ok(scale.min <= Math.min(...values) && scale.max >= Math.max(...values));
  }
  const scale = historyScale([11806.97,12004.02]);
  assert.ok(scale.min < 11806.97 && scale.max > 12004.02);
});

test('missing observations break the line instead of implying known rates', () => {
  const points = [{value:11806.97},{value:11838.92},{value:null},{value:11918.98},{value:null},{value:12004.02}];
  assert.deepEqual(historySegments(points).map(segment => segment.map(p => p.index)), [[0,1],[3],[5]]);
  assert.deepEqual(historySegments([{value:null}]), []);
});


test('canvas history retains missing calendar days and never joins across gaps', () => {
  const points = [11806.97,11838.92,null,11918.98,null,12004.02].map((value,i)=>({date:`2026-10-${24+i}`,value}));
  const series = historySeries(points);
  assert.equal(series[0].key, 'history');
  assert.equal(series[0].options.lineVisible, false);
  assert.equal(series[0].data.length, 6);
  assert.deepEqual(series[0].data[2], {time:Date.parse('2026-10-26T00:00:00Z')/1000});
  assert.deepEqual(series.slice(1).map(s=>s.data.map(p=>p.value)), [[11806.97,11838.92],[11918.98],[12004.02]]);
  assert.equal(series[2].options.pointMarkersVisible, true);
});


test('earlier pages merge in calendar order without duplicates or replacing known rates with gaps', () => {
 const current=[{date:'2026-09-29',value:11806.97},{date:'2026-09-30',value:null}];
 const earlier=[{date:'2026-09-28',value:11810},{date:'2026-09-29',value:null},{date:'2026-09-30',value:11820}];
 const merged=mergeHistoryPoints(current,earlier);
 assert.deepEqual(merged.map(p=>[p.date,p.value]), [['2026-09-28',11810],['2026-09-29',11806.97],['2026-09-30',11820]]);
});


test('a partly fetched July page does not expose its unfilled dates as pannable history', () => {
 const page=[{date:'2026-06-28',value:12055},{date:'2026-07-10',value:null},{date:'2026-07-11',value:12025.37},{date:'2026-07-12',value:12004.02}];
 assert.deepEqual(historyContiguousTail(page),page.slice(2));
 assert.deepEqual(historyContiguousTail([{date:'2026-07-28',value:null}]),[]);
 assert.deepEqual(historyContiguousTail(page.slice(2)),page.slice(2));
});
