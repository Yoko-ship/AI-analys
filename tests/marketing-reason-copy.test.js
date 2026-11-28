import test from 'node:test';
import assert from 'node:assert/strict';
import { reasonText } from '../frontend/src/admin/marketing/reasonCopy.js';

const occasion = 'An occasion does not confirm exchange schedule; use an exact checked source statement or remove the claim';
const media = 'Rendered media no longer matches this text and its original versions';

test('combined validation reasons preserve and translate a known message containing a semicolon', () => {
  const result = reasonText(`${occasion}; ${media}`);
  assert.match(result, /Повод не подтверждает расписание биржи/);
  assert.match(result, /Медиа больше не соответствует/);
  assert.doesNotMatch(result, /An occasion|use an exact/);
});

test('source-bound item prefixes also retain a compound known reason', () => {
  const result = reasonText(`Calendar item 2: ${occasion}; ${media}`);
  assert.match(result, /^Пункт календаря 2: Повод не подтверждает расписание биржи/);
  assert.match(result, /Медиа больше не соответствует/);
});
