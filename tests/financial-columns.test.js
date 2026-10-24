import test from 'node:test';
import assert from 'node:assert/strict';
import { financialGroup } from '../frontend/src/features/company/financialColumnGroups.js';

test('summary separates assets, equity and debt using each source form namespace', () => {
  assert.equal(financialGroup({ source_form: 'F1', source_code: '490' }, 'summary'), 'DEBT');
  assert.equal(financialGroup({ source_form: 'INSURANCE_BS', source_code: '490' }, 'summary'), 'ASSETS');
  assert.equal(financialGroup({ source_form: 'INSURANCE_BS', source_code: '570' }, 'summary'), 'EQUITY');
  assert.equal(financialGroup({ source_form: 'BANK_BS', source_code: '26б' }, 'summary'), 'EQUITY');
  assert.equal(financialGroup({ source_form: 'BS', metric_id: 'preferred_share_liability' }, 'summary'), 'DEBT');
  assert.equal(financialGroup({ source_form: 'F1', source_code: '490' }, 'original'), 'F1');
});
