import { prepareMarketRows } from "../../lib/marketData.js";
import { blocksMarketContent } from "../../lib/marketLoading.js";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { avgSharePrice, avgTradeValue, buildMarketStats, compareSortValues, finValue, formatCompactVolume, formatMarketTimestamp, marketDisplayPrice, marketStampTitle, sessionCountLabel, tradeCountLabel } from "../../shared/marketModel.jsx";
import { mt, sectorLabel } from "../../shared/marketCopy.jsx";
import { orderSectors, sectorOf } from "../../lib/sectors.js";
import { RangeHelpIcon, incompleteIssuerCapAvailability, lossLabel, lossTitle, multipleStatusText, notApplicableTitle, outlierLabel, outlierTitle } from "../../shared/valuationLabels.jsx";
import { formatMarketNumber, formatRatio } from "../../shared/format.jsx";
import { finFieldCoverage, finFieldPeriod, finPeriodCoverage, finRowPeriod, marketRowDay } from "../../lib/valuation.js";
import { TermInfo } from "../../shared/TermInfo.jsx";
import { MarketChangeBadge } from "../../shared/MarketChangeBadge.jsx";
import { FxRatesBar } from "../currency/index.js";
import { MarketBreadthCard, MarketStatCard } from "./Statistics.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { MarketColMenu, MarketColsPopover, MarketFloatScroll, MarketStickyHead } from "./TableOverlays.jsx";
import { BondsView } from "../bonds/index.js";
import { MarketHeatmap } from "./Heatmap.jsx";
import { CompanyInfoPanel } from "./CompanyInfoPanel.jsx";

