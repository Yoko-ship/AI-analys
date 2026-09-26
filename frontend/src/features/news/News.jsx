import { EDNEWS_TX, NEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime } from "./editorial.jsx";
import React from "react";
import { allowDownloads, cachedTranslation, onTranslation, translateHeadline } from "../../lib/translate.js";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { localizedCalendarTitle } from "../../lib/calendarTitle.js";
import { pickLeadIndex } from "../../lib/newsfeed.js";
import { MarketEventsFeed } from "../events/index.js";
import { formatMarketNumber, formatSignedPercent } from "../../shared/format.jsx";
import { sessionCountLabel } from "../../shared/marketModel.jsx";
import { VIEW_PATHS } from "../../app/routing.jsx";

function newsPeriod(item, language) {
  if (item.year == null) return "";
  if (item.quarter && item.quarter > 0) {
    return language === "en" ? `Q${item.quarter} ${item.year}` : language === "uz" ? `${item.year} ${item.quarter}-chorak` : `${item.quarter} кв. ${item.year}`;
  }
  return language === "en" ? `FY ${item.year}` : language === "uz" ? `${item.year}-yil` : `${item.year} год`;
}

function newsHeadline(item, language, tx) {
  const company = item.company || item.ticker || "";
  if (item.type === "listing") {
    const suffix = item.ticker ? ` (${item.ticker})` : "";
    return language === "en" ? `New listing: ${company}${suffix}` : language === "uz" ? `Yangi listing: ${company}${suffix}` : `Новый листинг: ${company}${suffix}`;
  }
  if (item.type === "delisting") {
    return language === "en" ? `${company} drops off active trading` : language === "uz" ? `${company} faol savdodan chiqdi` : `${company}: нет активных торгов`;
  }
  const form = (item.report_form && tx.forms[item.report_form]) || item.report_form || "";
  const period = newsPeriod(item, language);
  if (language === "en") return `${company} files ${form} report${period ? ` for ${period}` : ""}`.replace(/\s+/g, " ").trim();
  if (language === "uz") return `${company} ${form} hisobotini e'lon qildi${period ? ` (${period})` : ""}`.replace(/\s+/g, " ").trim();
  return `${company}: раскрыт отчёт ${form}${period ? ` за ${period}` : ""}`.replace(/\s+/g, " ").trim();
}

function newsDek(item, language) {
  if (item.type === "listing") {
    return language === "en" ? "Newly admitted to trading on the exchange." : language === "uz" ? "Birjada savdoga yangi kiritildi." : "Новая бумага допущена к торгам на бирже.";
  }
  if (item.type === "delisting") {
    return language === "en" ? "No recent trades — a possible delisting." : language === "uz" ? "So'nggi savdolar yo'q — delisting ehtimoli." : "Давно нет сделок — возможен делистинг.";
  }
  return language === "en" ? "Financial statements disclosed on the exchange." : language === "uz" ? "Moliyaviy hisobot birjada e'lon qilindi." : "Финансовая отчётность раскрыта на бирже.";
}

function NewsCard({ item, language, tx, variant, onOpen }) {
  const open = () => { if (item.ticker) onOpen(item.ticker); };
  const cls = variant === "lead" ? "news-lead" : "news-card";
  const TitleTag = variant === "lead" ? "h2" : "h3";
  return (
    <article className={`${cls} cat-${item.type}`} role="button" tabIndex={0}
      onClick={open} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } }}>
      <div className="news-meta">
        <span className={`news-tag cat-${item.type}`}>{tx.cat[item.type] || tx.cat.report}</span>
        <span className="news-time">{newsRelTime(item.date, language)}</span>
      </div>
      <TitleTag className={variant === "lead" ? "news-lead-title" : "news-card-title"}>{newsHeadline(item, language, tx)}</TitleTag>
      <p className={variant === "lead" ? "news-lead-dek" : "news-card-dek"}>{newsDek(item, language)}</p>
      {item.ticker && <span className="news-ticker">{item.ticker}</span>}
    </article>
  );
}

const NEWS_ADMIN_TX = {
  ru: { title: "Новостной агент (Grok)", ph: "Компания, тикер или тема…", days: "Дней", save: "Сохранять в ленту",
        run: "Найти", running: "Поиск…", found: "найдено", nw: "новых", rel: "релевантных", stored: "сохранено",
        empty: "Ничего не найдено", err: "Ошибка поиска", note: "Заметка",
        hint: "Каждый запуск — платный поиск Grok (web + X). Виден только администраторам." },
  en: { title: "News agent (Grok)", ph: "Company, ticker, or topic…", days: "Days", save: "Save to feed",
        run: "Search", running: "Searching…", found: "found", nw: "new", rel: "relevant", stored: "stored",
        empty: "Nothing found", err: "Search failed", note: "Note",
        hint: "Each run triggers a billed Grok web + X search. Admin-only." },
  uz: { title: "Yangiliklar agenti (Grok)", ph: "Kompaniya, ticker yoki mavzu…", days: "Kun", save: "Lentaga saqlash",
        run: "Qidirish", running: "Qidirilmoqda…", found: "topildi", nw: "yangi", rel: "tegishli", stored: "saqlandi",
        empty: "Hech narsa topilmadi", err: "Qidiruvda xatolik", note: "Izoh",
        hint: "Har bir qidiruv — pullik Grok (web + X). Faqat administratorlar uchun." },
};

const NEWS_ADMIN_TONE = { positive: "#2f9e5f", negative: "#c0504d", neutral: "#8a8a8a" };

// Admin-only tool on the news page: runs the Layer-B Grok agent (GET
// /api/news/agent-search, Bearer-authenticated + email-allowlisted server-side),
// shows what it found/classified, and — when "Save to feed" is on — stores it into
// the editorial feed. The machine X-Admin-Secret is never used here; the logged-in
// admin's own token authorises the call.
function NewsAdminPanel({ language, apiFetch, onStored }) {
  const tx = NEWS_ADMIN_TX[language] || NEWS_ADMIN_TX.ru;
  const [q, setQ] = React.useState("");
  const [days, setDays] = React.useState(7);
  const [store, setStore] = React.useState(true);
  const [loading, setLoading] = React.useState(false);
  const [res, setRes] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [open, setOpen] = React.useState(false);

  const run = async () => {
    const query = q.trim();
    if (!query || loading) return;
    setLoading(true); setErr(""); setRes(null);
    try {
      const params = new URLSearchParams({ q: query, days: String(days || 7), store: String(!!store) });
      const r = await apiFetch(`/api/news/agent-search?${params.toString()}`);
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d || !d.ok) setErr((d && d.detail) || tx.err);
      else { setRes(d); if (store && d.stored > 0 && onStored) onStored(); }
    } catch (e) { setErr(tx.err); }
    finally { setLoading(false); }
  };

  const border = "1px solid rgba(128,128,128,.28)";
  const box = { border, borderRadius: 10, background: "rgba(128,128,128,.06)" };
  const field = { padding: "8px 10px", borderRadius: 8, border, background: "transparent", color: "inherit", font: "inherit" };

  return (
    <section style={{ ...box, margin: "0 0 22px", overflow: "hidden" }}>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "10px 14px",
                 background: "transparent", border: "none", cursor: "pointer", font: "inherit", color: "inherit", textAlign: "left" }}>
        <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: ".08em", padding: "2px 6px", borderRadius: 4,
                       background: "rgba(192,80,77,.15)", color: "#c0504d" }}>ADMIN</span>
        <strong style={{ flex: 1 }}>{tx.title}</strong>
        <span style={{ opacity: .6 }} aria-hidden="true">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div style={{ padding: "4px 14px 14px" }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <input type="text" value={q} placeholder={tx.ph}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") run(); }}
              style={{ ...field, flex: "1 1 240px", minWidth: 180 }} />
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, opacity: .85 }}>
              {tx.days}
              <input type="number" min="1" max="30" value={days}
                onChange={(e) => setDays(Math.max(1, Math.min(30, Number(e.target.value) || 7)))}
                style={{ ...field, width: 58 }} />
            </label>
            <label style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, opacity: .85 }}>
              <input type="checkbox" checked={store} onChange={(e) => setStore(e.target.checked)} /> {tx.save}
            </label>
            <button type="button" onClick={run} disabled={loading || !q.trim()}
              style={{ padding: "8px 18px", borderRadius: 8, border: "none", color: "#fff", font: "inherit", fontWeight: 600,
                       cursor: loading || !q.trim() ? "default" : "pointer",
                       background: loading || !q.trim() ? "rgba(128,128,128,.4)" : "#2f6fed" }}>
              {loading ? tx.running : tx.run}
            </button>
          </div>
          <div style={{ fontSize: 11, opacity: .55, marginTop: 6 }}>{tx.hint}</div>
          {err && <div style={{ marginTop: 10, color: "#c0504d", fontSize: 13 }}>{err}</div>}
          {res && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>
                {res.found} {tx.found} · {res.new} {tx.nw} · {res.relevant} {tx.rel}
                {store ? ` · ${res.stored} ${tx.stored}` : ""}{res.backend ? ` · ${res.backend}` : ""}
              </div>
              {res.note && <div style={{ fontSize: 12, opacity: .7, marginTop: 2 }}>{tx.note}: {res.note}</div>}
              {(!res.items || res.items.length === 0) ? (
                <div style={{ marginTop: 10, opacity: .6, fontSize: 13 }}>{tx.empty}</div>
              ) : (
                <ul style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "grid", gap: 8 }}>
                  {res.items.map((it, i) => (
                    <li key={i} style={{ ...box, padding: "10px 12px" }}>
                      <a href={it.url} target="_blank" rel="noopener noreferrer"
                        style={{ fontWeight: 600, color: "inherit", textDecoration: "none" }}>{it.title || it.url}</a>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 6, fontSize: 12, opacity: .9 }}>
                        {it.source && <span>{it.source}</span>}
                        {it.type && <span className={`news-tag-mini cat-${it.type}`}>{it.type}</span>}
                        {it.tone && <span style={{ fontWeight: 600, color: NEWS_ADMIN_TONE[it.tone] || "inherit" }}>{it.tone}</span>}
                        {it.impact && it.impact !== "none" && <span>impact: {it.impact}</span>}
                        {it.direction && it.direction !== "unclear" && <span>{it.direction}</span>}
                        {Array.isArray(it.tickers) && it.tickers.length > 0 && <span style={{ fontWeight: 600 }}>{it.tickers.join(", ")}</span>}
                        <span title="relevant" style={{ marginLeft: "auto" }} aria-hidden="true">{it.relevant ? "★" : "☆"}</span>
                      </div>
                      {it.summary_ru && <div style={{ marginTop: 6, fontSize: 13, opacity: .92 }}>{it.summary_ru}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}

const _TONE_CLS = { positive: "pos", negative: "neg", neutral: "neu" };

// Coverage-weighted-ish market sentiment across the loaded feed, for the sidebar
// gauge: mean tone_score plus positive/neutral/negative counts. A statistical
// aggregate, not a verdict (matches the API's per-ticker sentiment endpoint).
function feedSentiment(items) {
  const counts = { positive: 0, neutral: 0, negative: 0 };
  let sum = 0, n = 0;
  for (const it of items) {
    if (it.tone && counts[it.tone] != null) counts[it.tone] += 1;
    if (typeof it.tone_score === "number") { sum += it.tone_score; n += 1; }
  }
  const avg = n ? sum / n : 0;
  return { avg, counts, pct: Math.round(((avg + 1) / 2) * 100), cls: avg > 0.15 ? "pos" : avg < -0.15 ? "neg" : "neu" };
}

// The stored summary in the reader's language. Falls back to Russian — the pivot the
// classifier writes first, and all a row collected before the other two columns existed
// has — and only then to the source's own lead-in, and that one ONLY when the source wrote
// it in the reader's language, or we would swap one foreign paragraph for another.
function edSummary(item, language) {
  if (!item) return "";
  return (item[`summary_${language}`] || "").trim()
    || (item.summary_ru || "").trim()
    || (item.lang === language ? (item.snippet || "").trim() : "");
}

// The story page's long read: our own account of the source's article, written by the
// collector's detail pass in all three UI languages, as paragraphs separated by blank lines.
// Russian is the pivot, exactly as for the summary — a reader gets the wrong language before
// they get an empty page. Absent on items whose source publishes no article page to read
// (the rating agencies ship a headline; an openinfo filing has no page at all).
function edDetail(item, language) {
  if (!item) return [];
  const text = ((item[`detail_${language}`] || "").trim()
    || (item.detail_ru || "").trim());
  return text ? text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean) : [];
}

// Ask the browser to put a foreign headline into the reader's language with its own
// on-device translator.
// Strictly an enhancement: `item.translatable` is the server's verdict (false for Moody's and
// Fitch, whose headline is a URL slug that machine translation gets factually wrong), and a
// browser without the API — Safari, Firefox, anything on iOS — simply never resolves a
// translation and keeps the Russian summary that was already on the card.
//
// The automatic pass uses only a language pack that is already installed, so nobody pays for
// a surprise download; when one is merely `downloadable`, `offer` goes true and the story
// page shows an opt-in the reader can take (or not).
function useBrowserHeadline(item, language) {
  const source = item && item.translatable && item.lang && item.lang !== language
    ? item.lang : "";
  const text = source ? item.title || "" : "";
  const [machine, setMachine] = React.useState(() => (text ? cachedTranslation(text, source, language) : ""));
  const [offer, setOffer] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    setMachine(text ? cachedTranslation(text, source, language) : "");
    setOffer(false);
    if (!text) return undefined;
    translateHeadline(text, source, language).then(({ text: out, status }) => {
      if (!alive) return;
      if (out) setMachine(out);
      else setOffer(status === "downloadable" || status === "downloading");
    });
    return () => { alive = false; };
  }, [text, source, language]);

  // Called from a click, which is what lets Chrome fetch the language pack at all.
  const request = React.useCallback(() => {
    if (!text) return;
    allowDownloads();
    setOffer(false);
    translateHeadline(text, source, language, { download: true })
      .then(({ text: out }) => { if (out) setMachine(out); });
  }, [text, source, language]);

  return { machine, offer, request };
}

