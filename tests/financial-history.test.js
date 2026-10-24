import test from 'node:test';
import assert from 'node:assert/strict';
import {continuousPoints} from '../frontend/src/lib/financialHistory.js';

test('financial lines cannot bridge an absent year or a missing value',()=>{
  assert.deepEqual(continuousPoints({'2022':10,'2023':20,'2025':30},['2022','2023','2025']).map(segment=>segment.map(point=>point.period)),[['2022','2023'],['2025']]);
  assert.deepEqual(continuousPoints({'2022':10,'2023':null,'2024':0},['2022','2023','2024']).map(segment=>segment.map(point=>point.value)),[[10],[0]]);
});

test('quarterly continuity crosses the year boundary but not a missing quarter',()=>{
  assert.deepEqual(continuousPoints({'2024Q4':-5,'2025Q1':0,'2025Q3':3},['2024Q4','2025Q1','2025Q3']).map(segment=>segment.map(point=>point.period)),[['2024Q4','2025Q1'],['2025Q3']]);
});
