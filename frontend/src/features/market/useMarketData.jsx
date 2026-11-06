import { useEffect, useRef, useState } from "react";
import { mt } from "../../shared/marketCopy.jsx";
import { splitLanguagePath } from "../../lib/languagePath.js";
import { requestMarketData } from "../../lib/marketStartup.js";

export function useMarketData({ toasts: toastsModule, preferences: preferencesModule, session: sessionModule, navigation: navigationModule }) {
  const { addToast } = toastsModule;
  const { language } = preferencesModule;
  const { apiFetch, canAccessCatalog } = sessionModule;
  const { activeView } = navigationModule;
  // Comparison owns its bounded data request; avoid fetching the full market
  // and catalog again in the shell. Load normal data when leaving it.
  const needsCatalog = activeView !== "companyCompare" && (activeView !== "catalog" || canAccessCatalog);
  const [companies, setCompanies] = useState([]);

  const [catalogStatus, setCatalogStatus] = useState(null);

  const [marketRows, setMarketRows] = useState([]);

  const [marketMeta, setMarketMeta] = useState({ updated_at: null, count: 0 });

  const [marketType, setMarketType] = useState(() => (
    splitLanguagePath(window.location.pathname).path.replace(/\/+$/, "") === "/bonds" ? "bond" : "stock"));

  const [marketQuery, setMarketQuery] = useState("");

  const [marketLoading, setMarketLoading] = useState(false);
  const marketRequest = useRef(0);
  const [marketLoadVersion, setMarketLoadVersion] = useState(0);

  const [marketMessage, setMarketMessage] = useState("");

  const [securitiesMap, setSecuritiesMap] = useState({});

  const [marketFinancials, setMarketFinancials] = useState({});

  const [marketTradeStats, setMarketTradeStats] = useState({});
  // Share-class switches filter the same equity snapshot. Only an instrument
  // type change needs a different request; explicit refresh still reloads it.
  const quoteType = ["profile", "issuers"].includes(activeView) || ["ordinary", "preferred"].includes(marketType) ? "stock" : marketType;

  useEffect(() => {
    if (!needsCatalog) return;
    loadCompanies().catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, needsCatalog]);

  useEffect(() => {
    if (!needsCatalog || !canAccessCatalog || activeView === "catalog") return;
    apiFetch("/api/catalog/status")
      .then((r) => r.json())
      .then((d) => { if (d.ok) setCatalogStatus(d); })
      .catch(() => {});
  }, [apiFetch, needsCatalog, canAccessCatalog, activeView]);

  useEffect(() => {
    // "main": the landing's ticker tape, board preview and movers are the real
    // board, so the "/" page needs the same rows the market view reads.
    if (activeView !== "issuers" && activeView !== "market" && activeView !== "heatmap"
      && activeView !== "company" && activeView !== "chart" && activeView !== "main" && activeView !== "auth"
      && activeView !== "profile") return;
    loadMarketStocks(quoteType).catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, quoteType, language]);

  useEffect(() => {
    if (!needsCatalog) return;
    requestMarketData("/api/securities", apiFetch)
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.securities) setSecuritiesMap(d.securities); })
      .catch(() => {});
  }, [apiFetch, needsCatalog]);

  const loadTradeStats = async () => {
    try {
      const response = await requestMarketData("/api/market/trade-stats");
      const data = await response.json();
      return data.ok ? data : null;
    } catch { return null; }
  };

  const loadCompanies = async () => {
    const res = await requestMarketData("/api/companies", apiFetch);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load companies");
    setCompanies(data.companies || []);
  };

  const loadMarketStocks = async (typeOverride = null, { refresh = false } = {}) => {
    const requestId = ++marketRequest.current;
    if (!refresh) setMarketLoadVersion(requestId);
    setMarketLoading(true);
    const needsStats = ["issuers", "market", "heatmap", "company", "chart", "main"].includes(activeView);
    // Cold navigation starts independent reads together. A forced refresh waits
    // for new quotes before fetching their supplements, preserving freshness.
    const statsRequest = needsStats && !refresh ? loadTradeStats() : null;
    setMarketMessage(mt(language, "loading"));
    try {
      const params = new URLSearchParams();
      // "ordinary"/"preferred" are share-type subsets the server can't filter (it
      // only knows stock/bond), so fetch stocks and narrow client-side.
      const requestedType = typeof typeOverride === "string" ? typeOverride : marketType;
      const apiType = (requestedType === "preferred" || requestedType === "ordinary") ? "stock" : requestedType;
      params.set("type", apiType);
      if (refresh) params.set("refresh", "true");
      const res = await requestMarketData(`/api/market/stocks${params.toString() ? `?${params}` : ""}`, apiFetch);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not load stock prices");
      if (requestId !== marketRequest.current) return;
      setMarketRows(Array.isArray(data.stocks) ? data.stocks : []);
      // Merge, don't replace: `refreshed_at`/`trade_date` come from the
      // trade-stats call, which runs on its own and must survive a reload here.
      setMarketMeta((prev) => ({ ...prev, updated_at: data.updated_at || null, count: data.count || 0, type: data.type || requestedType }));
      if (refresh) setMarketLoadVersion(requestId);
      if (needsStats) void (statsRequest || loadTradeStats()).then(data => {
        if (!data || requestId !== marketRequest.current) return;
        if (data.stats) setMarketTradeStats(data.stats);
        // Apply the timestamp with its quotes, even when statistics arrived first.
        setMarketMeta(prev => ({...prev, refreshed_at:data.quotes_refreshed_at || null,
          trade_date:data.trade_date || null, validation:data.validation || null}));
      });
      setMarketMessage(mt(language, "ready"));
    } catch (error) {
      if (requestId !== marketRequest.current) return;
      setMarketMessage(error.message);
      throw error;
    } finally {
      if (requestId === marketRequest.current) setMarketLoading(false);
    }
  };

  const resolveTicker = (value) => {
    const normalized = String(value || "").trim();
    if (!normalized) return "";
    const upper = normalized.toUpperCase();
    const match = companies.find((item) => item.ticker.toUpperCase() === upper || item.company_name.toLowerCase() === normalized.toLowerCase());
    return match?.ticker || upper;
  };
  return { marketLoadVersion, catalogStatus, companies, loadMarketStocks, marketFinancials, marketLoading, marketMessage, marketMeta, marketQuery, marketRows, marketTradeStats, marketType, resolveTicker, securitiesMap, setMarketQuery, setMarketType };
}
