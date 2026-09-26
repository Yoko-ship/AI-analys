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

test("the bond card leads with a full-width market chart that stays readable after resizing", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/bonds") return json(payload);
    if (p === "/api/bonds/CORPA") return json({ ...payload.items[3], ok: true, key_rate: payload.key_rate });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/bond/CORPA");
  const section = page.getByTestId("bond-market-position");
  const map = section.getByTestId("bond-yield-map");
  await expect(map).toHaveAttribute("data-points", "4");
  const header = await page.locator(".bondsec-card-head").boundingBox();
  const position = await section.boundingBox();
  const summary = await page.locator(".bondsec-summary").boundingBox();
  expect(position.y).toBeGreaterThanOrEqual(header.y + header.height);
  expect(position.y).toBeLessThan(header.y + header.height + 40);
  expect(position.y + position.height).toBeLessThanOrEqual(summary.y);
  expect((await map.boundingBox()).height).toBeGreaterThan(400);

  for (const width of [1440, 390, 320, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    // The drawing itself must fill the SVG, rather than a wide SVG centering a tiny plot.
    await expect.poll(() => map.evaluate((svg) => Math.abs(svg.viewBox.baseVal.width - svg.clientWidth))).toBeLessThan(2);
    const chart = await map.boundingBox();
    expect(chart.height).toBeGreaterThanOrEqual(319);
    const label = await section.locator(".bondsec-label-strong").boundingBox();
    expect(label.x).toBeGreaterThanOrEqual(chart.x);
    expect(label.x + label.width).toBeLessThanOrEqual(chart.x + chart.width);
    expect(await section.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  }
  await section.locator('.bondsec-map-pt[data-ticker="CORPA"] circle').hover();
  await expect(section.locator(".bondmap-tip")).toContainText("+614 б.п.");
  expect(errors).toEqual([]);
});
