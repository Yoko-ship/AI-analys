import React, { useEffect, useState } from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { orderSectors, sectorOf } from "../../lib/sectors.js";
import { formatMarketNumber, formatRatio } from "../../shared/format.jsx";
import { marketDisplayPrice } from "../../shared/marketModel.jsx";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { marketVolumeMetrics } from "../../lib/marketVolume.js";
import { formatMapMetric, HeatmapMetricPicker, mapMetricCoverage, useHeatmapMetrics } from "./HeatmapMetrics.jsx";

// How far a move has to go before the tile is fully saturated, per period. A
// session's 5 % is a big day; six months' 5 % is nothing, and drawing a half-year
// on the session's scale paints almost every tile the same flat green — a picture
// with no information left in it. The legend is built from the same number, so
// the swatches and the tiles can never describe different scales.
const HEATMAP_FULL_SCALE = { "1d": 5, "1w": 10, "1m": 20, "3m": 35, "6m": 50, "1y": 75, ytd: 75 };

const heatmapFullScale = (period) => HEATMAP_FULL_SCALE[period] || 5;

function heatmapColor(changePercent, full = 5, muted = false) {
  if (changePercent === null || !Number.isFinite(changePercent)) return muted ? "#313844" : "#3b4451";
  const span = Number.isFinite(full) && full > 0 ? full : 5;
  const dead = span / 50;
  const abs = Math.abs(changePercent);
  const intensity = Math.min(abs / span, 1);
  if (changePercent > dead) {
    const lightness = (muted ? 23 : 28) + intensity * (muted ? 11 : 15);
    return `hsl(${164 - intensity * 6} ${muted ? 48 : 66}% ${lightness}%)`;
  }
  if (changePercent < -dead) {
    const lightness = (muted ? 25 : 29) + intensity * (muted ? 10 : 14);
    return `hsl(${352 + intensity * 14} ${muted ? 50 : 70}% ${lightness}%)`;
  }
  return muted ? "#323a45" : "#46505d";
}

