import {expect} from "@playwright/test";

const day = "2026-09-25";
export const row = (ticker, price, prev, volume) => ({
  ticker, type: "stock", isin: `UZ${ticker}`, name: `${ticker} issuer`, last_price: price, close_price: prev,
  volume, quantity: 1000, trade_count: 4, last_trade_date: day, industry: "finance",
});
export const stocks = [row("AGBA", 1000, 900, 1e6), row("KVTS", 3000, 3100, 3e6)];

export async function openBoard(page, cols, validation = null, refreshedAt = null, boardStocks = stocks, {admin = false} = {}) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(({saved, admin}) => {
    if (admin) localStorage.setItem('uz_stock_analyzer_token', 'market-performance');
    sessionStorage.setItem("uz_sponsor_seen", "1");
    localStorage.setItem("uz_track_internal", "1");
    localStorage.setItem("uz_market_cols_v3", JSON.stringify(saved));
    localStorage.removeItem("uz_market_col_order_v2");
    localStorage.removeItem("uz_market_pinned_cols");
  }, {saved:cols, admin});
  await page.route("**/api/**", (route) => {
    const url = new URL(route.request().url());
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (url.pathname === "/api/companies") return json({ companies: boardStocks.map((r) => ({ ticker: r.ticker, company_name: r.name, sector: r.industry })) });
    if (url.pathname === "/api/securities") return json({ ok: true, securities: Object.fromEntries(boardStocks.map((r) => [r.ticker, { ...r, security_type: "stock" }])) });
    if (url.pathname === "/api/market/stocks") return json({ stocks: boardStocks, updated_at: "2026-11-05T05:00:00Z" });
    if (url.pathname === "/api/market/trade-stats") return json({ ok: true, stats: {}, validation,
      refreshed_at: "2026-11-05T04:30:00Z", quotes_refreshed_at: refreshedAt });
    if (url.pathname === "/api/market/financials") return json({ ok: true, financials: {} });
    if (url.pathname === "/api/market/multiples") return json({ ok: true, items: [] });
    if (url.pathname === "/api/auth/me") return admin ? json({user:{id:1,is_admin:true,email:'market@example.test'}}) : json({ user: null }, 401);
    return json({ ok: true });
  });
  await page.goto("/market");
  await expect(page.locator(".market-table tbody tr")).toHaveCount(boardStocks.length);
  return errors;
}
