import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { routeFingerprint } from '../frontend/src/lib/publicationLanding.js';

for (const { url, route } of JSON.parse(readFileSync(new URL('./fixtures/publication-routes.json', import.meta.url), 'utf8'))) {
  test(`publication route interoperates with Python: ${url}`, async () => {
    const location = new URL(url);
    assert.equal(location.pathname, route[0]);
    assert.equal(location.hash, route[2]);
    assert.equal(await routeFingerprint(location), createHash('sha256').update(JSON.stringify(route)).digest('hex'));
  });
}
