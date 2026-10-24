import test from 'node:test';
import assert from 'node:assert/strict';
import { financialsUrl } from '../frontend/src/lib/financialHistoryRequest.js';

test('ALKB NSBU history uses the same accepted request in overview and financial tabs', () => {
  const url = new URL(financialsUrl('ALKB', 'NSBU', 'separate', false), 'https://uzstock.uz');
  assert.equal(url.pathname, '/api/company/ALKB/financials');
  assert.equal(url.searchParams.get('form'), 'NSBU');
  assert.equal(url.searchParams.has('scope'), false);
});

test('IFRS quarterly history retains its selected perimeter', () => {
  const url = new URL(financialsUrl('ALKB', 'MSFO', 'consolidated', true), 'https://uzstock.uz');
  assert.equal(url.searchParams.get('scope'), 'consolidated');
  assert.equal(url.searchParams.get('freq'), 'quarterly');
});
