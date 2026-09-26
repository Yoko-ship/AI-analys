import React from "react";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { formatMarketNumber } from "../../shared/format.jsx";
import { signedFixed } from "../../shared/format.jsx";
import { sectorLabel } from "../../shared/marketCopy.jsx";
import { sectorOf } from "../../lib/sectors.js";

/**
 * «Сравнить с» — the reference's compare strip, a row of peer cards under the
 * toolbar. A click puts that security's line on the chart.
 *
 * A strip rather than the dropdown this replaced: a menu makes the reader
 * remember which peers exist and what they did today, and then choose blind.
 * The card carries the price and the day's move, so the choice is informed
 * before it is made — which is the whole reason the reference spends a row of
 * the page on it.
 *
 * The card shows the TICKER, not the company name the reference shows. Their
 * names are «Microsoft C…»; ours truncate to «"O'zbekneftgaz…» and
 * «"Kafolat sug'urt…», which name nothing — and the ticker is what the chart's
 * own legend and tooltip use, so the card and the line it draws agree.
 */
function AdvancedCompareBar({ peers, allRows, securitiesMap, selected, colors, onToggle, lang, max }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [q, setQ] = React.useState("");
  const [searching, setSearching] = React.useState(false);
  const scroller = React.useRef(null);
  const [arrows, setArrows] = React.useState({ left: false, right: false });
  const sync = React.useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    setArrows({ left: el.scrollLeft > 4, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
  }, []);
  const needle = q.trim().toUpperCase();
  const matches = (r) => String(r.ticker || "").toUpperCase().includes(needle)
    || String(r.name || "").toUpperCase().includes(needle);
  const found = needle
    ? (allRows || []).filter((r) => Number.isFinite(r.lastPrice) && r.lastPrice > 0 && matches(r)).slice(0, 40)
    : peers;
  // Whatever is ON the chart stays at the head of the strip, even when a search
  // excludes it: otherwise taking a line off means first searching for it again.
  const chosen = (allRows || []).filter((r) => selected.includes(String(r.ticker || "").toUpperCase()));
  const list = [...chosen, ...found.filter((r) => !selected.includes(String(r.ticker || "").toUpperCase()))];
  React.useEffect(() => {
    sync();
    if (typeof window === "undefined") return undefined;
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, [sync, list.length]);
  const nudge = (dir) => {
    const el = scroller.current;
    if (el) el.scrollBy({ left: dir * Math.max(240, el.clientWidth * 0.8), behavior: "smooth" });
  };
  const full = selected.length >= max;

  return (
    <div className="ac-compare">
      <button type="button" className={`ac-compare-btn ${searching ? "on" : ""}`}
        onClick={() => { setSearching((v) => !v); if (searching) setQ(""); }}>
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        {t("Сравнить с", "Taqqoslash", "Compare to")}
      </button>
      {searching && (
        <input className="ac-compare-input" type="search" autoFocus value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); setSearching(false); } }}
          placeholder={t("Тикер или название", "Tiker yoki nom", "Ticker or name")} />
      )}
      <div className="ac-compare-scroll">
        {arrows.left && (
          <button type="button" className="ac-compare-arrow left" onClick={() => nudge(-1)}
            aria-label={t("Назад", "Orqaga", "Back")}>‹</button>
        )}
        <div className="ac-compare-cards" ref={scroller} onScroll={sync}>
          {/* «Ничего не найдено» only answers a SEARCH. Before the board has
              loaded the strip is empty for a different reason, and saying the
              market holds nothing would be a false answer to a question the
              reader never asked. */}
          {list.length === 0 && (needle
            ? <span className="muted ac-compare-empty">{t("Ничего не найдено", "Hech narsa topilmadi", "Nothing found")}</span>
            : <span className="muted ac-compare-empty">{t("Загрузка списка…", "Ro'yxat yuklanmoqda…", "Loading the list…")}</span>
          )}
          {list.map((r) => {
            const tk = String(r.ticker || "").toUpperCase();
            const on = selected.includes(tk);
            const color = on ? colors[selected.indexOf(tk) % colors.length] : null;
            const tone = r.changePercent > 0 ? "pos" : r.changePercent < 0 ? "neg" : "";
            return (
              <button key={tk} type="button" className={`ac-cmp-card ${on ? "on" : ""}`}
                style={color ? { "--ac-color": color } : undefined}
                disabled={!on && full}
                aria-pressed={on}
                title={!on && full
                  ? t(`Не больше ${max} — уберите одну бумагу`, `${max} tadan ko'p emas`, `Up to ${max} — remove one first`)
                  : `${r.name || tk} — ${on ? t("убрать с графика", "grafikdan olib tashlash", "remove from the chart")
                                             : t("добавить на график", "grafikka qo'shish", "add to the chart")}`}
                onClick={() => onToggle(tk)}>
                <CompanyLogo logo={(securitiesMap || {})[tk]?.logo_url} name={r.name || tk} ticker={tk} />
                <span className="ac-cmp-tk">{tk}</span>
                <span className="ac-cmp-price">{formatMarketNumber(r.lastPrice, lang)}</span>
                <span className={`ac-cmp-chg ${tone}`}>
                  {Number.isFinite(r.changePercent)
                    ? `${signedFixed(r.changePercent)}%` : "—"}
                </span>
              </button>
            );
          })}
        </div>
        {arrows.right && (
          <button type="button" className="ac-compare-arrow right" onClick={() => nudge(1)}
            aria-label={t("Вперёд", "Oldinga", "Forward")}>›</button>
        )}
      </div>
    </div>
  );
}

