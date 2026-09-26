import { useEffect, useState } from "react";
import { mt } from "../../shared/marketCopy.jsx";

export function useMarketData({ toasts: toastsModule, preferences: preferencesModule, session: sessionModule, navigation: navigationModule }) {
  const { addToast } = toastsModule;
  const { language } = preferencesModule;
  const { apiFetch } = sessionModule;
  const { activeView } = navigationModule;
  const [companies, setCompanies] = useState([]);

  const [catalogStatus, setCatalogStatus] = useState(null);

  const [marketRows, setMarketRows] = useState([]);

  const [marketMeta, setMarketMeta] = useState({ updated_at: null, count: 0 });

  const [marketType, setMarketType] = useState(() => (
    window.location.pathname.replace(/\/+$/, "") === "/bonds" ? "bond" : "stock"));

  const [marketQuery, setMarketQuery] = useState("");

  const [marketLoading, setMarketLoading] = useState(false);

  const [marketMessage, setMarketMessage] = useState("");

  const [securitiesMap, setSecuritiesMap] = useState({});

  const [marketFinancials, setMarketFinancials] = useState({});

  const [marketTradeStats, setMarketTradeStats] = useState({});

  useEffect(() => {
    loadCompanies().catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  useEffect(() => {
    apiFetch("/api/catalog/status")
      .then((r) => r.json())
      .then((d) => { if (d.ok) setCatalogStatus(d); })
      .catch(() => {});
  }, [apiFetch]);

  useEffect(() => {
    // "main": the landing's ticker tape, board preview and movers are the real
    // board, so the "/" page needs the same rows the market view reads.
    if (activeView !== "market" && activeView !== "heatmap"
      && activeView !== "company" && activeView !== "chart" && activeView !== "main" && activeView !== "auth"
      && activeView !== "profile" && activeView !== "portfolio") return;
    loadMarketStocks((activeView === "profile" || activeView === "portfolio") ? "stock" : null).catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, marketType, language]);

  useEffect(() => {
    apiFetch("/api/securities")
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.securities) setSecuritiesMap(d.securities); })
      .catch(() => {});
  }, [apiFetch]);

  useEffect(() => {
    // "main" for the same reason as the stocks load above: the landing must
    // restate its rows against the same per-trade day statistics as /market.
    if (activeView !== "market" && activeView !== "heatmap"
      && activeView !== "company" && activeView !== "chart" && activeView !== "main") return;
    if (!marketRows.length || marketLoading) return;
    fetch("/api/market/trade-stats")
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) return;
        if (d.stats) setMarketTradeStats(d.stats);
        // When OUR pipeline last wrote the board. Merged into the market meta
        // rather than kept apart, because the header badge reads one object.
        setMarketMeta((prev) => ({ ...prev, refreshed_at: d.refreshed_at || null, trade_date: d.trade_date || null }));
      })
      .catch(() => {});
  }, [activeView, marketRows.length, marketLoading]);

  const loadCompanies = async () => {
    const res = await apiFetch("/api/companies");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load companies");
    setCompanies(data.companies || []);
  };

  const loadMarketStocks = async (typeOverride = null, { refresh = false } = {}) => {
    setMarketLoading(true);
    setMarketMessage(mt(language, "loading"));
    try {
      const params = new URLSearchParams();
      // "ordinary"/"preferred" are share-type subsets the server can't filter (it
      // only knows stock/bond), so fetch stocks and narrow client-side.
      const requestedType = typeof typeOverride === "string" ? typeOverride : marketType;
      const apiType = (requestedType === "preferred" || requestedType === "ordinary") ? "stock" : requestedType;
      params.set("type", apiType);
      if (refresh) params.set("refresh", "true");
      const res = await apiFetch(`/api/market/stocks${params.toString() ? `?${params}` : ""}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not load stock prices");
      setMarketRows(Array.isArray(data.stocks) ? data.stocks : []);
      // Merge, don't replace: `refreshed_at`/`trade_date` come from the
      // trade-stats call, which runs on its own and must survive a reload here.
      setMarketMeta((prev) => ({ ...prev, updated_at: data.updated_at || null, count: data.count || 0, type: data.type || requestedType }));
      setMarketMessage(mt(language, "ready"));
    } catch (error) {
      setMarketMessage(error.message);
      throw error;
    } finally {
      setMarketLoading(false);
    }
  };

  const resolveTicker = (value) => {
    const normalized = String(value || "").trim();
    if (!normalized) return "";
    const upper = normalized.toUpperCase();
    const match = companies.find((item) => item.ticker.toUpperCase() === upper || item.company_name.toLowerCase() === normalized.toLowerCase());
    return match?.ticker || upper;
  };
  return { catalogStatus, companies, loadMarketStocks, marketFinancials, marketLoading, marketMessage, marketMeta, marketQuery, marketRows, marketTradeStats, marketType, resolveTicker, securitiesMap, setMarketQuery, setMarketType };
}
