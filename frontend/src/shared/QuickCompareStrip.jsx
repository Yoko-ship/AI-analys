import React from "react";
import { QC_MAX } from "./priceChartModel.jsx";
import { CompanyLogo } from "./CompanyLogo.jsx";
import { formatMarketNumber } from "./format.jsx";
import { signedFixed } from "./format.jsx";

// The strip itself: the peers on offer, and the ones already on the chart as
// removable chips. Cards carry price and the day's move so the click is an
// informed one — MSN's strip does the same, and it is the only place on this
// page where another security's session is quoted next to this one's.
function QuickCompareStrip({ peers, securitiesMap, selected, colors, onToggle, lang, loading }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const scroller = React.useRef(null);
  const [scrollState, setScrollState] = React.useState({ left: false, right: false });
  const syncArrows = React.useCallback(() => {
    const n = scroller.current;
    if (!n) return;
    setScrollState({
      left: n.scrollLeft > 4,
      right: n.scrollLeft + n.clientWidth < n.scrollWidth - 4,
    });
  }, []);
  React.useEffect(() => {
    syncArrows();
    if (typeof window === "undefined") return undefined;
    window.addEventListener("resize", syncArrows);
    return () => window.removeEventListener("resize", syncArrows);
  }, [syncArrows, peers]);
  const nudge = (dir) => {
    const n = scroller.current;
    if (n) n.scrollBy({ left: dir * Math.max(180, n.clientWidth * 0.8), behavior: "smooth" });
  };

  if (!peers.length) return null;
  const chosen = new Set(selected);
  const full = selected.length >= QC_MAX;

  return (
    <div className="quick-compare">
      <div className="qc-head">
        <h4 className="qc-title">{t("Быстрое сравнение", "Tez taqqoslash", "Quick compare")}</h4>
        <div className="qc-chips">
          {selected.map((tk, i) => (
            <button key={tk} type="button" className="qc-chip"
              style={{ "--qc-color": colors[i % colors.length] }}
              title={t("Убрать с графика", "Grafikdan olib tashlash", "Remove from the chart")}
              onClick={() => onToggle(tk)}>
              <span className="qc-dot" aria-hidden="true" />
              {tk}
              <span className="qc-chip-x" aria-hidden="true">✕</span>
            </button>
          ))}
          {loading && <span className="qc-loading muted">{t("загрузка…", "yuklanmoqda…", "loading…")}</span>}
        </div>
      </div>
      <div className="qc-scroll">
        {scrollState.left && (
          <button type="button" className="qc-arrow qc-arrow-left" aria-label={t("Назад", "Orqaga", "Back")}
            onClick={() => nudge(-1)}>‹</button>
        )}
        <div className="qc-cards" ref={scroller} onScroll={syncArrows}>
          {peers.map((r) => {
            const tk = String(r.ticker || "").toUpperCase();
            const on = chosen.has(tk);
            const color = on ? colors[selected.indexOf(tk) % colors.length] : null;
            const tone = r.changePercent > 0 ? "pos" : r.changePercent < 0 ? "neg" : "";
            return (
              <button key={tk} type="button"
                className={`qc-card ${on ? "on" : ""}`}
                style={color ? { "--qc-color": color } : undefined}
                disabled={!on && full}
                aria-pressed={on}
                title={!on && full
                  ? t(`Не больше ${QC_MAX} — уберите одну бумагу, чтобы добавить другую`,
                      `${QC_MAX} tadan ko'p emas — bittasini olib tashlang`,
                      `Up to ${QC_MAX} — remove one to add another`)
                  : `${r.name || tk} — ${on ? t("убрать с графика", "grafikdan olib tashlash", "remove from the chart")
                                             : t("добавить на график", "grafikka qo'shish", "add to the chart")}`}
                onClick={() => onToggle(tk)}>
                <span className="qc-card-head">
                  <CompanyLogo logo={(securitiesMap || {})[tk]?.logo_url} name={r.name || tk} ticker={tk} />
                  <span className="qc-card-name">{r.name || tk}</span>
                </span>
                <span className="qc-card-figures">
                  <span className="qc-card-price">{formatMarketNumber(r.lastPrice, lang)}</span>
                  <span className={`qc-card-change ${tone}`}>
                    {Number.isFinite(r.changePercent)
                      ? `${signedFixed(r.changePercent)}%`
                      : "—"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
        {scrollState.right && (
          <button type="button" className="qc-arrow qc-arrow-right" aria-label={t("Вперёд", "Oldinga", "Forward")}
            onClick={() => nudge(1)}>›</button>
        )}
      </div>
    </div>
  );
}

export { QuickCompareStrip };
