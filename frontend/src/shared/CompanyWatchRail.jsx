import { sectorOf } from "../lib/sectors.js";
import { sectorLabel } from "./marketCopy.jsx";
import { formatMarketNumber } from "./format.jsx";
import { signedFixed } from "./format.jsx";

// A row's price line, drawn from stored settled closes (/api/quotes/series).
// Deliberately axis-less and label-less: at this size the only readable claim is
// the SHAPE, and a series of fewer than two sessions has no shape to show.
function RailSparkline({ points }) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const closes = points.map((p) => Number(p?.[1])).filter((v) => Number.isFinite(v) && v > 0);
  if (closes.length < 2) return null;
  const W = 56, H = 22, PAD = 2;
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const d = closes
    .map((v, i) => {
      const x = PAD + (i / (closes.length - 1)) * (W - PAD * 2);
      const y = PAD + (1 - (v - min) / range) * (H - PAD * 2);
      return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  // Toned against the window's own start, not the day's move: this line spans
  // weeks, and colouring it by today would contradict the shape it draws.
  const tone = closes[closes.length - 1] >= closes[0] ? "pos" : "neg";
  return (
    <svg className={`rail-spark tone-${tone}`} viewBox={`0 0 ${W} ${H}`} aria-hidden="true"
      preserveAspectRatio="none">
      <path d={d} />
    </svg>
  );
}

// The watch rail. MSN stacks «My watchlist» over «Suggested for you»; ours is
// Избранное, the issuer's own sector, and the session's movers — the three that
// can be answered from data we hold rather than from a recommender.
// Which securities the watch rail shows. Pure, and module-level, because the
// page has to fetch a price series for exactly these tickers — computing the
// lists twice would let the fetch ask for one set and the rail draw another.
function watchRailLists({ ticker, rows, securitiesMap, favorites }) {
  const up = String(ticker || "").toUpperCase();
  const favSet = favorites || new Set();
  const priced = (Array.isArray(rows) ? rows : [])
    .filter((r) => Number.isFinite(r.lastPrice) && r.lastPrice > 0);

  // sectorOf answers "other" for a ticker the catalog does not classify — a
  // bucket, not a sector. Listing its members as peers would put a fund next to
  // a cement plant and call them comparable.
  const mine = sectorOf(up, securitiesMap, null);
  const bySector = (!mine || mine === "other") ? [] : priced
    .filter((r) => String(r.ticker || "").toUpperCase() !== up
      && sectorOf(r.ticker, securitiesMap, null) === mine)
    .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0))
    .slice(0, 6);

  // Movers need a move: the exchange carries a close forward through sessions
  // with no executions, so an untraded security sits at exactly 0 % and would
  // otherwise fill the list from the middle outwards. `tradedToday` is the same
  // activity test the board uses — last == prev proves nothing on its own.
  const sorted = priced
    .filter((r) => Number.isFinite(r.changePercent) && r.tradedToday)
    .sort((a, b) => b.changePercent - a.changePercent);
  const movers = [...sorted.slice(0, 3), ...sorted.slice(-3).reverse()]
    .filter((r, i, all) => all.findIndex((x) => x.ticker === r.ticker) === i);

  return {
    priced,
    favRows: priced.filter((r) => favSet.has(String(r.ticker || "").toUpperCase())),
    bySector,
    movers,
  };
}

function CompanyWatchRail({ ticker, rows, securitiesMap, series, favorites, onToggleFavorite,
                            onOpen, signedIn, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const up = String(ticker || "").toUpperCase();
  const favSet = favorites || new Set();
  const { priced, favRows, bySector, movers } =
    watchRailLists({ ticker, rows, securitiesMap, favorites });

  const row = (r) => {
    const tk = String(r.ticker || "").toUpperCase();
    const isFav = favSet.has(tk);
    const tone = r.changePercent > 0 ? "pos" : r.changePercent < 0 ? "neg" : "";
    return (
      <div className={`rail-row ${tk === up ? "is-current" : ""}`} key={tk}>
        <button type="button" className="rail-row-name" onClick={() => onOpen && onOpen(tk)}>
          <span className="rail-row-ticker">{tk}</span>
          <span className="rail-row-sub">{sectorLabel(lang, sectorOf(tk, securitiesMap, null))}</span>
        </button>
        <RailSparkline points={(series || {})[tk]} />
        <span className="rail-row-figures">
          <span className="rail-row-price">{formatMarketNumber(r.lastPrice, lang)}</span>
          <span className={`rail-row-change ${tone}`}>
            {Number.isFinite(r.changePercent)
              ? `${signedFixed(r.changePercent)}%`
              : "—"}
          </span>
        </span>
        <button type="button" className={`rail-fav ${isFav ? "on" : ""}`}
          title={isFav ? t("Убрать из избранного", "Olib tashlash", "Remove from favourites")
                       : t("В избранное", "Tanlanganlarga", "Add to favourites")}
          onClick={() => onToggleFavorite && onToggleFavorite(tk, r.name)}>
          {isFav ? "★" : "☆"}
        </button>
      </div>
    );
  };

  const block = (title, items, empty) => (
    <div className="co-sidebar-block rail-block" key={title}>
      <h3 className="co-heading">{title}</h3>
      {items.length ? <div className="rail-rows">{items.map(row)}</div>
        : <p className="rail-empty muted">{empty}</p>}
    </div>
  );

  if (!priced.length) return null;
  return (
    <div className="company-watch-rail">
      {block(
        t("Избранное", "Tanlanganlar", "Watchlist"),
        favRows,
        signedIn
          ? t("Пока пусто — отметьте ☆ у бумаги", "Hozircha bo'sh — ☆ bosing", "Empty — mark a security with ☆")
          : t("Войдите, чтобы вести список", "Ro'yxat uchun kiring", "Sign in to keep a list"),
      )}
      {bySector.length > 0 && block(t("Тот же сектор", "Xuddi shu soha", "Same sector"), bySector, "")}
      {movers.length > 0 && block(t("Лидеры дня", "Kun liderlari", "Day's movers"), movers, "")}
    </div>
  );
}

export { CompanyWatchRail, watchRailLists };