// The same headline as `edHeadline`, but for the compact lists (the "latest" rail, an
// issuer's other stories) that only READ what a card has already translated rather than
// starting work of their own. Paired with useTranslationTick on the surrounding view so they
// repaint when a translation lands.
function edHeadlineCached(item, language) {
  const machine = item && item.translatable && item.lang && item.lang !== language
    ? cachedTranslation(item.title || "", item.lang, language) : "";
  return edHeadline(item, language, machine);
}

// Repaint this view whenever any headline finishes translating.
function useTranslationTick() {
  const [, bump] = React.useReducer((n) => n + 1, 0);
  React.useEffect(() => onTranslation(bump), []);
}

// Editorial news card ("Ledger" direction): serif headline, source image when the
// source provides one, source name shown in the byline, our own summary, and the AI
// tone/impact signal. Opens our own /news/{id} story page — the source link lives
// there, on the article itself.
function EdNewsCard({ item, language, variant, onOpen }) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const isLead = variant === "lead";
  const TitleTag = isLead ? "h2" : "h3";
  const [imgOk, setImgOk] = React.useState(true);
  const inApp = Boolean(item.id && onOpen);
  const { machine } = useBrowserHeadline(item, language);
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
  return (
    <a className={`${isLead ? "led-lead" : "led-story"}${art ? "" : " led-noart"}`} href={newsArticlePath(item)}
      {...(inApp ? { onClick: interceptNav(() => onOpen(item)) } : { target: "_blank", rel: "noopener noreferrer" })}>
      {art && (
        <div className={isLead ? "led-figure" : "led-thumb"}>
          <img src={item.image_url} alt="" loading="lazy" onError={() => setImgOk(false)} />
        </div>
      )}
      <div className="led-body">
        <div className="led-eyebrow">
          <span className="led-cat">{etx.cat[item.type] || item.type}</span>
          {item.tone && <><span className="led-sep">·</span><span className={`led-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span></>}
          {isLead && item.impact && item.impact !== "none" && <><span className="led-sep">·</span><span className="led-imp">{etx.impact[item.impact] || item.impact}</span></>}
        </div>
        <TitleTag className={isLead ? "led-lead-title" : "led-story-title"}>{head.text}</TitleTag>
        {summary && <p className={isLead ? "led-dek" : "led-story-dek"}>{summary}</p>}
        {head.original && (
          <p className={`led-orig ${isLead ? "led-dek" : "led-story-dek"}`}>
            <span className="led-lang">{head.lang}</span>{head.original}
            {head.machine && <span className="led-mt">{etx.machine}</span>}
          </p>
        )}
        <div className="led-byline">{item.source && <b>{item.source}</b>}{item.published_at ? ` · ${newsRelTime(item.published_at, language)}` : ""}</div>
      </div>
    </a>
  );
}

function newsDeskTickers(item) {
  if (!item) return [];
  const values = Array.isArray(item.tickers) ? item.tickers : (item.ticker ? [item.ticker] : []);
  return [...new Set(values.map((v) => String(v || "").trim().toUpperCase()).filter(Boolean))];
}

function NewsDeskPriorityStory({ item, language, variant, onOpen }) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const dtx = (NEWS_TX[language] || NEWS_TX.ru).desk;
  const isLead = variant === "lead";
  const { machine } = useBrowserHeadline(item, language);
  const head = edHeadline(item, language, machine);
  const summary = head.original && !head.machine ? "" : edSummary(item, language);
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const inApp = Boolean(item.id && onOpen);
  const tickers = newsDeskTickers(item);
  const TitleTag = isLead ? "h2" : "h3";
  const [imgOk, setImgOk] = React.useState(true);
  React.useEffect(() => setImgOk(true), [item.image_url]);
  const art = Boolean(item.image_url) && imgOk;
  return (
    <a className={`newsdesk-priority-story newsdesk-priority-story--${variant}${art ? " has-art" : ""}`} href={newsArticlePath(item)}
      {...(inApp ? { onClick: interceptNav(() => onOpen(item)) } : { target: "_blank", rel: "noopener noreferrer" })}>
      {art && (
        <figure className="newsdesk-priority-picture">
          <img src={item.image_url} alt="" loading={isLead ? "eager" : "lazy"}
            decoding="async" onError={() => setImgOk(false)} />
        </figure>
      )}
      <div className="newsdesk-meta">
        {isLead && <span>{dtx.main}</span>}
        <span className="newsdesk-category">{etx.cat[item.type] || item.type}</span>
        {item.tone && <span className={`newsdesk-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span>}
        {isLead && item.impact && item.impact !== "none" && <span>{etx.impact[item.impact] || item.impact}</span>}
      </div>
      <TitleTag>{head.text}</TitleTag>
      {isLead && summary && <p>{summary}</p>}
      {isLead && head.original && (
        <p className="newsdesk-original"><span>{head.lang}</span>{head.original}</p>
      )}
      <div className="newsdesk-byline">
        {item.source && <b>{item.source}</b>}
        {item.published_at && <span>{newsRelTime(item.published_at, language)}</span>}
        {tickers.length > 0 && <span className="newsdesk-related">{tickers.slice(0, 2).join(" · ")}</span>}
      </div>
    </a>
  );
}

function NewsDeskRow({ item, language, onOpen }) {
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const { machine } = useBrowserHeadline(item, language);
  const head = edHeadline(item, language, machine);
  const summary = head.original && !head.machine ? "" : edSummary(item, language);
  const detail = summary || head.original || item.source;
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const tickers = newsDeskTickers(item);
  const inApp = Boolean(item.id && onOpen);
  const [imgOk, setImgOk] = React.useState(true);
  React.useEffect(() => setImgOk(true), [item.image_url]);
  const art = Boolean(item.image_url) && imgOk;
  return (
    <a className={`newsdesk-row${art ? " has-art" : ""}`} href={newsArticlePath(item)}
      {...(inApp ? { onClick: interceptNav(() => onOpen(item)) } : { target: "_blank", rel: "noopener noreferrer" })}>
      <time>{item.published_at ? newsRelTime(item.published_at, language) : "—"}</time>
      {art && (
        <span className="newsdesk-row-picture">
          <img src={item.image_url} alt="" loading="lazy" decoding="async" onError={() => setImgOk(false)} />
        </span>
      )}
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
    </a>
  );
}

function newsDeskFocus(items) {
  const counts = new Map();
  for (const item of items || []) {
    for (const ticker of newsDeskTickers(item)) counts.set(ticker, (counts.get(ticker) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5);
}

// Reading modes over the four classes the §3.11 classifier already assigns —
// this stays a filter on data we hold, not a second pipeline.
const NEWS_TABS = [
  { key: "all", type: null },
  { key: "economy", type: "economy" },       // market + regulatory
  { key: "corporate", type: "corporate" },   // corporate_event + financial_report
  { key: "reporting", type: "financial_report" },
  { key: "regulator", type: "regulatory" },
  { key: "calendar", type: null },           // forward-looking: meetings + dividends
];

// «Корпоративные» is a disclosure feed, not a press review: the server serves that
// request from openinfo — the issuers' own filings — and only that request, so «Все»
// still carries what the papers write about an issuer. The rule lives there, with the
// source registry, not here: the tab asks for a reading mode, never for a source.

// Корпоративные splits again, by the instrument the filing is ABOUT. The
// classifier cannot make this split — a coupon payment and a dividend are both
// «corporate_event» — so the server makes it from the securities each item
// names. Only offered on that tab: an economy item names no issuer, and a
// bond/share filter over macro copy would empty the page.
const NEWS_INSTRUMENTS = ["all", "stock", "bond"];

function newsInstrumentFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("instrument");
  return NEWS_INSTRUMENTS.includes(wanted) ? wanted : "all";
}

function newsTabFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return NEWS_TABS.some((t) => t.key === wanted) ? wanted : "all";
}

