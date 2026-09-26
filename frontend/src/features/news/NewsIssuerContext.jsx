import { useNewsIssuerContext } from "./useNewsIssuerContext.js";
import { interceptNav, newsArticlePath, newsRelTime } from "./editorial.jsx";
import { formatMarketNumber, formatSignedPercent } from "../../shared/format.jsx";
import { _TONE_CLS } from "./newsText.jsx";
import { edHeadlineCached } from "./newsTranslation.js";
export function NewsIssuerContext({
  tickers,
  currentId,
  language,
  securitiesMap,
  onOpenCompany,
  onOpenNews,
  tx
}) {
  const {
    byTicker,
    keys
  } = useNewsIssuerContext({
    currentId,
    securitiesMap,
    tickers
  });

  // Issuers we have a quote for lead: a story naming four bond series should not push the
  // bank it is actually about off the list.

  if (!keys.length) return null;
  return <section className="led-art-block">
      <h3 className="led-panel-h">{tx.issuers}</h3>
      <div className="led-iss-grid">
        {keys.map(tk => {
        const sec = securitiesMap && securitiesMap[tk] || null;
        const data = byTicker[tk];
        const sentiment = data && data.sentiment;
        const others = (data && data.items || []).filter(n => String(n.id) !== String(currentId)).slice(0, 3);
        const last = sec ? Number(sec.last_price) : NaN;
        const close = sec ? Number(sec.close_price) : NaN;
        const chg = Number.isFinite(last) && Number.isFinite(close) && close ? (last - close) / close * 100 : null;
        const tone = sentiment && typeof sentiment.weighted_tone === "number" ? sentiment.weighted_tone : null;
        const toneCls = tone == null ? "" : tone > 0.15 ? "pos" : tone < -0.15 ? "neg" : "";
        const chgCls = chg == null ? "" : chg > 0 ? "pos" : chg < 0 ? "neg" : "";
        return <article className="led-iss" key={tk}>
              <button type="button" className="led-iss-head" title={tx.openCompany} onClick={() => onOpenCompany && onOpenCompany(tk)}>
                {sec && sec.logo_url && <img className="led-iss-logo" src={sec.logo_url} alt="" loading="lazy" onError={e => {
              e.currentTarget.style.display = "none";
            }} />}
                <span className="led-iss-name">{sec && sec.name || tk}</span>
                <span className="led-iss-tk">{tk}</span>
              </button>
              <dl className="led-iss-stats">
                <div><dt>{tx.price}</dt><dd>{Number.isFinite(last) ? formatMarketNumber(last, language) : "—"}</dd></div>
                <div><dt>{tx.change}</dt><dd className={chgCls}>{chg == null ? "—" : formatSignedPercent(chg)}</dd></div>
                <div><dt>{tx.tone90}</dt><dd className={toneCls}>{tone == null ? "—" : `${tone >= 0 ? "+" : ""}${tone.toFixed(2)}`}</dd></div>
              </dl>
              {sentiment && sentiment.count > 0 && <div className="led-iss-basis">{sentiment.count} {tx.basedOn}</div>}
              {others.length > 0 && <div className="led-iss-news">
                  <h4 className="led-panel-h">{tx.moreNews}</h4>
                  {others.map(n => <a key={n.id} className="led-lt" href={newsArticlePath(n)} {...n.id && onOpenNews ? {
              onClick: interceptNav(() => onOpenNews(n))
            } : {
              target: "_blank",
              rel: "noopener noreferrer"
            }}>
                      <span className={`led-dot ${_TONE_CLS[n.tone] || "neu"}`} />
                      <span className="led-lt-t">{edHeadlineCached(n, language).text}</span>
                      <span className="led-lt-s">{n.source}{n.published_at ? ` · ${newsRelTime(n.published_at, language)}` : ""}</span>
                    </a>)}
                </div>}
            </article>;
      })}
      </div>
      <p className="led-art-hint">{tx.tickersHint}</p>
    </section>;
}
