// Chart patterns on the company chart: off until asked for, drawn per family,
// each listed beside its UZSE record with a verdict that only claims a
// difference from chance when there is one — and absent, with the reason, on
// a security that trades too rarely to have shapes.
import { test, expect } from "@playwright/test";

const TICKER = "UNVB";
const SECURITY = { name: "Universal Bank", company_name: "Universal Bank", security_type: "stock",
  last_price: 8200, close_price: 8200, industry: "Banks" };
const CHART_SECURITIES = {
  UNVB: SECURITY,
  UZTL: { name: "Uzbektelecom", company_name: "Uzbektelecom", security_type: "stock",
    last_price: 17207, close_price: 17207, industry: "Telecommunications" },
  SQBN: { name: "SQB", company_name: "SQB", security_type: "stock",
    last_price: 40.95, close_price: 40.95, industry: "Banks" },
};

function priceHistory(startPrice = 6100) {
  const out = [];
  const end = new Date();
  end.setUTCHours(0, 0, 0, 0);
  let price = startPrice;
  for (let offset = 900; offset >= 0; offset -= 1) {
    const day = new Date(end.getTime() - offset * 864e5);
    if (day.getUTCDay() === 0 || day.getUTCDay() === 6) continue;
    price *= 1 + ((((offset * 37) % 15) - 7) / 1000);
    const open = price * (1 + ((((offset * 17) % 7) - 3) / 1000));
    out.push({ date: day.toISOString().slice(0, 10), open, high: Math.max(open, price) * 1.012,
      low: Math.min(open, price) * 0.988, close: price, value: 10_000_000 });
  }
  return out;
}

function patternsBody(history, status = "AVAILABLE", sensitivity = "medium", ticker = TICKER) {
  const at = (i) => history[history.length - i];
  const top = at(60), neck = at(50), signal = at(40);
  return {
    ok: true, ticker, status, tier: status === "AVAILABLE" ? "full" : "sparse", sensitivity,
    reason: status === "AVAILABLE" ? null : "59% свечей без внутридневного диапазона",
    market_stats: {
      double_top: { signals: 500, decided: 400, hit_rate_pct: 20, chance_pct: 30, avg_return_pct: -4, securities: 50 },
      hammer: { signals: 900, decided: 800, hit_rate_pct: 26, chance_pct: 25.5, avg_return_pct: -1, securities: 50 },
    },
    stats_meta: { securities: 53, generated: "2026-09-25" },
    backtest: { all: { trades: 12, win_rate_pct: 33.3, total_return_pct: -18.2, max_drawdown_pct: -27.5, sharpe: -0.4 },
      chart: { trades: 5, win_rate_pct: 40, total_return_pct: -6.1, max_drawdown_pct: -12.3, sharpe: -0.2 },
      candle: { trades: 7, win_rate_pct: 28.6, total_return_pct: -12.9, max_drawdown_pct: -20.1, sharpe: -0.5 },
      fee_bps: 15, slippage_bps: 20, horizon: 20 },
    cycle: { status: "AVAILABLE", period_sessions: 63, amplitude_pct: 4.2, p_value: 0.41, significant: false,
      next_peak_in: 12, next_trough_in: 43 },
    signals: status !== "AVAILABLE" ? [] : [
      { type: "double_top", family: "chart", direction: "bearish", start_date: top.date, signal_date: signal.date,
        price: signal.close, target: signal.close * 0.9, stop: top.close * 1.05, outcome: "stop",
        points: [{ date: top.date, price: top.high }, { date: neck.date, price: neck.low }],
        lines: [{ role: "neckline", from: { date: neck.date, price: neck.low }, to: { date: signal.date, price: neck.low } }],
        box: { from: top.date, to: signal.date, high: top.high, low: neck.low },
        angles: {} },
      { type: "hammer", family: "candle", direction: "bullish", start_date: at(20).date, signal_date: at(20).date,
        price: at(20).close, target: at(20).close * 1.05, stop: at(20).low, outcome: "horizon",
        points: [], lines: [], angles: {} },
    ],
  };
}

