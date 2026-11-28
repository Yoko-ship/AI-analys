import test from 'node:test';
import assert from 'node:assert/strict';

test('product observation retries preserve the exact receipt and omit unapproved fields', async t => {
  t.mock.method(globalThis.crypto, 'randomUUID', () => '00000000-0000-4000-8000-000000000999');
  const sent = [], values = new Map();
  globalThis.localStorage = { getItem: k => values.get(k) ?? null, setItem: (k,v) => values.set(k,String(v)), removeItem: k => values.delete(k) };
  globalThis.window = { location: { search: '' }, innerWidth: 1000, innerHeight: 800, scrollY: 0, addEventListener() {} };
  globalThis.document = { referrer: '', visibilityState: 'visible', documentElement: { scrollHeight: 1200 }, body: {}, addEventListener() {} };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { sendBeacon: () => true } });
  const track = await import('../frontend/src/lib/track.js');
  const actions = await import('../frontend/src/lib/productActions.js');
  localStorage.setItem('uz_stock_analyzer_token', 'synthetic-token');
  track.setTrackedUser(23);
  globalThis.fetch = async (url, options) => { if (url === '/api/track/actions') sent.push({ url, ...options }); return { ok: sent.length > 1, status: 503 }; };
  track.trackPageview({ path: '/company/UZTL', view: 'company', ticker: 'UZTL' });
  const delays = [];
  const result = await actions.sendProductAction({ kind: 'issuer_open', ticker: 'UZTL', language: 'en', query: 'private@example.test', uid: 999 },
    { delay: async ms => delays.push(ms) });
  assert.equal(result, true);
  assert.deepEqual(delays, [1000]);
  assert.equal(sent.length, 2);
  assert.equal(sent[0].body, sent[1].body);
  assert.equal(sent[0].headers.Authorization, 'Bearer synthetic-token');
  const event = JSON.parse(sent[0].body);
  assert.equal(Object.hasOwn(event, 'query'), false);
  assert.equal(Object.hasOwn(event, 'uid'), false);
  assert.equal(event.kind, 'issuer_open');
  assert.match(event.event_id, /^[0-9a-f-]{36}$/);
  sent.length = 0;
  assert.equal(await actions.sendProductAction({ kind: 'report_open', ticker: 'UZTL', language: 'en' }), false);
  assert.equal(await actions.sendProductAction({ kind: 'search_empty', query_type: 'other', result_count: 0, search_scope: 'partial', language: 'en' }), false);
  assert.equal(await actions.sendProductAction({ kind: 'issuer_open', ticker: 'private@example.test', language: 'en' }), false);
  assert.equal(sent.length, 0);
  track.endPageview();
});
