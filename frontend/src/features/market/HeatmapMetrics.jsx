import React from "react";
import { mt } from "../../shared/marketCopy.jsx";
import { formatMarketNumber, formatRatio } from "../../shared/format.jsx";
import { formatCompactVolume } from "../../shared/marketModel.jsx";
import { MarketColsPopover } from "./TableOverlays.jsx";
import { TermInfo } from "../../shared/TermInfo.jsx";

const METRICS = [["volume", "volumeCol"], ["volQty", "volQty"], ["avgShare", "avgSharePrice"],
  ["avgTrade", "avgTradePrice"], ["bigTrade", "bigTrade"], ["volShare", "volShare"]];
const STORAGE_KEY = "uz_market_map_metrics_v1";

export function useHeatmapMetrics(lang, type) {
  const [keys, setKeys] = React.useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (Array.isArray(saved)) return saved.filter((key) => METRICS.some(([id]) => id === key));
    } catch { /* Use the defaults when preferences are unavailable. */ }
    return METRICS.map(([key]) => key);
  });
  React.useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(keys)); } catch { /* Optional preference. */ }
  }, [keys]);
  const metrics = METRICS.map(([key, labelKey]) => ({ key,
    label: key === "avgShare" && type === "bond"
      ? lang === "ru" ? "Ср. цена облигации" : lang === "uz" ? "Obligatsiyaning o'rtacha narxi" : "Avg. bond price"
      : mt(lang, labelKey) }));
  return { metrics, selected: metrics.filter(({ key }) => keys.includes(key)), keys, setKeys };
}

export function formatMapMetric(key, value, lang, compact = false) {
  if (!Number.isFinite(value)) return "—";
  if (key === "volShare") return `${formatRatio(value, 2, lang)}%`;
  if (key === "volQty") return `${formatRatio(value, 0, lang)} ${mt(lang, "tradeQtyUnit")}`;
  const amount = compact && key !== "avgShare" ? formatCompactVolume(value, lang)
    : key === "avgShare" ? formatMarketNumber(value, lang) : formatRatio(value, 0, lang);
  return `${amount} UZS`;
}

export function mapMetricCoverage(row, key, lang) {
  const count = row?.periodDetailSessions;
  const total = row?.periodSessions;
  if (!["avgTrade", "bigTrade"].includes(key) || !Number.isFinite(count) || !(count < total)) return "";
  return lang === "ru" ? `Детали по ${count} из ${total} сессий`
    : lang === "uz" ? `${total} sessiyadan ${count} tasi bo'yicha tafsilotlar` : `Details for ${count} of ${total} sessions`;
}

export function HeatmapMetricPicker({ lang, metrics, keys, setKeys }) {
  const [open, setOpen] = React.useState(false);
  const anchor = React.useRef(null);
  const all = metrics.every(({ key }) => keys.includes(key));
  const title = lang === "ru" ? "Показатели" : lang === "uz" ? "Ko'rsatkichlar" : "Metrics";
  const close = () => { setOpen(false); anchor.current?.focus(); };
  return <div className="market-cols-wrap heatmap-metric-picker">
    <button type="button" ref={anchor} className={`market-cols-btn ${open ? "active" : ""}`}
      aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>
      {title}<span className="market-cols-count">{keys.length}</span>
    </button>
    {open && <MarketColsPopover anchorRef={anchor} onClose={close} title={title}
      closeLabel={lang === "ru" ? "Закрыть" : lang === "uz" ? "Yopish" : "Close"}>
      <div className="market-cols-body">
        <label className="market-cols-row">
          <input type="checkbox" checked={all} ref={(el) => { if (el) el.indeterminate = !all && keys.length > 0; }}
            onChange={() => setKeys(all ? [] : metrics.map(({ key }) => key))} />
          <span>{lang === "ru" ? "Все" : lang === "uz" ? "Barchasi" : "All"}</span>
        </label>
        {metrics.map(({ key, label }) => <label className="market-cols-row" key={key}>
          <input type="checkbox" aria-label={label} checked={keys.includes(key)} onChange={() => setKeys((current) => current.includes(key)
            ? current.filter((item) => item !== key) : [...current, key])} />
          <span>{label}</span><TermInfo termId={key} lang={lang} label={label} />
        </label>)}
      </div>
    </MarketColsPopover>}
  </div>;
}
