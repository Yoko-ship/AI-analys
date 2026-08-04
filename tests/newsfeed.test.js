// Which story leads the news page.
//
// Half the feed can never carry a picture — issuer filings on openinfo,
// central-bank notices, rating actions. Under «Корпоративные» that is 28 of 49
// stories, and the impact ranking regularly puts one of them first, so the tab
// opened on a bare headline while 40% of it was illustrated. A placeholder slab
// was tried and rejected, so the LEAD moves instead — but only a few places, or
// a photograph would start outranking relevance.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { LEAD_LOOKAHEAD, pickLeadIndex } from "../frontend/src/lib/newsfeed.js";

const withArt = (id) => ({ id, image_url: `https://img/${id}.jpg` });
const noArt = (id) => ({ id });

describe("pickLeadIndex", () => {
  it("keeps the top-ranked story when it has a picture", () => {
    assert.equal(pickLeadIndex([withArt(1), withArt(2), noArt(3)]), 0);
  });

  it("promotes the best-ranked story that has one", () => {
    // «Корпоративные»: openinfo filings rank first and carry no art.
    assert.equal(pickLeadIndex([noArt(1), noArt(2), withArt(3), withArt(4)]), 2);
  });

  it("will not reach past the lookahead for a picture", () => {
    const items = [...Array(LEAD_LOOKAHEAD).fill(null).map((_, i) => noArt(i)), withArt(99)];

    // A photograph that far down the ranking is not worth the masthead.
    assert.equal(pickLeadIndex(items), 0);
  });

  it("leads with the ranking when nothing has a picture", () => {
    // A feed of pure filings is imageless, and that is the honest outcome.
    assert.equal(pickLeadIndex([noArt(1), noArt(2), noArt(3)]), 0);
  });

  it("drops nothing — every other index is still the stack", () => {
    const items = [noArt(1), withArt(2), noArt(3)];
    const lead = pickLeadIndex(items);
    const stack = items.filter((_, i) => i !== lead);

    assert.equal(lead, 1);
    assert.deepEqual(stack.map((i) => i.id), [1, 3]);
    assert.equal(stack.length + 1, items.length);
  });

  it("survives an empty or malformed feed", () => {
    assert.equal(pickLeadIndex([]), 0);
    assert.equal(pickLeadIndex(null), 0);
    assert.equal(pickLeadIndex(undefined), 0);
    assert.equal(pickLeadIndex([null, withArt(2)]), 1);
  });

  it("treats an empty image_url as no picture", () => {
    assert.equal(pickLeadIndex([{ id: 1, image_url: "" }, withArt(2)]), 1);
  });
});
