// Карта доходности: priced issues against the ГЦБ curve, coloured by issuer
// group, with the excluded ones named, the table sorted by spread and every
// point's price basis on hover.
import { test, expect } from "@playwright/test";

const today = new Date().toISOString().slice(0, 10);
const bond = (ticker, segment, ytm, duration, bps, extra = {}) => ({
  ticker, isin: `UZ${ticker}`, name: ticker, issuer: `${ticker} issuer`, type: "bond", state: "live", segment,
  price: 110_000, issue_value: 5e10, last_trade_date: today,
  reference: { nominal: 100_000, coupon_rate: 25, coupon_freq: 12, is_complete: true, has_nominal: true, has_coupon: true },
  ytm: { value: ytm, status: "indicative" }, duration: { value: duration, status: "indicative" },
  g_spread: { value: bps / 100, bps, status: "indicative", curve_rate: ytm - bps / 100, extrapolated: duration < 1 },
  pricing: { value: 110_000, method: "vwap", sessions: 10, from: "2026-09-11", to: "2026-09-24" },
  price_pct: { value: 110 }, data_quality: [], ...extra,
});
const payload = {
  ok: true, board_day: today, count: 5,
  items: [
    bond("MFOA", "mfo", 22.1, 1.6, 1010),
    bond("MFOB", "mfo", 19.0, 0.99, 708),
    bond("BANKA", "bank", 17.5, 1.6, 547),
    bond("CORPA", "corporate", 18.3, 2.2, 614),
    bond("ANBK3B", "bank", null, null, null, {
      ytm: { value: null, status: "unavailable", blocked_reason: "COUPON_RATE_IMPLAUSIBLE" },
      duration: { value: null }, g_spread: { value: null },
      data_quality: [{ code: "COUPON_RATE_IMPLAUSIBLE", severity: "blocking" }] }),
  ],
  gov_curve: [
    { term_days: 364, rate: 11.97, rate_effective: 11.97, duration_years: 1.0, auction_date: "2026-09-03", income_type: "discount" },
    { term_days: 1095, rate: 12.25, rate_effective: 12.25, duration_years: 2.68, auction_date: "2026-09-03", income_type: "coupon" },
  ],
  key_rate: { rate: 14, effective_from: "2026-09-16" },
};

test("the yield map plots priced issues by group and explains what is missing", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/bonds") return json(payload);
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.goto("/bonds");
  await page.getByRole("button", { name: /Карта доходности/ }).first().click();

  const map = page.getByTestId("bond-yield-map");
  await expect(map).toHaveAttribute("data-points", "4");
  await expect(page.getByTestId("bond-map-coverage")).toContainText("ANBK3B");
  await expect(page.getByTestId("bond-segment-summary")).toContainText("МФО и финкомпании");

  // Sorted by spread, widest first.
  const firstRow = page.getByTestId("bond-spread-table").locator("tbody tr").first();
  await expect(firstRow).toContainText("MFOA");
  await expect(firstRow).toContainText("+1 010 б.п.");

  // The legend chips filter.
  await page.locator(".bondmap-chip", { hasText: "МФО" }).click();
  await expect(map).toHaveAttribute("data-points", "2");
  await page.locator(".bondmap-chip", { hasText: "МФО" }).click();
  await expect(map).toHaveAttribute("data-points", "4");

  // Hover names the price the yield was struck on.
  await page.locator('.bondsec-map-pt[data-ticker="MFOB"] circle').hover();
  const tip = page.locator(".bondmap-tip");
  await expect(tip).toContainText("MFOB");
  await expect(tip).toContainText("средневзвешенная по объёму");
  await expect(tip).toContainText("+708 б.п.");
  expect(errors).toEqual([]);
});
