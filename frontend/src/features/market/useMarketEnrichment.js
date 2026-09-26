import { useCallback, useEffect, useRef, useState } from "react";
export function useMarketEnrichment({
  rows,
  loading,
  viewMode,
  visibleCols,
  financials,
  type
}) {
  const [ratios, setRatios] = useState({});
  const ratiosRequested = useRef(false);
  const [changes, setChanges] = useState({});
  useEffect(() => {
    if (!rows.length || loading) return undefined;
    let alive = true;
    fetch("/api/market/changes").then(r => r.json()).then(d => {
      if (alive && d && d.ok) setChanges(d.changes || {});
    }).catch(() => {});
    return () => {
      alive = false;
    };
  }, [rows.length, loading]);
  const [multiples, setMultiples] = useState({});
  const [multiplesStatus, setMultiplesStatus] = useState("idle");
  const [onDemandFinancials, setOnDemandFinancials] = useState({});
  const financialsRequested = useRef(false);
  const multiplesRequested = useRef(false);
  const financialsRequest = useRef(null);
  const multiplesRequest = useRef(null);
  const [marketSummary, setMarketSummary] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [instruments, setInstruments] = useState({});
  useEffect(() => {
    if (!rows.length || loading) return undefined;
    let alive = true;
    // The single instrument universe (ТЗ §4). `is_active` here follows TRADING —
    // ninety days without an execution — rather than a registry flag, which is
    // what the "показать неактивные" switch below actually filters on.
    fetch("/api/instruments").then(r => r.json()).then(d => {
      if (!alive || !d || !d.ok) return;
      const by = {};
      (d.items || []).forEach(i => {
        by[i.ticker] = i;
      });
      setInstruments(by);
    }).catch(() => {});
    return () => {
      alive = false;
    };
  }, [rows.length, loading]);
  useEffect(() => {
    // Summary cards and map tiles do not exist on /market.  Fetching both there
    // spent bandwidth and server time for UI that could not be opened without a
    // route change.
    if (viewMode !== "heatmap" || !rows.length || loading) return undefined;
    let alive = true;
    fetch("/api/market/summary").then(r => r.json()).then(d => {
      if (alive && d && d.ok) setMarketSummary(d);
    }).catch(() => {});
    // The market map in ONE request (ТЗ §9): tiles, sector aggregates and the
    // counts behind them. It used to be stitched together on the client from
    // endpoints with different instrument universes.
    fetch("/api/heatmap").then(r => r.json()).then(d => {
      if (alive && d && d.ok) setMapData(d);
    }).catch(() => {});
    return () => {
      alive = false;
    };
  }, [viewMode, rows.length, loading]);
  const needsFinancials = ["finRevenue", "finGross", "finCash", "finLiab", "finNet", "finOperating"].some(key => visibleCols.has(key));
  const needsRatios = ["currentRatio", "quickRatio", "debtAssets", "assetTurnover", "roce"].some(key => visibleCols.has(key));
  const needsMultiples = ["pe", "pb", "ps", "roe", "roa", "netMargin", "eqAssets"].some(key => visibleCols.has(key));
  const suppliedFinancials = Object.keys(financials || {}).length > 0;
  const secondaryEquityReady = Boolean(rows.length && !loading && type !== "bond");
  // The board and export share in-flight requests and successful responses.
  // Failed requests can be retried explicitly without a render/fetch loop.
  const loadFinancials = useCallback(() => {
    if (suppliedFinancials) return Promise.resolve();
    if (!financialsRequest.current) {
      financialsRequest.current = fetch("/api/market/financials").then(r => {
        if (!r.ok) throw new Error("financials request failed");
        return r.json();
      }).then(d => {
        if (!d?.ok || !d.financials || typeof d.financials !== "object" || Array.isArray(d.financials)) {
          throw new Error("financials payload unavailable");
        }
        setOnDemandFinancials(d.financials);
      }).catch(error => {
        financialsRequest.current = null;
        throw error;
      });
    }
    return financialsRequest.current;
  }, [suppliedFinancials]);
  const loadMultiples = useCallback(() => {
    if (!multiplesRequest.current) {
      setMultiplesStatus("loading");
      multiplesRequest.current = fetch("/api/market/multiples?view=board").then(r => {
        if (!r.ok) throw new Error("multiples request failed");
        return r.json();
      }).then(d => {
        if (!d?.ok || !Array.isArray(d.items)) throw new Error("multiples payload unavailable");
        setMultiples(Object.fromEntries(d.items.map(item => [item.ticker, item])));
        setMultiplesStatus("ready");
      }).catch(error => {
        multiplesRequest.current = null;
        setMultiplesStatus("unavailable");
        throw error;
      });
    }
    return multiplesRequest.current;
  }, []);
  const prepareExport = () => type === "bond" ? Promise.resolve() : Promise.all([loadFinancials(), loadMultiples()]);
  useEffect(() => {
    if (!needsFinancials || suppliedFinancials || financialsRequested.current || !secondaryEquityReady) return;
    financialsRequested.current = true;
    loadFinancials().catch(() => {});
  }, [needsFinancials, suppliedFinancials, secondaryEquityReady, loadFinancials]);
  useEffect(() => {
    if (!needsRatios || ratiosRequested.current || !secondaryEquityReady) return;
    ratiosRequested.current = true;
    fetch("/api/market/ratios").then(r => r.json()).then(d => {
      setRatios(d.ok && d.ratios ? d.ratios : {});
    }).catch(() => {});
  }, [needsRatios, secondaryEquityReady]);
  useEffect(() => {
    if (!needsMultiples || multiplesRequested.current || !secondaryEquityReady) return;
    multiplesRequested.current = true;
    loadMultiples().catch(() => {});
  }, [needsMultiples, secondaryEquityReady, loadMultiples]);
  return {
    prepareExport,
    ratios,
    changes,
    multiples,
    multiplesStatus,
    onDemandFinancials,
    marketSummary,
    mapData,
    instruments,
    suppliedFinancials
  };
}