async function mock(page, status, asked = [], ticker = TICKER) {
  const security = CHART_SECURITIES[ticker];
  const history = priceHistory(security.last_price * 6100 / SECURITY.last_price);
  await page.route("**/api/**", (route) => {
    const p = new URL(route.request().url()).pathname;
    const json = (body, code = 200) => route.fulfill({ status: code, contentType: "application/json", body: JSON.stringify(body) });
    if (p === "/api/securities") return json({ ok: true, securities: { [ticker]: security } });
    if (p === `/api/price-history/${ticker}`) return json({ ok: true, points: history, adjustments: [] });
    if (p === `/api/company/${ticker}/patterns`) {
      const level = new URL(route.request().url()).searchParams.get("sensitivity") || "medium";
      asked.push(level);
      return json(patternsBody(history, status, level, ticker));
    }
    if (p === `/api/company/${ticker}/metrics`) return json({ ok: true, quality: { candles_enabled: true } });
    if (p === `/api/securities/${ticker}/info`) return json({ ok: true, security });
    if (p === "/api/auth/me") return json({ user: null }, 401);
    return json({});
  });
}

test("patterns are drawn per family and listed with an honest verdict", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const asked = [];
  await mock(page, "AVAILABLE", asked);
  await page.goto(`/company/${TICKER}`);
  const chart = page.locator(".company-price-chart");
  await expect(chart).toBeVisible();
  await expect(chart).toHaveAttribute("data-patterns", "0");
  await expect(page.getByTestId("pattern-list")).toHaveCount(0);

  await page.getByTestId("company-chart-patterns").click();
  await page.getByRole("menuitemcheckbox", { name: "Фигуры" }).click();
  await expect(chart).toHaveAttribute("data-patterns", "1");
  const list = page.getByTestId("pattern-list");
  await expect(list).toContainText("Двойная вершина");
  // 20 % against 30 % over 400 trades is a real gap: worse than chance.
  await expect(list).toContainText("хуже случайного");
  await expect(list).not.toContainText("Молот");

  await page.getByRole("menuitemcheckbox", { name: "Свечные модели" }).click();
  await expect(chart).toHaveAttribute("data-patterns", "2");
  // 26 % against 25.5 % is noise, and the list must not call it an edge.
  await expect(list).toContainText("Молот");
  await expect(list.locator(".pattern-verdict.same")).toHaveCount(1);
  await page.keyboard.press("Escape");

  // The strategy test quotes the family switched on: both families → "all".
  await expect(page.getByTestId("pattern-backtest")).toContainText("12");
  await expect(page.getByTestId("pattern-backtest")).toContainText("-18,2%");

  // Picking a pattern moves the chart onto it and selects it.
  const range = page.getByTestId("company-visible-range");
  const before = await range.getAttribute("data-from");
  const row = list.getByRole("button", { name: /Двойная вершина/ });
  await row.click();
  await expect.poll(() => range.getAttribute("data-from")).not.toBe(before);
  await expect(row).toHaveAttribute("aria-pressed", "true");

  // Sensitivity asks the server for that level's patterns and table.
  await page.getByTestId("company-chart-patterns").click();
  await page.getByRole("menuitemradio", { name: "Высокая" }).click();
  await expect.poll(() => asked.includes("high")).toBe(true);

  // Cycles: the verdict says noise when a random walk explains the peak.
  await page.getByRole("menuitemcheckbox", { name: "Цикличность" }).click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("pattern-cycle")).toContainText("63");
  await expect(page.getByTestId("pattern-cycle").locator("[data-verdict=noise]")).toBeVisible();

  // «Очистить всё» takes patterns off with every other overlay.
  await page.getByTestId("company-chart-clear-all").click();
  await expect(chart).toHaveAttribute("data-patterns", "0");
  await expect(page.getByTestId("pattern-list")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("a thin security gets no patterns and is told why", async ({ page }) => {
  await mock(page, "INSUFFICIENT_LIQUIDITY");
  await page.goto(`/company/${TICKER}`);
  await page.getByTestId("company-chart-patterns").click();
  await page.getByRole("menuitemcheckbox", { name: "Фигуры" }).click();
  const list = page.getByTestId("pattern-list");
  await expect(list).toContainText("Паттерны не строятся");
  await expect(list).toContainText("59% свечей без внутридневного диапазона");
  await expect(page.locator(".company-price-chart")).toHaveAttribute("data-patterns", "0");
});

const FULLSCREEN_ENTRY_POINTS = [
  { ticker: "UZTL", entry: "direct" },
  { ticker: "UNVB", entry: "company overview" },
  { ticker: "SQBN", entry: "company price history" },
];
for (const { ticker, entry } of FULLSCREEN_ENTRY_POINTS) {
  for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    test(`${ticker} patterns survive fullscreen from ${entry} at ${viewport.width}px`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const asked = [];
      await mock(page, "AVAILABLE", asked, ticker);
      if (entry === "direct") {
        await page.goto(`/chart/${ticker}`);
      } else {
        await page.goto(`/company/${ticker}`);
        if (entry === "company price history") {
          await page.getByRole("button", { name: "История цен", exact: true }).click();
        }
        await page.getByRole("button", { name: "Развернуть в расширенный график", exact: true }).click();
      }
      await expect(page).toHaveURL(new RegExp(`/chart/${ticker}(?:\\?|$)`));
      const chart = page.locator(".ac-canvas");
      const workspace = page.locator(".advanced-chart");
      const range = page.getByTestId("ac-visible-range");
      await expect(chart).toBeVisible();
      await page.getByTestId("ac-patterns").click();
      await page.getByRole("button", { name: "Фигуры", exact: true }).click();
      await page.getByRole("button", { name: "Свечные модели", exact: true }).click();
      await page.getByTestId("ac-patterns").click();
      await expect(chart).toHaveAttribute("data-patterns", "2");
      const selected = page.getByTestId("pattern-list").getByRole("button", { name: /Двойная вершина/ });
      await selected.click();
      await expect(selected).toHaveAttribute("aria-pressed", "true");
      const focusedRange = await range.evaluate((el) => ({ from: el.dataset.from, to: el.dataset.to }));

      await page.getByRole("button", { name: "Развернуть график на весь экран" }).click();
      await expect(workspace).toHaveClass(/is-fullscreen/);
      await page.screenshot({ path: testInfo.outputPath("patterns-fullscreen.png"), fullPage: true });

      // Every drawing pane and the time axis must fit inside the visible plot.
      await expect.poll(async () => chart.evaluate((el) => {
        const plot = el.closest(".ac-plot");
        return Math.abs(el.clientHeight - plot.clientHeight);
      })).toBeLessThanOrEqual(2);
      expect(await page.locator(".ac-plot").evaluate((el) => el.clientHeight)).toBeGreaterThanOrEqual(238);
      await expect(chart).toHaveAttribute("data-patterns", "2");
      await expect(range).toHaveAttribute("data-from", focusedRange.from);
      await expect(range).toHaveAttribute("data-to", focusedRange.to);
      await expect(selected).toHaveAttribute("aria-pressed", "true");

      // The lower panel remains reachable instead of shrinking or clipping the chart.
      await page.getByRole("button", { name: "Сбросить", exact: true }).click();
      const hammer = page.getByTestId("pattern-list").getByRole("button", { name: /Молот/ });
      await hammer.click();
      await expect(hammer).toHaveAttribute("aria-pressed", "true");
      await expect.poll(() => range.getAttribute("data-from")).not.toBe(focusedRange.from);
      await page.getByRole("button", { name: "Выйти из полноэкранного режима" }).click();
      await expect(workspace).not.toHaveClass(/is-fullscreen/);
      await expect(hammer).toHaveAttribute("aria-pressed", "true");
      await expect(chart).toHaveAttribute("data-patterns", "2");
      await page.screenshot({ path: testInfo.outputPath("patterns-restored.png"), fullPage: true });
      expect(asked).toEqual(["medium"]);
      expect(errors).toEqual([]);
    });
  }
}
