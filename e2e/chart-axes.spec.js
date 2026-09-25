// The company price chart's range buttons. The chart holds the whole archive
// (drag reaches back to the first session), so each button decides only the
// window it OPENS on — and «Макс» has to fit every session, not stop at the
// canvas's default bar spacing.
import { test, expect } from "@playwright/test";

const SECURITIES = { ok: true, securities: {
  UNVB: { name: "Universal Bank", security_type: "stock", last_price: 8200, close_price: 8500, industry: "Banks" },
} };

// Three years of daily closes between ~5 200 and ~23 800, traded on some days
// and not others — the sessions a thin UZSE security actually has.
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

const monthsBetween = (a, b) => {
  const x = new Date(a), y = new Date(b);
  return (y.getUTCFullYear() - x.getUTCFullYear()) * 12 + (y.getUTCMonth() - x.getUTCMonth());
};

test("each range button opens the chart on its own window", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const history = priceHistory();
  const first = history[history.length - 1].date;
  const last = history[0].date;
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const j = (b, s = 200) => route.fulfill({ status: s, contentType: "application/json", body: JSON.stringify(b) });
    if (p === "/api/securities") return j(SECURITIES);
    if (p.startsWith("/api/price-history/")) return j({ ok: true, points: history, adjustments: [] });
    if (p === "/api/auth/me") return j({ user: null }, 401);
    return j({});
  });

  await page.goto("/company/UNVB");
  const chart = page.locator(".company-price-chart");
  const range = page.getByTestId("company-visible-range");
  await expect(chart).toBeVisible();
  await expect(chart.locator("canvas").first()).toBeVisible();

  for (const [label, months] of [["1М", 1], ["3М", 3], ["6М", 6], ["1Г", 12]]) {
    await page.getByRole("button", { name: label, exact: true }).click();
    await expect(range).toHaveAttribute("data-to", last);
    // The window starts inside the month the button names (sessions are sparse).
    await expect.poll(async () => {
      const span = monthsBetween(await range.getAttribute("data-from"), last);
      return span >= months - 1 && span <= months;
    }).toBe(true);
    await expect(page.locator(".cpc-history-reset")).toHaveCount(0);
  }

  await page.getByRole("button", { name: "Макс", exact: true }).click();
  await expect(range).toHaveAttribute("data-from", first);
  await expect(range).toHaveAttribute("data-to", last);
  await expect(page.locator(".cpc-history-reset")).toHaveCount(0);
  expect(errors).toEqual([]);
});
