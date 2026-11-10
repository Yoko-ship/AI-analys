import { formatMarketTimestamp, marketStampTitle } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
export function MarketHeader({
  lang,
  isAdmin,
  meta,
  onRefresh,
  loading,
  rows,
  compact = false,
  showSearch,
  query,
  onQueryChange
}) {
  return <article className="panel market-hero-panel">
        <div className="market-hero-copy">
          {!compact && <><div className="panel-label">{mt(lang, "nav")}</div>
          <h1>{mt(lang, "title")}</h1>
          <p>{mt(lang, "subtitle")}</p></>}
          <p data-testid="market-last-update" role="status" title={marketStampTitle(meta, lang)}>
            {meta?.refreshed_at ? <>
              {mt(lang, "lastQuoteUpdate")}: {" "}
              <time dateTime={meta.refreshed_at}>{formatMarketTimestamp(meta.refreshed_at, lang)}</time>
              {" "}({mt(lang, "tashkentTime")})
            </> : mt(lang, "quoteUpdateUnknown")}
          </p>
        </div>
        {/* The search sits in the masthead, the first control a reader meets:
            looking a company up is what most visits to this page are for. */}
        {(showSearch || isAdmin) && <div className="market-hero-actions">
            {showSearch && <label className="market-search market-hero-search">
                <input type="search" value={query} onChange={event => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} aria-label={mt(lang, "search")} />
              </label>}
            {isAdmin && <button className="ghost-btn" type="button" onClick={onRefresh} disabled={loading}>
              {loading ? mt(lang, "loading") : mt(lang, "refresh")}
            </button>}
          </div>}
      </article>;
}
