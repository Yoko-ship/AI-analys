import { useNewsReaction } from "./useNewsReaction.js";
import { formatMarketNumber, formatSignedPercent } from "../../shared/format.jsx";
import { sessionCountLabel } from "../../shared/marketModel.jsx";
import { newsShortDay } from "./newsText.jsx";
export function NewsPriceReaction({
  newsId,
  language,
  securitiesMap,
  onOpenCompany,
  tx
}) {
  const {
    state
  } = useNewsReaction({
    newsId
  });

  // An issuer we could not price at all adds nothing to the page — the issuer block
  // above already names it. Only rows that carry a real comparison are shown.
  const rows = state.items.filter(r => r.status === "ok" || r.status === "no_session_yet");
  if (state.loading || !rows.length) return null;
  // Most stories are same-day, so printing that caveat on every row would turn it into
  // wallpaper. It belongs with the note that already qualifies the whole block.
  const sameDay = rows.some(r => r.after && r.after.same_day);
  return <section className="led-art-block led-rx">
      <h3 className="led-panel-h">{tx.rxTitle}</h3>
      <div className="led-rx-grid">
        {rows.map(r => {
        const sec = securitiesMap && securitiesMap[r.ticker] || null;
        const change = r.change && typeof r.change.value === "number" ? r.change.value : null;
        const since = r.since && typeof r.since.value === "number" ? r.since.value : null;
        const ratio = r.volume_vs_normal && typeof r.volume_vs_normal.value === "number" ? r.volume_vs_normal.value : null;
        const cls = change == null ? "" : change > 0 ? "pos" : change < 0 ? "neg" : "";
        return <article className="led-rx-row" key={r.ticker}>
              <button type="button" className="led-rx-tk" title={tx.openCompany} onClick={() => onOpenCompany && onOpenCompany(r.ticker)}>
                <b>{r.ticker}</b>{sec && sec.name ? <span>{sec.name}</span> : null}
              </button>
              {r.status === "no_session_yet" ? <p className="led-rx-none">{tx.rxNoSession}</p> : <>
                  <div className="led-rx-span">
                    <span className="led-rx-leg">
                      <i>{newsShortDay(r.before.date, language)}</i>
                      {formatMarketNumber(r.before.close, language)}
                    </span>
                    <span className="led-rx-arrow" aria-hidden="true">→</span>
                    <span className="led-rx-leg">
                      <i>{newsShortDay(r.after.date, language)}</i>
                      {formatMarketNumber(r.after.close, language)}
                    </span>
                    <b className={`led-rx-chg ${cls}`}>{formatSignedPercent(change)}</b>
                  </div>
                  <dl className="led-rx-meta">
                    {ratio != null && <div><dt>{tx.rxVolume}</dt><dd>{`×${ratio.toFixed(1)}`}</dd></div>}
                    {since != null && r.sessions_after > 1 && <div>
                        <dt>{tx.rxSince}</dt>
                        <dd className={since > 0 ? "pos" : since < 0 ? "neg" : ""}>
                          {formatSignedPercent(since)}
                          <span className="led-rx-sessions">
                            {` · ${r.sessions_after} ${sessionCountLabel(r.sessions_after, language)}`}
                          </span>
                        </dd>
                      </div>}
                  </dl>
                  {r.data_tier === "illiquid" && <p className="led-rx-hedge">{tx.rxIlliquid}</p>}
                </>}
            </article>;
      })}
      </div>
      <p className="led-art-hint">{sameDay ? `${tx.rxNote} ${tx.rxSameDay}` : tx.rxNote}</p>
    </section>;
}
