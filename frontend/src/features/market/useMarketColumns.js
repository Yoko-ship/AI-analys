import { snapPixel } from "../../lib/geometry.js";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
export function useMarketColumns({
  MARKET_COLS,
  type
}) {
  const [visibleCols, setVisibleCols] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("uz_market_cols_v3"));
      if (Array.isArray(s)) return new Set(s);
    } catch (e) {/* ignore */}
    return new Set(["change", "change1w", "change1m", "nominal", "open", "high", "low", "volume", "date", "source"]);
  });
  const [colsOpen, setColsOpen] = useState(false);
  const colsBtnRef = useRef(null);
  const [colsSearch, setColsSearch] = useState("");
  const [openGroups, setOpenGroups] = useState(() => new Set(["overview", "volumes", "financials"]));
  const toggleGroup = k => setOpenGroups(prev => {
    const n = new Set(prev);
    if (n.has(k)) n.delete(k);else n.add(k);
    return n;
  });
  useEffect(() => {
    try {
      localStorage.setItem("uz_market_cols_v3", JSON.stringify([...visibleCols]));
    } catch (e) {/* ignore */}
  }, [visibleCols]);
  const toggleCol = k => setVisibleCols(prev => {
    const n = new Set(prev);
    if (n.has(k)) n.delete(k);else n.add(k);
    return n;
  });
  const EQUITY_ONLY_COLS = new Set(["mktCap", "pe", "pb", "ps", "roe", "roa", "netMargin", "eqAssets", "finRevenue", "finGross", "finCash", "finLiab", "finNet", "finOperating", "currentRatio", "quickRatio", "debtAssets", "assetTurnover", "roce"]);
  const MOVABLE_KEYS = ["last", ...MARKET_COLS.map(([k]) => k)];
  const [colOrder, setColOrder] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("uz_market_col_order_v2"));
      if (Array.isArray(s)) {
        const known = new Set(["last", ...MARKET_COLS.map(([k]) => k)]);
        const kept = s.filter(k => known.has(k));
        const missing = ["last", ...MARKET_COLS.map(([k]) => k)].filter(k => !kept.includes(k));
        return [...kept, ...missing];
      }
    } catch (e) {/* ignore */}
    return ["last", ...MARKET_COLS.map(([k]) => k)];
  });
  useEffect(() => {
    try {
      localStorage.setItem("uz_market_col_order_v2", JSON.stringify(colOrder));
    } catch (e) {/* ignore */}
  }, [colOrder]);
  const [dragCol, setDragCol] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const wrapRef = useRef(null);
  const moveCol = (from, to) => {
    if (!from || from === to) return;
    setColOrder(prev => {
      const arr = prev.filter(k => MOVABLE_KEYS.includes(k));
      const fi = arr.indexOf(from);
      const ti = arr.indexOf(to);
      if (fi < 0 || ti < 0) return prev;
      const next = [...arr];
      next.splice(fi, 1);
      next.splice(ti, 0, from);
      return next;
    });
  };
  const resetColOrder = () => setColOrder(["last", ...MARKET_COLS.map(([k]) => k)]);
  const [pinnedCols, setPinnedCols] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("uz_market_pinned_cols"));
      if (Array.isArray(s)) return new Set(s);
    } catch (e) {/* ignore */}
    return new Set();
  });
  useEffect(() => {
    try {
      localStorage.setItem("uz_market_pinned_cols", JSON.stringify([...pinnedCols]));
    } catch (e) {/* ignore */}
  }, [pinnedCols]);
  const togglePin = k => setPinnedCols(prev => {
    const n = new Set(prev);
    if (n.has(k)) n.delete(k);else n.add(k);
    return n;
  });
  const shownOrder = colOrder.filter(k => (k === "last" || visibleCols.has(k)) && !(type === "bond" && EQUITY_ONLY_COLS.has(k)));
  const pinnedOrder = shownOrder.filter(k => pinnedCols.has(k));
  const visibleOrder = [...pinnedOrder, ...shownOrder.filter(k => !pinnedCols.has(k))];
  const colSpan = 3 + visibleOrder.length;
  const [pinOffsets, setPinOffsets] = useState({});
  const pinMeasureRef = useRef(() => {});
  const pinKeys = pinnedOrder.join("|");
  useEffect(() => {
    const measure = () => {
      const head = wrapRef.current && wrapRef.current.querySelector(".market-table thead tr");
      if (!head || !pinKeys) {
        setPinOffsets(prev => Object.keys(prev).length ? {} : prev);
        return;
      }
      const widths = Array.from(head.children).map(th => th.getBoundingClientRect().width);
      const next = {};
      let acc = 0;
      // The header row is [ticker, company, ...visibleOrder], and the frozen
      // columns are the first of visibleOrder — so the run is contiguous.
      ["__ticker", "__company", ...pinKeys.split("|")].forEach((k, i) => {
        next[k] = snapPixel(acc);
        acc += widths[i] || 0;
      });
      setPinOffsets(prev => {
        const ks = Object.keys(next);
        if (ks.length === Object.keys(prev).length && ks.every(k => prev[k] === next[k])) return prev;
        return next;
      });
    };
    pinMeasureRef.current = measure;
    measure();
    window.addEventListener("resize", measure);
    return () => {
      pinMeasureRef.current = () => {};
      window.removeEventListener("resize", measure);
    };
  }, [pinKeys]);
  useLayoutEffect(() => {
    pinMeasureRef.current();
  });
  const lastPinned = pinnedOrder[pinnedOrder.length - 1];
  const pinAt = key => pinKeys && pinOffsets[key] !== undefined ? {
    left: pinOffsets[key],
    edge: key === lastPinned
  } : null;
  const pinCls = pin => pin ? ` market-col-pinned${pin.edge ? " market-col-pinned-edge" : ""}` : "";
  const colGroupOf = key => visibleOrder.filter(k => pinnedCols.has(k) === pinnedCols.has(key));
  const moveColBy = (key, step) => {
    const group = colGroupOf(key);
    const i = group.indexOf(key);
    if (i < 0) return;
    if (step === "start") {
      if (i > 0) moveCol(key, group[0]);
      return;
    }
    if (step === "end") {
      if (i < group.length - 1) moveCol(key, group[group.length - 1]);
      return;
    }
    const j = i + step;
    if (j >= 0 && j < group.length) moveCol(key, group[j]);
  };
  const [colMenu, setColMenu] = useState(null);
  const closeColMenu = React.useCallback(() => setColMenu(null), []);
  return {
    visibleCols,
    setVisibleCols,
    colsOpen,
    setColsOpen,
    colsBtnRef,
    colsSearch,
    setColsSearch,
    openGroups,
    toggleGroup,
    toggleCol,
    MOVABLE_KEYS,
    dragCol,
    setDragCol,
    dragOverCol,
    setDragOverCol,
    wrapRef,
    moveCol,
    resetColOrder,
    pinnedCols,
    togglePin,
    shownOrder,
    visibleOrder,
    colSpan,
    pinAt,
    pinCls,
    colGroupOf,
    moveColBy,
    colMenu,
    setColMenu,
    closeColMenu
  };
}
