import test from 'node:test';
import assert from 'node:assert/strict';
import {createCatalogRequestCache} from '../frontend/src/lib/catalogRequestCache.js';

const response = data => ({ok:true, json:async () => data});
test('catalog shares in-flight requests and expires completed data using the clock', async () => {
  let now = 0, calls = 0, release;
  const cache = createCatalogRequestCache({now:() => now, ttl:60, fetcher:() => {
    calls++; return new Promise(resolve => {release = () => resolve(response({ok:true, calls}));});
  }});
  const url = '/api/terminal/issuer/HMKB/analytics?form=NSBU&scope=separate';
  const a = cache.read(url), b = cache.read(url);
  assert.equal(calls, 1);
  release();
  assert.equal(await a, await b);
  now = 59; assert.equal((await cache.read(url)).calls, 1);
  now = 60; assert.equal(cache.peek(url), null);
  const fresh = cache.read(url); release();
  assert.equal((await fresh).calls, 2);
});

test('issuer, language and reporting context have independent cache entries', async () => {
  const requests = [];
  const cache = createCatalogRequestCache({fetcher:async url => {requests.push(url); return response({url});}});
  const urls = ['HMKB?form=NSBU&scope=separate&lang=ru','AGBA?form=NSBU&scope=separate&lang=ru','HMKB?form=MSFO&scope=consolidated&lang=ru','HMKB?form=NSBU&scope=separate&lang=en'];
  for (const url of urls) assert.equal((await cache.read(url)).url, url);
  for (const url of urls) await cache.read(url);
  assert.deepEqual(requests, urls);
});

test('failed HTTP, malformed and unsuccessful API responses are retryable', async () => {
  for (const failure of [
    {ok:false, status:503, json:async () => ({error_id:'source-error'})},
    {ok:true, json:async () => {throw new SyntaxError('invalid json');}},
    response({ok:false}),
  ]) {
    let calls = 0;
    const cache = createCatalogRequestCache({fetcher:async () => ++calls === 1 ? failure : response({ok:true})});
    await assert.rejects(cache.read('HMKB'));
    assert.equal(cache.peek('HMKB'), null);
    assert.deepEqual(await cache.read('HMKB'), {ok:true});
    assert.equal(calls, 2);
  }
});

test('sync invalidation prevents a late old response from replacing fresh data', async () => {
  let calls = 0, release, signal;
  const cache = createCatalogRequestCache({fetcher:async (url, options) => {
    calls++;
    if (calls > 1) return response({revision:2});
    signal = options.signal;
    return new Promise(resolve => {release = () => resolve(response({revision:1}));});
  }});
  const pending = cache.read('HMKB');
  cache.clear();
  assert.equal(signal.aborted, true);
  await cache.read('HMKB'); release(); await pending;
  assert.deepEqual(cache.peek('HMKB'), {revision:2});
});

test('catalog cache bounds retained responses and keeps recently used entries', async () => {
  const cache = createCatalogRequestCache({maxEntries:2, fetcher:async url => response({url})});
  await cache.read('HMKB'); await cache.read('AGBA'); await cache.read('HMKB'); await cache.read('SQBN');
  assert.equal(cache.peek('AGBA'), null);
  assert.deepEqual(cache.peek('HMKB'), {url:'HMKB'});
  assert.deepEqual(cache.peek('SQBN'), {url:'SQBN'});
  cache.clear(); assert.equal(cache.peek('HMKB'), null);
});

test('invalid financial payloads are rejected before caching so retry can recover', async () => {
  let calls = 0;
  const cache = createCatalogRequestCache({fetcher:async () => response(++calls === 1 ? {detail:'invalid'} : {ok:true, rows:[]})});
  const options = {validate:data => data?.ok === true};
  await assert.rejects(cache.read('HMKB/financials/columns', options));
  assert.deepEqual(await cache.read('HMKB/financials/columns', options), {ok:true, rows:[]});
  assert.equal(calls, 2);
});

test('non-JSON service failures retain the HTTP status for the terminal journal', async () => {
  const cache = createCatalogRequestCache({fetcher:async () => ({ok:false, status:503, json:async () => {throw new SyntaxError('HTML response');}})});
  await assert.rejects(cache.read('HMKB'), /HTTP 503/);
});