// ── News «Календарь»: what lies ahead ────────────────────────────────────────
// Two forward-looking views over openinfo's own calendars — announced general
// meetings on a month grid (the shape openinfo's «Календарь событий» readers
// already know) and the market-wide dividend table. Both read snapshots the API
// keeps warm; the client only groups by day and filters by share class.
const NEWSCAL_TX = {
  ru: {
    views: { events: "Собрания", announcements: "Объявления", dividends: "Дивиденды" },
    viewHint: {
      events: "Объявленные общие собрания акционеров — по дате проведения",
      announcements: "Сообщения о созыве собраний — по дате публикации",
      dividends: "Объявленные дивиденды всего рынка — суммы, проценты и окна выплат",
    },
    weekdays: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    loading: "Загружаем календарь…", error: "Не удалось загрузить календарь.",
    emptyMonth: "На этот месяц собраний не заявлено.",
    wholeMonth: "Весь месяц",
    mode: { month: "Месяц", year: "Год" },
    searchPh: "Эмитент или тикер…",
    download: "Скачать CSV",
    divTypes: { common: "Простые акции", preferred: "Привилегированные", bond: "Облигации" },
    th: { issuer: "Эмитент", decision: "Дата решения", amount: "Сумма, сум", window: "Реестр / выплата",
      org: "Организация", title: "Название", pub: "Дата публикации", meeting: "Дата собрания" },
    pager: { perPage: "Показывать по", shown: "Показаны", of: "из" },
    annEmpty: "Объявлений не найдено.",
    divEmpty: "Данных по дивидендам пока нет.",
    divNote: "Суммы — на одну бумагу по решению собрания; период — окно закрытия реестра и выплаты.",
    source: "Источник: openinfo.uz",
  },
  en: {
    views: { events: "Meetings", announcements: "Announcements", dividends: "Dividends" },
    viewHint: {
      events: "Announced general shareholder meetings, by meeting date",
      announcements: "Meeting convocation notices, by publication date",
      dividends: "Declared dividends across the market — amounts, percents and payout windows",
    },
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    loading: "Loading the calendar…", error: "Could not load the calendar.",
    emptyMonth: "No meetings announced for this month.",
    wholeMonth: "Whole month",
    mode: { month: "Month", year: "Year" },
    searchPh: "Issuer or ticker…",
    download: "Download CSV",
    divTypes: { common: "Ordinary shares", preferred: "Preferred", bond: "Bonds" },
    th: { issuer: "Issuer", decision: "Decision date", amount: "Amount, UZS", window: "Record / payment",
      org: "Organization", title: "Title", pub: "Published", meeting: "Meeting date" },
    pager: { perPage: "Per page", shown: "Showing", of: "of" },
    annEmpty: "No announcements found.",
    divEmpty: "No dividend data yet.",
    divNote: "Amounts are per security, as resolved by the meeting; the window runs from the record date to the end of payment.",
    source: "Source: openinfo.uz",
  },
  uz: {
    views: { events: "Yig'ilishlar", announcements: "E'lonlar", dividends: "Dividendlar" },
    viewHint: {
      events: "E'lon qilingan umumiy yig'ilishlar — o'tkazish sanasi bo'yicha",
      announcements: "Yig'ilish chaqiruvi haqidagi xabarlar — e'lon sanasi bo'yicha",
      dividends: "Butun bozor bo'yicha e'lon qilingan dividendlar — summalar, foizlar va to'lov oynalari",
    },
    weekdays: ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
    loading: "Taqvim yuklanmoqda…", error: "Taqvimni yuklab bo'lmadi.",
    emptyMonth: "Bu oyga yig'ilishlar e'lon qilinmagan.",
    wholeMonth: "Butun oy",
    mode: { month: "Oy", year: "Yil" },
    searchPh: "Emitent yoki tiker…",
    download: "CSV yuklab olish",
    divTypes: { common: "Oddiy aksiyalar", preferred: "Imtiyozli", bond: "Obligatsiyalar" },
    th: { issuer: "Emitent", decision: "Qaror sanasi", amount: "Summa, so'm", window: "Reyestr / to'lov",
      org: "Tashkilot", title: "Nomi", pub: "E'lon sanasi", meeting: "Yig'ilish sanasi" },
    pager: { perPage: "Sahifada", shown: "Ko'rsatildi", of: "/" },
    annEmpty: "E'lonlar topilmadi.",
    divEmpty: "Dividendlar bo'yicha ma'lumot hozircha yo'q.",
    divNote: "Summalar — yig'ilish qarori bo'yicha bitta qog'ozga; davr — reyestr yopilishidan to'lov oxirigacha.",
    source: "Manba: openinfo.uz",
  },
};

const NEWS_CALENDAR_POLL_MS = 5 * 60 * 1000;

function calendarAnnouncementPath(item) {
  const id = String(item?.announcement_id || "").trim();
  if (!id) return "";
  return `/news/announcement/${encodeURIComponent(id)}`;
}

