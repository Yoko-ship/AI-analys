import test from 'node:test';
import assert from 'node:assert/strict';

async function setup() {
  const values = new Map(), sent = [];
  const store = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)), removeItem: key => values.delete(key) };
  globalThis.localStorage = store;
  globalThis.sessionStorage = store;
  globalThis.window = { location: { search: '?utm_source=telegram' }, innerWidth: 1000, innerHeight: 800, scrollY: 0, addEventListener() {} };
  globalThis.document = { referrer: '', visibilityState: 'visible', documentElement: { scrollHeight: 1200 }, body: {}, addEventListener() {} };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { sendBeacon: (_url, blob) => { sent.push(blob); return true; } } });
  const mod = await import(`../frontend/src/lib/track.js?case=${Math.random()}`);
  return { ...mod, values, payloads: () => Promise.all(sent.map(async b => JSON.parse(await b.text()))) };
}

test('feature tracking is bounded, inherits identity, and never manufactures a pageview per click', async () => {
  const m = await setup();
  assert.equal(typeof m.trackFeature, 'function');
  m.trackPageview({ path: '/company/UZTL', view: 'company', ticker: 'UZTL' });
  m.trackFeature('financials', 'UZTL');
  m.trackFeature('invented_private_search_text', 'UZTL');
  const rows = await m.payloads();
  assert.equal(rows.length, 2);
  assert.equal(rows[0].tv, 1);
  assert.equal(rows[1].event, 'feature_financials');
  assert.equal(rows[1].sid, rows[0].sid);
  assert.equal(rows[1].vid, rows[0].vid);
  assert.equal(rows[1].ticker, 'UZTL');
  assert.equal(rows[1].us, undefined);
  m.endPageview();
  m.trackFeature('chart');
  assert.equal((await m.payloads()).filter(r => r.event === 'feature_chart').length, 0);
});

test('an interaction after 30 idle minutes starts a visit with a landing page', async () => {
  const m = await setup();
  assert.equal(typeof m.trackFeature, 'function');
  const originalNow = Date.now;
  let now = originalNow();
  Date.now = () => now;
  try {
    m.trackPageview({ path: '/company/UZTL', view: 'company', ticker: 'UZTL' });
    const first = (await m.payloads())[0];
    now += 31 * 60 * 1000;
    m.trackFeature('chart', 'UZTL');
    const rows = await m.payloads();
    const action = rows.find(r => r.event === 'feature_chart');
    assert.notEqual(action.sid, first.sid);
    assert.equal(rows.filter(r => !r.event).length, 2);
    assert.equal(rows.find(r => !r.event && r.sid === action.sid).path, '/company/UZTL');
  } finally { Date.now = originalNow; }
});
