import { prepareMarketRows } from "../../lib/marketData.js";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import React from "react";
import { QC_COLORS, QC_MAX, chartRangeMonths, chartRangeWindowQuery, quickComparePeers } from "../../shared/priceChartModel.jsx";

import { CompanyWatchRail, watchRailLists } from "../../shared/CompanyWatchRail.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { signedFixed } from "../../shared/format.jsx";
import { CompanyInsightCard, CompanyInsightDialog } from "./Insights.jsx";
import { CompanyOverviewTab, CompanyReportsTab } from "./Overview.jsx";
import { CompanyPriceChart } from "../../shared/CompanyPriceChart.jsx";
import { QuickCompareStrip } from "../../shared/QuickCompareStrip.jsx";
import { CompanyDividendsTab, CompanyFinancialsTab } from "./Financials.jsx";

function CompanyPage({ ticker, securitiesMap, language, onBack, onOpenCompany, onOpenChart, marketRows, tradeStats, favoriteTickers, onToggleFavorite, signedIn, hasProAccess = false, apiFetch = fetch, onUpgrade }) {
  const lang = normalizeLanguage(language);
  // A data-quality row can link an administrator directly to the affected
  // financial view. Normal company links carry no query and still open обзор.
  const companyQuery = new URLSearchParams(window.location.search);
  const qualityIssue = companyQuery.get("qualityIssue") || "";
  const qualityPeriod = companyQuery.get("qualityPeriod") || "";
  const qualityField = companyQuery.get("qualityField") || "";
  const requestedTab = companyQuery.get("tab");
  const [tab, setTab] = React.useState(requestedTab === "financials" ? "financials" : "overview");

  // A company is a new page, even though the SPA swaps it into the same
  // document. Reset the previous view's scroll offset before paint so opening
  // a row near the bottom of the market board still shows the company header.
  React.useLayoutEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [ticker]);
  // Issuer-level multiples, straight from the endpoint the market board reads.
  const [mult, setMult] = React.useState(null);
  // A twelve-month snapshot pinned for the 52-week rail. The initial 1Y metrics
  // response fills it, so opening the page does not issue the same call twice.
  const [metrics12, setMetrics12] = React.useState(null);
  const [priceHistory, setPriceHistory] = React.useState(null);
  // Non-empty only for a series that spans a split or a bonus issue — the chart has to
  // say the older prices were restated, or they read as wrong against uzse.uz.
  const [priceAdjustments, setPriceAdjustments] = React.useState([]);
  // Hourly bars from the exchange's executions log (/api/intraday) — what 1Д
  // draws and what 1Н mixes with daily closes. They stay lazy until one of
  // those ranges is selected; the default annual chart cannot use them.
  const [intraday, setIntraday] = React.useState(null);
  // The button's identity, not a month count: 1Н and 1М both fetch one month,
  // and YTD's month count moves through the year. `chartRangeMonths` turns it
  // into what the endpoint understands.
  const [priceRange, setPriceRange] = React.useState("1y");
  const priceMonths = chartRangeMonths(priceRange);
  // The chart initially shows `priceRange`, but Ctrl+wheel and dragging can
  // reveal the archive behind it. Fetch the same depth as «Макс» once per
  // issuer; metrics remain pinned to the selected range below.
  const priceArchiveMonths = chartRangeMonths("max");
  const [priceLoading, setPriceLoading] = React.useState(false);
  // Window + absolute price metrics from /api/company/{ticker}/metrics.
  const [metrics, setMetrics] = React.useState(null);
  const [secInfo, setSecInfo] = React.useState((securitiesMap || {})[ticker] || null);
  const [infoLoading, setInfoLoading] = React.useState(false);
  const [companyData, setCompanyData] = React.useState(null);
  // Legal and tax data is intentionally page-lazy. It is not included in the
  // market/catalog payloads and is requested only after this issuer route opens.
  const [registryData, setRegistryData] = React.useState(null);
  const [registryLoading, setRegistryLoading] = React.useState(true);
  const [registryError, setRegistryError] = React.useState(false);
  const [registryRetry, setRegistryRetry] = React.useState(0);
  const [dividends, setDividends] = React.useState(null);
  // The issuer's annual series (fact store). Lazy: only the Финансы tab
  // reads it, and most visits never open that tab.
  const [finSeries, setFinSeries] = React.useState(null);
  const [finLoading, setFinLoading] = React.useState(false);
  // IFRS and NSBU are separate accounting contours.  A form choice therefore
  // invalidates the cached series; retaining NSBU rows while the header says
  // IFRS would be worse than a temporary loading state.
  const [finStandard, setFinStandard] = React.useState("NSBU");
  const [finScope, setFinScope] = React.useState("");
  // The Финансы tab's period switch. The quarterly series is its own request
  // and its own cache: nobody pays for quarters they never open.
  const [finFreq, setFinFreq] = React.useState(companyQuery.get("freq") === "quarterly" ? "quarterly" : "annual");
  const [finQSeries, setFinQSeries] = React.useState(null);
  const [finQLoading, setFinQLoading] = React.useState(false);
  // The splits register for the «Сплиты» sub-tab. Lazy with the rest of the
  // Финансы data; null = not asked yet, [] = asked and the record is empty.
  const [splits, setSplits] = React.useState(null);
  const [divLoading, setDivLoading] = React.useState(false);

  // Failed requests must be visible and retryable: every fetch below reports
  // an error state instead of silently leaving the page blank, and an `alive`
  // guard keeps a late response for a previous ticker from overwriting state.
  const [priceError, setPriceError] = React.useState(false);
  const [priceRetry, setPriceRetry] = React.useState(0);
  const [companyDataError, setCompanyDataError] = React.useState(false);
  const [companyDataRetry, setCompanyDataRetry] = React.useState(0);
  const [insightReport, setInsightReport] = React.useState(null);
  const [insightLoading, setInsightLoading] = React.useState(true);
  const [insightDetailLoading, setInsightDetailLoading] = React.useState(false);
  const [insightError, setInsightError] = React.useState(false);
  const [insightRetry, setInsightRetry] = React.useState(0);
  const [insightOpen, setInsightOpen] = React.useState(false);
  const insightTriggerRef = React.useRef(null);
  const closeInsight = React.useCallback(() => {
    setInsightOpen(false);
    window.requestAnimationFrame(() => insightTriggerRef.current?.focus());
  }, []);
  const openInsight = React.useCallback(() => {
    // The Finam-style issuer analysis belongs to this company page.  The
    // report is loaded from the issuer endpoint below; opening it here avoids
    // falling through to the retired generic /analysis workspace.
    if (insightReport && !insightReport.deferred_full_report) {
      setInsightOpen(true);
    } else if (insightReport && !insightLoading && !insightDetailLoading) {
      setInsightDetailLoading(true);
      fetch(`/api/v1/issuers/${encodeURIComponent(ticker)}/ai-report?standard=nsbu&scope=separate&lang=${lang}`)
        .then(async (response) => {
          const body = await response.json().catch(() => null);
          if (!response.ok || !body?.ok || !body?.headline) throw new Error("company insight unavailable");
          return body;
        })
        .then((body) => {
          setInsightReport(body);
          setInsightOpen(true);
        })
        .catch(() => setInsightError(true))
        .finally(() => setInsightDetailLoading(false));
    } else if (!insightLoading && !insightDetailLoading) {
      setInsightRetry((value) => value + 1);
    }
  }, [insightReport, insightLoading, insightDetailLoading, ticker, lang]);

  // Every board row, reconciled against the stored day statistics exactly as the
  // market table does it — the watch rail quotes other securities and must quote
  // them the way the board does. Computed here, above the effects, because the
  // sparkline request is keyed on which tickers the rail will show.
  const preparedRows = React.useMemo(() => {
    return prepareMarketRows(marketRows, tradeStats);
  }, [marketRows, tradeStats]);
  const railTickers = React.useMemo(() => {
    const { favRows, bySector, movers } = watchRailLists({
      ticker, rows: preparedRows, securitiesMap, favorites: favoriteTickers,
    });
    return [...new Set([...favRows, ...bySector, ...movers]
      .map((r) => String(r.ticker || "").toUpperCase()))].sort();
  }, [ticker, preparedRows, securitiesMap, favoriteTickers]);

  // Быстрое сравнение: which securities the strip offers, which of them are on
  // the chart, and their stored closes. The selection is the reader's and is
  // dropped when the page changes issuer — carrying UZTL's peers onto KSCM's
  // chart would compare a set nobody chose.
  const comparePeers = React.useMemo(
    () => quickComparePeers({ ticker, rows: preparedRows, securitiesMap }),
    [ticker, preparedRows, securitiesMap],
  );
  const [compareTickers, setCompareTickers] = React.useState([]);
  const [compareSeries, setCompareSeries] = React.useState({});
  const [compareLoading, setCompareLoading] = React.useState(false);
  React.useEffect(() => { setCompareTickers([]); }, [ticker]);
  const toggleCompare = React.useCallback((tk) => {
    const up = String(tk || "").toUpperCase();
    setCompareTickers((cur) => (cur.includes(up)
      ? cur.filter((x) => x !== up)
      : cur.length >= QC_MAX ? cur : [...cur, up]));
  }, []);
  const clearCompare = React.useCallback(() => {
    setCompareTickers([]);
    setCompareLoading(false);
  }, []);
  // The same stored-close endpoint the watch rail's sparklines read — one
  // request for the whole selection, not one per line. `days` is a count of
  // SESSIONS, not calendar days, so ask for everything the store holds and let
  // the chart trim to the range on screen.
  const compareKey = [...compareTickers].sort().join(",");
  React.useEffect(() => {
    // Cleared while a request was in flight: the flag has to fall with the
    // selection, or the strip keeps saying «загрузка…» over an empty chart.
    if (!compareKey) { setCompareLoading(false); return undefined; }
    let alive = true;
    setCompareLoading(true);
    fetch(`/api/quotes/series?tickers=${encodeURIComponent(compareKey)}&days=3650`)
      .then((r) => r.json())
      // Merged, not replaced: adding a second security must not make the first
      // one's line blink out while the request is in flight.
      .then((d) => { if (alive && d && d.ok) setCompareSeries((s) => ({ ...s, ...(d.series || {}) })); })
      .catch(() => {})
      .finally(() => { if (alive) setCompareLoading(false); });
    return () => { alive = false; };
  }, [compareKey]);
  const compareLines = React.useMemo(() => compareTickers.map((tk, i) => ({
    ticker: tk,
    color: QC_COLORS[i % QC_COLORS.length],
    points: compareSeries[tk] || null,
  })), [compareTickers, compareSeries]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setPriceLoading(true);
    setPriceError(false);
    fetch(`/api/price-history/${encodeURIComponent(ticker)}?months=${priceArchiveMonths}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) {
          setPriceHistory(d.points || []);
          setPriceAdjustments(d.adjustments || []);
        } else setPriceError(true);
      })
      .catch(() => { if (alive) setPriceError(true); })
      .finally(() => { if (alive) setPriceLoading(false); });
    return () => { alive = false; };
  }, [ticker, priceArchiveMonths, priceRetry]);

  React.useEffect(() => {
    if (!ticker || !["1d", "1w"].includes(priceRange)) return undefined;
    let alive = true;
    setIntraday(null);
    // Failure degrades, never blocks: with no bars the 1Н button draws daily
    // closes exactly as before, and 1Д says the bank is still empty.
    fetch(`/api/intraday/${encodeURIComponent(ticker)}?days=8`)
      .then((r) => r.json())
      .then((d) => { if (alive) setIntraday(d.ok ? (d.points || []) : []); })
      .catch(() => { if (alive) setIntraday([]); });
    return () => { alive = false; };
  }, [ticker, priceRange]);

  // Metrics are the server's job (ТЗ §3, second principle: one calc layer, and
  // the screen is not one of its implementations). The page reads `quality`
  // — whether the security trades often enough to be drawn as a slope rather
  // than a step — `ma_windows`, and now the `window` block, which is what the
  // rail's «За период» states. Keyed on the RANGE, not on the month count: 1Н
  // and 1М both fetch one month of history but measure different windows.
  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/metrics?months=${priceMonths}${chartRangeWindowQuery(priceRange)}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        const next = d.ok ? d : null;
        setMetrics(next);
        // The initial range is already twelve months. Reuse this response for
        // the fixed 52-week rail instead of issuing the same request twice.
        if (priceRange === "1y") setMetrics12(next);
      })
      .catch(() => { if (alive) setMetrics(null); });
    return () => { alive = false; };
  }, [ticker, priceMonths, priceRange, priceRetry]);

  // Only a reader who changes range before the initial 1Y response finishes
  // needs a separate fixed-year snapshot.
  React.useEffect(() => {
    if (!ticker || metrics12 || priceRange === "1y") return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/metrics?months=12`)
      .then((r) => r.json())
      .then((d) => { if (alive) setMetrics12(d.ok ? d : null); })
      .catch(() => { if (alive) setMetrics12(null); });
    return () => { alive = false; };
  }, [ticker, metrics12, priceRange, priceRetry]);

  // Dividends are no longer lazy: the key-stats rail states the last payout and
  // its yield on the Обзор tab, so waiting for the Дивиденды tab to be opened
  // would leave the rail permanently short of the one figure an equity holder
  // opens the page for.
  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setDividends(null);
    setDivLoading(true);
    fetch(`/api/dividends/${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setDividends(d.ok ? (d.items || []) : []); })
      .catch(() => { if (alive) setDividends([]); })
      .finally(() => { if (alive) setDivLoading(false); });
    return () => { alive = false; };
  }, [ticker]);

  React.useEffect(() => {
    setFinSeries(null);
    setFinQSeries(null);
    setSplits(null);
  }, [ticker, finStandard, finScope]);
  React.useEffect(() => {
    if (!ticker || tab !== "financials" || finSeries !== null) return undefined;
    let alive = true;
    setFinLoading(true);
    fetch(`/api/company/${encodeURIComponent(ticker)}/financials?form=${encodeURIComponent(finStandard)}${finStandard === "MSFO" && finScope ? `&scope=${encodeURIComponent(finScope)}` : ""}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setFinSeries(d.ok ? d : { periods: [], series: {} }); })
      .catch(() => { if (alive) setFinSeries({ periods: [], series: {} }); })
      .finally(() => { if (alive) setFinLoading(false); });
    return () => { alive = false; };
  }, [ticker, tab, finStandard, finScope, finSeries]);
  React.useEffect(() => {
    if (!ticker || tab !== "financials" || finFreq !== "quarterly" || finQSeries !== null) return undefined;
    let alive = true;
    setFinQLoading(true);
    fetch(`/api/company/${encodeURIComponent(ticker)}/financials?freq=quarterly&form=${encodeURIComponent(finStandard)}${finStandard === "MSFO" && finScope ? `&scope=${encodeURIComponent(finScope)}` : ""}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setFinQSeries(d.ok ? d : { periods: [], series: {} }); })
      .catch(() => { if (alive) setFinQSeries({ periods: [], series: {} }); })
      .finally(() => { if (alive) setFinQLoading(false); });
    return () => { alive = false; };
  }, [ticker, tab, finStandard, finScope, finFreq, finQSeries]);
  // The splits register, once per ticker and only when the Финансы tab is
  // open — the same laziness as the series above. An error resolves to [],
  // which the table renders as the honest «не зафиксировано».
  React.useEffect(() => {
    if (!ticker || tab !== "financials" || splits !== null) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/splits`)
      .then((r) => r.json())
      .then((d) => { if (alive) setSplits(d.ok ? (d.items || []) : []); })
      .catch(() => { if (alive) setSplits([]); });
    return () => { alive = false; };
  }, [ticker, tab, splits]);

  // ТЗ §8: the server owns this arithmetic, per ISSUER, with the auditor's
  // blocking findings already applied. A failure leaves `mult` null and the rail
  // simply omits the valuation rows — it never falls back to computing them.
  React.useEffect(() => {
    let alive = true;
    fetch(`/api/market/multiples?ticker=${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const up = String(ticker || "").toUpperCase();
        setMult((d.items || []).find((it) => String(it.ticker || "").toUpperCase() === up) || null);
      })
      .catch(() => { if (alive) setMult(null); });
    return () => { alive = false; };
  }, [ticker]);

  // One request for every sparkline in the watch rail. Keyed on the ticker LIST,
  // so it refetches when the lists change and not when a price ticks — the whole
  // reason this data is stored rather than fetched per row is to keep a list of
  // securities from costing one upstream request each.
  const [railSeries, setRailSeries] = React.useState({});
  const railKey = railTickers.join(",");
  React.useEffect(() => {
    if (!railKey) return undefined;
    let alive = true;
    // Sparklines are decorative support for the peer rail. Let the issuer's
    // own chart, metrics and teaser take the first network slots.
    const timer = window.setTimeout(() => {
      fetch(`/api/quotes/series?tickers=${encodeURIComponent(railKey)}&days=30`)
        .then((r) => r.json())
        .then((d) => { if (alive && d && d.ok) setRailSeries(d.series || {}); })
        .catch(() => {});
    }, 700);
    return () => { alive = false; window.clearTimeout(timer); };
  }, [railKey]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    const local = (securitiesMap || {})[ticker];
    if (local) setSecInfo(local);
    setInfoLoading(true);
    fetch(`/api/securities/${encodeURIComponent(ticker)}/info?language=${lang}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d.ok) return;
        setSecInfo({
          ...(d.security || {}),
          company_description: d.wiki?.extract || d.security?.company_description || null,
          source_url: d.wiki?.page_url || d.security?.source_url || null,
          wiki_title: d.wiki?.title || null,
          info_source: d.wiki?.source || (d.wiki?.extract ? "wikipedia" : null),
        });
      })
      .catch(() => {})
      .finally(() => { if (alive) setInfoLoading(false); });
    return () => { alive = false; };
  }, [ticker, lang, securitiesMap]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setRegistryData(null);
    setRegistryLoading(true);
    setRegistryError(false);
    fetch(`/api/company/${encodeURIComponent(ticker)}/registry`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body?.ok || !body?.registry?.company) throw new Error("company registry unavailable");
        return body;
      })
      .then((body) => { if (alive) setRegistryData(body); })
      .catch(() => { if (alive) setRegistryError(true); })
      .finally(() => { if (alive) setRegistryLoading(false); });
    return () => { alive = false; };
  }, [ticker, registryRetry]);

  React.useEffect(() => {
    if (!ticker || !["reports", "financials"].includes(tab) || companyData) return undefined;
    let alive = true;
    setCompanyDataError(false);
    fetch(`/api/catalog/company/${encodeURIComponent(ticker)}/reports`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) setCompanyData(d);
        else setCompanyDataError(true);
      })
      .catch(() => { if (alive) setCompanyDataError(true); });
    return () => { alive = false; };
  }, [ticker, tab, companyData, companyDataRetry]);

  // Fetch only the compact, traceable teaser for the page itself. The full
  // sector report stays deferred until the reader presses «Подробнее».
  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setInsightLoading(true);
    setInsightError(false);
    setInsightReport(null);
    setInsightOpen(false);
    fetch(`/api/v1/issuers/${encodeURIComponent(ticker)}/ai-report?standard=nsbu&scope=separate&lang=${lang}&summary=true`)
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body?.ok || !body?.headline) throw new Error("company insight unavailable");
        return body;
      })
      .then((body) => { if (alive) setInsightReport(body); })
      .catch(() => { if (alive) setInsightError(true); })
      .finally(() => { if (alive) setInsightLoading(false); });
    return () => { alive = false; };
  }, [ticker, lang, insightRetry]);

  if (!ticker) return null;
  const sec = secInfo || (securitiesMap || {})[ticker] || {};
  // The header's own row. It used to derive its move as a bare
  // `last_price - close_price`, which is the two-sessions-in-one-day defect
  // previousClose() exists to prevent — see applyTradeStats.
  const marketRow = preparedRows.find((r) => (r.ticker || "").toUpperCase() === ticker.toUpperCase()) || null;
  // Company-level financials for P/E and P/B; mirror the preferred-sibling fallback (TKDM <-> TKDMP).
  // A zero is not a quote: the board mirror fills never-traded listings (MXUS)
  // with literal 0s, and the header was announcing «0 сум» as if it were a price.
  const posPrice = (v) => (Number.isFinite(v) && v > 0 ? v : null);
  const lastPrice = posPrice(marketRow?.lastPrice) ?? posPrice(marketRow?.last_price) ?? posPrice(sec.last_price) ?? null;
  // The move the reconciled row settled on. Only when there is no board row at
  // all does the header fall back to differencing the securities-map closes —
  // and then it has no session to check them against, so it says nothing rather
  // than publishing a difference between two undated prices.
  const priceChange = marketRow
    ? (Number.isFinite(marketRow.changeValue) && Number.isFinite(marketRow.changePercent)
        ? { value: marketRow.changeValue, pct: marketRow.changePercent }
        : null)
    : null;
  // The securities map uses `type`/`share_type`/`is_preferred`/`sector`; some
  // callers pass `security_type`/`stock_type`/`industry`. Accept both shapes.
  const securityType = sec.security_type || sec.type;
  const isPreferred = sec.stock_type === "preferred" || sec.share_type === "preferred" || sec.is_preferred === true;
  const industry = sec.industry || sec.sector;
  const typeLabel = securityType === "bond"
    ? (lang === "ru" ? "Облигация" : lang === "uz" ? "Obligatsiya" : "Bond")
    : isPreferred
      ? (lang === "ru" ? "Прив. акция" : lang === "uz" ? "Imtiyozli" : "Preferred")
      : (lang === "ru" ? "Обыкн. акция" : lang === "uz" ? "Oddiy aksiya" : "Common Share");
  // The feed names only some preferred listings «(привилегированные)» — KFSKP,
  // FRAZP, IPKYP, PLSTP and UPOSP arrive without the suffix while HMKBP and
  // IPTBP carry it. One rule for every header, not the feed's mood.
  const baseName = sec.company_name || sec.name || ticker;
  const displayName = isPreferred && securityType !== "bond" && !/привилегирован/i.test(baseName)
    ? `${baseName} (привилегированные)`
    : baseName;
  const TABS = [
    { key: "overview", label: lang === "ru" ? "Обзор" : lang === "uz" ? "Umumiy" : "Overview" },
    { key: "chart", label: lang === "ru" ? "История цен" : lang === "uz" ? "Narxlar tarixi" : "Price History" },
    ...(securityType !== "bond" ? [{ key: "dividends", label: lang === "ru" ? "Дивиденды" : lang === "uz" ? "Dividendlar" : "Dividends" }] : []),
    { key: "reports", label: lang === "ru" ? "Отчёты" : lang === "uz" ? "Hisobotlar" : "Reports" },
    { key: "financials", label: lang === "ru" ? "Финансы" : lang === "uz" ? "Moliya" : "Financials" },
  ];
  return (
    <div className="company-page">
      <div className="company-page-header">
        <button className="company-page-back" type="button" onClick={onBack}>
          ← {lang === "ru" ? "Назад" : lang === "uz" ? "Orqaga" : "Back"}
        </button>
        <div className="company-page-hero">
          <CompanyLogo logo={sec.company_logo_url || sec.logo_url} name={baseName} ticker={ticker} />
          <div className="company-page-title">
            <h1>{displayName}</h1>
            <div className="company-page-meta">
              <span className="company-page-ticker">{ticker}</span>
              {sec.isin && <span className="muted" style={{ fontSize: 12 }}>{sec.isin}</span>}
              <span className="company-type-badge">{typeLabel}</span>
              {industry && <span className="sector-chip active" style={{ fontSize: 11, padding: "2px 10px" }}>{sectorLabel(lang, industry)}</span>}
            </div>
          </div>
          <div className="company-page-price">
            {lastPrice != null ? (
              <>
                <div className="company-page-price-val">{Number(lastPrice).toLocaleString("ru-RU")} сум</div>
                {priceChange && (
                  <div className={`company-page-price-change ${priceChange.value >= 0 ? "pos" : "neg"}`}>
                    {signedFixed(priceChange.value)} ({signedFixed(priceChange.pct)}%)
                  </div>
                )}
              </>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>{lang === "ru" ? "Нет данных" : "No data"}</div>
            )}
            <button className="primary-btn" type="button" style={{ marginTop: 8 }} onClick={openInsight} disabled={insightLoading || insightDetailLoading}>
              {insightLoading || insightDetailLoading
                ? (lang === "ru" ? "Загрузка анализа…" : lang === "uz" ? "Tahlil yuklanmoqda…" : "Loading analysis…")
                : (lang === "ru" ? "Открыть анализ" : lang === "uz" ? "Tahlilni ochish" : "Open Analysis")}
            </button>
          </div>
        </div>
        <div className="company-page-tabs">
          {TABS.map((t) => (
            <button key={t.key} type="button"
              className={`company-tab-btn ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="company-page-body">
        {tab === "overview" && (
          <CompanyInsightCard
            report={insightReport}
            loading={insightLoading}
            error={insightError}
            onOpen={openInsight}
            onRetry={() => setInsightRetry((value) => value + 1)}
            buttonRef={insightTriggerRef}
            lang={lang}
          />
        )}
        {companyDataError && (
          <div className="panel" style={{ padding: "12px 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: "1px solid rgba(220, 80, 80, 0.5)" }}>
            <span style={{ fontSize: 13 }}>
              {lang === "ru" ? "Не удалось загрузить отчёты и показатели компании."
                : lang === "uz" ? "Kompaniya hisobotlari va ko'rsatkichlarini yuklab bo'lmadi."
                : "Failed to load company reports and metrics."}
            </span>
            <button className="primary-btn" type="button" style={{ padding: "6px 14px", fontSize: 13 }}
              onClick={() => setCompanyDataRetry((n) => n + 1)}>
              {lang === "ru" ? "Повторить" : lang === "uz" ? "Qayta urinish" : "Retry"}
            </button>
          </div>
        )}
        {priceError && (tab === "overview" || tab === "chart") && (
          <div className="panel" style={{ padding: "12px 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: "1px solid rgba(220, 80, 80, 0.5)" }}>
            <span style={{ fontSize: 13 }}>
              {lang === "ru" ? "Не удалось загрузить историю цен."
                : lang === "uz" ? "Narxlar tarixini yuklab bo'lmadi."
                : "Failed to load price history."}
            </span>
            <button className="primary-btn" type="button" style={{ padding: "6px 14px", fontSize: 13 }}
              onClick={() => setPriceRetry((n) => n + 1)}>
              {lang === "ru" ? "Повторить" : lang === "uz" ? "Qayta urinish" : "Retry"}
            </button>
          </div>
        )}
        {tab === "overview" && (
          <CompanyOverviewTab sec={sec} ticker={ticker} priceHistory={priceHistory} priceLoading={priceLoading}
            priceAdjustments={priceAdjustments} intraday={intraday}
            compare={{
              peers: comparePeers, securitiesMap, selected: compareTickers,
              onToggle: toggleCompare, onClear: clearCompare,
              series: compareLines, loading: compareLoading,
            }}
            onExpandChart={onOpenChart
              ? () => onOpenChart(ticker, { range: priceRange,
                                            type: "line", compare: compareTickers,
                                            indicators: [], fin: [], from: "", to: "" })
              : null}
            priceRange={priceRange} onRangeChange={setPriceRange}
            securityType={securityType} isPreferred={isPreferred} industry={industry}
            marketRow={marketRow} lang={lang} infoLoading={infoLoading}
            registryData={registryData} registryLoading={registryLoading} registryError={registryError}
            onRegistryRetry={() => setRegistryRetry((value) => value + 1)}
            priceMetrics={metrics}
            metrics12={metrics12} mult={mult} dividends={dividends} lastPrice={lastPrice}
            watchRail={
              <CompanyWatchRail ticker={ticker} rows={preparedRows} securitiesMap={securitiesMap}
                series={railSeries} favorites={favoriteTickers} onToggleFavorite={onToggleFavorite}
                onOpen={onOpenCompany} signedIn={signedIn} lang={lang} />
            } />
        )}
        {tab === "chart" && (
          <div className="panel" style={{ padding: 24 }}>
            <h3 className="section-heading" style={{ marginBottom: 16 }}>{lang === "ru" ? `История цен — ${ticker}` : `Price History — ${ticker}`}</h3>
            <CompanyPriceChart history={priceHistory} loading={priceLoading} range={priceRange} onRangeChange={setPriceRange} lang={lang}
              intraday={intraday} quality={metrics?.quality} metricsWindows={metrics?.ma_windows}
              ticker={ticker} compare={compareLines} compareLoading={compareLoading}
              compareTools={{ peers: comparePeers, securitiesMap, selected: compareTickers,
                              onToggle: toggleCompare, onClear: clearCompare }}
              onExpand={onOpenChart
                ? () => onOpenChart(ticker, { range: priceRange,
                                              type: "line", compare: compareTickers,
                                              indicators: [], fin: [], from: "", to: "" })
                : null} />
            <QuickCompareStrip peers={comparePeers} securitiesMap={securitiesMap}
              selected={compareTickers} colors={QC_COLORS} onToggle={toggleCompare}
              lang={lang} loading={compareLoading} />
          </div>
        )}
        {tab === "dividends" && (
          <CompanyDividendsTab items={dividends} loading={divLoading} lang={lang} isPreferred={isPreferred} lastPrice={lastPrice} />
        )}
        {tab === "reports" && (
          <CompanyReportsTab reports={companyData?.reports || []} lang={lang} />
        )}
        {tab === "financials" && (
          <>
            {qualityIssue && <div className="panel" style={{ padding: "12px 16px", marginBottom: 12, border: "1px solid rgba(220, 80, 80, 0.5)" }}>
              <strong>{lang === "ru" ? "Административная проверка" : lang === "uz" ? "Ma'muriy tekshiruv" : "Administrative review"}: {qualityIssue}</strong>
              <span className="muted" style={{ marginLeft: 8 }}>{[qualityPeriod, qualityField].filter(Boolean).join(" · ")}</span>
            </div>}
            <CompanyFinancialsTab ticker={ticker} ratios={companyData?.ratios || {}} lang={lang}
              key={`${ticker}:${finStandard}:${finScope}:${finFreq}`}
              standard={finStandard} onStandardChange={setFinStandard}
              scope={finScope || (finFreq === "quarterly" ? finQSeries?.scope : finSeries?.scope)}
              onScopeChange={(value) => { setFinScope(value); setFinSeries(null); setFinQSeries(null); }}
              series={(finFreq === "quarterly" ? finQSeries?.series : finSeries?.series) || {}}
              periods={(finFreq === "quarterly" ? finQSeries?.periods : finSeries?.periods) || []}
              dataGaps={(finFreq === "quarterly" ? finQSeries?.data_gaps : finSeries?.data_gaps) || []}
              periodBasis={finFreq === "quarterly" ? finQSeries?.period_basis : finSeries?.period_basis}
              loading={finFreq === "quarterly"
                ? (finQLoading && finQSeries === null)
                : (finLoading && finSeries === null)}
              freq={finFreq} onFreqChange={setFinFreq} splits={splits} />
          </>
        )}
        {insightOpen && insightReport && (
          <CompanyInsightDialog report={insightReport} ticker={ticker} companyName={displayName} lang={lang} onClose={closeInsight} />
        )}
      </div>
    </div>
  );
}

export { CompanyPage };
