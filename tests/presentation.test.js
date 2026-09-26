import { test } from "node:test";
import assert from "node:assert/strict";
import * as format from "../frontend/src/lib/format.js";

test("display rounding preserves missing values and rounds only the final number", () => {
  assert.equal(typeof format.roundedDisplayValue, "function");
  for (const value of [null, undefined, "", " ", NaN, Infinity]) {
    assert.equal(format.roundedDisplayValue(value), null);
  }
  assert.equal(format.roundedDisplayValue(0), 0);
  assert.equal(format.roundedDisplayValue(12.345, 2), 12.35);
  assert.equal(format.roundedDisplayValue(-1.5), -1);
  assert.equal(format.roundedDisplayValue(0.0125, 4), 0.0125);
  assert.equal(format.roundedDisplayValue((1500 - 1440) / 1440 * 100, 2), 4.17);
});

test("chart geometry snaps pixels and selects bounded point indices", async () => {
  const { snapPixel, nearestPointIndex } = await import("../frontend/src/lib/geometry.js");
  assert.equal(snapPixel(24.37, .5), 24.5);
  assert.equal(snapPixel(24.2, .5), 24);
  assert.equal(nearestPointIndex(-.2, 10), 0);
  assert.equal(nearestPointIndex(1.2, 10), 9);
  assert.equal(nearestPointIndex(.5, 10), 5);
  assert.equal(nearestPointIndex(.7, 1), 0);
  assert.equal(nearestPointIndex(.7, 0), null);
});
test("axis labels fit narrow plots without collisions and preserve boundary dates", async () => {
  const { fitAxisLabels } = await import("../frontend/src/lib/geometry.js");
  const ticks = Array.from({ length: 13 }, (_, i) => ({ x: i * 24, label: `Month ${i}` }));
  const visible = fitAxisLabels(ticks, 0, 288, () => 90);
  assert.equal(visible[0].label, "Month 0");
  assert.equal(visible.at(-1).label, "Month 12");
  const left = tick => tick.x - (tick.anchor === "end" ? 90 : tick.anchor === "middle" ? 45 : 0);
  assert.ok(visible.length >= 2 && visible.length <= 3);
  visible.slice(1).forEach((tick, i) => assert.ok(left(tick) >= left(visible[i]) + 98));
  assert.deepEqual(fitAxisLabels([], 0, 288), []);
});
