import { EDNEWS_TX, NEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime } from "./editorial.jsx";
import React from "react";
import { newsHeadline, newsDek, _TONE_CLS, edSummary } from "./newsText.jsx";
import { useBrowserHeadline } from "./newsTranslation.js";
export function NewsCard({
  item,
  language,
  tx,
  variant,
  onOpen
}) {
  const open = () => {
    if (item.ticker) onOpen(item.ticker);
  };
  const cls = variant === "lead" ? "news-lead" : "news-card";
  const TitleTag = variant === "lead" ? "h2" : "h3";
  return <article className={`${cls} cat-${item.type}`} role="button" tabIndex={0} onClick={open} onKeyDown={e => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      open();
    }
  }}>
      <div className="news-meta">
        <span className={`news-tag cat-${item.type}`}>{tx.cat[item.type] || tx.cat.report}</span>
        <span className="news-time">{newsRelTime(item.date, language)}</span>
      </div>
      <TitleTag className={variant === "lead" ? "news-lead-title" : "news-card-title"}>{newsHeadline(item, language, tx)}</TitleTag>
      <p className={variant === "lead" ? "news-lead-dek" : "news-card-dek"}>{newsDek(item, language)}</p>
      {item.ticker && <span className="news-ticker">{item.ticker}</span>}
    </article>;
}
export function EdNewsCard({
  item,
  language,
  variant,
  onOpen
}) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const isLead = variant === "lead";
  const TitleTag = isLead ? "h2" : "h3";
  const [imgOk, setImgOk] = React.useState(true);
  const inApp = Boolean(item.id && onOpen);
  const {
    machine
  } = useBrowserHeadline(item, language);
  const head = edHeadline(item, language, machine);
  // When the Russian headline above IS our summary, printing it again as the dek would only
  // repeat the line; the source's own wording takes that slot instead. A translated headline
  // is not the summary, so there the dek goes back to doing its normal job.
  const summary = head.original && !head.machine ? "" : edSummary(item, language);
  const toneCls = _TONE_CLS[item.tone] || "neu";
  // Half our feed is issuer filings and central-bank notices that will never carry a
  // picture. A coloured slab in the photo's place only announces the absence — louder
  // than the headline on a phone — so an item without one simply has no figure and the
  // headline moves up into the space.
  const art = Boolean(item.image_url) && imgOk;
  return <a className={`${isLead ? "led-lead" : "led-story"}${art ? "" : " led-noart"}`} href={newsArticlePath(item)} {...inApp ? {
    onClick: interceptNav(() => onOpen(item))
  } : {
    target: "_blank",
    rel: "noopener noreferrer"
  }}>
      {art && <div className={isLead ? "led-figure" : "led-thumb"}>
          <img src={item.image_url} alt="" loading="lazy" onError={() => setImgOk(false)} />
        </div>}
      <div className="led-body">
        <div className="led-eyebrow">
          <span className="led-cat">{etx.cat[item.type] || item.type}</span>
          {item.tone && <><span className="led-sep">·</span><span className={`led-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span></>}
          {isLead && item.impact && item.impact !== "none" && <><span className="led-sep">·</span><span className="led-imp">{etx.impact[item.impact] || item.impact}</span></>}
        </div>
        <TitleTag className={isLead ? "led-lead-title" : "led-story-title"}>{head.text}</TitleTag>
        {summary && <p className={isLead ? "led-dek" : "led-story-dek"}>{summary}</p>}
        {head.original && <p className={`led-orig ${isLead ? "led-dek" : "led-story-dek"}`}>
            <span className="led-lang">{head.lang}</span>{head.original}
            {head.machine && <span className="led-mt">{etx.machine}</span>}
          </p>}
        <div className="led-byline">{item.source && <b>{item.source}</b>}{item.published_at ? ` · ${newsRelTime(item.published_at, language)}` : ""}</div>
      </div>
    </a>;
}
export function newsDeskTickers(item) {
  if (!item) return [];
  const values = Array.isArray(item.tickers) ? item.tickers : item.ticker ? [item.ticker] : [];
  return [...new Set(values.map(v => String(v || "").trim().toUpperCase()).filter(Boolean))];
}
export function NewsDeskPriorityStory({
  item,
  language,
  variant,
  onOpen
}) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const dtx = (NEWS_TX[language] || NEWS_TX.ru).desk;
  const isLead = variant === "lead";
  const {
    machine
  } = useBrowserHeadline(item, language);
  const head = edHeadline(item, language, machine);
  const summary = head.original && !head.machine ? "" : edSummary(item, language);
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const inApp = Boolean(item.id && onOpen);
  const tickers = newsDeskTickers(item);
  const TitleTag = isLead ? "h2" : "h3";
  const [imgOk, setImgOk] = React.useState(true);
  React.useEffect(() => setImgOk(true), [item.image_url]);
  const art = Boolean(item.image_url) && imgOk;
  return <a className={`newsdesk-priority-story newsdesk-priority-story--${variant}${art ? " has-art" : ""}`} href={newsArticlePath(item)} {...inApp ? {
    onClick: interceptNav(() => onOpen(item))
  } : {
    target: "_blank",
    rel: "noopener noreferrer"
  }}>
      {art && <figure className="newsdesk-priority-picture">
          <img src={item.image_url} alt="" loading={isLead ? "eager" : "lazy"} decoding="async" onError={() => setImgOk(false)} />
        </figure>}
      <div className="newsdesk-meta">
        {isLead && <span>{dtx.main}</span>}
        <span className="newsdesk-category">{etx.cat[item.type] || item.type}</span>
        {item.tone && <span className={`newsdesk-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span>}
        {isLead && item.impact && item.impact !== "none" && <span>{etx.impact[item.impact] || item.impact}</span>}
      </div>
      <TitleTag>{head.text}</TitleTag>
      {isLead && summary && <p>{summary}</p>}
      {isLead && head.original && <p className="newsdesk-original"><span>{head.lang}</span>{head.original}</p>}
      <div className="newsdesk-byline">
        {item.source && <b>{item.source}</b>}
        {item.published_at && <span>{newsRelTime(item.published_at, language)}</span>}
        {tickers.length > 0 && <span className="newsdesk-related">{tickers.slice(0, 2).join(" · ")}</span>}
      </div>
    </a>;
}
export function NewsDeskRow({
  item,
  language,
  onOpen
}) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const {
    machine
  } = useBrowserHeadline(item, language);
  const head = edHeadline(item, language, machine);
  const summary = head.original && !head.machine ? "" : edSummary(item, language);
  const detail = summary || head.original || item.source;
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const tickers = newsDeskTickers(item);
  const inApp = Boolean(item.id && onOpen);
  const [imgOk, setImgOk] = React.useState(true);
  React.useEffect(() => setImgOk(true), [item.image_url]);
  const art = Boolean(item.image_url) && imgOk;
  return <a className={`newsdesk-row${art ? " has-art" : ""}`} href={newsArticlePath(item)} {...inApp ? {
    onClick: interceptNav(() => onOpen(item))
  } : {
    target: "_blank",
    rel: "noopener noreferrer"
  }}>
      <time>{item.published_at ? newsRelTime(item.published_at, language) : "—"}</time>
      {art && <span className="newsdesk-row-picture">
          <img src={item.image_url} alt="" loading="lazy" decoding="async" onError={() => setImgOk(false)} />
        </span>}
      <span className="newsdesk-row-copy">
        <span className="newsdesk-row-kicker">
          <span className="newsdesk-row-category">{etx.cat[item.type] || item.type}</span>
          {tickers.length > 0 && <span className="newsdesk-row-tickers">{tickers.slice(0, 2).join(" · ")}</span>}
        </span>
        <strong>{head.text}</strong>
        {detail && <small>{detail}</small>}
      </span>
      <span className="newsdesk-row-end">
        <span className={`newsdesk-row-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone || "—"}</span>
        <span className="newsdesk-row-arrow" aria-hidden="true">→</span>
      </span>
    </a>;
}
export function newsDeskFocus(items) {
  const counts = new Map();
  for (const item of items || []) {
    for (const ticker of newsDeskTickers(item)) counts.set(ticker, (counts.get(ticker) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5);
}