/** The rail beside the advanced chart: search, favourites, peers. */
function AdvancedChartRail({ rows, securitiesMap, ticker, favorites, onToggleFavorite,
                             onOpen, lang, signedIn }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [q, setQ] = React.useState("");
  const up = String(ticker || "").toUpperCase();
  const favSet = favorites || new Set();
  const priced = (rows || []).filter((r) => Number.isFinite(r.lastPrice) && r.lastPrice > 0);
  const needle = q.trim().toUpperCase();

  const list = needle
    ? priced.filter((r) => String(r.ticker || "").toUpperCase().includes(needle)
        || String(r.name || "").toUpperCase().includes(needle)).slice(0, 40)
    : null;

  const row = (r) => {
    const tk = String(r.ticker || "").toUpperCase();
    const isFav = favSet.has(tk);
    const tone = r.changePercent > 0 ? "pos" : r.changePercent < 0 ? "neg" : "";
    return (
      <div className={`ac-rail-row ${tk === up ? "is-current" : ""}`} key={tk}>
        <button type="button" className="ac-rail-name" onClick={() => onOpen && onOpen(tk)}>
          <span className="ac-rail-tk">{tk}</span>
          <span className="ac-rail-sub">{r.name || sectorLabel(lang, sectorOf(tk, securitiesMap, null))}</span>
        </button>
        <span className="ac-rail-figures">
          <span className="ac-rail-price">{formatMarketNumber(r.lastPrice, lang)}</span>
          <span className={`ac-rail-chg ${tone}`}>
            {Number.isFinite(r.changePercent)
              ? `${signedFixed(r.changePercent)}%` : "—"}
          </span>
        </span>
        <button type="button" className={`rail-fav ${isFav ? "on" : ""}`}
          onClick={() => onToggleFavorite && onToggleFavorite(tk, r.name)}>{isFav ? "★" : "☆"}</button>
      </div>
    );
  };

  const favRows = priced.filter((r) => favSet.has(String(r.ticker || "").toUpperCase()));
  const mine = sectorOf(up, securitiesMap, null);
  const sector = (!mine || mine === "other") ? [] : priced
    .filter((r) => String(r.ticker || "").toUpperCase() !== up
      && sectorOf(r.ticker, securitiesMap, null) === mine)
    .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0)).slice(0, 12);

  return (
    <div className="ac-rail">
      <input className="ac-rail-search" type="search" value={q} onChange={(e) => setQ(e.target.value)}
        placeholder={t("Поиск бумаги", "Qog'oz qidirish", "Search securities")} />
      {list ? (
        <div className="ac-rail-block">
          <h4 className="ac-rail-head">{t("Найдено", "Topildi", "Found")}</h4>
          {list.length ? <div>{list.map(row)}</div>
            : <p className="muted ac-rail-empty">{t("Ничего не найдено", "Hech narsa topilmadi", "Nothing found")}</p>}
        </div>
      ) : (
        <>
          <div className="ac-rail-block">
            <h4 className="ac-rail-head">{t("Избранное", "Tanlanganlar", "Watchlist")}</h4>
            {favRows.length ? <div>{favRows.map(row)}</div>
              : <p className="muted ac-rail-empty">
                  {signedIn ? t("Пока пусто", "Hozircha bo'sh", "Empty")
                            : t("Войдите, чтобы вести список", "Ro'yxat uchun kiring", "Sign in to keep a list")}
                </p>}
          </div>
          {sector.length > 0 && (
            <div className="ac-rail-block">
              <h4 className="ac-rail-head">{t("Тот же сектор", "Xuddi shu soha", "Same sector")}</h4>
              <div>{sector.map(row)}</div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export { AdvancedChartRail, AdvancedCompareBar };
