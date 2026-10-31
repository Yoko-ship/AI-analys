import test from 'node:test';
import assert from 'node:assert/strict';
import {reportPeriodLabel, reportDateLabel, reportScopeLabel} from '../frontend/src/lib/reportingLabels.js';

test('report periods describe cumulative months instead of quarter codes', () => {
  assert.equal(reportPeriodLabel('2026Q1', 'ru'), 'январь–март 2026');
  assert.equal(reportPeriodLabel('2026Q2', 'ru'), 'январь–июнь 2026');
  assert.equal(reportPeriodLabel('2026Q3', 'ru'), 'январь–сентябрь 2026');
  assert.equal(reportPeriodLabel('2026Q4', 'ru'), '2026');
  assert.equal(reportPeriodLabel('2025', 'ru'), '2025');
  assert.equal(reportPeriodLabel('2026Q3', 'en'), 'January–September 2026');
  assert.equal(reportPeriodLabel('2026Q3', 'uz'), '2026-yil yanvar–sentabr');
  assert.equal(reportPeriodLabel('2026Q3', 'ru', true), '9 мес. 2026');
  assert.equal(reportPeriodLabel('2026Q3', 'en', true), '9 months 2026');
  assert.equal(reportPeriodLabel('2026Q3', 'uz', true), '2026 · 9 oy');
});

test('reporting dates retain their calendar date and reject missing or invalid values', () => {
  assert.equal(reportDateLabel('2026-09-30', 'ru'), '30 сентября 2026 г.');
  assert.equal(reportDateLabel('2026-09-30', 'en'), 'September 30, 2026');
  assert.equal(reportDateLabel('2026-09-30', 'uz'), '30-sentabr, 2026');
  assert.equal(reportPeriodLabel('2026-09-30', 'en'), 'September 30, 2026');
  for (const period of [null, '', '2026Q5', '2026-02-30', 'internal_code']) {
    assert.equal(reportPeriodLabel(period, 'ru'), '—');
  }
  assert.equal(reportDateLabel('2024-02-29', 'ru'), '29 февраля 2024 г.');
});

test('reporting scopes tell readers whether the numbers cover a company or a group', () => {
  assert.equal(reportScopeLabel('separate', 'ru'), 'Отчётность компании');
  assert.equal(reportScopeLabel('consolidated', 'ru'), 'Отчётность группы компаний');
  assert.equal(reportScopeLabel('separate', 'uz'), 'Kompaniya hisoboti');
  assert.equal(reportScopeLabel('consolidated', 'en'), 'Group financial statements');
  assert.equal(reportScopeLabel('unknown', 'ru'), 'Состав отчётности не уточнён');
});
