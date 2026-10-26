import {test} from 'node:test';import assert from 'node:assert/strict';
import {mapAreaValue} from '../frontend/src/features/market/mapArea.js';
test('map area is independent from direction and uses only the selected measure',()=>{
 const row={changePercent:-5,stockVolume:120,marketCap:500};
 assert.equal(mapAreaValue(row,'turnover'),120);assert.equal(mapAreaValue(row,'capitalization'),500);
 assert.equal(mapAreaValue(row,'equal'),1);assert.equal(mapAreaValue(row,'movement'),5);
 assert.equal(mapAreaValue({},'capitalization'),0);
});