// Pagination the way the source's tables do it: a shown-range line, a
// «Показывать по N» selector and a numbered strip with ellipses.
function NewsCalPager({ p, pages, total, from, to, size, onPage, onSize, tx }) {
  if (!total) return null;
  const nums = [];
  for (const n of [1, p - 1, p, p + 1, pages]) {
    if (n >= 1 && n <= pages && !nums.includes(n)) nums.push(n);
  }
  nums.sort((a, b) => a - b);
  return (
    <div className="newscal-pager">
      <span className="muted">{tx.pager.shown} {from}–{to} {tx.pager.of} {total}</span>
      <label className="newscal-psize muted">
        {tx.pager.perPage}
        <select className="newscal-select" value={size} onChange={(e) => onSize(Number(e.target.value))}>
          {[10, 25, 50].map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
      </label>
      <div className="newscal-pnums">
        <button type="button" className="newscal-arrow" disabled={p <= 1} aria-label="prev"
          onClick={() => onPage(p - 1)}>‹</button>
        {nums.map((n, i) => (
          <React.Fragment key={n}>
            {i > 0 && nums[i - 1] < n - 1 && <span className="muted">…</span>}
            <button type="button" className={`newscal-pnum ${n === p ? "active" : ""}`}
              onClick={() => onPage(n)}>{n}</button>
          </React.Fragment>
        ))}
        <button type="button" className="newscal-arrow" disabled={p >= pages} aria-label="next"
          onClick={() => onPage(p + 1)}>›</button>
      </div>
    </div>
  );
}

function NewsCalendarView({ language, onOpenCompany, onOpenAnnouncement }) {
  const lang = normalizeLanguage(language);
  const tx = NEWSCAL_TX[lang] || NEWSCAL_TX.ru;
  const locale = lang === "en" ? "en-US" : lang === "uz" ? "uz" : "ru-RU";
  const today = new Date();
  const [view, setView] = React.useState("events");
  const [mode, setMode] = React.useState("month"); // «Месяц» | «Год» — the source's own toggle
  const [cursor, setCursor] = React.useState({ y: today.getFullYear(), m: today.getMonth() + 1 });
  const [day, setDay] = React.useState(null);
  const [search, setSearch] = React.useState("");
  const [events, setEvents] = React.useState({ loading: true, error: false, items: [] });
  const [anns, setAnns] = React.useState(null); // null = not asked for yet
  const [divs, setDivs] = React.useState(null); // null = not asked for yet
  const [divType, setDivType] = React.useState("common");
  const [divSort, setDivSort] = React.useState({ key: "pub", dir: -1 });
  const [pageSize, setPageSize] = React.useState(10);
  const [page, setPage] = React.useState(1);
  const [refreshTick, setRefreshTick] = React.useState(0);
  React.useEffect(() => { setPage(1); }, [view, divType, search, pageSize, divSort]);

  React.useEffect(() => {
    const refresh = () => {
      if (!document.hidden) setRefreshTick((n) => n + 1);
    };
    const timer = window.setInterval(refresh, NEWS_CALENDAR_POLL_MS);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);

  React.useEffect(() => {
    let alive = true;
    setEvents({ loading: true, error: false, items: [] });
    setDay(null);
    fetch(mode === "year"
      ? `/api/news/calendar/meetings?year=${cursor.y}`
      : `/api/news/calendar/meetings?year=${cursor.y}&month=${cursor.m}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setEvents({ loading: false, error: !d || !d.ok, items: (d && d.items) || [] }); })
      .catch(() => { if (alive) setEvents({ loading: false, error: true, items: [] }); });
    return () => { alive = false; };
  }, [cursor.y, cursor.m, mode, refreshTick]);

  React.useEffect(() => {
    if (view !== "dividends") return undefined;
    let alive = true;
    fetch("/api/news/calendar/dividends?limit=1000")
      .then((r) => r.json())
      .then((d) => { if (alive) setDivs({ error: !d || !d.ok, items: (d && d.items) || [] }); })
      .catch(() => { if (alive) setDivs({ error: true, items: [] }); });
    return () => { alive = false; };
  }, [view, refreshTick]);

  React.useEffect(() => {
    if (view !== "announcements") return undefined;
    let alive = true;
    fetch("/api/news/calendar/announcements?limit=2000")
      .then((r) => r.json())
      .then((d) => { if (alive) setAnns({ error: !d || !d.ok, items: (d && d.items) || [] }); })
      .catch(() => { if (alive) setAnns({ error: true, items: [] }); });
    return () => { alive = false; };
  }, [view, refreshTick]);

  const q = search.trim().toLowerCase();
  const filteredEvents = React.useMemo(
    () => (q
      ? events.items.filter((it) => String(it.organization || "").toLowerCase().includes(q)
        || String(it.ticker || "").toLowerCase().includes(q))
      : events.items),
    [events.items, q],
  );

  const byDay = React.useMemo(() => {
    const map = new Map();
    for (const it of filteredEvents) {
      const n = parseInt(String(it.meeting_date || "").slice(8, 10), 10);
      if (!n) continue;
      if (!map.has(n)) map.set(n, []);
      map.get(n).push(it);
    }
    return map;
  }, [filteredEvents]);

  // Year view: the same rows grouped by month, because a 12-month grid answers
  // no question a dated list does not.
  const byMonth = React.useMemo(() => {
    const map = new Map();
    for (const it of filteredEvents) {
      const key = String(it.meeting_date || "").slice(0, 7);
      if (!key) continue;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(it);
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [filteredEvents]);

  const monthLabel = new Date(cursor.y, cursor.m - 1, 1).toLocaleDateString(locale, { month: "long", year: "numeric" });
  const daysInMonth = new Date(cursor.y, cursor.m, 0).getDate();
  const lead = (new Date(cursor.y, cursor.m - 1, 1).getDay() + 6) % 7; // Monday-first
  const isThisMonth = today.getFullYear() === cursor.y && today.getMonth() + 1 === cursor.m;
  const move = (delta) => setCursor(({ y, m }) => {
    const next = m + delta;
    return next < 1 ? { y: y - 1, m: 12 } : next > 12 ? { y: y + 1, m: 1 } : { y, m: next };
  });

  const fmtDay = (iso) => (iso ? new Date(iso).toLocaleDateString(locale, { day: "numeric", month: "short" }) : "");
  const fmtTime = (iso) => {
    // The meeting hour is only trustworthy when the issuer filed one: a real
    // agenda starts on a round minute, while a date copied from the filing
    // timestamp carries its seconds (16:21:48). Those render date-only.
    const m = /T(\d\d):(\d\d):(\d\d)/.exec(String(iso || ""));
    if (!m || m[3] !== "00" || (m[1] === "00" && m[2] === "00")) return "";
    return `${m[1]}:${m[2]}`;
  };
  const listItems = day == null ? filteredEvents : byDay.get(day) || [];

  const fmtNum = (v) => (v == null ? "—" : Number(v).toLocaleString(locale, { maximumFractionDigits: 2 }));
  const fmtDate = (d) => (d ? new Date(d).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" }) : "—");
  // The chip picks the share class, the columns follow it — the same three-way
  // split the source's table offers. Decisions that declared nothing for the
  // chosen class stay on the company pages, where they are the issuer's record.
  const amountOf = (r) => (divType === "preferred" ? r.preferred_amount : divType === "bond" ? r.bond_amount : r.ordinary_amount);
  const pctOf = (r) => (divType === "preferred" ? r.preferred_percent : divType === "bond" ? r.bond_percent : r.ordinary_percent);
  const startOf = (r) => (divType === "preferred" ? r.preferred_start : divType === "bond" ? r.bond_start : r.ordinary_start);
  const endOf = (r) => (divType === "preferred" ? r.preferred_end : divType === "bond" ? r.bond_end : r.ordinary_end);
  const divItems = React.useMemo(() => {
    const rows = ((divs && divs.items) || []).filter((r) => (amountOf(r) || 0) > 0);
    if (!q) return rows;
    return rows.filter((r) => String(r.organization || "").toLowerCase().includes(q)
      || (r.tickers || []).some((t) => String(t).toLowerCase().includes(q)));
  }, [divs, divType, q]);

  const downloadCsv = () => {
    const esc = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
    const lines = [[tx.th.issuer, "Ticker", tx.th.decision, tx.th.amount, "%",
      tx.th.window, "Link"].map(esc).join(";")];
    for (const r of divItems) {
      lines.push([r.organization, (r.tickers || []).join(", "), r.decision_date,
        amountOf(r), pctOf(r), [startOf(r), endOf(r)].filter(Boolean).join(" – "),
        r.link].map(esc).join(";"));
    }
    // BOM so Excel reads the Cyrillic as UTF-8; semicolons for the RU locale.
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `dividends_${divType}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const annItems = React.useMemo(() => {
    const rows = (anns && anns.items) || [];
    if (!q) return rows;
    return rows.filter((it) => String(it.organization || "").toLowerCase().includes(q)
      || String(it.ticker || "").toLowerCase().includes(q)
      || String(it.title || "").toLowerCase().includes(q));
  }, [anns, q]);

  const sortedDivs = React.useMemo(() => {
    const val = (r) => (divSort.key === "amount" ? (amountOf(r) || 0)
      : divSort.key === "percent" ? (pctOf(r) || 0)
        : divSort.key === "decision" ? String(r.decision_date || "")
          : String(r.pub_date || ""));
    return [...divItems].sort((a, b) => {
      const x = val(a); const y = val(b);
      return (x < y ? -1 : x > y ? 1 : 0) * divSort.dir;
    });
  }, [divItems, divSort, divType]);

  const paginate = (rows) => {
    const total = rows.length;
    const pages = Math.max(1, Math.ceil(total / pageSize));
    const p = Math.min(page, pages);
    const from = total === 0 ? 0 : (p - 1) * pageSize + 1;
    const slice = rows.slice((p - 1) * pageSize, (p - 1) * pageSize + pageSize);
    return { slice, total, pages, p, from, to: total === 0 ? 0 : from + slice.length - 1 };
  };
  const annPage = paginate(annItems);
  const divPage = paginate(sortedDivs);

  const sortTh = (key, label, num) => (
    <th className={`newscal-sortth${num ? " dividend-num" : ""}`}
      aria-sort={divSort.key === key ? (divSort.dir < 0 ? "descending" : "ascending") : undefined}
      onClick={() => setDivSort((s) => ({ key, dir: s.key === key ? -s.dir : -1 }))}>
      {label}{divSort.key === key ? (divSort.dir < 0 ? " ↓" : " ↑") : ""}
    </th>
  );

  const orgCell = (it) => (it.ticker && onOpenCompany
    ? (
      <button type="button" className="newscal-org-btn" onClick={() => onOpenCompany(it.ticker)}>
        {it.organization} <span className="newscal-tk">{it.ticker}</span>
      </button>
    )
    : <span className="newscal-row-org">{it.organization}</span>);

  const renderRow = (it, i) => {
    const href = calendarAnnouncementPath(it);
    const contents = (
      <>
        <span className="newscal-row-date">
          {fmtDay(it.meeting_date)}{fmtTime(it.meeting_date) ? ` · ${fmtTime(it.meeting_date)}` : ""}
        </span>
        <div className="newscal-row-body">
          <span className="newscal-row-org">{it.organization}</span>
          {it.title && (
            <span className="newscal-row-title" title={it.title}>
              {localizedCalendarTitle(it, lang)}
            </span>
          )}
        </div>
      </>
    );
    return href ? (
      <a key={it.announcement_id || i} className="newscal-row newscal-news-row"
        href={href}
        {...(onOpenAnnouncement ? { onClick: interceptNav(() => onOpenAnnouncement(it)) } : {})}
        aria-label={`${it.organization || ""}: ${localizedCalendarTitle(it, lang)}`}>
        {contents}
      </a>
    ) : <div key={it.announcement_id || i} className="newscal-row">{contents}</div>;
  };

  return (
    <div className="newscal">
      <div className="news-subtabs" role="group" aria-label={tx.views.events}>
        {["events", "announcements", "dividends"].map((key) => (
          <button key={key} type="button"
            className={`news-subtab ${view === key ? "active" : ""}`}
            aria-pressed={view === key}
            onClick={() => setView(key)}>
            {tx.views[key]}
          </button>
        ))}
      </div>
      <p className="muted newscal-hint">{tx.viewHint[view]}</p>

      {view === "events" ? (
        <>
          <div className="newscal-bar">
            <div className="newscal-nav">
              <button type="button" className="newscal-arrow" aria-label="prev"
                onClick={() => (mode === "year" ? setCursor((c) => ({ ...c, y: c.y - 1 })) : move(-1))}>‹</button>
              <select className="newscal-select" value={cursor.y} aria-label="year"
                onChange={(e) => setCursor((c) => ({ ...c, y: Number(e.target.value) }))}>
                {[today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1].map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
              {mode === "month" && (
                <select className="newscal-select" value={cursor.m} aria-label="month"
                  onChange={(e) => setCursor((c) => ({ ...c, m: Number(e.target.value) }))}>
                  {Array.from({ length: 12 }).map((_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {new Date(2000, i, 1).toLocaleDateString(locale, { month: "long" })}
                    </option>
                  ))}
                </select>
              )}
              <button type="button" className="newscal-arrow" aria-label="next"
                onClick={() => (mode === "year" ? setCursor((c) => ({ ...c, y: c.y + 1 })) : move(1))}>›</button>
            </div>
            <div className="newscal-toggle" role="group">
              {["month", "year"].map((k) => (
                <button key={k} type="button"
                  className={`newscal-toggle-btn ${mode === k ? "active" : ""}`}
                  aria-pressed={mode === k}
                  onClick={() => { setMode(k); setDay(null); }}>
                  {tx.mode[k]}
                </button>
              ))}
            </div>
            <input className="newscal-search" type="search" value={search}
              placeholder={tx.searchPh} onChange={(e) => setSearch(e.target.value)} />
            {day != null && (
              <button type="button" className="ghost-btn" style={{ fontSize: 12 }} onClick={() => setDay(null)}>
                {tx.wholeMonth}
              </button>
            )}
          </div>

          {events.loading ? (
            <div className="led-empty">{tx.loading}</div>
          ) : events.error ? (
            <div className="led-empty">{tx.error}</div>
          ) : (
            <>
              {mode === "month" && (
              <div className="newscal-grid">
                {tx.weekdays.map((w) => <div key={w} className="newscal-dow">{w}</div>)}
                {Array.from({ length: lead }).map((_, i) => <div key={`b${i}`} className="newscal-cell blank" />)}
                {Array.from({ length: daysInMonth }).map((_, i) => {
                  const n = i + 1;
                  const evs = byDay.get(n) || [];
                  const isToday = isThisMonth && today.getDate() === n;
                  return (
                    <button key={n} type="button"
                      className={`newscal-cell${evs.length ? " has-events" : ""}${day === n ? " selected" : ""}${isToday ? " today" : ""}`}
                      disabled={!evs.length}
                      onClick={() => setDay(day === n ? null : n)}>
                      <span className="newscal-daynum">{n}</span>
                      {evs.length > 0 && <span className="newscal-count">{evs.length}</span>}
                      {evs.slice(0, 2).map((e, j) => <span key={j} className="newscal-chip">{e.organization}</span>)}
                      {evs.length > 2 && <span className="newscal-more">+{evs.length - 2}</span>}
                    </button>
                  );
                })}
                {/* Fill the last row: an unrendered remainder exposes the grid's
                    border-colored background as a grey slab in the light theme. */}
                {Array.from({ length: (7 - (lead + daysInMonth) % 7) % 7 }).map((_, i) => (
                  <div key={`t${i}`} className="newscal-cell blank" />
                ))}
              </div>
              )}

              {listItems.length === 0 ? (
                <div className="led-empty">{tx.emptyMonth}</div>
              ) : mode === "year" ? (
                <div className="newscal-list">
                  {byMonth.map(([key, items]) => (
                    <React.Fragment key={key}>
                      <div className="newscal-mh">
                        {new Date(`${key}-01T00:00:00`).toLocaleDateString(locale, { month: "long", year: "numeric" })}
                      </div>
                      {items.map(renderRow)}
                    </React.Fragment>
                  ))}
                </div>
              ) : (
                <div className="newscal-list">{listItems.map(renderRow)}</div>
              )}
            </>
          )}
        </>
      ) : view === "announcements" ? (
        <>
          <div className="newscal-bar">
            <input className="newscal-search" type="search" value={search}
              placeholder={tx.searchPh} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {!anns ? (
            <div className="led-empty">{tx.loading}</div>
          ) : anns.error ? (
            <div className="led-empty">{tx.error}</div>
          ) : annPage.total === 0 ? (
            <div className="led-empty">{tx.annEmpty}</div>
          ) : (
            <>
              <div className="dividend-table-wrap panel">
                <table className="dividend-table">
                  <thead>
                    <tr>
                      <th>{tx.th.org}</th>
                      <th>{tx.th.title}</th>
                      <th>{tx.th.pub}</th>
                      <th>{tx.th.meeting}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {annPage.slice.map((it, i) => {
                      const localizedTitle = localizedCalendarTitle(it, lang);
                      return (
                        <tr key={it.announcement_id || i}>
                          <td>{orgCell(it)}</td>
                          <td className="newscal-anntitle" title={it.title || undefined}>
                            {calendarAnnouncementPath(it) ? (
                              <a className="newscal-news-link" href={calendarAnnouncementPath(it)}
                                {...(onOpenAnnouncement ? { onClick: interceptNav(() => onOpenAnnouncement(it)) } : {})}>
                                {localizedTitle || "—"}
                              </a>
                            ) : localizedTitle || "—"}
                          </td>
                          <td className="muted" style={{ whiteSpace: "nowrap" }}>{fmtDate(it.pub_date)}</td>
                          <td style={{ whiteSpace: "nowrap" }}>
                            {fmtDate(it.meeting_date)}{fmtTime(it.meeting_date) ? ` · ${fmtTime(it.meeting_date)}` : ""}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <NewsCalPager {...annPage} size={pageSize} onPage={setPage} onSize={setPageSize} tx={tx} />
            </>
          )}
        </>
      ) : (
        <>
          <div className="newscal-bar">
            <div className="news-subtabs" role="group" aria-label={tx.views.dividends} style={{ margin: 0 }}>
              {["common", "preferred", "bond"].map((key) => (
                <button key={key} type="button"
                  className={`news-subtab ${divType === key ? "active" : ""}`}
                  aria-pressed={divType === key}
                  onClick={() => setDivType(key)}>
                  {tx.divTypes[key]}
                </button>
              ))}
            </div>
            <input className="newscal-search" type="search" value={search}
              placeholder={tx.searchPh} onChange={(e) => setSearch(e.target.value)} />
            {divItems.length > 0 && (
              <button type="button" className="ghost-btn" style={{ fontSize: 12 }} onClick={downloadCsv}>
                {tx.download}
              </button>
            )}
          </div>
          {!divs ? (
            <div className="led-empty">{tx.loading}</div>
          ) : divs.error ? (
            <div className="led-empty">{tx.error}</div>
          ) : divItems.length === 0 ? (
            <div className="led-empty">{tx.divEmpty}</div>
          ) : (
            <>
              <div className="dividend-table-wrap panel">
                <table className="dividend-table">
                  <thead>
                    <tr>
                      <th>{tx.th.issuer}</th>
                      {sortTh("decision", tx.th.decision, false)}
                      {sortTh("amount", tx.th.amount, true)}
                      {sortTh("percent", "%", true)}
                      <th>{tx.th.window}</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {divPage.slice.map((r, i) => {
                      const start = startOf(r);
                      const end = endOf(r);
                      return (
                        <tr key={r.filing_id || i}>
                          <td>{orgCell(r)}</td>
                          <td style={{ whiteSpace: "nowrap" }}>{fmtDate(r.decision_date)}</td>
                          <td className="dividend-num">{amountOf(r) ? fmtNum(amountOf(r)) : "—"}</td>
                          <td className="dividend-num muted">{pctOf(r) ? `${fmtNum(pctOf(r))}%` : "—"}</td>
                          <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                            {(start || end) ? `${fmtDate(start)} – ${fmtDate(end)}` : "—"}
                          </td>
                          <td>{r.link && <a href={r.link} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>→</a>}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <NewsCalPager {...divPage} size={pageSize} onPage={setPage} onSize={setPageSize} tx={tx} />
              <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>{tx.divNote}</p>
            </>
          )}
        </>
      )}
      <p className="muted" style={{ fontSize: 11, marginTop: 14 }}>{tx.source}</p>
    </div>
  );
}

function NewsView({ language, onOpenCompany, onOpenNews, onOpenAnnouncement, user, apiFetch }) {
  const tx = NEWS_TX[language] || NEWS_TX.ru;
  useTranslationTick();
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const [state, setState] = React.useState({ loading: true, error: false, items: [] });
  const [reloadKey, setReloadKey] = React.useState(0);
  // Kept in the URL so a tab can be linked and survives a reload — as a query,
  // not a path, because /news/{slug} is already the article route.
  const [tab, setTab] = React.useState(newsTabFromLocation);
  const [instrument, setInstrument] = React.useState(newsInstrumentFromLocation);
  React.useEffect(() => {
    const onPop = () => { setTab(newsTabFromLocation()); setInstrument(newsInstrumentFromLocation()); };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  // One writer for the query string: the tab and the instrument share it, and
  // two callbacks each rebuilding the URL from their own state dropped the
  // other's parameter every time either was pressed.
  const pushQuery = React.useCallback((nextTab, nextInstrument) => {
    const p = new URLSearchParams();
    if (nextTab !== "all") p.set("tab", nextTab);
    if (nextTab === "corporate" && nextInstrument !== "all") p.set("instrument", nextInstrument);
    const q = p.toString();
    try {
      window.history.replaceState({}, "", q ? `/news?${q}` : "/news");
    } catch { /* history is unavailable in some embedded views */ }
  }, []);
  const selectTab = React.useCallback((key) => {
    setTab(key);
    // Leaving Корпоративные drops the instrument: it is a filter on issuer
    // filings, and carrying it onto Экономика would ask macro copy which bonds
    // it names.
    const nextInstrument = key === "corporate" ? instrument : "all";
    setInstrument(nextInstrument);
    pushQuery(key, nextInstrument);
  }, [instrument, pushQuery]);
  const selectInstrument = React.useCallback((key) => {
    setInstrument(key);
    pushQuery("corporate", key);
  }, [pushQuery]);

  React.useEffect(() => {
    let alive = true;
    // «Календарь» is not a reading mode over the feed — it renders its own
    // component below and fetches its own endpoints; asking the feed for it
    // would flash a skeleton over a page that never uses the answer.
    if (tab === "calendar") { setState({ loading: false, error: false, items: [] }); return undefined; }
    setState({ loading: true, error: false, items: [] });
    const group = (NEWS_TABS.find((t) => t.key === tab) || {}).type;
    const inst = tab === "corporate" && instrument !== "all" ? `&instrument=${instrument}` : "";
    fetch(`/api/news/feed?limit=60&days=30${group ? `&type=${group}` : ""}${inst}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setState({ loading: false, error: !d || !d.ok, items: (d && d.items) || [] }); })
      .catch(() => { if (alive) setState({ loading: false, error: true, items: [] }); });
    return () => { alive = false; };
  }, [reloadKey, tab, instrument]);

  const { loading, error, items } = state;
  // Which story gets the masthead when the top-ranked one cannot be illustrated
  // — see lib/newsfeed.js. Nothing is dropped: the story that would have led
  // simply leads the stack instead.
  const leadIndex = React.useMemo(() => pickLeadIndex(items), [items]);
  const lead = items[leadIndex];
  const stack = items.filter((_, i) => i !== leadIndex);
  // The main column follows the API's impact ranking; the rail is literally "latest", so it
  // needs its own chronological copy rather than the top of the ranked list.
  const latest = React.useMemo(
    () => [...items].sort((a, b) => String(b.published_at || "").localeCompare(String(a.published_at || ""))),
    [items],
  );
  const mood = feedSentiment(items);
  const moodLabel = mood.cls === "pos" ? etx.moodPos : mood.cls === "neg" ? etx.moodNeg : etx.moodNeu;
  const secondary = stack.slice(0, 2);
  const priorityItems = lead ? [lead, ...secondary] : secondary;
  const feedItems = latest.filter((item) => !priorityItems.includes(item));
  const focus = React.useMemo(() => newsDeskFocus(items), [items]);
  const dtx = tx.desk || NEWS_TX.ru.desk;
  const updated = latest[0] && latest[0].published_at ? newsRelTime(latest[0].published_at, language) : "";

  return (
    <div className="news-view led newsdesk">
      <header className="newsdesk-head">
        <div>
          <h1>{tx.title}</h1>
          <p>{(tab === "corporate" && instrument !== "all" && tx.instrumentHint && tx.instrumentHint[instrument])
            || (tx.tabHint && tx.tabHint[tab]) || tx.subtitle}</p>
        </div>
        {!loading && tab !== "calendar" && (
          <div className="newsdesk-updated">
            {updated && <span>{dtx.updated} {updated}</span>}
            <span>{items.length} {dtx.stories}</span>
          </div>
        )}
      </header>

      <nav className="newsdesk-tabs" aria-label={tx.title}>
        {NEWS_TABS.map((t) => (
          <button key={t.key} type="button"
            className={`newsdesk-tab ${tab === t.key ? "active" : ""}`}
            aria-current={tab === t.key ? "page" : undefined}
            onClick={() => selectTab(t.key)}>
            {(tx.tabs && tx.tabs[t.key]) || t.key}
          </button>
        ))}
      </nav>

      {/* A second row, not three more tabs beside the first: this narrows
          «Корпоративные», it is not a fourth peer of it. */}
      {tab === "corporate" && (
        <div className="newsdesk-subtabs" role="group" aria-label={(tx.tabs && tx.tabs.corporate) || "corporate"}>
          {NEWS_INSTRUMENTS.map((key) => (
            <button key={key} type="button"
              className={`newsdesk-subtab ${instrument === key ? "active" : ""}`}
              aria-pressed={instrument === key}
              onClick={() => selectInstrument(key)}>
              {(tx.instruments && tx.instruments[key]) || key}
            </button>
          ))}
        </div>
      )}

      {user && user.is_admin && apiFetch && (
        <NewsAdminPanel language={language} apiFetch={apiFetch} onStored={() => setReloadKey((k) => k + 1)} />
      )}

      {tab === "calendar" ? (
        <NewsCalendarView
          language={language}
          onOpenCompany={onOpenCompany}
          onOpenAnnouncement={onOpenAnnouncement}
        />
      ) : loading ? (
        <div className="newsdesk-loading" aria-label={tx.loadingText}>
          <div className="newsdesk-loading-lead" />
          <div className="newsdesk-loading-side" />
          <div className="newsdesk-loading-feed" />
        </div>
      ) : error ? (
        <div className="led-empty">{tx.error}</div>
      ) : !items.length ? (
        <div className="led-empty">
          {tab === "corporate" && instrument !== "all"
            ? (tx.emptyInstrument || tx.emptyTab || tx.empty)
            : tab === "all" ? tx.empty : (tx.emptyTab || tx.empty)}
        </div>
      ) : (
        <div className="newsdesk-board">
          <section className="newsdesk-priority" aria-label={dtx.main}>
            {lead && <NewsDeskPriorityStory item={lead} language={language} variant="lead" onOpen={onOpenNews} />}
            <div className="newsdesk-secondary">
              {secondary.map((item, index) => (
                <NewsDeskPriorityStory key={item.id || item.url || index} item={item} language={language} variant="secondary" onOpen={onOpenNews} />
              ))}
            </div>
            <aside className="newsdesk-mood">
              <h2>{dtx.marketNow}</h2>
              <div className="newsdesk-mood-score"><strong className={mood.cls}>{(mood.avg >= 0 ? "+" : "") + mood.avg.toFixed(2)}</strong><span>{dtx.days30}</span></div>
              <div className="newsdesk-mood-row"><span>{dtx.positive}</span><b>{mood.counts.positive}</b></div>
              <div className="newsdesk-mood-row"><span>{dtx.neutral}</span><b>{mood.counts.neutral}</b></div>
              <div className="newsdesk-mood-row"><span>{dtx.negative}</span><b>{mood.counts.negative}</b></div>
              <small>{moodLabel}</small>
            </aside>
          </section>

          <section className="newsdesk-feed-layout">
            <main className="newsdesk-feed">
              <div className="newsdesk-feed-head">
                <span className="newsdesk-live-dot" aria-hidden="true" />
                <h2>{dtx.latest}</h2>
                <span>{dtx.important}</span>
              </div>
              <div className="newsdesk-rows">
                {feedItems.map((item, index) => (
                  <NewsDeskRow key={item.id || item.url || index} item={item} language={language} onOpen={onOpenNews} />
                ))}
                {!feedItems.length && <div className="newsdesk-feed-empty">{tx.emptyTab || tx.empty}</div>}
              </div>
            </main>
            <aside className="newsdesk-side">
              {focus.length > 0 && (
                <section className="newsdesk-side-section">
                  <h2>{dtx.focus}</h2>
                  {focus.map(([ticker, count]) => (
                    <button key={ticker} type="button" className="newsdesk-focus-row" onClick={() => onOpenCompany && onOpenCompany(ticker)}>
                      <strong>{ticker}</strong><span>{count} {dtx.events}</span>
                    </button>
                  ))}
                </section>
              )}
              <section className="newsdesk-side-section newsdesk-calendar-callout">
                <h2>{dtx.calendar}</h2>
                <p>{dtx.calendarCopy}</p>
                <button type="button" onClick={() => selectTab("calendar")}>{dtx.openCalendar} →</button>
              </section>
            </aside>
          </section>
        </div>
      )}

      {/* The filings timeline is the raw disclosure record for the corporate
          reading mode. It follows the edited board instead of interrupting its
          priority hierarchy; the Акции/Облигации control still narrows only the
          stories above, while this record keeps its own filing-kind controls. */}
      {tab === "corporate" && (
        <div className="newsdesk-disclosures">
          <MarketEventsFeed lang={normalizeLanguage(language)} onOpenCompany={onOpenCompany} />
        </div>
      )}
    </div>
  );
}

// ── /news/{id}: one story on its own page ────────────────────────────────────
// Everything here comes from the row the collector already stored (headline, our own
// summary, the classifier's tone / impact / direction, issuer links). Opening a story
// is a plain database read — no model is called, so the §3.11 LLM budget is untouched.
// The source's article text is never stored and never shown: the page attributes the
// outlet and links out for the full text.
const NEWS_ARTICLE_TX = {
  ru: {
    back: "Все новости", loading: "Загружаем новость…",
    notFound: "Новость не найдена или уже недоступна.", error: "Не удалось загрузить новость.",
    summaryNote: "Краткое изложение подготовлено платформой на основе публикации источника. Полный текст — на сайте источника.",
    detailNote: "Изложение подготовлено платформой своими словами по публикации источника: это не текст источника. Оригинал и фотографии — на сайте источника.",
    noSummary: "Краткого изложения нет — откройте публикацию у источника.",
    readSource: "Читать в источнике", signal: "Оценка влияния", tone: "Тональность",
    impact: "Возможное влияние", direction: "Направление", relevance: "Релевантность рынку",
    dir: { up: "рост", down: "снижение", mixed: "смешанное", unclear: "неясно" },
    impactNone: "не значимо", tickers: "Упомянутые эмитенты",
    tickersHint: "Откройте карточку эмитента — котировки, отчётность и его новости.",
    sectors: "Секторы", related: "По теме", source: "Источник",
    sourceLead: "Как сообщает источник", about: "О публикации",
    origTitle: "Заголовок источника",
    translate: "Перевести заголовок средствами браузера",
    translateHint: "Перевод выполняется офлайн, самим браузером. При первом запуске он загрузит языковой пакет; текст никуда не отправляется.",
    machineTitle: "Заголовок источника, переведён браузером",
    published: "Опубликовано", added: "В ленте с", langLabel: "Язык",
    langs: { ru: "русский", uz: "узбекский", en: "английский" },
    filingDetail: "Из раскрытия эмитента",
    disclosureNote: "Это раскрытие самого эмитента на портале openinfo.uz. Портал не публикует отдельную страницу для каждого существенного факта — ссылка открывает карточку эмитента со списком его раскрытий.",
    openDisclosure: "Карточка эмитента на openinfo.uz",
    issuers: "Эмитенты в этой новости", price: "Цена", change: "Изм.",
    tone90: "Тон · 90 дн", basedOn: "публикаций за 90 дней",
    moreNews: "Другие новости эмитента", openCompany: "Открыть карточку эмитента",
    rxTitle: "Котировки вокруг публикации", rxVolume: "Объём к среднему",
    rxSince: "С публикации",
    rxNoSession: "После публикации торгов по бумаге ещё не было.",
    rxSameDay: "Сессия того же дня — публикация могла выйти и после её закрытия.",
    rxIlliquid: "Бумага торгуется редко: движение может отражать одну сделку.",
    rxNote: "Это два закрытия биржи и даты, к которым они относятся, — совпадение по времени, а не доказанная реакция рынка на эту новость.",
  },
  en: {
    back: "All news", loading: "Loading the story…",
    notFound: "This story was not found, or is no longer available.", error: "Could not load the story.",
    summaryNote: "This summary was prepared by the platform from the source's publication. The full text is on the source's site.",
    detailNote: "This account was written by the platform in its own words from the source's publication — it is not the source's text. The original and its photographs are on the source's site.",
    noSummary: "No summary available — open the publication at the source.",
    readSource: "Read at the source", signal: "Impact assessment", tone: "Tone",
    impact: "Possible impact", direction: "Direction", relevance: "Market relevance",
    dir: { up: "up", down: "down", mixed: "mixed", unclear: "unclear" },
    impactNone: "not material", tickers: "Issuers mentioned",
    tickersHint: "Open an issuer to see its quotes, filings and news.",
    sectors: "Sectors", related: "Related", source: "Source",
    sourceLead: "As the source reports", about: "About this item",
    origTitle: "The source's headline",
    translate: "Translate the headline in your browser",
    translateHint: "The translation runs offline, in the browser itself. The first run downloads a language pack; the text is never sent anywhere.",
    machineTitle: "The source's headline, translated by your browser",
    published: "Published", added: "In the feed since", langLabel: "Language",
    langs: { ru: "Russian", uz: "Uzbek", en: "English" },
    filingDetail: "From the filing",
    disclosureNote: "This is the issuer's own filing on the openinfo.uz portal. The portal publishes no standalone page per material fact — the link opens the issuer's card, which lists its disclosures.",
    openDisclosure: "Issuer page on openinfo.uz",
    issuers: "Issuers in this story", price: "Price", change: "Chg.",
    tone90: "Tone · 90d", basedOn: "items over 90 days",
    moreNews: "More from this issuer", openCompany: "Open the issuer page",
    rxTitle: "Quotes around the publication", rxVolume: "Volume vs average",
    rxSince: "Since publication",
    rxNoSession: "The security has not traded since this was published.",
    rxSameDay: "Same-day session — the story may also have come out after it closed.",
    rxIlliquid: "This security trades rarely: the move may rest on a single trade.",
    rxNote: "These are two exchange closes and the dates they belong to — a coincidence in time, not a demonstrated market reaction to this story.",
  },
  uz: {
    back: "Barcha yangiliklar", loading: "Yangilik yuklanmoqda…",
    notFound: "Yangilik topilmadi yoki endi mavjud emas.", error: "Yangilikni yuklab bo'lmadi.",
    summaryNote: "Qisqacha bayon platforma tomonidan manba nashri asosida tayyorlangan. To'liq matn manba saytida.",
    detailNote: "Bayon platforma tomonidan manba nashri asosida o'z so'zlari bilan yozilgan — bu manbaning matni emas. Asl nashr va suratlar manba saytida.",
    noSummary: "Qisqacha bayon yo'q — nashrni manbada oching.",
    readSource: "Manbada o'qish", signal: "Ta'sir bahosi", tone: "Ohang",
    impact: "Mumkin bo'lgan ta'sir", direction: "Yo'nalish", relevance: "Bozorga aloqadorlik",
    dir: { up: "o'sish", down: "pasayish", mixed: "aralash", unclear: "noaniq" },
    impactNone: "ahamiyatsiz", tickers: "Tilga olingan emitentlar",
    tickersHint: "Emitent kartasini oching — kotirovkalar, hisobotlar va yangiliklar.",
    sectors: "Sektorlar", related: "Mavzu bo'yicha", source: "Manba",
    sourceLead: "Manba xabar qilishicha", about: "Nashr haqida",
    origTitle: "Manba sarlavhasi",
    translate: "Sarlavhani brauzer vositasida tarjima qilish",
    translateHint: "Tarjima brauzerning o'zida, oflayn bajariladi. Birinchi ishga tushirishda til paketi yuklanadi; matn hech qayerga yuborilmaydi.",
    machineTitle: "Manba sarlavhasi, brauzer tarjimasi",
    published: "E'lon qilingan", added: "Lentada", langLabel: "Til",
    langs: { ru: "rus", uz: "o'zbek", en: "ingliz" },
    filingDetail: "Emitent oshkor qilishidan",
    disclosureNote: "Bu emitentning openinfo.uz portalidagi o'z oshkor qilishi. Portal har bir muhim fakt uchun alohida sahifa chop etmaydi — havola emitent kartasini ochadi.",
    openDisclosure: "openinfo.uz dagi emitent kartasi",
    issuers: "Ushbu yangilikdagi emitentlar", price: "Narx", change: "O'zg.",
    tone90: "Ohang · 90 kun", basedOn: "90 kunlik nashrlar",
    moreNews: "Emitentning boshqa yangiliklari", openCompany: "Emitent kartasini ochish",
    rxTitle: "E'lon atrofidagi kotirovkalar", rxVolume: "Hajm — o'rtachaga nisbatan",
    rxSince: "E'londan beri",
    rxNoSession: "E'londan keyin bu qog'oz bo'yicha savdo bo'lmagan.",
    rxSameDay: "O'sha kungi sessiya — e'lon u yopilgandan keyin ham chiqqan bo'lishi mumkin.",
    rxIlliquid: "Qog'oz kam savdo qilinadi: harakat bitta bitimga tayanishi mumkin.",
    rxNote: "Bu — birjaning ikki yopilishi va ular tegishli sanalar: vaqt bo'yicha mos kelish, bu yangilikka bozor reaksiyasi isboti emas.",
  },
};

function newsAbsTime(dateStr, language) {
  if (!dateStr) return "";
  const raw = String(dateStr).replace(" ", "T");
  const d = new Date(raw);
  if (isNaN(d.getTime())) return String(dateStr);
  const loc = language === "en" ? "en-US" : language === "uz" ? "uz-UZ" : "ru-RU";
  const opts = { day: "numeric", month: "long", year: "numeric" };
  if (raw.length > 10) { opts.hour = "2-digit"; opts.minute = "2-digit"; }
  return d.toLocaleString(loc, opts);
}

function newsHost(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

// We store two short texts per item: the source's own lead-in (`snippet`, from its feed)
// and our one-sentence `summary_ru`. They are usually complementary — the lead-in often
// keeps a detail the summary drops — so the page shows both, unless the summary already
// says the same thing, in which case repeating it would only pad the page.
function newsAddsDetail(snippet, summary) {
  const words = (s) => new Set(
    (String(s || "").toLowerCase().match(/[\wЀ-ӿ]+/g) || []).filter((w) => w.length > 3));
  const lead = words(snippet);
  if (lead.size < 4) return false;
  const ours = words(summary);
  let shared = 0;
  lead.forEach((w) => { if (ours.has(w)) shared += 1; });
  return shared / lead.size < 0.7;
}

// Issuer context — the depth a stock platform can add where a news site cannot, and the
// answer to what a reader actually opened the story for: what does this mean for the shares.
// For every issuer the story names, its quote, the 90-day tone of its coverage and its other
// recent headlines. Assembled entirely from what we already serve — `/api/securities` is
// loaded app-wide (so a cold deep link has prices too) and `/api/news/ticker/{t}` is a plain
// DB read — so it adds no model call and no source fetch.
// A short date for the two closes the reaction block compares — the year is noise
// when both sessions are days apart, and the full stamp already sits in the byline.
function newsShortDay(dateStr, language) {
  if (!dateStr) return "";
  const d = new Date(String(dateStr).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(dateStr);
  const loc = language === "en" ? "en-US" : language === "uz" ? "uz-UZ" : "ru-RU";
  return d.toLocaleDateString(loc, { day: "numeric", month: "short" });
}

// What the tagged issuers' prices did around the story. Loaded on its own, after the
// article text: the first call for an issuer reaches openinfo for the full series and
// the reader should not wait on that to read the story.
//
// The wording is the point. This block never says the news moved the price — it shows
// two dated closes and says so underneath, because that is all the data supports.
function NewsPriceReaction({ newsId, language, securitiesMap, onOpenCompany, tx }) {
  const [state, setState] = React.useState({ loading: true, items: [] });
  useTranslationTick();

  React.useEffect(() => {
    let alive = true;
    setState({ loading: true, items: [] });
    fetch(`/api/news/item/${encodeURIComponent(newsId)}/reaction`)
      .then((r) => r.json())
      .then((d) => { if (alive) setState({ loading: false, items: (d && d.ok && d.items) || [] }); })
      .catch(() => { if (alive) setState({ loading: false, items: [] }); });
    return () => { alive = false; };
  }, [newsId]);

  // An issuer we could not price at all adds nothing to the page — the issuer block
  // above already names it. Only rows that carry a real comparison are shown.
  const rows = state.items.filter((r) => r.status === "ok" || r.status === "no_session_yet");
  if (state.loading || !rows.length) return null;
  // Most stories are same-day, so printing that caveat on every row would turn it into
  // wallpaper. It belongs with the note that already qualifies the whole block.
  const sameDay = rows.some((r) => r.after && r.after.same_day);

  return (
    <section className="led-art-block led-rx">
      <h3 className="led-panel-h">{tx.rxTitle}</h3>
      <div className="led-rx-grid">
        {rows.map((r) => {
          const sec = (securitiesMap && securitiesMap[r.ticker]) || null;
          const change = r.change && typeof r.change.value === "number" ? r.change.value : null;
          const since = r.since && typeof r.since.value === "number" ? r.since.value : null;
          const ratio = r.volume_vs_normal && typeof r.volume_vs_normal.value === "number"
            ? r.volume_vs_normal.value : null;
          const cls = change == null ? "" : change > 0 ? "pos" : change < 0 ? "neg" : "";
          return (
            <article className="led-rx-row" key={r.ticker}>
              <button type="button" className="led-rx-tk" title={tx.openCompany}
                onClick={() => onOpenCompany && onOpenCompany(r.ticker)}>
                <b>{r.ticker}</b>{sec && sec.name ? <span>{sec.name}</span> : null}
              </button>
              {r.status === "no_session_yet" ? (
                <p className="led-rx-none">{tx.rxNoSession}</p>
              ) : (
                <>
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
                    {ratio != null && (
                      <div><dt>{tx.rxVolume}</dt><dd>{`×${ratio.toFixed(1)}`}</dd></div>
                    )}
                    {since != null && r.sessions_after > 1 && (
                      <div>
                        <dt>{tx.rxSince}</dt>
                        <dd className={since > 0 ? "pos" : since < 0 ? "neg" : ""}>
                          {formatSignedPercent(since)}
                          <span className="led-rx-sessions">
                            {` · ${r.sessions_after} ${sessionCountLabel(r.sessions_after, language)}`}
                          </span>
                        </dd>
                      </div>
                    )}
                  </dl>
                  {r.data_tier === "illiquid" && <p className="led-rx-hedge">{tx.rxIlliquid}</p>}
                </>
              )}
            </article>
          );
        })}
      </div>
      <p className="led-art-hint">{sameDay ? `${tx.rxNote} ${tx.rxSameDay}` : tx.rxNote}</p>
    </section>
  );
}

function NewsIssuerContext({ tickers, currentId, language, securitiesMap, onOpenCompany, onOpenNews, tx }) {
  const [byTicker, setByTicker] = React.useState({});
  useTranslationTick();
  // Issuers we have a quote for lead: a story naming four bond series should not push the
  // bank it is actually about off the list.
  const keys = React.useMemo(() => {
    const known = (t) => (securitiesMap && securitiesMap[t] ? 0 : 1);
    return [...tickers].sort((a, b) => known(a) - known(b)).slice(0, 3);
  }, [tickers, securitiesMap]);
  const keyList = keys.join(",");

  React.useEffect(() => {
    let alive = true;
    setByTicker({});
    if (!keys.length) return undefined;
    Promise.all(keys.map((t) =>
      fetch(`/api/news/ticker/${encodeURIComponent(t)}?limit=6&days=90&exclude_news_id=${encodeURIComponent(currentId)}`)
        .then((r) => r.json())
        .then((d) => [t, d && d.ok ? d : null])
        .catch(() => [t, null])))
      .then((pairs) => { if (alive) setByTicker(Object.fromEntries(pairs)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyList, currentId]);

  if (!keys.length) return null;
  return (
    <section className="led-art-block">
      <h3 className="led-panel-h">{tx.issuers}</h3>
      <div className="led-iss-grid">
        {keys.map((tk) => {
          const sec = (securitiesMap && securitiesMap[tk]) || null;
          const data = byTicker[tk];
          const sentiment = data && data.sentiment;
          const others = ((data && data.items) || [])
            .filter((n) => String(n.id) !== String(currentId)).slice(0, 3);
          const last = sec ? Number(sec.last_price) : NaN;
          const close = sec ? Number(sec.close_price) : NaN;
          const chg = Number.isFinite(last) && Number.isFinite(close) && close
            ? ((last - close) / close) * 100 : null;
          const tone = sentiment && typeof sentiment.weighted_tone === "number"
            ? sentiment.weighted_tone : null;
          const toneCls = tone == null ? "" : tone > 0.15 ? "pos" : tone < -0.15 ? "neg" : "";
          const chgCls = chg == null ? "" : chg > 0 ? "pos" : chg < 0 ? "neg" : "";
          return (
            <article className="led-iss" key={tk}>
              <button type="button" className="led-iss-head" title={tx.openCompany}
                onClick={() => onOpenCompany && onOpenCompany(tk)}>
                {sec && sec.logo_url && (
                  <img className="led-iss-logo" src={sec.logo_url} alt="" loading="lazy"
                    onError={(e) => { e.currentTarget.style.display = "none"; }} />
                )}
                <span className="led-iss-name">{(sec && sec.name) || tk}</span>
                <span className="led-iss-tk">{tk}</span>
              </button>
              <dl className="led-iss-stats">
                <div><dt>{tx.price}</dt><dd>{Number.isFinite(last) ? formatMarketNumber(last, language) : "—"}</dd></div>
                <div><dt>{tx.change}</dt><dd className={chgCls}>{chg == null ? "—" : formatSignedPercent(chg)}</dd></div>
                <div><dt>{tx.tone90}</dt><dd className={toneCls}>{tone == null ? "—" : `${tone >= 0 ? "+" : ""}${tone.toFixed(2)}`}</dd></div>
              </dl>
              {sentiment && sentiment.count > 0 && (
                <div className="led-iss-basis">{sentiment.count} {tx.basedOn}</div>
              )}
              {others.length > 0 && (
                <div className="led-iss-news">
                  <h4 className="led-panel-h">{tx.moreNews}</h4>
                  {others.map((n) => (
                    <a key={n.id} className="led-lt" href={newsArticlePath(n)}
                      {...(n.id && onOpenNews
                        ? { onClick: interceptNav(() => onOpenNews(n)) }
                        : { target: "_blank", rel: "noopener noreferrer" })}>
                      <span className={`led-dot ${_TONE_CLS[n.tone] || "neu"}`} />
                      <span className="led-lt-t">{edHeadlineCached(n, language).text}</span>
                      <span className="led-lt-s">{n.source}{n.published_at ? ` · ${newsRelTime(n.published_at, language)}` : ""}</span>
                    </a>
                  ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
      <p className="led-art-hint">{tx.tickersHint}</p>
    </section>
  );
}

const ANNOUNCEMENT_ARTICLE_TX = {
  ru: {
    back: "К календарю", eyebrow: "Объявление OpenInfo", details: "Текст объявления",
    organization: "Информация об организации", facts: "Сведения",
    original: "Открыть оригинал", pdf: "Скачать PDF", source: "Источник: openinfo.uz",
    loading: "Загружаем объявление…", notFound: "Объявление не найдено.",
    error: "Не удалось загрузить объявление. Попробуйте позже.",
  },
  en: {
    back: "Back to calendar", eyebrow: "OpenInfo announcement", details: "Announcement",
    organization: "Organization information", facts: "Details",
    original: "Open original", pdf: "Download PDF", source: "Source: openinfo.uz",
    loading: "Loading announcement…", notFound: "Announcement not found.",
    error: "Could not load the announcement. Please try again later.",
  },
  uz: {
    back: "Taqvimga qaytish", eyebrow: "OpenInfo e'loni", details: "E'lon matni",
    organization: "Tashkilot haqida ma'lumot", facts: "Ma'lumotlar",
    original: "Aslini ochish", pdf: "PDF-ni yuklab olish", source: "Manba: openinfo.uz",
    loading: "E'lon yuklanmoqda…", notFound: "E'lon topilmadi.",
    error: "E'lonni yuklab bo'lmadi. Keyinroq qayta urinib ko'ring.",
  },
};

function AnnouncementArticleView({ announcementId, language, onBack }) {
  const lang = normalizeLanguage(language);
  const tx = ANNOUNCEMENT_ARTICLE_TX[lang] || ANNOUNCEMENT_ARTICLE_TX.ru;
  const [state, setState] = React.useState({ loading: true, error: "", item: null });

  React.useEffect(() => {
    let alive = true;
    setState({ loading: true, error: "", item: null });
    window.scrollTo({ top: 0, behavior: "auto" });
    fetch(`/api/news/calendar/announcements/${encodeURIComponent(announcementId)}?language=${lang}`)
      .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))
      .then(({ status, body }) => {
        if (!alive) return;
        if (body && body.ok && body.item) {
          setState({ loading: false, error: "", item: body.item });
        } else {
          setState({ loading: false, error: status === 404 || status === 422 ? "notFound" : "error", item: null });
        }
      })
      .catch(() => { if (alive) setState({ loading: false, error: "error", item: null }); });
    return () => { alive = false; };
  }, [announcementId, lang]);

  const back = (
    <a className="led-back" href="/news?tab=calendar" onClick={interceptNav(onBack)}>← {tx.back}</a>
  );
  if (state.loading) {
    return (
      <div className="news-view led announcement-article">
        {back}
        <div className="led-skel-row" aria-label={tx.loading} />
        <div className="led-skel-lead" />
      </div>
    );
  }
  if (state.error || !state.item) {
    return (
      <div className="news-view led announcement-article">
        {back}
        <div className="led-empty">{state.error === "notFound" ? tx.notFound : tx.error}</div>
      </div>
    );
  }

  const item = state.item;
  const metadata = Array.isArray(item.metadata) ? item.metadata : [];
  const content = Array.isArray(item.content) ? item.content : [];
  const organizationDetails = Array.isArray(item.organization_details) ? item.organization_details : [];
  return (
    <div className="news-view led announcement-article">
      {back}
      <div className="announcement-layout">
        <main className="announcement-main">
          <article className="led-art">
            <div className="led-eyebrow"><span className="led-cat">{tx.eyebrow}</span></div>
            <h1 className="led-art-title">{item.title}</h1>
            {item.organization && <p className="announcement-company">{item.organization}</p>}

            {metadata.length > 0 && (
              <dl className="announcement-meta" aria-label={tx.facts}>
                {metadata.map((field, i) => (
                  <div key={`${field.label}-${i}`}>
                    <dt>{field.label}</dt>
                    <dd>{field.value}</dd>
                  </div>
                ))}
              </dl>
            )}

            {content.length > 0 && (
              <section className="announcement-body">
                <h2 className="led-panel-h">{tx.details}</h2>
                {content.map((block, i) => (
                  block.kind === "heading"
                    ? <h3 key={i}>{block.text}</h3>
                    : <p key={i} className={block.kind === "list_item" ? "is-list-item" : undefined}>{block.text}</p>
                ))}
              </section>
            )}

            <div className="led-art-source announcement-actions">
              <p className="led-art-note">{tx.source}</p>
              <div>
                {item.pdf_url && (
                  <a className="announcement-secondary" href={item.pdf_url} target="_blank" rel="noopener noreferrer nofollow">
                    {tx.pdf}
                  </a>
                )}
                {item.source_url && (
                  <a className="led-art-cta" href={item.source_url} target="_blank" rel="noopener noreferrer nofollow">
                    {tx.original}<span className="led-art-host">openinfo.uz</span>
                  </a>
                )}
              </div>
            </div>
          </article>
        </main>

        {organizationDetails.length > 0 && (
          <aside className="announcement-rail">
            <div className="led-panel">
              <h2 className="led-panel-h">{tx.organization}</h2>
              <dl className="led-sig led-sig--rows">
                {organizationDetails.map((field, i) => (
                  <div key={`${field.label}-${i}`}><dt>{field.label}</dt><dd>{field.value}</dd></div>
                ))}
              </dl>
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}

function NewsArticleView({ newsId, language, securitiesMap, onOpenCompany, onOpenNews, onBack }) {
  const tx = NEWS_ARTICLE_TX[language] || NEWS_ARTICLE_TX.ru;
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const [state, setState] = React.useState({ loading: true, error: "", data: null });
  const [imgOk, setImgOk] = React.useState(true);
  // A picture narrower than the column it sits in is served at its own size instead of being
  // blown up to fit. The collector now swaps a feed's thumbnail for the full-size original
  // where the CMS keeps one (uza.uz shipped 320px), but some sources simply have no larger
  // file, and a stretched 320px photo is the first thing a reader notices.
  const [imgSmall, setImgSmall] = React.useState(false);
  // Above the loading/error returns below, because hooks cannot sit behind one. The hook
  // handles a null item by doing nothing, which is what the loading state needs anyway.
  const browser = useBrowserHeadline(state.data ? state.data.item : null, language);

  React.useEffect(() => {
    let alive = true;
    setState({ loading: true, error: "", data: null });
    setImgOk(true);
    setImgSmall(false);
    window.scrollTo({ top: 0, behavior: "auto" });
    fetch(`/api/news/item/${encodeURIComponent(newsId)}`)
      .then(async (r) => ({ status: r.status, body: await r.json().catch(() => null) }))
      .then(({ status, body }) => {
        if (!alive) return;
        if (body && body.ok) setState({ loading: false, error: "", data: body });
        // 422 = a hand-typed /news/{something-that-is-not-an-id}: still "no such story".
        else setState({ loading: false, error: status === 404 || status === 422 ? "notFound" : "error", data: null });
      })
      .catch(() => { if (alive) setState({ loading: false, error: "error", data: null }); });
    return () => { alive = false; };
  }, [newsId]);

  const back = (
    <a className="led-back" href={VIEW_PATHS.news} onClick={interceptNav(onBack)}>← {tx.back}</a>
  );

  if (state.loading) {
    return (
      <div className="news-view led">
        {back}
        <div className="led-cols">
          <div className="led-main"><div className="led-skel-row" /><div className="led-skel-lead" /><div className="led-skel-row" /></div>
          <aside className="led-rail"><div className="led-skel-panel" /></aside>
        </div>
      </div>
    );
  }
  if (state.error || !state.data) {
    return (
      <div className="news-view led">
        {back}
        <div className="led-empty">{state.error === "notFound" ? tx.notFound : tx.error}</div>
      </div>
    );
  }

  const { item, related = [], disclaimer } = state.data;
  const head = edHeadline(item, language, browser.machine);
  const summary = edSummary(item, language);
  // Same rule as the card: when the headline above is already our summary, the lead slot
  // carries the source's own headline instead of repeating it. Once the browser has
  // translated the real headline the summary is no longer a duplicate, so it comes back.
  const lead = head.original && !head.machine ? "" : (summary || tx.noSummary);
  // An openinfo item is a filing, not an article: the portal has no page for a single
  // material fact (verified — /facts/{id}, /fact/{id} and /organizations/{org}/facts/{id}
  // all 404), so its link can only reach the issuer's card. Promising "the full text at the
  // source" there would be a lie, so the call to action says what the link actually does.
  const isDisclosure = item.source_id === "openinfo_facts";
  // Only when the snippet is not already doing duty as the lead paragraph above.
  // For a filing the stored text is not a quote from an outlet — it is the disclosure's own
  // figures (dividend per share, percent actually paid, the payment window), which the summary
  // only paraphrases. Those numbers are the whole point, so they are shown unconditionally
  // rather than being suppressed as a near-duplicate.
  // Our own retelling of the source's article, in paragraphs. When it exists it IS the body
  // of the page, and the source's one-sentence teaser below would only repeat its opening.
  const detail = edDetail(item, language);
  const sourceLead = summary && item.snippet
    && (isDisclosure || (!detail.length && newsAddsDetail(item.snippet, summary)))
    ? item.snippet : "";
  const toneCls = _TONE_CLS[item.tone] || "neu";
  const host = newsHost(item.url);
  const tickers = Array.isArray(item.tickers) ? item.tickers : [];
  const sectors = Array.isArray(item.sectors) ? item.sectors : [];
  const relevancePct = typeof item.relevance_score === "number"
    ? `${Math.round(Math.max(0, Math.min(item.relevance_score, 1)) * 100)}%` : null;
  const toneScore = typeof item.tone_score === "number"
    ? `${item.tone_score >= 0 ? "+" : ""}${item.tone_score.toFixed(2)}` : "";

  return (
    <div className="news-view led">
      {back}
      <div className="led-cols">
        <main className="led-main">
          <article className="led-art">
            <div className="led-eyebrow">
              <span className="led-cat">{etx.cat[item.type] || item.type}</span>
              {item.tone && <><span className="led-sep">·</span><span className={`led-tone ${toneCls}`}>{etx.tone[item.tone] || item.tone}</span></>}
              {item.impact && item.impact !== "none" && <><span className="led-sep">·</span><span className="led-imp">{etx.impact[item.impact] || item.impact}</span></>}
            </div>
            <h1 className="led-art-title">{head.text}</h1>
            <div className="led-art-byline">
              {item.source && <b>{item.source}</b>}
              {item.published_at && <span>{newsAbsTime(item.published_at, language)}</span>}
              {item.published_at && <span className="led-art-rel">{newsRelTime(item.published_at, language)}</span>}
            </div>

            {item.image_url && imgOk && (
              <div className={`led-figure led-art-figure${imgSmall ? " is-small" : ""}`}>
                <img
                  src={item.image_url}
                  alt=""
                  loading="lazy"
                  onError={() => setImgOk(false)}
                  onLoad={(e) => setImgSmall((e.target.naturalWidth || 0) < 760)}
                />
              </div>
            )}

            {lead && <p className="led-art-lead">{lead}</p>}

            {detail.length > 0 && (
              <div className="led-art-body">
                {detail.map((para, i) => <p key={i}>{para}</p>)}
              </div>
            )}

            {head.original && (
              <section className="led-art-quote">
                <h3 className="led-panel-h">{head.machine ? tx.machineTitle : tx.origTitle}</h3>
                <p className="led-orig"><span className="led-lang">{head.lang}</span>{head.original}</p>
                {/* Offered only when the browser HAS the translator but not yet this
                    language pack. Downloading one is a real cost and Chrome requires a
                    gesture for it, so it is the reader's call, remembered afterwards. */}
                {browser.offer && (
                  <div className="led-mt-offer">
                    <button type="button" className="led-mt-btn" onClick={browser.request}>
                      {tx.translate}
                    </button>
                    <span className="led-mt-hint">{tx.translateHint}</span>
                  </div>
                )}
              </section>
            )}

            {sourceLead && (
              <section className="led-art-quote">
                <h3 className="led-panel-h">{isDisclosure ? tx.filingDetail : tx.sourceLead}</h3>
                <p>{sourceLead}</p>
              </section>
            )}

            <div className="led-art-source">
              <p className="led-art-note">
                {isDisclosure ? tx.disclosureNote
                  : (detail.length > 0 ? tx.detailNote : tx.summaryNote)}
              </p>
              {item.url && (
                <a className="led-art-cta" href={item.url} target="_blank" rel="noopener noreferrer nofollow">
                  {isDisclosure ? tx.openDisclosure : tx.readSource}
                  {host && <span className="led-art-host">{host}</span>}
                </a>
              )}
            </div>

            {tickers.length > 0 && (
              <NewsIssuerContext
                tickers={tickers}
                currentId={item.id}
                language={language}
                securitiesMap={securitiesMap}
                onOpenCompany={onOpenCompany}
                onOpenNews={onOpenNews}
                tx={tx}
              />
            )}

            {tickers.length > 0 && item.id && (
              <NewsPriceReaction
                newsId={item.id}
                language={language}
                securitiesMap={securitiesMap}
                onOpenCompany={onOpenCompany}
                tx={tx}
              />
            )}

            {sectors.length > 0 && (
              <section className="led-art-block">
                <h3 className="led-panel-h">{tx.sectors}</h3>
                <div className="led-chips">
                  {sectors.map((s, i) => <span key={`${s}-${i}`} className="led-chip">{s}</span>)}
                </div>
              </section>
            )}
          </article>

          {related.length > 0 && (
            <section className="led-art-related">
              <div className="led-rule" />
              <h3 className="led-panel-h">{tx.related}</h3>
              <div className="led-stack">
                {related.map((it, i) => (
                  <EdNewsCard key={it.id || i} item={it} language={language} variant="story" onOpen={onOpenNews} />
                ))}
              </div>
            </section>
          )}
        </main>

        <aside className="led-rail">
          <div className="led-panel">
            <h4 className="led-panel-h">{tx.signal}</h4>
            <dl className="led-sig">
              <div><dt>{tx.tone}</dt><dd className={toneCls}>{etx.tone[item.tone] || item.tone} {toneScore}</dd></div>
              <div><dt>{tx.impact}</dt><dd>{item.impact === "none" ? tx.impactNone : (etx.impact[item.impact] || item.impact)}</dd></div>
              <div><dt>{tx.direction}</dt><dd>{tx.dir[item.direction] || item.direction || tx.dir.unclear}</dd></div>
              {relevancePct && <div><dt>{tx.relevance}</dt><dd>{relevancePct}</dd></div>}
              {item.source && <div><dt>{tx.source}</dt><dd>{item.source}</dd></div>}
            </dl>
            {disclaimer && <p className="led-sig-note">{disclaimer}</p>}
          </div>
          <div className="led-panel">
            <h4 className="led-panel-h">{tx.about}</h4>
            <dl className="led-sig led-sig--rows">
              {item.published_at && <div><dt>{tx.published}</dt><dd>{newsAbsTime(item.published_at, language)}</dd></div>}
              {item.collected_at && <div><dt>{tx.added}</dt><dd>{newsAbsTime(item.collected_at, language)}</dd></div>}
              {item.lang && <div><dt>{tx.langLabel}</dt><dd>{(tx.langs && tx.langs[item.lang]) || item.lang}</dd></div>}
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}

export { AnnouncementArticleView, NewsArticleView, NewsView };
