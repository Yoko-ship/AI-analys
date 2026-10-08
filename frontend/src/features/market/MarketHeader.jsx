import { formatMarketTimestamp, marketStampTitle } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
export function MarketHeader({
  lang,
  isAdmin,
  meta,
  onRefresh,
  loading,
  rows,
  showSearch,
  query,
  onQueryChange
}) {
  return <article className="panel market-hero-panel">
        <div className="market-hero-copy">
          <div className="panel-label">{mt(lang, "nav")}</div>
          <h1>{mt(lang, "title")}</h1>
          <p>{mt(lang, "subtitle")}</p>
        </div>
        {/* The search sits in the masthead, the first control a reader meets:
            looking a company up is what most visits to this page are for. */}
        {(showSearch || isAdmin) && <div className="market-hero-actions">
            {showSearch && <label className="market-search market-hero-search">
                <input type="search" value={query} onChange={event => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} aria-label={mt(lang, "search")} />
              </label>}
            {/* Operator controls, not reader information: the collector's stamp and
                the manual re-pull answer "did OUR 08:00/13:00/16:10 run land", a
                question only an admin can act on. Readers get the session date on
                the board itself.
                When WE last refreshed the board (the collector's 08:00 / 13:00 /
                16:10 runs), not when someone else's mirror refreshed its cache —
                the second is what this used to show, and it can never report our
                schedule. The mirror's stamp and the session it describes stay in
                the tooltip; the feed stamp is the fallback if the trade-stats call
                has not landed yet. */}
            {isAdmin && <span className="status-badge muted" title={marketStampTitle(meta, lang)}>
              {mt(lang, "updated")}: {formatMarketTimestamp(meta?.refreshed_at || meta?.updated_at, lang)}
            </span>}
            {isAdmin && <button className="ghost-btn" type="button" onClick={onRefresh} disabled={loading}>
              {loading ? mt(lang, "loading") : mt(lang, "refresh")}
            </button>}
          </div>}
      </article>;
}