function heatmapShortName(name) {
  if (!name) return "";
  // Extract content inside quotes: "Hamkorbank" ATB → Hamkorbank
  const m = name.match(/["""«»]([^"""«»]+)["""«»]/);
  const base = m ? m[1] : name.replace(/\s+(AJ|ATB|MK|OAJ|XK)\b.*/i, "").trim();
  return base.length > 13 ? base.slice(0, 12) + "…" : base;
}

// Bruls/Huizing/van Wijk squarified treemap. Every returned rectangle keeps
// its item's exact proportional area while avoiding unreadable long slivers.
function heatmapWorst(row, length) {
  const sum = row.reduce((total, item) => total + item.area, 0);
  if (sum <= 0) return Infinity;
  let max = -Infinity;
  let min = Infinity;
  row.forEach((item) => {
    max = Math.max(max, item.area);
    min = Math.min(min, item.area);
  });
  const sumSquared = sum * sum;
  const lengthSquared = length * length;
  return Math.max((lengthSquared * max) / sumSquared, sumSquared / (lengthSquared * min));
}

function squarifyTreemap(items, x, y, width, height) {
  const output = [];
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (total <= 0 || width <= 0 || height <= 0) return output;
  const scale = (width * height) / total;
  const data = items.map((item) => ({ ...item, area: item.value * scale }));
  let rect = { x, y, w: width, h: height };
  let index = 0;
  while (index < data.length) {
    const length = Math.min(rect.w, rect.h);
    let row = [data[index]];
    let next = index + 1;
    while (next < data.length) {
      const candidate = row.concat(data[next]);
      if (heatmapWorst(candidate, length) <= heatmapWorst(row, length)) {
        row = candidate;
        next += 1;
      } else break;
    }
    const rowArea = row.reduce((sum, item) => sum + item.area, 0);
    if (rect.w <= rect.h) {
      const rowHeight = rowArea / rect.w;
      let cursorX = rect.x;
      row.forEach((item) => {
        const itemWidth = item.area / rowHeight;
        output.push({ ...item, x: cursorX, y: rect.y, w: itemWidth, h: rowHeight });
        cursorX += itemWidth;
      });
      rect = { x: rect.x, y: rect.y + rowHeight, w: rect.w, h: rect.h - rowHeight };
    } else {
      const rowWidth = rowArea / rect.h;
      let cursorY = rect.y;
      row.forEach((item) => {
        const itemHeight = item.area / rowWidth;
        output.push({ ...item, x: rect.x, y: cursorY, w: rowWidth, h: itemHeight });
        cursorY += itemHeight;
      });
      rect = { x: rect.x + rowWidth, y: rect.y, w: rect.w - rowWidth, h: rect.h };
    }
    index = next;
  }
  return output;
}

function MarketHeatmap({ rows, companies, securitiesMap, language, onAnalyze, onOpenCompany, type, mapData, stats, period = "1d" }) {
  // Which question the map is drawing. Over a window every cell's colour is the
  // change over it and its bottom meter is the turnover over it — the caller
  // has already restated the rows (see `mapRows`), so the board arithmetic
  // below needs no special case. What does need one is everything the SERVER
  // said about today; see `tileStatus`.
  const windowed = period !== "1d";
  const fullScale = heatmapFullScale(period);
  // Per-tile classification from /api/heatmap (ТЗ §9). The server decides what a
  // tile IS — priced, traded-but-unpriced, dormant, or resting on a single trade
  // — because the same judgement has to hold for the aggregates it also returns.
  const tileMeta = React.useMemo(() => {
    const by = new Map();
    (mapData?.tiles || []).forEach((t) => by.set(String(t.ticker || "").toUpperCase(), t));
    return by;
  }, [mapData]);
  const metaOf = (r) => tileMeta.get(String(r?.ticker || "").toUpperCase()) || null;
  const tileStatus = (r) => {
    // The server's classification answers «did this trade TODAY», and over a
    // window the map is not drawing today: a security that sat out this morning
    // but moved 30 % since May is not a «не торговалась» grey square. A window's
    // own test is simply whether the stored closes reach back far enough to
    // measure it — the same test the «Изм. 1М» column applies.
    if (windowed) return Number.isFinite(r?.changePercent) ? "ok" : "not_traded";
    const meta = metaOf(r);
    if (meta) return meta.status;
    // Before the response lands, fall back to the same rule the server applies.
    if (!Number.isFinite(r?.changePercent)) return r?.inactive ? "inactive" : "not_traded";
    return "ok";
  };
  // «Rests on fewer than five trades» is a statement about one session. A month
  // of sessions is not low-confidence because this morning was thin.
  const lowConfidence = (r) => !windowed && metaOf(r)?.confidence === "low";
  const lang = normalizeLanguage(language);
  const [hover, setHover] = useState(null);
  const [selectedTicker, setSelectedTicker] = useState("");
  const metricSelection = useHeatmapMetrics(lang, type);
  const selectedMetrics = metricSelection.selected;
  const treeRef = React.useRef(null);
  const [treeSize, setTreeSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    const element = treeRef.current;
    if (!element) return undefined;
    const measure = () => setTreeSize({ w: element.clientWidth, h: element.clientHeight });
    measure();
    let observer;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(measure);
      observer.observe(element);
    } else window.addEventListener("resize", measure);
    return () => {
      if (observer) observer.disconnect();
      else window.removeEventListener("resize", measure);
    };
  }, []);

  const companyMap = {};
  (companies || []).forEach((c) => { companyMap[c.ticker] = c; });
  // Sector membership comes from lib/sectors.js — the same call the Рынок filter
  // bar makes, so a ticker cannot be Фонды in the table and Прочее on the map.
  const sectorKeyOf = (t) => sectorOf(t, securitiesMap, companyMap);
  const isPreferredRow = (row) =>
    securitiesMap?.[row.ticker]?.is_preferred === true ||
    securitiesMap?.[row.ticker]?.share_type === "preferred" ||
    row.share_type === "preferred";

  // Every listed instrument stays on the map: instruments that traded today are
  // colored by their change, while inactive registry listings and tickers
  // without a price change render as small NEUTRAL (grey, "—") tiles instead of
  // disappearing entirely. Bonds are excluded on the stock-focused views
  // (Акции and its subtypes) but shown when the user picks the Bonds segment.
  const isBond = (row) => row.type === "bond" || securitiesMap?.[row.ticker]?.type === "bond";
  const allowBonds = type === "bond";
  const isNeutralRow = (row) => row.inactive === true || !Number.isFinite(row.changePercent);
  const tradedRows = (Array.isArray(rows) ? rows : []).filter((row) => allowBonds || !isBond(row));

  // A request failure used to leave this panel as a featureless dark rectangle.
  // Say plainly when the market-board request has not produced any rows instead
  // of making a missing response look like a blank exchange session.
  if (tradedRows.length === 0) {
    const message = lang === "uz"
      ? "Bozor xaritasini chizish uchun ma'lumot hozircha mavjud emas. Sahifani yangilang."
      : lang === "en"
        ? "Market data is not available to draw the map yet. Refresh the page to try again."
        : "Пока нет данных, чтобы построить карту рынка. Обновите страницу и попробуйте ещё раз.";
    return <p className="market-empty-cell heatmap-empty-state" role="status">{message}</p>;
  }

  // Area answers the same question as colour: how strongly did this security
  // move over the selected period? Direction belongs to colour; magnitude
  // (absolute percentage change) belongs to area. A 0% or unavailable name gets
  // only a tiny floor so it remains discoverable without competing visually
  // with securities that actually moved.
  const movementValue = (row) => (
    tileStatus(row) === "ok" && Number.isFinite(row.changePercent)
      ? Math.abs(row.changePercent)
      : 0
  );
  const maxMovementValue = Math.max(0, ...tradedRows.map(movementValue));
  const movementFloor = maxMovementValue > 0 ? maxMovementValue * 0.002 : 1;
  const tileWeight = (row) => Math.max(
    movementValue(row),
    movementFloor * (isNeutralRow(row) ? 0.65 : 1)
  );

  const formatPct = (pct) => {
    if (pct === null || !Number.isFinite(pct)) return "—";
    return `${pct > 0 ? "+" : ""}${formatRatio(pct, 2, lang)}%`;
  };
  // ТЗ §9: a group moves by TURNOVER, not by headcount. A simple mean gave a
  // security that traded one share the same say as one that traded 98.4 mn on
  // 860 trades, so the sector reported a move nobody could have made. Tiles
  // without a real price never vote — they are not "unchanged".
  const avgOf = (rs) => {
    const counted = rs.filter((r) => Number.isFinite(r.changePercent)
      && tileStatus(r) === "ok");
    if (!counted.length) return null;
    const weight = counted.reduce((s, r) => s + (Number.isFinite(r.stockVolume) ? r.stockVolume : 0), 0);
    if (weight > 0) {
      return counted.reduce((s, r) => s + r.changePercent * (r.stockVolume || 0), 0) / weight;
    }
    return counted.reduce((a, r) => a + r.changePercent, 0) / counted.length;
  };
  // How many tiles actually entered that number, out of how many are shown —
  // ТЗ §9 requires the count to travel with the aggregate.
  const countedOf = (rs) => ({
    counted: rs.filter((r) => Number.isFinite(r.changePercent) && tileStatus(r) === "ok").length,
    total: rs.length,
  });

  const rowsBySector = {};
  tradedRows.forEach((row) => { (rowsBySector[sectorKeyOf(row.ticker)] ||= []).push(row); });
  const sectorItems = orderSectors(Object.keys(rowsBySector)).map((sector) => {
    const sectorRows = rowsBySector[sector].slice().sort((a, b) => tileWeight(b) - tileWeight(a));
    return {
      sector,
      rows: sectorRows,
      value: sectorRows.reduce((sum, row) => sum + tileWeight(row), 0),
    };
  }).sort((a, b) => b.value - a.value);
  const sectorRects = squarifyTreemap(sectorItems, 0, 0, treeSize.w, treeSize.h);
  const sectorLayout = sectorRects.map((sectorRect) => {
    const showHeader = sectorRect.w > 86 && sectorRect.h > 54;
    const headerHeight = showHeader ? 26 : 0;
    const stocks = squarifyTreemap(
      sectorRect.rows.map((row) => ({ row, value: tileWeight(row) })),
      sectorRect.x,
      sectorRect.y + headerHeight,
      sectorRect.w,
      Math.max(0, sectorRect.h - headerHeight)
    );
    return { ...sectorRect, showHeader, headerHeight, stocks };
  });
  const TREEMAP_GAP = 4;

  // Drawn from the period's own scale, never from a fixed ±5 %: a legend that
  // says «≥ +5%» over a picture where the saturation point is 50 % is not a key,
  // it is a wrong caption. The stops sit just past saturation and at two fifths
  // of it, which is exactly where the session's ±5,5/±2 always were.
  const mid = fullScale * 0.4;
  const LEGEND_STOPS = [
    { pct: -fullScale * 1.1, label: `≤ −${formatRatio(fullScale, 0, lang)}%` },
    { pct: -mid,             label: `−${formatRatio(mid, 0, lang)}%` },
    { pct: 0,                label: "0" },
    { pct: mid,              label: `+${formatRatio(mid, 0, lang)}%` },
    { pct: fullScale * 1.1,  label: `≥ +${formatRatio(fullScale, 0, lang)}%` },
  ];

  const marketAverage = avgOf(tradedRows);
  const flatBand = fullScale / 50;
  const signalRows = tradedRows.filter((row) => Number.isFinite(row.changePercent) && tileStatus(row) === "ok");
  const rising = signalRows.filter((row) => row.changePercent > flatBand).length;
  const falling = signalRows.filter((row) => row.changePercent < -flatBand).length;
  const flat = Math.max(0, signalRows.length - rising - falling);
  const unavailable = Math.max(0, tradedRows.length - signalRows.length);
  const breadthTotal = Math.max(1, rising + falling + flat + unavailable);
  const mapCopy = lang === "ru"
    ? { pulse: "Пульс рынка", weighted: "взвешено по обороту", up: "Рост", down: "Снижение", flat: "Без изменения", noData: "Без данных", scale: "Изменение цены", area: "Площадь", movement: "Сила движения", securities: "бумаг", board: "Тепловая карта рынка", sectors: "Сектора", price: "Цена", turnover: "Оборот", focus: "В фокусе", mainMove: "Главное движение", open: "Нажмите, чтобы открыть компанию", preferred: "Привилегированная акция" }
    : lang === "uz"
      ? { pulse: "Bozor pulsi", weighted: "aylanma bo'yicha", up: "O'sish", down: "Pasayish", flat: "O'zgarishsiz", noData: "Ma'lumotsiz", scale: "Narx o'zgarishi", area: "Maydon", movement: "Harakat kuchi", securities: "qog'oz", board: "Bozor issiqlik xaritasi", sectors: "Sektorlar", price: "Narx", turnover: "Aylanma", focus: "Tanlangan", mainMove: "Asosiy harakat", open: "Kompaniyani ochish uchun bosing", preferred: "Imtiyozli aksiya" }
      : { pulse: "Market pulse", weighted: "turnover weighted", up: "Up", down: "Down", flat: "Unchanged", noData: "No data", scale: "Price change", area: "Area", movement: "Move magnitude", securities: "securities", board: "Market heatmap", sectors: "Sectors", price: "Price", turnover: "Turnover", focus: "In focus", mainMove: "Largest move", open: "Click to open company", preferred: "Preferred share" };
  const mainMover = signalRows.reduce((best, row) => (
    !best || Math.abs(row.changePercent) > Math.abs(best.changePercent) ? row : best
  ), null);
  // Resolve from current rows so changing the period never leaves stale values.
  const focusRow = tradedRows.find((row) => row.ticker === hover?.ticker)
    || tradedRows.find((row) => row.ticker === selectedTicker) || mainMover || tradedRows[0] || null;
  const focusMetrics = marketVolumeMetrics(focusRow, stats);
  const focusStatus = focusRow ? tileStatus(focusRow) : null;
  const focusPrice = focusRow ? marketDisplayPrice(focusRow) : null;
  const focusName = focusRow
    ? focusRow.name || companyMap[focusRow.ticker]?.company_name || focusRow.ticker
    : null;

  return (
    <div className="heatmap-wrap">
      <div className="heatmap-overview">
        <div className="heatmap-pulse">
          <span className="heatmap-overview-kicker">{mapCopy.pulse}</span>
          <div className="heatmap-pulse-main">
            <strong className={`tone-${marketAverage > flatBand ? "good" : marketAverage < -flatBand ? "danger" : "neutral"}`}>
              {formatPct(marketAverage)}
            </strong>
            <span>{mapCopy.weighted}</span>
          </div>
        </div>

        <div className="heatmap-breadth" aria-label={`${mapCopy.up}: ${rising}; ${mapCopy.down}: ${falling}; ${mapCopy.flat}: ${flat}`}>
          <div className="heatmap-breadth-track" aria-hidden="true">
            <span className="is-up" style={{ width: `${(rising / breadthTotal) * 100}%` }} />
            <span className="is-flat" style={{ width: `${(flat / breadthTotal) * 100}%` }} />
            <span className="is-down" style={{ width: `${(falling / breadthTotal) * 100}%` }} />
            <span className="is-missing" style={{ width: `${(unavailable / breadthTotal) * 100}%` }} />
          </div>
          <div className="heatmap-breadth-values">
            <span className="is-up"><i />{mapCopy.up} <b>{rising}</b></span>
            <span className="is-flat"><i />{mapCopy.flat} <b>{flat}</b></span>
            <span className="is-down"><i />{mapCopy.down} <b>{falling}</b></span>
            {unavailable > 0 && <span className="is-missing"><i />{mapCopy.noData} <b>{unavailable}</b></span>}
          </div>
        </div>

        <div className="heatmap-legend">
          <div className="heatmap-legend-head">
            <span>{mapCopy.scale}</span>
            <span className="heatmap-area-note" aria-label={`${mapCopy.area}: ${mapCopy.movement}`}>
              <small>{mapCopy.area}</small>
              <b>|%|</b>
              <span>{mapCopy.movement}</span>
            </span>
          </div>
          <div className="heatmap-legend-gradient" aria-hidden="true" />
          <div className="heatmap-legend-labels">
            {LEGEND_STOPS.map(({ label }) => <span key={label}>{label}</span>)}
          </div>
        </div>
      </div>

      <div className="heatmap-metrics-toolbar">
        <HeatmapMetricPicker lang={lang} {...metricSelection} />
        <label className="heatmap-security-picker">
          {lang === "ru" ? "Бумага на карте" : lang === "uz" ? "Xaritadagi qog'oz" : "Security on map"}
          <select value={focusRow?.ticker || ""} onChange={(event) => { setSelectedTicker(event.target.value); setHover(null); }}>
            {tradedRows.map((row) => <option key={row.ticker} value={row.ticker}>{row.ticker}</option>)}
          </select>
        </label>
      </div>

      {focusRow && (
        <button
          className="heatmap-focus-strip"
          type="button"
          onClick={() => (onOpenCompany ? onOpenCompany(focusRow.ticker) : onAnalyze(focusRow.ticker))}
          aria-live="polite"
        >
          <span className="heatmap-focus-signal" style={{ background: focusStatus === "ok" ? heatmapColor(focusRow.changePercent, fullScale) : undefined }} />
          <span className="heatmap-focus-identity">
            <small>{hover || selectedTicker === focusRow.ticker ? mapCopy.focus : mapCopy.mainMove}</small>
            <span>
              <strong>{focusRow.ticker}</strong>
              <b className={`tone-${focusRow.changePercent > flatBand ? "good" : focusRow.changePercent < -flatBand ? "danger" : "neutral"}`}>
                {focusStatus === "ok" ? formatPct(focusRow.changePercent) : "—"}
              </b>
            </span>
            <em>{focusName}</em>
          </span>
          <span className="heatmap-focus-facts">
            <span><small>{mapCopy.price}</small><strong>{focusPrice != null ? `${formatMarketNumber(focusPrice, lang)} UZS` : "—"}</strong></span>
            <span><small>{mapCopy.sectors}</small><strong>{sectorLabel(lang, sectorKeyOf(focusRow.ticker))}</strong></span>
          </span>
          <span className="heatmap-focus-open">{type === "bond"
            ? lang === "ru" ? "Нажмите, чтобы открыть выпуск" : lang === "uz" ? "Chiqarilishni ochish uchun bosing" : "Click to open bond"
            : mapCopy.open}<b>↗</b></span>
        </button>
      )}

      {focusRow && selectedMetrics.length > 0 && <div className="heatmap-metric-details" aria-live="polite" data-ticker={focusRow.ticker}>
        {selectedMetrics.map(({ key, label }) => <div key={key} data-metric={key}>
          <small>{label}</small><strong>{formatMapMetric(key, focusMetrics[key], lang)}</strong>
          {windowed && mapMetricCoverage(focusRow, key, lang) && <small className="heatmap-metric-note">{mapMetricCoverage(focusRow, key, lang)}</small>}
        </div>)}
      </div>}

      <div className="heatmap-tree" ref={treeRef} role="group" aria-label={mapCopy.board}>
        {sectorLayout.map((sector) => {
          const sectorRows = sector.stocks.map((stock) => stock.row);
          const sectorAverage = avgOf(sectorRows);
          const sectorTally = countedOf(sectorRows);
          return (
            <React.Fragment key={sector.sector}>
              {sector.showHeader && (
                <div
                  className="heatmap-tree-label"
                  style={{ left: sector.x, top: sector.y, width: sector.w, height: sector.headerHeight }}
                >
                  <span>{sectorLabel(lang, sector.sector)}</span>
                  <strong className={`tone-${sectorAverage > flatBand ? "good" : sectorAverage < -flatBand ? "danger" : "neutral"}`}>
                    {formatPct(sectorAverage)}
                  </strong>
                  <small>{sectorTally.total}</small>
                </div>
              )}
              {sector.stocks.map((stock) => {
                const row = stock.row;
                const status = tileStatus(row);
                const companyName = row.name || companyMap[row.ticker]?.company_name || row.ticker;
                const tileGap = Math.min(TREEMAP_GAP, stock.w * 0.35, stock.h * 0.35);
                const width = stock.w - tileGap;
                const height = stock.h - tileGap;
                if (width <= 0 || height <= 0) return null;
                const tickerSize = Math.max(8, Math.min(Math.min(width, height) / 3.1, width / 4.7, 21));
                // A ticker or status badge clipped into a movement-floor cell
                // becomes a meaningless dot. Micro tiles keep only their fill;
                // the full accessible label and the focus strip still expose
                // every security on hover, focus and click.
                const tickerMinWidth = Math.max(34, row.ticker.length * 5 + 12);
                const showTicker = width >= tickerMinWidth && height >= 24;
                const showPercent = width >= 58 && height >= 40;
                const showName = width > 105 && height > 62;
                const values = marketVolumeMetrics(row, stats);
                const metricSlots = width >= 180 ? Math.max(0, Math.floor((height - 80) / 17)) : 0;
                const tileMetrics = selectedMetrics.slice(0, metricSlots);
                const metricTitle = selectedMetrics.map(({ key, label }) => [
                  `${label}: ${formatMapMetric(key, values[key], lang)}`,
                  windowed ? mapMetricCoverage(row, key, lang) : "",
                ].filter(Boolean).join(" · ")).join("\n");
                const preferred = isPreferredRow(row);
                const showPreferredBadge = preferred && width >= 84 && height >= 44;
                const microTile = !showTicker;
                const active = hover?.ticker === row.ticker;
                return (
                  <button
                    key={row.ticker}
                    className={`heatmap-tree-tile${microTile ? " is-micro" : ""}${active ? " is-active" : ""}${preferred ? " is-preferred" : ""}${lowConfidence(row) ? " is-low-confidence" : ""}${status !== "ok" ? " is-unavailable" : ""}`}
                    type="button"
                    style={{
                      left: stock.x + tileGap / 2,
                      top: stock.y + tileGap / 2,
                      width,
                      height,
                      "--tile-fill": status === "ok" ? heatmapColor(row.changePercent, fullScale) : undefined,
                    }}
                    aria-label={`${row.ticker}, ${companyName}, ${sectorLabel(lang, sector.sector)}, ${status === "ok" ? formatPct(row.changePercent) : mapCopy.noData}`}
                    title={metricTitle}
                    data-ticker={row.ticker}
                    onClick={() => (onOpenCompany ? onOpenCompany(row.ticker) : onAnalyze(row.ticker))}
                    onMouseEnter={() => setHover({ ticker: row.ticker, row })}
                    onMouseLeave={() => setHover((current) => (current?.ticker === row.ticker ? null : current))}
                    onFocus={() => setHover({ ticker: row.ticker, row })}
                    onBlur={() => setHover((current) => (current?.ticker === row.ticker ? null : current))}
                  >
                    {showTicker && (
                      <span className="htt-ticker" style={{ fontSize: tickerSize }}>
                        {row.ticker}{showPreferredBadge && <em title={mapCopy.preferred}>P</em>}
                      </span>
                    )}
                    {showPercent && <span className="htt-pct" style={{ fontSize: tickerSize * 0.78 }}>{status === "ok" ? formatPct(row.changePercent) : "—"}</span>}
                    {showName && <span className="htt-name">{heatmapShortName(companyName)}</span>}
                    {tileMetrics.length > 0 && <span className="htt-metrics">
                      {tileMetrics.map(({ key, label }) => <span key={key} data-metric={key}>
                        <span>{label}</span><b>{formatMapMetric(key, values[key], lang, true)}</b>
                      </span>)}
                    </span>}
                  </button>
                );
              })}
            </React.Fragment>
          );
        })}
      </div>

      {sectorItems.length === 0 && (
        <p className="market-empty-cell">
          {lang === "ru" ? "Нет данных для карты" : lang === "uz" ? "Xarita uchun ma'lumot yo'q" : "No data for map"}
        </p>
      )}
    </div>
  );
}

export { MarketHeatmap };
