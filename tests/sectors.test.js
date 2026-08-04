// Sector membership is one rule for the whole app. Run with `npm run test:unit`.
//
// The regression pinned here: the Рынок filter bar read the securities catalog
// while the heat map asked /api/companies first. That endpoint answers a ticker
// it has never heard of with the literal string "other" instead of leaving the
// field blank, so its default won the `||` and the catalog's real answer was
// never consulted — UZNF and UZNFP were Фонды in the table and Прочее on the
// map. Separately, "trade" and "professional" were missing from the map's
// sector order, so Торговля and Услуги had chips in the table and no blocks on
// the map.
import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { SECTOR_ORDER, orderSectors, sectorOf } from "../frontend/src/lib/sectors.js";

describe("sectorOf", () => {
  it("takes the securities catalog over the companies list", () => {
    // The real disagreement: UTGAP is logistics in the catalog, transport in
    // COMPANY_SECTORS. The catalog wins — the same precedence the server's
    // instruments.build_catalog documents.
    const securities = { UTGAP: { sector: "logistics" } };
    const companies = { UTGAP: { sector: "transport" } };
    assert.equal(sectorOf("UTGAP", securities, companies), "logistics");
  });

  it("is not fooled by the companies list defaulting an unknown ticker to other", () => {
    // /api/companies has never heard of UZNF, and answers "other" rather than
    // omitting the field. Reading it first buried the catalog's "funds".
    const securities = { UZNF: { sector: "funds" }, UZNFP: { sector: "funds" } };
    const companies = { UZNF: { sector: "other" }, UZNFP: { sector: "other" } };
    assert.equal(sectorOf("UZNF", securities, companies), "funds");
    assert.equal(sectorOf("UZNFP", securities, companies), "funds");
  });

  it("falls back to the companies list for a ticker the catalog has not reached", () => {
    assert.equal(sectorOf("NEW", {}, { NEW: { sector: "mining" } }), "mining");
  });

  it("files an unknown ticker under other rather than answering to no sector", () => {
    assert.equal(sectorOf("ZZZ", {}, {}), "other");
    assert.equal(sectorOf(null, {}, {}), "other");
    assert.equal(sectorOf("ZZZ", undefined, undefined), "other");
  });

  it("matches on the ticker regardless of case", () => {
    assert.equal(sectorOf("uznf", { UZNF: { sector: "funds" } }, {}), "funds");
  });
});

describe("orderSectors", () => {
  it("carries every sector the filter bar can raise a chip for", () => {
    // The chips the Рынок page shows today. None of them may be missing from
    // the map's order, or its tiles get folded into Прочее.
    for (const s of ["finance", "funds", "logistics", "manufacturing", "mining",
                     "other", "professional", "telecom", "trade", "transport"]) {
      assert.ok(SECTOR_ORDER.includes(s), `${s} is missing from SECTOR_ORDER`);
    }
  });

  it("keeps trade and professional as blocks of their own", () => {
    const got = orderSectors(["other", "trade", "professional", "finance"]);
    assert.deepEqual(got, ["finance", "trade", "professional", "other"]);
  });

  it("appends a sector the catalog grows later instead of dropping its tiles", () => {
    const got = orderSectors(["finance", "agriculture", "other"]);
    assert.deepEqual(got, ["finance", "other", "agriculture"]);
  });

  it("returns only the sectors actually present", () => {
    assert.deepEqual(orderSectors(["funds"]), ["funds"]);
    assert.deepEqual(orderSectors([]), []);
  });
});
