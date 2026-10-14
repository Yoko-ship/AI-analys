import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { inPeriod, isoDay, monthsBefore, periodCutoff, periodQuery, spanChange } from "../frontend/src/lib/periods.js";

// A weekday series ending on `end`, one close per session, rising by one.
function sessions(start, end, skip = new Set()) {
  const out = [];
  let price = 100;
  for (let t = new Date(`${start}T00:00:00Z`); t <= new Date(`${end}T00:00:00Z`); t.setUTCDate(t.getUTCDate() + 1)) {
    const day = t.toISOString().slice(0, 10);
    if (t.getUTCDay() === 0 || t.getUTCDay() === 6 || skip.has(day)) continue;
    price += 1;
    out.push({ date: day, close: price });
  }
  return out;
}

describe("the chart's periods are the board's periods", () => {
  // Server: formulas.period_cutoff. These are the same dates, pinned on both sides.
  const cases = [
    ["3m", "2026-10-12", "2026-07-12"], // a Sunday: the base is Friday 10.07
    ["6m", "2026-10-12", "2026-04-12"],
    ["1m", "2026-10-12", "2026-09-12"],
    ["1w", "2026-10-12", "2026-10-05"],
    ["1y", "2026-10-12", "2025-10-12"],
    ["ytd", "2026-10-12", "2025-12-31"],
    ["3m", "2026-05-31", "2026-02-28"], // setUTCMonth made this 03.03
    ["1m", "2028-03-31", "2028-02-29"],
    ["5y", "2026-10-13", "2021-10-13"],
  ];
  for (const [code, anchor, cutoff] of cases) {
    it(`${code} from ${anchor} starts after ${cutoff}`, () => {
      assert.equal(periodCutoff(code, anchor), cutoff);
    });
  }

  it("has no cutoff for a period it does not know", () => {
    assert.equal(periodCutoff("max", "2026-10-12"), null);
    assert.equal(periodCutoff("1y", null), null);
  });

  it("reads every date shape the history endpoints use", () => {
    assert.equal(isoDay("20261012"), "2026-10-12");
    assert.equal(isoDay("2026-10-12T14:00"), "2026-10-12");
    assert.equal(isoDay(""), null);
    assert.equal(monthsBefore("2026-05-31", 3), "2026-02-28");
  });

  it("keeps the session ON the cutoff out of the window — it is the base", () => {
    const days = sessions("2026-07-01", "2026-10-13");
    const window = inPeriod(days, periodCutoff("3m", "2026-10-13"));
    assert.equal(window[0].date, "2026-07-14");
  });

  it("compares hourly bars by day, so a session's bars stay in its window", () => {
    const bars = [{ date: "2026-10-05T10:00", close: 1 }, { date: "2026-10-06T10:00", close: 2 }];
    assert.deepEqual(inPeriod(bars, "2026-10-05").map((p) => p.date), ["2026-10-06T10:00"]);
  });
});

describe("a period's change is measured from the close before it", () => {
  it("ALSMP 3М on 12.10.2026: 143.53 %, from 10.07, not 191.57 % from 13.07", () => {
    const daily = [
      { date: "2026-07-10", close: 10655.88 },
      { date: "2026-07-13", close: 8900.01 },
      { date: "2026-10-12", close: 25950 },
    ];
    const window = inPeriod(daily, periodCutoff("3m", "2026-10-12"));
    const got = spanChange(daily, window[0].date, window.at(-1).date);
    assert.equal(got.baseDate, "2026-07-10");
    assert.equal(Number(got.pct.toFixed(2)), 143.53);
  });

  it("is the board's base on every weekday and weekend anchor", () => {
    const daily = sessions("2025-01-01", "2026-10-13", new Set(["2026-03-20", "2026-09-01"]));
    for (const anchor of ["2026-10-12", "2026-10-11", "2026-05-31", "2026-03-23", "2026-09-02"]) {
      for (const code of ["1w", "1m", "3m", "6m", "1y", "ytd"]) {
        const cutoff = periodCutoff(code, anchor);
        const upTo = daily.filter((p) => p.date <= anchor);
        const window = inPeriod(upTo, cutoff);
        const base = upTo.filter((p) => p.date <= cutoff).at(-1);
        const got = spanChange(upTo, window[0].date, window.at(-1).date);
        assert.equal(got.baseDate, base.date, `${code} from ${anchor}`);
      }
    }
  });

  it("has no figure when nothing precedes the span, except over the whole history", () => {
    const daily = [{ date: "2026-09-20", close: 100 }, { date: "2026-10-12", close: 130 }];
    assert.equal(spanChange(daily, "2026-09-20", "2026-10-12"), null);
    assert.equal(Number(spanChange(daily, "2026-09-20", "2026-10-12", { fromFirst: true }).pct.toFixed(6)), 30);
  });

  it("measures a session of hourly bars from the previous close", () => {
    const daily = [{ date: "2026-10-09", close: 100 }, { date: "2026-10-12", close: 110 }];
    const got = spanChange(daily, "2026-10-12T10:00", "2026-10-12T16:00");
    assert.equal(got.baseDate, "2026-10-09");
  });
});

describe("the card asks the server for a period by name", () => {
  for (const key of ["1w", "1m", "3m", "6m", "1y", "3y", "5y", "ytd"]) {
    it(`${key} is sent as window=${key}, with no day count from the reader's clock`, () => {
      assert.equal(periodQuery(key, key === "1w" ? 7 : null), `&window=${key}`);
    });
  }
  it("1d keeps its day count — the server has no period by that name", () => {
    assert.equal(periodQuery("1d", 1), "&days=1&window=1d");
  });
});
