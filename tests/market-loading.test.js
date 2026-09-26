import assert from "node:assert/strict";
import test from "node:test";

import { blocksMarketContent } from "../frontend/src/lib/marketLoading.js";

test("an initial empty market load blocks the content area", () => {
  assert.equal(blocksMarketContent(true, 0), true);
});

test("a refresh keeps the last good market rows visible", () => {
  assert.equal(blocksMarketContent(true, 89), false);
});

test("settled empty and populated states do not show the loading blocker", () => {
  assert.equal(blocksMarketContent(false, 0), false);
  assert.equal(blocksMarketContent(false, 89), false);
});
