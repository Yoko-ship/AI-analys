import test from "node:test";
import assert from "node:assert/strict";
import { calendarBounds, paymentPeriod, periodPreset, validatePeriod } from "../frontend/src/features/bonds/calendarModel.js";

const flow = (date, ticker, coupon, principal = 0) => ({ date, ticker, coupon, principal });

test("payment period includes both boundary dates and excludes outside payments", () => {
  const data = { flows: [flow("2026-10-19", "B", 200, 1000), flow("2026-10-02", "A", 10),
    flow("2026-10-03", "A", 100), flow("2026-10-20", "C", 20), flow("2026-10-03", "B", 50)] };
  const result = paymentPeriod(data, { from: "2026-10-03", to: "2026-10-19" });
  assert.equal(result.flows.length, 3);
  assert.equal(result.coupon, 350);
  assert.equal(result.principal, 1000);
  assert.equal(result.issues, 2);
  assert.equal(result.next.date, "2026-10-03");
  assert.deepEqual(result.months, [{ key: "2026-10", year: 2026, month: 10, coupon: 350, principal: 1000, issues: 2 }]);
  assert.equal(paymentPeriod(data, { from: "2026-10-03", to: "2026-10-03" }).flows.length, 2);
  assert.equal(data.flows[0].date, "2026-10-19");
});

test("months include empty months across a year boundary and leap day", () => {
  const result = paymentPeriod({ flows: [flow("2028-02-29", "LEAP", 100)] }, { from: "2027-12-31", to: "2028-03-01" });
  assert.deepEqual(result.months.map((month) => month.key), ["2027-12", "2028-01", "2028-02", "2028-03"]);
  assert.deepEqual(result.months.map((month) => month.coupon), [0, 0, 100, 0]);
  assert.equal(result.next.ticker, "LEAP");
});

test("a period without payments has zero totals and keeps its calendar months", () => {
  const result = paymentPeriod({ flows: [flow("2026-10-03", "A", 100)] }, { from: "2026-11-01", to: "2026-11-30" });
  assert.deepEqual([result.coupon, result.principal, result.issues, result.flows.length], [0, 0, 0, 0]);
  assert.equal(result.next, undefined);
  assert.equal(result.months[0].key, "2026-11");
});

test("presets use calendar days and stop at the API schedule boundary", () => {
  const bounds = calendarBounds({ today: "2027-12-31", months: [{ year: 2028, month: 2 }] });
  assert.equal(bounds.to, "2028-02-29");
  assert.deepEqual(periodPreset(bounds, 30), { from: "2027-12-31", to: "2028-01-30" });
  assert.deepEqual(periodPreset(bounds, 365), { from: "2027-12-31", to: "2028-02-29" });
});

test("reject missing, impossible, reversed and unavailable dates", () => {
  const bounds = { from: "2026-09-26", to: "2031-08-31" };
  assert.equal(validatePeriod({ from: "", to: "2026-10-01" }, bounds), "dates");
  assert.equal(validatePeriod({ from: "2027-02-29", to: "2027-03-01" }, bounds), "dates");
  assert.equal(validatePeriod({ from: "2026-10-02", to: "2026-10-01" }, bounds), "order");
  assert.equal(validatePeriod({ from: "2026-09-25", to: "2026-10-01" }, bounds), "bounds");
  assert.equal(validatePeriod({ from: "2026-10-01", to: "2031-09-01" }, bounds), "bounds");
  assert.equal(validatePeriod({ from: "2028-02-29", to: "2028-02-29" }, bounds), null);
  assert.equal(validatePeriod(bounds, bounds), null);
});
