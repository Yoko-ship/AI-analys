import test from 'node:test';
import assert from 'node:assert/strict';
import {Readable} from 'node:stream';
import {readDownload} from '../e2e/helpers/download.js';

test('CSV assertions read remote browser downloads without a local path', async () => {
  const csv = '\ufeffTicker,"ROE, %"\r\nHMKB,"25,43"\r\nUTHK,—\r\n';
  const bytes = Buffer.from(csv);
  const remote = {
    path() { throw new Error('Path is not available when connecting remotely. Use saveAs() to save a local copy.'); },
    async createReadStream() {
      // Split inside the UTF-8 em dash to check decoding across stream chunks.
      const split = bytes.indexOf(Buffer.from('—')) + 1;
      return Readable.from([bytes.subarray(0, split), bytes.subarray(split)]);
    },
  };
  assert.equal(await readDownload(Promise.resolve(remote)), csv);
  assert.equal(await readDownload(remote), csv);
});

test('failed download streams fail CSV verification', async () => {
  await assert.rejects(readDownload({async createReadStream() {
    return Readable.from((async function* () {
      yield Buffer.from('partial');
      throw new Error('Download interrupted');
    })());
  }}), /Download interrupted/);
});
