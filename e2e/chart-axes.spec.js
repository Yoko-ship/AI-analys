// The company price chart's axes. Both defects fixed here were invisible to
// unit tests and obvious on screen: the last date printed on top of its
// neighbour, and the price scale was five samples of the data range.
import { test, expect } from "@playwright/test";

const SECURITIES = { ok: true, securities: {
  UNVB: { name: "Universal Bank", security_type: "stock", last_price: 8200, close_price: 8500, industry: "Banks" },
} };

// Three years of daily closes between ~5 200 and ~23 800, traded on some days
// and not others, so the weekly buckets come out at a count that does not
// divide evenly by the label step — which is exactly when the axis collided.
function priceHistory() {
  const out = [];
  const start = new Date("2023-09-01");
  let price = 21000;
  for (let d = 0; d < 1065; d++) {
    const day = new Date(start.getTime() + d * 864e5);
    if (day.getDay() === 0 || day.getDay() === 6) continue;
    if ((d * 7919) % 11 < 6) continue;
    price = Math.max(5200, Math.min(23800, price * (1 + (((d * 7919) % 21) - 10) / 120)));
    const open = price * (1 + (((d * 104729) % 9) - 4) / 200);
    out.push({
      date: day.toISOString().slice(0, 10),
      open: Math.round(open),
      high: Math.round(Math.max(open, price) * 1.02),
      low: Math.round(Math.min(open, price) * 0.98),
      close: Math.round(price),
      volume: (d * 7919) % 13 === 0 ? 0 : ((d * 31) % 400) + 5,
    });
  }
  return out.reverse();                              // the feed returns newest-first
}

test("the price axes stay readable on three years of weekly candles", async ({ page }) => {
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const j = (b, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
    if (p === "/api/securities") return j(SECURITIES);
    if (p.startsWith("/api/price-history/")) return j({ ok: true, points: priceHistory(), adjustments: [] });
    if (p === "/api/auth/me") return j({ user: null }, 401);
    return j({});
  });

  await page.goto("/company/UNVB");
  const svg = page.locator(".company-price-chart-svg");
  await expect(svg).toBeVisible();
  await page.getByRole("button", { name: "3Г", exact: true }).click();
  await expect(page.locator(".chart-interval-tag")).toHaveText("недельные");

  const axes = await svg.evaluate((el) => {
    const texts = Array.from(el.querySelectorAll("text"));
    return {
      y: texts.filter((t) => t.getAttribute("text-anchor") === "end" && Number(t.getAttribute("y")) < 340)
              .map((t) => t.textContent),
      x: texts.filter((t) => Number(t.getAttribute("y")) > 340)
              .map((t) => ({ x: Number(t.getAttribute("x")), anchor: t.getAttribute("text-anchor") })),
    };
  });

  // No two dates share a place on the axis. The endpoint label is what used to
  // land on top of the last grid tick — 3 units away from it in the worst case.
  const gaps = axes.x.slice(1).map((t, i) => t.x - axes.x[i].x);
  expect(axes.x.length).toBeGreaterThanOrEqual(5);
  expect(Math.min(...gaps)).toBeGreaterThan(60);
  // The label at the end of the axis is anchored inward, so it cannot hang
  // outside the 820-unit viewBox and be clipped by the frame.
  expect(axes.x[axes.x.length - 1].anchor).toBe("end");
  expect(axes.x[axes.x.length - 1].x).toBeLessThanOrEqual(820);

  // Round numbers inside the range — not minP + k·range/4, which gave
  // 5.0K / 9.8K / 14.5K / 19.3K / 24.0K and read as data, not as a scale.
  expect(axes.y).toEqual(["10.0K", "15.0K", "20.0K"]);
});