function MarketView({
  rows,
  meta,
  loading,
  message,
  query,
  onQueryChange,
  type,
  onTypeChange,
  onRefresh,
  onAnalyze,
  onOpenCompany,
  onOpenBond,
  onOpenBankFx,
  language,
  companies,
  securitiesMap,
  financials,
  tradeStats,
  favoriteTickers,
  onToggleFavorite,
  viewMode: viewModeProp,
  onViewModeChange,
  isAdmin = false,
}) {
  const lang = normalizeLanguage(language);
  // viewMode is driven by the route (table = /market, heatmap = /heatmap).
  const viewMode = viewModeProp || "table";
  const setViewMode = onViewModeChange || (() => {});
  const [marketSector, setMarketSector] = useState(null);
  const [favOnly, setFavOnly] = useState(false);
  const [panelTicker, setPanelTicker] = useState(null);
  const [panelWiki, setPanelWiki] = useState(null);
  const [panelWikiLoading, setPanelWikiLoading] = useState(false);
  const hasFav = (t) => !!favoriteTickers && favoriteTickers.has(String(t || "").trim().toUpperCase());

  // Per-ticker financial ratios & equity (facts store) for P/E, P/B and the
  // §3.8 ratio-coefficient columns. Fetched once; keyed by ticker.
  const [ratios, setRatios] = useState({});
  const ratiosRequested = useRef(false);

  // Price change over a WEEK, a MONTH, a quarter, half a year, a year and
  // year-to-date, per security, off the same stored closes the charts draw
  // (/api/market/changes). The board measured one period — the session — so
  // «сколько он сделал за месяц?» meant opening every company page in turn.
  //
  // The period is the reader's choice and it travels: the «Изменение» column,
  // the movers strip on this page and the board preview on the landing page all
  // follow it, because three answers to one question on one screen is worse than
  // none. The explicit «Изм. 1Н» and «Изм. 1М» columns never move — a reader
  // comparing the week against the month needs both at once.
  const [changes, setChanges] = useState({});
  useEffect(() => {
    if (!rows.length || loading) return undefined;
    let alive = true;
    fetch("/api/market/changes")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setChanges(d.changes || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [rows.length, loading]);
  // Which of the exchange's two boards is on screen. Not persisted: MAIN is the
  // market, NEGO is a handful of deals on a given day, and a reader who returns
  // tomorrow to a five-row board they do not remember choosing would read it as
  // the market having collapsed.
  const [segment, setSegment] = useState("main");
  const [changePeriod, setChangePeriod] = useState(() => {
    try {
      const saved = localStorage.getItem(CHANGE_PERIOD_KEY);
      if (CHANGE_PERIODS.some((p) => p.code === saved)) return saved;
    } catch (e) { /* ignore */ }
    return "1d";
  });
  useEffect(() => {
    try { localStorage.setItem(CHANGE_PERIOD_KEY, changePeriod); } catch (e) { /* ignore */ }
  }, [changePeriod]);
  // One security's change over one period, as {pct, from} or null. The session
  // keeps its own rule — a security that did not trade today has NO change to
  // report (ТЗ §2.4), which is a different statement from a flat one — while a
  // window is answered by the stored closes or not at all.
  const changeOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = (changes[String(ticker || "").toUpperCase()] || {})[code];
    return hit && Number.isFinite(hit.pct) ? hit : null;
  };
  // The same window's TURNOVER, as {value, sessions, from} — the sum of what the
  // security changed hands for over it. Kept separate from the change because a
  // line can have traded over a month without having a close a month back to
  // measure from (its history starts inside the window), and the liquidity panel
  // must still be able to rank it.
  const turnoverOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = ((changes[String(ticker || "").toUpperCase()] || {}).turnover || {})[code];
    return hit && Number.isFinite(hit.value) ? hit : null;
  };
  // Everything ELSE the window did, on the same footing as a session: its
  // opening price, its high and low, the сумы and the bumagi that changed hands,
  // the average share price, the average deal and the biggest one.
  //
  // Customer, 19.08.2026: «когда я выбираю период — например за год — должны
  // МЕНЯТЬСЯ цифры: открытие, макс, мин, объём в сумах/шт, ср. цена акции,
  // ср. сумма сделки, крупнейшая сделка, объёмы %, капитализация, объём торгов,
  // рост, снижение — а не только показывать их изменение». Until now the board
  // could restate two of them (the percent and the turnover) and reprinted the
  // SESSION's figures under every other heading, so a row read «за год» beside
  // this morning's high and low.
  const statsOver = (ticker, code) => {
    if (code === "1d") return null;
    const hit = ((changes[String(ticker || "").toUpperCase()] || {}).stats || {})[code];
    return hit || null;
  };

  // «Номинальная стоимость» of the security, off the exchange's own card via the
  // listing registry (`parval`), joined onto the board row by the server. A zero
  // par is the card saying "not stated" and the collector lands that as absent —
  // so any number here is a filed one, and a dash is the source's silence rather
  // than a rounding of nothing.
  const parOf = (row) => {
    const par = Number(row?.nominal);
    return Number.isFinite(par) && par > 0 ? par : null;
  };
  // What the market pays per sum of par. For a bond this is the конвенция the
  // whole market quotes in (a price is a percentage of par); for a share it is
  // the plainest possible statement of how far the price has left its issue
  // value behind. Shown as a multiple, not a percent, because on this market the
  // numbers run from 0.3x to 60x and a percent column of «5 800 %» reads as an
  // error.
  const priceToPar = (row) => {
    const par = parOf(row);
    const price = marketDisplayPrice(row);
    return par && Number.isFinite(price) && price > 0 ? price / par : null;
  };

  // Multiples come from the server, computed per ISSUER (ТЗ §8). Keyed by
  // ticker, but both classes of an issuer carry the same object — that is the
  // point: the board used to divide ONE class's capitalisation by the WHOLE
  // issuer's profit, so no pair of classes could agree. A statement that failed
  // validation arrives with its multiples already suppressed and the reason
  // attached, so nothing here has to decide what is publishable.
  const [multiples, setMultiples] = useState({});
  const [multiplesStatus, setMultiplesStatus] = useState("idle");
  const [onDemandFinancials, setOnDemandFinancials] = useState({});
  const financialsRequested = useRef(false);
  const multiplesRequested = useRef(false);
  const [marketSummary, setMarketSummary] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [instruments, setInstruments] = useState({});
  // ТЗ §4: dormant listings are hidden by default and reachable by a switch —
  // not dropped, because a security that stopped trading is a fact about the
  // market and hiding it permanently is how five references came to disagree.
  //
  // The switch is a FILTER, not an "include" checkbox. It is named «Неактивные»
  // and sits beside «Избранное», which shows favourites and only favourites —
  // so pressing it and getting the whole board back with eleven more rows
  // buried in it read as a broken button. Now it lands the reader on the
  // eleven, which is the question the chip's name asks.
  const [inactiveOnly, setInactiveOnly] = useState(false);
  useEffect(() => {
    if (!rows.length || loading) return undefined;
    let alive = true;
    // The single instrument universe (ТЗ §4). `is_active` here follows TRADING —
    // ninety days without an execution — rather than a registry flag, which is
    // what the "показать неактивные" switch below actually filters on.
    fetch("/api/instruments")
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const by = {};
        (d.items || []).forEach((i) => { by[i.ticker] = i; });
        setInstruments(by);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, [rows.length, loading]);

  useEffect(() => {
    if (viewMode !== "heatmap" || !rows.length || loading) return undefined;
    let alive = true;
    fetch("/api/market/summary")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setMarketSummary(d); })
      .catch(() => {});
    // The market map in ONE request (ТЗ §9): tiles, sector aggregates and the
    // counts behind them. It used to be stitched together on the client from
    // endpoints with different instrument universes.
    fetch("/api/heatmap")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setMapData(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [viewMode, rows.length, loading]);

  // Column sorting, as an ORDERED chain of keys. An empty chain falls back to the
  // default (date desc, then |change|) — which is itself two-level, and used to be
  // the only two-level order the board could express: one click on any header threw
  // it away. "Latest session first, biggest turnover within the day" is the question
  // the board is actually read with, and it needs two columns to ask.
  //
  // Plain click collapses back to a single key (the old behaviour, unchanged).
  // Shift/⌘/Ctrl-click appends: first press adds the column, second flips its
  // direction, third drops it out of the chain again.
  const [sortKeys, setSortKeys] = useState([]);
  // Text columns read best ascending, numeric/date columns descending.
  const defaultSortDir = (key) => (["ticker", "company"].includes(key) ? "asc" : "desc");
  const sortRankOf = (key) => sortKeys.findIndex((s) => s.key === key);
  const sortDirOf = (key) => sortKeys.find((s) => s.key === key)?.dir || null;
  const onSort = (key, additive = false) => {
    setSortKeys((prev) => {
      const i = prev.findIndex((s) => s.key === key);
      if (!additive) {
        // Re-clicking the only active key flips it; anything else starts over.
        if (prev.length === 1 && i === 0) return [{ key, dir: prev[0].dir === "asc" ? "desc" : "asc" }];
        return [{ key, dir: defaultSortDir(key) }];
      }
      if (i < 0) return [...prev, { key, dir: defaultSortDir(key) }];
      const next = [...prev];
      if (next[i].dir === defaultSortDir(key)) {
        next[i] = { key, dir: next[i].dir === "asc" ? "desc" : "asc" };
        return next;
      }
      next.splice(i, 1);
      return next;
    });
  };
  const clearSort = () => setSortKeys([]);
  // A phone has no Shift key, and the board stays a table there. Long-press on a
  // header is the touch equivalent of the modifier: it appends instead of replacing.
  const longPress = useRef({ timer: null, fired: false });
  const startLongPress = (key) => {
    longPress.current.fired = false;
    clearTimeout(longPress.current.timer);
    longPress.current.timer = setTimeout(() => {
      longPress.current.fired = true;
      onSort(key, true);
    }, 500);
  };
  const cancelLongPress = () => clearTimeout(longPress.current.timer);
  useEffect(() => () => clearTimeout(longPress.current.timer), []);
  // A modifier nobody is told about is a feature nobody has. The hint appears the
  // moment it becomes actionable — right after the first column is sorted, not on
  // a cold page where it would be noise — and retires for good once the reader has
  // either built a two-key order or dismissed it.
  const [sortHintSeen, setSortHintSeen] = useState(() => {
    try { return localStorage.getItem("uz_market_sort_hint") === "seen"; } catch (e) { return false; }
  });
  const dismissSortHint = () => {
    setSortHintSeen(true);
    try { localStorage.setItem("uz_market_sort_hint", "seen"); } catch (e) { /* ignore */ }
  };
  useEffect(() => {
    if (sortKeys.length > 1 && !sortHintSeen) dismissSortHint();
  }, [sortKeys.length, sortHintSeen]); // eslint-disable-line react-hooks/exhaustive-deps
  // Touch has no Shift key, so the hint must name the gesture that device HAS.
  const coarsePointer = typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(pointer: coarse)").matches;

  // User-configurable quote columns (ticker/company/last are always shown).
  // Quote columns grouped into collapsible sections in the settings dropdown.
  // Each section is a sibling of "AI screener overview" (not nested under it).
  const COL_GROUPS = [
    { key: "overview", title: mt(lang, "grpOverview"), cols: [
      // «Изм.» follows the period selector; these two never do. A reader who is
      // comparing the week against the month needs both on screen at once, and a
      // column whose meaning depends on a control elsewhere cannot be that.
      ["change", `${mt(lang, "change")} (${changePeriodLabel(changePeriod, lang, "short")})`],
      ["change1w", `${mt(lang, "change")} 1${lang === "en" ? "W" : lang === "uz" ? "H" : "Н"}`],
      ["change1m", `${mt(lang, "change")} 1${lang === "en" ? "M" : lang === "uz" ? "O" : "М"}`],
      // «Номинальная стоимость» and what the market pays for it. The par is a
      // registry fact about the security; the ratio beside it is the reading a
      // par is FOR — a share trading at eighteen times its par and one trading
      // below it are two different propositions.
      ["nominal", mt(lang, "nominalCol")],
      ["priceToPar", mt(lang, "nominalToPrice")],
      ["open", mt(lang, "open")],
      ["high", mt(lang, "high")],
      ["low", mt(lang, "low")],
      ["date", mt(lang, "date")],
      ["source", mt(lang, "source")],
    ] },
    { key: "volumes", title: mt(lang, "grpVolumes"), cols: [
      ["volume", mt(lang, "volumeCol")],
      ["volQty", mt(lang, "volQty")],
      ["avgShare", mt(lang, "avgSharePrice")],
      ["avgTrade", mt(lang, "avgTradePrice")],
      ["bigTrade", mt(lang, "bigTrade")],
      ["volShare", mt(lang, "volShare")],
    ] },
    { key: "financials", title: mt(lang, "grpFinancials"), cols: [
      ["finRevenue", mt(lang, "finRevenue")],
      ["finGross", mt(lang, "finGross")],
      ["finCash", mt(lang, "finCash")],
      ["finLiab", mt(lang, "finLiab")],
      ["finNet", mt(lang, "finNet")],
      ["finOperating", mt(lang, "finOperating")],
    ] },
    // Долг/Капитал удалён по ТЗ мультипликаторов (лист 06): 47 из 99 значений
    // не воспроизводились, единицы были смешаны. Его роль делят P/S
    // (нефинансовый сектор) и Капитал/Активы (в первую очередь банки).
    { key: "multiples", title: mt(lang, "grpMultiples"), cols: [
      ["mktCap", mt(lang, "mktCap")],
      ["pe", "P/E"],
      ["pb", "P/B"],
      ["ps", "P/S"],
      ["roe", "ROE"],
      ["roa", "ROA"],
      ["netMargin", mt(lang, "netMargin")],
      ["eqAssets", mt(lang, "equityAssets")],
    ] },
    // The ratio rows of the company page's «Коэффициенты» card, on the board —
    // the same numbers from the same indicator filings, so a reader who
    // compares two issuers does not have to open two pages to do it. Published
    // as the issuer published them (Долг/Активы in percent, the rest bare
    // coefficients), with the year each one belongs to under the figure.
    { key: "coefficients", title: mt(lang, "grpRatios"), cols: [
      ["currentRatio", mt(lang, "currentRatio")],
      ["quickRatio", mt(lang, "quickRatio")],
      ["debtAssets", mt(lang, "debtAssets")],
      ["assetTurnover", mt(lang, "assetTurnover")],
      ["roce", "ROCE"],
    ] },
  ];
  const MARKET_COLS = COL_GROUPS.flatMap((g) => g.cols);
  // Core columns are always shown — listed in the settings panel as locked rows.
  const CORE_COLS = [
    ["ticker", mt(lang, "ticker")],
    ["company", mt(lang, "company")],
    ["last", mt(lang, "last")],
  ];
  // Every sortable column by its screen label — the sort chain and the CSV header
  // both name keys the reader only ever sees as column titles.
  const SORT_LABEL_OF = Object.fromEntries([...CORE_COLS, ...MARKET_COLS]);
  // The key carries a version. A new column added to the DEFAULT set is invisible
  // to every reader who has ever opened this table, because their saved selection
  // is what loads — the week and month change columns would have shipped to
  // nobody. Bumping the key retires the old selection once, deliberately. It went
  // to _v3 in the same session as _v2: «Номинал» joined the default set an hour
  // later, and a reader who had already picked up _v2 would not have seen it.
  const [visibleCols, setVisibleCols] = useState(() => {
    try { const s = JSON.parse(localStorage.getItem("uz_market_cols_v3")); if (Array.isArray(s)) return new Set(s); } catch (e) { /* ignore */ }
    return new Set(["change", "change1w", "change1m", "nominal",
                    "open", "high", "low", "volume", "date", "source"]);
  });
  const needsFinancials = ["finRevenue", "finGross", "finCash", "finLiab", "finNet", "finOperating"]
    .some((key) => visibleCols.has(key));
  const needsRatios = ["currentRatio", "quickRatio", "debtAssets", "assetTurnover", "roce"]
    .some((key) => visibleCols.has(key));
  const needsMultiples = ["pe", "pb", "ps", "roe", "roa", "netMargin", "eqAssets"]
    .some((key) => visibleCols.has(key));
  const suppliedFinancials = Object.keys(financials || {}).length > 0;
  const secondaryEquityReady = Boolean(rows.length && !loading && type !== "bond");

  useEffect(() => {
    if (!needsFinancials || suppliedFinancials || financialsRequested.current || !secondaryEquityReady) return;
    financialsRequested.current = true;
    fetch("/api/market/financials")
      .then((r) => r.json())
      .then((d) => {
        setOnDemandFinancials(d.ok && d.financials ? d.financials : {});
      })
      .catch(() => {});
  }, [needsFinancials, suppliedFinancials, secondaryEquityReady]);

  useEffect(() => {
    if (!needsRatios || ratiosRequested.current || !secondaryEquityReady) return;
    ratiosRequested.current = true;
    fetch("/api/market/ratios")
      .then((r) => r.json())
      .then((d) => {
        setRatios(d.ok && d.ratios ? d.ratios : {});
      })
      .catch(() => {});
  }, [needsRatios, secondaryEquityReady]);

  useEffect(() => {
    if (!needsMultiples || multiplesRequested.current || !secondaryEquityReady) return;
    multiplesRequested.current = true;
    setMultiplesStatus("loading");
    fetch("/api/market/multiples")
      .then((r) => {
        if (!r.ok) throw new Error("multiples request failed");
        return r.json();
      })
      .then((d) => {
        if (!d || !d.ok) throw new Error("multiples payload unavailable");
        const byTicker = {};
        (d.items || []).forEach((it) => { byTicker[it.ticker] = it; });
        setMultiples(byTicker);
        setMultiplesStatus("ready");
      })
      .catch(() => { setMultiplesStatus("unavailable"); });
  }, [needsMultiples, secondaryEquityReady]);

  const [colsOpen, setColsOpen] = useState(false);
  const colsBtnRef = useRef(null); // the popover is portaled — it anchors off this
  const [colsSearch, setColsSearch] = useState("");
  const [openGroups, setOpenGroups] = useState(() => new Set(["overview", "volumes", "financials"]));
  const toggleGroup = (k) => setOpenGroups((prev) => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  useEffect(() => { try { localStorage.setItem("uz_market_cols_v3", JSON.stringify([...visibleCols])); } catch (e) { /* ignore */ } }, [visibleCols]);
  const toggleCol = (k) => setVisibleCols((prev) => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  // Bonds carry no equity metrics — the exchange feed gives them only price/trade
  // data (no market cap, P/E, ROE, or issuer financials). Hide the stock-only
  // columns on the bonds view instead of rendering misleading blank cells; stocks
  // and bonds are not comparable on the same metrics.
  const EQUITY_ONLY_COLS = new Set(["mktCap", "pe", "pb", "ps", "roe", "roa", "netMargin", "eqAssets", "finRevenue", "finGross", "finCash", "finLiab", "finNet", "finOperating",
    "currentRatio", "quickRatio", "debtAssets", "assetTurnover", "roce"]);

  // Drag-to-reorder columns. Ticker + company stay pinned left (identity cells);
  // everything from "last" onward is reorderable. Order is persisted per user.
  const MOVABLE_KEYS = ["last", ...MARKET_COLS.map(([k]) => k)];
  // The key carries a version alongside uz_market_cols_v3, and for the same reason:
  // a saved order keeps only the keys it knew and APPENDS the rest, so a column
  // added next to «Изм.» landed at the far right of the board for every reader who
  // had ever opened it — three screens of horizontal scroll from the column it
  // belongs beside. Bumping the key retires the old order once, deliberately.
  const [colOrder, setColOrder] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("uz_market_col_order_v2"));
      if (Array.isArray(s)) {
        const known = new Set(["last", ...MARKET_COLS.map(([k]) => k)]);
        const kept = s.filter((k) => known.has(k));
        const missing = ["last", ...MARKET_COLS.map(([k]) => k)].filter((k) => !kept.includes(k));
        return [...kept, ...missing];
      }
    } catch (e) { /* ignore */ }
    return ["last", ...MARKET_COLS.map(([k]) => k)];
  });
  useEffect(() => { try { localStorage.setItem("uz_market_col_order_v2", JSON.stringify(colOrder)); } catch (e) { /* ignore */ } }, [colOrder]);
  const [dragCol, setDragCol] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const wrapRef = useRef(null); // .market-table-wrap — for the horizontal scroll controls
  const moveCol = (from, to) => {
    if (!from || from === to) return;
    setColOrder((prev) => {
      const arr = prev.filter((k) => MOVABLE_KEYS.includes(k));
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

  // Frozen columns. A column can only be frozen at the left edge — that is what
  // freezing IS — so pinning hoists it to the front of the movable block and the
  // identity cells (ticker, company) join the frozen group, otherwise the pinned
  // column would float over the very names it is meant to be read against.
  const [pinnedCols, setPinnedCols] = useState(() => {
    try { const s = JSON.parse(localStorage.getItem("uz_market_pinned_cols")); if (Array.isArray(s)) return new Set(s); } catch (e) { /* ignore */ }
    return new Set();
  });
  useEffect(() => { try { localStorage.setItem("uz_market_pinned_cols", JSON.stringify([...pinnedCols])); } catch (e) { /* ignore */ } }, [pinnedCols]);
  const togglePin = (k) => setPinnedCols((prev) => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n; });

  // Visible movable columns in the user's chosen order ("last" is always shown).
  const shownOrder = colOrder.filter((k) =>
    (k === "last" || visibleCols.has(k)) && !(type === "bond" && EQUITY_ONLY_COLS.has(k)));
  const pinnedOrder = shownOrder.filter((k) => pinnedCols.has(k));
  const visibleOrder = [...pinnedOrder, ...shownOrder.filter((k) => !pinnedCols.has(k))];
  const colSpan = 3 + visibleOrder.length;

  // Where each frozen column comes to rest: the summed width of everything
  // frozen to its left, measured off the live header (the table lays itself out
  // by content, so no width is knowable in advance). Re-measured after every
  // render — the same trick MarketStickyHead uses, and just as cheap, because a
  // measurement that changed nothing never reaches state.
  const [pinOffsets, setPinOffsets] = useState({});
  const pinMeasureRef = useRef(() => {});
  const pinKeys = pinnedOrder.join("|");
  useEffect(() => {
    const measure = () => {
      const head = wrapRef.current && wrapRef.current.querySelector(".market-table thead tr");
      if (!head || !pinKeys) {
        setPinOffsets((prev) => (Object.keys(prev).length ? {} : prev));
        return;
      }
      const widths = Array.from(head.children).map((th) => th.getBoundingClientRect().width);
      const next = {};
      let acc = 0;
      // The header row is [ticker, company, ...visibleOrder], and the frozen
      // columns are the first of visibleOrder — so the run is contiguous.
      ["__ticker", "__company", ...pinKeys.split("|")].forEach((k, i) => {
        next[k] = Math.round(acc);
        acc += widths[i] || 0;
      });
      setPinOffsets((prev) => {
        const ks = Object.keys(next);
        if (ks.length === Object.keys(prev).length && ks.every((k) => prev[k] === next[k])) return prev;
        return next;
      });
    };
    pinMeasureRef.current = measure;
    measure();
    window.addEventListener("resize", measure);
    return () => { pinMeasureRef.current = () => {}; window.removeEventListener("resize", measure); };
  }, [pinKeys]);
  useLayoutEffect(() => { pinMeasureRef.current(); });
  // Until the widths are known the columns would all stack at left: 0 — better
  // one unfrozen frame than a frame of columns piled on each other.
  const lastPinned = pinnedOrder[pinnedOrder.length - 1];
  const pinAt = (key) => (pinKeys && pinOffsets[key] !== undefined
    ? { left: pinOffsets[key], edge: key === lastPinned }
    : null);
  const pinCls = (pin) => (pin ? ` market-col-pinned${pin.edge ? " market-col-pinned-edge" : ""}` : "");

  // Moves act inside the column's own block: a frozen column reorders among the
  // frozen ones, a loose column among the loose. Otherwise "move right" on a
  // frozen column would change nothing on screen, since freezing puts it back.
  const colGroupOf = (key) => visibleOrder.filter((k) => pinnedCols.has(k) === pinnedCols.has(key));
  const moveColBy = (key, step) => {
    const group = colGroupOf(key);
    const i = group.indexOf(key);
    if (i < 0) return;
    if (step === "start") { if (i > 0) moveCol(key, group[0]); return; }
    if (step === "end") { if (i < group.length - 1) moveCol(key, group[group.length - 1]); return; }
    const j = i + step;
    if (j >= 0 && j < group.length) moveCol(key, group[j]);
  };

  // The header toolbar: which column it belongs to, and whether it was opened
  // from the mirrored sticky bar (so it anchors to the header the reader sees).
  const [colMenu, setColMenu] = useState(null);
  const closeColMenu = React.useCallback(() => setColMenu(null), []);

  const openPanel = (ticker) => {
    setPanelTicker(ticker);
    setPanelWiki(null);
    setPanelWikiLoading(true);
    fetch(`/api/securities/${encodeURIComponent(ticker)}/info?language=${lang}`)
      .then((r) => r.json())
      .then((d) => { if (d.ok) setPanelWiki(d.wiki); })
      .catch(() => {})
      .finally(() => setPanelWikiLoading(false));
  };

  const smap = securitiesMap || {};
  // Fallback sector source for a ticker the securities catalog has not reached;
  // the heat map builds the same map from the same list.
  const companyMap = React.useMemo(() => {
    const by = {};
    (companies || []).forEach((c) => { if (c?.ticker) by[c.ticker] = c; });
    return by;
  }, [companies]);
  const fmap = suppliedFinancials ? financials : onDemandFinancials;
  // Financials are company-level, so a preferred share shares its common
  // sibling's figures (and vice versa) — mirror the logo sibling fallback
  // (TKDM <-> TKDMP) so both halves of a pair show data from one cached row.
  const finOf = (ticker) => {
    const t = String(ticker || "").toUpperCase();
    return fmap[t] || fmap[t.endsWith("P") ? t.slice(0, -1) : `${t}P`] || null;
  };
  const tmap = tradeStats || {};
  const preparedEnriched = prepareMarketRows(rows, tmap);

  // MAIN | NEGO — the exchange's own two boards. Its execution feed tags every
  // deal with a board id: G1 is the auction, T1 is a negotiated (переговорная)
  // deal struck bilaterally at an agreed price. The two are not one market and
  // must not be summed: a 2,2-млрд-бумаг T1 deal at 55 while the auction traded
  // 95,5–99,99 (HMKB, 14.08.2026) poisoned the session's turnover, low and VWAP
  // until the day statistics were split.
  //
  // MAIN is the board this page has always shown. NEGO is the same securities
  // seen through their negotiated deals: only the lines that had one, with the
  // negotiated turnover, quantity and count in the volume columns and the
  // negotiated average price derived from them. The PRICES stay the session's —
  // a negotiated price is not a quote, which is the whole reason the boards are
  // separate — and the note under the table says so.
  const negotiated = (r) => Number.isFinite(r?.nego?.value) && r.nego.value > 0;
  const asNegotiated = (r) => ({
    ...r,
    stockVolume: r.nego.value,
    stockQuantity: r.nego.qty,
    stockTradeCount: r.nego.count,
    // Cleared so «Ср. цена акции» derives from the NEGOTIATED turnover and
    // quantity (avgSharePrice) instead of serving the auction's VWAP under a
    // negotiated row. Same for the session VWAP column.
    avgPrice: undefined,
    vwap: null,
    // The date column must name the day the DEAL was struck. A negotiated deal is
    // not a session and is routinely weeks old — the ones on this market in
    // August 2026 were dated 02.07, 10.07, 07.08 and 13.08 — so showing the
    // auction's last-trade date beside a negotiated turnover would date the deal
    // to a session it had nothing to do with.
    last_trade_date: r.nego.date || r.last_trade_date,
  });
  const negotiatedCount = preparedEnriched.filter(negotiated).length;
  // How many negotiated deals the stored statistics know about ALTOGETHER. Most of
  // them are on bonds, and the bonds segment is its own section — so an empty NEGO
  // board here has to say where the deals actually are, or it reads as «this
  // market has none» when the market has four.
  const negotiatedAnywhere = Object.values(tmap).filter(
    (s) => Number.isFinite(s?.block_value) && s.block_value > 0).length;
  const preparedAllSession = segment === "nego"
    ? preparedEnriched.filter(negotiated).map(asNegotiated)
    : preparedEnriched;
  // Over a WINDOW every row is restated once, here, rather than at each of the
  // dozen places that read one. A window's «объём» is its sessions' turnover
  // added up, its «макс» is the highest price inside it, its «ср. сумма сделки»
  // is those сумы over those deals — so the columns, the summary cards, the
  // movers strip, the sort keys, the CSV and the heat map all answer for the
  // period the reader chose, and none of them has to know that a period was
  // chosen. A figure the stored sessions cannot answer comes back null and the
  // cell prints a dash: no column is filled with a session's number under a
  // heading that says a year.
  //
  // NEGO is left alone: a negotiated deal is not a session, the boards are
  // separate for that reason, and there is no windowed record of them to sum.
  const windowed = changePeriod !== "1d" && segment !== "nego";
  const orNull = (v) => (Number.isFinite(v) ? v : null);
  const asPeriod = (r) => {
    const hit = changeOver(r.ticker, changePeriod);
    const st = statsOver(r.ticker, changePeriod);
    return {
      ...r,
      changePercent: hit ? hit.pct : null,
      // Dropped, not converted: a window has no single сум figure — it spans
      // many sessions — and carrying the session's would put this morning's
      // сумы beside half a year's percent.
      changeValue: null,
      periodPct: hit ? hit.pct : null,
      stockVolume: orNull(st?.value),
      periodVolume: orNull(st?.value),
      stockQuantity: orNull(st?.qty),
      stockTradeCount: orNull(st?.trades),
      // The window's volume-weighted price. Cleared rather than left as the
      // session's, so «Ср. цена акции» can never quote one morning under a year.
      avgPrice: Number.isFinite(st?.vwap) ? st.vwap : undefined,
      vwap: orNull(st?.vwap),
      // `undefined`, not null: the session renderers fall back to the last price
      // when these are exactly null, and a window with no stored open must show
      // a dash rather than today's quote.
      openPrice: Number.isFinite(st?.open) ? st.open : undefined,
      highPrice: Number.isFinite(st?.high) ? st.high : undefined,
      lowPrice: Number.isFinite(st?.low) ? st.low : undefined,
      ts: st && Number.isFinite(st.largest_value)
        ? { ...(r.ts || {}), largest_value: st.largest_value,
            largest_qty: orNull(st.largest_qty),
            largest_pct_value: orNull(st.largest_pct) }
        : (r.ts ? { ...r.ts, largest_value: null, largest_qty: null,
                    largest_pct_value: null } : r.ts),
      periodFrom: st?.from || hit?.from || null,
      periodTo: st?.to || null,
      periodSessions: orNull(st?.sessions),
      periodApprox: st?.approx === true,
      // How many of the window's sessions could say how many deals they held.
      // Absent when all of them could; a number here means the deal count and
      // the largest deal are floors over that many sessions, not the whole.
      periodDetailSessions: orNull(st?.detail_sessions),
    };
  };
  const preparedAll = windowed ? preparedAllSession.map(asPeriod) : preparedAllSession;
  // "preferred" is a client-side subset of stocks (the feed was fetched as
  // type=stock); narrow to preferred shares so the table, sectors and heatmap
  // all reflect the filter.
  const isPreferredSec = (r) =>
    smap[r.ticker]?.is_preferred === true ||
    smap[r.ticker]?.share_type === "preferred" ||
    r.share_type === "preferred";
  const byClass =
    type === "preferred" ? preparedAll.filter(isPreferredSec)
    : type === "ordinary" ? preparedAll.filter((r) => !isPreferredSec(r))
    : preparedAll;
  // ТЗ §4: activity is a fact about trading, taken from /api/instruments, not a
  // flag on the row — the registry's own flag disagreed with the tape.
  const isDormant = (r) => {
    const item = instruments[String(r.ticker || "").toUpperCase()];
    return item ? item.is_active === false : r.inactive === true;
  };
  const dormantCount = byClass.filter(isDormant).length;
  const prepared = byClass.filter((r) => isDormant(r) === inactiveOnly);
  // The MAP never shows a dormant listing. A treemap is a picture of movement —
  // every tile's area is the absolute change over the selected period — and a
  // security without a measured move can only be a tiny neutral placeholder that
  // says «—». Eleven of those told the reader nothing the «неактивные: 10» line
  // on the capitalisation card does not already say, in words. Computed from the
  // rows rather than from `inactiveOnly` on purpose: switching the table's filter
  // on and then switching to the map must not carry the eleven across.
  // The TABLE keeps the filter — there a dormant listing has a last close, a
  // date and an issuer to read, which is a row worth having.
  const mapRows = byClass.filter((r) => !isDormant(r));
  // The map answers for the SELECTED period, like the «Изм.» column and the
  // movers strip beside it — one question on the screen, one answer. It needs no
  // restatement of its own: `mapRows` comes off rows already restated for the
  // period, so a tile's colour and its AREA both describe the window the reader
  // chose, from the same stored sessions the column reads.
  const periodMapRows = mapRows;
  const search = String(query || "").trim().toLowerCase();

  // Gather sectors present in current data. Same resolver as the heat map, so a
  // chip here and a block there always hold the same tickers — and a row the
  // securities catalog has not reached lands under Прочее instead of answering
  // to no chip at all.
  const rowSector = (r) => sectorOf(r.ticker, smap, companyMap);
  // Display order, not alphabetical-by-english-key: sorted on the key, the list
  // read «Добыча, Логистика, Прочее, Производство…» — an order that exists only
  // in a language the reader is not being shown, with «Прочее» in the middle of
  // it. orderSectors is the same sequence the heat map's blocks follow.
  const presentSectors = orderSectors([...new Set(prepared.map(rowSector))]);
  const sectorWord = lang === "en" ? "Sector" : lang === "uz" ? "Soha" : "Отрасль";
  // A sector the current segment holds none of cannot filter it. Облигации are
  // «Прочее» to a security and nothing else, so a «Финансы» picked under Акции
  // would empty that table — and, since a chip row with one option is not drawn
  // (see below), leave no control to undo it. The choice is only suspended, not
  // thrown away: switching back to Акции applies it again.
  const activeSector = presentSectors.includes(marketSector) ? marketSector : null;
  // The map draws exactly what the sector control says, like the table beside
  // it. `periodMapRows` is declared before `activeSector` (it is built off the
  // period-restated rows), so the filter is applied here rather than there.
  const sectorMapRows = activeSector
    ? periodMapRows.filter((r) => rowSector(r) === activeSector)
    : periodMapRows;

  // §3.8 multipliers are calculated and validated only by the server.  A
  // client-side fallback would divide a single share class by issuer-level
  // earnings and can therefore produce a false P/E or P/B for preferred shares.
  const ratioOf = (ticker) => ratios[ticker] || ratios[String(ticker || "").toUpperCase()] || null;
  const mktCapOf = (r) => (Number.isFinite(r.marketCap) ? r.marketCap : null);
  const multiplesOf = (r) => multiples[String(r.ticker || "").toUpperCase()] || null;
  const unavailableMultiple = () => ({
    value: null,
    status: multiplesStatus === "loading" ? "loading" : "unavailable",
  });
  const multipleOf = (r, field) => multiplesOf(r)?.[field] || unavailableMultiple();
  const valuationOf = (r) => {
    const server = multiplesOf(r);
    return {
      pe: server?.pe || unavailableMultiple(),
      pb: server?.pb || unavailableMultiple(),
      server: Boolean(server),
    };
  };
  // An out-of-range multiple sorts (and exports) as absent: a P/E column
  // ordered by value must not crown a 2 816× that the cell marks as anomalous.
  const peOf = (r) => {
    const m = valuationOf(r).pe;
    return m?.status === "out_of_range" ? null : m?.value ?? null;
  };

  // A flow figure scaled to twelve months, for SORTING only (ТЗ §7). Returns
  // null rather than a raw value when the period is unknown: ordering by a
  // number whose span nobody knows is the defect, not the fix.
  const annualisedFin = (r, field) => {
    const fin = finOf(r.ticker);
    const value = fin?.[field];
    if (!Number.isFinite(value)) return null;
    const months = Number.isFinite(fin?.period_months)
      ? fin.period_months
      : (fin?.quarter > 0 ? fin.quarter * 3 : (fin?.year ? 12 : null));
    if (!months || months <= 0) return null;
    return (value * 12) / months;
  };

  // ТЗ §8: a multiple the server withheld says WHY. «убыток» is a fact about the
  // issuer, not missing data; a range status means the figure exists and is not
  // suitable for direct comparison.
  const statusText = (status) => multipleStatusText(status, lang);
  const multipleCell = (row, metric, digits, suffix = "×") => {
    // Keep an outlier visible for audit, but label it so it is never mistaken
    // for an ordinary comparable multiple.
    if (metric?.value != null && metric.status === "out_of_range") {
      const help = outlierTitle(metric, digits, suffix, lang);
      return (
        <td className="num">
          <strong>{formatRatio(metric.value, digits, lang)}{suffix}</strong>
          <span className="fin-cell-period metric-warning metric-warning--out_of_range">
            {outlierLabel(lang)} <RangeHelpIcon title={help} />
          </span>
        </td>
      );
    }
    if (metric?.value != null) {
      const flags = [];
      if (metric.estimate) flags.push(mt(lang, "estimateFlag"));
      const period = metric.base_period || metric.financial_period || null;
      const title = [
        period,
        metric.denominator_period && metric.denominator_period !== period
          ? `${lang === "ru" ? "средняя база" : lang === "uz" ? "o‘rtacha baza" : "average base"}: ${metric.denominator_period}`
          : null,
        metric.note,
        metric.allowed ? `∉ [${metric.allowed.join("; ")}]` : null,
      ].filter(Boolean).join(" · ") || undefined;
      const sub = [period, ...flags].filter(Boolean).join(" · ");
      return (
        <td className="num" title={title}>
          <strong>{formatRatio(metric.value, digits, lang)}{suffix}</strong>
          {sub && <span className="fin-cell-period">{sub}</span>}
        </td>
      );
    }
    if (metric?.computed != null && metric.status === "loss_making") {
      return (
        <td className="num">
          <span className="cell-status" title={lossTitle(metric, digits, suffix, lang)}>{lossLabel(lang)}</span>
        </td>
      );
    }
    if (metric?.computed != null && metric.status === "unverified") {
      const period = metric?.base_period || null;
      return (
        <td className="num" title={period || undefined}>
          <strong>{formatRatio(metric.computed, digits, lang)}{suffix}</strong>
          {period && <span className="fin-cell-period">{period}</span>}
        </td>
      );
    }
    const issuerCapGap = incompleteIssuerCapAvailability(
      metric, multiplesOf(row)?.market_cap_issuer, row?.ticker, lang,
    );
    const label = issuerCapGap?.label || statusText(metric?.status);
    if (!label) return <td className="num">{noSecLabel(row)}</td>;
    if (metric?.status === "not_applicable") {
      return (
        <td className="num">
          <span className="cell-status">{label} <RangeHelpIcon title={notApplicableTitle(lang)} /></span>
        </td>
      );
    }
    const reasons = issuerCapGap?.title || (metric?.reasons || []).join("; ")
      || (metric?.computed != null
        ? `${formatRatio(metric.computed, digits, lang)}${suffix} ∉ [${metric.allowed?.join(", ")}]`
        : metric?.note || "");
    const period = metric?.base_period ? ` · ${metric.base_period}` : "";
    return <td className="num"><span className="cell-status" title={(reasons + period).trim() || undefined}>{label}</span></td>;
  };
  // Issuers openinfo records as having no tradable securities at all
  // (is_listing=false, empty RFB/OTC share registries — e.g. MNGM):
  // market-value cells state that fact instead of an ambiguous dash.
  const noSecLabel = (r) => (r.isin ? "—"
    : lang === "ru" ? "нет бумаг" : lang === "uz" ? "qog'oz yo'q" : "no securities");
  // "Not applicable": the figure is undefined for this issuer's reporting
  // form (bank/insurer/fund statements) rather than missing.
  const naLabel = () => (lang === "ru" ? "н/п" : lang === "uz" ? "t/e" : "n/a");
  // Trade date of the row's day statistics (YYYYMMDD → YYYY-MM-DD).
  const tsDate = (r) => {
    const d = String(r.ts?.trade_date || "");
    return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : null;
  };
  // Per-trade stat cells for securities with no execution in the archive at
  // all (verified 10-year lookback): state "no trades" — the same fact the
  // trade-date column shows — rather than an ambiguous dash.
  const neverTraded = (r) => (!r.last_trade_date && !r.ts ? mt(lang, "noTrade") : "—");
  const pbOf = (r) => {
    const m = valuationOf(r).pb;
    return m?.status === "out_of_range" ? null : m?.value ?? null;
  };

  // One financials cell, with the reporting period it belongs to underneath it.
  // The period is not decoration: these figures mix completed annuals with
  // cumulative quarters across issuers, and a field whose only source is another
  // filing carries that filing's period (marked, so it reads as a footnote rather
  // than as this row's number).
  const finCell = (row, field, { naWhenTopLine = false } = {}) => {
    const f = finOf(row.ticker);
    const value = f?.[field];
    if (value == null && naWhenTopLine && Number.isFinite(f?.revenue)) {
      return <td className="num">{naLabel()}</td>;
    }
    if (!Number.isFinite(value)) return <td className="num">—</td>;
    const period = finFieldPeriod(f, field);
    const borrowed = Boolean((f?.field_periods || {})[field]);
    const coverage = finPeriodCoverage(period, lang);
    // How much trading the figure covers, printed rather than only hovered: NSBU
    // quarters are cumulative, so this column routinely sets one issuer's six
    // months beside another's three and a third's completed year. Balance lines
    // get no suffix — they are a position on the closing date, not an accumulation.
    const length = finFieldCoverage(period, field, lang);
    return (
      <td className="num">
        <strong>{finValue(value, lang)}</strong>
        {period && (
          <span className={`fin-cell-period${borrowed ? " borrowed" : ""}`}
                title={borrowed
                  ? `${period} · ${coverage} — ${lang === "ru" ? "период отличается от периода строки"
                      : lang === "uz" ? "davr qator davridan farq qiladi"
                      : "a different period than the row"}`
                  : `${period} · ${coverage}`}>
            {period}{length ? ` · ${length}` : ""}{borrowed ? " *" : ""}
          </span>
        )}
      </td>
    );
  };

  // One published coefficient from the issuer's own indicator filing — the same
  // rows the company page's «Коэффициенты» card carries.
  //
  // UNITS ARE THE SOURCE'S. Долг/Активы is published as a percent; текущая и
  // быстрая ликвидность, оборачиваемость активов and ROCE are published as bare
  // coefficients (ROCE 0,07 is seven percent of capital employed). Of these,
  // only debt_ratio and total_asset_turnover reproduce from the sums this
  // platform holds — 401 of 401 issuer-years each; the others are the source's
  // arithmetic on a base it does not name, so they are shown exactly as filed
  // and never rescaled into a percent we would be inventing.
  //
  // The year sits under the figure and is per FIELD, not per issuer: a company
  // can publish liquidity for 2023 and ROE for 2025, and one label over both
  // would claim something the store does not say.
  // The two liquidity ratios are defined on a balance that splits current from
  // non-current assets, and the bank form does not: a bank's balance is ordered by
  // instrument, not by maturity, and «текущая ликвидность» has no meaning on it.
  // The remaining 28 empty cells on this board are exactly the thirteen banks and
  // their preferred lines — so the cell says «н/п», the way the gross-profit and
  // operating-income columns already do for the same forms, rather than leaving a
  // dash a reader would read as our gap.
  const LIQUIDITY_FIELDS = new Set(["current_ratio", "quick_ratio"]);
  const ratioCell = (row, field, { digits = 2, suffix = "" } = {}) => {
    const r = ratioOf(row.ticker);
    const value = r?.[field];
    if (!Number.isFinite(value)) {
      const form = finOf(row.ticker)?.org_type;
      if (LIQUIDITY_FIELDS.has(field) && form === "bank") {
        return (
          <td className="num">
            <span className="cell-status" title={lang === "en"
              ? "The bank balance is not split into current and non-current assets — no liquidity ratio is defined on it"
              : lang === "uz"
                ? "Bank balansi joriy va uzoq muddatli aktivlarga bo'linmaydi — likvidlik koeffitsiyenti aniqlanmaydi"
                : "Банковский баланс не делится на текущие и долгосрочные активы — коэффициент ликвидности на нём не определён"}>
              {lang === "en" ? "n/a" : "н/п"}
            </span>
          </td>
        );
      }
      return <td className="num">—</td>;
    }
    const period = (r.periods || {})[field] || null;
    return (
      <td className="num">
        {formatRatio(value, digits, lang)}{suffix}
        {period && <span className="fin-cell-period">{period}</span>}
      </td>
    );
  };

  // Value read for each sortable column. ticker/company/date are strings, the rest numeric.
  const sortAccessors = {
    ticker: (r) => r.ticker || "",
    company: (r) => r.name || "",
    last: (r) => marketDisplayPrice(r),
    // The selected period's change, so the order follows what the column shows.
    change: (r) => (changePeriod === "1d"
      ? r.changePercent
      : (changeOver(r.ticker, changePeriod)?.pct ?? null)),
    change1w: (r) => changeOver(r.ticker, "1w")?.pct ?? null,
    change1m: (r) => changeOver(r.ticker, "1m")?.pct ?? null,
    nominal: (r) => parOf(r),
    priceToPar: (r) => priceToPar(r),
    open: (r) => r.openPrice,
    high: (r) => r.highPrice,
    low: (r) => r.lowPrice,
    volume: (r) => r.stockVolume,
    volQty: (r) => r.stockQuantity,
    avgShare: (r) => (Number.isFinite(r.avgPrice) ? r.avgPrice : avgSharePrice(r)),
    avgTrade: (r) => avgTradeValue(r),
    bigTrade: (r) => r.ts?.largest_value,
    volShare: (r) => r.stockVolume,
    // ТЗ §7: a column that mixes reporting periods may not be ordered by its
    // raw values. The cached rows span twelve different (year, months)
    // combinations, so a full year always outranked a peer's four quarters for
    // no reason the reader could see. The CELL keeps its own period and label;
    // only the SORT runs on the twelve-month normalisation. Balance-sheet lines
    // are a position on a date and are never scaled.
    finRevenue: (r) => annualisedFin(r, "revenue"),
    finGross: (r) => annualisedFin(r, "gross_profit"),
    finCash: (r) => finOf(r.ticker)?.cash,
    finLiab: (r) => finOf(r.ticker)?.total_liabilities,
    finNet: (r) => annualisedFin(r, "net_income"),
    finOperating: (r) => annualisedFin(r, "operating_income"),
    mktCap: (r) => mktCapOf(r),
    pe: (r) => peOf(r),
    pb: (r) => pbOf(r),
    // Sort on what is RENDERED — the server envelope — not on the raw
    // indicator feed. Sorting on the feed while rendering the envelope put a
    // withheld value's ghost in the ordering (ТЗ мультипликаторов, лист 05:
    // «сортировка по марже выдаёт бессмысленный порядок»).
    ps: (r) => multipleOf(r, "ps").value,
    roe: (r) => multipleOf(r, "roe").value,
    roa: (r) => multipleOf(r, "roa").value,
    netMargin: (r) => multipleOf(r, "net_margin").value,
    eqAssets: (r) => multipleOf(r, "equity_assets").value,
    // The published coefficients sort on what they show. Unlike the financials
    // columns there is nothing to annualise: a liquidity ratio is a position on
    // a date, and a turnover is already a full year's revenue over assets.
    currentRatio: (r) => ratioOf(r.ticker)?.current_ratio,
    quickRatio: (r) => ratioOf(r.ticker)?.quick_ratio,
    debtAssets: (r) => ratioOf(r.ticker)?.debt_ratio,
    assetTurnover: (r) => ratioOf(r.ticker)?.total_asset_turnover,
    roce: (r) => ratioOf(r.ticker)?.return_to_capital_employed,
    // Normalized to YYYYMMDD so the comparison is chronological. The raw field is
    // a mix of DD.MM.YYYY (live feed) and YYYY-MM-DD (listings registry), and
    // comparing those as strings ordered by the leading digits — "31.01.2026"
    // sorted above "05.02.2026", so "latest first" broke at every month boundary.
    date: (r) => marketRowDay(r) || "",
    source: (r) => r.url || "",
  };

  const visibleRows = prepared
    .filter((row) => {
      if (favOnly && !hasFav(row.ticker)) return false;
      if (activeSector && rowSector(row) !== activeSector) return false;
      if (!search) return true;
      return `${row.ticker || ""} ${row.name || ""} ${row.isin || ""}`.toLowerCase().includes(search);
    })
    .sort((a, b) => {
      if (!sortKeys.length) {
        // Same normalization as the `date` accessor — the default "most recently
        // traded first" order was wrong across month boundaries for exactly the
        // same reason (mixed DD.MM.YYYY / YYYY-MM-DD compared lexicographically).
        const aDate = marketRowDay(a) || "";
        const bDate = marketRowDay(b) || "";
        if (aDate !== bDate) return bDate.localeCompare(aDate);
        return Math.abs(b.changePercent ?? -Infinity) - Math.abs(a.changePercent ?? -Infinity);
      }
      // Each key decides only the rows the keys before it tied on.
      for (const { key, dir } of sortKeys) {
        const acc = sortAccessors[key];
        if (!acc) continue;
        const c = compareSortValues(acc(a), acc(b), dir);
        if (c) return c;
      }
      return 0;
    });
  // The summary cards describe the BOARD, not the table's filter. Fed the
  // dormant subset they answered «сделки сегодня: 11» about eleven securities
  // that have not traded in three months, and named a «лидер роста» at 0 %.
  // Favourites, search and «Неактивные» therefore still never reach them.
  //
  // The sector chip is the one exception (customer, 2026-08-18): it picks WHICH
  // market is being read, not which rows of one are hidden, and a «Финансы»
  // board whose cards went on counting the whole exchange's advancers and
  // capitalisation was answering a question nobody had asked. The pool is the
  // one the movers panels have used since 2026-08-12, so the cards and the
  // strip under them can never describe different sets of securities.
  //
  // Only while the chip row is on screen, though. The map has no sector control
  // (its tiles are the whole board) and a card silently answering for one sector
  // beside a picture of all of them would be unreadable — with nothing to click
  // to find out why.
  // The cards state what the reader is looking at — and since the sector control
  // now stands over the map as well, «Финансы» there has to restate them for the
  // same eight issuers it restates under the table.
  const cardSector = activeSector;
  // Two readings, deliberately: `stats` stays the whole board because the CSV,
  // the session date and the «доля объёма» column all make a claim ABOUT THE
  // MARKET — a row's share of the day's turnover is not a share of its sector's
  // — while `cardStats` is what the four cards and the movers strip report.
  const stats = buildMarketStats(byClass.filter((r) => !isDormant(r)), { windowed });
  const cardStats = cardSector
    ? buildMarketStats(byClass.filter((r) => !isDormant(r) && rowSector(r) === cardSector),
                       { windowed })
    : stats;
  const moverStats = cardStats;
  // Капитализация is a STOCK, not a flow: whatever period is on screen, the
  // market is worth what it is worth today, and restating the card's value to
  // the window's first session would put a year-old figure under a heading that
  // says «Капитализация». What the period CAN say is how far that figure moved
  // over it — so the card keeps today's sum and gains the period's change.
  //
  // Measured on the same rows the card sums, from the same window percents the
  // «Изм.» column shows: each line's capitalisation is walked back through its
  // own change to what it was at the window's start, and the two sums compared.
  // Share counts are held constant — an issue inside the window would move the
  // sum without the price moving — which is why this is stated as the change in
  // the market's PRICE, and why a line whose window has no percent sits out of
  // both sums rather than entering one of them.
  const capPeriodChange = (() => {
    if (!windowed) return null;
    const pool = byClass.filter(
      (r) => !isDormant(r) && (!cardSector || rowSector(r) === cardSector));
    let now = 0;
    let before = 0;
    pool.forEach((r) => {
      const cap = mktCapOf(r);
      const pct = r.changePercent;
      if (!(cap > 0) || !Number.isFinite(pct) || pct <= -100) return;
      now += cap;
      before += cap / (1 + pct / 100);
    });
    return before > 0 ? (now - before) / before * 100 : null;
  })();
  // Dormant listings inside the selected sector — what the capitalisation card
  // below leaves out of its own sum, counted on the same basis the server's
  // whole-market answer counts them.
  const sectorDormant = cardSector
    ? byClass.filter((r) => isDormant(r) && rowSector(r) === cardSector).length
    : 0;
  // Over a WINDOW all three panels are a different list, and they are not drawn
  // from the latest session's rows: a security that has not traded today still
  // moved over the month, and leaving it out would rank the month by who
  // happened to trade this morning (buildMarketStats, `windowed`).
  //
  // Ликвидность followed the same rule until 2026-08-18 only because the sum did
  // not exist — the strip could show the session's turnover or nothing. Every
  // settled session's total_value has been stored per security since 2025-08-13,
  // so the month's turnover is now the month's sessions added up, served beside
  // the change over the same window (/api/market/changes → `turnover`). It is a
  // sum of what actually traded, and each line carries the session count and the
  // first session inside the window in its tooltip, because on this market «за
  // полгода» is routinely four sessions and a reader must be able to see that.
  // Nothing to re-derive: `byClass` already IS the period's rows, so the three
  // panels come out of the same buildMarketStats the cards use and can never
  // describe a different set of securities from the table under them.
  const periodMovers = moverStats;

  // §3.8: export the table the user is looking at as OUR report, client-side.
  //
  // It used to emit a bare 20-column board dump — English headers on a Russian page, UZSE's
  // own name strings, full-precision floats ("43.84615384615385") and a comma delimiter —
  // which read as somebody else's export, because that is what an exchange board is. What
  // separates our page from uzse.uz is the reporting beside the quote, and none of it was in
  // the file: revenue, gross and operating profit, net income, cash, liabilities, and the
  // period each of those figures actually covers. Those are here now, next to the multiples
  // computed from them, under a header block that says what the file is and where each part
  // came from.
  //
  // Delimiter and decimal mark follow the UI language for the same reason. Excel in a ru/uz
  // locale splits on ';' and reads ',' as the decimal mark, so a comma-separated file with
  // dotted decimals opens as a single column of text — the most literal way to look like a
  // foreign dump.
  const exportCsv = () => {
    const ruLocale = lang !== "en";
    const sep = ruLocale ? ";" : ",";
    const cell = (v) => {
      if (v === null || v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v))) return "";
      let s = typeof v === "number"
        ? (ruLocale ? String(v).replace(".", ",") : String(v))
        : String(v);
      // A quoted field is needed for the delimiter, quotes and newlines — and, once decimals
      // are commas, for every number too when the delimiter is a comma.
      return new RegExp(`["\\n\\r${sep === ";" ? ";" : ","}]`).test(s)
        ? `"${s.replace(/"/g, '""')}"` : s;
    };
    // Rounded the way the screen rounds: a report states a figure, it does not dump a float.
    const round = (v, digits) => (Number.isFinite(v) ? Number(v.toFixed(digits)) : "");
    const money = (v) => (Number.isFinite(v) ? Math.round(v) : "");

    const filters = [
      mt(lang, type === "stock" ? "stocks" : type === "bond" ? "bonds"
        : type === "preferred" ? "preferredStocks" : type === "ordinary" ? "ordinaryStocks" : "all"),
      // The file states the filters that ACTUALLY shaped it — a suspended sector
      // named in the header would describe a selection the rows never went through.
      activeSector || "",
      favOnly ? mt(lang, "csvFav") : "",
      // The export states its filters, and «только неактивные» changes what the
      // whole file IS — a sheet of eleven dormant listings that looks like the
      // board would be read as the board.
      inactiveOnly ? (lang === "en" ? "inactive only" : lang === "uz" ? "faqat faol emas" : "только неактивные") : "",
      String(query || "").trim() ? `${mt(lang, "csvSearch")}: ${String(query).trim()}` : "",
    ].filter(Boolean).join(" · ");
    // `last_trade_date` arrives as DD.MM.YYYY from the live feed and YYYY-MM-DD from the
    // listings registry. Normalise both through marketRowDay so one column holds one format.
    const day = (d) => (/^\d{8}$/.test(d || "") ? `${d.slice(6)}.${d.slice(4, 6)}.${d.slice(0, 4)}` : "");
    const session = day(stats.boardDay);

    // Two columns, so the block reads as label/value in a spreadsheet rather than as text
    // spilled across the sheet. A blank row separates it from the table proper.
    const lines = [
      [mt(lang, "csvTitle"), ""].map(cell).join(sep),
      // Stamped DD.MM.YYYY like every other date in the file. Deliberately not the browser
      // locale's own format: on en-US that prints 7/29/2026 next to a 29.07.2026 trade-date
      // column, and one report should not carry two date conventions.
      [mt(lang, "csvGenerated"), (() => {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      })()].map(cell).join(sep),
      // Over a window there is no ONE session to stamp — `stats.boardDay` is
      // null by design — and a «Торговая сессия» row with nothing after it reads
      // as a missing value rather than as a period export. The period line below
      // takes its place.
      ...(session ? [[mt(lang, "csvSession"), session].map(cell).join(sep)] : []),
      // Which PERIOD the volume columns describe. Without it the file is a set
      // of numbers that look like a session and are a year — the one thing a
      // spreadsheet, unlike the screen, carries no control to reveal.
      ...(windowed
        ? [[mt(lang, "csvPeriod"), changePeriodLabel(changePeriod, lang, "label")].map(cell).join(sep),
           [mt(lang, "csvPeriodNote"), ""].map(cell).join(sep)]
        : []),
      [mt(lang, "csvFilter"), filters].map(cell).join(sep),
      // The file is the table as it stands on screen, so the row ORDER is part of
      // what is being exported — state it rather than let the reader guess.
      [mt(lang, "csvSort"), sortKeys.length
        ? sortKeys.map(({ key, dir }) => `${SORT_LABEL_OF[key] || key} ${dir === "asc" ? "↑" : "↓"}`).join(" → ")
        : mt(lang, "csvSortDefault")].map(cell).join(sep),
      [mt(lang, "csvRows"), visibleRows.length].map(cell).join(sep),
      [mt(lang, "csvMoneyNote"), ""].map(cell).join(sep),
      [mt(lang, "csvSources"), ""].map(cell).join(sep),
      "",
    ];

    const header = [
      mt(lang, "ticker"), mt(lang, "company"), mt(lang, "isin"), mt(lang, "sector"),
      mt(lang, "shareType"), mt(lang, "date"),
      mt(lang, "last"), `${mt(lang, "change")}, %`,
      // Each window change names the session it was measured from — the same
      // statement the cell's tooltip makes, because a percent without its base
      // date is not reproducible from a spreadsheet.
      `${mt(lang, "change")} 1${lang === "en" ? "W" : lang === "uz" ? "H" : "Н"}, %`,
      lang === "en" ? "1W base" : lang === "uz" ? "1H bazasi" : "База 1Н",
      `${mt(lang, "change")} 1${lang === "en" ? "M" : lang === "uz" ? "O" : "М"}, %`,
      lang === "en" ? "1M base" : lang === "uz" ? "1O bazasi" : "База 1М",
      mt(lang, "open"), mt(lang, "high"), mt(lang, "low"),
      mt(lang, "volumeCol"), mt(lang, "csvTrades"), mt(lang, "volQty"),
      mt(lang, "avgSharePrice"), "VWAP", mt(lang, "bigTrade"), mt(lang, "volShare"),
      mt(lang, "finPeriod"), mt(lang, "finCoverage"),
      mt(lang, "finRevenue"), mt(lang, "finGross"), mt(lang, "finOperating"),
      mt(lang, "finNet"), mt(lang, "finCash"), mt(lang, "finLiab"),
      mt(lang, "mktCap"), mt(lang, "pe"), mt(lang, "pb"), "P/S",
      mt(lang, "roe"), mt(lang, "roa"),
      `${mt(lang, "netMargin")}, % (${mt(lang, "netMarginBankNote")})`,
      `${mt(lang, "equityAssets")}, %`,
    ];
    lines.push(header.map(cell).join(sep));

    for (const row of visibleRows) {
      const sec = smap[row.ticker] || {};
      const fin = finOf(row.ticker) || null;
      const period = finRowPeriod(fin);
      const share = (stats.boardDay && marketRowDay(row) !== stats.boardDay) ? 0
        : Number.isFinite(row.stockVolume) && stats.totalVolume > 0
          ? (row.stockVolume / stats.totalVolume) * 100 : "";
      const isPreferred = sec.is_preferred || row.share_type === "preferred";
      lines.push([
        row.ticker,
        row.name,
        row.isin,
        sec.sector || "",
        (row.type === "bond" || sec.type === "bond") ? mt(lang, "bondOne")
          : isPreferred ? mt(lang, "preferred") : mt(lang, "ordinary"),
        day(marketRowDay(row)),
        round(marketDisplayPrice(row), 2), round(row.changePercent, 2),
        round(changeOver(row.ticker, "1w")?.pct, 2), day(changeOver(row.ticker, "1w")?.from),
        round(changeOver(row.ticker, "1m")?.pct, 2), day(changeOver(row.ticker, "1m")?.from),
        round(row.openPrice, 2), round(row.highPrice, 2), round(row.lowPrice, 2),
        money(row.stockVolume), row.stockTradeCount, row.stockQuantity,
        round(Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row), 2),
        round(row.vwap, 2), money(row.ts?.largest_value), round(share, 2),
        period || "", period ? finPeriodCoverage(period, lang) : "",
        money(fin?.revenue), money(fin?.gross_profit), money(fin?.operating_income),
        money(fin?.net_income), money(fin?.cash), money(fin?.total_liabilities),
        money(mktCapOf(row)), round(peOf(row), 2), round(pbOf(row), 2),
        round(multipleOf(row, "ps").value, 2),
        round(multipleOf(row, "roe").value, 2),
        round(multipleOf(row, "roa").value, 2),
        round(multipleOf(row, "net_margin").value, 2),
        round(multipleOf(row, "equity_assets").value, 2),
      ].map(cell).join(sep));
    }

    // CRLF and the BOM: what Excel expects of a CSV on Windows, which is where these open.
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `uzse_${type || "all"}_${windowed ? changePeriod : ((stats.boardDay || "").slice(0, 8) || "latest")}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const formatLeader = (row) => row ? `${row.ticker} ${formatRatio(row.changePercent, 2, lang)}%` : "—";

  const sortTh = (key, label, opts = {}) => {
    const { movable = false, num = false, pinKey = null } = opts;
    const pin = pinKey ? pinAt(pinKey) : null;
    const rank = sortRankOf(key);
    const dir = sortDirOf(key);
    const chained = sortKeys.length > 1;
    const cls = [
      "market-th-sortable",
      num ? "market-th-num" : "",
      rank >= 0 ? "sorted" : "",
      movable ? "market-th-movable" : "",
      movable && dragCol === key ? "dragging" : "",
      movable && dragOverCol === key && dragCol && dragCol !== key ? "drag-over" : "",
      colMenu && colMenu.key === key ? "menu-open" : "",
      pin ? `market-col-pinned${pin.edge ? " market-col-pinned-edge" : ""}` : "",
    ].filter(Boolean).join(" ");
    const menuLabel = lang === "en" ? "Column controls"
      : lang === "uz" ? "Ustun boshqaruvi" : "Управление столбцом";
    // ⌘ on a Mac, Ctrl elsewhere — Shift works everywhere and is the one we teach.
    const isAdditive = (e) => e.shiftKey || e.metaKey || e.ctrlKey;
    const hint = lang === "en" ? "Shift+click (or long-press) — add as a secondary sort"
      : lang === "uz" ? "Shift+bosish (yoki uzoq bosish) — qoʻshimcha saralash kaliti"
      : "Shift+клик (или долгое нажатие) — добавить второй ключ сортировки";
    const dragHint = lang === "en" ? "Drag to reorder · click to sort"
      : lang === "uz" ? "Tartibni o'zgartirish uchun torting · saralash uchun bosing"
      : "Перетащите, чтобы переставить · нажмите для сортировки";
    return (
    <th
      key={key}
      className={cls}
      data-sort-key={key}
      onClick={(e) => {
        // The long-press already sorted; the tap that ends it must not sort again.
        if (longPress.current.fired) { longPress.current.fired = false; return; }
        onSort(key, isAdditive(e));
      }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSort(key, isAdditive(e)); } }}
      onTouchStart={() => startLongPress(key)}
      onTouchMove={cancelLongPress}
      onTouchEnd={cancelLongPress}
      onTouchCancel={cancelLongPress}
      onContextMenu={(e) => { if (longPress.current.fired) e.preventDefault(); }}
      role="button"
      tabIndex={0}
      /* ARIA asks for aria-sort on ONE header at a time, so the chain's later keys
         announce their rank through the accessible name instead. */
      aria-sort={rank === 0 ? (dir === "asc" ? "ascending" : "descending") : "none"}
      aria-label={rank > 0
        ? `${label} — ${lang === "en" ? "sort" : lang === "uz" ? "saralash" : "сортировка"} ${rank + 1}, ${
            dir === "asc" ? (lang === "en" ? "ascending" : lang === "uz" ? "oʻsish" : "по возрастанию")
              : (lang === "en" ? "descending" : lang === "uz" ? "kamayish" : "по убыванию")}`
        : undefined}
      draggable={movable}
      onDragStart={movable ? (e) => { setDragCol(key); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", key); } catch (_) { /* ignore */ } } : undefined}
      onDragOver={movable ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (dragOverCol !== key) setDragOverCol(key); } : undefined}
      onDragEnter={movable ? (e) => e.preventDefault() : undefined}
      onDragLeave={movable ? () => { setDragOverCol((c) => (c === key ? null : c)); } : undefined}
      onDrop={movable ? (e) => { e.preventDefault(); let from = dragCol; if (!from) { try { from = e.dataTransfer.getData("text/plain"); } catch (_) { from = null; } } moveCol(from, key); setDragCol(null); setDragOverCol(null); } : undefined}
      onDragEnd={movable ? () => { setDragCol(null); setDragOverCol(null); } : undefined}
      title={movable ? `${dragHint} · ${hint}` : hint}
      style={pin ? { left: pin.left } : undefined}
    >
      <span className="market-th-inner">
        {movable && <span className="market-th-grip" aria-hidden="true">⋮⋮</span>}
        <span>{label}</span>
        {/* Renders nothing for a column that is not an economic term (компания,
            UZSE) — the marker promises an explanation and must not appear
            without one. */}
        <TermInfo termId={key} lang={lang} label={label} />
        <span className="market-sort-caret">{rank >= 0 ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
        {/* The rank only earns its space once the order actually has more than one
            key — a lone "1" beside a single sorted column says nothing. */}
        {chained && rank >= 0 && <span className="market-sort-rank" aria-hidden="true">{rank + 1}</span>}
        {/* The column's own controls. Only the movable columns get it: ticker and
            company cannot be moved, hidden or unfrozen, so a toolbar there would
            be six dead buttons. The header's own click still sorts — this button
            swallows every gesture that would otherwise reach it, including the
            long-press and the drag. */}
        {movable && (
          <button
            type="button"
            className={`market-th-menu-btn${colMenu && colMenu.key === key ? " is-open" : ""}`}
            draggable={false}
            title={menuLabel}
            aria-label={`${label} — ${menuLabel}`}
            aria-haspopup="true"
            aria-expanded={!!(colMenu && colMenu.key === key)}
            onPointerDown={(e) => e.stopPropagation()}
            onMouseDown={(e) => e.stopPropagation()}
            onTouchStart={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              const fromSticky = !!e.currentTarget.closest(".market-sticky-head");
              setColMenu((c) => (c && c.key === key ? null : { key, fromSticky }));
            }}
          >
            <svg viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor"
              strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 6l4 4 4-4" />
            </svg>
          </button>
        )}
      </span>
    </th>
    );
  };

  // ТЗ §2.4/§9: "отсутствие данных показывается как нулевое изменение" was the
  // defect. This cell substituted 0 whenever a close price existed, so a security
  // that has not traded since 15.07 read as "unchanged today" beside securities
  // that genuinely did not move. Measured against the trade archive, seven rows
  // showed 0 % where the last real session moved by up to 20 %. No trading in
  // this session means no change to report — the cell says so, and names the day
  // the price is actually from.
  const sessionChangeCell = (row) => {
    if (!row.tradedToday) {
      const when = row.last_trade_date || row.ts?.trade_date;
      return (
        <td className="num">
          <span className="cell-status" title={when
            ? `${lang === "ru" ? "цена за" : lang === "uz" ? "narx" : "price from"} ${when}`
            : undefined}>
            {lang === "en" ? "no trades" : lang === "uz" ? "bitim yo'q" : "нет сделок"}
          </span>
        </td>
      );
    }
    return <td className="num"><MarketChangeBadge value={row.changeValue} percent={row.changePercent} language={lang} /></td>;
  };

  // A change over a window says which session it measured FROM. On this market
  // the base is rarely the date the label implies — a security can go a fortnight
  // without a trade, so «за неделю» is routinely measured from a close three
  // weeks old, and a reader is entitled to know that before acting on it.
  const windowChangeCell = (row, code) => {
    const hit = changeOver(row.ticker, code);
    if (!hit) {
      return (
        <td className="num">
          <span className="cell-status" title={lang === "en"
            ? "no settled close that far back"
            : lang === "uz" ? "bu davr uchun yopilish narxi yo'q"
            : "нет закрытия за этот период"}>—</span>
        </td>
      );
    }
    const from = String(hit.from || "");
    const pretty = from.length === 8 ? `${from.slice(6)}.${from.slice(4, 6)}.${from.slice(0, 4)}` : from;
    return (
      <td className="num" title={pretty
        ? `${lang === "en" ? "from the close of" : lang === "uz" ? "yopilishdan" : "от закрытия"} ${pretty}`
        : undefined}>
        <MarketChangeBadge percent={hit.pct} language={lang} />
      </td>
    );
  };

  // Label + cell registry so the movable columns can render in any order.
  // The columns whose figures ARE the period once one is chosen. Their headers
  // carry it: «Объём торгов» over a year and over this morning are different
  // claims, the table is read without the period control in view, and a reader
  // who cannot see which is on screen will read the year as today.
  const PERIOD_COLS = new Set(["open", "high", "low", "volume", "volQty",
                               "avgShare", "avgTrade", "bigTrade", "volShare"]);
  const LABEL_OF = Object.fromEntries(
    [["last", mt(lang, "last")], ...MARKET_COLS].map(([k, label]) => [
      k,
      windowed && PERIOD_COLS.has(k)
        ? `${label} · ${changePeriodLabel(changePeriod, lang, "short")}`
        : label,
    ]));
  const NUM_COLS = new Set(MOVABLE_KEYS.filter((k) => k !== "date" && k !== "source"));
  // What a period cell is a statement about. On this market «за полгода» is
  // routinely four sessions, so the count and the first session inside the
  // window are not decoration — they are what makes the figure readable.
  const prettyDay = (d) => {
    const v = String(d || "");
    return v.length === 8 ? `${v.slice(6)}.${v.slice(4, 6)}.${v.slice(0, 4)}` : v;
  };
  const periodHint = (row, { extremes = false, detail = false } = {}) => {
    if (!windowed || !row?.periodSessions) return undefined;
    const label = changePeriodLabel(changePeriod, lang, "short");
    const sessions = `${formatRatio(row.periodSessions, 0, lang)} ${sessionCountLabel(row.periodSessions, lang)}`;
    const span = row.periodFrom
      ? `${lang === "en" ? "from" : lang === "uz" ? "dan" : "с"} ${prettyDay(row.periodFrom)}${
          row.periodTo ? ` ${lang === "en" ? "to" : lang === "uz" ? "gacha" : "по"} ${prettyDay(row.periodTo)}` : ""}`
      : "";
    // A session banked before the day statistics existed carries no high or low,
    // and its close stands in for both. The extreme is then a bound, not a
    // reading, and the cell that shows it says so rather than implying precision.
    const bound = extremes && row.periodApprox
      ? (lang === "en" ? "some sessions counted by their close"
         : lang === "uz" ? "ba'zi sessiyalar yopilish narxi bo'yicha"
         : "по закрытиям части сессий")
      : "";
    // The deal count and the largest deal exist only for the sessions banked
    // with the day statistics beside them; over a year that is a subset, and a
    // floor presented as a total is the one thing these cells must not be.
    const partial = detail && row.periodDetailSessions
      ? (lang === "en" ? `by ${formatRatio(row.periodDetailSessions, 0, lang)} of ${formatRatio(row.periodSessions, 0, lang)} sessions`
         : lang === "uz" ? `${formatRatio(row.periodSessions, 0, lang)} sessiyadan ${formatRatio(row.periodDetailSessions, 0, lang)} tasi bo'yicha`
         : `по ${formatRatio(row.periodDetailSessions, 0, lang)} из ${formatRatio(row.periodSessions, 0, lang)} сессий`)
      : "";
    return [label, sessions, span, bound, partial].filter(Boolean).join(" · ");
  };
  const CELL_OF = {
    last: (row) => <td className="num">{(() => { const p = marketDisplayPrice(row); return p == null ? "—" : formatMarketNumber(p, lang); })()}</td>,
    // ТЗ §2.4/§9: "отсутствие данных показывается как нулевое изменение" was
    // the defect. This cell substituted 0 whenever a close price existed, so a
    // security that has not traded since 15.07 read as "unchanged today" beside
    // securities that genuinely did not move. Measured against the trade
    // archive, seven rows showed 0 % where the last real session moved by up to
    // 20 %. No trading in this session means no change to report — the cell
    // says so, and names the day the price is actually from.
    change: (row) => (changePeriod === "1d"
      ? sessionChangeCell(row)
      : windowChangeCell(row, changePeriod)),
    change1w: (row) => windowChangeCell(row, "1w"),
    change1m: (row) => windowChangeCell(row, "1m"),
    nominal: (row) => {
      const par = parOf(row);
      return <td className="num">{par == null ? "—" : formatMarketNumber(par, lang)}</td>;
    },
    priceToPar: (row) => {
      const ratio = priceToPar(row);
      return (
        <td className="num" title={ratio == null ? undefined : (lang === "en"
          ? `price ${formatMarketNumber(marketDisplayPrice(row), lang)} · par ${formatMarketNumber(parOf(row), lang)}`
          : lang === "uz" ? `narx ${formatMarketNumber(marketDisplayPrice(row), lang)} · nominal ${formatMarketNumber(parOf(row), lang)}`
          : `цена ${formatMarketNumber(marketDisplayPrice(row), lang)} · номинал ${formatMarketNumber(parOf(row), lang)}`)}>
          {ratio == null ? "—" : `${formatRatio(ratio, 2, lang)}×`}
        </td>
      );
    },
    // Over a window `openPrice` is the period's own opening price and is
    // `undefined` when no stored session can say — which is why the fallback
    // below tests for `null` exactly: a window with no open must print a dash,
    // never today's quote under a heading that says a year.
    open: (row) => <td className="num" title={periodHint(row)}>{(() => { const v = row.openPrice !== null ? row.openPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    high: (row) => <td className="num" title={periodHint(row, { extremes: true })}>{(() => { const v = row.highPrice !== null ? row.highPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    low: (row) => <td className="num" title={periodHint(row, { extremes: true })}>{(() => { const v = row.lowPrice !== null ? row.lowPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    volume: (row) => (
      <td className="num" title={periodHint(row)}>
        {row.stockVolume !== null ? formatRatio(row.stockVolume, 0, lang) : "—"}
        {row.stockTradeCount !== null && <span title={periodHint(row, { detail: true })}>{formatRatio(row.stockTradeCount, 0, lang)} {tradeCountLabel(row.stockTradeCount, lang)}</span>}
      </td>
    ),
    volQty: (row) => <td className="num" title={periodHint(row)}>{row.stockQuantity !== null ? formatRatio(row.stockQuantity, 0, lang) : "—"}</td>,
    avgShare: (row) => { const v = Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row); return <td className="num" title={periodHint(row)}>{v === null || v === undefined ? neverTraded(row) : formatMarketNumber(v, lang)}</td>; },
    avgTrade: (row) => <td className="num" title={periodHint(row, { detail: true })}>{avgTradeValue(row) !== null ? formatRatio(avgTradeValue(row), 0, lang) : neverTraded(row)}</td>,
    // Over a window this is the biggest deal of the whole period, and the
    // tooltip names the session it was struck in — «крупнейшая сделка за год»
    // is a fact about one day inside the year.
    bigTrade: (row) => (
      <td className="num" title={periodHint(row, { detail: true })}>
        {row.ts && Number.isFinite(row.ts.largest_value) ? (
          <>
            {formatRatio(row.ts.largest_value, 0, lang)}
            <span>
              {Number.isFinite(row.ts.largest_qty) ? `${formatRatio(row.ts.largest_qty, 0, lang)} ${mt(lang, "tradeQtyUnit")}` : ""}
              {Number.isFinite(row.ts.largest_pct_value) ? ` · ${formatRatio(row.ts.largest_pct_value, 1, lang)}%` : ""}
            </span>
          </>
        ) : neverTraded(row)}
      </td>
    ),
    volShare: (row) => <td className="num" title={periodHint(row)}>{(() => {
      // Share of the LATEST session's turnover: an untraded security's
      // backfilled old-day volume contributes 0% of today, by definition.
      // Over a window there is no such session — `stats.boardDay` is null — and
      // the share is of the window's own total, which is the same statement one
      // period longer.
      if (stats.boardDay && marketRowDay(row) !== stats.boardDay) return `0%`;
      return Number.isFinite(row.stockVolume) && stats.totalVolume > 0 ? `${formatRatio(row.stockVolume / stats.totalVolume * 100, 2, lang)}%` : "—";
    })()}</td>,
    finRevenue: (row) => finCell(row, "revenue"),
    // Bank/insurer/fund filings have no gross-profit or operating-income
    // lines (their reporting form differs) — when the issuer's top line IS
    // published but the form carries no such line, say "not applicable"
    // instead of an ambiguous dash.
    finGross: (row) => finCell(row, "gross_profit", { naWhenTopLine: true }),
    finCash: (row) => finCell(row, "cash"),
    finLiab: (row) => finCell(row, "total_liabilities"),
    finNet: (row) => finCell(row, "net_income"),
    finOperating: (row) => finCell(row, "operating_income", { naWhenTopLine: true }),
    mktCap: (row) => <td className="num">{(() => { const v = mktCapOf(row); return v == null ? noSecLabel(row) : formatRatio(v, 0, lang); })()}</td>,
    pe: (row) => {
      const m = valuationOf(row).pe;
      if (m?.value == null || m.status === "out_of_range") return multipleCell(row, m, 2);
      // Name the earnings period on the cell: this is the one multiple whose
      // denominator can come from a different filing than the row's own figures.
      const period = m.base_period;
      const months = m.base_months;
      return (
        <td className="num" title={period ? `${lang === "ru" ? "прибыль за" : lang === "uz" ? "foyda" : "earnings for"} ${period}${months ? ` · ${months} ${lang === "ru" ? "мес." : lang === "uz" ? "oy" : "months"}` : ""}` : undefined}>
          <strong>{formatRatio(m.value, 2, lang)}×</strong>
          {(() => {
            const sub = [period, m.estimate ? mt(lang, "estimateFlag") : null]
              .filter(Boolean).join(" · ");
            return sub ? <span className="fin-cell-period">{sub}</span> : null;
          })()}
        </td>
      );
    },
    pb: (row) => multipleCell(row, valuationOf(row).pb, 2),
    ps: (row) => multipleCell(row, multipleOf(row, "ps"), 2),
    roe: (row) => multipleCell(row, multipleOf(row, "roe"), 1, "%"),
    roa: (row) => multipleCell(row, multipleOf(row, "roa"), 1, "%"),
    netMargin: (row) => multipleCell(row, multipleOf(row, "net_margin"), 1, "%"),
    eqAssets: (row) => multipleCell(row, multipleOf(row, "equity_assets"), 1, "%"),
    currentRatio: (row) => ratioCell(row, "current_ratio"),
    quickRatio: (row) => ratioCell(row, "quick_ratio"),
    debtAssets: (row) => ratioCell(row, "debt_ratio", { digits: 1, suffix: "%" }),
    assetTurnover: (row) => ratioCell(row, "total_asset_turnover"),
    roce: (row) => ratioCell(row, "return_to_capital_employed"),
    date: (row) => (
      <td>
        {/* The live feed reports last_trade_date=null for some securities
            that did trade — the backfilled day stats carry the real date. */}
        <strong>{row.last_trade_date || tsDate(row) || mt(lang, "noTrade")}</strong>
        {row.close_date && <span>{mt(lang, "closeDate")} {row.close_date}</span>}
      </td>
    ),
    source: (row) => (
      <td>
        {row.url ? (
          <a className="market-source-link" href={row.url} target="_blank" rel="noreferrer">{mt(lang, "source")}</a>
        ) : "—"}
      </td>
    ),
  };

  // One header row, rendered twice: in the table itself and in the pinned bar
  // (MarketStickyHead), so both carry the same sort and drag-reorder handlers.
  const headCells = [
    sortTh("ticker", mt(lang, "ticker"), { pinKey: "__ticker" }),
    sortTh("company", mt(lang, "company"), { pinKey: "__company" }),
    ...visibleOrder.map((k) => sortTh(k, LABEL_OF[k], { movable: true, num: NUM_COLS.has(k), pinKey: k })),
  ];
  const pinTicker = pinAt("__ticker");
  const pinCompany = pinAt("__company");

  return (
    <section className="market-layout">
      <article className="panel market-hero-panel">
        <div className="market-hero-copy">
          <div className="panel-label">{mt(lang, "nav")}</div>
          <h1>{mt(lang, "title")}</h1>
          <p>{mt(lang, "subtitle")}</p>
        </div>
        {/* Operator controls, not reader information: the collector's stamp and
            the manual re-pull answer "did OUR 08:00/13:00/16:10 run land", a
            question only an admin can act on. Readers get the session date on
            the board itself. */}
        {isAdmin && (
          <div className="market-hero-actions">
            {/* When WE last refreshed the board (the collector's 08:00 / 13:00 /
                16:10 runs), not when someone else's mirror refreshed its cache —
                the second is what this used to show, and it can never report our
                schedule. The mirror's stamp and the session it describes stay in
                the tooltip; the feed stamp is the fallback if the trade-stats call
                has not landed yet. */}
            <span className="status-badge muted" title={marketStampTitle(meta, lang)}>
              {mt(lang, "updated")}: {formatMarketTimestamp(meta?.refreshed_at || meta?.updated_at, lang)}
            </span>
            <button className="ghost-btn" type="button" onClick={onRefresh} disabled={loading}>
              {loading ? mt(lang, "loading") : mt(lang, "refresh")}
            </button>
          </div>
        )}
      </article>

      {/* The FX strip and summary cards provide context for the visual map, but
          duplicate information available in the market table. Keep this block
          on the dedicated heatmap page only. */}
      {viewMode === "heatmap" && (
        <>
          <FxRatesBar language={lang} onOpenBanks={onOpenBankFx} />

          {/* The sector control that scopes these four cards is further down the
              page, in the filter bar — so the row has to say for itself which
              sector it is answering for, and offer the way back. Without this the
              numbers change under a control the reader cannot see from here. */}
          {cardSector && (
            <div className="market-stats-scope">
              <span className="market-stats-scope-label">
                {lang === "en" ? "Sector" : lang === "uz" ? "Tarmoq" : "Категория"}:
              </span>
              <button type="button" className="market-stats-scope-chip" onClick={() => setMarketSector(null)}>
                {sectorLabel(lang, cardSector)}
                <span aria-hidden="true">×</span>
              </button>
            </div>
          )}

          <div className="market-stats-grid">
        {/* Инструментов / Сделки сегодня / Без изменений were removed at the
            customer's request (2026-08-12) — the row keeps only the counters
            that name a mover or a sum of money. Up and down belong to one market
            breadth reading, so they share a card and a proportional rail. */}
        <MarketBreadthCard
          language={lang}
          advancers={cardStats.advancers}
          decliners={cardStats.decliners}
          topGrowth={formatLeader(cardStats.topGrowth)}
          topDrop={formatLeader(cardStats.topDrop)} />
        {/* ТЗ §8: the market's capitalisation is its ACTIVE SHARES. The client
            sum counted bonds, which carry no ownership, and dormant listings —
            23 of them, 29 088 bn — inside a figure labelled "the market". The
            server now answers with the total and with what it left out. */}
        {(() => {
          // Whole board: the server's own figure, because only it can say what it
          // left out. Under a sector chip there is no server answer to ask for, so
          // the sum comes from that sector's active rows — the same pool the three
          // counters beside it use — and the note counts what it left out of THEM.
          const server = cardSector ? null : marketSummary?.market_cap;
          const value = server?.value ?? cardStats.totalMarketCap;
          if (!(value > 0)) return null;
          let sub = "UZS";
          if (server) {
            const ex = server.excluded || {};
            const excludedNote = [
              ex.bonds?.instruments ? `${lang === "ru" ? "облигации" : lang === "uz" ? "obligatsiyalar" : "bonds"} — ${ex.bonds.instruments}` : null,
              ex.inactive_listings?.instruments ? `${lang === "ru" ? "неактивные" : lang === "uz" ? "faol emas" : "inactive"} — ${ex.inactive_listings.instruments}` : null,
            ].filter(Boolean).join(", ");
            if (excludedNote) sub = `UZS · ${lang === "ru" ? "исключено" : lang === "uz" ? "hisobdan chiqarilgan" : "excluded"}: ${excludedNote}`;
          } else if (sectorDormant) {
            // Its own sentence, not the market note's list with one item left in
            // it: «без облигации: 17, неактивные: 10» works as an enumeration
            // after «без», «без неактивные: 10» on its own does not.
            sub = `UZS · ${lang === "ru" ? "без неактивных" : lang === "uz" ? "faol emaslarsiz" : "excl. inactive"}: ${sectorDormant}`;
          }
          if (Number.isFinite(capPeriodChange)) {
            // The period the reader chose, spelled out beside its own number:
            // the card is read without the period control in view.
            sub = `${sub} · ${changePeriodLabel(changePeriod, lang, "short")}: ${
              capPeriodChange > 0 ? "+" : ""}${formatRatio(capPeriodChange, 2, lang)}%`;
          }
          return (
            <MarketStatCard
              label={mt(lang, "marketCap")}
              value={formatCompactVolume(value, lang)}
              sub={sub}
              kind="capitalization" />
          );
        })()}
        {/* The day's turnover is the sum of the rows below it, not a separate
            feed's idea of the day: the mirror's /trades snapshot covers a fixed
            44 securities and called 31.07 "120,7 млн over ~900 trades" while the
            board it sits above listed 1,56 млрд over 6 507 — and it cannot
            answer per tab, so the shares view was quoting bond turnover too. */}
        {cardStats.totalVolume > 0 && <MarketStatCard label={windowed ? `${mt(lang, "volume")} · ${changePeriodLabel(changePeriod, lang, "short")}` : mt(lang, "volume")} termId="volume" lang={lang} value={formatCompactVolume(cardStats.totalVolume, lang)} sub={cardStats.totalTrades ? `${formatRatio(cardStats.totalTrades, 0, lang)} ${tradeCountLabel(cardStats.totalTrades, lang)}` : null} kind="turnover" />}
          </div>
        </>
      )}

      {/* Three readings of one session: who moved, and who was actually
          tradeable. Ликвидность answers the question the two percent lists
          cannot — a +20 % on one 37 200-сум trade is a move, not a market —
          and it reads off the same «Объём» (turnover in money) the column, the
          turnover card and the charts already mean — in the same compact form
          those use, so the figure is recognisable without a unit spelled out
          beside it (one was tried in the head and the customer had it out). */}
      {viewMode === "table"
        && (periodMovers.topGainers.length > 0 || periodMovers.topLosers.length > 0 || periodMovers.topVolume.length > 0) && (
        <div className="market-top-movers">
          {[
            // The two change panels carry the selected period in their heading:
            // «Топ роста» over a month and over a session are different claims,
            // and the strip is read at a glance without the control in view.
            { key: "up", title: `${mt(lang, "topGainers")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
              rows: periodMovers.topGainers,
              value: (r) => `+${formatRatio(changePeriod === "1d" ? r.changePercent : r.periodPct, 2, lang)}%` },
            { key: "down", title: `${mt(lang, "topLosers")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
              rows: periodMovers.topLosers,
              value: (r) => `${formatRatio(changePeriod === "1d" ? r.changePercent : r.periodPct, 2, lang)}%` },
            // Ликвидность carries the period too, and over a window it says how
            // many sessions it added up and from which one: «5,6 млрд» over six
            // months means one thing across 80 sessions and quite another across
            // three, and the panel is read without the control in view.
            { key: "vol", title: `${mt(lang, "topLiquidity")}${changePeriod === "1d" ? "" : ` · ${changePeriodLabel(changePeriod, lang, "short")}`}`,
              rows: periodMovers.topVolume,
              value: (r) => formatCompactVolume(changePeriod === "1d" ? r.stockVolume : r.periodVolume, lang),
              hint: (r) => {
                if (changePeriod === "1d" || !r.periodSessions) return undefined;
                const from = String(r.periodFrom || "");
                const pretty = from.length === 8 ? `${from.slice(6)}.${from.slice(4, 6)}.${from.slice(0, 4)}` : from;
                const sessions = `${formatRatio(r.periodSessions, 0, lang)} ${sessionCountLabel(r.periodSessions, lang)}`;
                return pretty
                  ? `${sessions} ${lang === "en" ? "since" : lang === "uz" ? "boshlab" : "с"} ${pretty}`
                  : sessions;
              } },
          ].map((col) => (
            <article className={`market-movers-col ${col.key}`} key={col.key}>
              <div className="market-movers-head">
                <span className={`market-movers-dot ${col.key}`} />
                <h3>{col.title}</h3>
              </div>
              <ul className="market-movers-list">
                {col.rows.length ? col.rows.map((r, index) => (
                  <li key={r.ticker}>
                    <button
                      type="button"
                      className="market-movers-item"
                      title={col.hint ? col.hint(r) : undefined}
                      onClick={() => onOpenCompany ? onOpenCompany(r.ticker) : onAnalyze(r.ticker)}
                    >
                      <span className="market-movers-rank" aria-hidden="true">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <span className="market-movers-tk">
                        <CompanyLogo logo={smap[r.ticker]?.logo_url} name={r.name || r.ticker} ticker={r.ticker} />
                        <span className="market-movers-name">{r.ticker}</span>
                      </span>
                      <span className={`market-movers-chg ${col.key}`}>{col.value(r)}</span>
                    </button>
                  </li>
                )) : <li className="market-movers-empty">—</li>}
              </ul>
            </article>
          ))}
        </div>
      )}

      <article className="panel market-board">
        <div className="market-board-head">
          <div>
            <div className="panel-label">{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</div>
            <h2>{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</h2>
          </div>
          <div className="market-board-head-right">
            {(windowed || stats.boardDay) && (
              <span className="market-session-date">
                {windowed
                  ? changePeriodLabel(changePeriod, lang, "label")
                  : `${stats.boardDay.slice(6, 8)}.${stats.boardDay.slice(4, 6)}.${stats.boardDay.slice(0, 4)}`}
              </span>
            )}
            <div className="market-view-toggle">
              <button
                type="button"
                className={viewMode === "table" ? "active" : ""}
                onClick={() => setViewMode("table")}
                title={lang === "en" ? "Table view" : lang === "uz" ? "Jadval ko'rinishi" : "Таблица"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="2" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="6.6" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="11.2" width="13" height="1.8" rx="0.9"/>
                </svg>
                <span>{lang === "en" ? "Table" : lang === "uz" ? "Jadval" : "Таблица"}</span>
              </button>
              <button
                type="button"
                className={viewMode === "heatmap" ? "active" : ""}
                onClick={() => setViewMode("heatmap")}
                title={lang === "en" ? "Market map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="1" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                </svg>
                <span>{lang === "en" ? "Map" : lang === "uz" ? "Xarita" : "Карта"}</span>
              </button>
            </div>
            {viewMode === "table" && (
              <span className="status-badge muted">{mt(lang, "showing")}: {visibleRows.length}/{prepared.length}</span>
            )}
          </div>
        </div>

        {/* Every filter the board has — instrument class, share class, favourites,
            search, the column picker and the sector chips — lives in one block so
            it can stick under the topbar as a unit. Scrolling to row 300 must not
            cost the reader the controls that put those rows on screen. */}
        <div className="market-filterbar">
        <div className="market-controls">
          {/* Level 1: instrument class — stocks vs bonds are not comparable
              (price/capitalisation vs coupon/maturity), so they never share a table. */}
          <div className="market-type-levels">
            <div className="segmented-control market-type-control">
              {[
                ["stock", mt(lang, "stocks")],
                ["bond", mt(lang, "bonds")],
              ].map(([value, label]) => {
                const active = value === "bond" ? type === "bond" : type !== "bond";
                return (
                  <button key={value} type="button" className={active ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>
                );
              })}
            </div>
            {/* MAIN | NEGO — the exchange's own two boards, side by side with the
                instrument class because that is the same kind of choice: which
                market you are looking at, not which slice of one. The count says
                how many lines had a negotiated deal, so an empty NEGO board
                reads as «none today» rather than as a broken page. */}
            <div className="segmented-control market-segment-control"
              role="group"
              aria-label={lang === "en" ? "Market board" : lang === "uz" ? "Bozor" : "Рынок"}>
              {[["main", lang === "en" ? "Main" : lang === "uz" ? "Asosiy" : "Основной"],
                ["nego", lang === "en" ? "Negotiated" : lang === "uz" ? "Kelishilgan" : "Переговорный"]]
                .map(([value, label]) => (
                  <button key={value} type="button"
                    className={segment === value ? "active" : ""}
                    aria-pressed={segment === value}
                    onClick={() => setSegment(value)}
                    title={value === "main"
                      ? (lang === "en" ? "The auction session (board G1)"
                         : lang === "uz" ? "Auksion sessiyasi (G1)" : "Аукционная сессия (борд G1)")
                      : (lang === "en" ? "Negotiated deals, struck bilaterally (board T1)"
                         : lang === "uz" ? "Kelishilgan bitimlar (T1)" : "Переговорные сделки, вне сессии (борд T1)")}>
                    {label}
                    {value === "nego" && negotiatedCount > 0 ? ` (${negotiatedCount})` : ""}
                  </button>
                ))}
            </div>
            {/* Level 2: share class — only meaningful inside stocks. */}
            {type !== "bond" && (
              <div className="segmented-control market-subtype-control">
                {[
                  ["stock", mt(lang, "all")],
                  ["ordinary", mt(lang, "ordinaryStocks")],
                  ["preferred", mt(lang, "preferredStocks")],
                ].map(([value, label]) => (
                  <button key={value} type="button" className={type === value ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          {/* Отрасль. A dropdown rather than the row of chips this used to be:
              eleven chips took a band of the pinned bar to themselves, wrapped
              onto two lines on a laptop, and — because the band was drawn for
              the table only — the map had no sector control at all. One list,
              one answer, both views. */}
          {presentSectors.length > 1 && (
            <label className="market-sector-select">
              <select
                value={activeSector || ""}
                data-all={activeSector ? undefined : "1"}
                onChange={(event) => setMarketSector(event.target.value || null)}
                aria-label={sectorWord}
                title={lang === "en" ? "Show one sector only"
                  : lang === "uz" ? "Faqat bitta sohani ko'rsatish"
                  : "Показать только одну отрасль"}
              >
                <option value="">{`${sectorWord}: ${sectorLabel(lang, "all").toLowerCase()}`}</option>
                {presentSectors.map((s) => (
                  <option key={s} value={s}>{sectorLabel(lang, s)}</option>
                ))}
              </select>
            </label>
          )}
          {viewMode === "table" && (
            <button
              type="button"
              className={`market-fav-filter ${favOnly ? "active" : ""}`}
              aria-pressed={favOnly}
              onClick={() => setFavOnly((v) => !v)}
              title={lang === "en" ? "Show favorites only" : lang === "uz" ? "Faqat tanlanganlar" : "Только избранное"}
            >
              <span className="fav-star">{favOnly ? "★" : "☆"}</span>
              <span className="market-btn-label">{lang === "en" ? "Favorites" : lang === "uz" ? "Tanlanganlar" : "Избранное"}</span>
            </button>
          )}
          {/* ТЗ §4: dormant listings are hidden, not dropped — the count says
              how many, so their absence is a stated fact rather than a silence,
              and the chip shows exactly those rows. Table only: the map has
              nothing to draw for a security with no session (see `mapRows`), so
              offering the switch there would be offering eleven empty squares. */}
          {viewMode === "table" && dormantCount > 0 && (
            <button
              type="button"
              className={`market-fav-filter market-dormant-filter ${inactiveOnly ? "active" : ""}`}
              aria-pressed={inactiveOnly}
              onClick={() => setInactiveOnly((v) => !v)}
              title={inactiveOnly
                ? (lang === "en" ? "Back to the traded board"
                   : lang === "uz" ? "Savdodagi ro'yxatga qaytish" : "Вернуться к торгуемым")
                : (lang === "en" ? `Show the ${dormantCount} listings with no trades for 90 days`
                   : lang === "uz" ? `90 kun bitimsiz ${dormantCount} qog'ozni ko'rsatish`
                   : `Показать ${dormantCount} бумаг без сделок более 90 дней`)}
            >
              <span className="market-btn-label">
                {lang === "en" ? "Inactive" : lang === "uz" ? "Faol emas" : "Неактивные"}
                {` (${dormantCount})`}
              </span>
            </button>
          )}
          {viewMode === "table" && (
            <label className="market-search">
              <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} />
            </label>
          )}
          {viewMode === "table" && (
            <button type="button" className="market-fav-filter market-export-btn" onClick={exportCsv} title={mt(lang, "exportCsv")}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
              <span className="market-btn-label">{mt(lang, "exportCsv")}</span>
            </button>
          )}
          {viewMode === "table" && (
            <div className="market-cols-wrap">
              <button
                type="button"
                ref={colsBtnRef}
                className={`market-cols-btn ${colsOpen ? "active" : ""}`}
                aria-haspopup="true" aria-expanded={colsOpen}
                onClick={() => setColsOpen((o) => !o)}
                title={lang === "en"
                  ? "Choose which columns the table shows"
                  : lang === "uz" ? "Jadval ustunlarini tanlash"
                  : "Выбрать колонки таблицы"}
              >
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
                {/* Named, like every other button in this bar. A bare gear beside
                    «Избранное», «Неактивные» and «Экспорт CSV» read as an
                    afterthought and was the one control a reader had to guess at —
                    which is how a board with fifteen hidden columns looks like a
                    board that has none. The count says how many are on. */}
                <span className="market-btn-label">
                  {lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"}
                  <span className="market-cols-count">{shownOrder.length}</span>
                </span>
              </button>
              {colsOpen && (
                <MarketColsPopover
                  anchorRef={colsBtnRef}
                  onClose={() => setColsOpen(false)}
                  title={lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"}
                  closeLabel={lang === "en" ? "Close" : lang === "uz" ? "Yopish" : "Закрыть"}
                >
                  <>
                    <div className="market-cols-search">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
                      <input
                        type="text"
                        value={colsSearch}
                        onChange={(e) => setColsSearch(e.target.value)}
                        placeholder={lang === "en" ? "Search" : lang === "uz" ? "Qidirish" : "Поиск"}
                      />
                    </div>
                    {/* Its own scrollport: the groups scroll here, the search box
                        and the reset footer stay put, and `overscroll-behavior`
                        (CSS) stops the page behind from taking over the gesture. */}
                    <div className="market-cols-body">
                    {(() => {
                      const q = colsSearch.trim().toLowerCase();
                      const matches = (label) => !q || label.toLowerCase().includes(q);
                      const anyMatch = CORE_COLS.some(([, l]) => matches(l)) || MARKET_COLS.some(([, l]) => matches(l));
                      if (!anyMatch) {
                        return <div className="market-cols-empty">{lang === "en" ? "Nothing found" : lang === "uz" ? "Hech narsa topilmadi" : "Ничего не найдено"}</div>;
                      }
                      return (
                        <>
                          {!q && (
                            <div className="market-cols-group">
                              <div className="market-cols-group-body">
                                {CORE_COLS.map(([k, label]) => (
                                  <label key={k} className="market-cols-row market-cols-row-locked">
                                    <input type="checkbox" checked disabled readOnly />
                                    <span>{label}</span>
                                    {/* Same ⓘ as the column header: this panel is where a
                                        reader decides whether a column is worth its width,
                                        which is exactly when they need to know what it
                                        means — before it is on screen to be hovered. */}
                                    <TermInfo termId={k} lang={lang} label={label} />
                                  </label>
                                ))}
                              </div>
                            </div>
                          )}
                          {COL_GROUPS.map((group) => {
                            const cols = group.cols.filter(([, label]) => matches(label));
                            if (!cols.length) return null;
                            const open = q ? true : openGroups.has(group.key);
                            const allOn = group.cols.every(([k]) => visibleCols.has(k));
                            const someOn = group.cols.some(([k]) => visibleCols.has(k));
                            const shownInGroup = group.cols.filter(([k]) => visibleCols.has(k)).length;
                            const setGroupAll = () => setVisibleCols((prev) => {
                              const n = new Set(prev);
                              group.cols.forEach(([k]) => { if (allOn) n.delete(k); else n.add(k); });
                              return n;
                            });
                            return (
                              <div className="market-cols-group" key={group.key}>
                                <button
                                  type="button"
                                  className="market-cols-group-head"
                                  onClick={() => toggleGroup(group.key)}
                                  aria-expanded={open}
                                >
                                  <span className="market-cols-group-title">{group.title}</span>
                                  <span className="market-cols-group-meta">
                                    <span className="market-cols-group-badge">{shownInGroup}</span>
                                    <span className={`market-cols-group-chevron${open ? " open" : ""}`}>›</span>
                                  </span>
                                </button>
                                {open && (
                                  <div className="market-cols-group-body">
                                    {!q && (
                                      <label className="market-cols-row market-cols-all">
                                        <input
                                          type="checkbox"
                                          checked={allOn}
                                          ref={(el) => { if (el) el.indeterminate = someOn && !allOn; }}
                                          onChange={setGroupAll}
                                        />
                                        <span>{lang === "en" ? "All" : lang === "uz" ? "Hammasi" : "Все"}</span>
                                      </label>
                                    )}
                                    {cols.map(([k, label]) => (
                                      <label key={k} className="market-cols-row">
                                        <input
                                          type="checkbox"
                                          checked={visibleCols.has(k)}
                                          onChange={() => toggleCol(k)}
                                        />
                                        <span>{label}</span>
                                        {/* The picker's column key IS the glossary id, so the
                                            row asks for its own definition. A column that is
                                            not an economic term (Источник) renders no marker.
                                            The ⓘ is a <button>: per the HTML spec a label does
                                            not activate for events aimed at interactive
                                            descendants, so asking what P/E means does not
                                            toggle the P/E column. */}
                                        <TermInfo termId={k} lang={lang} label={label} />
                                      </label>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </>
                      );
                    })()}
                    </div>
                    <div className="market-cols-footer">
                      {/* The two things the headers do that a header does not look
                          like it does. This panel is where a reader comes looking
                          for table controls, so both are stated here as well. */}
                      <span className="market-cols-hint">
                        <span>{lang === "en" ? "Drag column headers to reorder" : lang === "uz" ? "Tartib uchun sarlavhalarni torting" : "Перетаскивайте заголовки для порядка"}</span>
                        <span>{coarsePointer
                          ? (lang === "en" ? "Press and hold a header to sort by two columns"
                            : lang === "uz" ? "Ikki ustun bo‘yicha saralash — sarlavhani uzoq bosing"
                            : "Долгое нажатие — сортировка по двум колонкам")
                          : (lang === "en" ? "Shift + click to sort by two columns"
                            : lang === "uz" ? "Shift + bosish — ikki ustun bo‘yicha saralash"
                            : "Shift + клик — сортировка по двум колонкам")}</span>
                      </span>
                      <button type="button" className="market-cols-reset" onClick={resetColOrder}>
                        {lang === "en" ? "Reset order" : lang === "uz" ? "Tartibni tiklash" : "Сбросить порядок"}
                      </button>
                    </div>
                  </>
                </MarketColsPopover>
              )}
            </div>
          )}
        </div>

          {/* The period every «изменение» on this screen is measured over. It
            moves the «Изм.» column, the movers strip and the map together —
            one question, one answer. The two fixed 1Н/1М columns stay where
            they are; a reader can still have all three on screen. */}
        <div className="market-period-row">
        <span className="market-period-label">
          {lang === "en" ? "Change over" : lang === "uz" ? "O'zgarish davri" : "Изменение за"}
        </span>
        <div className="segmented-control market-period-control"
          role="group"
          aria-label={lang === "en" ? "Change period" : lang === "uz" ? "O'zgarish davri" : "Период изменения"}>
          {CHANGE_PERIODS.map((p) => (
            <button
              key={p.code}
              type="button"
              className={changePeriod === p.code ? "active" : ""}
              aria-pressed={changePeriod === p.code}
              onClick={() => setChangePeriod(p.code)}
              title={lang === "en" ? `Change over ${changePeriodLabel(p.code, lang)}`
                : lang === "uz" ? `${changePeriodLabel(p.code, lang)} o'zgarishi`
                : `Изменение за ${changePeriodLabel(p.code, lang).toLowerCase()}`}
            >
              {p.code === "1d"
                ? (lang === "en" ? "Session" : lang === "uz" ? "Sessiya" : "Сессия")
                : p.code === "ytd" ? "YTD" : changePeriodLabel(p.code, lang)}
            </button>
          ))}
        </div>
        </div>

        {/* A sort built from two headers is invisible once you scroll — the carets
            are off in the columns that made it. Spell the chain out, in order, with
            one control back to the board's default order.

            It shows from the FIRST sorted column, not the second, for two reasons:
            until now a header click could never be undone (there was no way back to
            "latest session first"), and one sorted column is exactly the moment the
            reader is ready to be told a second one can be added. */}
        {viewMode === "table" && sortKeys.length > 0 && (
          <div className="market-sort-chain">
            <span className="market-sort-chain-label">
              {lang === "en" ? "Sorted by" : lang === "uz" ? "Saralash" : "Сортировка"}:
            </span>
            {sortKeys.map(({ key, dir }, i) => (
              <button
                key={key}
                type="button"
                className="market-sort-chain-chip"
                onClick={() => onSort(key, true)}
                title={lang === "en" ? "Click to flip, again to remove"
                  : lang === "uz" ? "Yoʻnalishni almashtirish uchun bosing, olib tashlash uchun yana bosing"
                  : "Клик — сменить направление, ещё раз — убрать"}
              >
                {sortKeys.length > 1 && <span className="market-sort-chain-rank">{i + 1}</span>}
                <span>{SORT_LABEL_OF[key] || key}</span>
                <span className="market-sort-caret">{dir === "asc" ? "▲" : "▼"}</span>
              </button>
            ))}
            {sortKeys.length === 1 && !sortHintSeen && (
              <span className="market-sort-teach">
                {coarsePointer ? (
                  lang === "en" ? <>press and hold another column to sort by <b>two</b></>
                    : lang === "uz" ? <>ikkinchi kalit uchun boshqa ustunni <b>uzoq bosing</b></>
                    : <>удерживайте другую колонку, чтобы сортировать по <b>двум</b></>
                ) : (
                  lang === "en" ? <><kbd>Shift</kbd> + click another column to sort by <b>two</b></>
                    : lang === "uz" ? <><kbd>Shift</kbd> + boshqa ustunni bosing — <b>ikkita</b> kalit</>
                    : <><kbd>Shift</kbd> + клик по другой колонке — сортировка по <b>двум</b></>
                )}
                <button
                  type="button"
                  className="market-sort-teach-close"
                  onClick={dismissSortHint}
                  aria-label={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                  title={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                >×</button>
              </span>
            )}
            <button type="button" className="market-sort-chain-reset" onClick={clearSort}>
              {lang === "en" ? "Reset" : lang === "uz" ? "Tiklash" : "Сбросить"}
            </button>
          </div>
        )}
        </div>

        {/* ТЗ Дополнение 1 §А.2: bonds get their own table, not a row in the
            equity board — an issue has a value rather than a capitalisation, and
            no earnings for a multiple to divide by. The «Облигации» segment IS
            the bond section: screener + yield map, a row opens /bond/{T}. */}
        {viewMode === "table" && type === "bond" ? (
          <BondsView language={lang} onOpenBond={onOpenBond || onAnalyze} embedded />
        ) : viewMode === "heatmap" ? (
          blocksMarketContent(loading, rows.length) ? (
            <p className="market-empty-cell">{mt(lang, "loading")}</p>
          ) : (
            <MarketHeatmap rows={sectorMapRows} companies={companies} securitiesMap={smap} language={lang} onAnalyze={onAnalyze} onOpenCompany={onOpenCompany} type={type} mapData={mapData} period={changePeriod} />
          )
        ) : (
          <>
          {/* What the reader is now looking at, and why these rows do not
              behave like the rest of the board: the price is a close from
              months ago carried forward, the day's change is nil because there
              was no day, and the server leaves them out of the market's
              capitalisation. Without this the eleven rows look like eleven
              securities that all happened to close flat. */}
          {inactiveOnly && (
            <p className="market-dormant-note">
              {lang === "en"
                ? "Listings with no trades for over 90 days. The price is their last settled close, carried forward — there is no day's move, and the market capitalisation above leaves them out."
                : lang === "uz"
                  ? "90 kundan ortiq bitimsiz qog'ozlar. Narx — ularning oxirgi yopilishi, oldinga ko'chirilgan; kunlik o'zgarish yo'q va yuqoridagi kapitalizatsiya ularni hisobga olmaydi."
                  : "Бумаги без сделок более 90 дней. Цена — их последнее закрытие, перенесённое вперёд: дневного изменения нет, и в капитализацию рынка выше они не входят."}
            </p>
          )}
          {/* The NEGO board's own contract, stated where it is read: which
              columns are negotiated figures, which are still the session's, and
              why the two are never added together. */}
          {segment === "nego" && (
            <p className="market-dormant-note">
              {lang === "en"
                ? "Negotiated deals (exchange board T1) — struck bilaterally at an agreed price, outside the auction. Turnover, quantity, trades and the average price are the negotiated ones; the quote, the day's change and the OHLC remain the auction session's, because a negotiated price is not a quote. The exchange's own bulletin excludes these deals from the session, and so does the Main board."
                : lang === "uz"
                  ? "Kelishilgan bitimlar (T1 bordi) — auksiondan tashqari, kelishilgan narxda. Aylanma, hajm, bitimlar soni va o'rtacha narx — kelishilgan; kotirovka, kunlik o'zgarish va OHLC — auksion sessiyasining, chunki kelishilgan narx kotirovka emas."
                  : "Переговорные сделки (борд T1) — заключены двусторонне по согласованной цене, вне аукциона. Оборот, количество, число сделок и средняя цена — переговорные; котировка, дневное изменение и OHLC остаются аукционными, потому что переговорная цена не является котировкой. Бюллетень биржи не включает эти сделки в сессию — и «Основной» рынок здесь тоже."}
            </p>
          )}
          {segment === "nego" && negotiatedCount === 0 && !loading && (
            <p className="market-dormant-note">
              {lang === "en"
                ? `No negotiated deals on record for the securities on this board.${
                    negotiatedAnywhere ? ` The exchange's statistics hold ${negotiatedAnywhere} for other instruments — most of them bonds, which have their own section.` : ""}`
                : lang === "uz"
                  ? `Bu ro'yxatdagi qog'ozlar bo'yicha kelishilgan bitimlar yo'q.${
                      negotiatedAnywhere ? ` Boshqa instrumentlar bo'yicha — ${negotiatedAnywhere}, asosan obligatsiyalar.` : ""}`
                  : `По бумагам этого раздела переговорных сделок не зафиксировано.${
                      negotiatedAnywhere ? ` В статистике биржи их ${negotiatedAnywhere} по другим инструментам — в основном по облигациям, у которых свой раздел.` : ""}`}
            </p>
          )}
          <div className="market-table-wrap" ref={wrapRef}>
            <table className="market-table">
              <thead>
                <tr>{headCells}</tr>
              </thead>
              <tbody>
                {blocksMarketContent(loading, rows.length) ? (
                  <tr><td colSpan={colSpan} className="market-empty-cell">{mt(lang, "loading")}</td></tr>
                ) : visibleRows.length ? (
                  visibleRows.map((row) => {
                    const sec = smap[row.ticker] || {};
                    const logo = sec.logo_url;
                    const isPreferred = sec.is_preferred || row.share_type === "preferred";
                    const isFav = hasFav(row.ticker);
                    return (
                    <tr key={`${row.ticker}-${row.isin}`}>
                      <td className={`market-ticker-cell${pinCls(pinTicker)}`} style={pinTicker ? { left: pinTicker.left } : undefined}>
                        <button
                          type="button"
                          className={`market-fav-btn ${isFav ? "is-fav" : ""}`}
                          aria-pressed={isFav}
                          title={isFav
                            ? (lang === "en" ? "Remove from favorites" : lang === "uz" ? "Tanlanganlardan olib tashlash" : "Убрать из избранного")
                            : (lang === "en" ? "Add to favorites" : lang === "uz" ? "Tanlanganlarga qo'shish" : "В избранное")}
                          onClick={(e) => { e.stopPropagation(); onToggleFavorite && onToggleFavorite(row.ticker, row.name); }}
                        >
                          {isFav ? "★" : "☆"}
                        </button>
                        <CompanyLogo logo={logo} name={row.name || row.ticker} ticker={row.ticker} />
                        <div className="market-ticker-info">
                          <button type="button" className="market-ticker-btn" onClick={() => onOpenCompany ? onOpenCompany(row.ticker) : onAnalyze(row.ticker)}>
                            {row.ticker || "—"}
                          </button>
                          <span>{(row.type === "bond" || sec.type === "bond")
                            ? mt(lang, "bondOne")
                            : isPreferred ? mt(lang, "preferred")
                            : row.share_type ? mt(lang, row.share_type)
                            : (row.type || "—")}</span>
                        </div>
                        <button
                          type="button"
                          className="market-info-btn"
                          title={lang === "en" ? "Company info" : lang === "uz" ? "Kompaniya ma'lumoti" : "О компании"}
                          onClick={() => openPanel(row.ticker)}
                        >ℹ</button>
                      </td>
                      <td className={pinCls(pinCompany).trim() || undefined} style={pinCompany ? { left: pinCompany.left } : undefined}>
                        <button type="button" className="market-company-name-btn" onClick={() => onOpenCompany && onOpenCompany(row.ticker)}>
                          {row.name || sec.name || "—"}
                        </button>
                        <span>{row.isin || "—"}</span>
                      </td>
                      {visibleOrder.map((k) => {
                        const cell = CELL_OF[k](row);
                        const pin = pinAt(k);
                        if (!pin) return React.cloneElement(cell, { key: k });
                        return React.cloneElement(cell, {
                          key: k,
                          className: `${cell.props.className || ""}${pinCls(pin)}`.trim(),
                          style: { ...(cell.props.style || {}), left: pin.left },
                        });
                      })}
                    </tr>
                    );
                  })
                ) : (
                  <tr><td colSpan={colSpan} className="market-empty-cell">{favOnly
                    ? (lang === "en" ? "No favorites yet — tap ☆ next to a company to track it."
                       : lang === "uz" ? "Hali tanlanganlar yo'q — kuzatish uchun kompaniya yonidagi ☆ ni bosing."
                       : "Пока нет избранного — нажмите ☆ рядом с компанией, чтобы следить за ней.")
                    : inactiveOnly
                      ? (lang === "en" ? "No dormant listing matches the current filters."
                         : lang === "uz" ? "Joriy filtrlarga mos keladigan faol bo'lmagan qog'oz yo'q."
                         : "Под текущие фильтры не попала ни одна неактивная бумага.")
                      : mt(lang, "empty")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <MarketStickyHead
            wrapRef={wrapRef}
            cells={headCells}
            colSignature={visibleOrder.join("|")}
            rowCount={visibleRows.length}
            loading={loading}
          />
          <MarketFloatScroll
            wrapRef={wrapRef}
            colSignature={visibleOrder.join("|")}
            rowCount={visibleRows.length}
            loading={loading}
          />
          {colMenu && visibleOrder.includes(colMenu.key) && (() => {
            const key = colMenu.key;
            const group = colGroupOf(key);
            const i = group.indexOf(key);
            return (
              <MarketColMenu
                colKey={key}
                fromSticky={colMenu.fromSticky}
                lang={lang}
                state={{
                  dir: sortDirOf(key),
                  pinned: pinnedCols.has(key),
                  canLeft: i > 0,
                  canRight: i >= 0 && i < group.length - 1,
                  // "Последняя" is a core column: the picker keeps it locked too.
                  canHide: key !== "last",
                }}
                actions={{
                  sort: (dir) => setSortKeys([{ key, dir }]),
                  move: (step) => moveColBy(key, step),
                  pin: () => togglePin(key),
                  hide: () => { toggleCol(key); setColMenu(null); },
                }}
                onClose={closeColMenu}
              />
            );
          })()}
          </>
        )}
      </article>

      {panelTicker && (
        <CompanyInfoPanel
          ticker={panelTicker}
          secInfo={smap[panelTicker]}
          wikiInfo={panelWiki}
          language={language}
          onClose={() => { setPanelTicker(null); setPanelWiki(null); }}
          loading={panelWikiLoading}
        />
      )}
    </section>
  );
}

export { MarketView };
