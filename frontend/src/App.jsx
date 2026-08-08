import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
// ТЗ §10.7: rounding lives in lib/format.js and thresholds come from the
// server via lib/flags.js, so a label cannot claim a window the calculation
// layer did not apply.
import { compact as fmtCompact, metric as fmtMetric, num as fmtNumber, pct as fmtPct, price as fmtPrice } from "./lib/format.js";
import { loadConfig, threshold as cfgThreshold } from "./lib/flags.js";
// Sector membership is one rule, shared by the Рынок filter bar and the heat map
// (see frontend/src/lib/sectors.js and tests/sectors.test.js) — they used to read
// two different maps and file the same ticker under two different sectors.
import { SECTOR_ORDER, orderSectors, sectorOf } from "./lib/sectors.js";
import heroImage from "./assets/hero-image.png";
import promoVideo from "./assets/promo.mp4";
import promoPoster from "./assets/promo-poster.jpg";
import logoIcon from "./assets/icon.png";
// Pure, unit-tested helpers. Valuation multiples and period labels live in one
// module so the market table and the company page cannot compute them differently
// (see frontend/src/lib/valuation.js and tests/valuation.test.js).
import {
  finEarnings,
  finFieldCoverage,
  finFieldPeriod,
  finPeriodCoverage,
  finRowPeriod,
  marketRowDay,
  normalizeMarketDay,
  previousClose,
  tradeStatsApply,
  valuationRatios,
} from "./lib/valuation.js";
import {
  allowDownloads,
  cachedTranslation,
  onTranslation,
  translateHeadline,
} from "./lib/translate.js";
import { pickLeadIndex } from "./lib/newsfeed.js";
// ТЗ §3.2: one glossary for the whole site. The /reference page and every ⓘ
// marker in the interface read the same entries, so a term cannot be explained
// two different ways depending on where the reader met it.
import { termFor } from "./lib/glossary.js";
// The admin panel is a screen of its own, with its own token layer — see
// admin/admin.css for why it deliberately does not inherit the site's theme.
import AdminPanel from "./admin/AdminPanel.jsx";

// --- Client-side routing: each view maps to a real URL path ------------------
const VIEW_PATHS = {
  main: "/",
  market: "/market",
  heatmap: "/heatmap",
  catalog: "/catalog",
  news: "/news",
  analysis: "/analysis",
  compare: "/compare",
  profile: "/profile",
  auth: "/login",
  // Internal, reached by direct link, not from the nav: the admin panel lives at
  // /admin/{section}. The old secret-in-a-field audit screen used to own
  // /admin/audit, so that path is kept and now opens the panel's Аудит section.
  admin: "/admin",
};

function viewToPath(view, ticker, newsId, adminSection) {
  if (view === "company" && ticker) return `/company/${encodeURIComponent(ticker)}`;
  if (view === "newsArticle" && newsId) return `/news/${encodeURIComponent(newsId)}`;
  if (view === "admin") {
    return adminSection && adminSection !== "overview" ? `/admin/${adminSection}` : "/admin";
  }
  return VIEW_PATHS[view] || "/";
}

function pathToView(pathname) {
  const clean = (pathname || "/").replace(/\/+$/, "") || "/";
  if (clean.startsWith("/company/")) {
    return { view: "company", ticker: decodeURIComponent(clean.slice("/company/".length)), newsId: null };
  }
  // /news is the feed; /news/{id} is one story on its own page.
  if (clean.startsWith("/news/")) {
    const id = decodeURIComponent(clean.slice("/news/".length)).split("/")[0];
    return id ? { view: "newsArticle", ticker: null, newsId: id }
              : { view: "news", ticker: null, newsId: null };
  }
  if (clean === "/admin" || clean.startsWith("/admin/")) {
    const raw = clean.slice("/admin".length).replace(/^\//, "");
    // /admin/audit is the old audit screen's URL; it opens the findings section.
    const section = raw === "audit" ? "findings" : (raw || "overview");
    return { view: "admin", ticker: null, newsId: null, adminSection: section };
  }
  const found = Object.entries(VIEW_PATHS).find(([, p]) => p === clean);
  return { view: found ? found[0] : "main", ticker: null, newsId: null };
}

function newsArticlePath(item) {
  return item && item.id ? `/news/${encodeURIComponent(item.id)}` : (item && item.url) || "#";
}

const STORAGE_KEY = "uz_stock_analyzer_token";
const LANGUAGE_KEY = "uz_stock_analyzer_language";
const THEME_KEY = "uz_stock_analyzer_theme";

// Mandatory legal disclaimer (ТЗ §3.2) — shown on every page and forced into every report.
const DISCLAIMER = {
  ru: "Аналитические материалы, прогнозы и оценки, представленные на платформе, носят исключительно информационный характер и подготовлены на основе публично доступных данных. Они не являются инвестиционными рекомендациями, офертой или призывом к совершению каких-либо операций с ценными бумагами. Платформа не несёт ответственности за инвестиционные решения, принятые пользователями на основе представленной информации.",
  uz: "Platformada taqdim etilgan tahliliy materiallar, prognozlar va baholar faqat ma'lumot berish maqsadida tayyorlangan bo'lib, ommaviy ma'lumotlar asosida shakllantirilgan. Ular investitsiya tavsiyasi, taklif yoki qimmatli qog'ozlar bilan biron-bir operatsiyani amalga oshirishga undov hisoblanmaydi. Platforma foydalanuvchilar tomonidan taqdim etilgan ma'lumotlar asosida qabul qilingan investitsiya qarorlari uchun javobgar emas.",
  en: "The analytical materials, forecasts, and assessments provided on the platform are for informational purposes only and are based on publicly available data. They do not constitute investment advice, an offer, or a solicitation to conduct any transactions with securities. The platform bears no responsibility for investment decisions made by users based on the information provided.",
};

function DisclaimerNote({ language, variant = "footer" }) {
  const text = DISCLAIMER[language] || DISCLAIMER.ru;
  const label = language === "uz" ? "Ogohlantirish" : language === "en" ? "Disclaimer" : "Дисклеймер";
  return (
    <div className={`disclaimer-note disclaimer-note--${variant}`} role="note">
      <span className="disclaimer-note__label">{label}</span>
      <p className="disclaimer-note__text">{text}</p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// News (ТЗ §3.2, item 6) — market-news section built to the hero-lead + card-grid
// pattern that professional financial-news sites (Bloomberg / Reuters) converge on:
// one large lead story, a grid of secondary items, a compact "latest" rail, with
// functional category tags, timestamps and a strong headline hierarchy. Content is
// the editorial §3.11 feed from /api/news/feed — overall Uzbek economy / market /
// issuer news, gathered from Uzbek sources and AI-sorted by likely price impact.
// ─────────────────────────────────────────────────────────────────────────────
const NEWS_TX = {
  ru: {
    eyebrow: "Рынок · Аналитическая лента", title: "Новости рынка",
    subtitle: "Главные новости экономики, рынка и эмитентов Узбекистана — собраны из узбекских источников и отсортированы ИИ по возможному влиянию на котировки.",
    latest: "Свежее", empty: "Пока нет свежих новостей. Загляните позже.",
    loadingText: "Загружаем ленту…", error: "Не удалось загрузить новости.",
    tabs: { all: "Все", economy: "Экономика", corporate: "Корпоративные" },
    tabHint: {
      all: "Экономика и эмитенты в одной ленте",
      economy: "Макроэкономика, ставки и регулирование — то, что двигает рынок целиком",
      corporate: "События и отчётность конкретных эмитентов",
    },
    emptyTab: "В этом разделе пока пусто — посмотрите «Все».",
    cat: { report: "Отчётность", listing: "Листинг", delisting: "Делистинг" },
    forms: { NAS: "НСБУ", NSBU: "НСБУ", IFRS: "МСФО", MSFO: "МСФО", Audit: "Аудит", Audition: "Аудит" },
  },
  en: {
    eyebrow: "Market · Analytical feed", title: "Market News",
    subtitle: "The economy, market and issuer news that matters in Uzbekistan — gathered from Uzbek sources and AI-sorted by likely price impact.",
    latest: "Latest", empty: "No recent news yet. Check back soon.",
    loadingText: "Loading the feed…", error: "Could not load the news feed.",
    tabs: { all: "All", economy: "Economy", corporate: "Corporate" },
    tabHint: {
      all: "The economy and the issuers in one feed",
      economy: "Macro, rates and regulation — what moves the market as a whole",
      corporate: "Events and reporting of individual issuers",
    },
    emptyTab: "Nothing here yet — try “All”.",
    cat: { report: "Filing", listing: "Listing", delisting: "Delisting" },
    forms: { NAS: "NAS", NSBU: "NAS", IFRS: "IFRS", MSFO: "IFRS", Audit: "Audit", Audition: "Audit" },
  },
  uz: {
    eyebrow: "Bozor · Tahliliy lenta", title: "Bozor yangiliklari",
    subtitle: "O'zbekiston iqtisodiyoti, bozori va emitentlari bo'yicha muhim yangiliklar — o'zbek manbalaridan yig'iladi va sun'iy intellekt tomonidan ta'sir bo'yicha saralanadi.",
    latest: "So'nggi", empty: "Hozircha yangi yangiliklar yo'q. Keyinroq qayting.",
    loadingText: "Lenta yuklanmoqda…", error: "Yangiliklarni yuklab bo'lmadi.",
    tabs: { all: "Barchasi", economy: "Iqtisodiyot", corporate: "Korporativ" },
    tabHint: {
      all: "Iqtisodiyot va emitentlar bitta lentada",
      economy: "Makroiqtisodiyot, stavkalar va tartibga solish — bozorni butunlay harakatga keltiradigan narsalar",
      corporate: "Aniq emitentlarning voqealari va hisobotlari",
    },
    emptyTab: "Bu bo'limda hozircha bo'sh — «Barchasi»ni ko'ring.",
    cat: { report: "Hisobot", listing: "Listing", delisting: "Delisting" },
    forms: { NAS: "NAS", NSBU: "NAS", IFRS: "IFRS", MSFO: "IFRS", Audit: "Audit", Audition: "Audit" },
  },
};

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

function newsRelTime(dateStr, language) {
  if (!dateStr) return "";
  const d = new Date(String(dateStr).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(dateStr);
  const diff = (Date.now() - d.getTime()) / 1000;
  const loc = language === "en" ? "en-US" : "ru-RU";
  if (diff < 3600) { const m = Math.max(1, Math.floor(diff / 60)); return language === "en" ? `${m}m ago` : language === "uz" ? `${m} daq oldin` : `${m} мин назад`; }
  if (diff < 86400) { const h = Math.floor(diff / 3600); return language === "en" ? `${h}h ago` : language === "uz" ? `${h} soat oldin` : `${h} ч назад`; }
  if (diff < 86400 * 7) { const dd = Math.floor(diff / 86400); return language === "en" ? `${dd}d ago` : language === "uz" ? `${dd} kun oldin` : `${dd} дн назад`; }
  return d.toLocaleDateString(loc, { day: "numeric", month: "short", year: "numeric" });
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

// Labels for the editorial feed's AI fields (the 4 §3.11 classes + tone/impact).
const EDNEWS_TX = {
  ru: { cat: { financial_report: "Отчётность", corporate_event: "Корпсобытие", regulatory: "Регулятор", market: "Рынок" },
        tone: { positive: "позитив", neutral: "нейтрально", negative: "негатив" },
        impact: { high: "высокое влияние", medium: "среднее влияние", low: "низкое влияние" },
        mood: "Настроение рынка · 30 дней", moodPos: "позитивное", moodNeu: "нейтральное", moodNeg: "негативное",
        machine: "перевод браузера" },
  en: { cat: { financial_report: "Earnings", corporate_event: "Corporate", regulatory: "Regulatory", market: "Market" },
        tone: { positive: "positive", neutral: "neutral", negative: "negative" },
        impact: { high: "high impact", medium: "medium impact", low: "low impact" },
        mood: "Market sentiment · 30 days", moodPos: "positive", moodNeu: "neutral", moodNeg: "negative",
        machine: "browser translation" },
  uz: { cat: { financial_report: "Hisobot", corporate_event: "Korporativ", regulatory: "Regulyator", market: "Bozor" },
        tone: { positive: "ijobiy", neutral: "neytral", negative: "salbiy" },
        impact: { high: "yuqori ta'sir", medium: "o'rta ta'sir", low: "past ta'sir" },
        mood: "Bozor kayfiyati · 30 kun", moodPos: "ijobiy", moodNeu: "neytral", moodNeg: "salbiy",
        machine: "brauzer tarjimasi" },
};

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

// Plain left-clicks are handled in-app; modified clicks (new tab, new window) and
// middle-clicks are left to the browser, which is why these are real <a href> links.
function interceptNav(handler) {
  return (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    handler();
  };
}

// The headline to print for an editorial item, plus the original when we substituted one.
// The API ships `title_ru` — our own stored Russian summary, promoted — only for items whose
// own headline is not Russian (kun.uz before it moved to its Russian feed; Moody's, Fitch and
// The Diplomat, which publish in English and nothing else). Nothing is translated: no model
// runs on the read path, and the substitute is text we already wrote when the item was
// collected. On the English and Uzbek UI the original stays, because swapping in a Russian
// sentence there would trade one foreign headline for another. The original is returned
// either way so the card can print it as attribution — for a rating action the agency's exact
// wording is the news.
// `machine` is the browser's own translation of the source headline, when it produced one
// (see useBrowserHeadline). It outranks the summary, because a translated headline is still
// a headline while the summary is a sentence about the story — but it is only ever an
// upgrade: if it is absent, the summary the server already supplied carries the card.
function edHeadline(item, language, machine) {
  const title = (item && item.title) || "";
  const lang = (item && item.lang) || "";
  // Foreign means "not the language this reader is reading", so a Russian headline needs
  // replacing on the English site exactly as an English one does on the Russian site.
  const foreign = Boolean(lang) && lang !== language;
  if (foreign && machine) {
    return { text: machine, original: title, lang, machine: true };
  }
  const stored = (item && item[`title_${language}`]) || "";
  const swap = foreign && Boolean(stored);
  return {
    text: swap ? stored : title,
    original: swap ? title : "",
    lang,
    machine: false,
  };
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

// The two reading modes, over the four classes the §3.11 classifier already
// assigns — so this is a filter on data we hold, not a second pipeline. They
// partition all four types, so every story is reachable from one of them.
const NEWS_TABS = [
  { key: "all", type: null },
  { key: "economy", type: "economy" },       // market + regulatory
  { key: "corporate", type: "corporate" },   // corporate_event + financial_report
];

function newsTabFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return NEWS_TABS.some((t) => t.key === wanted) ? wanted : "all";
}

function NewsView({ language, onOpenCompany, onOpenNews, user, apiFetch }) {
  const tx = NEWS_TX[language] || NEWS_TX.ru;
  useTranslationTick();
  const etx = EDNEWS_TX[language] || EDNEWS_TX.ru;
  const [state, setState] = React.useState({ loading: true, error: false, items: [] });
  const [reloadKey, setReloadKey] = React.useState(0);
  // Kept in the URL so a tab can be linked and survives a reload — as a query,
  // not a path, because /news/{slug} is already the article route.
  const [tab, setTab] = React.useState(newsTabFromLocation);
  React.useEffect(() => {
    const onPop = () => setTab(newsTabFromLocation());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const selectTab = React.useCallback((key) => {
    setTab(key);
    try {
      window.history.replaceState({}, "", key === "all" ? "/news" : `/news?tab=${key}`);
    } catch { /* history is unavailable in some embedded views */ }
  }, []);

  React.useEffect(() => {
    let alive = true;
    setState({ loading: true, error: false, items: [] });
    const group = (NEWS_TABS.find((t) => t.key === tab) || {}).type;
    fetch(`/api/news/feed?limit=60&days=30${group ? `&type=${group}` : ""}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setState({ loading: false, error: !d || !d.ok, items: (d && d.items) || [] }); })
      .catch(() => { if (alive) setState({ loading: false, error: true, items: [] }); });
    return () => { alive = false; };
  }, [reloadKey, tab]);

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

  return (
    <div className="news-view led">
      <header className="led-head">
        <div className="led-kicker">{tx.eyebrow}</div>
        <h1 className="led-title">{tx.title}</h1>
        <p className="led-sub">{(tx.tabHint && tx.tabHint[tab]) || tx.subtitle}</p>
      </header>

      <nav className="news-tabs" aria-label={tx.title}>
        {NEWS_TABS.map((t) => (
          <button key={t.key} type="button"
            className={`news-tab ${tab === t.key ? "active" : ""}`}
            aria-current={tab === t.key ? "page" : undefined}
            onClick={() => selectTab(t.key)}>
            {(tx.tabs && tx.tabs[t.key]) || t.key}
          </button>
        ))}
      </nav>

      {user && user.is_admin && apiFetch && (
        <NewsAdminPanel language={language} apiFetch={apiFetch} onStored={() => setReloadKey((k) => k + 1)} />
      )}

      {loading ? (
        <div className="led-cols">
          <div className="led-main"><div className="led-skel-lead" /><div className="led-skel-row" /><div className="led-skel-row" /></div>
          <aside className="led-rail"><div className="led-skel-panel" /></aside>
        </div>
      ) : error ? (
        <div className="led-empty">{tx.error}</div>
      ) : !items.length ? (
        <div className="led-empty">{tab === "all" ? tx.empty : (tx.emptyTab || tx.empty)}</div>
      ) : (
        <div className="led-cols">
          <main className="led-main">
            {lead && <EdNewsCard item={lead} language={language} variant="lead" onOpen={onOpenNews} />}
            {stack.length > 0 && (
              <>
                <div className="led-rule" />
                <div className="led-stack">
                  {stack.map((it, i) => <EdNewsCard key={it.id || i} item={it} language={language} variant="story" onOpen={onOpenNews} />)}
                </div>
              </>
            )}
          </main>
          <aside className="led-rail">
            <div className="led-panel">
              <h4 className="led-panel-h">{etx.mood}</h4>
              <div className="led-gauge"><b className={mood.cls}>{(mood.avg >= 0 ? "+" : "") + mood.avg.toFixed(2)}</b><span>{moodLabel}</span></div>
              <div className="led-bar"><i style={{ width: mood.pct + "%" }} /></div>
              <div className="led-counts">
                <span className="pos">▲ {mood.counts.positive}</span>
                <span className="neu">● {mood.counts.neutral}</span>
                <span className="neg">▼ {mood.counts.negative}</span>
              </div>
            </div>
            <div className="led-panel led-latest">
              <h4 className="led-panel-h">{tx.latest}</h4>
              {latest.slice(0, 7).map((it, i) => (
                <a key={it.id || i} className="led-lt" href={newsArticlePath(it)}
                  {...(it.id && onOpenNews
                    ? { onClick: interceptNav(() => onOpenNews(it)) }
                    : { target: "_blank", rel: "noopener noreferrer" })}>
                  <span className={`led-dot ${_TONE_CLS[it.tone] || "neu"}`} />
                  <span className="led-lt-t">{edHeadlineCached(it, language).text}</span>
                  <span className="led-lt-s">{it.source}{it.published_at ? ` · ${newsRelTime(it.published_at, language)}` : ""}</span>
                </a>
              ))}
            </div>
          </aside>
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
      fetch(`/api/news/ticker/${encodeURIComponent(t)}?limit=6&days=90`)
        .then((r) => r.json())
        .then((d) => [t, d && d.ok ? d : null])
        .catch(() => [t, null])))
      .then((pairs) => { if (alive) setByTicker(Object.fromEntries(pairs)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyList]);

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

// Modern SVG Icons for landing page
const Icons = {
  chart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 3v18h18" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M7 14l4-4 4 4 5-5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  zap: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  users: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="9" cy="7" r="4" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  target: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="10" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="6" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="12" cy="12" r="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  database: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <ellipse cx="12" cy="5" rx="9" ry="3" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  trending: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M23 6l-9.5 9.5-5-5L1 18" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M17 6h6v6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  lock: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M7 11V7a5 5 0 0 1 10 0v4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  star: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="10" strokeLinecap="round" strokeLinejoin="round"/>
      <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  ),
};

const TEXTS = {
  ru: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "Платформа для анализа компаний Узбекистана",
    nav: { main: "Главная", about: "О проекте", auth: "Вход", profile: "Профиль", analysis: "Анализ", catalog: "Каталог", news: "Новости" },
    catalog: {
      title: "Каталог отчётности",
      subtitle: "Все доступные отчёты листинговых компаний с openinfo.uz",
      searchPlaceholder: "Поиск по тикеру или названию...",
      syncAll: "Синхронизировать всё",
      syncCompany: "Обновить",
      syncing: "Синхронизация...",
      syncDone: "Обновлено",
      empty: "Каталог пуст — нажмите «Синхронизировать всё»",
      selectCompany: "Выберите компанию из списка",
      noReports: "Отчёты не найдены",
      notPublished: "За выбранный период данный тип отчёта не был опубликован",
      available: "Отчёт опубликован",
      loading: "Загрузка...",
      reports: "отчётов",
      companies: "компаний",
      totalReports: "отчётов в базе",
      lastSync: "Последнее обновление",
      forms: { NSBU: "НСБУ", MSFO: "МСФО", Audition: "Аудит" },
      periods: { annual: "Годовой", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Тип аналитики",
      runAnalysis: "Запустить анализ",
      analysisLoading: "Анализируем...",
      analysisTypes: {
        financial: "Финансовый анализ",
        ratio: "Коэффициенты (ROA, ROE, Debt...)",
        dynamics: "Динамика показателей",
        quarter_compare: "Сравнение кварталов",
        annual_compare: "Сравнение годовых отчётов",
        swot: "SWOT-анализ",
        recommendation: "Аналитический вывод",
        multi_company: "Сравнение компаний",
      },
      compareWith: "Сравнить с:",
      comparePeriod: "Период для сравнения:",
      noValue: "Нет данных",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Чистая маржа", debt_ratio: "Debt Ratio", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Выручка", net_income: "Чистая прибыль", total_assets: "Активы", equity: "Капитал", total_liabilities: "Обязательства" },
      pdfReport: "Открыть PDF",
      excelIncome: "Excel — фин. результаты",
      excelBalance: "Excel — баланс",
      excelReport: "Скачать Excel",
      exportPdf: "Скачать PDF",
      notifications: "Уведомления",
      notifEmpty: "Нет новых отчётов",
      notifNewReport: "Новый отчёт опубликован",
    },
    languageLabel: "Язык",
    languageOptions: { ru: "Русский", en: "English", uz: "O'zbek" },
    theme: { label: "Тема", light: "Светлая", dark: "Тёмная" },
    hero: {
      title: "Современный анализ компаний в одном интерфейсе",
      copy:
        "Веб-платформа для быстрого анализа компаний: регистрация, вход, профиль, избранное, история и структурированный финансовый отчет с графиками.",
      badges: ["Финансовые отчеты", "Личный кабинет", "Графики и метрики"],
      ctas: { analysis: "Перейти к анализу", profile: "Открыть профиль" },
    },
    dashboard: {
      title: "Панель показателей",
      copy: "Ключевые ориентиры по проекту и вашей активности",
      cards: {
        companies: "Компаний в каталоге",
        analyses: "Всего анализов",
        avgScore: "Средний скор",
        cached: "Из кэша",
      },
      activityTitle: "Активность анализов",
      activityCopy: "Количество анализов за последние 14 дней",
      activityEmpty: "Активность появится после нескольких анализов",
      peak: "Пик",
      trend: "Тренд",
    },
    main: {
      title: "Платформа для инвестиционного анализа",
      copy: "Получайте профессиональный анализ узбекских компаний за секунды. Оценка финансового здоровья, риски и потенциал роста.",
      features: [
        { icon: "chart", title: "Глубокий анализ", copy: "Финансовые коэффициенты, динамика выручки и прибыли, структура баланса" },
        { icon: "zap", title: "Мгновенный результат", copy: "Полный отчёт с графиками и разбором отчётности за несколько секунд" },
        { icon: "shield", title: "Надежные данные", copy: "Актуальная финансовая отчетность напрямую с Узбекской биржи" },
        { icon: "target", title: "Ключевые метрики", copy: "Ликвидность, волатильность, рентабельность и долговая нагрузка" },
      ],
      howItWorks: {
        title: "Как это работает",
        steps: [
          { num: "01", title: "Выберите компанию", copy: "Введите тикер или выберите из каталога доступных компаний" },
          { num: "02", title: "Запустите анализ", copy: "Система соберет данные и проведет комплексный финансовый анализ" },
          { num: "03", title: "Получите отчет", copy: "Изучите оценку, графики и метрики с аналитическими выводами" },
        ],
      },
      stats: {
        title: "Платформа в цифрах",
        items: [
          { value: "50+", label: "Компаний в базе" },
          { value: "15+", label: "Метрик анализа" },
          { value: "24/7", label: "Доступность" },
          { value: "100%", label: "Бесплатно" },
        ],
      },
      cta: {
        title: "Готовы начать?",
        copy: "Зарегистрируйтесь бесплатно и получите доступ ко всем инструментам анализа",
        button: "Начать анализ",
      },
    },
    about: {
      title: "О проекте",
      leftCards: [
        { title: "Backend", copy: "API, авторизация, Postgres и анализ уже работают как единый слой." },
        { title: "Frontend", copy: "Новая оболочка собрана на React и Vite для более чистой архитектуры." },
        { title: "Подача данных", copy: "Результат подается через карточки, графики и аккуратные аккордеоны." },
      ],
      rightTitle: "Что получает пользователь",
      rightCards: [
        { title: "Оценка", copy: "Общий скор по компании." },
        { title: "Итоговая оценка", copy: "Краткое фактологическое резюме по данным." },
        { title: "Метрики", copy: "Ликвидность, рентабельность, долговая нагрузка и динамика." },
        { title: "История", copy: "Сохраненные анализы и избранные компании." },
      ],
    },
    auth: {
      title: "Вход",
      signedOut: "Вход не выполнен",
      signedIn: "Вход выполнен",
      loginTab: "Вход",
      registerTab: "Регистрация",
      login: { email: "Email", password: "Пароль", submit: "Войти" },
      register: { fullName: "Имя и фамилия", email: "Email", password: "Пароль", submit: "Создать аккаунт" },
      oauthLabel: "Или продолжить через",
      google: "Google",
      logout: "Выйти",
      signedInAs: "Вошли как",
      messages: {
        loginOk: "Вход выполнен",
        registerOk: "Аккаунт создан",
        logoutOk: "Выход выполнен",
        authRequired: "Сначала выполните вход",
      },
    },
    profile: {
      title: "Личный кабинет",
      subtitle: "Профиль, статистика, избранное и история",
      editTitle: "Редактирование профиля",
      name: "Отображаемое имя",
      avatar: "Аватар",
      save: "Сохранить",
      clearAvatar: "Удалить аватар",
      refresh: "Обновить",
      analyze: "Перейти к анализу",
      statsTitle: "Активность",
      favoritesTitle: "Избранное",
      historyTitle: "История анализов",
      repeat: "Повторить",
      stats: {
        totalAnalyses: "Всего анализов",
        analyses7d: "За 7 дней",
        analyses30d: "За 30 дней",
        analyzedCompanies: "Компаний в истории",
        avgScore: "Средний скор",
        bestScore: "Лучшая оценка",
        cachedAnalyses: "Из кэша",
        topCompany: "Чаще всего смотрят",
      },
      empty: "Профиль появится после входа в систему.",
      historyEmpty: "После первого анализа здесь появится история действий.",
      favoritesEmpty: "Добавляйте компании в избранное из анализа или истории.",
      filters: { search: "Поиск по компании или тикеру", all: "Все анализы", favorites: "Только избранное" },
      remove: "Убрать",
    },
    analysis: {
      title: "Анализ компании",
      company: "Компания",
      mode: "Режим",
      quick: "Быстрый",
      full: "Полный",
      reportType: "Тип анализа",
      fullAnalysis: "Полный анализ",
      quarterlyReport: "Квартальный",
      annualReport: "Годовой",
      quarter: "Квартал",
      currentYear: "Сравнить год",
      previousYear: "С годом",
      reportingForm: "Форма отчётности",
      reportFormIFRS: "МСФО",
      reportFormNAS: "НСБУ",
      reportFormAudit: "Аудиторское заключение",
      reportFormHint: "Выбор формы влияет только на режим квартального/годового сравнения. НСБУ — единственная форма с Excel-данными на openinfo.uz. МСФО и аудиторские заключения публикуются в PDF-формате без Excel-таблиц.",
      reportFormLatestNote: "В режиме «Полный анализ» данные берутся из структурированной отчётности НСБУ (форма 1 + форма 2) — форма отчётности применяется только при квартальном/годовом сравнении.",
      reportFormNotFound: "Компания не опубликовала данный тип отчёта за выбранный период.",
      forceRefresh: "Обновить из источника (обойти кэш)",
      submit: "Анализировать",
      availableTitle: "Доступные компании",
      resultTitle: "Результат",
      resultEmpty: "Анализ еще не выполнен",
      resultLoading: "Анализ выполняется...",
      resultCacheWaiting: "Ожидание",
      resultCacheHit: "Из кэша",
      resultFresh: "Свежий расчет",
      score: "Оценка / 100",
      verdictPlaceholder: "Запустите анализ, чтобы увидеть итоговый вывод.",
      metricsTitle: "Ключевые показатели",
      sectionsTitle: "Разделы отчета",
      favoriteAdd: "В избранное",
      favoriteRemove: "Убрать из избранного",
      chartTitle: "Динамика выручки и прибыли",
      chartEmpty: "График появится после первого анализа.",
      chartMetaEmpty: "Нет данных",
      noData: "Недостаточно данных",
      signalRevenue: "Выручка",
      signalDebt: "Обязательства",
      signalMargin: "Маржа",
      signalRisk: "Риск",
      signalTrend: "Тренд",
      signalLatest: "Последнее",
      signalUp: "Позитивно",
      signalFlat: "Стабильно",
      signalDown: "Под давлением",
      loadingMetrics: "Загрузка",
      loadingChart: "Загрузка графика",
      loadingSections: "Загрузка отчета",
      loadingCache: "Проверка",
      completed: "Анализ завершен",
    },
    toasts: { success: "Готово", error: "Ошибка", info: "Инфо" },
    sections: {
      ОБЩИЕ_СВЕДЕНИЯ: "Общие сведения об эмитенте и методология анализа",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Горизонтальный анализ бухгалтерского баланса",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Вертикальный анализ бухгалтерского баланса",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Анализ отчёта о финансовых результатах",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Коэффициентный анализ",
      СВОДНАЯ_ТАБЛИЦА: "Сводная таблица ключевых показателей",
      ЗАКЛЮЧЕНИЕ: "Итоговая оценка",
      СКОРИНГ: "Ключевые наблюдения по отчётности",
      ДОСЬЕ: "Краткое досье эмитента",
      ЧТО_С_ДЕНЬГАМИ: "Финансовая выжимка",
      ТРЕНД: "Анализ трендов и динамики показателей",
      ЭФФЕКТИВНОСТЬ: "Операционная эффективность и оборачиваемость",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Технический анализ (RSI, Фибоначчи, объёмы)",
      ОЦЕНКА_СТОИМОСТИ: "Оценка стоимости по показателям",
      ФИБОНАЧЧИ: "Технический анализ (уровни Фибоначчи)",
      ОЦЕНКА_ЦЕНЫ: "Оценка стоимости и качества цены",
      КАТАЛИЗАТОРЫ: "Факторы влияния на стоимость акций",
      РЫНОЧНЫЕ_ДАННЫЕ: "Рыночные данные и ликвидность",
      СИЛЬНЫЕ_СТОРОНЫ: "Сильные стороны и конкурентные преимущества",
      СЛАБЫЕ_СТОРОНЫ: "Риски и слабые стороны",
      ВОЗМОЖНОСТИ: "Возможности роста",
      УГРОЗЫ: "Угрозы и внешние риски",
      ПРОГНОЗ: "Аналитический обзор динамики",
      ВЕРДИКТ: "Итоговая оценка",
      СОВЕТЫ: "На что обратить внимание",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Ограничения анализа",
      ИТОГ: "Резюме для инвестора",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Позитивные факторы",
      КРАСНЫЕ_ФЛАГИ: "Негативные факторы",
    },
    metrics: {
      total_score: "Итоговый скор",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Критерии Баффетта",
      graham_number: "Стоимость Грэма",
      dcf: "Оценка стоимости",
      industry: "Отрасль",
      market_liquidity: "Ликвидность",
      debt_burden: "Долговая нагрузка",
      momentum: "Тренд",
    },
  },
  en: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "Company analysis platform for Uzbekistan",
    nav: { main: "Main", about: "About", auth: "Sign in", profile: "Profile", analysis: "Analysis", catalog: "Catalog", news: "News" },
    catalog: {
      title: "Report Catalog",
      subtitle: "All available reports of listed companies from openinfo.uz",
      searchPlaceholder: "Search by ticker or name...",
      syncAll: "Sync all",
      syncCompany: "Refresh",
      syncing: "Syncing...",
      syncDone: "Updated",
      empty: "Catalog is empty — click \"Sync all\"",
      selectCompany: "Select a company from the list",
      noReports: "No reports found",
      notPublished: "This report type was not published for the selected period",
      available: "Report is available",
      loading: "Loading...",
      reports: "reports",
      companies: "companies",
      totalReports: "reports in database",
      lastSync: "Last updated",
      forms: { NSBU: "NAS", MSFO: "IFRS", Audition: "Audit" },
      periods: { annual: "Annual", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Analysis type",
      runAnalysis: "Run analysis",
      analysisLoading: "Analyzing...",
      analysisTypes: {
        financial: "Financial analysis",
        ratio: "Ratios (ROA, ROE, Debt...)",
        dynamics: "Metrics dynamics",
        quarter_compare: "Quarter comparison",
        annual_compare: "Annual comparison",
        swot: "SWOT analysis",
        recommendation: "Analytical conclusion",
        multi_company: "Company comparison",
      },
      compareWith: "Compare with:",
      comparePeriod: "Period to compare:",
      noValue: "No data",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Net Margin", debt_ratio: "Debt Ratio", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Revenue", net_income: "Net Income", total_assets: "Total Assets", equity: "Equity", total_liabilities: "Total Liabilities" },
      pdfReport: "Open PDF",
      excelIncome: "Excel — income statement",
      excelBalance: "Excel — balance sheet",
      excelReport: "Download Excel",
      exportPdf: "Download PDF",
      notifications: "Notifications",
      notifEmpty: "No new reports",
      notifNewReport: "New report published",
    },
    languageLabel: "Language",
    languageOptions: { ru: "Russian", en: "English", uz: "Uzbek" },
    theme: { label: "Theme", light: "Light", dark: "Dark" },
    hero: {
      title: "Modern company analysis in one dashboard",
      copy: "A web platform for fast company analysis, authentication, profile management, favorites, history, and financial reporting with charts.",
      badges: ["Financial reports", "Personal dashboard", "Charts and metrics"],
      ctas: { analysis: "Go to analysis", profile: "Open profile" },
    },
    dashboard: {
      title: "Dashboard",
      copy: "Project-wide metrics and your recent activity",
      cards: {
        companies: "Companies in catalog",
        analyses: "Total analyses",
        avgScore: "Average score",
        cached: "From cache",
      },
      activityTitle: "Analysis activity",
      activityCopy: "Analyses completed over the last 14 days",
      activityEmpty: "Activity will appear after a few analyses",
      peak: "Peak",
      trend: "Trend",
    },
    main: {
      title: "Investment Analysis Platform",
      copy: "Get professional analysis of Uzbek companies in seconds. Financial health assessment, risks, and growth potential.",
      features: [
        { icon: "chart", title: "Deep Analysis", copy: "Financial ratios, revenue and profit dynamics, balance-sheet structure" },
        { icon: "zap", title: "Instant Results", copy: "Complete report with charts and statement breakdown in seconds" },
        { icon: "shield", title: "Reliable Data", copy: "Up-to-date financial statements directly from Uzbek Stock Exchange" },
        { icon: "target", title: "Key Metrics", copy: "Liquidity, volatility, profitability and debt load" },
      ],
      howItWorks: {
        title: "How It Works",
        steps: [
          { num: "01", title: "Select Company", copy: "Enter ticker or choose from the available companies catalog" },
          { num: "02", title: "Run Analysis", copy: "System collects data and performs comprehensive financial analysis" },
          { num: "03", title: "Get Report", copy: "Review score, charts and metrics with analytical conclusions" },
        ],
      },
      stats: {
        title: "Platform in Numbers",
        items: [
          { value: "50+", label: "Companies" },
          { value: "15+", label: "Analysis Metrics" },
          { value: "24/7", label: "Availability" },
          { value: "100%", label: "Free" },
        ],
      },
      cta: {
        title: "Ready to Start?",
        copy: "Register for free and get access to all analysis tools",
        button: "Start Analysis",
      },
    },
    about: {
      title: "About the project",
      leftCards: [
        { title: "Backend", copy: "API, auth, Postgres, and analysis already work as one layer." },
        { title: "Frontend", copy: "The new shell is built with React and Vite." },
        { title: "Delivery", copy: "Results are shown through cards, charts, and clean accordions." },
      ],
      rightTitle: "What the user gets",
      rightCards: [
        { title: "Score", copy: "One main score for quick orientation." },
        { title: "Bottom line", copy: "A short factual summary of the data." },
        { title: "Metrics", copy: "Liquidity, profitability, debt load, and trend dynamics." },
        { title: "History", copy: "Saved analyses and favorite companies." },
      ],
    },
    auth: {
      title: "Sign in",
      signedOut: "Not signed in",
      signedIn: "Signed in",
      loginTab: "Sign in",
      registerTab: "Register",
      login: { email: "Email", password: "Password", submit: "Sign in" },
      register: { fullName: "Full name", email: "Email", password: "Password", submit: "Create account" },
      oauthLabel: "Or continue with",
      google: "Google",
      logout: "Log out",
      signedInAs: "Signed in as",
      messages: {
        loginOk: "Signed in",
        registerOk: "Account created",
        logoutOk: "Signed out",
        authRequired: "Please sign in first",
      },
    },
    profile: {
      title: "Profile",
      subtitle: "Profile, statistics, favorites, and history",
      editTitle: "Edit profile",
      name: "Display name",
      avatar: "Avatar",
      save: "Save",
      clearAvatar: "Remove avatar",
      refresh: "Refresh",
      analyze: "Go to analysis",
      statsTitle: "Activity",
      favoritesTitle: "Favorites",
      historyTitle: "Analysis history",
      repeat: "Repeat",
      stats: {
        totalAnalyses: "Total analyses",
        analyses7d: "Last 7 days",
        analyses30d: "Last 30 days",
        analyzedCompanies: "Companies in history",
        avgScore: "Average score",
        bestScore: "Best score",
        cachedAnalyses: "From cache",
        topCompany: "Most viewed",
      },
      empty: "Profile appears after sign in.",
      historyEmpty: "Your activity history will appear after the first analysis.",
      favoritesEmpty: "Add companies to favorites from analysis or history.",
      filters: { search: "Search by company or ticker", all: "All analyses", favorites: "Favorites only" },
      remove: "Remove",
    },
    analysis: {
      title: "Company analysis",
      company: "Company",
      mode: "Mode",
      quick: "Quick",
      full: "Full",
      reportType: "Analysis type",
      fullAnalysis: "Full analysis",
      quarterlyReport: "Quarterly",
      annualReport: "Annual",
      quarter: "Quarter",
      currentYear: "Compare year",
      previousYear: "With year",
      reportingForm: "Reporting form",
      reportFormIFRS: "IFRS",
      reportFormNAS: "NAS",
      reportFormAudit: "Auditor's Report",
      reportFormHint: "Form selection applies only to quarterly/annual comparison mode. NAS is the only form with Excel data on openinfo.uz. IFRS and audit reports are published as PDF with no Excel tables.",
      reportFormLatestNote: "In Full analysis mode data is sourced from NAS structured reports (form 1 + form 2). The reporting form only applies to quarterly/annual comparison.",
      reportFormNotFound: "The company did not publish this type of report for the selected period.",
      forceRefresh: "Refresh from source (bypass cache)",
      submit: "Analyze",
      availableTitle: "Available companies",
      resultTitle: "Result",
      resultEmpty: "No analysis yet",
      resultLoading: "Running analysis...",
      resultCacheWaiting: "Waiting",
      resultCacheHit: "From cache",
      resultFresh: "Fresh result",
      score: "Score / 100",
      verdictPlaceholder: "Run analysis to see the final verdict.",
      metricsTitle: "Key metrics",
      sectionsTitle: "Report sections",
      favoriteAdd: "Add to favorites",
      favoriteRemove: "Remove from favorites",
      chartTitle: "Revenue and profit trend",
      chartEmpty: "The chart appears after the first analysis.",
      chartMetaEmpty: "No data",
      noData: "No data",
      signalRevenue: "Revenue",
      signalDebt: "Liabilities",
      signalMargin: "Margin",
      signalRisk: "Risk",
      signalTrend: "Trend",
      signalLatest: "Latest",
      signalUp: "Positive",
      signalFlat: "Stable",
      signalDown: "Under pressure",
      loadingMetrics: "Loading",
      loadingChart: "Loading chart",
      loadingSections: "Loading report",
      loadingCache: "Checking",
      completed: "Analysis completed",
    },
    toasts: { success: "Done", error: "Error", info: "Info" },
    sections: {
      ОБЩИЕ_СВЕДЕНИЯ: "Issuer Overview and Analytical Methodology",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Horizontal Balance Sheet Analysis",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Vertical Balance Sheet Analysis",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Income Statement Analysis",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Financial Ratio Analysis",
      СВОДНАЯ_ТАБЛИЦА: "Summary Table of Key Metrics",
      ЗАКЛЮЧЕНИЕ: "Final Assessment",
      СКОРИНГ: "Key observations from the report",
      ДОСЬЕ: "Company Snapshot",
      ЧТО_С_ДЕНЬГАМИ: "Financial Position Brief",
      ТРЕНД: "Trend and Dynamics Analysis",
      ЭФФЕКТИВНОСТЬ: "Operational Efficiency and Turnover",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Technical Analysis (RSI, Fibonacci, Volume)",
      ОЦЕНКА_СТОИМОСТИ: "Indicator-Based Valuation",
      ФИБОНАЧЧИ: "Technical Analysis (Fibonacci Levels)",
      ОЦЕНКА_ЦЕНЫ: "Valuation and price quality",
      КАТАЛИЗАТОРЫ: "Stock Price Catalysts",
      РЫНОЧНЫЕ_ДАННЫЕ: "Market Data and Liquidity",
      СИЛЬНЫЕ_СТОРОНЫ: "Strengths and Competitive Advantages",
      СЛАБЫЕ_СТОРОНЫ: "Risks and Weaknesses",
      ВОЗМОЖНОСТИ: "Growth Opportunities",
      УГРОЗЫ: "Threats and External Risks",
      ПРОГНОЗ: "Analytical Overview of Dynamics",
      ВЕРДИКТ: "Final Assessment",
      СОВЕТЫ: "What to Pay Attention To",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Analysis Limitations",
      ИТОГ: "Executive Summary",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Positive Factors",
      КРАСНЫЕ_ФЛАГИ: "Negative Factors",
    },
    metrics: {
      total_score: "Total score",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Buffett criteria",
      graham_number: "Graham value",
      dcf: "Value assessment",
      industry: "Industry",
      market_liquidity: "Liquidity",
      debt_burden: "Debt load",
      momentum: "Trend",
    },
  },
  uz: {
    pageTitle: "UZ Stock Analyzer",
    brand: "UZ Stock Analyzer",
    subtitle: "O'zbekiston kompaniyalarini tahlil qilish platformasi",
    nav: { main: "Bosh sahifa", about: "Loyiha haqida", auth: "Kirish", profile: "Profil", analysis: "Tahlil", catalog: "Katalog", news: "Yangiliklar" },
    catalog: {
      title: "Hisobotlar katalogi",
      subtitle: "openinfo.uz'dan barcha ro'yxatga olingan kompaniyalarning hisobotlari",
      searchPlaceholder: "Ticker yoki nomi bo'yicha qidirish...",
      syncAll: "Hammasini sinxronlash",
      syncCompany: "Yangilash",
      syncing: "Sinxronlanmoqda...",
      syncDone: "Yangilandi",
      empty: "Katalog bo'sh — «Hammasini sinxronlash» ni bosing",
      selectCompany: "Ro'yxatdan kompaniyani tanlang",
      noReports: "Hisobotlar topilmadi",
      notPublished: "Tanlangan davr uchun bu turdagi hisobot e'lon qilinmagan",
      available: "Hisobot mavjud",
      loading: "Yuklanmoqda...",
      reports: "hisobot",
      companies: "kompaniya",
      totalReports: "bazadagi hisobotlar",
      lastSync: "Oxirgi yangilanish",
      forms: { NSBU: "NSBU", MSFO: "MHXS", Audition: "Audit" },
      periods: { annual: "Yillik", q1: "Q1", q2: "Q2", q3: "Q3" },
      analysisLabel: "Tahlil turi",
      runAnalysis: "Tahlilni ishga tushirish",
      analysisLoading: "Tahlil qilinmoqda...",
      analysisTypes: {
        financial: "Moliyaviy tahlil",
        ratio: "Koeffitsientlar (ROA, ROE...)",
        dynamics: "Ko'rsatkichlar dinamikasi",
        quarter_compare: "Choraklar taqqoslash",
        annual_compare: "Yillik hisobotlar taqqoslash",
        swot: "SWOT tahlili",
        recommendation: "Tahliliy xulosa",
        multi_company: "Kompaniyalar taqqoslash",
      },
      compareWith: "Bilan solishtiring:",
      comparePeriod: "Taqqoslash davri:",
      noValue: "Ma'lumot yo'q",
      ratioLabels: { ROA: "ROA", ROE: "ROE", net_margin: "Sof marja", debt_ratio: "Qarz nisbati", debt_to_equity: "D/E" },
      dynamicsLabels: { revenue: "Daromad", net_income: "Sof foyda", total_assets: "Jami aktiv", equity: "Kapital", total_liabilities: "Majburiyatlar" },
      pdfReport: "PDFni ochish",
      excelIncome: "Excel — moliyaviy natija",
      excelBalance: "Excel — balans",
      excelReport: "Excel yuklab olish",
      exportPdf: "PDF yuklab olish",
      notifications: "Bildirishnomalar",
      notifEmpty: "Yangi hisobotlar yo'q",
      notifNewReport: "Yangi hisobot chop etildi",
    },
    languageLabel: "Til",
    languageOptions: { ru: "Ruscha", en: "English", uz: "O'zbek" },
    theme: { label: "Mavzu", light: "Yorug'", dark: "Qorong'i" },
    hero: {
      title: "Bitta panelda zamonaviy kompaniya tahlili",
      copy: "Kompaniyalarni tez tahlil qilish uchun veb-platforma: ro'yxatdan o'tish, kirish, profil, tanlanganlar, tarix va grafiklar bilan moliyaviy hisobot.",
      badges: ["Moliyaviy hisobotlar", "Shaxsiy kabinet", "Grafiklar va metrikalar"],
      ctas: { analysis: "Tahlilga o'tish", profile: "Profilni ochish" },
    },
    dashboard: {
      title: "Ko'rsatkichlar paneli",
      copy: "Loyiha bo'yicha asosiy ko'rsatkichlar va faollik",
      cards: {
        companies: "Katalogdagi kompaniyalar",
        analyses: "Jami tahlillar",
        avgScore: "O'rtacha baho",
        cached: "Keshdan",
      },
      activityTitle: "Tahlil faolligi",
      activityCopy: "So'nggi 14 kun ichidagi tahlillar soni",
      activityEmpty: "Bir nechta tahlildan keyin faollik ko'rinadi",
      peak: "Cho'qqi",
      trend: "Trend",
    },
    main: {
      title: "Investitsion tahlil platformasi",
      copy: "O'zbek kompaniyalarining professional tahlilini soniyalar ichida oling. Moliyaviy salomatlik, xavflar va o'sish imkoniyatlari.",
      features: [
        { icon: "chart", title: "Chuqur tahlil", copy: "Moliyaviy koeffitsientlar, daromad va foyda dinamikasi, balans tuzilishi" },
        { icon: "zap", title: "Tezkor natija", copy: "Grafik va hisobot tahlili bilan to'liq hisobot soniyalar ichida" },
        { icon: "shield", title: "Ishonchli ma'lumot", copy: "O'zbekiston birjasidan to'g'ridan-to'g'ri yangilangan moliyaviy hisobotlar" },
        { icon: "target", title: "Asosiy metrikalar", copy: "Likvidlik, volatillik, rentabellik va qarz yuki" },
      ],
      howItWorks: {
        title: "Qanday ishlaydi",
        steps: [
          { num: "01", title: "Kompaniyani tanlang", copy: "Ticker kiriting yoki mavjud kompaniyalar katalogidan tanlang" },
          { num: "02", title: "Tahlilni boshlang", copy: "Tizim ma'lumotlarni yig'adi va keng qamrovli moliyaviy tahlil o'tkazadi" },
          { num: "03", title: "Hisobotni oling", copy: "Baho, grafik va metrikalarni tahliliy xulosalar bilan ko'rib chiqing" },
        ],
      },
      stats: {
        title: "Platforma raqamlarda",
        items: [
          { value: "50+", label: "Kompaniyalar" },
          { value: "15+", label: "Tahlil metrikasi" },
          { value: "24/7", label: "Mavjudlik" },
          { value: "100%", label: "Bepul" },
        ],
      },
      cta: {
        title: "Boshlashga tayyormisiz?",
        copy: "Bepul ro'yxatdan o'ting va barcha tahlil vositalariga kirish imkoniyatiga ega bo'ling",
        button: "Tahlilni boshlash",
      },
    },
    about: {
      title: "Loyiha haqida",
      leftCards: [
        { title: "Backend", copy: "API, avtorizatsiya, Postgres va tahlil bitta qatlam sifatida ishlaydi." },
        { title: "Frontend", copy: "Yangi interfeys React va Vite asosida yig'ilgan." },
        { title: "Taqdimot", copy: "Natija kartalar, grafiklar va ixcham akкордеonlar orqali ko'rsatiladi." },
      ],
      rightTitle: "Foydalanuvchi nimani oladi",
      rightCards: [
        { title: "Baho", copy: "Tez orientatsiya uchun yagona ko'rsatkich." },
        { title: "Xulosa", copy: "Qisqa yakuniy baho." },
        { title: "Metrikalar", copy: "Likvidlik, rentabellik, qarz yuki va trend dinamikasi." },
        { title: "Tarix", copy: "Saqlangan tahlillar va tanlangan kompaniyalar." },
      ],
    },
    auth: {
      title: "Kirish",
      signedOut: "Kirish yo'q",
      signedIn: "Kirish amalga oshirildi",
      loginTab: "Kirish",
      registerTab: "Ro'yxatdan o'tish",
      login: { email: "Email", password: "Parol", submit: "Kirish" },
      register: { fullName: "Ism va familiya", email: "Email", password: "Parol", submit: "Akkaunt yaratish" },
      oauthLabel: "Yoki davom eting",
      google: "Google",
      logout: "Chiqish",
      signedInAs: "Kirish amalga oshirildi",
      messages: {
        loginOk: "Kirish amalga oshirildi",
        registerOk: "Akkaunt yaratildi",
        logoutOk: "Chiqish amalga oshirildi",
        authRequired: "Avval tizimga kiring",
      },
    },
    profile: {
      title: "Profil",
      subtitle: "Profil, statistika, tanlanganlar va tarix",
      editTitle: "Profilni tahrirlash",
      name: "Ko'rinadigan ism",
      avatar: "Avatar",
      save: "Saqlash",
      clearAvatar: "Avatarni o'chirish",
      refresh: "Yangilash",
      analyze: "Tahlilga o'tish",
      statsTitle: "Faollik",
      favoritesTitle: "Tanlanganlar",
      historyTitle: "Tahlillar tarixi",
      repeat: "Takrorlash",
      stats: {
        totalAnalyses: "Jami tahlillar",
        analyses7d: "7 kun ichida",
        analyses30d: "30 kun ichida",
        analyzedCompanies: "Tarixdagi kompaniyalar",
        avgScore: "O'rtacha baho",
        bestScore: "Eng yaxshi baho",
        cachedAnalyses: "Keshdan",
        topCompany: "Eng ko'p ko'rilgan",
      },
      empty: "Profil tizimga kirgandan keyin ko'rinadi.",
      historyEmpty: "Birinchi tahlildan keyin bu yerda tarix paydo bo'ladi.",
      favoritesEmpty: "Tahlil yoki tarixdan kompaniyalarni tanlanganlarga qo'shing.",
      filters: { search: "Kompaniya yoki ticker bo'yicha qidirish", all: "Barcha tahlillar", favorites: "Faqat tanlanganlar" },
      remove: "O'chirish",
    },
    analysis: {
      title: "Kompaniya tahlili",
      company: "Kompaniya",
      mode: "Rejim",
      quick: "Tez",
      full: "To'liq",
      reportType: "Tahlil turi",
      fullAnalysis: "To'liq tahlil",
      quarterlyReport: "Choraklik",
      annualReport: "Yillik",
      quarter: "Chorak",
      currentYear: "Taqqoslanadigan yil",
      previousYear: "Bilan solishtirish",
      reportingForm: "Hisobot shakli",
      reportFormIFRS: "MXHS",
      reportFormNAS: "MHBS",
      reportFormAudit: "Auditorlik xulosasi",
      reportFormHint: "Shakl tanlash faqat choraklik/yillik taqqoslash rejimiga ta'sir qiladi. MHBS — openinfo.uz'da Excel ma'lumotlari mavjud bo'lgan yagona shakl. MXHS va auditorlik xulosalari Excel jadvallarsiz PDF formatida nashr etiladi.",
      reportFormLatestNote: "«To'liq tahlil» rejimida ma'lumotlar MHBS tizimli hisobotlaridan (forma 1 + forma 2) olinadi. Hisobot shakli faqat choraklik/yillik taqqoslashda qo'llaniladi.",
      reportFormNotFound: "Kompaniya tanlangan davr uchun ushbu turdagi hisobotni nashr etmagan.",
      forceRefresh: "Manbadan yangilash (keshni chetlab o'tish)",
      submit: "Tahlil qilish",
      availableTitle: "Mavjud kompaniyalar",
      resultTitle: "Natija",
      resultEmpty: "Tahlil hali bajarilmagan",
      resultLoading: "Tahlil bajarilmoqda...",
      resultCacheWaiting: "Kutilmoqda",
      resultCacheHit: "Keshdan",
      resultFresh: "Yangi natija",
      score: "Baho / 100",
      verdictPlaceholder: "Yakuniy xulosani ko'rish uchun tahlilni ishga tushiring.",
      metricsTitle: "Asosiy ko'rsatkichlar",
      sectionsTitle: "Hisobot bo'limlari",
      favoriteAdd: "Tanlanganlarga qo'shish",
      favoriteRemove: "Tanlanganlardan olib tashlash",
      chartTitle: "Tushum va foyda dinamikasi",
      chartEmpty: "Grafik birinchi tahlildan so'ng paydo bo'ladi.",
      chartMetaEmpty: "Ma'lumot yo'q",
      noData: "Ma'lumot yo'q",
      signalRevenue: "Tushum",
      signalDebt: "Majburiyatlar",
      signalMargin: "Marja",
      signalRisk: "Risk",
      signalTrend: "Trend",
      signalLatest: "So'nggi",
      signalUp: "Ijobiy",
      signalFlat: "Barqaror",
      signalDown: "Bosim ostida",
      loadingMetrics: "Yuklanmoqda",
      loadingChart: "Grafik yuklanmoqda",
      loadingSections: "Hisobot yuklanmoqda",
      loadingCache: "Tekshirilmoqda",
      completed: "Tahlil yakunlandi",
    },
    toasts: { success: "Tayyor", error: "Xato", info: "Ma'lumot" },
    sections: {
      ОБЩИЕ_СВЕДЕНИЯ: "Emitent haqida umumiy ma'lumot va tahlil metodologiyasi",
      ГОРИЗОНТАЛЬНЫЙ_АНАЛИЗ: "Buxgalteriya balansining gorizontal tahlili",
      ВЕРТИКАЛЬНЫЙ_АНАЛИЗ: "Buxgalteriya balansining vertikal tahlili",
      АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ: "Moliyaviy natijalar hisoboti tahlili",
      КОЭФФИЦИЕНТНЫЙ_АНАЛИЗ: "Moliyaviy koeffitsientlar tahlili",
      СВОДНАЯ_ТАБЛИЦА: "Asosiy ko'rsatkichlarning umumlashtirilgan jadvali",
      ЗАКЛЮЧЕНИЕ: "Yakuniy baho",
      СКОРИНГ: "Hisobot bo'yicha asosiy kuzatuvlar",
      ДОСЬЕ: "Emitent haqida qisqacha ma'lumot",
      ЧТО_С_ДЕНЬГАМИ: "Moliyaviy holat qisqacha",
      ТРЕНД: "Trendlar va dinamika tahlili",
      ЭФФЕКТИВНОСТЬ: "Operatsion samaradorlik va aylanma",
      ТЕХНИЧЕСКИЙ_АНАЛИЗ: "Texnik tahlil (RSI, Fibonachchi, hajmlar)",
      ОЦЕНКА_СТОИМОСТИ: "Ko'rsatkichlar asosida baholash",
      ФИБОНАЧЧИ: "Texnik tahlil (Fibonachchi darajalari)",
      ОЦЕНКА_ЦЕНЫ: "Qiymat va narx sifatini baholash",
      КАТАЛИЗАТОРЫ: "Aksiya narxiga ta'sir qiluvchi omillar",
      РЫНОЧНЫЕ_ДАННЫЕ: "Bozor ma'lumotlari va likvidlik",
      СИЛЬНЫЕ_СТОРОНЫ: "Kuchli tomonlar va raqobatbardosh ustunliklar",
      СЛАБЫЕ_СТОРОНЫ: "Xavflar va zaif tomonlar",
      ВОЗМОЖНОСТИ: "O'sish imkoniyatlari",
      УГРОЗЫ: "Tahdidlar va tashqi xavflar",
      ПРОГНОЗ: "Dinamikaning tahliliy sharhi",
      ВЕРДИКТ: "Yakuniy baho",
      СОВЕТЫ: "Nimaga e'tibor berish kerak",
      ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА: "Tahlil cheklovlari",
      ИТОГ: "Investor uchun xulosa",
      ЗЕЛЕНЫЕ_ФЛАГИ: "Ijobiy omillar",
      КРАСНЫЕ_ФЛАГИ: "Salbiy omillar",
    },
    metrics: {
      total_score: "Yakuniy baho",
      piotroski_f_score: "Piotroski F-Score",
      altman_z_score: "Altman Z-Score",
      buffett_criteria: "Baffet mezonlari",
      graham_number: "Grem qiymati",
      dcf: "Qiymat bahosi",
      industry: "Sektor",
      market_liquidity: "Likvidlik",
      debt_burden: "Qarz yuki",
      momentum: "Trend",
    },
  },
};

const VISUAL_TEXTS = {
  ru: {
    dashboardPeriod: "14 дней",
    sparklineEmpty: "пока нет истории",
    financialStructure: "Финансовая структура",
    financialStructureCopy: "Последние доступные данные МСФО",
    scoreAndRisk: "Скоринг и устойчивость",
    scoreAndRiskCopy: "Ключевые индикаторы качества и риска",
    revenue: "Выручка",
    ebitda: "EBITDA",
    netIncome: "Чистая прибыль",
    assets: "Активы",
    equity: "Капитал",
    debt: "Обязательства",
    totalScore: "Итоговый скоринг",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Долговая нагрузка",
    noVisualData: "Недостаточно данных для визуализации",
    latestPeriod: "последний период",
  },
  en: {
    dashboardPeriod: "14 days",
    sparklineEmpty: "no history yet",
    financialStructure: "Financial structure",
    financialStructureCopy: "Latest available IFRS data",
    scoreAndRisk: "Score and resilience",
    scoreAndRiskCopy: "Core quality and risk indicators",
    revenue: "Revenue",
    ebitda: "EBITDA",
    netIncome: "Net income",
    assets: "Assets",
    equity: "Equity",
    debt: "Liabilities",
    totalScore: "Total score",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Leverage",
    noVisualData: "Not enough data to visualize",
    latestPeriod: "latest period",
  },
  uz: {
    dashboardPeriod: "14 kun",
    sparklineEmpty: "hozircha tarix yo'q",
    financialStructure: "Moliyaviy tuzilma",
    financialStructureCopy: "So'nggi mavjud IFRS ma'lumotlari",
    scoreAndRisk: "Skoring va barqarorlik",
    scoreAndRiskCopy: "Sifat va risk bo'yicha asosiy indikatorlar",
    revenue: "Daromad",
    ebitda: "EBITDA",
    netIncome: "Sof foyda",
    assets: "Aktivlar",
    equity: "Kapital",
    debt: "Majburiyatlar",
    totalScore: "Yakuniy skoring",
    piotroski: "Piotroski",
    altman: "Altman Z",
    leverage: "Qarz yuki",
    noVisualData: "Vizualizatsiya uchun ma'lumot yetarli emas",
    latestPeriod: "so'nggi davr",
  },
};

const DISCLOSURE_TEXTS = {
  ru: {
    capabilitiesLabel: "Информационный контур",
    capabilitiesTitle: "Система должна обеспечивать",
    capabilitiesIntro: "Система проектируется как справочный слой для просмотра рыночной информации и базовых данных фондового рынка.",
    capabilities: [
      "Просмотр котировок",
      "Просмотр графиков цен",
      "Просмотр объемов торгов",
      "Просмотр списка эмитентов",
      "Просмотр облигаций",
      "Просмотр новостей",
      "Просмотр листинга и делистинга",
      "Просмотр режимов торгов",
      "Просмотр тарифов",
      "Просмотр терминов фондового рынка",
      "Просмотр общерыночной статистики",
    ],
    restrictionsLabel: "Публичные ограничения",
    restrictionsTitle: "Ограничения публичного контура",
    restrictionsIntro: "Публичная часть сервиса должна оставаться информационной и не подменять профессиональную консультацию.",
    restrictions: [
      "Персональные данные",
      "Прогнозная аналитика",
      "Инвестиционные рекомендации",
      "Индивидуальные аналитические выводы",
      "Юридические заключения",
    ],
  },
  en: {
    capabilitiesLabel: "Information scope",
    capabilitiesTitle: "The system should provide",
    capabilitiesIntro: "The system is designed as a reference layer for market data and basic stock market information.",
    capabilities: [
      "Quotes",
      "Price charts",
      "Trading volumes",
      "Issuer list",
      "Bonds",
      "News",
      "Listings and delistings",
      "Trading modes",
      "Tariffs",
      "Stock market terms",
      "Market-wide statistics",
    ],
    restrictionsLabel: "Public restrictions",
    restrictionsTitle: "Public scope restrictions",
    restrictionsIntro: "The public part of the service must remain informational and must not replace professional advice.",
    restrictions: [
      "Personal data",
      "Forecast analytics",
      "Investment recommendations",
      "Individual analytical conclusions",
      "Legal opinions",
    ],
  },
  uz: {
    capabilitiesLabel: "Axborot konturi",
    capabilitiesTitle: "Tizim ta'minlashi kerak",
    capabilitiesIntro: "Tizim bozor ma'lumotlari va fond bozori bo'yicha asosiy ma'lumotlarni ko'rish uchun axborot qatlami sifatida loyihalanadi.",
    capabilities: [
      "Kotirovkalarni ko'rish",
      "Narx grafiklarini ko'rish",
      "Savdo hajmlarini ko'rish",
      "Emitentlar ro'yxatini ko'rish",
      "Obligatsiyalarni ko'rish",
      "Yangiliklarni ko'rish",
      "Listing va delistingni ko'rish",
      "Savdo rejimlarini ko'rish",
      "Tariflarni ko'rish",
      "Fond bozori terminlarini ko'rish",
      "Umumbozor statistikasini ko'rish",
    ],
    restrictionsLabel: "Ommaviy cheklovlar",
    restrictionsTitle: "Ommaviy kontur cheklovlari",
    restrictionsIntro: "Servisning ommaviy qismi axborot xarakterida bo'lishi va professional maslahat o'rnini bosmasligi kerak.",
    restrictions: [
      "Shaxsiy ma'lumotlar",
      "Prognoz analitikasi",
      "Investitsion tavsiyalar",
      "Individual analitik xulosalar",
      "Huquqiy xulosalar",
    ],
  },
};

function normalizeLanguage(value) {
  return ["ru", "en", "uz"].includes(value) ? value : "ru";
}

function t(language, path, params = {}) {
  const lang = normalizeLanguage(language);
  const parts = path.split(".");
  const resolve = (obj) => {
    let current = obj;
    for (const part of parts) {
      current = current?.[part];
    }
    return current;
  };
  let value = resolve(TEXTS[lang]) ?? resolve(TEXTS.ru);
  if (value === undefined || value === null) return "";
  const stringValue = String(value);
  return stringValue.replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? ""));
}

function vt(language, key) {
  const lang = normalizeLanguage(language);
  return VISUAL_TEXTS[lang]?.[key] ?? VISUAL_TEXTS.ru[key] ?? key;
}

function disclosureText(language) {
  return DISCLOSURE_TEXTS[normalizeLanguage(language)] ?? DISCLOSURE_TEXTS.ru;
}

const COMPARE_TEXTS = {
  ru: {
    nav: "Сравнение",
    title: "Сравнение эмитентов",
    subtitle: "Сравните 2-5 компаний по МСФО, рыночной ликвидности, отчетам и нормализованным показателям 0-100.",
    company1: "Компания 1",
    company2: "Компания 2",
    company3: "Компания 3",
    company4: "Компания 4",
    company5: "Компания 5",
    placeholder: "Тикер или название компании",
    optional: "необязательно",
    includeAi: "Сформировать comparative AI summary",
    submit: "Сравнить",
    loading: "Сравнение выполняется...",
    ready: "Сравнение готово",
    authRequired: "Сначала выполните вход",
    minRequired: "Выберите минимум две разные компании",
    overview: "Итог сравнения",
    leaders: "Лидеры по ключевым блокам",
    charts: "Сравнительные графики",
    tables: "Сравнительные таблицы",
    aiSummary: "Comparative AI summary",
    methodology: "Методика",
    ranking: "Рейтинг",
    normalizedRanking: "Нормализованный рейтинг",
    normalizedNote: "Все разнородные метрики приведены к шкале 0-100: чем выше, тем сильнее позиция компании.",
    noData: "Нет данных",
    empty: "Добавьте 2-5 компаний и запустите сравнение.",
    quick: "Быстрый выбор",
    errors: "Предупреждения",
    raw: "значение",
    normalized: "норм.",
    rank: "место",
  },
  en: {
    nav: "Compare",
    title: "Issuer comparison",
    subtitle: "Compare 2-5 companies by IFRS metrics, market liquidity, reports, and normalized 0-100 indicators.",
    company1: "Company 1",
    company2: "Company 2",
    company3: "Company 3",
    company4: "Company 4",
    company5: "Company 5",
    placeholder: "Ticker or company name",
    optional: "optional",
    includeAi: "Generate comparative AI summary",
    submit: "Compare",
    loading: "Comparison is running...",
    ready: "Comparison is ready",
    authRequired: "Please sign in first",
    minRequired: "Select at least two different companies",
    overview: "Comparison result",
    leaders: "Leaders by key blocks",
    charts: "Comparative charts",
    tables: "Comparative tables",
    aiSummary: "Comparative AI summary",
    methodology: "Methodology",
    ranking: "Ranking",
    normalizedRanking: "Normalized ranking",
    normalizedNote: "Different metrics are normalized to a 0-100 scale: higher means a stronger relative position.",
    noData: "No data",
    empty: "Add 2-5 companies and run comparison.",
    quick: "Quick pick",
    errors: "Warnings",
    raw: "value",
    normalized: "norm.",
    rank: "rank",
  },
  uz: {
    nav: "Taqqoslash",
    title: "Emitentlarni taqqoslash",
    subtitle: "2-5 kompaniyani IFRS ko'rsatkichlari, bozor likvidligi, hisobotlar va 0-100 normalizatsiya bo'yicha solishtiring.",
    company1: "Kompaniya 1",
    company2: "Kompaniya 2",
    company3: "Kompaniya 3",
    company4: "Kompaniya 4",
    company5: "Kompaniya 5",
    placeholder: "Ticker yoki kompaniya nomi",
    optional: "ixtiyoriy",
    includeAi: "Comparative AI summary yaratish",
    submit: "Taqqoslash",
    loading: "Taqqoslash bajarilmoqda...",
    ready: "Taqqoslash tayyor",
    authRequired: "Avval tizimga kiring",
    minRequired: "Kamida ikki xil kompaniyani tanlang",
    overview: "Taqqoslash natijasi",
    leaders: "Asosiy bloklar bo'yicha liderlar",
    charts: "Taqqoslash grafiklari",
    tables: "Taqqoslash jadvallari",
    aiSummary: "Comparative AI summary",
    methodology: "Metodika",
    ranking: "Reyting",
    normalizedRanking: "Normalizatsiya reytingi",
    normalizedNote: "Turli metrikalar 0-100 shkalasiga keltiriladi: yuqori qiymat nisbatan kuchliroq pozitsiyani bildiradi.",
    noData: "Ma'lumot yo'q",
    empty: "2-5 kompaniya qo'shing va taqqoslashni boshlang.",
    quick: "Tez tanlash",
    errors: "Ogohlantirishlar",
    raw: "qiymat",
    normalized: "norm.",
    rank: "o'rin",
  },
};

function ct(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_TEXTS[lang]?.[key] ?? COMPARE_TEXTS.ru[key] ?? key;
}

const MARKET_TEXTS = {
  ru: {
    nav: "Рынок",
    title: "Цены акций UZSE",
    subtitle: "Актуальные цены, дневной диапазон и изменение к предыдущему закрытию",
    updated: "Обновлено",
    refresh: "Обновить",
    loading: "Загружаем котировки...",
    ready: "Котировки загружены",
    empty: "Нет данных по выбранному фильтру",
    search: "Поиск по тикеру или компании",
    all: "Все",
    stocks: "Акции",
    bonds: "Облигации",
    preferredStocks: "Привилегированные",
    ordinaryStocks: "Обыкновенные",
    bondOne: "облигация",
    instruments: "Инструментов",
    traded: "Сделки сегодня",
    advancers: "Рост",
    decliners: "Снижение",
    unchanged: "Без изменений",
    topGrowth: "Лидер роста",
    topDrop: "Лидер снижения",
    tableTitle: "Биржевые инструменты",
    showing: "Показано",
    ticker: "Тикер",
    company: "Компания",
    last: "Последняя",
    change: "Изм.",
    open: "Открытие",
    high: "Макс.",
    low: "Мин.",
    date: "Дата сделки",
    closeDate: "закр.",
    type: "Тип",
    ordinary: "обыкновенный",
    preferred: "привилегированный",
    source: "UZSE",
    analyze: "Анализ",
    noTrade: "нет сделки",
    volume: "Объём торгов",
    marketCap: "Капитализация",
    volumeCol: "Объём",
    tradeCount: "сделок",
    volQty: "Объём (шт)",
    avgSharePrice: "Ср. цена акции",
    avgTradePrice: "Ср. сумма сделки",
    volShare: "% объёма",
    bigTrade: "Крупнейшая сделка",
    tradeQtyUnit: "шт",
    grpOverview: "Обзор AI-скринер",
    grpVolumes: "Объёмы",
    grpFinancials: "Фин. показатели",
    grpMultiples: "Мультипликаторы",
    mktCap: "Капитализация",
    netMargin: "Чистая маржа",
    debtEquity: "Долг/Капитал",
    exportCsv: "Экспорт CSV",
    topGainers: "Топ роста",
    topLosers: "Топ падения",
    finRevenue: "Выручка",
    finGross: "Валовая прибыль",
    finCash: "Наличность в кассе",
    finLiab: "Общие обязательства",
    finNet: "Чистая прибыль",
    finOperating: "Операц. доход",
    isin: "ISIN",
    sector: "Сектор",
    shareType: "Тип бумаги",
    pe: "P/E",
    pb: "P/B",
    roe: "ROE, %",
    roa: "ROA, %",
    finPeriod: "Отчётный период",
    finCoverage: "Охват периода",
    csvTrades: "Сделок",
    csvTitle: "UZSE — рынок и отчётность эмитентов",
    csvGenerated: "Выгружено",
    csvSession: "Торговая сессия",
    csvFilter: "Фильтр",
    csvSort: "Сортировка",
    csvSortDefault: "по дате сделки, затем по модулю изменения",
    csvRows: "Строк",
    csvFav: "только избранное",
    csvSearch: "поиск",
    csvSources: "Котировки — UZSE (uzse.uz). Финансовая отчётность — раскрытия эмитентов (openinfo.uz). Капитализация, мультипликаторы и коэффициенты рассчитаны платформой.",
    csvMoneyNote: "Денежные величины — в сумах (UZS).",
  },
  en: {
    nav: "Market",
    title: "UZSE stock prices",
    subtitle: "Latest prices, daily range, and change versus previous close",
    updated: "Updated",
    refresh: "Refresh",
    loading: "Loading quotes...",
    ready: "Quotes loaded",
    empty: "No instruments for this filter",
    search: "Search ticker or company",
    all: "All",
    stocks: "Stocks",
    bonds: "Bonds",
    preferredStocks: "Preferred",
    ordinaryStocks: "Ordinary",
    bondOne: "bond",
    instruments: "Instruments",
    traded: "Traded today",
    advancers: "Up",
    decliners: "Down",
    unchanged: "Unchanged",
    topGrowth: "Top gainer",
    topDrop: "Top decliner",
    tableTitle: "Market instruments",
    showing: "Showing",
    ticker: "Ticker",
    company: "Company",
    last: "Last",
    change: "Chg.",
    open: "Open",
    high: "High",
    low: "Low",
    date: "Trade date",
    closeDate: "close",
    type: "Type",
    ordinary: "ordinary share",
    preferred: "preferred share",
    source: "UZSE",
    analyze: "Analyze",
    noTrade: "no trade",
    volume: "Volume",
    marketCap: "Market cap",
    volumeCol: "Volume",
    tradeCount: "trades",
    volQty: "Volume (units)",
    avgSharePrice: "Avg share price",
    avgTradePrice: "Avg trade size",
    volShare: "% of volume",
    bigTrade: "Largest trade",
    tradeQtyUnit: "units",
    grpOverview: "AI screener overview",
    grpVolumes: "Volumes",
    grpFinancials: "Financials",
    grpMultiples: "Multiples",
    mktCap: "Market cap",
    netMargin: "Net margin",
    debtEquity: "Debt/Equity",
    exportCsv: "Export CSV",
    topGainers: "Top gainers",
    topLosers: "Top losers",
    finRevenue: "Revenue",
    finGross: "Gross profit",
    finCash: "Cash on hand",
    finLiab: "Total liabilities",
    finNet: "Net profit",
    finOperating: "Operating income",
    isin: "ISIN",
    sector: "Sector",
    shareType: "Security type",
    pe: "P/E",
    pb: "P/B",
    roe: "ROE, %",
    roa: "ROA, %",
    finPeriod: "Reporting period",
    finCoverage: "Period coverage",
    csvTrades: "Trades",
    csvTitle: "UZSE — market and issuer reporting",
    csvGenerated: "Exported",
    csvSession: "Trading session",
    csvFilter: "Filter",
    csvSort: "Sorted by",
    csvSortDefault: "trade date, then absolute change",
    csvRows: "Rows",
    csvFav: "favorites only",
    csvSearch: "search",
    csvSources: "Quotes — UZSE (uzse.uz). Financial statements — issuer filings (openinfo.uz). Market cap, multiples and ratios are computed by the platform.",
    csvMoneyNote: "Monetary figures are in soum (UZS).",
  },
  uz: {
    nav: "Bozor",
    title: "UZSE aksiya narxlari",
    subtitle: "So'nggi narxlar, kunlik oraliq va oldingi yopilish bilan farq",
    updated: "Yangilandi",
    refresh: "Yangilash",
    loading: "Kotirovkalar yuklanmoqda...",
    ready: "Kotirovkalar yuklandi",
    empty: "Bu filtr bo'yicha ma'lumot yo'q",
    search: "Ticker yoki kompaniya bo'yicha qidirish",
    all: "Hammasi",
    stocks: "Aksiyalar",
    bonds: "Obligatsiyalar",
    preferredStocks: "Imtiyozli",
    ordinaryStocks: "Oddiy",
    bondOne: "obligatsiya",
    instruments: "Instrumentlar",
    traded: "Bugun savdo bo'lgan",
    advancers: "O'sish",
    decliners: "Pasayish",
    unchanged: "O'zgarishsiz",
    topGrowth: "Eng katta o'sish",
    topDrop: "Eng katta pasayish",
    tableTitle: "Bozor instrumentlari",
    showing: "Ko'rsatilgan",
    ticker: "Ticker",
    company: "Kompaniya",
    last: "So'nggi",
    change: "O'zg.",
    open: "Ochilish",
    high: "Maks.",
    low: "Min.",
    date: "Savdo sanasi",
    closeDate: "yop.",
    type: "Tur",
    ordinary: "oddiy aksiya",
    preferred: "imtiyozli aksiya",
    source: "UZSE",
    analyze: "Tahlil",
    noTrade: "savdo yo'q",
    volume: "Savdo hajmi",
    marketCap: "Kapitalizatsiya",
    volumeCol: "Hajm",
    tradeCount: "savdo",
    volQty: "Hajm (dona)",
    avgSharePrice: "O'rt. aksiya narxi",
    avgTradePrice: "O'rt. bitim summasi",
    volShare: "Hajm %",
    bigTrade: "Eng katta bitim",
    tradeQtyUnit: "dona",
    grpOverview: "AI-skrener sharhi",
    grpVolumes: "Hajmlar",
    grpFinancials: "Moliyaviy ko'rsatkichlar",
    grpMultiples: "Multiplikatorlar",
    mktCap: "Kapitalizatsiya",
    netMargin: "Sof marja",
    debtEquity: "Qarz/Kapital",
    exportCsv: "CSV eksport",
    topGainers: "Eng ko'p o'sganlar",
    topLosers: "Eng ko'p tushganlar",
    finRevenue: "Tushum",
    finGross: "Yalpi foyda",
    finCash: "Kassadagi naqd",
    finLiab: "Jami majburiyatlar",
    finNet: "Sof foyda",
    finOperating: "Operatsion daromad",
    isin: "ISIN",
    sector: "Sektor",
    shareType: "Qogʻoz turi",
    pe: "P/E",
    pb: "P/B",
    roe: "ROE, %",
    roa: "ROA, %",
    finPeriod: "Hisobot davri",
    finCoverage: "Davr qamrovi",
    csvTrades: "Bitimlar",
    csvTitle: "UZSE — bozor va emitentlar hisoboti",
    csvGenerated: "Yuklab olingan",
    csvSession: "Savdo sessiyasi",
    csvFilter: "Filtr",
    csvSort: "Saralash",
    csvSortDefault: "bitim sanasi, soʻng oʻzgarish moduli",
    csvRows: "Qatorlar",
    csvFav: "faqat tanlanganlar",
    csvSearch: "qidiruv",
    csvSources: "Kotirovkalar — UZSE (uzse.uz). Moliyaviy hisobot — emitentlar oshkor qilishi (openinfo.uz). Kapitalizatsiya, multiplikatorlar va koeffitsiyentlar platforma tomonidan hisoblangan.",
    csvMoneyNote: "Pul qiymatlari soʻmda (UZS).",
  },
};

const SECTOR_LABELS = {
  ru: {
    all: "Все",
    finance: "Финансы",
    funds: "Фонды",
    manufacturing: "Производство",
    mining: "Добыча",
    transport: "Транспорт",
    logistics: "Логистика",
    telecom: "Телеком",
    trade: "Торговля",
    professional: "Услуги",
    other: "Прочее",
  },
  en: {
    all: "All",
    finance: "Finance",
    funds: "Funds",
    manufacturing: "Manufacturing",
    mining: "Mining",
    transport: "Transport",
    logistics: "Logistics",
    telecom: "Telecom",
    trade: "Trade",
    professional: "Services",
    other: "Other",
  },
  uz: {
    all: "Hammasi",
    finance: "Moliya",
    funds: "Fondlar",
    manufacturing: "Ishlab chiqarish",
    mining: "Konchilik",
    transport: "Transport",
    logistics: "Logistika",
    telecom: "Telekom",
    trade: "Savdo",
    professional: "Xizmatlar",
    other: "Boshqalar",
  },
};

function sectorLabel(language, sector) {
  const lang = normalizeLanguage(language);
  return SECTOR_LABELS[lang]?.[sector] ?? SECTOR_LABELS.ru[sector] ?? sector;
}

function mt(language, key) {
  const lang = normalizeLanguage(language);
  return MARKET_TEXTS[lang]?.[key] ?? MARKET_TEXTS.ru[key] ?? key;
}

function safeNumber(value) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatDateLabel(value, language) {
  if (!value) return t(language, "analysis.noData");
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return t(language, "analysis.noData");
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, { day: "2-digit", month: "long", year: "numeric" }).format(date);
}

function formatCompactNumber(value, language, digits = 1) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    notation: Math.abs(num) >= 1000 ? "compact" : "standard",
    maximumFractionDigits: digits,
  }).format(num);
}

function formatSignedPercent(value, digits = 1) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const fixed = Number(num.toFixed(digits));
  return `${fixed > 0 ? "+" : ""}${fixed}%`;
}

function formatRatio(value, digits = 2, language = "ru") {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(num);
}

function formatMarketNumber(value, language, digits = 2) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: Math.abs(num) < 10 ? 2 : 0,
    maximumFractionDigits: digits,
  }).format(num);
}

function formatCompactVolume(value, lang) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "—";
  if (num >= 1e9) return formatRatio(num / 1e9, 1, lang) + "B";
  if (num >= 1e6) return formatRatio(num / 1e6, 1, lang) + "M";
  if (num >= 1e3) return formatRatio(num / 1e3, 1, lang) + "K";
  return formatRatio(num, 0, lang);
}

function formatMarketTimestamp(value, language) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  return new Intl.DateTimeFormat(locale, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

// "1 сделок" is what a bare noun gives you in Russian. The board prints the
// trade count under the turnover on every row, so the wrong form is on screen
// seventy times at once. Uzbek takes no plural marker after a numeral, and
// English needs only the two forms.
function tradeCountLabel(n, language) {
  const abs = Math.abs(Math.round(Number(n) || 0));
  if (language === "uz") return "savdo";
  if (language === "en") return abs === 1 ? "trade" : "trades";
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod10 === 1 && mod100 !== 11) return "сделка";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "сделки";
  return "сделок";
}

// Same three Russian forms, for the sessions counted since a story was published.
function sessionCountLabel(n, language) {
  const abs = Math.abs(Math.round(Number(n) || 0));
  if (language === "uz") return "sessiya";
  if (language === "en") return abs === 1 ? "session" : "sessions";
  const mod10 = abs % 10;
  const mod100 = abs % 100;
  if (mod10 === 1 && mod100 !== 11) return "сессия";
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return "сессии";
  return "сессий";
}

// Tooltip behind the "Обновлено" badge: the trading session the numbers belong
// to, and the exchange mirror's own stamp — the two facts the headline number
// deliberately leaves out.
function marketStampTitle(meta, language) {
  const lines = [];
  const session = meta?.trade_date;
  if (session) {
    // `catalog_trade_stats.trade_date` is compacted YYYYMMDD in production
    // (that is the form the day-vs-day comparisons use), while older rows and
    // the listings registry carry ISO. Accept both rather than printing
    // "20260731" at a reader.
    const raw = String(session);
    const iso = /^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}` : raw;
    const d = new Date(`${iso}T00:00:00`);
    const shown = Number.isNaN(d.getTime())
      ? raw
      : new Intl.DateTimeFormat(language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU",
          { day: "2-digit", month: "short", year: "numeric" }).format(d);
    lines.push(`${language === "en" ? "Trading session" : language === "uz" ? "Savdo sessiyasi" : "Торговая сессия"}: ${shown}`);
  }
  if (meta?.updated_at) {
    lines.push(`${language === "en" ? "Exchange feed" : language === "uz" ? "Birja lentasi" : "Биржевая лента"}: ${formatMarketTimestamp(meta.updated_at, language)}`);
  }
  return lines.join("\n") || undefined;
}

function marketChange(stock) {
  // last_price is null when no trade happened today; Number(null)=0 so we
  // must guard on the raw value, not the coerced number.
  if (stock?.last_price == null) return { value: null, percent: null };
  const last = safeNumber(stock.last_price);
  const close = safeNumber(stock.close_price);
  if (last === null || close === null || close === 0) {
    return { value: null, percent: null };
  }
  const value = last - close;
  return {
    value,
    percent: (value / Math.abs(close)) * 100,
  };
}

function marketTone(percent) {
  if (percent === null || percent === undefined || !Number.isFinite(Number(percent))) return "neutral";
  if (Number(percent) > 0.05) return "good";
  if (Number(percent) < -0.05) return "danger";
  return "neutral";
}

function enrichMarketStock(stock) {
  const change = marketChange(stock);
  return {
    ...stock,
    lastPrice: safeNumber(stock?.last_price),
    closePrice: safeNumber(stock?.close_price),
    openPrice: safeNumber(stock?.open) || null,
    highPrice: safeNumber(stock?.high) || null,
    lowPrice: safeNumber(stock?.low) || null,
    stockVolume: safeNumber(stock?.volume),
    stockQuantity: safeNumber(stock?.quantity),
    stockTradeCount: safeNumber(stock?.trade_count),
    marketCap: safeNumber(stock?.market_cap) || null,
    nominal: safeNumber(stock?.nominal) || null,
    sharesOutstanding: safeNumber(stock?.shares_outstanding) || null,
    changeValue: change.value,
    changePercent: change.percent,
    // Did this security trade in the session the board is showing? The
    // exchange carries a close forward through sessions with no executions, so
    // last == prev proves nothing on its own — a security CAN trade and close
    // exactly flat, and that is a real 0 %. Only activity separates the two.
    tradedToday: (safeNumber(stock?.trade_count) || 0) > 0
      || (safeNumber(stock?.volume) || 0) > 0
      || (safeNumber(stock?.quantity) || 0) > 0,
    tone: marketTone(change.percent),
  };
}

// The newest session any stored day-statistic describes.
function latestTradeStatsDay(tmap) {
  return Object.values(tmap || {}).reduce((m, t) => {
    const d = String(t?.trade_date || "");
    return /^\d{8}$/.test(d) && (!m || d > m) ? d : m;
  }, null);
}

// Reconcile ONE enriched board row against the stored per-trade day statistics.
//
// Per-trade stats (UZSE) are the complete, correct daily totals — the plain
// /stocks snapshot can be stale. When present, override turnover/qty/trades with
// them and expose the average trade price. The change stays close-to-close (the
// exchange's official convention — UZSE's daily bulletin computes O'zgarish from
// the closing price, not the day's average; and a backfilled older day's average
// vs the current close would fabricate a bogus "today's move" for an untraded
// security).
//
// Module-level because the market board and the company page's key-stats rail
// must describe the SAME session for the same security. The company header used
// to derive its move as a bare `last_price - close_price`, which is the exact
// two-days-in-one-day defect `previousClose` exists to prevent — so a security
// the board showed flat could lead the company page at +20 %.
function applyTradeStats(r, tmap, latestTsDay) {
  const t = (tmap || {})[r.isin] || (tmap || {})[(r.isin || "").toUpperCase()];
  if (!t) return r;
  const rowDay = normalizeMarketDay(r.last_trade_date);
  const tsDay = normalizeMarketDay(t.trade_date);
  // The day stats and the feed row must describe the SAME session — a stored
  // day older than the row's own last trade is a snapshot the nightly push
  // never refreshed, and its turnover belongs to no quote on the page. Fall
  // back to the feed's own figures for the row's day; an em-dash where the
  // feed has none is honest, a number from another week is not.
  if (!tradeStatsApply(r.last_trade_date, t.trade_date)) return r;
  const out = { ...r, ts: t };
  if (Number.isFinite(t.total_value)) out.stockVolume = t.total_value;
  if (Number.isFinite(t.total_qty)) out.stockQuantity = t.total_qty;
  if (Number.isFinite(t.trade_count)) out.stockTradeCount = t.trade_count;
  if (Number.isFinite(t.avg_price)) out.avgPrice = t.avg_price;
  if (Number.isFinite(t.vwap)) out.vwap = t.vwap;
  // The feed lags for thin names — SANE still carried its 13.07 trade
  // while today's executions existed (and sometimes last_price is null
  // outright) — so the official move vanished from the board. When the
  // day stats are the latest session AND newer than the feed row, the
  // session's own OHLC is authoritative: price/date/OHLC come from it and
  // the change is close-to-close (session close vs the feed's stale
  // close, which IS the previous close — matching the daily bulletin).
  const tsIsNewer = tsDay && tsDay === latestTsDay &&
    (r.lastPrice === null || !rowDay || rowDay < tsDay);
  if (tsIsNewer) {
    const px = Number.isFinite(t.close_price) ? t.close_price
      : Number.isFinite(t.vwap) ? t.vwap : t.avg_price;
    if (Number.isFinite(px)) {
      out.lastPrice = px;
      if (Number.isFinite(t.open_price)) out.openPrice = t.open_price;
      if (Number.isFinite(t.high_price)) out.highPrice = t.high_price;
      if (Number.isFinite(t.low_price)) out.lowPrice = t.low_price;
      if (/^\d{8}$/.test(String(t.trade_date))) {
        const d = String(t.trade_date);
        out.last_trade_date = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}`;
      }
      // Against the newest close the exchange published BEFORE this session —
      // not against whatever `close_price` the row is carrying. Once the quote
      // pass falls two sessions behind, that field is the PREVIOUS session's
      // previous close, and the difference is two days' move wearing one day's
      // date: UQEQ's single unchanged 37 200 trade led the top-gainers panel at
      // +20 % because it was struck against 05.08's 31 000. See previousClose.
      const prev = previousClose({
        lastPrice: r.lastPrice, lastTradeDate: r.last_trade_date,
        closePrice: r.closePrice, closeDate: r.close_date,
      }, t.trade_date);
      if (prev) {
        // The row now states this session, so it must state this session's
        // previous close too — the "закр." line under the trade date reads it.
        out.closePrice = prev.price;
        out.close_price = prev.price;
        out.close_date = prev.date ?? null;
        out.changeValue = px - prev.price;
        out.changePercent = ((px - prev.price) / Math.abs(prev.price)) * 100;
      } else {
        // Nothing datable to measure from. An em-dash is the honest cell.
        out.changeValue = null;
        out.changePercent = null;
      }
      out.tone = marketTone(out.changePercent);
    } else if (rowDay && rowDay < tsDay) {
      // The stats put this row in a session the quote layer has not reached,
      // and carry no price to restate it with. Whatever change the quote holds
      // belongs to the older session — leaving it in place is how a stale move
      // gets published under today's date, which is the whole defect above.
      out.changeValue = null;
      out.changePercent = null;
      out.tone = marketTone(null);
    }
  }
  return out;
}

// Average execution price per share = turnover (sums) / shares traded.
function avgSharePrice(row) {
  const vol = row?.stockVolume, qty = row?.stockQuantity;
  return Number.isFinite(vol) && Number.isFinite(qty) && qty > 0 ? vol / qty : null;
}

// Average value per trade = turnover (sums) / number of trades.
function avgTradeValue(row) {
  const vol = row?.stockVolume, n = row?.stockTradeCount;
  return Number.isFinite(vol) && Number.isFinite(n) && n > 0 ? vol / n : null;
}

// Price to show in the quote column. UZSE sometimes reports last_price=null even
// for a security that traded today (e.g. UZAS: null price but real turnover), and
// Number(null)===0 would render a misleading "0,00". So: use the last trade price
// when present; otherwise, only if the security actually traded, fall back to the
// average trade price (turnover/shares) or the close; else null → em-dash.
function marketDisplayPrice(row) {
  if (row?.last_price != null && Number.isFinite(row.lastPrice)) return row.lastPrice;
  // A security can trade with its data only in the trade-stats feed (avgPrice),
  // while the /stocks feed reports null volume (e.g. MIQE). Treat a real trade
  // average as proof it traded so we show the price instead of an em-dash.
  const traded = row?.stockTradeCount > 0 || row?.stockVolume > 0 || row?.stockQuantity > 0
    || (Number.isFinite(row?.avgPrice) && row.avgPrice > 0);
  if (traded) {
    const avg = Number.isFinite(row?.avgPrice) && row.avgPrice > 0 ? row.avgPrice : avgSharePrice(row);
    if (Number.isFinite(avg) && avg > 0) return avg;
  }
  // Last known price: fall back to the close price (the UI already marks these
  // rows "закр." / "нет сделки") even when the security did not trade today, so
  // illiquid names show a real price instead of an em-dash.
  return Number.isFinite(row?.closePrice) && row.closePrice > 0 ? row.closePrice : null;
}

// Financial indicator cell: compact sums (e.g. "1,2 млрд"), em-dash when absent.
function finValue(v, lang) {
  return Number.isFinite(v) ? formatCompactNumber(v, lang) : "—";
}

// One comparison for one sort key. Returns 0 on a tie so the next key in the
// chain can decide — which is the whole reason multi-key sorting works at all.
function compareSortValues(av, bv, dir) {
  const sign = dir === "asc" ? 1 : -1;
  if (typeof av === "string" || typeof bv === "string") {
    return sign * String(av).localeCompare(String(bv));
  }
  // Empty values (no trade / missing) always sink to the bottom, regardless of direction.
  const aEmpty = av === null || av === undefined || Number.isNaN(av);
  const bEmpty = bv === null || bv === undefined || Number.isNaN(bv);
  if (aEmpty && bEmpty) return 0;
  if (aEmpty) return 1;
  if (bEmpty) return -1;
  return sign * (av - bv);
}

function buildMarketStats(rows) {
  // Movers, counters and the day's turnover follow the exchange's daily
  // bulletin: only securities that traded on the LATEST session count.
  // Backfilled last-day stats (an untraded security showing its own last
  // trading day) must not surface as "today's" gainers/losers/volume.
  const boardDay = rows.reduce((m, r) => { const d = marketRowDay(r); return d && (!m || d > m) ? d : m; }, null);
  const todays = boardDay ? rows.filter((r) => marketRowDay(r) === boardDay) : rows;
  // Everything on the latest session's date traded (the feed's null-price
  // quirk must not undercount securities whose executions we hold).
  const traded = todays.length;
  const advancers = todays.filter((row) => row.changePercent !== null && row.changePercent > 0.05).length;
  const decliners = todays.filter((row) => row.changePercent !== null && row.changePercent < -0.05).length;
  const unchanged = todays.filter((row) => Number.isFinite(row.changePercent) && row.changePercent >= -0.05 && row.changePercent <= 0.05).length;
  const withChange = todays.filter((row) => Number.isFinite(row.changePercent));
  const topGrowth = withChange.reduce((best, row) => (!best || row.changePercent > best.changePercent ? row : best), null);
  const topDrop = withChange.reduce((worst, row) => (!worst || row.changePercent < worst.changePercent ? row : worst), null);
  const topGainers = withChange.filter((r) => r.changePercent > 0).sort((a, b) => b.changePercent - a.changePercent).slice(0, 5);
  const topLosers = withChange.filter((r) => r.changePercent < 0).sort((a, b) => a.changePercent - b.changePercent).slice(0, 5);
  const totalVolume = todays.reduce((s, r) => s + (Number.isFinite(r.stockVolume) ? r.stockVolume : 0), 0);
  const totalTrades = todays.reduce((s, r) => s + (Number.isFinite(r.stockTradeCount) ? r.stockTradeCount : 0), 0);
  const totalMarketCap = rows.reduce((s, r) => s + (Number.isFinite(r.marketCap) && r.marketCap > 0 ? r.marketCap : 0), 0);
  return { boardDay, traded, advancers, decliners, unchanged, topGrowth, topDrop, topGainers, topLosers, totalVolume, totalTrades, totalMarketCap };
}

const SCORE_EXPLANATION_TEXTS = {
  ru: {
    ranges: {
      A: "сильный диапазон 80-100",
      B: "хороший диапазон 60-79",
      C: "средний диапазон 40-59",
      D: "слабый диапазон ниже 40",
    },
    inputs: "Влияют",
    trend: "тренд",
    momentum: "импульс",
    dcf: "DCF",
    industry: "отрасль",
    liquidity: "ликвидность",
    noFactors: "Недостаточно сильных сигналов, чтобы поднять компанию выше текущего класса",
    advice: {
      A: "Финансовое состояние выглядит сильным.",
      B: "До A нужны еще более устойчивые рост и прибыльность.",
      C: "До B нужны сильнее рост, прибыльность и устойчивость баланса.",
      D: "Нужны заметное улучшение прибыли, ликвидности и долговой нагрузки.",
    },
    signals: { bullish: "положительный", neutral: "нейтральный", bearish: "негативный" },
  },
  en: {
    ranges: {
      A: "strong 80-100 range",
      B: "good 60-79 range",
      C: "middle 40-59 range",
      D: "weak range below 40",
    },
    inputs: "Drivers",
    trend: "trend",
    momentum: "momentum",
    dcf: "DCF",
    industry: "industry",
    liquidity: "liquidity",
    noFactors: "There are not enough strong signals to lift the company above this class",
    advice: {
      A: "Financial condition looks strong.",
      B: "A needs more consistent growth and profitability.",
      C: "B needs stronger growth, profitability, and balance-sheet stability.",
      D: "Profit, liquidity, and debt load need clear improvement.",
    },
    signals: { bullish: "positive", neutral: "neutral", bearish: "negative" },
  },
  uz: {
    ranges: {
      A: "kuchli 80-100 oralig'i",
      B: "yaxshi 60-79 oralig'i",
      C: "o'rtacha 40-59 oralig'i",
      D: "40 dan past zaif oralig'i",
    },
    inputs: "Ta'sir qilganlar",
    trend: "trend",
    momentum: "impuls",
    dcf: "DCF",
    industry: "sektor",
    liquidity: "likvidlik",
    noFactors: "Kompaniyani hozirgi sinfdan yuqoriga olib chiqadigan kuchli signallar yetarli emas",
    advice: {
      A: "Moliyaviy holat kuchli ko'rinadi.",
      B: "A uchun o'sish va rentabellik yanada barqaror bo'lishi kerak.",
      C: "B uchun o'sish, rentabellik va balans barqarorligi kuchliroq bo'lishi kerak.",
      D: "Foyda, likvidlik va qarz yuki aniq yaxshilanishi kerak.",
    },
    signals: { bullish: "ijobiy", neutral: "neytral", bearish: "salbiy" },
  },
};

function scoreGradeCode(score) {
  const value = safeNumber(score);
  if (value === null) return null;
  if (value >= 80) return "A";
  if (value >= 60) return "B";
  if (value >= 40) return "C";
  return "D";
}

function buildScoreExplanation(total = {}, metrics = {}, language = "ru") {
  const lang = normalizeLanguage(language);
  const text = SCORE_EXPLANATION_TEXTS[lang] || SCORE_EXPLANATION_TEXTS.ru;
  const score = safeNumber(total?.score);
  const code = scoreGradeCode(score) || String(total?.grade || "").trim().slice(0, 1).toUpperCase();
  if (!["A", "B", "C", "D"].includes(code)) return "";
  const gradeCode = code;
  const factors = [];

  const trends = metrics?.trends || {};
  const trendScore = safeNumber(trends.overall_score);
  if (trendScore !== null) factors.push(`${text.trend} ${formatRatio(trendScore, 0, lang)}/12`);

  const momentum = metrics?.momentum || {};
  const momentumScore = safeNumber(momentum.overall_score);
  if (momentumScore !== null) {
    factors.push(`${text.momentum} ${formatRatio(momentumScore, 0, lang)}`);
  } else if (momentum.css) {
    factors.push(`${text.momentum} ${text.signals[momentum.css] || momentum.css}`);
  }

  const dcfSignal = metrics?.dcf?.signal;
  if (dcfSignal) factors.push(`${text.dcf} ${text.signals[dcfSignal] || dcfSignal}`);

  const industry = metrics?.industry || {};
  if (industry.good_count !== undefined || industry.weak_count !== undefined) {
    factors.push(`${text.industry} +${industry.good_count ?? 0}/-${industry.weak_count ?? 0}`);
  }

  const liquidityDays = metrics?.market_liquidity?.trade_days;
  if (liquidityDays !== undefined && liquidityDays !== null) {
    factors.push(`${text.liquidity} ${liquidityDays}/30`);
  }

  const range = text.ranges[gradeCode] || text.ranges.C;
  const factorText = factors.length ? `${text.inputs}: ${factors.slice(0, 3).join("; ")}.` : `${text.noFactors}.`;
  return `${gradeCode}: ${range}. ${factorText} ${text.advice[gradeCode] || text.advice.C}`;
}

function getSectionTitle(language, key) {
  return t(language, `sections.${key}`) || key.replaceAll("_", " ");
}

// 14 разделов из _analysis_prompt_v2 в analysis_service.py (public-information-v4-bank-aware-2026-05-27).
// Эти разделы выводятся сверху в строго заданном порядке, остальные — под катом «Дополнительно».
const PRIMARY_SECTIONS = [
  "СКОРИНГ",
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ТЕХНИЧЕСКИЙ_АНАЛИЗ",
  "ОЦЕНКА_ЦЕНЫ",
  "КАТАЛИЗАТОРЫ",
  "СИЛЬНЫЕ_СТОРОНЫ",
  "СЛАБЫЕ_СТОРОНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА",
  "ИТОГ",
];

function splitSections(sections) {
  const sourceEntries = sections ? Object.entries(sections) : [];
  const lookup = new Map(sourceEntries);
  const primary = [];
  const seen = new Set();
  for (const key of PRIMARY_SECTIONS) {
    if (lookup.has(key)) {
      primary.push([key, lookup.get(key)]);
      seen.add(key);
    }
  }
  const supplementary = sourceEntries.filter(([key]) => !seen.has(key));
  return { primary, supplementary };
}

function getProfileInitials(user) {
  const source = (user?.full_name || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const second = parts.length > 1 ? parts[1][0] : parts[0][1] || "";
  return (first + second).toUpperCase();
}

function hashToHue(source) {
  return String(source || "").split("").reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 360, 47);
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read image"));
    reader.readAsDataURL(file);
  });
}

function buildSeriesChart(series, language) {
  const points = Array.isArray(series) ? series : [];
  const filtered = points
    .map((row) => ({
      year: row?.year,
      revenue: safeNumber(row?.revenue),
      profit: safeNumber(row?.net_income),
      debt: safeNumber(row?.total_liabilities ?? row?.total_debt ?? row?.debt),
    }))
    .filter((row) => row.year !== undefined && row.year !== null && (row.revenue !== null || row.profit !== null || row.debt !== null));

  if (filtered.length < 2) return null;

  const width = 1000;
  const height = 340;
  const padding = { left: 74, right: 24, top: 28, bottom: 44 };
  const allValues = filtered.flatMap((row) => [row.revenue, row.profit, row.debt]).filter((value) => Number.isFinite(value));
  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (min > 0) min = 0;
  if (max < 0) max = 0;
  const range = max - min === 0 ? 1 : max - min;
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const x = (index) => padding.left + (filtered.length <= 1 ? innerWidth / 2 : (index / (filtered.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const line = (arr) =>
    arr
      .map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(Number.isFinite(point) ? point : min).toFixed(2)}`)
      .join(" ");

  const revenuePoints = filtered.map((row) => row.revenue ?? min);
  const profitPoints = filtered.map((row) => row.profit ?? min);
  const debtPoints = filtered.map((row) => row.debt ?? min);
  const revenuePath = line(revenuePoints);
  const profitPath = line(profitPoints);
  const debtPath = line(debtPoints);
  const zeroY = y(0);
  const areaPath = `${revenuePath} L ${x(filtered.length - 1).toFixed(2)} ${zeroY.toFixed(2)} L ${x(0).toFixed(2)} ${zeroY.toFixed(2)} Z`;

  const yTicks = Array.from({ length: 5 }, (_, idx) => {
    const ratio = idx / 4;
    const value = max - ratio * range;
    const yy = padding.top + ratio * innerHeight;
    return { value, y: yy };
  });

  const latest = filtered.at(-1);
  const previous = filtered.at(-2) || {};
  const revenueChange =
    Number.isFinite(latest.revenue) && Number.isFinite(previous.revenue)
      ? ((latest.revenue - previous.revenue) / Math.abs(previous.revenue || 1)) * 100
      : null;
  const profitChange =
    Number.isFinite(latest.profit) && Number.isFinite(previous.profit)
      ? ((latest.profit - previous.profit) / Math.abs(previous.profit || 1)) * 100
      : null;
  const debtChange =
    Number.isFinite(latest.debt) && Number.isFinite(previous.debt)
      ? ((latest.debt - previous.debt) / Math.abs(previous.debt || 1)) * 100
      : null;

  return {
    width,
    height,
    filtered,
    areaPath,
    revenuePath,
    profitPath,
    debtPath,
    yTicks,
    latest,
    revenueChange,
    profitChange,
    debtChange,
    x,
    y,
  };
}

function buildActivitySeries(entries, language) {
  const items = Array.isArray(entries) ? entries : [];
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  const dayMap = new Map();
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const keyFor = (date) =>
    [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - offset);
    const key = keyFor(date);
    dayMap.set(key, {
      key,
      label: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(date),
      shortLabel: new Intl.DateTimeFormat(locale, { weekday: "short" }).format(date),
      count: 0,
      cached: 0,
      scoreTotal: 0,
      scoreCount: 0,
      avgScore: null,
    });
  }

  for (const item of items) {
    const createdAt = item?.created_at;
    if (!createdAt) continue;
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) continue;
    date.setHours(0, 0, 0, 0);
    const key = keyFor(date);
    const bucket = dayMap.get(key);
    if (!bucket) continue;
    bucket.count += 1;
    if (item?.from_cache) bucket.cached += 1;
    const score = safeNumber(item?.score ?? item?.summary?.score ?? item?.result?.summary?.score);
    if (score !== null) {
      bucket.scoreTotal += score;
      bucket.scoreCount += 1;
    }
  }

  const days = Array.from(dayMap.values()).map((day) => ({
    ...day,
    avgScore: day.scoreCount ? day.scoreTotal / day.scoreCount : null,
  }));
  const maxCount = Math.max(1, ...days.map((day) => day.count || 0));
  const maxCached = Math.max(1, ...days.map((day) => day.cached || 0));
  const total = days.reduce((sum, day) => sum + (day.count || 0), 0);
  const cachedTotal = days.reduce((sum, day) => sum + (day.cached || 0), 0);
  const scoreDays = days.filter((day) => day.avgScore !== null);
  const avgScore = scoreDays.length ? scoreDays.reduce((sum, day) => sum + day.avgScore, 0) / scoreDays.length : null;
  const peak = days.reduce((best, day) => (day.count > (best?.count || 0) ? day : best), days[0] || null);

  return { days, maxCount, maxCached, total, cachedTotal, avgScore, peak };
}

function buildSparkline(values, width = 220, height = 74) {
  const points = (Array.isArray(values) ? values : []).map((value) => safeNumber(value)).filter((value) => value !== null);
  if (!points.length) return null;

  let min = Math.min(...points);
  let max = Math.max(...points);
  if (min === max) {
    min -= 1;
    max += 1;
  }

  const padding = { left: 8, right: 8, top: 10, bottom: 12 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const range = max - min || 1;
  const x = (index) => padding.left + (points.length <= 1 ? innerWidth / 2 : (index / (points.length - 1)) * innerWidth);
  const y = (value) => padding.top + ((max - value) / range) * innerHeight;
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"} ${x(index).toFixed(2)} ${y(point).toFixed(2)}`).join(" ");
  const areaPath = `${path} L ${x(points.length - 1).toFixed(2)} ${height - padding.bottom} L ${x(0).toFixed(2)} ${height - padding.bottom} Z`;

  return { width, height, points, path, areaPath, latest: points.at(-1), min, max };
}

function scorePercent(score) {
  if (score === null || score === undefined || score === "") return null;
  const value = Number(score);
  if (!Number.isFinite(value)) return null;
  return clampPercent(value <= 10 ? value * 10 : value);
}

function scoreTone(score) {
  const value = scorePercent(score);
  if (value === null) return "neutral";
  if (value >= 70) return "good";
  if (value >= 45) return "warning";
  return "danger";
}

function clampPercent(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return null;
  return Math.max(0, Math.min(100, num));
}

function CompanyLogo({ logo, name, ticker }) {
  const [failed, setFailed] = React.useState(false);
  if (!logo || failed) {
    // No logo: render a designed monogram tile — the ticker initials over a
    // gradient whose hue is derived deterministically from the ticker, so each
    // issuer gets a distinct, stable, intentional-looking mark.
    const seed = ticker || name || "?";
    const mono = (seed.replace(/[^A-Za-z0-9]/g, "").slice(0, 2) || "?").toUpperCase();
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) % 360;
    return <span className="chip-logo-fallback" style={{ "--mono-h": h }}>{mono}</span>;
  }
  // Self-hosted icon-marks (/logos/*) are transparent and float directly on the
  // surface; remote and /logos/plate/* (wordmark/dark) logos keep a light plate.
  const isFloat = typeof logo === "string"
    && logo.startsWith("/logos/") && !logo.startsWith("/logos/plate/");
  return (
    <img
      className={`chip-logo${isFloat ? " chip-logo--float" : ""}`}
      src={logo}
      alt={name}
      onError={() => setFailed(true)}
      loading="lazy"
    />
  );
}

function ToastStack({ toasts, onDismiss, language }) {
  return (
    <div className="toast-stack" aria-live="polite" aria-atomic="true">
      {toasts.map((toast) => (
        <div key={toast.id} className={`toast toast-${toast.tone} show`}>
          <div className="toast-label">{toast.tone === "error" ? t(language, "toasts.error") : toast.tone === "success" ? t(language, "toasts.success") : t(language, "toasts.info")}</div>
          <div className="toast-message">{toast.message}</div>
          <button className="toast-close" type="button" onClick={() => onDismiss(toast.id)}>
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function StatCard({ label, value, sub }) {
  return (
    <article className="profile-stat-card">
      <div className="profile-stat-label">{label}</div>
      <div className="profile-stat-value">{value}</div>
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

function DisclosureCard({ label, title, intro, items, tone = "neutral" }) {
  return (
    <article className={`panel disclosure-card tone-${tone}`}>
      <div className="panel-head">
        <div>
          <div className="panel-label">{label}</div>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="panel-intro">{intro}</p>
      <ul className="disclosure-list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </article>
  );
}

function MiniSparkline({ values, tone = "neutral", language }) {
  const data = buildSparkline(values);

  if (!data) {
    return <div className="mini-sparkline-empty" aria-label={vt(language, "sparklineEmpty")} />;
  }

  return (
    <svg className={`mini-sparkline tone-${tone}`} viewBox={`0 0 ${data.width} ${data.height}`} role="img" aria-label={vt(language, "dashboardPeriod")}>
      <path d={data.areaPath} className="mini-sparkline-area" />
      <path d={data.path} className="mini-sparkline-line" />
      {data.points.map((point, index) => {
        if (index !== data.points.length - 1) return null;
        const x = data.points.length <= 1 ? data.width / 2 : 8 + (index / (data.points.length - 1)) * (data.width - 16);
        const y = 10 + ((data.max - point) / (data.max - data.min || 1)) * (data.height - 22);
        return <circle key={index} cx={x} cy={y} r="4" className="mini-sparkline-dot" />;
      })}
    </svg>
  );
}

function DashboardMetricCard({ label, value, sub, tone = "neutral", sparkline, language }) {
  return (
    <article className={`dashboard-metric-card tone-${tone}`}>
      <div className="dashboard-metric-top">
        <div>
          <div className="profile-stat-label">{label}</div>
          <div className="profile-stat-value">{value}</div>
        </div>
        <span className="metric-pulse" />
      </div>
      <MiniSparkline values={sparkline} tone={tone} language={language} />
      <div className="profile-stat-sub">{sub}</div>
    </article>
  );
}

function ScoreGauge({ score, language }) {
  const numeric = safeNumber(score);
  const value = scorePercent(numeric) ?? 0;
  const radius = 48;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (value / 100) * circumference;
  const tone = scoreTone(numeric);

  // Gradient colors based on tone
  const gradientColors = {
    good: ["#10b981", "#059669"],
    warning: ["#f59e0b", "#d97706"],
    danger: ["#ef4444", "#dc2626"],
    neutral: ["#ff9d00", "#e68a00"],
  };
  const [startColor, endColor] = gradientColors[tone] || gradientColors.neutral;

  return (
    <div className={`score-gauge tone-${tone}`}>
      <svg viewBox="0 0 128 128" role="img" aria-label={t(language, "analysis.score")}>
        <defs>
          <linearGradient id={`scoreGradient-${tone}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={startColor} />
            <stop offset="100%" stopColor={endColor} />
          </linearGradient>
          <filter id="gaugeGlow">
            <feGaussianBlur stdDeviation="2" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <circle className="score-gauge-track" cx="64" cy="64" r={radius} />
        <circle
          className="score-gauge-progress"
          cx="64"
          cy="64"
          r={radius}
          style={{
            strokeDasharray: circumference,
            strokeDashoffset: dashOffset,
            stroke: `url(#scoreGradient-${tone})`,
          }}
          filter="url(#gaugeGlow)"
        />
      </svg>
      <div className="score-gauge-center">
        <strong>{numeric === null ? "--" : Math.round(numeric)}</strong>
        <span>{t(language, "analysis.score")}</span>
      </div>
    </div>
  );
}

function MetricCard({ label, value, sub, tone = "neutral" }) {
  // Tone indicator icons
  const toneIcons = {
    good: "↑",
    warning: "→",
    danger: "↓",
    neutral: "•",
  };
  const icon = toneIcons[tone] || toneIcons.neutral;

  return (
    <article className={`metric-card metric-${tone} tone-${tone}`}>
      <div className="metric-header">
        <div className="metric-label">{label}</div>
        <span className={`metric-indicator tone-${tone}`}>{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
    </article>
  );
}

const SECTION_LABELS = {
  ru: "РАЗДЕЛ",
  en: "SECTION",
  uz: "BO'LIM",
};

const SUPPLEMENTARY_LABELS = {
  ru: "ПРИЛОЖЕНИЕ",
  en: "APPENDIX",
  uz: "ILOVA",
};

// Subheaders we want to bold: any uppercase phrase (4-60 chars) ending with ":"
// covers RU/EN/UZ ("ЛИКВИДНОСТЬ:", "LIQUIDITY:", "LIKVIDLIK:") in one rule.
const UPPER_SUBHEADER_RE = /^[A-ZА-ЯЁЎҚҒҲ][A-ZА-ЯЁЎҚҒҲ0-9\s,'’\-/()&]{2,58}:\s*$/u;

// KV pair: short label, then value that *starts with a number or sign* — keeps
// real metric lines ("ROE: 15.2%") and rejects normal prose ("Главное: банк…").
const KV_LABEL_MAX = 40;
const KV_VALUE_NUMERIC_RE = /^\s*[+\-−]?\s*[\d(]/;

const TLDR_HEADER_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*$/i;
const TLDR_INLINE_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]\s*(.+)$/i;
const TLDR_STARTS_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\b/i;
const TLDR_STRUCTURED_HINT_RE = /\b(?:Тон|Tone|Плюсы|Минусы|Pluses|Minuses|Strengths|Concerns|Score|Скор|Для\s+тебя|For\s+you|Bu\s+siz)\s*[-:：—]/i;
const TLDR_TONE_LABEL_RE = /^\s*Тон\s*[-:：—]\s*(.+)$/i;
const TLDR_SCORE_LABEL_RE = /^\s*Скор\s*[-:：—]\s*(.+)$/i;
const TLDR_PLUSES_LABEL_RE = /^\s*Плюсы\s*[-:：—]?\s*$/i;
const TLDR_MINUSES_LABEL_RE = /^\s*Минусы\s*[-:：—]?\s*$/i;
const TLDR_FORYOU_LABEL_RE = /^\s*Для\s+тебя\s*[-:：—]\s*(.+)$/i;
const TLDR_BULLET_RE = /^\s*[-•—]\s+(.+)$/;
const TLDR_TONE_KEYS = {
  позитивный: "positive",
  positive: "positive",
  ijobiy: "positive",
  умеренный: "neutral",
  умеренная: "neutral",
  neutral: "neutral",
  mixed: "neutral",
  смешанный: "neutral",
  o_rtacha: "neutral",
  "o'rtacha": "neutral",
  тревожный: "caution",
  тревожная: "caution",
  осторожно: "caution",
  caution: "caution",
  warning: "caution",
  ehtiyot: "caution",
  критичный: "critical",
  критическая: "critical",
  critical: "critical",
  негативный: "critical",
  негативная: "critical",
  tanqidiy: "critical",
  нет_данных: "unknown",
  unknown: "unknown",
  insufficient: "unknown",
  "ma'lumot_yo'q": "unknown",
};

function normalizeToneKey(raw) {
  if (!raw) return "unknown";
  const clean = String(raw)
    .toLowerCase()
    .replace(/[.,;!?].*$/, "")
    .replace(/\s+/g, "_")
    .trim();
  return TLDR_TONE_KEYS[clean] || TLDR_TONE_KEYS[clean.replace(/_.*$/, "")] || "neutral";
}

function splitInlineBullets(text) {
  if (!text) return [];
  const cleaned = text.replace(/^[-•—]\s*/, "");
  return cleaned
    .split(/\s+[-•—]\s+/)
    .map((s) => s.replace(/[\s.;,]+$/, "").trim())
    .filter(Boolean);
}

function parseInlineTldr(rawText) {
  if (!rawText) return null;
  const text = rawText.replace(/^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*/i, "").trim();
  if (!text) return null;

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: null,
  };

  const labelOrder = [
    { key: "tone", re: /Тон\s*[-:：—]\s*/i },
    { key: "score", re: /Скор\s*[-:：—]\s*/i },
    { key: "pluses", re: /Плюсы\s*[-:：—]\s*/i },
    { key: "minuses", re: /Минусы\s*[-:：—]\s*/i },
    { key: "forYou", re: /Для\s+тебя\s*[-:：—]\s*/i },
  ];

  const matches = [];
  for (const { key, re } of labelOrder) {
    const m = text.match(re);
    if (m && m.index !== undefined) {
      matches.push({ key, start: m.index, valueStart: m.index + m[0].length });
    }
  }
  if (!matches.length) {
    tldr.summary = text;
    return tldr;
  }
  matches.sort((a, b) => a.start - b.start);

  if (matches[0].start > 0) {
    const head = text.slice(0, matches[0].start).trim();
    if (head) tldr.summary = head;
  }

  for (let i = 0; i < matches.length; i++) {
    const current = matches[i];
    const end = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const value = text.slice(current.valueStart, end).trim();
    if (!value) continue;
    if (current.key === "tone") {
      tldr.toneRaw = value;
      tldr.tone = normalizeToneKey(value);
    } else if (current.key === "score") {
      tldr.score = value;
    } else if (current.key === "pluses") {
      tldr.pluses = splitInlineBullets(value);
    } else if (current.key === "minuses") {
      tldr.minuses = splitInlineBullets(value);
    } else if (current.key === "forYou") {
      // The "Для тебя" value is the LAST inline label, so when the model crams
      // an entire section onto one line it greedily swallows the trailing hero
      // paragraph ("Статус: ... Причина — ..."). Cut it off so "Для тебя" stays
      // a short phrase and the rest renders as normal section text.
      const heroCut = value.search(/(?:Статус|Вывод|Итог|Резюме|Заключение)\s*[:：]/i);
      if (heroCut > 0) {
        tldr.forYou = value.slice(0, heroCut).trim();
        tldr.trailing = value.slice(heroCut).trim();
      } else {
        tldr.forYou = value;
      }
    }
  }

  return tldr;
}

function parseTldrBlock(body) {
  if (!body) return { tldr: null, rest: body };
  const lines = body.split("\n");

  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed) continue;
    if (!TLDR_STARTS_RE.test(trimmed)) return { tldr: null, rest: body };
    start = i;
    break;
  }
  if (start === -1) return { tldr: null, rest: body };

  const firstLine = lines[start].trim();
  const firstLineHasStructuredHint = TLDR_STRUCTURED_HINT_RE.test(firstLine);

  // CASE A: LLM emitted TL;DR as a single dense line with inline labels
  // ("TL;DR Тон: ... Плюсы: - ... Минусы: - ... Для тебя: ...").
  // Consume the whole TL;DR header line and parse it inline.
  if (firstLineHasStructuredHint) {
    const tldr = parseInlineTldr(firstLine);
    if (tldr && (tldr.pluses.length || tldr.minuses.length || tldr.forYou || tldr.toneRaw || tldr.summary)) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (tldr.trailing) {
        rest = `${tldr.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete tldr.trailing;
      }
      return { tldr, rest };
    }
  }

  // CASE B: classic multiline structured block.
  let headerLines = 1;
  let inlineSummary = null;
  const inlineMatch = firstLine.match(TLDR_INLINE_RE);
  if (inlineMatch) {
    inlineSummary = inlineMatch[1].trim();
  }

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: inlineSummary,
  };

  let cursor = start + headerLines;
  let activeList = null;
  let consumed = cursor;

  while (cursor < lines.length) {
    const trimmed = lines[cursor].trim();
    if (!trimmed) {
      cursor += 1;
      consumed = cursor;
      continue;
    }

    let matched = false;

    const tone = trimmed.match(TLDR_TONE_LABEL_RE);
    if (tone) {
      tldr.toneRaw = tone[1].trim();
      tldr.tone = normalizeToneKey(tone[1]);
      activeList = null;
      matched = true;
    }

    const score = !matched && trimmed.match(TLDR_SCORE_LABEL_RE);
    if (score) {
      tldr.score = score[1].trim();
      activeList = null;
      matched = true;
    }

    if (!matched && TLDR_PLUSES_LABEL_RE.test(trimmed)) {
      activeList = "pluses";
      matched = true;
    }
    if (!matched && TLDR_MINUSES_LABEL_RE.test(trimmed)) {
      activeList = "minuses";
      matched = true;
    }

    const forYou = !matched && trimmed.match(TLDR_FORYOU_LABEL_RE);
    if (forYou) {
      tldr.forYou = forYou[1].trim();
      activeList = null;
      matched = true;
    }

    const bullet = !matched && trimmed.match(TLDR_BULLET_RE);
    if (bullet && activeList) {
      tldr[activeList].push(bullet[1].trim());
      matched = true;
    }

    if (!matched) break;

    cursor += 1;
    consumed = cursor;
  }

  if (!tldr.pluses.length && !tldr.minuses.length && !tldr.forYou && !tldr.toneRaw && !tldr.summary) {
    // Last-resort: parse the first paragraph as inline.
    const fallback = parseInlineTldr(firstLine);
    if (fallback) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (fallback.trailing) {
        rest = `${fallback.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete fallback.trailing;
      }
      return { tldr: fallback, rest };
    }
    return { tldr: null, rest: body };
  }

  const rest = lines.slice(0, start).concat(lines.slice(consumed)).join("\n").replace(/^\s+|\s+$/g, "");
  return { tldr, rest };
}

function tldrCardTitle(language, tone) {
  const dict = {
    ru: {
      positive: "Сильная сторона",
      neutral: "Смешанная картина",
      caution: "Требует внимания",
      critical: "Повышенный риск",
      unknown: "Недостаточно данных",
    },
    en: {
      positive: "Strong signal",
      neutral: "Mixed picture",
      caution: "Watch closely",
      critical: "Elevated risk",
      unknown: "Insufficient data",
    },
    uz: {
      positive: "Kuchli tomon",
      neutral: "Aralash holat",
      caution: "Diqqat talab qiladi",
      critical: "Yuqori xavf",
      unknown: "Ma'lumot yetarli emas",
    },
  };
  return dict[language]?.[tone] || dict.ru[tone] || dict.ru.neutral;
}

const TONE_ICONS = {
  positive: "✓",
  neutral: "~",
  caution: "⚠",
  critical: "✗",
  unknown: "?",
};

function TldrCard({ tldr, language = "ru", variant = "default" }) {
  if (!tldr) return null;
  const hasPluses = tldr.pluses?.length > 0;
  const hasMinuses = tldr.minuses?.length > 0;
  const labels = {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
    en: { pluses: "Strengths", minuses: "Concerns", forYou: "What this means for you" },
    uz: { pluses: "Kuchli tomonlar", minuses: "Zaif tomonlar", forYou: "Bu siz uchun nimani anglatadi" },
  }[language] || {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
  }.ru;

  return (
    <div className={`tldr-card tldr-card--${tldr.tone} tldr-card--${variant}`}>
      <div className="tldr-card__head">
        <span className="tldr-card__tone-icon" aria-hidden="true">{TONE_ICONS[tldr.tone] || "~"}</span>
        <span className="tldr-card__tone-label">{tldrCardTitle(language, tldr.tone)}</span>
        {/* Numeric score removed for ТЗ compliance (2026-07-09). */}
      </div>
      {tldr.summary && <p className="tldr-card__summary">{tldr.summary}</p>}
      <div className="tldr-card__body">
        {hasPluses && (
          <div className="tldr-card__col tldr-card__col--pos">
            <div className="tldr-card__col-label">{labels.pluses}</div>
            <ul>
              {tldr.pluses.map((item, idx) => <li key={`p-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
        {hasMinuses && (
          <div className="tldr-card__col tldr-card__col--neg">
            <div className="tldr-card__col-label">{labels.minuses}</div>
            <ul>
              {tldr.minuses.map((item, idx) => <li key={`m-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
      </div>
      {tldr.forYou && (
        <div className="tldr-card__foryou">
          <span className="tldr-card__foryou-label">{labels.forYou}:</span>
          <span className="tldr-card__foryou-text">{tldr.forYou}</span>
        </div>
      )}
    </div>
  );
}

function pickFirstParagraph(text) {
  if (!text) return null;
  const blocks = text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  if (!blocks.length) return null;
  return blocks[0]
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join(" ");
}

function HeroVerdictBlock({ analysisResult, language = "ru" }) {
  if (!analysisResult?.sections) return null;
  const scoringRaw = analysisResult.sections["СКОРИНГ"];
  const summaryRaw =
    analysisResult.sections["ИТОГ"] ||
    analysisResult.sections["ВЕРДИКТ"] ||
    null;
  if (!scoringRaw && !summaryRaw) return null;

  const { tldr: scoringTldr } = parseTldrBlock(scoringRaw || "");
  const { tldr: summaryTldr, rest: summaryRest } = parseTldrBlock(summaryRaw || "");
  const heroParagraph = pickFirstParagraph(summaryRest);

  const tone = scoringTldr?.tone || summaryTldr?.tone || "neutral";
  const score = scoringTldr?.score || null;
  const verdictTitle = tldrCardTitle(language, tone);
  const pluses = scoringTldr?.pluses?.length ? scoringTldr.pluses : summaryTldr?.pluses || [];
  const minuses = scoringTldr?.minuses?.length ? scoringTldr.minuses : summaryTldr?.minuses || [];
  const forYou = summaryTldr?.forYou || scoringTldr?.forYou || null;

  const headline = {
    ru: { lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами" },
    en: { lead: "What the report shows", pluses: "Key positives", minuses: "Key concerns", paragraph: "In plain language" },
    uz: { lead: "Hisobotda nima ko'rinmoqda", pluses: "Asosiy ijobiy tomonlar", minuses: "Asosiy salbiy tomonlar", paragraph: "Sodda til bilan" },
  }[language] || {
    lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами",
  };

  return (
    <article className={`hero-verdict hero-verdict--${tone}`}>
      <div className="hero-verdict__crown">
        <span className="hero-verdict__crown-label">{headline.lead}</span>
        {/* Composite attractiveness score removed for ТЗ compliance (2026-07-09). */}
      </div>
      <div className="hero-verdict__headline">
        <span className="hero-verdict__icon" aria-hidden="true">{TONE_ICONS[tone] || "~"}</span>
        <h2 className="hero-verdict__title">{verdictTitle}</h2>
      </div>
      {(pluses.length > 0 || minuses.length > 0) && (
        <div className="hero-verdict__grid">
          {pluses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--pos">
              <div className="hero-verdict__col-label">{headline.pluses}</div>
              <ul>
                {pluses.slice(0, 3).map((item, idx) => <li key={`hp-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
          {minuses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--neg">
              <div className="hero-verdict__col-label">{headline.minuses}</div>
              <ul>
                {minuses.slice(0, 3).map((item, idx) => <li key={`hm-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      {heroParagraph && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{heroParagraph}</p>
        </div>
      )}
      {!heroParagraph && forYou && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{forYou}</p>
        </div>
      )}
    </article>
  );
}

function renderAnalysisContent(text, { keyPrefix = "analysis" } = {}) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let tableBuffer = [];
  let inTable = false;
  let proseBuffer = [];

  const tableCaptionRe = /^(?:таблица|table|jadval)\b/i;

  const flushProse = () => {
    if (!proseBuffer.length) return;
    elements.push(
      <section key={`${keyPrefix}-detail-${elements.length}`} className="analysis-sector analysis-sector--detail">
        {proseBuffer.map(({ key, text: paragraph }) => (
          <p key={key} className="analysis-para">{paragraph}</p>
        ))}
      </section>
    );
    proseBuffer = [];
  };

  const popTableCaption = () => {
    if (!proseBuffer.length) return null;
    const last = proseBuffer[proseBuffer.length - 1].text.trim();
    if (!tableCaptionRe.test(last)) return null;
    proseBuffer = proseBuffer.slice(0, -1);
    return last;
  };

  const flushTable = () => {
    if (tableBuffer.length > 0) {
      const caption = popTableCaption();
      flushProse();
      const headers = tableBuffer[0].split('|').filter(c => c.trim()).map(c => c.trim());
      const rows = tableBuffer.slice(2).filter(row => !row.match(/^\|[-\s|]+\|$/));
      elements.push(
        <section key={`${keyPrefix}-table-${elements.length}`} className="analysis-sector analysis-sector--table">
          {caption && <div className="analysis-sector__caption">{caption}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri} className={row.includes('ИТОГО') || row.includes('Итого') ? 'total-row' : ''}>
                    {row.split('|').filter(c => c.trim()).map((cell, ci) => {
                      const val = cell.trim();
                      const isNeg = val.startsWith('-') || val.startsWith('−');
                      const isPos = val.startsWith('+');
                      return <td key={ci} className={`${ci > 0 ? 'num' : ''} ${isNeg ? 'neg' : ''} ${isPos ? 'pos' : ''}`}>{val}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      );
      tableBuffer = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      inTable = true;
      tableBuffer.push(trimmed);
      continue;
    } else if (inTable) {
      flushTable();
      inTable = false;
    }

    if (!trimmed) {
      continue;
    } else if (trimmed.match(/^[0-9]+\.[0-9]+\.\s+/)) {
      flushProse();
      elements.push(<h3 key={`${keyPrefix}-subsec-${i}`} className="analysis-subsection">{trimmed}</h3>);
    } else if (UPPER_SUBHEADER_RE.test(trimmed)) {
      flushProse();
      elements.push(<h4 key={`${keyPrefix}-h4-${i}`} className="analysis-subheader">{trimmed}</h4>);
    } else if (trimmed.match(/^(Формула|Formula|Formula):/i) || trimmed.match(/^Формула:\s*.+=.+/i) || (trimmed.includes('=') && trimmed.match(/^\•?\s*[\w\s()]+\s*[=:]\s*.*[0-9]/))) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-formula-${i}`} className="formula-box">{trimmed}</div>);
    } else if (trimmed.startsWith('•') || trimmed.startsWith('—') || trimmed.startsWith('-')) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-bullet-${i}`} className="analysis-bullet">{trimmed}</div>);
    } else if (trimmed.match(/^[0-9]+\./)) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-num-${i}`} className="analysis-numbered">{trimmed}</div>);
    } else if (trimmed.match(/^(✓|✗|🟢|🟡|🟠|🔴)/)) {
      const isGood = trimmed.startsWith('✓') || trimmed.startsWith('🟢');
      const isBad = trimmed.startsWith('✗') || trimmed.startsWith('🔴');
      flushProse();
      elements.push(<div key={`${keyPrefix}-check-${i}`} className={`analysis-check ${isGood ? 'good' : ''} ${isBad ? 'bad' : ''}`}>{trimmed}</div>);
    } else if (
      trimmed.includes(':') &&
      trimmed.split(':')[0].length < KV_LABEL_MAX &&
      !trimmed.startsWith('http') &&
      KV_VALUE_NUMERIC_RE.test(trimmed.split(':').slice(1).join(':').trim())
    ) {
      flushProse();
      const [label, ...rest] = trimmed.split(':');
      const value = rest.join(':').trim();
      elements.push(
        <div key={`${keyPrefix}-kv-${i}`} className="analysis-kv">
          <span className="analysis-kv-label">{label}:</span>
          <span className="analysis-kv-value">{value}</span>
        </div>
      );
    } else {
      proseBuffer.push({ key: `${keyPrefix}-p-${i}`, text: trimmed });
    }
  }

  flushTable();
  flushProse();
  return elements;
}

function SectionCard({ title, body, index, open = false, language = "ru" }) {
  const sectionLabel = SECTION_LABELS[language] || SECTION_LABELS.ru;
  const { tldr, rest } = parseTldrBlock(body);
  const summaryHint = tldr?.summary || tldr?.forYou || null;

  return (
    <details className={`section-card fade-in${tldr ? ` section-card--tone-${tldr.tone}` : ""}`} open={open}>
      <summary>
        <span className="section-number">{sectionLabel} {String(index + 1).padStart(2, "0")}</span>
        <span className="section-title-text">{title}</span>
        {summaryHint && <span className="section-tldr-inline">{summaryHint}</span>}
      </summary>
      <div className="section-content">
        {tldr && <TldrCard tldr={tldr} language={language} />}
        {renderAnalysisContent(rest, { keyPrefix: `section-${index}` })}
      </div>
    </details>
  );
}

const ARTICLE_SECTION_ORDER = [
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ОЦЕНКА_ЦЕНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ИТОГ",
];

const ARTICLE_SECTION_TITLES = {
  ru: {
    ДОСЬЕ: "Общие сведения об эмитенте и методология анализа",
    ЧТО_С_ДЕНЬГАМИ: "Горизонтальный и вертикальный анализ отчётности",
    ТРЕНД: "Анализ динамики показателей",
    ЭФФЕКТИВНОСТЬ: "Коэффициентный анализ",
    ОЦЕНКА_ЦЕНЫ: "Оценка стоимости и качества цены",
    РЫНОЧНЫЕ_ДАННЫЕ: "Публичные рыночные данные",
    ВЕРДИКТ: "Итоговая оценка качества отчётности",
    ИТОГ: "Заключение для частного инвестора",
  },
  en: {
    ДОСЬЕ: "Issuer overview and analysis method",
    ЧТО_С_ДЕНЬГАМИ: "Horizontal and vertical financial analysis",
    ТРЕНД: "Performance trend analysis",
    ЭФФЕКТИВНОСТЬ: "Ratio analysis",
    ОЦЕНКА_ЦЕНЫ: "Valuation and price quality",
    РЫНОЧНЫЕ_ДАННЫЕ: "Public market data",
    ВЕРДИКТ: "Final reporting-quality assessment",
    ИТОГ: "Conclusion for a private investor",
  },
  uz: {
    ДОСЬЕ: "Emitent haqida umumiy ma'lumot va tahlil usuli",
    ЧТО_С_ДЕНЬГАМИ: "Hisobotning gorizontal va vertikal tahlili",
    ТРЕНД: "Ko'rsatkichlar dinamikasi tahlili",
    ЭФФЕКТИВНОСТЬ: "Koeffitsiyentlar tahlili",
    ОЦЕНКА_ЦЕНЫ: "Qiymat va narx sifati",
    РЫНОЧНЫЕ_ДАННЫЕ: "Ochiq bozor ma'lumotlari",
    ВЕРДИКТ: "Hisobot sifati bo'yicha yakuniy baho",
    ИТОГ: "Xususiy investor uchun xulosa",
  },
};

function countReportTables(reportTables) {
  if (!reportTables || typeof reportTables !== "object") return 0;
  return Object.values(reportTables).reduce((sum, tables) => sum + (Array.isArray(tables) ? tables.length : 0), 0);
}

function articleTableCellClass(cell, columnIndex) {
  const value = String(cell ?? "").trim();
  const classes = [];
  if (columnIndex > 0) classes.push("num");
  if (value.startsWith("-") || value.startsWith("\u2212")) classes.push("neg");
  if (value.startsWith("+")) classes.push("pos");
  return classes.join(" ");
}

function isArticleTotalRow(row) {
  const label = String(Array.isArray(row) ? row[0] ?? "" : "").toLowerCase();
  return label.includes("итого") || label.includes("total") || label.includes("jami");
}

function StructuredReportBlocks({ blocks = [], keyPrefix = "article" }) {
  return blocks.map((block, index) => {
    if (block?.type === "subheading" && block.text) {
      return (
        <section key={`${keyPrefix}-subheading-${index}`} className="analysis-sector analysis-sector--subheading">
          <h4 className="article-subheading">{block.text}</h4>
        </section>
      );
    }
    if (block?.type === "rating") {
      return (
        <section key={`${keyPrefix}-rating-${index}`} className={`analysis-sector analysis-sector--rating tone-${block.tone || "neutral"}`}>
          <div className={`article-rating tone-${block.tone || "neutral"}`}>
            {block.label && <span className="article-rating__label">{block.label}</span>}
            <strong className="article-rating__value">{block.value ?? "—"}</strong>
            {block.text && <p>{block.text}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "kpi_grid") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-kpi-${index}`} className="analysis-sector analysis-sector--kpi-grid">
          <div className="article-kpi-grid">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-kpi-card tone-${item.tone || "neutral"}`}>
                <span className="article-kpi-card__label">{item.label}</span>
                <strong className="article-kpi-card__value">{item.value ?? "—"}</strong>
                {item.hint && <p className="article-kpi-card__hint">{item.hint}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "formula") {
      return (
        <section key={`${keyPrefix}-formula-${index}`} className={`analysis-sector analysis-sector--formula tone-${block.tone || "neutral"}`}>
          <div className={`article-formula tone-${block.tone || "neutral"}`}>
            {block.title && <div className="article-formula__title">{block.title}</div>}
            <div className="article-formula__body">
              <code>{block.formula}</code>
              <strong>{block.result ?? "—"}</strong>
            </div>
            {block.description && <p>{block.description}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_summary") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-summary-${index}`} className="analysis-sector analysis-sector--verdict-summary">
          <div className="article-verdict-summary">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-summary-card tone-${item.tone || "neutral"}`}>
                <span className="article-verdict-summary-card__label">{item.label}</span>
                {item.value && <strong className="article-verdict-summary-card__value">{item.value}</strong>}
                {item.text && <p className="article-verdict-summary-card__text">{item.text}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_list") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-${index}`} className="analysis-sector analysis-sector--verdict-list">
          <div className="article-verdict-list">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-item tone-${item.tone || "neutral"}`}>
                <span>{item.label}</span>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "table") {
      const headers = Array.isArray(block.headers) ? block.headers : [];
      const rows = Array.isArray(block.rows) ? block.rows : [];
      if (!headers.length || !rows.length) return null;
      return (
        <section key={`${keyPrefix}-table-${block.id || index}`} className="analysis-sector analysis-sector--table">
          {block.caption && <div className="analysis-sector__caption">{block.caption}</div>}
          {block.note && <div className="analysis-sector__note">{block.note}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((header, headerIndex) => <th key={headerIndex}>{header}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => {
                  const cells = Array.isArray(row) ? row : [];
                  return (
                    <tr key={rowIndex} className={isArticleTotalRow(cells) ? "total-row" : ""}>
                      {cells.map((cell, cellIndex) => (
                        <td key={cellIndex} className={articleTableCellClass(cell, cellIndex)}>
                          {cell ?? "—"}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      );
    }
    if (block?.type === "paragraph" && block.text) {
      return (
        <section key={`${keyPrefix}-paragraph-${index}`} className="analysis-sector analysis-sector--detail">
          <p className="analysis-para">{block.text}</p>
        </section>
      );
    }
    return null;
  });
}

function ReportArticleView({ analysisResult, language = "ru" }) {
  const articleReport = analysisResult?.article_report?.sections?.length ? analysisResult.article_report : null;
  const sections = analysisResult?.sections || {};
  const ordered = ARTICLE_SECTION_ORDER
    .filter((key) => sections[key])
    .map((key) => [key, sections[key]]);
  const fallback = Object.entries(sections).filter(([key]) => !ARTICLE_SECTION_ORDER.includes(key));
  const entries = ordered.length ? ordered : fallback;
  if (!articleReport && !entries.length) return null;

  const dict = {
    ru: {
      desk: "UZ STOCK ANALYZER",
      title: "Анализ финансовой отчётности",
      subtitle: "Структурированный отчёт с таблицами и подробным разбором",
      annotation: "Аннотация",
      company: "Эмитент",
      ticker: "Тикер",
      annual: "Годовой период",
      quarterly: "Квартальный период",
      analysisPeriod: "Период анализа",
      comparison: "Сравнение",
      tables: "Таблиц",
      source: "Источник",
      fresh: "Свежий расчёт",
      cache: "Из кэша",
    },
    en: {
      desk: "UZ STOCK ANALYZER",
      title: "Financial Statement Analysis",
      subtitle: "Structured report with tables and detailed commentary",
      annotation: "Abstract",
      company: "Issuer",
      ticker: "Ticker",
      annual: "Annual period",
      quarterly: "Quarterly period",
      analysisPeriod: "Analysis period",
      comparison: "Comparison",
      tables: "Tables",
      source: "Source",
      fresh: "Fresh run",
      cache: "Cached",
    },
    uz: {
      desk: "UZ STOCK ANALYZER",
      title: "Moliyaviy hisobot tahlili",
      subtitle: "Jadvallar va batafsil izohlar bilan tuzilgan hisobot",
      annotation: "Annotatsiya",
      company: "Emitent",
      ticker: "Tiker",
      annual: "Yillik davr",
      quarterly: "Chorak davr",
      analysisPeriod: "Tahlil davri",
      comparison: "Taqqoslash",
      tables: "Jadval",
      source: "Manba",
      fresh: "Yangi hisob",
      cache: "Keshdan",
    },
  }[language] || {
    desk: "UZ STOCK ANALYZER",
    title: "Анализ финансовой отчётности",
    subtitle: "Структурированный отчёт с таблицами и подробным разбором",
    annotation: "Аннотация",
    company: "Эмитент",
    ticker: "Тикер",
    annual: "Годовой период",
    quarterly: "Квартальный период",
    analysisPeriod: "Период анализа",
    comparison: "Сравнение",
    tables: "Таблиц",
    source: "Источник",
    fresh: "Свежий расчёт",
    cache: "Из кэша",
  };

  const reportMeta = articleReport?.meta || {};
  const company = reportMeta.company || analysisResult.company_name || analysisResult.input || "—";
  const ticker = reportMeta.ticker || analysisResult.ticker || "—";
  const tableCount = reportMeta.table_count ?? countReportTables(analysisResult.report_tables);
  const selectedComparison = reportMeta.report_comparison?.label || analysisResult.report_comparison?.label || "";
  const summaryRaw = sections["ИТОГ"] || sections["ВЕРДИКТ"] || entries[0]?.[1] || "";
  const { rest: summaryRest } = parseTldrBlock(summaryRaw);
  const abstractText = articleReport?.abstract || pickFirstParagraph(summaryRest) || tldrCardTitle(language, "neutral");
  const sectionTitles = ARTICLE_SECTION_TITLES[language] || ARTICLE_SECTION_TITLES.ru;
  const articleSections = articleReport?.sections || [];

  return (
    <article className="report-article-panel">
      <div className="report-article">
        <header className="report-article__masthead">
          <div className="report-article__desk">{dict.desk}</div>
          <h2>{dict.title}</h2>
          <div className="report-article__subtitle">{dict.subtitle}</div>
          <div className="report-article__rule" aria-hidden="true"><span /><em>DATA REPORT</em><span /></div>
        </header>

        <div className="report-article__meta">
          {[
            [dict.company, company],
            [dict.ticker, ticker],
            [dict.annual, reportMeta.annual_period || analysisResult.annual_period || "—"],
            [dict.quarterly, reportMeta.quarterly_period || analysisResult.quarterly_period || "—"],
            [dict.analysisPeriod, reportMeta.analysis_period || reportMeta.analysis_comparison || "—"],
            ...(selectedComparison ? [[dict.comparison, selectedComparison]] : []),
            [dict.tables, tableCount || "—"],
            [dict.source, analysisResult.from_cache ? dict.cache : dict.fresh],
          ].map(([label, value]) => (
            <div className="report-article__meta-item" key={label}>
              <div className="report-article__meta-label">{label}</div>
              <div className="report-article__meta-value">{value}</div>
            </div>
          ))}
        </div>

        {abstractText && (
          <section className="report-article__abstract">
            <div className="report-article__abstract-label">{dict.annotation}</div>
            <p>{abstractText}</p>
          </section>
        )}

        <div className="report-article__body">
          {articleReport ? articleSections.map((section, index) => (
            <section className="report-article__section" key={section.id || index}>
              <span className="report-article__section-number">{section.number || String(index + 1).padStart(2, "0")}</span>
              <h3>{section.title || `${dict.tables} ${String(index + 1).padStart(2, "0")}`}</h3>
              <div className="report-article__section-content">
                <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`article-structured-${section.id || index}`} />
              </div>
            </section>
          )) : entries.map(([key, value], index) => {
            const { rest } = parseTldrBlock(value || "");
            if (!rest) return null;
            return (
              <section className="report-article__section" key={key}>
                <span className="report-article__section-number">{String(index + 1).padStart(2, "0")}</span>
                <h3>{sectionTitles[key] || getSectionTitle(language, key)}</h3>
                <div className="report-article__section-content">
                  {renderAnalysisContent(rest, { keyPrefix: `article-${index}-${key}` })}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </article>
  );
}

const COMPARE_COLORS = ["#6ef0c1", "#f5b84d", "#7dd3fc"];

const COMPARE_TABLE_TITLES = {
  ru: {
    overview: "Обзор",
    profitability: "Прибыльность",
    growth: "Рост",
    balance: "Баланс и риск",
    market: "Рынок",
    documents: "Отчеты",
    category_scores: "Сводные категории",
  },
  en: {
    overview: "Overview",
    profitability: "Profitability",
    growth: "Growth",
    balance: "Balance and risk",
    market: "Market",
    documents: "Reports",
    category_scores: "Category scores",
  },
  uz: {
    overview: "Umumiy",
    profitability: "Rentabellik",
    growth: "O'sish",
    balance: "Balans va risk",
    market: "Bozor",
    documents: "Hisobotlar",
    category_scores: "Kategoriya ballari",
  },
};

const COMPARE_LEADER_LABELS = {
  ru: {
    overall_leader: "Общий лидер",
    profitability_leader: "Прибыльность",
    roe_leader: "ROE",
    balance_quality_leader: "Качество баланса",
    market_liquidity_leader: "Ликвидность",
    lowest_debt_ratio: "Минимальная долговая нагрузка",
  },
  en: {
    overall_leader: "Overall leader",
    profitability_leader: "Profitability",
    roe_leader: "ROE",
    balance_quality_leader: "Balance quality",
    market_liquidity_leader: "Liquidity",
    lowest_debt_ratio: "Lowest debt load",
  },
  uz: {
    overall_leader: "Umumiy lider",
    profitability_leader: "Rentabellik",
    roe_leader: "ROE",
    balance_quality_leader: "Balans sifati",
    market_liquidity_leader: "Likvidlik",
    lowest_debt_ratio: "Eng past qarz yuki",
  },
};

function compareTableTitle(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_TABLE_TITLES[lang]?.[key] ?? key.replaceAll("_", " ");
}

function compareLeaderLabel(language, key) {
  const lang = normalizeLanguage(language);
  return COMPARE_LEADER_LABELS[lang]?.[key] ?? key.replaceAll("_", " ");
}

function formatCompareValue(value, language, unit = "") {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  const num = Number(value);
  if (!Number.isFinite(num)) return String(value);
  const normalizedUnit = String(unit || "").trim();
  const formatted = Math.abs(num) >= 1000 ? formatCompactNumber(num, language, 2) : formatRatio(num, 2, language);
  if (normalizedUnit === "%") return `${formatted}%`;
  if (normalizedUnit === "x") return `${formatted}x`;
  if (normalizedUnit.startsWith("/")) return `${formatted}${normalizedUnit}`;
  if (!normalizedUnit) return formatted;
  return `${formatted} ${normalizedUnit}`;
}

function formatCompareCell(cell, column, language) {
  if (cell && typeof cell === "object" && !Array.isArray(cell)) {
    return {
      value: formatCompareValue(cell.raw, language, column?.unit),
      normalized: cell.normalized,
      rank: cell.rank,
    };
  }
  return {
    value: formatCompareValue(cell, language, column?.unit),
    normalized: null,
    rank: null,
  };
}

function getCompareSeriesData(series) {
  return Array.isArray(series?.data) ? series.data : Array.isArray(series?.values) ? series.values : [];
}

function getCompareAxisLabel(item) {
  if (!item || typeof item !== "object") return String(item || "");
  return item.ticker || item.company_name || item.label || "";
}

function CompareLeaderCards({ leaders, language }) {
  const entries = Object.entries(leaders || {}).filter(([, value]) => value);
  if (!entries.length) {
    return <div className="empty-state"><p className="empty-copy">{ct(language, "noData")}</p></div>;
  }

  return (
    <div className="compare-leader-grid">
      {entries.map(([key, value], index) => (
        <article key={key} className="compare-leader-card" style={{ "--series-color": COMPARE_COLORS[index % COMPARE_COLORS.length] }}>
          <span>{compareLeaderLabel(language, key)}</span>
          <strong>{value.ticker || value.company || "—"}</strong>
          <p>{formatCompareValue(value.value, language)}</p>
        </article>
      ))}
    </div>
  );
}

function CompareRanking({ title, rows, scoreKey, language }) {
  const items = Array.isArray(rows) ? rows : [];
  if (!items.length) return null;
  return (
    <article className="compare-ranking-card">
      <h3>{title}</h3>
      <div className="compare-ranking-list">
        {items.map((item) => (
          <div key={`${title}-${item.rank}-${item.ticker || item.company}`} className="compare-ranking-row">
            <span className="compare-rank">#{item.rank}</span>
            <span className="compare-company">{item.ticker || item.company || "—"}</span>
            <strong>{formatCompareValue(item[scoreKey], language, scoreKey.endsWith("score") ? "/100" : "")}</strong>
          </div>
        ))}
      </div>
    </article>
  );
}

function CompareRadarChart({ chart, language }) {
  const labels = Array.isArray(chart?.labels) ? chart.labels : [];
  const datasets = Array.isArray(chart?.datasets) ? chart.datasets : [];
  const size = 360;
  const center = size / 2;
  const radius = 116;
  const labelRadius = 150;

  if (labels.length < 3 || !datasets.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  const point = (index, value, customRadius = radius) => {
    const angle = -Math.PI / 2 + (index / labels.length) * Math.PI * 2;
    const bounded = Math.max(0, Math.min(100, Number(value) || 0)) / 100;
    const r = customRadius * bounded;
    return {
      x: center + Math.cos(angle) * r,
      y: center + Math.sin(angle) * r,
    };
  };

  const ringPath = (level) =>
    labels
      .map((_, index) => {
        const p = point(index, 100, radius * level);
        return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
      })
      .join(" ") + " Z";

  return (
    <div className="compare-radar-wrap">
      <svg className="compare-radar" viewBox={`0 0 ${size} ${size}`} role="img" aria-label={chart.title || ct(language, "charts")}>
        {[0.25, 0.5, 0.75, 1].map((level) => (
          <path key={level} className="compare-radar-ring" d={ringPath(level)} />
        ))}
        {labels.map((label, index) => {
          const edge = point(index, 100);
          const textPoint = point(index, 100, labelRadius);
          return (
            <g key={label.key || label.label || index}>
              <line className="compare-radar-axis" x1={center} y1={center} x2={edge.x} y2={edge.y} />
              <text className="compare-radar-label" x={textPoint.x} y={textPoint.y} textAnchor="middle">
                {label.label || label.key || index + 1}
              </text>
            </g>
          );
        })}
        {datasets.map((dataset, datasetIndex) => {
          const data = getCompareSeriesData(dataset);
          const path = labels
            .map((_, index) => {
              const p = point(index, data[index]);
              return `${index === 0 ? "M" : "L"} ${p.x.toFixed(2)} ${p.y.toFixed(2)}`;
            })
            .join(" ") + " Z";
          return (
            <g key={dataset.label || dataset.company_name || datasetIndex} style={{ "--series-color": COMPARE_COLORS[datasetIndex % COMPARE_COLORS.length] }}>
              <path className="compare-radar-area" d={path} />
              <path className="compare-radar-line" d={path} />
            </g>
          );
        })}
      </svg>
      <div className="compare-chart-legend">
        {datasets.map((dataset, index) => (
          <span key={dataset.label || dataset.company_name || index} className="legend-chip">
            <i className="legend-swatch" style={{ background: COMPARE_COLORS[index % COMPARE_COLORS.length] }} />
            {dataset.label || dataset.company_name || `#${index + 1}`}
          </span>
        ))}
      </div>
    </div>
  );
}

function CompareBarChart({ chart, language }) {
  const axis = Array.isArray(chart?.x) ? chart.x : [];
  const series = Array.isArray(chart?.series) ? chart.series : [];
  const values = series.flatMap((item) => getCompareSeriesData(item).map((value) => Math.abs(Number(value))).filter(Number.isFinite));
  const max = Math.max(1, ...values);

  if (!axis.length || !series.length) {
    return <div className="compare-chart-empty">{ct(language, "noData")}</div>;
  }

  return (
    <div className="compare-bars">
      {axis.map((item, rowIndex) => (
        <div key={`${getCompareAxisLabel(item)}-${rowIndex}`} className="compare-bar-company">
          <div className="compare-bar-company-name">{getCompareAxisLabel(item)}</div>
          <div className="compare-bar-series">
            {series.map((serie, serieIndex) => {
              const raw = getCompareSeriesData(serie)[rowIndex];
              const num = Number(raw);
              const isFiniteValue = Number.isFinite(num);
              const width = isFiniteValue ? Math.max(4, (Math.abs(num) / max) * 100) : 0;
              return (
                <div key={`${serie.key || serie.label}-${rowIndex}`} className="compare-bar-row">
                  <span>{serie.label || serie.key}</span>
                  <div className="compare-bar-track">
                    <i
                      className={isFiniteValue && num < 0 ? "is-negative" : ""}
                      style={{ width: `${width}%`, background: COMPARE_COLORS[serieIndex % COMPARE_COLORS.length] }}
                    />
                  </div>
                  <strong>{formatCompareValue(raw, language)}</strong>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function CompareChartCard({ chart, language }) {
  if (!chart) return null;
  const isRadar = chart.type === "radar";
  return (
    <article className={`chart-card compare-chart-card compare-chart-${chart.type || "bar"}`}>
      <div className="chart-head">
        <div>
          <div className="panel-label">{ct(language, "charts")}</div>
          <h3>{chart.title || ct(language, "charts")}</h3>
        </div>
        <span className="status-badge muted">{isRadar ? "0-100" : chart.type || "chart"}</span>
      </div>
      {isRadar ? <CompareRadarChart chart={chart} language={language} /> : <CompareBarChart chart={chart} language={language} />}
    </article>
  );
}

function compareCellSortValue(raw) {
  const v = raw && typeof raw === "object" ? (raw.normalized ?? raw.value ?? raw.raw) : raw;
  if (typeof v === "number") return { num: v, str: String(v) };
  const n = parseFloat(String(v ?? "").replace(/[^\d.\-]/g, ""));
  return { num: Number.isFinite(n) ? n : null, str: String(v ?? "") };
}

function CompareTable({ table, title, language }) {
  const columns = Array.isArray(table?.columns) ? table.columns : [];
  const rows = Array.isArray(table?.rows) ? table.rows : [];
  const [sort, setSort] = React.useState({ key: null, dir: 1 });
  const [transposed, setTransposed] = React.useState(false);

  const toggleSort = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: 1 }));
  const sortedRows = React.useMemo(() => {
    if (!sort.key) return rows;
    return [...rows].sort((a, b) => {
      const av = compareCellSortValue(a[sort.key]);
      const bv = compareCellSortValue(b[sort.key]);
      if (av.num !== null && bv.num !== null) return (av.num - bv.num) * sort.dir;
      if (av.num !== null) return -1;
      if (bv.num !== null) return 1;
      return av.str.localeCompare(bv.str) * sort.dir;
    });
  }, [rows, sort]);

  // "Среднее по сравнению" row — averages each numeric metric across the compared issuers (ТЗ §3.6).
  const avgRow = React.useMemo(() => {
    const out = {};
    let hasAny = false;
    columns.forEach((column) => {
      const nums = rows.map((r) => compareCellSortValue(r[column.key]).num).filter((n) => n !== null);
      if (nums.length >= 2) {
        out[column.key] = nums.reduce((a, b) => a + b, 0) / nums.length;
        hasAny = true;
      } else {
        out[column.key] = null;
      }
    });
    return hasAny ? out : null;
  }, [rows, columns]);

  // Rules of Hooks: the empty-table bail-out MUST come after every hook call.
  // When it sat above the two useMemo above, a table going empty -> non-empty
  // rendered a different number of hooks than the previous pass, which React
  // treats as a fatal error — it threw and blanked the whole compare view.
  if (!columns.length || !rows.length) return null;

  const avgLabel = language === "en" ? "Average" : language === "uz" ? "O'rtacha" : "Среднее";
  const labelCol = columns[0];
  const metricCols = columns.slice(1);
  const transposeLabel = language === "en" ? "Transpose" : language === "uz" ? "Transpoze" : "Транспонировать";
  const rowHeader = (row, i) => {
    const c = labelCol ? formatCompareCell(row[labelCol.key], labelCol, language).value : null;
    return c || row.company_name || row.ticker || `#${i + 1}`;
  };

  return (
    <article className="compare-table-card">
      <div className="section-title-row">
        <h3>{title}</h3>
        <div className="compare-table-tools">
          <button type="button" className="ghost-btn compare-transpose-btn" onClick={() => setTransposed((v) => !v)}>
            ⇄ {transposeLabel}
          </button>
          <span className="muted">{rows.length}</span>
        </div>
      </div>
      <div className="compare-table-scroll">
        {!transposed ? (
          <table className="compare-table">
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} className="compare-th-sortable" onClick={() => toggleSort(column.key)}>
                    {column.label || column.key}
                    {sort.key === column.key ? <span className="compare-sort-arrow">{sort.dir === 1 ? " ▲" : " ▼"}</span> : null}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedRows.map((row, rowIndex) => (
                <tr key={`${title}-${row.company_name || row.ticker || rowIndex}`}>
                  {columns.map((column) => {
                    const cell = formatCompareCell(row[column.key], column, language);
                    return (
                      <td key={column.key}>
                        <strong>{cell.value}</strong>
                        {cell.normalized !== null && cell.normalized !== undefined ? (
                          <span>{ct(language, "normalized")}: {formatCompareValue(cell.normalized, language, "/100")}</span>
                        ) : null}
                        {cell.rank ? <em>#{cell.rank}</em> : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
              {avgRow && (
                <tr className="compare-avg-row">
                  {columns.map((column, ci) => (
                    <td key={column.key}>
                      {ci === 0 ? (
                        <strong>{avgLabel}</strong>
                      ) : avgRow[column.key] !== null ? (
                        <strong>{formatCompareValue(avgRow[column.key], language, "")}</strong>
                      ) : (
                        <span>—</span>
                      )}
                    </td>
                  ))}
                </tr>
              )}
            </tbody>
          </table>
        ) : (
          <table className="compare-table">
            <thead>
              <tr>
                <th>{labelCol?.label || ""}</th>
                {sortedRows.map((row, i) => (
                  <th key={i}>{rowHeader(row, i)}</th>
                ))}
                {avgRow && <th className="compare-avg-col">{avgLabel}</th>}
              </tr>
            </thead>
            <tbody>
              {metricCols.map((column) => (
                <tr key={column.key}>
                  <td><strong>{column.label || column.key}</strong></td>
                  {sortedRows.map((row, i) => {
                    const cell = formatCompareCell(row[column.key], column, language);
                    return (
                      <td key={i}>
                        <strong>{cell.value}</strong>
                        {cell.rank ? <em>#{cell.rank}</em> : null}
                      </td>
                    );
                  })}
                  {avgRow && (
                    <td className="compare-avg-col">
                      {avgRow[column.key] !== null && avgRow[column.key] !== undefined
                        ? <strong>{formatCompareValue(avgRow[column.key], language, "")}</strong>
                        : <span>—</span>}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </article>
  );
}

function CompareSummaryText({ summary, language }) {
  const text = summary?.text || summary?.summary || "";
  if (!text) {
    return <p className="empty-copy">{summary?.error || ct(language, "noData")}</p>;
  }
  return (
    <div className="compare-ai-text">
      {String(text)
        .split(/\n+/)
        .filter(Boolean)
        .map((line, index) => (
          <p key={index}>{line}</p>
        ))}
    </div>
  );
}

function MarketStatCard({ label, value, sub, tone = "neutral", termId, lang }) {
  return (
    <article className={`market-stat-card tone-${tone}`}>
      <span>{label}{termId && <TermInfo termId={termId} lang={lang} label={label} />}</span>
      <strong>{value}</strong>
      {sub ? <em>{sub}</em> : null}
    </article>
  );
}

function MarketChangeBadge({ value, percent, language }) {
  const tone = marketTone(percent);
  const sign = Number(value) > 0 ? "+" : "";
  const percentSign = Number(percent) > 0 ? "+" : "";
  return (
    <span className={`market-change-badge tone-${tone}`}>
      {value === null || percent === null
        ? "—"
        : `${sign}${formatMarketNumber(value, language)} · ${percentSign}${formatRatio(percent, 2, language)}%`}
    </span>
  );
}

function heatmapTileStyle(changePercent) {
  if (changePercent === null || !Number.isFinite(changePercent)) return {};
  const abs = Math.abs(changePercent);
  // 0.1% → L 20%; 5%+ → L 42% (TradingView-style vivid HSL)
  const lightness = Math.min(20 + (abs / 5) * 22, 44).toFixed(0);
  if (changePercent > 0.1) return { background: `hsl(160 65% ${lightness}%)` };
  if (changePercent < -0.1) return { background: `hsl(0 70% ${lightness}%)` };
  return {};
}

function heatmapShortName(name) {
  if (!name) return "";
  // Extract content inside quotes: "Hamkorbank" ATB → Hamkorbank
  const m = name.match(/["""«»]([^"""«»]+)["""«»]/);
  const base = m ? m[1] : name.replace(/\s+(AJ|ATB|MK|OAJ|XK)\b.*/i, "").trim();
  return base.length > 13 ? base.slice(0, 12) + "…" : base;
}

// Squarified treemap (Bruls/Huizing/van Wijk): pack items so each tile's AREA
// is proportional to its value while keeping aspect ratios near-square.
// Returns each input item with an absolute rect {x, y, w, h}.
function heatmapWorst(row, length) {
  const sum = row.reduce((s, r) => s + r.area, 0);
  if (sum <= 0) return Infinity;
  let max = -Infinity, min = Infinity;
  for (const r of row) { if (r.area > max) max = r.area; if (r.area < min) min = r.area; }
  const sum2 = sum * sum, l2 = length * length;
  return Math.max((l2 * max) / sum2, sum2 / (l2 * min));
}

function squarifyTreemap(items, x, y, w, h) {
  const out = [];
  const total = items.reduce((s, d) => s + d.value, 0);
  if (total <= 0 || w <= 0 || h <= 0) return out;
  const scale = (w * h) / total;
  const data = items.map((d) => ({ ...d, area: d.value * scale }));
  let rect = { x, y, w, h };
  let i = 0;
  while (i < data.length) {
    const length = Math.min(rect.w, rect.h);
    let row = [data[i]];
    let j = i + 1;
    while (j < data.length) {
      const cand = row.concat(data[j]);
      if (heatmapWorst(cand, length) <= heatmapWorst(row, length)) { row = cand; j++; } else break;
    }
    const rowArea = row.reduce((s, r) => s + r.area, 0);
    if (rect.w <= rect.h) {
      const rowH = rowArea / rect.w;
      let cx = rect.x;
      for (const r of row) { const rw = r.area / rowH; out.push({ ...r, x: cx, y: rect.y, w: rw, h: rowH }); cx += rw; }
      rect = { x: rect.x, y: rect.y + rowH, w: rect.w, h: rect.h - rowH };
    } else {
      const rowW = rowArea / rect.h;
      let cy = rect.y;
      for (const r of row) { const rh = r.area / rowW; out.push({ ...r, x: rect.x, y: cy, w: rowW, h: rh }); cy += rh; }
      rect = { x: rect.x + rowW, y: rect.y, w: rect.w - rowW, h: rect.h };
    }
    i = j;
  }
  return out;
}

function MarketHeatmap({ rows, companies, securitiesMap, language, onAnalyze, type, mapData }) {
  // Per-tile classification from /api/heatmap (ТЗ §9). The server decides what a
  // tile IS — priced, traded-but-unpriced, dormant, or resting on a single trade
  // — because the same judgement has to hold for the aggregates it also returns.
  const tileMeta = React.useMemo(() => {
    const by = new Map();
    (mapData?.tiles || []).forEach((t) => by.set(String(t.ticker || "").toUpperCase(), t));
    return by;
  }, [mapData]);
  const metaOf = (r) => tileMeta.get(String(r?.ticker || "").toUpperCase()) || null;
  const tileStatus = (r) => {
    const meta = metaOf(r);
    if (meta) return meta.status;
    // Before the response lands, fall back to the same rule the server applies.
    if (!Number.isFinite(r?.changePercent)) return r?.inactive ? "inactive" : "not_traded";
    return "ok";
  };
  const lowConfidence = (r) => metaOf(r)?.confidence === "low";
  const lang = normalizeLanguage(language);
  const wrapRef = React.useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState(null); // { ticker, row, x, y } — rich hover tooltip

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    let ro;
    if (typeof ResizeObserver !== "undefined") { ro = new ResizeObserver(measure); ro.observe(el); }
    else window.addEventListener("resize", measure);
    return () => { if (ro) ro.disconnect(); else window.removeEventListener("resize", measure); };
  }, []);

  const companyMap = {};
  (companies || []).forEach((c) => { companyMap[c.ticker] = c; });
  // Sector membership comes from lib/sectors.js — the same call the Рынок filter
  // bar makes, so a ticker cannot be Фонды in the table and Прочее on the map.
  const sectorKeyOf = (t) => sectorOf(t, securitiesMap, companyMap);
  const isPreferredRow = (row) =>
    securitiesMap?.[row.ticker]?.is_preferred === true ||
    securitiesMap?.[row.ticker]?.share_type === "preferred" ||
    row.share_type === "preferred";

  // Every listed instrument stays on the map: instruments that traded today are
  // colored by their change, while inactive registry listings and tickers
  // without a price change render as small NEUTRAL (grey, "—") tiles instead of
  // disappearing entirely. Bonds are excluded on the stock-focused views
  // (Акции and its subtypes) but shown when the user picks the Bonds segment.
  const isBond = (row) => row.type === "bond" || securitiesMap?.[row.ticker]?.type === "bond";
  const allowBonds = type === "bond";
  const isNeutralRow = (row) => row.inactive === true || !Number.isFinite(row.changePercent);
  const tradedRows = rows.filter((row) => allowBonds || !isBond(row));

  // Tile weight = compressed (sqrt) volume, floored so thin movers stay visible.
  // The floor is global (over every row) so a tile's area means the same amount
  // of traded value in the ordinary block and the preferred block alike.
  // Neutral (non-traded) tiles get a third of the floor so the ~50 inactive
  // listings stay visible without swamping the map with grey.
  const rawWeight = (r) => Math.sqrt(Math.max(r.stockVolume || 0, 1));
  const activeRows = tradedRows.filter((r) => !isNeutralRow(r));
  const maxRaw = Math.max(1, ...(activeRows.length ? activeRows : tradedRows).map(rawWeight));
  const floor = maxRaw * 0.05;
  const weight = (r) => (isNeutralRow(r) ? floor / 3 : Math.max(rawWeight(r), floor));

  const formatPct = (pct) => {
    if (pct === null || !Number.isFinite(pct)) return "—";
    return `${pct > 0 ? "+" : ""}${formatRatio(pct, 2, lang)}%`;
  };
  // ТЗ §9: a group moves by TURNOVER, not by headcount. A simple mean gave a
  // security that traded one share the same say as one that traded 98.4 mn on
  // 860 trades, so the sector reported a move nobody could have made. Tiles
  // without a real price never vote — they are not "unchanged".
  const avgOf = (rs) => {
    const counted = rs.filter((r) => Number.isFinite(r.changePercent)
      && tileStatus(r) === "ok");
    if (!counted.length) return null;
    const weight = counted.reduce((s, r) => s + (Number.isFinite(r.stockVolume) ? r.stockVolume : 0), 0);
    if (weight > 0) {
      return counted.reduce((s, r) => s + r.changePercent * (r.stockVolume || 0), 0) / weight;
    }
    return counted.reduce((a, r) => a + r.changePercent, 0) / counted.length;
  };
  // How many tiles actually entered that number, out of how many are shown —
  // ТЗ §9 requires the count to travel with the aggregate.
  const countedOf = (rs) => ({
    counted: rs.filter((r) => Number.isFinite(r.changePercent) && tileStatus(r) === "ok").length,
    total: rs.length,
  });

  // Top level splits share class (ordinary vs preferred); each block is then the
  // usual sector→stock treemap. Blocks stack vertically; heights are ∝ traded
  // weight but clamped so the (usually thinner) preferred block stays readable.
  const GROUP_ORDER = ["ordinary", "preferred"];
  const rowsByGroup = { ordinary: [], preferred: [] };
  tradedRows.forEach((row) => { rowsByGroup[isPreferredRow(row) ? "preferred" : "ordinary"].push(row); });
  const groups = GROUP_ORDER
    .map((key) => ({ key, rows: rowsByGroup[key] }))
    .filter((g) => g.rows.length);

  const HEADER = 17;   // sector header strip
  const GHEADER = 22;  // share-class block header strip
  const buildSectors = (groupRows, bodyY, bodyH) => {
    const sectorGroups = {};
    groupRows.forEach((row) => { (sectorGroups[sectorKeyOf(row.ticker)] ||= []).push(row); });
    Object.values(sectorGroups).forEach((g) => g.sort((a, b) => weight(b) - weight(a)));
    const orderedSectors = orderSectors(Object.keys(sectorGroups));
    const sectorItems = orderedSectors.map((s) => ({
      sector: s,
      rows: sectorGroups[s],
      value: sectorGroups[s].reduce((sum, r) => sum + weight(r), 0),
    }));
    const sectorRects = squarifyTreemap(sectorItems, 0, bodyY, size.w, bodyH);
    return sectorRects.map((sr) => {
      const header = sr.h > 48 && sr.w > 64;
      const hdr = header ? HEADER : 0;
      const stocks = squarifyTreemap(
        sr.rows.map((r) => ({ row: r, value: weight(r) })),
        sr.x, sr.y + hdr, sr.w, Math.max(sr.h - hdr, 0)
      );
      return { sector: sr.sector, rect: sr, header, headerH: HEADER, stocks };
    });
  };

  let layout = [];
  if (size.w > 12 && size.h > 12 && groups.length) {
    const showBlockHeaders = groups.length > 1;
    const bodyTotal = size.h - (showBlockHeaders ? GHEADER * groups.length : 0);
    groups.forEach((g) => { g.weight = g.rows.reduce((s, r) => s + weight(r), 0); });
    const totalW = groups.reduce((s, g) => s + g.weight, 0) || 1;
    let fracs = groups.map((g) => g.weight / totalW);
    if (groups.length > 1) {
      fracs = fracs.map((f) => Math.min(0.72, Math.max(0.28, f)));
      const fsum = fracs.reduce((a, b) => a + b, 0);
      fracs = fracs.map((f) => f / fsum);
    }
    let y = 0;
    layout = groups.map((g, gi) => {
      const gh = showBlockHeaders ? GHEADER : 0;
      const headerRect = { x: 0, y, w: size.w, h: gh };
      const bodyY = y + gh;
      const bodyH = fracs[gi] * bodyTotal;
      const sectors = buildSectors(g.rows, bodyY, bodyH);
      y = bodyY + bodyH;
      return { key: g.key, showHeader: showBlockHeaders, headerRect, avg: avgOf(g.rows), sectors };
    });
  }

  const groupLabel = (key) => key === "preferred"
    ? (lang === "ru" ? "Привилегированные" : lang === "uz" ? "Imtiyozli aksiyalar" : "Preferred")
    : (lang === "ru" ? "Обыкновенные" : lang === "uz" ? "Oddiy aksiyalar" : "Ordinary");

  const GAP = 1.5;
  const LEGEND_STOPS = [
    { pct: -5.5, label: "≤ −5%" },
    { pct: -2,   label: "−2%" },
    { pct: 0,    label: "0" },
    { pct: 2,    label: "+2%" },
    { pct: 5.5,  label: "≥ +5%" },
  ];

  return (
    <div className="heatmap-wrap">
      <div className="heatmap-legend">
        {LEGEND_STOPS.map(({ pct, label }) => {
          const s = heatmapTileStyle(pct);
          return (
            <span key={label} className="heatmap-legend-item">
              <span className="heatmap-legend-swatch" style={s.background ? { background: s.background } : undefined} />
              <span>{label}</span>
            </span>
          );
        })}
      </div>

      <div className="heatmap-tree" ref={wrapRef}>
        {layout.map((group) => (
          <React.Fragment key={group.key}>
            {group.showHeader && (
              <div className={`heatmap-group-label is-${group.key}`}
                style={{ left: group.headerRect.x, top: group.headerRect.y, width: group.headerRect.w, height: group.headerRect.h }}>
                <span className="hgl-name">{groupLabel(group.key)}</span>
                {group.avg !== null && (
                  <span className={`htl-avg tone-${group.avg > 0.1 ? "good" : group.avg < -0.1 ? "danger" : "neutral"}`}>{formatPct(group.avg)}</span>
                )}
              </div>
            )}
            {group.sectors.map((sec) => {
              const label = sectorLabel(lang, sec.sector);
              // Turnover-weighted, over priced tiles only — the same rule as the
              // block header and the server's own aggregate (ТЗ §9).
              const sectorRows = sec.stocks.map((s) => s.row);
              const avg = avgOf(sectorRows);
              const tally = countedOf(sectorRows);
              return (
                <React.Fragment key={`${group.key}-${sec.sector}`}>
                  {sec.header && (
                    <div className="heatmap-tree-label" style={{ left: sec.rect.x, top: sec.rect.y, width: sec.rect.w, height: sec.headerH }}>
                      <span>{label}</span>
                      {avg !== null && (
                        <>
                          <span className={`htl-avg tone-${avg > 0.1 ? "good" : avg < -0.1 ? "danger" : "neutral"}`}>{formatPct(avg)}</span>
                          {/* "12 из 21" — how many tiles the number rests on. */}
                          {tally.counted < tally.total && (
                            <span className="htl-count" title={lang === "ru"
                              ? "учтены только бумаги с ценой, вес по обороту"
                              : lang === "uz" ? "faqat narxli qog'ozlar, aylanma bo'yicha vazn"
                              : "priced securities only, weighted by turnover"}>
                              {tally.counted} {lang === "ru" ? "из" : lang === "uz" ? "dan" : "of"} {tally.total}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  )}
                  {sec.stocks.map((st) => {
                    const row = st.row;
                    const status = tileStatus(row);
                    const tileStyle = heatmapTileStyle(row.changePercent);
                    const isNeutral = !tileStyle.background;
                    // ТЗ §9: a tile with no price gets its own look, not the
                    // neutral grey that reads as "unchanged"; a tile resting on
                    // fewer than five trades is framed so "+20 %" cannot be read
                    // without also reading "1 trade, 1 share".
                    const statusClass = status === "no_price" ? " is-no-price"
                      : status === "not_traded" ? " is-not-traded"
                      : status === "inactive" ? " is-inactive" : "";
                    const confClass = lowConfidence(row) ? " is-low-confidence" : "";
                    const w = st.w - GAP, h = st.h - GAP;
                    if (w < 1 || h < 1) return null;
                    const tickerSize = Math.max(8, Math.min(Math.min(w, h) / 2.9, w / 4.4, 19));
                    const showTicker = w > 22 && h > 15;
                    const showPct = w > 34 && h > 32;
                    return (
                      <button
                        key={row.ticker}
                        type="button"
                        className={`heatmap-tree-tile${isNeutral ? " is-neutral" : ""}${statusClass}${confClass}`}
                        style={{ left: st.x + GAP / 2, top: st.y + GAP / 2, width: w, height: h, ...tileStyle }}
                        onClick={() => onAnalyze(row.ticker)}
                        onMouseEnter={(e) => setHover({ ticker: row.ticker, row, x: e.clientX, y: e.clientY })}
                        onMouseLeave={() => setHover((h) => (h && h.ticker === row.ticker ? null : h))}
                      >
                        {showTicker && <span className="htt-ticker" style={{ fontSize: tickerSize }}>{row.ticker}</span>}
                        {showPct && <span className="htt-pct" style={{ fontSize: tickerSize * 0.76 }}>{formatPct(row.changePercent)}</span>}
                      </button>
                    );
                  })}
                </React.Fragment>
              );
            })}
          </React.Fragment>
        ))}
      </div>

      {groups.length === 0 && (
        <p className="market-empty-cell">
          {lang === "ru" ? "Нет данных для карты" : lang === "uz" ? "Xarita uchun ma'lumot yo'q" : "No data for map"}
        </p>
      )}

      {hover && (() => {
        const r = hover.row;
        const name = r.name || companyMap[r.ticker]?.company_name || r.ticker;
        const price = marketDisplayPrice(r);
        const avgShare = Number.isFinite(r.avgPrice) ? r.avgPrice : avgSharePrice(r);
        const avgTrade = avgTradeValue(r);
        const largest = r.ts && Number.isFinite(r.ts.largest_value) ? r.ts.largest_value : null;
        const num = (v, d = 0) => (Number.isFinite(v) && v > 0 ? formatRatio(v, d, lang) : "—");
        const stats = [
          [mt(lang, "volumeCol"), num(r.stockVolume)],
          [mt(lang, "volQty"), num(r.stockQuantity)],
          [mt(lang, "avgSharePrice"), Number.isFinite(avgShare) && avgShare > 0 ? formatMarketNumber(avgShare, lang) : "—"],
          [mt(lang, "avgTradePrice"), num(avgTrade)],
          [mt(lang, "bigTrade"), num(largest)],
        ];
        // position: fixed at the cursor, clamped inside the viewport
        const TT_W = 236, TT_H = 210;
        const vw = typeof window !== "undefined" ? window.innerWidth : 1280;
        const vh = typeof window !== "undefined" ? window.innerHeight : 800;
        const left = Math.max(8, Math.min(hover.x + 16, vw - TT_W - 8));
        const top = Math.max(8, Math.min(hover.y + 16, vh - TT_H - 8));
        const tone = marketTone(r.changePercent);
        // Portal to <body> so an ancestor's backdrop-filter/transform doesn't turn
        // position:fixed into a clipped, mispositioned box.
        return createPortal(
          <div className="heatmap-tt" style={{ left, top, width: TT_W }}>
            <div className="heatmap-tt-head">
              <span className="heatmap-tt-ticker">{r.ticker}</span>
              <span className={`heatmap-tt-pct tone-${tone}`}>{formatPct(r.changePercent)}</span>
            </div>
            <div className="heatmap-tt-name">{name}</div>
            {price != null && <div className="heatmap-tt-price">{formatMarketNumber(price, lang)}</div>}
            {/* ТЗ §9: the tooltip carries the ACTUAL figures behind the colour,
                so a move that rests on one lot cannot be read as a market. */}
            {(() => {
              const meta = metaOf(r);
              if (!meta) return null;
              if (meta.status !== "ok") {
                return <div className="heatmap-tt-note">{meta.reason}</div>;
              }
              if (meta.confidence !== "low") return null;
              const parts = [
                meta.trades != null ? `${meta.trades} ${lang === "ru" ? "сдел." : lang === "uz" ? "bitim" : "trades"}` : null,
                meta.quantity != null ? `${formatMarketNumber(meta.quantity, lang)} ${lang === "ru" ? "бум." : lang === "uz" ? "qog'oz" : "sec."}` : null,
                meta.turnover != null ? `${formatMarketNumber(meta.turnover, lang)} ${lang === "ru" ? "сум" : lang === "uz" ? "so'm" : "UZS"}` : null,
              ].filter(Boolean);
              return <div className="heatmap-tt-note is-warn">{parts.join(", ")}</div>;
            })()}
            <div className="heatmap-tt-stats">
              {stats.map(([k, v]) => (
                <div className="heatmap-tt-row" key={k}><span>{k}</span><span>{v}</span></div>
              ))}
            </div>
          </div>,
          document.body
        );
      })()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Company detail page components
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// /admin/audit — the auditor's own screen (ТЗ v1.3 §12.6)
//
// The market tab shows the auditor without its vocabulary: a withheld metric is
// a dash with a reason. This page is the other audience — it shows the run, the
// rule, the security, the expected and actual values, and the INPUT that
// produced the finding, so the calculation can be reproduced locally instead of
// argued about. The admin secret is held in the field, never persisted: this is
// a machine-to-machine credential and the browser is not a machine.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Bonds (ТЗ Дополнение 1 §А.2)
//
// Eleven issues trade genuinely and had no place in the interface at all. They
// get their own table rather than a row in the equity board, because the columns
// differ: an issue has a value, not a capitalisation, and it has no earnings, so
// P/E and P/B are not blank for it — they do not apply.
// ---------------------------------------------------------------------------

function BondsTable({ language, onOpen }) {
  const lang = normalizeLanguage(language);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    fetch("/api/bonds")
      .then((r) => r.json())
      .then((d) => { if (alive) { if (d && d.ok) setData(d); else setError(true); } })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, []);

  if (error) return <p className="muted">{t("Раздел облигаций недоступен", "Obligatsiyalar bo'limi mavjud emas", "Bonds section unavailable")}</p>;
  if (!data) return <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>;

  const money = (v) => fmtCompact(v, lang);
  const pct = (v) => fmtPct(v, lang);
  const metric = (m) => {
    if (m?.value != null) return fmtMetric(m, lang);
    // A withheld value carries its reason; an em-dash alone would read as "we
    // did not bother" rather than "the source does not publish it".
    return <span className="cell-status" title={m?.note || m?.status || ""}>—</span>;
  };

  return (
    <div className="bonds-wrap">
      <div className="bonds-head">
        <span className="panel-label">{t("Облигации", "Obligatsiyalar", "Bonds")}</span>
        <span className="muted">
          {data.count} {t("выпусков", "chiqarilish", "issues")}
          {" · "}
          {/* NOT the equity market's capitalisation, and labelled so nobody
              adds the two together. */}
          {t("стоимость выпусков", "chiqarilish qiymati", "issue value")}: {money(data.issue_value_total)}
          {" · "}
          {t("базис дней", "kun bazisi", "day count")}: {data.day_count_basis}
        </span>
      </div>
      {/* The contour turns on in three stages, so the note has to say WHICH one
          is missing: the par comes from the exchange, the coupon from the
          issuer's payment filings, and the maturity only once a redemption
          window is filed. One sentence for all three would be wrong in whichever
          state it is not describing. */}
      {data.with_reference === 0 && (data.with_coupon ? (
        <p className="bonds-note muted">
          {t("Купон, НКД и текущая доходность посчитаны по существенным фактам эмитента, номинал — по данным биржи. Доходность к погашению и дюрация не считаются: дату погашения эмитент публикует только когда начинает выкуп, а срок «N дней с начала размещения» — это не дата.",
             "Kupon, YHD va joriy daromadlilik emitentning muhim faktlari bo'yicha, nominal — birja ma'lumoti bo'yicha hisoblangan. Daromadlilik va duratsiya hisoblanmaydi: to'lov sanasi faqat qaytarib sotib olish boshlanganda e'lon qilinadi.",
             "The coupon, the accrued interest and the running yield are computed from the issuer's material facts, the par from the exchange. Yield to maturity and duration are not: an issuer files a redemption date only when it starts redeeming, and \"N days after placement began\" is not a date.")}
        </p>
      ) : data.with_nominal ? (
        <p className="bonds-note muted">
          {t("Цена показана в процентах от номинала — номинал взят с биржи. Доходность к погашению и дюрация не считаются: купонная ставка и дата погашения не публикуются ни на бирже, ни в API.",
             "Narx nominalga nisbatan foizda ko'rsatilgan — nominal birjadan olingan. Daromadlilik va duratsiya hisoblanmaydi: kupon stavkasi va to'lov sanasi e'lon qilinmaydi.",
             "Price is shown as a percentage of par, with the par taken from the exchange. Yield to maturity and duration are not computed: the coupon rate and the maturity date are published neither by the exchange nor by the API.")}
        </p>
      ) : (
        <p className="bonds-note muted">
          {t("Доходность, дюрация и цена в процентах от номинала не считаются: источник не публикует номинал, купон и дату погашения. Как только справочник выпусков загружен, метрики появляются сами.",
             "Daromadlilik va duratsiya hisoblanmaydi: manba nominal, kupon va to'lov sanasini e'lon qilmaydi.",
             "Yield, duration and price as a percentage of par are not computed: the source publishes no nominal, coupon or maturity. They appear by themselves once the issue reference is loaded.")}
        </p>
      ))}
      <div className="market-table-scroll">
        <table className="market-table bonds-table">
          <thead>
            <tr>
              <th>{t("Тикер", "Ticker", "Ticker")}<TermInfo termId="ticker" lang={lang} /></th>
              <th>{t("Эмитент", "Emitent", "Issuer")}<TermInfo termId="issuer" lang={lang} /></th>
              <th className="num">{t("Цена", "Narx", "Price")}</th>
              <th className="num">{t("Изм.", "O'zg.", "Chg")}<TermInfo termId="change" lang={lang} /></th>
              <th className="num">{t("Оборот", "Aylanma", "Turnover")}<TermInfo termId="volume" lang={lang} /></th>
              <th className="num">{t("Сделки", "Bitimlar", "Trades")}</th>
              {/* Two different sizes: how many securities the issue is, and what
                  they are worth at today's price. The second is not equity
                  capitalisation and is never summed into it. */}
              <th className="num">{t("Выпуск, бумаг", "Chiqarilish, dona", "Issue, securities")}</th>
              <th className="num">{t("Стоимость выпуска", "Chiqarilish qiymati", "Issue value")}</th>
              <th className="num">% {t("номинала", "nominal", "of par")}<TermInfo termId="parPercent" lang={lang} /></th>
              {/* Two yields, never merged into one column: the coupon is what
                  the issuer pays on par, the running yield is what that coupon
                  is worth at today's price, and YTM is neither. */}
              <th className="num">{t("Купон", "Kupon", "Coupon")}<TermInfo termId="coupon" lang={lang} /></th>
              <th className="num">{t("Тек. дох.", "Joriy dar.", "Running")}<TermInfo termId="runningYield" lang={lang} /></th>
              <th className="num">{t("Доходность", "Daromadlilik", "YTM")}<TermInfo termId="ytm" lang={lang} /></th>
              <th>{t("Качество", "Sifat", "Quality")}</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((b) => (
              <tr key={b.ticker} onClick={() => onOpen && onOpen(b.ticker)} className="bond-row">
                <td><strong>{b.ticker}</strong></td>
                {/* The issuer's legal name runs to sixty characters and four of
                    the twelve issues share one — truncated here rather than
                    allowed to set the table's width. */}
                <td style={{ maxWidth: 230, overflow: "hidden", textOverflow: "ellipsis" }}
                    title={b.issuer || b.name || ""}>{b.issuer || b.name || "—"}</td>
                <td className="num">{fmtPrice(b.price, lang)}</td>
                <td className={`num tone-${marketTone(b.change_pct)}`}>{pct(b.change_pct)}</td>
                <td className="num">{money(b.turnover)}</td>
                <td className="num">{Number.isFinite(b.trades) ? b.trades : "—"}</td>
                <td className="num">{fmtNumber(b.reference?.issue_volume, lang, 0)}</td>
                <td className="num">{money(b.issue_value)}</td>
                <td className="num">{metric(b.price_pct)}</td>
                <td className="num">
                  {b.reference?.coupon_rate != null
                    ? `${fmtNumber(b.reference.coupon_rate, lang, 2)}%`
                    : <span className="cell-status" title={t("эмитент не подавал начислений по этому выпуску", "", "the issuer has filed no accrual for this issue")}>—</span>}
                </td>
                <td className="num">{metric(b.simple_yield)}</td>
                <td className="num">{metric(b.ytm)}</td>
                <td>
                  {b.status !== "ok"
                    ? <span className="cell-status" title={b.reason || ""}>
                        {b.status === "matured"
                          ? t("в погашении", "qaytarilmoqda", "redeeming")
                          : b.status === "no_price"
                            ? t("нет цены", "narx yo'q", "no price")
                            : t("нет сделок", "bitim yo'q", "not traded")}
                      </span>
                    : <span className="muted">{b.quality?.data_tier || "—"}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
// ---------------------------------------------------------------------------
// The auditor's own screen used to live here as AuditAdminPage, authenticated by
// typing the machine X-Admin-Secret into a field. It is superseded by the admin
// panel (admin/AdminPanel.jsx, section «Аудит»), which authenticates as the
// signed-in administrator instead, so the shared secret no longer reaches the
// browser at all. /admin/audit still resolves; it now opens that section.
// ---------------------------------------------------------------------------



// The spans the chart offers.
//
// `months` is what /api/price-history is ASKED for — its smallest unit is a
// month — and `days`/`ytd` then narrow the loaded series on the client. Keeping
// both in one table is what stops the buttons and the fetch drifting apart.
//
// There is deliberately NO 1D. UZSE publishes one row per SESSION and no
// intraday ticks (see the candle note below: bars can only be rolled up, never
// down), so a day view would be a single candle — a button that looks like the
// others and answers nothing.
const CHART_RANGES = [
  { key: "1w", months: 1, days: 7, span: 0.25, label: ["1Н", "1H", "1W"] },
  { key: "1m", months: 1, span: 1, label: ["1М", "1O", "1M"] },
  { key: "3m", months: 3, span: 3, label: ["3М", "3O", "3M"] },
  { key: "6m", months: 6, span: 6, label: ["6М", "6O", "6M"] },
  { key: "ytd", ytd: true, label: ["YTD", "YTD", "YTD"] },
  { key: "1y", months: 12, span: 12, label: ["1Г", "1Y", "1Y"] },
  { key: "3y", months: 36, span: 36, label: ["3Г", "3Y", "3Y"] },
  { key: "5y", months: 60, span: 60, label: ["5Л", "5Y", "5Y"] },
  { key: "max", months: 240, span: 240, label: ["Макс", "Maks", "Max"] },
];

function chartRange(key) {
  return CHART_RANGES.find((r) => r.key === key) || CHART_RANGES.find((r) => r.key === "1y");
}

/** Months to ask the API for. YTD is a moving target — in January it is weeks. */
function chartRangeMonths(key) {
  const r = chartRange(key);
  if (r.ytd) return Math.min(60, new Date().getMonth() + 2);
  return r.months;
}

/** How much calendar the view actually shows, in months — drives bucket width. */
function chartRangeSpan(key) {
  const r = chartRange(key);
  return r.ytd ? new Date().getMonth() + 1 : r.span;
}

/** The first date the view keeps, or null when the whole fetch is shown. */
function chartRangeCutoff(key) {
  const r = chartRange(key);
  if (r.ytd) return `${new Date().getFullYear()}-01-01`;
  if (r.days) {
    const d = new Date();
    d.setDate(d.getDate() - r.days);
    return d.toISOString().slice(0, 10);
  }
  return null;
}

function CompanyPriceChart({ history, loading, range, onRangeChange, adjustments, lang, quality, metricsWindows }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const months = chartRangeSpan(range);
  const [hover, setHover] = React.useState(null);
  const [maOn, setMaOn] = React.useState({ ma20: false, ma50: false });

  // The chart's height used to be a side effect of its width: the SVG carried a
  // fixed 820x360 viewBox at `width: 100%; height: auto`, so it was 488px tall
  // in a 1112px column and 246px in a 560px one — tall where there was room to
  // spare and short where there was none, with 664px of empty page underneath it
  // at 1900px. Measure the box instead and solve the viewBox height for the
  // height we actually want, which keeps the 1:1 aspect mapping (no distorted
  // strokes or stretched axis labels, which is what preserveAspectRatio="none"
  // would have cost) while letting the drawing fill its space.
  // A CALLBACK ref, not useRef + useLayoutEffect([]): this component returns
  // early while the history is still loading, so on the first render there is no
  // <svg> to measure — and an effect with an empty dependency list never runs
  // again once the chart appears. It measured 0 forever and the chart stayed at
  // its old fixed height.
  const [boxW, setBoxW] = React.useState(0);
  const [viewH, setViewH] = React.useState(0);
  const chartNode = React.useRef(null);
  const roRef = React.useRef(null);
  const measure = React.useCallback(() => {
    const n = chartNode.current;
    if (!n || typeof window === "undefined") return;
    setBoxW(n.getBoundingClientRect().width);
    setViewH(window.innerHeight);
  }, []);
  const attachChart = React.useCallback((node) => {
    if (roRef.current) { roRef.current.disconnect(); roRef.current = null; }
    chartNode.current = node;
    if (!node) return;
    measure();
    if (typeof ResizeObserver !== "undefined") {
      roRef.current = new ResizeObserver(measure);
      roRef.current.observe(node);
    }
  }, [measure]);
  React.useEffect(() => {
    if (typeof window === "undefined") return undefined;
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure]);

  const rangeBar = (
    <div className="company-chart-ranges">
      {CHART_RANGES.map((r) => (
        <button key={r.key} type="button"
          className={`range-btn ${range === r.key ? "active" : ""}`}
          onClick={() => onRangeChange(r.key)}>
          {r.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
        </button>
      ))}
    </div>
  );

  if (loading) return <div className="chart-loading muted">{t("Загрузка...", "Yuklanmoqda...", "Loading...")}</div>;

  // The feed returns newest-first — sort ascending so time reads left→right.
  const daily = (history || []).map((h) => {
    if (Array.isArray(h)) return { date: h[0], close: Number(h[1]) || 0, volume: 0, change: null };
    return {
      date: h.date || h.trade_date,
      open: h.open != null ? Number(h.open) : null,
      high: h.high != null ? Number(h.high) : null,
      low: h.low != null ? Number(h.low) : null,
      close: Number(h.close ?? h.price ?? h.close_price ?? 0),
      volume: Number(h.volume ?? h.trading_volume ?? 0) || 0,
      change: h.change != null ? Number(h.change) : null,
    };
  }).filter((p) => p.close > 0 && p.date).sort((a, b) => String(a.date).localeCompare(String(b.date)));

  // The endpoint's smallest unit is a month, so 1Н and YTD ask for the month(s)
  // that contain them and are trimmed here. ISO dates compare as strings.
  const cutoff = chartRangeCutoff(range);
  const windowed = cutoff ? daily.filter((p) => String(p.date) >= cutoff) : daily;
  // A week with no executions is a fact about the security, not a failure to
  // load anything — on this market most securities trade on a minority of days,
  // and «история недоступна» would be a lie about a page that has years of it.
  if (cutoff && windowed.length < 2 && daily.length >= 2) return (
    <div className="company-chart-wrap">
      <div className="company-chart-toolbar">{rangeBar}</div>
      <div className="muted" style={{ padding: "48px 0", textAlign: "center", fontSize: 14 }}>
        {chartRange(range).ytd
          ? t("С начала года сделок не было", "Yil boshidan bitim bo'lmagan", "No trades since the start of the year")
          : t("За неделю сделок не было", "Bir haftada bitim bo'lmagan", "No trades in the past week")}
      </div>
    </div>
  );

  if (daily.length < 2) return (
    <div>
      <div className="company-chart-toolbar">{rangeBar}</div>
      <div className="muted" style={{ padding: "32px 0", textAlign: "center" }}>
        {t("История цен недоступна", "Narxlar tarixi mavjud emas", "Price history unavailable")}
      </div>
    </div>
  );

  // uz-UZ renders months as "M01"/"M02"; keep Russian month names for ru+uz.
  const dateLocale = lang === "en" ? "en-US" : "ru-RU";
  const fmtDate = (d, withYear) => d
    ? new Date(d).toLocaleDateString(dateLocale, withYear ? { year: "2-digit", month: "short", day: "numeric" } : { month: "short", day: "numeric" })
    : "";
  // Multi-year ranges show "mon 'yy" on the axis (day-of-month is noise at monthly/quarterly buckets).
  const fmtAxis = (d) => d
    ? (months >= 12 ? new Date(d).toLocaleDateString(dateLocale, { year: "2-digit", month: "short" }) : fmtDate(d))
    : "";
  const abbrev = (v) => v == null ? "—" : Math.abs(v) >= 1e6 ? `${(v / 1e6).toFixed(2)}M` : Math.abs(v) >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : `${Math.round(v)}`;
  const fmtFull = (v) => v == null ? "—" : Number(v).toLocaleString(dateLocale, { maximumFractionDigits: 2 });

  const W = 820;
  // How tall the drawing should actually be on screen, before it is expressed in
  // viewBox units. Bounded at both ends: a chart shorter than 340px cannot show
  // a candle body, and one taller than 660px pushes «О компании» off the fold on
  // a laptop. 58 % of the window is the band between those on the screens this
  // is used on; the fallback runs one frame, before the box has been measured.
  // Left unrounded on purpose: these are SVG user units, not a published figure,
  // and the repo's round-on-output rule is about the latter.
  const targetPx = Math.max(340, Math.min(660, (viewH || 900) * 0.58));
  const H = boxW > 0 ? (targetPx * W) / boxW : 360;
  const PAD = { top: 14, right: 14, bottom: 40, left: 64 };
  // No volume strip: the reference design has none, and the session's turnover,
  // share count and trade count are stated in the «Торги» block beside the
  // chart — so the information is on the page, not in a 1px histogram that a
  // daily line at «Макс» turns into a smear.
  const priceTop = PAD.top;
  const priceBot = H - PAD.bottom;
  const innerW = W - PAD.left - PAD.right;

  // ONE view: a line. The customer asked for the reference page's chart and only
  // that, so the candle mode, its interval roll-up (day/week/month/quarter) and
  // the Линия/Свечи switch are gone. A line needs no bar width, which is what
  // the roll-up existed to protect, so every session the range loaded is drawn.
  //
  // ТЗ §6: OHLC correctness is a property of a POINT, not of the series — kept
  // because the tooltip still states open/high/low for the days that have them.
  const ohlcOk = (p) => p.open > 0 && p.high > 0 && p.low > 0 && p.close > 0
    && p.low <= Math.min(p.open, p.close) && Math.max(p.open, p.close) <= p.high;
  const points = windowed;
  // ТЗ §6 still applies to the SHAPE of the line. On a security that trades on a
  // minority of days a straight segment between two trades three weeks apart
  // draws prices that never existed, so the series becomes a step. The server
  // decides which securities those are (data_tier sparse/illiquid), not a hand.
  const stepLine = quality ? quality.candles_enabled === false : false;

  // Per point, again: a single record without a low must not drag the whole
  // price scale to NaN.
  const lows = points.map((p) => (ohlcOk(p) ? p.low : p.close));
  const highs = points.map((p) => (ohlcOk(p) ? p.high : p.close));
  const minP = Math.min(...lows), maxP = Math.max(...highs);
  const rangeP = maxP - minP || 1;
  const maxVol = Math.max(...points.map((p) => p.volume), 1);
  // Per-point markers only where a marker can be READ. On a step series every
  // point is a trade and worth showing, but KSCM at «Макс» has 1033 of them:
  // they stop being marks and become a smear over the line. Same measured-width
  // reasoning the candle interval used before it was removed.
  const gapPx = (innerW * (boxW > 0 ? boxW / W : 1)) / Math.max(1, points.length - 1);
  const showPointMarks = stepLine && gapPx >= 8;

  const xs = (i) => PAD.left + (i / (points.length - 1)) * innerW;
  const ys = (p) => priceTop + (1 - (p - minP) / rangeP) * (priceBot - priceTop);

  const lineD = points.map((p, i) => {
    const x = xs(i).toFixed(1), y = ys(p.close).toFixed(1);
    if (i === 0) return `M${x},${y}`;
    // A step carries the previous price forward to the day it actually changed.
    return stepLine ? `L${x},${ys(points[i - 1].close).toFixed(1)} L${x},${y}` : `L${x},${y}`;
  }).join(" ");
  const areaD = `${lineD} L${xs(points.length - 1).toFixed(1)},${priceBot.toFixed(1)} L${xs(0).toFixed(1)},${priceBot.toFixed(1)} Z`;
  const isUp = points[points.length - 1].close >= points[0].close;
  const color = isUp ? "#22c55e" : "#ef4444";

  // ТЗ §6: moving averages are always computed on the RAW DAILY series over a
  // calendar window, whatever the display bucket is. Averaging 20 weekly
  // candles spans 134 calendar days, not 28 — which is why "MA20" drew one
  // line in candle mode and a different one in line mode on 72 of 72
  // securities. The window comes from the server's threshold config.
  // The window the SERVER applied: from the metrics response when it has
  // arrived, otherwise from /api/config — never a literal invented here.
  const MA_DAYS = {
    ma20: metricsWindows?.ma20 || cfgThreshold("moving_average.ma20_calendar_days", 28),
    ma50: metricsWindows?.ma50 || cfgThreshold("moving_average.ma50_calendar_days", 70),
  };
  const MA_MIN_OBS = 3;
  const calendarMA = (days) => {
    const out = new Array(daily.length).fill(null);
    let start = 0, sum = 0;
    for (let i = 0; i < daily.length; i++) {
      sum += daily[i].close;
      const cutoff = new Date(daily[i].date);
      cutoff.setDate(cutoff.getDate() - (days - 1));
      while (start < i && new Date(daily[start].date) < cutoff) {
        sum -= daily[start].close;
        start += 1;
      }
      const n = i - start + 1;
      out[i] = n >= MA_MIN_OBS ? sum / n : null;
    }
    return out;
  };
  // The MA is a daily series; the chart may be drawing weekly or monthly
  // buckets. Each drawn point carries the date of the last day in its bucket,
  // so the value is read off that day rather than recomputed on the buckets.
  const alignToPoints = (dailySeries) => {
    const byDate = new Map();
    daily.forEach((p, i) => byDate.set(p.date, dailySeries[i]));
    return points.map((p) => (byDate.has(p.date) ? byDate.get(p.date) : null));
  };
  // Not memoised on purpose: this sits after the component's early returns, so
  // a hook here would be a conditional hook. Both passes are O(n) over a few
  // hundred points.
  const ma20Daily = calendarMA(MA_DAYS.ma20);
  const ma50Daily = calendarMA(MA_DAYS.ma50);
  const ma20Available = ma20Daily.some((v) => v != null);
  const ma50Available = ma50Daily.some((v) => v != null);
  const maPath = (arr) => {
    let d = "", started = false;
    arr.forEach((v, i) => {
      if (v == null) return;
      d += `${started ? "L" : "M"}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`;
      started = true;
    });
    return d;
  };
  const ma20 = maOn.ma20 && ma20Available ? alignToPoints(ma20Daily) : null;
  const ma50 = maOn.ma50 && ma50Available ? alignToPoints(ma50Daily) : null;

  // Grid lines land on round numbers inside the data range — 5K / 10K / 15K —
  // instead of five samples of it (9.8K, 14.5K, 19.3K), which read as data
  // rather than as a scale. The plotted range is untouched: only where the
  // lines are drawn changes.
  const yTicks = 4;
  const niceStep = (span, count) => {
    const raw = span / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  };
  const yStep = rangeP > 0 ? niceStep(rangeP, yTicks) : 0;
  const yLabels = [];
  if (yStep > 0) {
    const first = Math.ceil(minP / yStep) * yStep;
    // Full numbers, not 10.0K: this is a price scale and the reference states it
    // as one. `abbrev` stays for the tooltip's volume, where a K/M really helps.
    for (let v = first; v <= maxP + yStep * 1e-9; v += yStep) yLabels.push({ y: ys(v), label: fmtFull(v) });
  }
  // A flat or near-flat series can leave one round number in range (or none) —
  // then an even split of the range is the only honest axis left.
  if (yLabels.length < 2) {
    yLabels.length = 0;
    const seen = new Set();
    for (let i = 0; i <= yTicks; i++) {
      const v = minP + (i / yTicks) * rangeP;
      // A price that never moved would otherwise stack the same number five
      // times down the panel and call it a scale.
      const label = fmtFull(v);
      if (seen.has(label)) continue;
      seen.add(label);
      yLabels.push({ y: ys(v), label });
    }
  }

  // The last point always gets a label. When the regular grid lands a candle or
  // two short of it the two strings print on top of each other (three years of
  // weekly buckets did exactly that), so a tick too close to its neighbour
  // yields — and the endpoint wins the collision.
  const X_LABEL_GAP = 64;
  const xStep = Math.max(1, Math.floor(points.length / 6));
  const xLabels = [];
  points.forEach((p, i) => {
    const isLast = i === points.length - 1;
    if (i % xStep !== 0 && !isLast) return;
    const x = xs(i);
    const prev = xLabels[xLabels.length - 1];
    if (prev && x - prev.x < X_LABEL_GAP) {
      if (!isLast) return;
      xLabels.pop();
    }
    xLabels.push({ x, label: fmtAxis(p.date) });
  });

  const onMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    const relX = ((e.clientX - rect.left) / rect.width) * W;
    let i = Math.round(((relX - PAD.left) / innerW) * (points.length - 1));
    i = Math.max(0, Math.min(points.length - 1, i));
    setHover(i);
  };

  const hp = hover != null ? points[hover] : null;
  const hx = hover != null ? xs(hover) : 0;
  const ttRight = hover != null && hx > W * 0.62;

  // Splits and bonus issues that fall inside the visible span. The prices either side are
  // already in the same unit (the server restated the older half), but the day the share
  // count changed is still worth naming — otherwise a reader checking a 2024 close against
  // uzse.uz finds a different number and no explanation. An event before the first point
  // (index 0) has nothing left to mark: the whole span is already post-event.
  const eventMarks = (adjustments || [])
    .map((a) => ({ ...a, i: points.findIndex((p) => String(p.date) >= String(a.ex_date)) }))
    .filter((a) => a.i > 0);
  const kindLabel = (kind) => kind === "bonus"
    ? t("бонусная эмиссия", "bonus emissiya", "bonus issue")
    : t("дробление", "aksiyalarni maydalash", "split");

  return (
    <div className="company-chart-wrap">
      <div className="company-chart-toolbar">
        {rangeBar}
        <div className="company-chart-opts">
          <button type="button" className={`chart-opt-btn chart-ma-ma20 ${maOn.ma20 ? "active" : ""}`}
            disabled={!ma20Available}
            title={`${MA_DAYS.ma20} ${t("календарных дней", "kalendar kun", "calendar days")}`}
            onClick={() => setMaOn((s) => ({ ...s, ma20: !s.ma20 }))}>MA20</button>
          <button type="button" className={`chart-opt-btn chart-ma-ma50 ${maOn.ma50 ? "active" : ""}`}
            disabled={!ma50Available}
            title={`${MA_DAYS.ma50} ${t("календарных дней", "kalendar kun", "calendar days")}`}
            onClick={() => setMaOn((s) => ({ ...s, ma50: !s.ma50 }))}>MA50</button>
        </div>
      </div>

      {stepLine && (
        <p className="cpc-tier-note muted">
          {t("Цена показана ступенями — между сделками она не менялась",
             "Narx pog'onalar bilan ko'rsatilgan — bitimlar orasida u o'zgarmagan",
             "The price is drawn as steps — between trades it did not move")}
          {quality?.reason ? ` — ${quality.reason}` : ""}
          {"."}
        </p>
      )}

      {/* `height: auto` still derives the height from the viewBox — but the
          viewBox height is now solved from the measured width, so the result is
          `targetPx` at any column width. Everything expressed in viewBox units
          (axis gutter, volume strip, type) renders at a size set by the WIDTH
          and is unchanged by this; the whole of the extra height goes to the
          price plot, which is the part worth more room. */}
      <svg ref={attachChart} viewBox={`0 0 ${W} ${H}`} className="company-price-chart-svg" style={{ width: "100%", height: "auto" }}
        onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="cpcgrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.22" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Dashed horizontal grid, as in the reference. Full plot width, under
            everything the reader is meant to look at. */}
        {yLabels.map((tick, i) => (
          <line key={i} x1={PAD.left} y1={tick.y} x2={W - PAD.right} y2={tick.y}
            stroke="currentColor" strokeOpacity="0.16" strokeDasharray="4 6" strokeWidth="0.8" />
        ))}

        <path d={areaD} fill="url(#cpcgrad)" />
        <path d={lineD} fill="none" stroke={color} strokeWidth="2"
          strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />

        {ma20 && <path d={maPath(ma20)} fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeOpacity="0.9" />}
        {ma50 && <path d={maPath(ma50)} fill="none" stroke="#a855f7" strokeWidth="1.5" strokeOpacity="0.9" />}

        {yLabels.map((tick, i) => (
          <text key={`yl${i}`} x={PAD.left - 6} y={tick.y + 4} textAnchor="end" fontSize="10" fill="currentColor" opacity="0.5">{tick.label}</text>
        ))}
        {/* Centred everywhere except at the ends, where half of "июнь 26 г."
            would hang outside the viewBox and get clipped by the frame. */}
        {xLabels.map((tick, i) => (
          <text key={`xl${i}`} x={tick.x} y={H - 6}
            textAnchor={tick.x < PAD.left + 26 ? "start" : tick.x > W - PAD.right - 26 ? "end" : "middle"}
            fontSize="10" fill="currentColor" opacity="0.5">{tick.label}</text>
        ))}

        {/* ТЗ §6: on a step chart the points carry the day's volume in their
            size, so a run of identical prices does not read as steady trading;
            and a move that stopped exactly at the ±20 % daily limit is marked,
            because it is a rule of the exchange, not a decision of the market. */}
        {showPointMarks && points.map((p, i) => {
          const share = maxVol > 0 ? (p.volume || 0) / maxVol : 0;
          const r = 1.6 + Math.sqrt(Math.max(share, 0)) * 3.4;
          const prev = i > 0 ? points[i - 1].close : null;
          const move = prev && prev > 0 ? ((p.close - prev) / prev) * 100 : null;
          const atLimit = move != null && Math.abs(Math.abs(move) - 20) < 0.5;
          return (
            <g key={`pt${i}`}>
              <circle cx={xs(i)} cy={ys(p.close)} r={r} fill={color} fillOpacity="0.75" />
              {atLimit && (
                <rect x={xs(i) - 4.5} y={ys(p.close) - 4.5} width="9" height="9"
                  fill="none" stroke="#fbbf24" strokeWidth="1.2">
                  <title>{t("движение упёрлось в дневной лимит ±20 %",
                            "harakat kunlik ±20 % limitga tayandi",
                            "move hit the ±20 % daily limit")}</title>
                </rect>
              )}
            </g>
          );
        })}

        {<circle cx={xs(points.length - 1)} cy={ys(points[points.length - 1].close)} r="4" fill={color} />}

        {eventMarks.map((m) => (
          <line key={`ev${m.ex_date}`} x1={xs(m.i)} y1={priceTop} x2={xs(m.i)} y2={priceBot}
            stroke="currentColor" strokeOpacity="0.3" strokeDasharray="2 4" />
        ))}

        {/* Crosshair */}
        {hover != null && (
          <>
            <line x1={hx} y1={priceTop} x2={hx} y2={priceBot} stroke="currentColor" strokeOpacity="0.38" strokeDasharray="3 3" />
            <circle cx={hx} cy={ys(points[hover].close)} r="3.6" fill={color} stroke="var(--panel, #0b0f1a)" strokeWidth="1.5" />
          </>
        )}
      </svg>

      {hp && (
        <div className="cpc-tooltip" style={ttRight
          ? { right: `calc(${((W - hx) / W) * 100}% + 12px)` }
          : { left: `calc(${(hx / W) * 100}% + 12px)` }}>
          <div className="cpc-tt-date">{fmtDate(hp.date, true)}</div>
          <div className="cpc-tt-row"><span>{t("Закрытие", "Yopilish", "Close")}</span><b>{fmtFull(hp.close)}</b></div>
          {ohlcOk(hp) && (
            <>
              <div className="cpc-tt-row"><span>{t("Откр.", "Ochil.", "Open")}</span><b>{fmtFull(hp.open)}</b></div>
              <div className="cpc-tt-row"><span>{t("Макс.", "Maks.", "High")}</span><b>{fmtFull(hp.high)}</b></div>
              <div className="cpc-tt-row"><span>{t("Мин.", "Min.", "Low")}</span><b>{fmtFull(hp.low)}</b></div>
            </>
          )}
          <div className="cpc-tt-row"><span>{t("Объём", "Hajm", "Volume")}</span><b>{abbrev(hp.volume)}</b></div>
          {hp.change != null && (
            <div className="cpc-tt-row"><span>{t("Изм.", "O'zg.", "Chg")}</span>
              <b style={{ color: hp.change >= 0 ? "#22c55e" : "#ef4444" }}>{hp.change >= 0 ? "+" : ""}{fmtFull(hp.change)}</b>
            </div>
          )}
        </div>
      )}

      {eventMarks.length > 0 && (
        <p className="cpc-adjust-note">
          {t("Цены до этих дат пересчитаны на текущую акцию",
             "Bu sanalargacha boʻlgan narxlar joriy aksiyaga qayta hisoblangan",
             "Prices before these dates are restated onto the current share")}
          {": "}
          {eventMarks.map((m, i) => (
            <React.Fragment key={m.ex_date}>
              {i > 0 && "; "}
              {fmtDate(m.ex_date, true)} — {kindLabel(m.kind)} ×{fmtFull(m.ratio)}
            </React.Fragment>
          ))}
          {t(". На бирже они котировались в прежних долях.",
             ". Birjada ular eski ulushlarda kotirovka qilingan.",
             ". The exchange quoted them in the old units.")}
        </p>
      )}
    </div>
  );
}

// The price-statistics strip that used to sit under the chart — VWAP, макс/мин,
// среднее закрытий, 1М/YTD/YoY/QoQ, волатильность and макс. дневной диапазон —
// was REMOVED from the company page by the customer on 2026-08-08. It is not on
// the quote page this layout follows, and on a page a shareholder reads it was
// six figures nothing on screen explained: two different averages of the same
// window, six percent apart, next to a historical peak from June 2024 that never
// changes.
//
// Nothing was deleted below the screen. /api/company/{t}/metrics and formulas.py
// are untouched — the auditor, the exports and the paid analysis all read them,
// and this page still reads `quality` and `ma_windows` off the same response to
// decide whether candles are meaningful. The figures are unpublished here, not
// gone; re-rendering them is a component away.

// ТЗ §8: a multiple the server withheld says WHY. «убыток» is a fact about the
// issuer, not missing data; «проверяется» means the statement behind it failed
// validation; a range status means the figure exists and is not believable.
// ТЗ v1.3 §12.6: the auditor is visible without its rule codes — a withheld
// metric is a dash whose tooltip says why; the reader does not need to know
// which rule fired, only which numbers they can trust.
//
// Module-level because the market board and the company page's key-stats rail
// now read the SAME /api/market/multiples envelope. While this vocabulary lived
// inside MarketView the company page had no way to say «снято аудитом», so it
// recomputed P/E and P/B itself and published figures the board withheld.
const MULTIPLE_STATUS_TEXT = {
  audit_blocked: ["снято аудитом", "audit olib tashladi", "withheld by audit"],
  loss_making: ["убыток", "zarar", "loss"],
  unverified: ["проверяется", "tekshirilmoqda", "under review"],
  out_of_range: ["вне диапазона", "diapazondan tashqari", "out of range"],
  shares_inconsistent: ["сверка акций", "aksiyalar sverkasi", "share count"],
  incomplete: ["нет всех классов", "barcha sinflar yo'q", "classes missing"],
  no_market_cap: ["нет капитализации", "kapitalizatsiya yo'q", "no market cap"],
  no_share_count: ["нет числа акций", "aksiyalar soni yo'q", "no share count"],
};

function multipleStatusText(status, lang) {
  const words = MULTIPLE_STATUS_TEXT[status];
  return words ? words[lang === "uz" ? 1 : lang === "en" ? 2 : 0] : null;
}

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
              ? `${r.changePercent > 0 ? "+" : ""}${r.changePercent.toFixed(2)}%`
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

// The key-stats rail — what the session did, what the issuer is worth, and on
// what basis. It sits beside the chart instead of below it because the numbers
// a reader opens a company page for were previously two screens down, behind a
// chart that filled the first one.
//
// Every valuation figure here comes from /api/market/multiples — the same
// issuer-level envelope the market board reads, audit suppression included. The
// page used to recompute P/E and P/B on the client at CLASS level, which is the
// wrong denominator for a two-class issuer and, worse, bypassed the auditor: a
// figure the board withheld as «снято аудитом» still printed here.
function CompanyKeyStats({ row, sec, metrics12, mult, dividends, lastPrice, securityType, lang, placement = "rail" }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const num = (v) => (Number.isFinite(v) ? formatMarketNumber(v, lang) : null);
  const compact = (v) => (Number.isFinite(v) ? formatCompactVolume(v, lang) : null);
  const count = (v) => (Number.isFinite(v) ? formatRatio(v, 0, lang) : null);

  // A plain row: rendered only when there is something to put in it. An empty
  // label with a dash tells the reader nothing they did not already know.
  const rows = [];
  const put = (label, value, hint) => {
    if (value == null || value === "") return;
    rows.push(
      <div className="company-metric-row" key={label}>
        <span className="panel-label">{label}</span>
        <span className="company-metric-val" title={hint || undefined}>{value}</span>
      </div>,
    );
  };

  // A multiple keeps the server's verdict: a value, or the reason it is absent.
  const putMultiple = (label, metric, digits = 2, suffix = "×", caption) => {
    if (!metric) return;
    let node;
    if (metric.value != null) {
      node = <>{formatRatio(metric.value, digits, lang)}{suffix}</>;
    } else {
      const words = multipleStatusText(metric.status, lang);
      if (!words) return;
      const why = (metric.reasons || []).join("; ") || metric.note || "";
      node = <span className="cell-status" title={why || undefined}>{words}</span>;
    }
    rows.push(
      <div className="company-metric-row" key={label}>
        <span className="panel-label">
          {label}{caption ? <span className="co-metric-period"> · {caption}</span> : null}
        </span>
        <span className="company-metric-val">{node}</span>
      </div>,
    );
  };

  const low = row?.lowPrice, high = row?.highPrice;
  const win = metrics12?.window;
  const yearLow = win?.min_close?.value, yearHigh = win?.max_close?.value;

  // A range reads faster as a picture than as two numbers, and the marker is
  // the only thing on this page that says where today sits inside the year.
  const rangeBar = (lo, hi, at) => {
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null;
    const pos = Number.isFinite(at) ? Math.min(100, Math.max(0, ((at - lo) / (hi - lo)) * 100)) : null;
    return (
      <div className="keystat-range">
        <div className="keystat-range-track">
          {pos != null && <span className="keystat-range-dot" style={{ left: `${pos}%` }} />}
        </div>
        <div className="keystat-range-ends">
          <span>{num(lo)}</span><span>{num(hi)}</span>
        </div>
      </div>
    );
  };

  const blocks = [];
  const pushBlock = (key, title, body, note) => {
    if (!body || (Array.isArray(body) && body.length === 0)) return;
    blocks.push(
      <div className="co-sidebar-block" data-block={key} key={key}>
        <h3 className="co-heading">{title}</h3>
        <div className="company-metrics-list">{body}</div>
        {note && <div className="keystat-note muted">{note}</div>}
      </div>,
    );
  };

  // --- Session -------------------------------------------------------------
  put(t("Пред. закрытие", "Oldingi yopilish", "Previous close"), num(row?.closePrice));
  put(t("Открытие", "Ochilish", "Open"), num(row?.openPrice));
  if (Number.isFinite(low) && Number.isFinite(high) && high > low) {
    put(t("Диапазон дня", "Kunlik diapazon", "Day range"), `${num(low)} – ${num(high)}`);
  }
  put(t("Оборот", "Aylanma", "Turnover"), compact(row?.stockVolume) ? `${compact(row.stockVolume)} UZS` : null);
  put(t("Бумаг", "Qog'ozlar", "Shares traded"), count(row?.stockQuantity));
  put(t("Сделок", "Bitimlar", "Trades"), count(row?.stockTradeCount));
  put(t("Средняя цена", "O'rtacha narx", "Average price"),
      num(Number.isFinite(row?.avgPrice) ? row.avgPrice : avgSharePrice(row)));
  const sessionRows = rows.splice(0, rows.length);
  // The date is not decoration: the board carries a close forward through
  // sessions with no executions, so a rail with no date invites reading an old
  // session as today's.
  const sessionDate = row?.last_trade_date || row?.close_date || sec?.last_trade_date || null;
  pushBlock("session", t("Торги", "Savdolar", "Session"), sessionRows,
    sessionDate ? `${t("сессия", "sessiya", "session")} ${sessionDate}` : null);

  // --- The year ------------------------------------------------------------
  const yearBar = rangeBar(yearLow, yearHigh, lastPrice);
  if (yearBar) {
    blocks.push(
      <div className="co-sidebar-block" data-block="range" key="range">
        <h3 className="co-heading">{t("Диапазон 52 недели", "52 hafta diapazoni", "52-week range")}</h3>
        {yearBar}
        <div className="keystat-note muted">
          {t("по ценам закрытия", "yopilish narxlari bo'yicha", "on closing prices")}
          {win?.points ? ` · ${win.points} ${t("точек", "nuqta", "points")}` : ""}
        </div>
      </div>,
    );
  }

  // --- Valuation -----------------------------------------------------------
  // Капитализация is THIS class — the same figure the market board's column
  // shows, and the only one that divides by the share count on the next line.
  // The issuer total is a different quantity and gets its own row when the
  // issuer has more than one class; printing the issuer figure above a class
  // share count invites a division that means nothing (UZTLP: 9 945,8B over
  // 29,6M shares).
  const capClass = safeNumber(row?.marketCap);
  const capIssuer = mult?.market_cap_issuer?.value;
  put(t("Капитализация", "Kapitalizatsiya", "Market cap"),
      compact(capClass) ? `${compact(capClass)} UZS` : null);
  put(t("Акций в обращении", "Muomaladagi aksiyalar", "Shares outstanding"), count(row?.sharesOutstanding));
  if ((mult?.issuer_classes?.length || 0) > 1 && Number.isFinite(capIssuer)
      && (!Number.isFinite(capClass) || Math.abs(capIssuer - capClass) > 1)) {
    put(t("Капитализация эмитента", "Emitent kapitalizatsiyasi", "Issuer market cap"),
        `${compact(capIssuer)} UZS`,
        `${t("все классы", "barcha sinflar", "all classes")}: ${mult.issuer_classes.join(", ")}`);
  }
  const valuationRows = rows.splice(0, rows.length);
  putMultiple("P/E", mult?.pe, 2, "×", mult?.base_period || undefined);
  putMultiple("P/B", mult?.pb, 2, "×");
  putMultiple("BVPS", mult?.bvps, 2, "");
  pushBlock("valuation", t("Оценка", "Baholash", "Valuation"), [...valuationRows, ...rows.splice(0, rows.length)]);

  // --- Profitability -------------------------------------------------------
  putMultiple("ROE", mult?.roe, 2, "");
  putMultiple("ROA", mult?.roa, 2, "");
  putMultiple(t("Чистая маржа", "Sof marja", "Net margin"), mult?.net_margin, 2, "");
  putMultiple(t("Долг/Капитал", "Qarz/Kapital", "Debt/Equity"), mult?.debt_to_equity, 2, "");
  pushBlock("profitability", t("Рентабельность", "Rentabellik", "Profitability"), rows.splice(0, rows.length));

  // --- Dividends -----------------------------------------------------------
  // Bonds pay coupons, not dividends; the tab is hidden for them and so is this.
  if (securityType !== "bond" && Array.isArray(dividends) && dividends.length) {
    const d = dividendSummary(dividends, { isPreferred: isPreferredRow(sec), lastPrice });
    put(t("Последний дивиденд", "Oxirgi dividend", "Last dividend"),
        d.latestAmt != null ? `${num(safeNumber(d.latestAmt))} ${t("сум/акц.", "so'm/aksiya", "UZS/share")}` : null);
    if (d.yieldPct != null) {
      put(t("Дивидендная доходность", "Dividend daromadliligi", "Dividend yield"),
          `${formatRatio(d.yieldPct, 2, lang)}%`,
          d.latestYear && !d.latestIsRecent
            ? t(`по выплате ${d.latestYear} г. к текущей цене`,
                `${d.latestYear}-yil to'lovi bo'yicha`,
                `on the ${d.latestYear} payout, at the current price`)
            : t("к текущей цене", "joriy narxga", "to current price"));
    }
    put(t("Выплат в истории", "Tarixdagi to'lovlar", "Payouts on record"), count(d.payouts));
    // A yield built on an old payout has to say so ON the block, not only in a
    // tooltip: KSCM's last declaration was 2020 and against today's price it
    // reads 64 %, which nobody would take as historical unless told.
    const divNote = d.latestYear && !d.latestIsRecent
      ? t(`доходность по выплате ${d.latestYear} г. к текущей цене`,
          `daromadlilik ${d.latestYear}-yil to'lovi bo'yicha`,
          `yield on the ${d.latestYear} payout, at the current price`)
      : d.latest?.decision_date ? `${t("решение", "qaror", "declared")} ${d.latest.decision_date}` : null;
    pushBlock("dividends", t("Дивиденды", "Dividendlar", "Dividends"), rows.splice(0, rows.length), divNote);
  }

  // Which of these sit beside the chart and which drop to the row underneath.
  // The split is not cosmetic: the four that stay are what a reader checks
  // AGAINST the chart — the session, the year's range, the multiples and the
  // returns on capital. Дивиденды and Детали are reference, read once, and they
  // were the 436px that made this rail 1521px tall against a 1029px column.
  const wanted = placement === "lower"
    ? new Set(["dividends"])
    : new Set(["session", "range", "valuation", "profitability"]);
  const shown = blocks.filter((b) => wanted.has(b.props["data-block"]));
  if (!shown.length) return null;
  return <div className="company-keystats">{shown}</div>;
}

// Preferred detection, matching the shapes the securities map and the board use.
function isPreferredRow(sec) {
  return sec?.stock_type === "preferred" || sec?.share_type === "preferred" || sec?.is_preferred === true;
}

/**
 * The dividend headline: latest declared payout, its yield, and how many are on
 * record. ONE rule, because the tab and the key-stats rail both state it and a
 * page that answers "последний дивиденд" twice with two numbers is worse than a
 * page that does not answer it at all.
 *
 * `latest` is the newest filing that declared something for THIS share class —
 * openinfo's calendar also carries decisions that declared nothing (Aloqabank
 * files four dated 11.06.2013 alone), and those are not the latest dividend.
 * `payouts` counts filings that declared for EITHER class, which is what the
 * issuer's payout history means.
 */
function dividendSummary(items, { isPreferred, lastPrice } = {}) {
  const rows = Array.isArray(items) ? items : [];
  const amtKey = isPreferred ? "preferred_amount" : "ordinary_amount";
  const latest = rows.find((r) => (r[amtKey] || 0) > 0) || rows[0] || null;
  const latestAmt = latest ? latest[amtKey] : null;
  const yieldPct = (latestAmt && lastPrice) ? (latestAmt / lastPrice) * 100 : null;
  const declared = rows.filter((r) => (r.ordinary_amount || 0) > 0 || (r.preferred_amount || 0) > 0);
  const latestYear = latestAmt && latest?.decision_date ? String(latest.decision_date).slice(0, 4) : null;
  return {
    rows, latest, latestAmt, yieldPct, declared,
    payouts: declared.length,
    latestYear,
    // The last payout is not always a recent one: SQBN's ordinary line was last
    // paid in 2019 while its preferred line still pays every year, so a bare
    // "к текущей цене" would read as this year's yield.
    latestIsRecent: !!latestYear && (new Date().getFullYear() - Number(latestYear)) <= 1,
  };
}

function CompanyOverviewTab({ sec, priceHistory, priceLoading, priceAdjustments, priceRange, onRangeChange, companyData, financials, lang, infoLoading, securityType, isPreferred, industry, marketRow, priceMetrics, metrics12, mult, dividends, lastPrice, watchRail }) {
  const nominalVal = safeNumber(marketRow?.nominal) || null;

  return (
    <div className="company-overview-layout">
      {/* Three columns at full width, MSN's shape: the watchlist on the left,
          the security in the middle, its numbers on the right. Valuation,
          profitability and the session all come from /api/market/multiples and
          the board row, so nothing here is recomputed and nothing can disagree
          with the market table. */}
      <div className="company-hero-grid">
        <div className="company-hero-watch">{watchRail}</div>
        <div className="company-hero-main">
          <div className="company-chart-panel panel">
            {/* The metrics response still decides whether candles mean anything
                here (`quality`) and how long a moving average is (`ma_windows`);
                only its numbers stopped being printed. */}
            <CompanyPriceChart history={priceHistory} loading={priceLoading} range={priceRange} onRangeChange={onRangeChange} adjustments={priceAdjustments} lang={lang}
              quality={priceMetrics?.quality} metricsWindows={priceMetrics?.ma_windows} />
          </div>
          <div className="company-overview-main">
            <h3 className="co-heading">{lang === "ru" ? "О компании" : lang === "uz" ? "Kompaniya haqida" : "About the company"}</h3>
            {sec.company_description ? (
              <>
                <p className="company-description-text">{sec.company_description}</p>
                {sec.source_url && (
                  <a href={sec.source_url} target="_blank" rel="noreferrer" className="wiki-link">
                    {sec.info_source === "wikipedia"
                      ? (lang === "ru" ? "Читать на Википедии →" : lang === "uz" ? "Vikipediyada o'qish →" : "Read on Wikipedia →")
                      : (lang === "ru" ? "Официальный сайт →" : lang === "uz" ? "Rasmiy sayt →" : "Official website →")}
                  </a>
                )}
              </>
            ) : infoLoading ? (
              <div className="company-desc-skeleton" aria-hidden="true">
                <span /><span /><span /><span style={{ width: "62%" }} />
              </div>
            ) : (
              <p className="muted" style={{ fontSize: 14 }}>{lang === "ru" ? "Информация о компании недоступна." : lang === "uz" ? "Kompaniya haqida ma'lumot mavjud emas." : "Company information is currently unavailable."}</p>
            )}
          </div>
        </div>

        {/* Four blocks, sized to end level with the chart and «О компании»
            beside them: 1058px against 1029px. It carried six and ran to
            1521px, which is where the 492px of empty page under the main column
            came from — the void was the rail being long, not the chart being
            short. */}
        <div className="company-overview-sidebar">
          <CompanyKeyStats row={marketRow} sec={sec} metrics12={metrics12} mult={mult}
            dividends={dividends} lastPrice={lastPrice} securityType={securityType} lang={lang}
            placement="rail" />
        </div>
      </div>

      {/* What a reader consults once rather than reads against the chart. Laid
          out in rail-width tracks, not stretched across the page: «Детали» is a
          four-row key/value list and at 1800px its labels and values would sit
          at opposite ends of the screen. */}
      <div className="company-lower-grid">
        <CompanyKeyStats row={marketRow} sec={sec} metrics12={metrics12} mult={mult}
          dividends={dividends} lastPrice={lastPrice} securityType={securityType} lang={lang}
          placement="lower" />
        <div className="co-sidebar-block">
            <h3 className="co-heading">{lang === "ru" ? "Детали" : "Details"}</h3>
            <div className="company-metrics-list">
              {sec.isin && <div className="company-metric-row"><span className="panel-label">ISIN</span><span className="isin-mono">{sec.isin}</span></div>}
              {nominalVal && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Номинал" : lang === "uz" ? "Nominal" : "Nominal"}</span><span>{formatMarketNumber(nominalVal, lang)} UZS</span></div>}
              {industry && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Отрасль" : lang === "uz" ? "Soha" : "Sector"}</span><span>{sectorLabel(lang, industry)}</span></div>}
              {securityType && <div className="company-metric-row"><span className="panel-label">{lang === "ru" ? "Тип" : lang === "uz" ? "Turi" : "Type"}</span><span>{securityType === "bond" ? (lang === "ru" ? "Облигация" : lang === "uz" ? "Obligatsiya" : "Bond") : (lang === "ru" ? "Акция" : lang === "uz" ? "Aksiya" : "Stock")}</span></div>}
              {securityType !== "bond" && (
                <div className="company-metric-row">
                  <span className="panel-label">{lang === "ru" ? "Класс" : lang === "uz" ? "Sinf" : "Class"}</span>
                  <span>{isPreferred ? (lang === "ru" ? "Привилегированная" : lang === "uz" ? "Imtiyozli" : "Preferred") : (lang === "ru" ? "Обыкновенная" : lang === "uz" ? "Oddiy" : "Common")}</span>
                </div>
              )}
          </div>
        </div>
      </div>
    </div>
  );
}

function CompanyReportsTab({ reports, lang }) {
  const forms = [...new Set((reports || []).map((r) => r.report_form))];
  const [form, setForm] = React.useState(forms[0] || null);
  // Keyed on the actual form set, not reports.length: two companies with the
  // same report count but different form types used to keep a stale filter
  // and show "no reports" even though reports existed.
  const formsKey = forms.join("|");
  React.useEffect(() => {
    if (forms.length > 0 && !forms.includes(form)) setForm(forms[0]);
  }, [formsKey]);
  const visible = form ? reports.filter((r) => r.report_form === form) : reports;
  const FORM_LABELS = { NSBU: "НСБУ", MSFO: "МСФО", Audition: lang === "ru" ? "Аудит" : "Audit" };
  return (
    <div>
      {forms.length > 1 && (
        <div className="company-chart-ranges" style={{ marginBottom: 12 }}>
          {forms.map((f) => (
            <button key={f} type="button" className={`range-btn ${form === f ? "active" : ""}`} onClick={() => setForm(f)}>{FORM_LABELS[f] || f}</button>
          ))}
        </div>
      )}
      {visible.length === 0 ? (
        <div className="panel" style={{ padding: 32, textAlign: "center" }}>
          <p className="muted">{lang === "ru" ? "Отчётов не найдено" : "No reports found"}</p>
        </div>
      ) : (
        <div className="company-reports-list">
          {visible.map((r, i) => (
            <div key={i} className="company-report-row panel">
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{r.title || `${r.report_form} ${r.year || ""} ${r.quarter ? `Q${r.quarter}` : ""}`}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {r.period_type} · {r.year}{r.quarter ? ` Q${r.quarter}` : ""} · {r.report_form}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {r.excel_url && <a href={r.excel_url} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>Excel →</a>}
                {r.excel_url_form1 && r.excel_url_form1 !== r.excel_url && <a href={r.excel_url_form1} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>{lang === "ru" ? "Баланс →" : lang === "uz" ? "Balans →" : "Balance →"}</a>}
                {r.pdf_url && !r.pdf_url.includes("/reports/to_pdf") && <a href={r.pdf_url} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>PDF →</a>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// The Финансы tab, on the reference page's shape: sub-tabs across the statement,
// a multi-series chart of the section's headline lines, then a table with one
// column per YEAR and a growth row under each absolute figure.
//
// The series comes from /api/company/{t}/financials — the fact store, which has
// held nine to eleven annual periods per issuer all along and was serving
// nobody. This tab used to show ONE period's five ratios out of the reports
// cache, and «не кешированы» for every issuer whose cache was cold.
//
// No Cash Flow sub-tab: NSBU form 4 is not parsed, so there is no cash-flow
// series to put behind it. An empty fourth tab would look like a loading bug.
const FIN_SECTIONS = [
  {
    key: "income",
    label: ["Прибыли и убытки", "Foyda va zarar", "Income Statement"],
    rows: ["net_revenue", "net_profit"],
    // Percentages get their own block, as on the reference: mixing a margin
    // into a column of sums invites reading 5.62 as five sums.
    margins: ["gross_profit_margin", "ebit_margin", "net_profit_margin"],
    chart: ["net_revenue", "net_profit"],
  },
  {
    key: "balance",
    label: ["Баланс", "Balans", "Balance Sheet"],
    rows: ["total_assets", "total_liabilities", "total_equity"],
    chart: ["total_assets", "total_liabilities", "total_equity"],
  },
  {
    key: "ratios",
    label: ["Коэффициенты", "Koeffitsiyentlar", "Key Ratios"],
    margins: ["roe", "roa", "current_ratio", "quick_ratio", "debt_ratio",
              "debt_to_equity", "total_asset_turnover", "return_to_capital_employed"],
    chart: ["roe", "roa"],
  },
];

const FIN_FIELD_LABELS = {
  net_revenue: ["Выручка", "Tushum", "Revenue"],
  net_profit: ["Чистая прибыль", "Sof foyda", "Net Profit"],
  total_assets: ["Активы", "Aktivlar", "Total Assets"],
  total_liabilities: ["Обязательства", "Majburiyatlar", "Total Liabilities"],
  total_equity: ["Капитал", "Kapital", "Total Equity"],
  gross_profit_margin: ["Валовая маржа", "Yalpi marja", "Gross Margin"],
  ebit_margin: ["EBIT-маржа", "EBIT marja", "EBIT Margin"],
  net_profit_margin: ["Чистая маржа", "Sof marja", "Net Margin"],
  roe: ["ROE", "ROE", "ROE"],
  roa: ["ROA", "ROA", "ROA"],
  current_ratio: ["Текущая ликвидность", "Joriy likvidlik", "Current Ratio"],
  quick_ratio: ["Быстрая ликвидность", "Tez likvidlik", "Quick Ratio"],
  debt_ratio: ["Долг/Активы", "Qarz/Aktivlar", "Debt Ratio"],
  debt_to_equity: ["Долг/Капитал", "Qarz/Kapital", "Debt/Equity"],
  total_asset_turnover: ["Оборачиваемость активов", "Aktivlar aylanmasi", "Asset Turnover"],
  return_to_capital_employed: ["ROCE", "ROCE", "ROCE"],
};

const finLabel = (field, lang) =>
  (FIN_FIELD_LABELS[field] || [field, field, field])[lang === "uz" ? 1 : lang === "en" ? 2 : 0];

// The section's headline lines over time. Deliberately not the price chart: no
// range buttons, no hover — this is a shape, and the table underneath is the data.
function FinancialsChart({ fields, series, periods, lang }) {
  const cols = [...periods].reverse();               // oldest → newest, left → right
  const COLORS = ["#38bdf8", "#f59e0b", "#a855f7"];
  const drawn = fields
    .map((f, i) => ({ f, color: COLORS[i % COLORS.length], s: series[f] }))
    .filter((d) => d.s && cols.some((c) => Number.isFinite(d.s.values[c])));
  if (drawn.length === 0 || cols.length < 2) return null;

  const all = drawn.flatMap((d) => cols.map((c) => d.s.values[c]).filter(Number.isFinite));
  // Zero-based, as on the reference: an axis that starts at its own minimum
  // turns a three-percent move into a cliff.
  const max = Math.max(...all, 0), min = Math.min(...all, 0);
  const span = max - min || 1;
  const W = 820, H = 210, PAD = { t: 12, r: 14, b: 26, l: 70 };
  const x = (i) => PAD.l + (i / Math.max(1, cols.length - 1)) * (W - PAD.l - PAD.r);
  const y = (v) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b);
  const money = drawn[0].s.money;
  const pct = drawn[0].s.unit === "%";
  const axis = (v) => (money ? formatCompactVolume(v, lang)
    : `${formatRatio(v, 1, lang)}${pct ? "%" : ""}`);
  return (
    <div className="fin-chart">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
        {[0, 0.5, 1].map((f, i) => (
          <line key={i} x1={PAD.l} y1={y(min + f * span)} x2={W - PAD.r} y2={y(min + f * span)}
            stroke="currentColor" strokeOpacity="0.16" strokeDasharray="4 6" strokeWidth="0.8" />
        ))}
        {[0, 0.5, 1].map((f, i) => (
          <text key={`l${i}`} x={PAD.l - 8} y={y(min + f * span) + 3.5} textAnchor="end"
            fontSize="10" fill="currentColor" opacity="0.5">{axis(min + f * span)}</text>
        ))}
        {drawn.map((d) => {
          const pts = cols.map((c, i) => ({ i, v: d.s.values[c] })).filter((pt) => Number.isFinite(pt.v));
          if (pts.length < 2) return null;
          const path = pts.map((pt, k) => `${k ? "L" : "M"}${x(pt.i).toFixed(1)},${y(pt.v).toFixed(1)}`).join(" ");
          return <path key={d.f} d={path} fill="none" stroke={d.color} strokeWidth="2"
            strokeLinejoin="round" vectorEffect="non-scaling-stroke" />;
        })}
        {cols.map((c, i) => (
          <text key={c} x={x(i)} y={H - 8} fontSize="10" fill="currentColor" opacity="0.5"
            textAnchor={i === 0 ? "start" : i === cols.length - 1 ? "end" : "middle"}>{c}</text>
        ))}
      </svg>
      <div className="fin-legend">
        {drawn.map((d) => (
          <span key={d.f} className="fin-legend-item">
            <i style={{ background: d.color }} />{finLabel(d.f, lang)}
          </span>
        ))}
      </div>
    </div>
  );
}

function CompanyFinancialsTab({ ratios, series, periods, loading, lang }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [section, setSection] = React.useState("income");

  if (loading) return <div className="chart-loading muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div>;

  const cols = periods || [];
  const has = (f) => series?.[f] && cols.some((p) => Number.isFinite(series[f].values[p]));
  const available = FIN_SECTIONS
    .map((sec) => ({ ...sec, rows: (sec.rows || []).filter(has), margins: (sec.margins || []).filter(has) }))
    .filter((sec) => sec.rows.length + sec.margins.length > 0);

  // Nothing in the fact store. Fall back to the single period the reports cache
  // holds rather than showing an empty tab — it is less, but it is what we have.
  if (available.length === 0) {
    const m = ratios?.metrics || {};
    const legacy = [["ROA", "ROA"], ["ROE", "ROE"],
                    ["net_margin", finLabel("net_profit_margin", lang)],
                    ["debt_ratio", finLabel("debt_ratio", lang)],
                    ["debt_to_equity", finLabel("debt_to_equity", lang)]]
      .filter(([k]) => m[k] != null);
    if (legacy.length === 0) return (
      <div className="panel" style={{ padding: 32, textAlign: "center" }}>
        <p className="muted">{t("Финансовые показатели не опубликованы",
                                "Moliyaviy korsatkichlar elon qilinmagan",
                                "No financial indicators published")}</p>
      </div>
    );
    return (
      <div className="panel" style={{ padding: "16px 20px" }}>
        {ratios?.year && (
          <div className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
            {t("Последние данные", "Songgi malumotlar", "Latest")}: {ratios.year}
            {ratios.quarter ? ` Q${ratios.quarter}` : ""}
          </div>
        )}
        <div className="company-metrics-list">
          {legacy.map(([k, l]) => (
            <div key={k} className="company-metric-row">
              <span className="panel-label">{l}</span>
              <span className="company-metric-val">{formatRatio(m[k], 2, lang)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  const active = available.find((sec) => sec.key === section) || available[0];

  const growth = (f, i) => {
    const v = series[f].values[cols[i]], prev = series[f].values[cols[i + 1]];
    if (!Number.isFinite(v) || !Number.isFinite(prev) || prev === 0) return null;
    return ((v - prev) / Math.abs(prev)) * 100;
  };
  // The unit comes from the server, which owns the scale contract: money in
  // full UZS, every margin already converted to percent, plain coefficients
  // left alone. Nothing here decides what a number means.
  const cell = (f, p) => {
    const v = series[f].values[p];
    if (!Number.isFinite(v)) return "—";
    if (series[f].money) return formatCompactVolume(v, lang);
    const suffix = series[f].unit === "%" ? "%" : "";
    return `${formatRatio(v, 2, lang)}${suffix}`;
  };

  const rowsBlock = (fields, withGrowth) => fields.map((f) => (
    <React.Fragment key={f}>
      <tr>
        <th scope="row">{finLabel(f, lang)}</th>
        {cols.map((p) => <td key={p} className="num">{cell(f, p)}</td>)}
      </tr>
      {withGrowth && (
        <tr className="fin-growth">
          <th scope="row">{t("Рост г/г", "Osish y/y", "Growth YoY")}</th>
          {cols.map((p, i) => {
            const g = growth(f, i);
            return (
              <td key={p} className={`num ${g == null ? "" : g >= 0 ? "pos" : "neg"}`}>
                {g == null ? "—" : `${g > 0 ? "+" : ""}${g.toFixed(2)}%`}
              </td>
            );
          })}
        </tr>
      )}
    </React.Fragment>
  ));

  return (
    <div className="company-financials">
      <div className="fin-subtabs">
        {available.map((sec) => (
          <button key={sec.key} type="button"
            className={`fin-subtab ${active.key === sec.key ? "active" : ""}`}
            onClick={() => setSection(sec.key)}>
            {sec.label[lang === "uz" ? 1 : lang === "en" ? 2 : 0]}
          </button>
        ))}
      </div>

      <div className="panel fin-panel">
        <FinancialsChart fields={(active.chart || []).filter(has)} series={series} periods={cols} lang={lang} />

        <div className="fin-table-wrap">
          <table className="fin-table">
            <thead>
              <tr>
                <th scope="col">{t("Годовые данные", "Yillik malumotlar", "Fiscal year")}</th>
                {cols.map((p) => <th key={p} scope="col" className="num">{p}</th>)}
              </tr>
            </thead>
            <tbody>
              {rowsBlock(active.rows || [], true)}
              {(active.margins || []).length > 0 && (active.rows || []).length > 0 && (
                <tr className="fin-section-row">
                  <th scope="row" colSpan={cols.length + 1}>
                    {t("Маржинальность", "Marjinallik", "Margin Analysis")}
                  </th>
                </tr>
              )}
              {rowsBlock(active.margins || [], false)}
            </tbody>
          </table>
        </div>

        <p className="fin-note muted">
          {t("Суммы в сумах, по годовым отчётам эмитента. Коэффициенты — в тех единицах, в которых они опубликованы.",
             "Summalar somda, emitentning yillik hisobotlari boyicha.",
             "Sums in UZS, from the issuer's annual filings. Ratios in the units they were published in.")}
        </p>
      </div>
    </div>
  );
}

function CompanyDividendsTab({ items, loading, lang, isPreferred, lastPrice }) {
  // openinfo's calendar also carries decisions that declared nothing — Aloqabank
  // files four of them dated 11.06.2013 alone, and they render as rows of dashes
  // that read like a broken table. They stay available behind the toggle, because
  // "the meeting resolved to pay nothing" is an answer to the question the tab asks.
  const [showSilent, setShowSilent] = React.useState(false);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const locale = lang === "en" ? "en-US" : "ru-RU";
  const fmt = (v) => v == null ? "—" : Number(v).toLocaleString(locale, { maximumFractionDigits: 2 });
  const fmtDate = (d) => d ? new Date(d).toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric" }) : "—";

  if (loading) return <div className="chart-loading muted">{t("Загрузка...", "Yuklanmoqda...", "Loading...")}</div>;
  const rows = items || [];
  if (rows.length === 0) return (
    <div className="panel" style={{ padding: 32, textAlign: "center" }}>
      <p className="muted">{t("Дивиденды не объявлялись", "Dividendlar e'lon qilinmagan", "No dividends on record")}</p>
    </div>
  );

  // Same rule as the key-stats rail — see dividendSummary().
  const { latest, latestAmt, yieldPct, declared, payouts, latestYear, latestIsRecent } =
    dividendSummary(rows, { isPreferred, lastPrice });
  // O'zsanoatqurilishbank files 92 calendar entries and declared a payout in 9 of
  // them. When an issuer declared nothing at all there is nothing to fold away —
  // the silent filings ARE the record, so they stay on screen.
  const silent = payouts === 0 ? 0 : rows.length - payouts;
  const visible = (showSilent || payouts === 0) ? rows : declared;

  return (
    <div className="company-dividends">
      <div className="dividend-cards">
        <div className="dividend-card panel">
          <div className="dividend-card-label">{t("Последний дивиденд", "Oxirgi dividend", "Latest dividend")}</div>
          <div className="dividend-card-val">{fmt(latestAmt)} <span className="dividend-card-unit">{t("сум/акц.", "so'm/aksiya", "UZS/sh")}</span></div>
          {latest && <div className="muted" style={{ fontSize: 12 }}>{fmtDate(latest.decision_date)}</div>}
        </div>
        {yieldPct != null && (
          <div className="dividend-card panel">
            <div className="dividend-card-label">{t("Дивидендная доходность", "Dividend daromadliligi", "Dividend yield")}</div>
            <div className="dividend-card-val">{yieldPct.toFixed(2)}%</div>
            {/* The last payout is not always a recent one: SQBN's ordinary line was
                last paid in 2019 while its preferred line still pays every year. A
                bare "к текущей цене" then reads as this year's yield, so the caption
                names the year the figure actually comes from. */}
            <div className="muted" style={{ fontSize: 12 }}>
              {latestYear && !latestIsRecent
                ? t(`по выплате ${latestYear} г. к текущей цене`, `${latestYear}-yil to'lovi bo'yicha`, `on the ${latestYear} payout, at the current price`)
                : t("к текущей цене", "joriy narxga", "to current price")}
            </div>
          </div>
        )}
        <div className="dividend-card panel">
          <div className="dividend-card-label">{t("Выплат в истории", "Tarixdagi to'lovlar", "Payouts on record")}</div>
          <div className="dividend-card-val">{payouts}</div>
        </div>
      </div>
      <div className="dividend-table-wrap panel">
        <table className="dividend-table">
          <thead>
            <tr>
              <th>{t("Дата решения", "Qaror sanasi", "Decision date")}</th>
              <th className="dividend-num">{t("Обыкн., сум", "Oddiy, so'm", "Ordinary, UZS")}</th>
              <th className="dividend-num">%</th>
              <th className="dividend-num">{t("Прив., сум", "Imtiyozli, so'm", "Preferred, UZS")}</th>
              <th className="dividend-num">%</th>
              <th>{t("Реестр / выплата", "Reyestr / to'lov", "Record / payment")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => (
              <tr key={i}>
                <td>{fmtDate(r.decision_date)}</td>
                <td className="dividend-num">{r.ordinary_amount ? fmt(r.ordinary_amount) : "—"}</td>
                <td className="dividend-num muted">{r.ordinary_percent ? `${fmt(r.ordinary_percent)}%` : "—"}</td>
                <td className="dividend-num">{r.preferred_amount ? fmt(r.preferred_amount) : "—"}</td>
                <td className="dividend-num muted">{r.preferred_percent ? `${fmt(r.preferred_percent)}%` : "—"}</td>
                {/* The payment window belongs to the share class being viewed: a
                    filing declares a separate one for the preferred line, and a
                    preferred page showing the ordinary window dates the wrong payout. */}
                <td className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>{(() => {
                  const start = isPreferred ? (r.preferred_start || r.ordinary_start) : r.ordinary_start;
                  const end = isPreferred ? (r.preferred_end || r.ordinary_end) : r.ordinary_end;
                  return (start || end) ? `${fmtDate(start)} – ${fmtDate(end)}` : "—";
                })()}</td>
                <td>{r.link && <a href={r.link} target="_blank" rel="noreferrer" className="ghost-btn" style={{ fontSize: 12 }}>→</a>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {silent > 0 && (
        <button type="button" className="ghost-btn" style={{ fontSize: 12, marginTop: 10 }}
                onClick={() => setShowSilent((v) => !v)}>
          {showSilent
            ? t("Скрыть решения без выплаты", "To'lovsiz qarorlarni yashirish", "Hide no-payout decisions")
            : t(`Показать ещё ${silent} решений без выплаты`, `Yana ${silent} ta to'lovsiz qaror`, `Show ${silent} more no-payout decisions`)}
        </button>
      )}
      {yieldPct != null && (
        <p className="muted" style={{ fontSize: 11, marginTop: 10 }}>
          {t("Доходность рассчитана по последней цене и без учёта даты закрытия реестра.", "Daromadlilik oxirgi narx bo'yicha hisoblangan.", "Yield is computed against the latest price, before the record date.")}
        </p>
      )}
    </div>
  );
}

function CompanyPage({ ticker, securitiesMap, language, onBack, onAnalyze, onOpenCompany, marketRows, financials, tradeStats, favoriteTickers, onToggleFavorite, signedIn }) {
  const lang = normalizeLanguage(language);
  const [tab, setTab] = React.useState("overview");
  // Issuer-level multiples, straight from the endpoint the market board reads.
  const [mult, setMult] = React.useState(null);
  // A SECOND metrics call, pinned to twelve months. The main one follows the
  // period button by design (ТЗ §5), so reading the 52-week range off it would
  // relabel a one-month high as a yearly one the moment somebody pressed «1М».
  const [metrics12, setMetrics12] = React.useState(null);
  const [priceHistory, setPriceHistory] = React.useState(null);
  // Non-empty only for a series that spans a split or a bonus issue — the chart has to
  // say the older prices were restated, or they read as wrong against uzse.uz.
  const [priceAdjustments, setPriceAdjustments] = React.useState([]);
  // The button's identity, not a month count: 1Н and 1М both fetch one month,
  // and YTD's month count moves through the year. `chartRangeMonths` turns it
  // into what the endpoint understands.
  const [priceRange, setPriceRange] = React.useState("1y");
  const priceMonths = chartRangeMonths(priceRange);
  const [priceLoading, setPriceLoading] = React.useState(false);
  // Window + absolute price metrics from /api/company/{ticker}/metrics.
  const [metrics, setMetrics] = React.useState(null);
  const [secInfo, setSecInfo] = React.useState((securitiesMap || {})[ticker] || null);
  const [infoLoading, setInfoLoading] = React.useState(false);
  const [companyData, setCompanyData] = React.useState(null);
  const [dividends, setDividends] = React.useState(null);
  // The issuer's annual series (fact store). Lazy: only the Финансы tab
  // reads it, and most visits never open that tab.
  const [finSeries, setFinSeries] = React.useState(null);
  const [finLoading, setFinLoading] = React.useState(false);
  const [divLoading, setDivLoading] = React.useState(false);

  // Failed requests must be visible and retryable: every fetch below reports
  // an error state instead of silently leaving the page blank, and an `alive`
  // guard keeps a late response for a previous ticker from overwriting state.
  const [priceError, setPriceError] = React.useState(false);
  const [priceRetry, setPriceRetry] = React.useState(0);
  const [companyDataError, setCompanyDataError] = React.useState(false);
  const [companyDataRetry, setCompanyDataRetry] = React.useState(0);

  // Every board row, reconciled against the stored day statistics exactly as the
  // market table does it — the watch rail quotes other securities and must quote
  // them the way the board does. Computed here, above the effects, because the
  // sparkline request is keyed on which tickers the rail will show.
  const preparedRows = React.useMemo(() => {
    const day = latestTradeStatsDay(tradeStats || {});
    return (marketRows || []).map(enrichMarketStock)
      .map((r) => applyTradeStats(r, tradeStats || {}, day));
  }, [marketRows, tradeStats]);
  const railTickers = React.useMemo(() => {
    const { favRows, bySector, movers } = watchRailLists({
      ticker, rows: preparedRows, securitiesMap, favorites: favoriteTickers,
    });
    return [...new Set([...favRows, ...bySector, ...movers]
      .map((r) => String(r.ticker || "").toUpperCase()))].sort();
  }, [ticker, preparedRows, securitiesMap, favoriteTickers]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setPriceLoading(true);
    setPriceError(false);
    fetch(`/api/price-history/${encodeURIComponent(ticker)}?months=${priceMonths}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) {
          setPriceHistory(d.points || []);
          setPriceAdjustments(d.adjustments || []);
        } else setPriceError(true);
      })
      .catch(() => { if (alive) setPriceError(true); })
      .finally(() => { if (alive) setPriceLoading(false); });
    return () => { alive = false; };
  }, [ticker, priceMonths, priceRetry]);

  // Metrics are the server's job (ТЗ §3, second principle: one calc layer, and
  // the screen is not one of its implementations). Since the statistics strip
  // was removed this page reads only `quality` — whether the security trades
  // often enough to be drawn as a slope rather than a step — and `ma_windows`. The
  // response still carries the full window/absolute contract for the auditor,
  // the exports and the paid analysis.
  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/metrics?months=${priceMonths}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setMetrics(d.ok ? d : null); })
      .catch(() => { if (alive) setMetrics(null); });
    return () => { alive = false; };
  }, [ticker, priceMonths, priceRetry]);

  // Dividends are no longer lazy: the key-stats rail states the last payout and
  // its yield on the Обзор tab, so waiting for the Дивиденды tab to be opened
  // would leave the rail permanently short of the one figure an equity holder
  // opens the page for.
  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setDividends(null);
    setDivLoading(true);
    fetch(`/api/dividends/${encodeURIComponent(ticker)}`)
      .then((r) => r.json())
      .then((d) => { if (alive) setDividends(d.ok ? (d.items || []) : []); })
      .catch(() => { if (alive) setDividends([]); })
      .finally(() => { if (alive) setDivLoading(false); });
    return () => { alive = false; };
  }, [ticker]);

  React.useEffect(() => { setFinSeries(null); }, [ticker]);
  React.useEffect(() => {
    if (!ticker || tab !== "financials" || finSeries !== null) return undefined;
    let alive = true;
    setFinLoading(true);
    fetch(`/api/company/${encodeURIComponent(ticker)}/financials`)
      .then((r) => r.json())
      .then((d) => { if (alive) setFinSeries(d.ok ? d : { periods: [], series: {} }); })
      .catch(() => { if (alive) setFinSeries({ periods: [], series: {} }); })
      .finally(() => { if (alive) setFinLoading(false); });
    return () => { alive = false; };
  }, [ticker, tab, finSeries]);

  // ТЗ §8: the server owns this arithmetic, per ISSUER, with the auditor's
  // blocking findings already applied. A failure leaves `mult` null and the rail
  // simply omits the valuation rows — it never falls back to computing them.
  React.useEffect(() => {
    let alive = true;
    fetch("/api/market/multiples")
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const up = String(ticker || "").toUpperCase();
        setMult((d.items || []).find((it) => String(it.ticker || "").toUpperCase() === up) || null);
      })
      .catch(() => { if (alive) setMult(null); });
    return () => { alive = false; };
  }, [ticker]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/metrics?months=12`)
      .then((r) => r.json())
      .then((d) => { if (alive) setMetrics12(d.ok ? d : null); })
      .catch(() => { if (alive) setMetrics12(null); });
    return () => { alive = false; };
  }, [ticker, priceRetry]);

  // One request for every sparkline in the watch rail. Keyed on the ticker LIST,
  // so it refetches when the lists change and not when a price ticks — the whole
  // reason this data is stored rather than fetched per row is to keep a list of
  // securities from costing one upstream request each.
  const [railSeries, setRailSeries] = React.useState({});
  const railKey = railTickers.join(",");
  React.useEffect(() => {
    if (!railKey) return undefined;
    let alive = true;
    fetch(`/api/quotes/series?tickers=${encodeURIComponent(railKey)}&days=30`)
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setRailSeries(d.series || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [railKey]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    const local = (securitiesMap || {})[ticker];
    if (local) setSecInfo(local);
    setInfoLoading(true);
    fetch(`/api/securities/${encodeURIComponent(ticker)}/info?language=${lang}`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d.ok) return;
        setSecInfo({
          ...(d.security || {}),
          company_description: d.wiki?.extract || d.security?.company_description || null,
          source_url: d.wiki?.page_url || d.security?.source_url || null,
          wiki_title: d.wiki?.title || null,
          info_source: d.wiki?.source || (d.wiki?.extract ? "wikipedia" : null),
        });
      })
      .catch(() => {})
      .finally(() => { if (alive) setInfoLoading(false); });
    return () => { alive = false; };
  }, [ticker, lang]);

  React.useEffect(() => {
    if (!ticker) return undefined;
    let alive = true;
    setCompanyDataError(false);
    fetch(`/api/catalog/company/${encodeURIComponent(ticker)}/reports`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.ok) setCompanyData(d);
        else setCompanyDataError(true);
      })
      .catch(() => { if (alive) setCompanyDataError(true); });
    return () => { alive = false; };
  }, [ticker, companyDataRetry]);

  if (!ticker) return null;
  const sec = secInfo || (securitiesMap || {})[ticker] || {};
  // The header's own row. It used to derive its move as a bare
  // `last_price - close_price`, which is the two-sessions-in-one-day defect
  // previousClose() exists to prevent — see applyTradeStats.
  const marketRow = preparedRows.find((r) => (r.ticker || "").toUpperCase() === ticker.toUpperCase()) || null;
  // Company-level financials for P/E and P/B; mirror the preferred-sibling fallback (TKDM <-> TKDMP).
  const companyFin = (() => {
    const f = financials || {};
    const up = ticker.toUpperCase();
    return f[up] || f[up.endsWith("P") ? up.slice(0, -1) : `${up}P`] || null;
  })();
  const lastPrice = marketRow?.lastPrice ?? marketRow?.last_price ?? sec.last_price ?? null;
  // The move the reconciled row settled on. Only when there is no board row at
  // all does the header fall back to differencing the securities-map closes —
  // and then it has no session to check them against, so it says nothing rather
  // than publishing a difference between two undated prices.
  const priceChange = marketRow
    ? (Number.isFinite(marketRow.changeValue) && Number.isFinite(marketRow.changePercent)
        ? { value: marketRow.changeValue, pct: marketRow.changePercent }
        : null)
    : null;
  // The securities map uses `type`/`share_type`/`is_preferred`/`sector`; some
  // callers pass `security_type`/`stock_type`/`industry`. Accept both shapes.
  const securityType = sec.security_type || sec.type;
  const isPreferred = sec.stock_type === "preferred" || sec.share_type === "preferred" || sec.is_preferred === true;
  const industry = sec.industry || sec.sector;
  const typeLabel = securityType === "bond"
    ? (lang === "ru" ? "Облигация" : lang === "uz" ? "Obligatsiya" : "Bond")
    : isPreferred
      ? (lang === "ru" ? "Прив. акция" : lang === "uz" ? "Imtiyozli" : "Preferred")
      : (lang === "ru" ? "Обыкн. акция" : lang === "uz" ? "Oddiy aksiya" : "Common Share");
  const TABS = [
    { key: "overview", label: lang === "ru" ? "Обзор" : lang === "uz" ? "Umumiy" : "Overview" },
    { key: "chart", label: lang === "ru" ? "История цен" : lang === "uz" ? "Narxlar tarixi" : "Price History" },
    ...(securityType !== "bond" ? [{ key: "dividends", label: lang === "ru" ? "Дивиденды" : lang === "uz" ? "Dividendlar" : "Dividends" }] : []),
    { key: "reports", label: lang === "ru" ? "Отчёты" : lang === "uz" ? "Hisobotlar" : "Reports" },
    { key: "financials", label: lang === "ru" ? "Финансы" : lang === "uz" ? "Moliya" : "Financials" },
  ];
  return (
    <div className="company-page">
      <div className="company-page-header">
        <button className="company-page-back" type="button" onClick={onBack}>
          ← {lang === "ru" ? "Назад" : lang === "uz" ? "Orqaga" : "Back"}
        </button>
        <div className="company-page-hero">
          <CompanyLogo logo={sec.company_logo_url || sec.logo_url} name={sec.company_name || sec.name || ticker} ticker={ticker} />
          <div className="company-page-title">
            <h1>{sec.company_name || sec.name || ticker}</h1>
            <div className="company-page-meta">
              <span className="company-page-ticker">{ticker}</span>
              {sec.isin && <span className="muted" style={{ fontSize: 12 }}>{sec.isin}</span>}
              <span className="company-type-badge">{typeLabel}</span>
              {industry && <span className="sector-chip active" style={{ fontSize: 11, padding: "2px 10px" }}>{sectorLabel(lang, industry)}</span>}
            </div>
          </div>
          <div className="company-page-price">
            {lastPrice != null ? (
              <>
                <div className="company-page-price-val">{Number(lastPrice).toLocaleString("ru-RU")} сум</div>
                {priceChange && (
                  <div className={`company-page-price-change ${priceChange.value >= 0 ? "pos" : "neg"}`}>
                    {priceChange.value >= 0 ? "+" : ""}{priceChange.value.toFixed(2)} ({priceChange.pct >= 0 ? "+" : ""}{priceChange.pct.toFixed(2)}%)
                  </div>
                )}
              </>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>{lang === "ru" ? "Нет данных" : "No data"}</div>
            )}
            <button className="primary-btn" type="button" style={{ marginTop: 8 }} onClick={() => onAnalyze(ticker)}>
              {lang === "ru" ? "Запустить анализ" : lang === "uz" ? "Tahlil qilish" : "Run Analysis"}
            </button>
          </div>
        </div>
        <div className="company-page-tabs">
          {TABS.map((t) => (
            <button key={t.key} type="button"
              className={`company-tab-btn ${tab === t.key ? "active" : ""}`}
              onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      <div className="company-page-body">
        {companyDataError && (
          <div className="panel" style={{ padding: "12px 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: "1px solid rgba(220, 80, 80, 0.5)" }}>
            <span style={{ fontSize: 13 }}>
              {lang === "ru" ? "Не удалось загрузить отчёты и показатели компании."
                : lang === "uz" ? "Kompaniya hisobotlari va ko'rsatkichlarini yuklab bo'lmadi."
                : "Failed to load company reports and metrics."}
            </span>
            <button className="primary-btn" type="button" style={{ padding: "6px 14px", fontSize: 13 }}
              onClick={() => setCompanyDataRetry((n) => n + 1)}>
              {lang === "ru" ? "Повторить" : lang === "uz" ? "Qayta urinish" : "Retry"}
            </button>
          </div>
        )}
        {priceError && (tab === "overview" || tab === "chart") && (
          <div className="panel" style={{ padding: "12px 16px", marginBottom: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, border: "1px solid rgba(220, 80, 80, 0.5)" }}>
            <span style={{ fontSize: 13 }}>
              {lang === "ru" ? "Не удалось загрузить историю цен."
                : lang === "uz" ? "Narxlar tarixini yuklab bo'lmadi."
                : "Failed to load price history."}
            </span>
            <button className="primary-btn" type="button" style={{ padding: "6px 14px", fontSize: 13 }}
              onClick={() => setPriceRetry((n) => n + 1)}>
              {lang === "ru" ? "Повторить" : lang === "uz" ? "Qayta urinish" : "Retry"}
            </button>
          </div>
        )}
        {tab === "overview" && (
          <CompanyOverviewTab sec={sec} priceHistory={priceHistory} priceLoading={priceLoading}
            priceAdjustments={priceAdjustments}
            priceRange={priceRange} onRangeChange={setPriceRange}
            securityType={securityType} isPreferred={isPreferred} industry={industry}
            marketRow={marketRow} companyData={companyData} financials={companyFin} lang={lang} infoLoading={infoLoading}
            priceMetrics={metrics}
            metrics12={metrics12} mult={mult} dividends={dividends} lastPrice={lastPrice}
            watchRail={
              <CompanyWatchRail ticker={ticker} rows={preparedRows} securitiesMap={securitiesMap}
                series={railSeries} favorites={favoriteTickers} onToggleFavorite={onToggleFavorite}
                onOpen={onOpenCompany} signedIn={signedIn} lang={lang} />
            } />
        )}
        {tab === "chart" && (
          <div className="panel" style={{ padding: 24 }}>
            <h3 className="section-heading" style={{ marginBottom: 16 }}>{lang === "ru" ? `История цен — ${ticker}` : `Price History — ${ticker}`}</h3>
            <CompanyPriceChart history={priceHistory} loading={priceLoading} range={priceRange} onRangeChange={setPriceRange} lang={lang}
              quality={metrics?.quality} metricsWindows={metrics?.ma_windows} />
          </div>
        )}
        {tab === "dividends" && (
          <CompanyDividendsTab items={dividends} loading={divLoading} lang={lang} isPreferred={isPreferred} lastPrice={lastPrice} />
        )}
        {tab === "reports" && (
          <CompanyReportsTab reports={companyData?.reports || []} lang={lang} />
        )}
        {tab === "financials" && (
          <CompanyFinancialsTab ratios={companyData?.ratios || {}} lang={lang}
            series={finSeries?.series || {}} periods={finSeries?.periods || []}
            loading={finLoading && finSeries === null} />
        )}
      </div>
    </div>
  );
}

function CompanyInfoPanel({ ticker, secInfo, wikiInfo, language, onClose, loading }) {
  const lang = normalizeLanguage(language);
  if (!ticker) return null;
  const name = secInfo?.name || ticker;
  const logo = secInfo?.logo_url;
  const sector = secInfo?.sector;
  const isin = secInfo?.isin;
  const isPreferred = secInfo?.is_preferred;
  const secType = secInfo?.type;

  const sectorText = sector ? sectorLabel(lang, sector) : null;
  const typeLabels = { stock: lang === "en" ? "Stock" : lang === "uz" ? "Aksiya" : "Акция", bond: lang === "en" ? "Bond" : lang === "uz" ? "Obligatsiya" : "Облигация" };

  return (
    <div className="company-panel-overlay" onClick={onClose}>
      <aside className="company-info-panel" onClick={(e) => e.stopPropagation()}>
        <button className="company-panel-close" type="button" onClick={onClose}>×</button>
        <div className="company-panel-header">
          <CompanyLogo logo={logo} name={name} ticker={ticker} />
          <div className="company-panel-title">
            <h2>{name}</h2>
            <div className="company-panel-meta">
              <span className="status-badge muted">{ticker}</span>
              {isin && <span className="status-badge muted">{isin}</span>}
              {sectorText && <span className="status-badge">{sectorText}</span>}
              {secType && <span className="status-badge muted">{typeLabels[secType] || secType}</span>}
              {isPreferred && <span className="status-badge muted">{lang === "en" ? "Preferred" : lang === "uz" ? "Imtiyozli" : "Привилег."}</span>}
            </div>
          </div>
        </div>
        <div className="company-panel-body">
          {loading ? (
            <p className="company-panel-wiki muted">{lang === "en" ? "Loading..." : lang === "uz" ? "Yuklanmoqda..." : "Загрузка..."}</p>
          ) : wikiInfo?.extract ? (
            <>
              <p className="company-panel-wiki">{wikiInfo.extract}</p>
              {wikiInfo.page_url && (
                <a href={wikiInfo.page_url} target="_blank" rel="noreferrer" className="company-panel-wiki-link">
                  {wikiInfo.source === "wikipedia"
                    ? (lang === "en" ? "Read on Wikipedia →" : lang === "uz" ? "Vikipediyada o'qish →" : "Читать на Википедии →")
                    : (lang === "en" ? "Official website →" : lang === "uz" ? "Rasmiy sayt →" : "Официальный сайт →")}
                </a>
              )}
            </>
          ) : (
            <p className="company-panel-wiki muted">
              {lang === "en" ? "No description available." : lang === "uz" ? "Tavsif mavjud emas." : "Описание недоступно."}
            </p>
          )}
          {secInfo?.last_price != null && (
            <div className="company-panel-price">
              <span className="company-panel-price-label">{lang === "en" ? "Last price" : lang === "uz" ? "Oxirgi narx" : "Последняя цена"}</span>
              <strong className="company-panel-price-value">{Number(secInfo.last_price).toLocaleString(lang === "en" ? "en-US" : "ru-RU")} сум</strong>
              {secInfo.last_trade_date && <span className="muted">{secInfo.last_trade_date}</span>}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

// A floating horizontal scrollbar for the wide market table, clung to the bottom of
// the table's visible area (the screen bottom while the table runs off the fold).
// The table's own scroll container (.market-table-wrap) has no height cap, so its
// native horizontal scrollbar sits at the very bottom of a tall table — unreachable
// without scrolling the whole page down. We hide that native bar (see CSS) and mirror
// it here so it's always reachable. Rendered via a body portal because the table's
// ancestors (.market-board overflow:hidden + backdrop-filter, .app-shell-wrap
// overflow:hidden) would otherwise clip/mis-anchor a position:fixed element.
function MarketFloatScroll({ wrapRef, colSignature, rowCount, loading }) {
  const trackRef = useRef(null);
  const [box, setBox] = useState({ show: false, left: 0, width: 0, top: 0 });
  const [thumb, setThumb] = useState({ width: 0, left: 0 });
  const drag = useRef(null);
  const MIN_THUMB = 40;

  // Track geometry + thumb size/position, derived from the table's live scroll state.
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    let raf = 0;
    const measure = () => {
      raf = 0;
      const el = wrapRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const sw = el.scrollWidth, cw = el.clientWidth;
      const max = sw - cw;
      // Clamp to the table's VISIBLE rectangle: the wrap can extend past the viewport
      // (the layout has a min-width and .app-shell-wrap clips the overflow).
      const left = Math.max(r.left, 0);
      const right = Math.min(r.right, window.innerWidth);
      const trackW = right - left;
      // The wrap's native bar is hidden (see CSS) — this floating bar is the only
      // horizontal scrollbar. It clings to the viewport bottom while the table runs
      // below the fold, and to the table's own bottom edge once the end scrolls into
      // view, so exactly one bar is visible whenever the table is on screen.
      const inView = max > 1 && r.top < window.innerHeight && r.bottom > 40 && trackW > 40;
      if (!inView) {
        setBox((b) => (b.show ? { ...b, show: false } : b));
        return;
      }
      const BAR = 14;
      const top = Math.min(window.innerHeight, r.bottom) - BAR;
      setBox({ show: true, left, width: trackW, top });
      const tw = Math.max(trackW * (cw / sw), MIN_THUMB);
      const tl = max > 0 ? (el.scrollLeft / max) * (trackW - tw) : 0;
      setThumb({ width: tw, left: tl });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();
    // capture:true reaches window for the wrap's own (non-bubbling) horizontal scroll too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    // Table scrolled (trackpad / Shift+wheel / keyboard) -> re-derive the thumb.
    wrap.addEventListener("scroll", schedule, { passive: true });
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      wrap.removeEventListener("scroll", schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
    // colSignature/rowCount/loading: ResizeObserver won't fire when only scrollWidth changes.
  }, [wrapRef, colSignature, rowCount, loading]);

  // Drag the thumb -> the table scrolls (mapped by the thumb's travel range).
  useEffect(() => {
    const onMove = (e) => {
      const d = drag.current;
      const el = wrapRef.current;
      if (!d || !el) return;
      const denom = d.trackW - d.thumbW;
      const max = el.scrollWidth - el.clientWidth;
      el.scrollLeft = denom > 0 ? d.startScroll + ((e.clientX - d.startX) / denom) * max : d.startScroll;
    };
    const onUp = () => { if (drag.current) { drag.current = null; document.body.classList.remove("market-float-dragging"); } };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  }, [wrapRef]);

  const onThumbDown = (e) => {
    const el = wrapRef.current;
    if (!el) return;
    e.preventDefault();
    drag.current = { startX: e.clientX, startScroll: el.scrollLeft, trackW: box.width, thumbW: thumb.width };
    document.body.classList.add("market-float-dragging");
  };
  const onTrackDown = (e) => {
    if (e.target !== trackRef.current) return; // ignore clicks on the thumb
    const el = wrapRef.current;
    if (!el) return;
    const clickX = e.clientX - trackRef.current.getBoundingClientRect().left;
    const dir = clickX < thumb.left ? -1 : 1; // page toward the click
    el.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: "smooth" });
  };

  return createPortal(
    <div
      className="market-float-scroll"
      ref={trackRef}
      onPointerDown={onTrackDown}
      aria-hidden="true"
      style={{ display: box.show ? "block" : "none", left: box.left, width: box.width, top: box.top }}
    >
      <div className="market-float-thumb" style={{ width: thumb.width, left: thumb.left }} onPointerDown={onThumbDown} />
    </div>,
    document.body
  );
}

// The column picker ("Обзор / Объёмы / Фин. показатели / Мультипликаторы").
// It used to be an absolutely-positioned child of the toolbar, which meant it
// rode the page up on the first scroll gesture and — now that the toolbar is
// sticky and .market-board clips — would have been cut off at the board edge.
// Portaled to <body> instead: a fixed popover re-anchored to its button on
// every scroll/resize, and on a phone a bottom sheet with its own scrollport,
// so a thumb drag moves the list of columns and not the page behind it.
/**
 * The ⓘ beside an economic label: what this term means, on hover, at the point
 * the reader met it. Definitions come from lib/glossary.js by id.
 *
 * It is portaled to <body> for the same reason the column picker is — inside the
 * board's horizontal scrollport a positioned child is clipped by the scroll box,
 * so a tooltip on the rightmost header would be cut in half or scroll away from
 * the header that opened it.
 *
 * Hover opens it on a mouse; tap toggles it on a phone, where there is no hover
 * at all. Every pointer event stops at the marker: the header underneath sorts on
 * click and drags to reorder, and asking what a column means must do neither.
 */
function TermInfo({ termId, lang, label }) {
  const entry = termFor(termId, lang);
  const btnRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState(null);

  useLayoutEffect(() => {
    if (!open) { setPos(null); return undefined; }
    let raf = 0;
    const place = () => {
      raf = 0;
      const btn = btnRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      const width = Math.min(320, window.innerWidth - 24);
      const left = Math.max(12, Math.min(r.left + r.width / 2 - width / 2, window.innerWidth - width - 12));
      // Below the marker by default; above it when the viewport bottom is closer
      // than the tooltip is tall, so it is never half off-screen.
      const below = window.innerHeight - r.bottom;
      setPos({ left, width, top: below > 190 ? r.bottom + 8 : null, bottom: below > 190 ? null : window.innerHeight - r.top + 8 });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(place); };
    place();
    // capture:true — the table's own scrollport does not bubble its scroll event.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    const onDocDown = (e) => { if (!btnRef.current || !btnRef.current.contains(e.target)) setOpen(false); };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDocDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDocDown);
    };
  }, [open]);

  // A term with no entry yet renders nothing rather than an ⓘ that explains nothing.
  if (!entry) return null;

  const stop = (e) => { e.stopPropagation(); };
  return (
    <>
      <button
        type="button"
        ref={btnRef}
        className={`term-info-btn${open ? " open" : ""}`}
        aria-label={`${label || entry.term} — ${lang === "en" ? "what this means" : lang === "uz" ? "bu nimani anglatadi" : "что это значит"}`}
        aria-expanded={open}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen((v) => !v); }}
        onMouseDown={stop}
        onPointerDown={stop}
        onTouchStart={stop}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); } }}
        onDragStart={(e) => { e.preventDefault(); e.stopPropagation(); }}
      >ℹ</button>
      {open && pos && createPortal(
        <div
          className="term-tooltip"
          role="tooltip"
          style={{ left: pos.left, width: pos.width, ...(pos.top != null ? { top: pos.top } : { bottom: pos.bottom }) }}
        >
          <div className="term-tooltip-term">{entry.term}</div>
          <div className="term-tooltip-def">{entry.def}</div>
        </div>,
        document.body,
      )}
    </>
  );
}

function MarketColsPopover({ anchorRef, onClose, title, closeLabel, children }) {
  const [pos, setPos] = useState(null);
  const [sheet, setSheet] = useState(() => window.matchMedia("(max-width: 760px)").matches);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 760px)");
    const onChange = () => setSheet(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // Desktop geometry only — the sheet is pinned to the viewport bottom by CSS
  // and has nothing to measure.
  useLayoutEffect(() => {
    if (sheet) { setPos(null); return undefined; }
    let raf = 0;
    const place = () => {
      raf = 0;
      const btn = anchorRef.current;
      if (!btn) return;
      const r = btn.getBoundingClientRect();
      const width = Math.min(300, window.innerWidth - 24);
      // Right-aligned to the button, but never off either edge of the viewport.
      const left = Math.max(12, Math.min(r.right - width, window.innerWidth - width - 12));
      const top = Math.max(8, Math.min(r.bottom + 8, window.innerHeight - 200));
      setPos({ top, left, width, maxHeight: Math.max(200, window.innerHeight - top - 16) });
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(place); };
    place();
    // capture:true so an inner scrollport's (non-bubbling) scroll re-anchors too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    return () => {
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [anchorRef, sheet]);

  // Esc closes. On the sheet the page behind is frozen as well, so the scroll
  // gesture belongs to the sheet alone — the complaint that "scroll gets in the
  // way" on a phone was the page scrolling under an open filter panel.
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    if (!sheet) return () => window.removeEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose, sheet]);

  return createPortal(
    <>
      <div className={`market-cols-backdrop${sheet ? " is-sheet" : ""}`} onClick={onClose} />
      <div
        className={`market-cols-dropdown${sheet ? " market-cols-sheet" : ""}`}
        role="menu"
        style={sheet || !pos ? undefined : { top: pos.top, left: pos.left, width: pos.width, maxHeight: pos.maxHeight }}
      >
        {sheet && (
          <div className="market-cols-sheet-head">
            <span className="market-cols-sheet-grip" aria-hidden="true" />
            <span className="market-cols-sheet-title">{title}</span>
            <button type="button" className="market-cols-sheet-close" onClick={onClose} aria-label={closeLabel}>×</button>
          </div>
        )}
        {children}
      </div>
    </>,
    document.body
  );
}

// The board's column headers, pinned under the topbar while the rows scroll past.
// The real <thead> can't simply be `position: sticky`: its nearest scrollport is
// .market-table-wrap, which `overflow-x: auto` turns into a scroll container on
// BOTH axes, and that box never scrolls vertically — a sticky th would stay glued
// to the top of the table and ride the page up with it. So the header row is
// mirrored into a fixed bar: the SAME <th> elements (same sort and drag-reorder
// handlers), the column widths measured off the live table, and the wrap's own
// horizontal scroll offset, so the two read and behave as one header. Portaled to
// <body> for the same reason as MarketFloatScroll — the table's ancestors
// (.market-board overflow:hidden, .app-shell-wrap) would otherwise clip it.
function MarketStickyHead({ wrapRef, cells, colSignature, rowCount, loading }) {
  const scrollerRef = useRef(null);
  const [box, setBox] = useState({ show: false, left: 0, width: 0, top: 0, tableWidth: 0, cols: [] });
  const lastKey = useRef("");
  const measureRef = useRef(() => {});

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return undefined;
    let raf = 0;
    const hide = () => {
      if (lastKey.current === "hidden") return;
      lastKey.current = "hidden";
      setBox((b) => ({ ...b, show: false }));
    };
    // The bar mirrors the slice of the table the viewport actually shows, so its
    // own scroll offset is the table's scrollLeft plus whatever the wrap has run
    // off the left edge of the screen.
    const syncScroll = (el, wrapLeft) => {
      const sc = scrollerRef.current;
      if (sc) sc.scrollLeft = el.scrollLeft + (Math.max(wrapLeft, 0) - wrapLeft);
    };
    const measure = () => {
      raf = 0;
      const el = wrapRef.current;
      const table = el && el.querySelector(".market-table");
      const headRow = table && table.querySelector("thead tr");
      if (!el || !table || !headRow || loading || !rowCount) { hide(); return; }
      // Pin under the sticky topbar, whose height differs per breakpoint. The
      // filter bar above the table scrolls away with the page (by request), so
      // the topbar is the only thing this has to clear.
      const topbar = document.querySelector(".topbar");
      const pin = topbar ? Math.max(0, Math.round(topbar.getBoundingClientRect().bottom)) : 0;
      const headRect = headRow.getBoundingClientRect();
      const tableRect = table.getBoundingClientRect();
      const wrapRect = el.getBoundingClientRect();
      const left = Math.max(wrapRect.left, 0);
      const width = Math.min(wrapRect.right, window.innerWidth) - left;
      // Only while the real header sits above the pin line and rows are still
      // under it — otherwise the bar would hang over a table that has scrolled by.
      if (headRect.bottom > pin + 1 || tableRect.bottom < pin + headRect.height + 24 || width < 60) { hide(); return; }
      // Half-pixel rounding: enough to keep the labels over their columns, coarse
      // enough that sub-pixel noise doesn't re-render the bar on every frame.
      const round = (v) => Math.round(v * 2) / 2;
      const cols = Array.from(headRow.children).map((th) => round(th.getBoundingClientRect().width));
      const key = `${round(left)}|${round(width)}|${pin}|${round(tableRect.width)}|${cols.join(",")}`;
      syncScroll(el, wrapRect.left);
      if (key === lastKey.current) return;
      lastKey.current = key;
      setBox({ show: true, left, width, top: pin, tableWidth: round(tableRect.width), cols });
    };
    measureRef.current = measure;
    const schedule = () => { if (!raf) raf = requestAnimationFrame(measure); };
    measure();
    // capture:true reaches window for the wrap's own (non-bubbling) horizontal scroll too.
    window.addEventListener("scroll", schedule, { passive: true, capture: true });
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    ro.observe(wrap);
    wrap.addEventListener("scroll", schedule, { passive: true });
    return () => {
      measureRef.current = () => {};
      window.removeEventListener("scroll", schedule, { capture: true });
      window.removeEventListener("resize", schedule);
      wrap.removeEventListener("scroll", schedule);
      ro.disconnect();
      if (raf) cancelAnimationFrame(raf);
    };
  }, [wrapRef, colSignature, rowCount, loading]);

  // Column widths also move on things no observer reports — a sort caret, a
  // language switch, a font finishing its load. Re-measuring after every render
  // is cheap because `lastKey` swallows the no-op ones.
  useLayoutEffect(() => { measureRef.current(); });

  // A column CSS has hidden (mobile drops the company name) measures 0 wide.
  // It has to be left out of BOTH the colgroup and the row: a `display: none`
  // cell drops out of the row entirely under fixed table layout, so every
  // following header would shift one column to the left.
  const mirrored = box.cols
    .map((w, i) => ({ w, i }))
    .filter(({ w, i }) => w > 0 && cells[i]);

  // Nothing in the DOM until it is actually pinned — a second copy of the header
  // row hanging around would double every `.market-table thead` query.
  if (!box.show || !mirrored.length) return null;

  return createPortal(
    <div
      className="market-sticky-head"
      aria-hidden="true"
      style={{ left: box.left, width: box.width, top: box.top }}
    >
      <div className="market-sticky-head__scroller" ref={scrollerRef}>
        <table
          className="market-table market-sticky-head__table"
          style={{ width: box.tableWidth || undefined, minWidth: box.tableWidth || undefined }}
        >
          <colgroup>
            {mirrored.map(({ i, w }) => <col key={i} style={{ width: w }} />)}
          </colgroup>
          <thead>
            <tr>
              {mirrored.map(({ i }) => React.cloneElement(cells[i], {
                // The bar is aria-hidden (the real header is the one screen
                // readers and Tab travel through), so its copies stay unfocusable.
                tabIndex: -1,
              }))}
            </tr>
          </thead>
        </table>
      </div>
    </div>,
    document.body
  );
}

function MarketView({
  rows,
  meta,
  loading,
  message,
  query,
  onQueryChange,
  type,
  onTypeChange,
  onRefresh,
  onAnalyze,
  onOpenCompany,
  language,
  companies,
  securitiesMap,
  financials,
  tradeStats,
  favoriteTickers,
  onToggleFavorite,
  viewMode: viewModeProp,
  onViewModeChange,
  isAdmin = false,
}) {
  const lang = normalizeLanguage(language);
  // viewMode is driven by the route (table = /market, heatmap = /heatmap).
  const viewMode = viewModeProp || "table";
  const setViewMode = onViewModeChange || (() => {});
  const [marketSector, setMarketSector] = useState(null);
  const [favOnly, setFavOnly] = useState(false);
  const [panelTicker, setPanelTicker] = useState(null);
  const [panelWiki, setPanelWiki] = useState(null);
  const [panelWikiLoading, setPanelWikiLoading] = useState(false);
  const hasFav = (t) => !!favoriteTickers && favoriteTickers.has(String(t || "").trim().toUpperCase());

  // Per-ticker financial ratios & equity (facts store) for P/E, P/B and the
  // §3.8 ratio-coefficient columns. Fetched once; keyed by ticker.
  const [ratios, setRatios] = useState({});
  useEffect(() => {
    let alive = true;
    fetch("/api/market/ratios")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setRatios(d.ratios || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Multiples come from the server, computed per ISSUER (ТЗ §8). Keyed by
  // ticker, but both classes of an issuer carry the same object — that is the
  // point: the board used to divide ONE class's capitalisation by the WHOLE
  // issuer's profit, so no pair of classes could agree. A statement that failed
  // validation arrives with its multiples already suppressed and the reason
  // attached, so nothing here has to decide what is publishable.
  const [multiples, setMultiples] = useState({});
  const [marketSummary, setMarketSummary] = useState(null);
  const [mapData, setMapData] = useState(null);
  const [instruments, setInstruments] = useState({});
  // ТЗ §4: dormant listings are hidden by default and reachable by a switch —
  // not dropped, because a security that stopped trading is a fact about the
  // market and hiding it permanently is how five references came to disagree.
  const [showInactive, setShowInactive] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch("/api/market/multiples")
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const byTicker = {};
        (d.items || []).forEach((it) => { byTicker[it.ticker] = it; });
        setMultiples(byTicker);
      })
      .catch(() => {});
    fetch("/api/market/summary")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setMarketSummary(d); })
      .catch(() => {});
    // The market map in ONE request (ТЗ §9): tiles, sector aggregates and the
    // counts behind them. It used to be stitched together on the client from
    // endpoints with different instrument universes.
    fetch("/api/heatmap")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setMapData(d); })
      .catch(() => {});
    // The single instrument universe (ТЗ §4). `is_active` here follows TRADING —
    // ninety days without an execution — rather than a registry flag, which is
    // what the "показать неактивные" switch below actually filters on.
    fetch("/api/instruments")
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const by = {};
        (d.items || []).forEach((i) => { by[i.ticker] = i; });
        setInstruments(by);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Column sorting, as an ORDERED chain of keys. An empty chain falls back to the
  // default (date desc, then |change|) — which is itself two-level, and used to be
  // the only two-level order the board could express: one click on any header threw
  // it away. "Latest session first, biggest turnover within the day" is the question
  // the board is actually read with, and it needs two columns to ask.
  //
  // Plain click collapses back to a single key (the old behaviour, unchanged).
  // Shift/⌘/Ctrl-click appends: first press adds the column, second flips its
  // direction, third drops it out of the chain again.
  const [sortKeys, setSortKeys] = useState([]);
  // Text columns read best ascending, numeric/date columns descending.
  const defaultSortDir = (key) => (["ticker", "company"].includes(key) ? "asc" : "desc");
  const sortRankOf = (key) => sortKeys.findIndex((s) => s.key === key);
  const sortDirOf = (key) => sortKeys.find((s) => s.key === key)?.dir || null;
  const onSort = (key, additive = false) => {
    setSortKeys((prev) => {
      const i = prev.findIndex((s) => s.key === key);
      if (!additive) {
        // Re-clicking the only active key flips it; anything else starts over.
        if (prev.length === 1 && i === 0) return [{ key, dir: prev[0].dir === "asc" ? "desc" : "asc" }];
        return [{ key, dir: defaultSortDir(key) }];
      }
      if (i < 0) return [...prev, { key, dir: defaultSortDir(key) }];
      const next = [...prev];
      if (next[i].dir === defaultSortDir(key)) {
        next[i] = { key, dir: next[i].dir === "asc" ? "desc" : "asc" };
        return next;
      }
      next.splice(i, 1);
      return next;
    });
  };
  const clearSort = () => setSortKeys([]);
  // A phone has no Shift key, and the board stays a table there. Long-press on a
  // header is the touch equivalent of the modifier: it appends instead of replacing.
  const longPress = useRef({ timer: null, fired: false });
  const startLongPress = (key) => {
    longPress.current.fired = false;
    clearTimeout(longPress.current.timer);
    longPress.current.timer = setTimeout(() => {
      longPress.current.fired = true;
      onSort(key, true);
    }, 500);
  };
  const cancelLongPress = () => clearTimeout(longPress.current.timer);
  useEffect(() => () => clearTimeout(longPress.current.timer), []);
  // A modifier nobody is told about is a feature nobody has. The hint appears the
  // moment it becomes actionable — right after the first column is sorted, not on
  // a cold page where it would be noise — and retires for good once the reader has
  // either built a two-key order or dismissed it.
  const [sortHintSeen, setSortHintSeen] = useState(() => {
    try { return localStorage.getItem("uz_market_sort_hint") === "seen"; } catch (e) { return false; }
  });
  const dismissSortHint = () => {
    setSortHintSeen(true);
    try { localStorage.setItem("uz_market_sort_hint", "seen"); } catch (e) { /* ignore */ }
  };
  useEffect(() => {
    if (sortKeys.length > 1 && !sortHintSeen) dismissSortHint();
  }, [sortKeys.length, sortHintSeen]); // eslint-disable-line react-hooks/exhaustive-deps
  // Touch has no Shift key, so the hint must name the gesture that device HAS.
  const coarsePointer = typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia("(pointer: coarse)").matches;

  // User-configurable quote columns (ticker/company/last are always shown).
  // Quote columns grouped into collapsible sections in the settings dropdown.
  // Each section is a sibling of "AI screener overview" (not nested under it).
  const COL_GROUPS = [
    { key: "overview", title: mt(lang, "grpOverview"), cols: [
      ["change", mt(lang, "change")],
      ["open", mt(lang, "open")],
      ["high", mt(lang, "high")],
      ["low", mt(lang, "low")],
      ["date", mt(lang, "date")],
      ["source", mt(lang, "source")],
    ] },
    { key: "volumes", title: mt(lang, "grpVolumes"), cols: [
      ["volume", mt(lang, "volumeCol")],
      ["volQty", mt(lang, "volQty")],
      ["avgShare", mt(lang, "avgSharePrice")],
      ["avgTrade", mt(lang, "avgTradePrice")],
      ["bigTrade", mt(lang, "bigTrade")],
      ["volShare", mt(lang, "volShare")],
    ] },
    { key: "financials", title: mt(lang, "grpFinancials"), cols: [
      ["finRevenue", mt(lang, "finRevenue")],
      ["finGross", mt(lang, "finGross")],
      ["finCash", mt(lang, "finCash")],
      ["finLiab", mt(lang, "finLiab")],
      ["finNet", mt(lang, "finNet")],
      ["finOperating", mt(lang, "finOperating")],
    ] },
    { key: "multiples", title: mt(lang, "grpMultiples"), cols: [
      ["mktCap", mt(lang, "mktCap")],
      ["pe", "P/E"],
      ["pb", "P/B"],
      ["roe", "ROE"],
      ["roa", "ROA"],
      ["netMargin", mt(lang, "netMargin")],
      ["debtEq", mt(lang, "debtEquity")],
    ] },
  ];
  const MARKET_COLS = COL_GROUPS.flatMap((g) => g.cols);
  // Core columns are always shown — listed in the settings panel as locked rows.
  const CORE_COLS = [
    ["ticker", mt(lang, "ticker")],
    ["company", mt(lang, "company")],
    ["last", mt(lang, "last")],
  ];
  // Every sortable column by its screen label — the sort chain and the CSV header
  // both name keys the reader only ever sees as column titles.
  const SORT_LABEL_OF = Object.fromEntries([...CORE_COLS, ...MARKET_COLS]);
  const [visibleCols, setVisibleCols] = useState(() => {
    try { const s = JSON.parse(localStorage.getItem("uz_market_cols")); if (Array.isArray(s)) return new Set(s); } catch (e) { /* ignore */ }
    return new Set(["change", "open", "high", "low", "volume", "date", "source"]);
  });
  const [colsOpen, setColsOpen] = useState(false);
  const colsBtnRef = useRef(null); // the popover is portaled — it anchors off this
  const [colsSearch, setColsSearch] = useState("");
  const [openGroups, setOpenGroups] = useState(() => new Set(["overview", "volumes", "financials"]));
  const toggleGroup = (k) => setOpenGroups((prev) => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  useEffect(() => { try { localStorage.setItem("uz_market_cols", JSON.stringify([...visibleCols])); } catch (e) { /* ignore */ } }, [visibleCols]);
  const toggleCol = (k) => setVisibleCols((prev) => { const n = new Set(prev); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  // Bonds carry no equity metrics — the exchange feed gives them only price/trade
  // data (no market cap, P/E, ROE, or issuer financials). Hide the stock-only
  // columns on the bonds view instead of rendering misleading blank cells; stocks
  // and bonds are not comparable on the same metrics.
  const EQUITY_ONLY_COLS = new Set(["mktCap", "pe", "pb", "roe", "roa", "netMargin", "debtEq", "finRevenue", "finGross", "finCash", "finLiab", "finNet", "finOperating"]);

  // Drag-to-reorder columns. Ticker + company stay pinned left (identity cells);
  // everything from "last" onward is reorderable. Order is persisted per user.
  const MOVABLE_KEYS = ["last", ...MARKET_COLS.map(([k]) => k)];
  const [colOrder, setColOrder] = useState(() => {
    try {
      const s = JSON.parse(localStorage.getItem("uz_market_col_order"));
      if (Array.isArray(s)) {
        const known = new Set(["last", ...MARKET_COLS.map(([k]) => k)]);
        const kept = s.filter((k) => known.has(k));
        const missing = ["last", ...MARKET_COLS.map(([k]) => k)].filter((k) => !kept.includes(k));
        return [...kept, ...missing];
      }
    } catch (e) { /* ignore */ }
    return ["last", ...MARKET_COLS.map(([k]) => k)];
  });
  useEffect(() => { try { localStorage.setItem("uz_market_col_order", JSON.stringify(colOrder)); } catch (e) { /* ignore */ } }, [colOrder]);
  const [dragCol, setDragCol] = useState(null);
  const [dragOverCol, setDragOverCol] = useState(null);
  const wrapRef = useRef(null); // .market-table-wrap — for the horizontal scroll controls
  const moveCol = (from, to) => {
    if (!from || from === to) return;
    setColOrder((prev) => {
      const arr = prev.filter((k) => MOVABLE_KEYS.includes(k));
      const fi = arr.indexOf(from);
      const ti = arr.indexOf(to);
      if (fi < 0 || ti < 0) return prev;
      const next = [...arr];
      next.splice(fi, 1);
      next.splice(ti, 0, from);
      return next;
    });
  };
  const resetColOrder = () => setColOrder(["last", ...MARKET_COLS.map(([k]) => k)]);
  // Visible movable columns in the user's chosen order ("last" is always shown).
  const visibleOrder = colOrder.filter((k) =>
    (k === "last" || visibleCols.has(k)) && !(type === "bond" && EQUITY_ONLY_COLS.has(k)));
  const colSpan = 3 + visibleOrder.length;

  const openPanel = (ticker) => {
    setPanelTicker(ticker);
    setPanelWiki(null);
    setPanelWikiLoading(true);
    fetch(`/api/securities/${encodeURIComponent(ticker)}/info?language=${lang}`)
      .then((r) => r.json())
      .then((d) => { if (d.ok) setPanelWiki(d.wiki); })
      .catch(() => {})
      .finally(() => setPanelWikiLoading(false));
  };

  const smap = securitiesMap || {};
  // Fallback sector source for a ticker the securities catalog has not reached;
  // the heat map builds the same map from the same list.
  const companyMap = React.useMemo(() => {
    const by = {};
    (companies || []).forEach((c) => { if (c?.ticker) by[c.ticker] = c; });
    return by;
  }, [companies]);
  const fmap = financials || {};
  // Financials are company-level, so a preferred share shares its common
  // sibling's figures (and vice versa) — mirror the logo sibling fallback
  // (TKDM <-> TKDMP) so both halves of a pair show data from one cached row.
  const finOf = (ticker) => {
    const t = String(ticker || "").toUpperCase();
    return fmap[t] || fmap[t.endsWith("P") ? t.slice(0, -1) : `${t}P`] || null;
  };
  const tmap = tradeStats || {};
  const latestTsDay = latestTradeStatsDay(tmap);
  const preparedAll = (Array.isArray(rows) ? rows : [])
    .map(enrichMarketStock)
    .map((r) => applyTradeStats(r, tmap, latestTsDay));
  // "preferred" is a client-side subset of stocks (the feed was fetched as
  // type=stock); narrow to preferred shares so the table, sectors and heatmap
  // all reflect the filter.
  const isPreferredSec = (r) =>
    smap[r.ticker]?.is_preferred === true ||
    smap[r.ticker]?.share_type === "preferred" ||
    r.share_type === "preferred";
  const byClass =
    type === "preferred" ? preparedAll.filter(isPreferredSec)
    : type === "ordinary" ? preparedAll.filter((r) => !isPreferredSec(r))
    : preparedAll;
  // ТЗ §4: activity is a fact about trading, taken from /api/instruments, not a
  // flag on the row — the registry's own flag disagreed with the tape.
  const isDormant = (r) => {
    const item = instruments[String(r.ticker || "").toUpperCase()];
    return item ? item.is_active === false : r.inactive === true;
  };
  const dormantCount = byClass.filter(isDormant).length;
  const prepared = showInactive ? byClass : byClass.filter((r) => !isDormant(r));
  const search = String(query || "").trim().toLowerCase();

  // Gather sectors present in current data. Same resolver as the heat map, so a
  // chip here and a block there always hold the same tickers — and a row the
  // securities catalog has not reached lands under Прочее instead of answering
  // to no chip at all.
  const rowSector = (r) => sectorOf(r.ticker, smap, companyMap);
  const presentSectors = [...new Set(prepared.map(rowSector))].sort();

  // §3.8 multipliers. Inputs are gathered here; the arithmetic lives in the one
  // shared valuationRatios() so this table and the company page cannot disagree.
  const ratioOf = (ticker) => ratios[ticker] || ratios[String(ticker || "").toUpperCase()] || null;
  const mktCapOf = (r) => (Number.isFinite(r.marketCap) ? r.marketCap : null);
  // Earnings for the multiples: the last complete fiscal year when the issuer's
  // latest filing is a cumulative quarter, so P/E means the same thing in every
  // row. Without it the column silently mixes 3-, 6- and 12-month profits.
  const earningsOf = (r) => finEarnings(finOf(r.ticker));
  // ТЗ §8: the server owns this arithmetic. `valuationRatios` remains only as a
  // fallback for the moment before /api/market/multiples answers — it computes
  // at CLASS level and is therefore wrong for a two-class issuer, so it must
  // never outlive the response.
  const multiplesOf = (r) => multiples[String(r.ticker || "").toUpperCase()] || null;
  const valuationOf = (r) => {
    const server = multiplesOf(r);
    if (server) return { pe: server.pe, pb: server.pb, server: true };
    const rat = ratioOf(r.ticker) || {};
    const local = valuationRatios({
      marketCap: mktCapOf(r),
      netIncome: earningsOf(r).netIncome,
      equity: rat.total_equity,
      roePercent: rat.roe,
    });
    return {
      pe: { value: local.pe, status: local.pe == null ? "no_financials" : "ok" },
      pb: { value: local.pb, status: local.pb == null ? "no_financials" : "ok" },
      server: false,
    };
  };
  const peOf = (r) => valuationOf(r).pe?.value ?? null;

  // A flow figure scaled to twelve months, for SORTING only (ТЗ §7). Returns
  // null rather than a raw value when the period is unknown: ordering by a
  // number whose span nobody knows is the defect, not the fix.
  const annualisedFin = (r, field) => {
    const fin = finOf(r.ticker);
    const value = fin?.[field];
    if (!Number.isFinite(value)) return null;
    const months = Number.isFinite(fin?.period_months)
      ? fin.period_months
      : (fin?.quarter > 0 ? fin.quarter * 3 : (fin?.year ? 12 : null));
    if (!months || months <= 0) return null;
    return (value * 12) / months;
  };

  // ТЗ §8: a multiple the server withheld says WHY. «убыток» is a fact about the
  // issuer, not missing data; «проверяется» means the statement behind it failed
  // validation; a range status means the figure exists and is not believable.
  const statusText = (status) => multipleStatusText(status, lang);
  const multipleCell = (row, metric, digits, suffix = "×") => {
    if (metric?.value != null) {
      return <td className="num">{formatRatio(metric.value, digits, lang)}{suffix}</td>;
    }
    const label = statusText(metric?.status);
    if (!label) return <td className="num">{noSecLabel(row)}</td>;
    const reasons = (metric?.reasons || []).join("; ")
      || (metric?.computed != null
        ? `${formatRatio(metric.computed, digits, lang)}${suffix} ∉ [${metric.allowed?.join(", ")}]`
        : metric?.note || "");
    return <td className="num"><span className="cell-status" title={reasons || undefined}>{label}</span></td>;
  };
  // Issuers openinfo records as having no tradable securities at all
  // (is_listing=false, empty RFB/OTC share registries — e.g. MNGM, OCBK):
  // market-value cells state that fact instead of an ambiguous dash.
  const noSecLabel = (r) => (r.isin ? "—"
    : lang === "ru" ? "нет бумаг" : lang === "uz" ? "qog'oz yo'q" : "no securities");
  // "Not applicable": the figure is undefined for this issuer's reporting
  // form (bank/insurer/fund statements) rather than missing.
  const naLabel = () => (lang === "ru" ? "н/п" : lang === "uz" ? "t/e" : "n/a");
  // Trade date of the row's day statistics (YYYYMMDD → YYYY-MM-DD).
  const tsDate = (r) => {
    const d = String(r.ts?.trade_date || "");
    return /^\d{8}$/.test(d) ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)}` : null;
  };
  // Per-trade stat cells for securities with no execution in the archive at
  // all (verified 10-year lookback): state "no trades" — the same fact the
  // trade-date column shows — rather than an ambiguous dash.
  const neverTraded = (r) => (!r.last_trade_date && !r.ts ? mt(lang, "noTrade") : "—");
  const pbOf = (r) => valuationOf(r).pb?.value ?? null;

  // One financials cell, with the reporting period it belongs to underneath it.
  // The period is not decoration: these figures mix completed annuals with
  // cumulative quarters across issuers, and a field whose only source is another
  // filing carries that filing's period (marked, so it reads as a footnote rather
  // than as this row's number).
  const finCell = (row, field, { naWhenTopLine = false } = {}) => {
    const f = finOf(row.ticker);
    const value = f?.[field];
    if (value == null && naWhenTopLine && Number.isFinite(f?.revenue)) {
      return <td className="num">{naLabel()}</td>;
    }
    if (!Number.isFinite(value)) return <td className="num">—</td>;
    const period = finFieldPeriod(f, field);
    const borrowed = Boolean((f?.field_periods || {})[field]);
    const coverage = finPeriodCoverage(period, lang);
    // How much trading the figure covers, printed rather than only hovered: NSBU
    // quarters are cumulative, so this column routinely sets one issuer's six
    // months beside another's three and a third's completed year. Balance lines
    // get no suffix — they are a position on the closing date, not an accumulation.
    const length = finFieldCoverage(period, field, lang);
    return (
      <td className="num">
        <strong>{finValue(value, lang)}</strong>
        {period && (
          <span className={`fin-cell-period${borrowed ? " borrowed" : ""}`}
                title={borrowed
                  ? `${period} · ${coverage} — ${lang === "ru" ? "период отличается от периода строки"
                      : lang === "uz" ? "davr qator davridan farq qiladi"
                      : "a different period than the row"}`
                  : `${period} · ${coverage}`}>
            {period}{length ? ` · ${length}` : ""}{borrowed ? " *" : ""}
          </span>
        )}
      </td>
    );
  };

  // Value read for each sortable column. ticker/company/date are strings, the rest numeric.
  const sortAccessors = {
    ticker: (r) => r.ticker || "",
    company: (r) => r.name || "",
    last: (r) => marketDisplayPrice(r),
    change: (r) => r.changePercent,
    open: (r) => r.openPrice,
    high: (r) => r.highPrice,
    low: (r) => r.lowPrice,
    volume: (r) => r.stockVolume,
    volQty: (r) => r.stockQuantity,
    avgShare: (r) => (Number.isFinite(r.avgPrice) ? r.avgPrice : avgSharePrice(r)),
    avgTrade: (r) => avgTradeValue(r),
    bigTrade: (r) => r.ts?.largest_value,
    volShare: (r) => r.stockVolume,
    // ТЗ §7: a column that mixes reporting periods may not be ordered by its
    // raw values. The cached rows span twelve different (year, months)
    // combinations, so a full year always outranked a peer's four quarters for
    // no reason the reader could see. The CELL keeps its own period and label;
    // only the SORT runs on the twelve-month normalisation. Balance-sheet lines
    // are a position on a date and are never scaled.
    finRevenue: (r) => annualisedFin(r, "revenue"),
    finGross: (r) => annualisedFin(r, "gross_profit"),
    finCash: (r) => finOf(r.ticker)?.cash,
    finLiab: (r) => finOf(r.ticker)?.total_liabilities,
    finNet: (r) => annualisedFin(r, "net_income"),
    finOperating: (r) => annualisedFin(r, "operating_income"),
    mktCap: (r) => mktCapOf(r),
    pe: (r) => peOf(r),
    pb: (r) => pbOf(r),
    roe: (r) => ratioOf(r.ticker)?.roe,
    roa: (r) => ratioOf(r.ticker)?.roa,
    netMargin: (r) => ratioOf(r.ticker)?.net_profit_margin,
    debtEq: (r) => ratioOf(r.ticker)?.debt_to_equity,
    // Normalized to YYYYMMDD so the comparison is chronological. The raw field is
    // a mix of DD.MM.YYYY (live feed) and YYYY-MM-DD (listings registry), and
    // comparing those as strings ordered by the leading digits — "31.01.2026"
    // sorted above "05.02.2026", so "latest first" broke at every month boundary.
    date: (r) => marketRowDay(r) || "",
    source: (r) => r.url || "",
  };

  const visibleRows = prepared
    .filter((row) => {
      if (favOnly && !hasFav(row.ticker)) return false;
      if (marketSector && rowSector(row) !== marketSector) return false;
      if (!search) return true;
      return `${row.ticker || ""} ${row.name || ""} ${row.isin || ""}`.toLowerCase().includes(search);
    })
    .sort((a, b) => {
      if (!sortKeys.length) {
        // Same normalization as the `date` accessor — the default "most recently
        // traded first" order was wrong across month boundaries for exactly the
        // same reason (mixed DD.MM.YYYY / YYYY-MM-DD compared lexicographically).
        const aDate = marketRowDay(a) || "";
        const bDate = marketRowDay(b) || "";
        if (aDate !== bDate) return bDate.localeCompare(aDate);
        return Math.abs(b.changePercent ?? -Infinity) - Math.abs(a.changePercent ?? -Infinity);
      }
      // Each key decides only the rows the keys before it tied on.
      for (const { key, dir } of sortKeys) {
        const acc = sortAccessors[key];
        if (!acc) continue;
        const c = compareSortValues(acc(a), acc(b), dir);
        if (c) return c;
      }
      return 0;
    });
  const stats = buildMarketStats(prepared);

  // §3.8: export the table the user is looking at as OUR report, client-side.
  //
  // It used to emit a bare 20-column board dump — English headers on a Russian page, UZSE's
  // own name strings, full-precision floats ("43.84615384615385") and a comma delimiter —
  // which read as somebody else's export, because that is what an exchange board is. What
  // separates our page from uzse.uz is the reporting beside the quote, and none of it was in
  // the file: revenue, gross and operating profit, net income, cash, liabilities, and the
  // period each of those figures actually covers. Those are here now, next to the multiples
  // computed from them, under a header block that says what the file is and where each part
  // came from.
  //
  // Delimiter and decimal mark follow the UI language for the same reason. Excel in a ru/uz
  // locale splits on ';' and reads ',' as the decimal mark, so a comma-separated file with
  // dotted decimals opens as a single column of text — the most literal way to look like a
  // foreign dump.
  const exportCsv = () => {
    const ruLocale = lang !== "en";
    const sep = ruLocale ? ";" : ",";
    const cell = (v) => {
      if (v === null || v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v))) return "";
      let s = typeof v === "number"
        ? (ruLocale ? String(v).replace(".", ",") : String(v))
        : String(v);
      // A quoted field is needed for the delimiter, quotes and newlines — and, once decimals
      // are commas, for every number too when the delimiter is a comma.
      return new RegExp(`["\\n\\r${sep === ";" ? ";" : ","}]`).test(s)
        ? `"${s.replace(/"/g, '""')}"` : s;
    };
    // Rounded the way the screen rounds: a report states a figure, it does not dump a float.
    const round = (v, digits) => (Number.isFinite(v) ? Number(v.toFixed(digits)) : "");
    const money = (v) => (Number.isFinite(v) ? Math.round(v) : "");

    const filters = [
      mt(lang, type === "stock" ? "stocks" : type === "bond" ? "bonds"
        : type === "preferred" ? "preferredStocks" : type === "ordinary" ? "ordinaryStocks" : "all"),
      marketSector || "",
      favOnly ? mt(lang, "csvFav") : "",
      String(query || "").trim() ? `${mt(lang, "csvSearch")}: ${String(query).trim()}` : "",
    ].filter(Boolean).join(" · ");
    // `last_trade_date` arrives as DD.MM.YYYY from the live feed and YYYY-MM-DD from the
    // listings registry. Normalise both through marketRowDay so one column holds one format.
    const day = (d) => (/^\d{8}$/.test(d || "") ? `${d.slice(6)}.${d.slice(4, 6)}.${d.slice(0, 4)}` : "");
    const session = day(stats.boardDay);

    // Two columns, so the block reads as label/value in a spreadsheet rather than as text
    // spilled across the sheet. A blank row separates it from the table proper.
    const lines = [
      [mt(lang, "csvTitle"), ""].map(cell).join(sep),
      // Stamped DD.MM.YYYY like every other date in the file. Deliberately not the browser
      // locale's own format: on en-US that prints 7/29/2026 next to a 29.07.2026 trade-date
      // column, and one report should not carry two date conventions.
      [mt(lang, "csvGenerated"), (() => {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, "0");
        return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      })()].map(cell).join(sep),
      [mt(lang, "csvSession"), session].map(cell).join(sep),
      [mt(lang, "csvFilter"), filters].map(cell).join(sep),
      // The file is the table as it stands on screen, so the row ORDER is part of
      // what is being exported — state it rather than let the reader guess.
      [mt(lang, "csvSort"), sortKeys.length
        ? sortKeys.map(({ key, dir }) => `${SORT_LABEL_OF[key] || key} ${dir === "asc" ? "↑" : "↓"}`).join(" → ")
        : mt(lang, "csvSortDefault")].map(cell).join(sep),
      [mt(lang, "csvRows"), visibleRows.length].map(cell).join(sep),
      [mt(lang, "csvMoneyNote"), ""].map(cell).join(sep),
      [mt(lang, "csvSources"), ""].map(cell).join(sep),
      "",
    ];

    const header = [
      mt(lang, "ticker"), mt(lang, "company"), mt(lang, "isin"), mt(lang, "sector"),
      mt(lang, "shareType"), mt(lang, "date"),
      mt(lang, "last"), `${mt(lang, "change")}, %`, mt(lang, "open"), mt(lang, "high"), mt(lang, "low"),
      mt(lang, "volumeCol"), mt(lang, "csvTrades"), mt(lang, "volQty"),
      mt(lang, "avgSharePrice"), "VWAP", mt(lang, "bigTrade"), mt(lang, "volShare"),
      mt(lang, "finPeriod"), mt(lang, "finCoverage"),
      mt(lang, "finRevenue"), mt(lang, "finGross"), mt(lang, "finOperating"),
      mt(lang, "finNet"), mt(lang, "finCash"), mt(lang, "finLiab"),
      mt(lang, "mktCap"), mt(lang, "pe"), mt(lang, "pb"),
      mt(lang, "roe"), mt(lang, "roa"), `${mt(lang, "netMargin")}, %`, mt(lang, "debtEquity"),
    ];
    lines.push(header.map(cell).join(sep));

    for (const row of visibleRows) {
      const sec = smap[row.ticker] || {};
      const rat = ratioOf(row.ticker) || {};
      const fin = finOf(row.ticker) || null;
      const period = finRowPeriod(fin);
      const share = (stats.boardDay && marketRowDay(row) !== stats.boardDay) ? 0
        : Number.isFinite(row.stockVolume) && stats.totalVolume > 0
          ? (row.stockVolume / stats.totalVolume) * 100 : "";
      const isPreferred = sec.is_preferred || row.share_type === "preferred";
      lines.push([
        row.ticker,
        row.name,
        row.isin,
        sec.sector || "",
        (row.type === "bond" || sec.type === "bond") ? mt(lang, "bondOne")
          : isPreferred ? mt(lang, "preferred") : mt(lang, "ordinary"),
        day(marketRowDay(row)),
        round(marketDisplayPrice(row), 2), round(row.changePercent, 2),
        round(row.openPrice, 2), round(row.highPrice, 2), round(row.lowPrice, 2),
        money(row.stockVolume), row.stockTradeCount, row.stockQuantity,
        round(Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row), 2),
        round(row.vwap, 2), money(row.ts?.largest_value), round(share, 2),
        period || "", period ? finPeriodCoverage(period, lang) : "",
        money(fin?.revenue), money(fin?.gross_profit), money(fin?.operating_income),
        money(fin?.net_income), money(fin?.cash), money(fin?.total_liabilities),
        money(mktCapOf(row)), round(peOf(row), 2), round(pbOf(row), 2),
        round(rat.roe, 2), round(rat.roa, 2), round(rat.net_profit_margin, 2),
        round(rat.debt_to_equity, 2),
      ].map(cell).join(sep));
    }

    // CRLF and the BOM: what Excel expects of a CSV on Windows, which is where these open.
    const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `uzse_${type || "all"}_${(stats.boardDay || "").slice(0, 8) || "latest"}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const formatLeader = (row) => row ? `${row.ticker} ${formatRatio(row.changePercent, 2, lang)}%` : "—";

  const sortTh = (key, label, opts = {}) => {
    const { movable = false, num = false } = opts;
    const rank = sortRankOf(key);
    const dir = sortDirOf(key);
    const chained = sortKeys.length > 1;
    const cls = [
      "market-th-sortable",
      num ? "market-th-num" : "",
      rank >= 0 ? "sorted" : "",
      movable ? "market-th-movable" : "",
      movable && dragCol === key ? "dragging" : "",
      movable && dragOverCol === key && dragCol && dragCol !== key ? "drag-over" : "",
    ].filter(Boolean).join(" ");
    // ⌘ on a Mac, Ctrl elsewhere — Shift works everywhere and is the one we teach.
    const isAdditive = (e) => e.shiftKey || e.metaKey || e.ctrlKey;
    const hint = lang === "en" ? "Shift+click (or long-press) — add as a secondary sort"
      : lang === "uz" ? "Shift+bosish (yoki uzoq bosish) — qoʻshimcha saralash kaliti"
      : "Shift+клик (или долгое нажатие) — добавить второй ключ сортировки";
    const dragHint = lang === "en" ? "Drag to reorder · click to sort"
      : lang === "uz" ? "Tartibni o'zgartirish uchun torting · saralash uchun bosing"
      : "Перетащите, чтобы переставить · нажмите для сортировки";
    return (
    <th
      key={key}
      className={cls}
      data-sort-key={key}
      onClick={(e) => {
        // The long-press already sorted; the tap that ends it must not sort again.
        if (longPress.current.fired) { longPress.current.fired = false; return; }
        onSort(key, isAdditive(e));
      }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSort(key, isAdditive(e)); } }}
      onTouchStart={() => startLongPress(key)}
      onTouchMove={cancelLongPress}
      onTouchEnd={cancelLongPress}
      onTouchCancel={cancelLongPress}
      onContextMenu={(e) => { if (longPress.current.fired) e.preventDefault(); }}
      role="button"
      tabIndex={0}
      /* ARIA asks for aria-sort on ONE header at a time, so the chain's later keys
         announce their rank through the accessible name instead. */
      aria-sort={rank === 0 ? (dir === "asc" ? "ascending" : "descending") : "none"}
      aria-label={rank > 0
        ? `${label} — ${lang === "en" ? "sort" : lang === "uz" ? "saralash" : "сортировка"} ${rank + 1}, ${
            dir === "asc" ? (lang === "en" ? "ascending" : lang === "uz" ? "oʻsish" : "по возрастанию")
              : (lang === "en" ? "descending" : lang === "uz" ? "kamayish" : "по убыванию")}`
        : undefined}
      draggable={movable}
      onDragStart={movable ? (e) => { setDragCol(key); e.dataTransfer.effectAllowed = "move"; try { e.dataTransfer.setData("text/plain", key); } catch (_) { /* ignore */ } } : undefined}
      onDragOver={movable ? (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (dragOverCol !== key) setDragOverCol(key); } : undefined}
      onDragEnter={movable ? (e) => e.preventDefault() : undefined}
      onDragLeave={movable ? () => { setDragOverCol((c) => (c === key ? null : c)); } : undefined}
      onDrop={movable ? (e) => { e.preventDefault(); let from = dragCol; if (!from) { try { from = e.dataTransfer.getData("text/plain"); } catch (_) { from = null; } } moveCol(from, key); setDragCol(null); setDragOverCol(null); } : undefined}
      onDragEnd={movable ? () => { setDragCol(null); setDragOverCol(null); } : undefined}
      title={movable ? `${dragHint} · ${hint}` : hint}
    >
      <span className="market-th-inner">
        {movable && <span className="market-th-grip" aria-hidden="true">⋮⋮</span>}
        <span>{label}</span>
        {/* Renders nothing for a column that is not an economic term (компания,
            UZSE) — the marker promises an explanation and must not appear
            without one. */}
        <TermInfo termId={key} lang={lang} label={label} />
        <span className="market-sort-caret">{rank >= 0 ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
        {/* The rank only earns its space once the order actually has more than one
            key — a lone "1" beside a single sorted column says nothing. */}
        {chained && rank >= 0 && <span className="market-sort-rank" aria-hidden="true">{rank + 1}</span>}
      </span>
    </th>
    );
  };

  // Label + cell registry so the movable columns can render in any order.
  const LABEL_OF = Object.fromEntries([["last", mt(lang, "last")], ...MARKET_COLS]);
  const NUM_COLS = new Set(MOVABLE_KEYS.filter((k) => k !== "date" && k !== "source"));
  const CELL_OF = {
    last: (row) => <td className="num">{(() => { const p = marketDisplayPrice(row); return p == null ? "—" : formatMarketNumber(p, lang); })()}</td>,
    // ТЗ §2.4/§9: "отсутствие данных показывается как нулевое изменение" was
    // the defect. This cell substituted 0 whenever a close price existed, so a
    // security that has not traded since 15.07 read as "unchanged today" beside
    // securities that genuinely did not move. Measured against the trade
    // archive, seven rows showed 0 % where the last real session moved by up to
    // 20 %. No trading in this session means no change to report — the cell
    // says so, and names the day the price is actually from.
    change: (row) => {
      if (!row.tradedToday) {
        const when = row.last_trade_date || row.ts?.trade_date;
        return (
          <td className="num">
            <span className="cell-status" title={when
              ? `${lang === "ru" ? "цена за" : lang === "uz" ? "narx" : "price from"} ${when}`
              : undefined}>
              {lang === "en" ? "no trades" : lang === "uz" ? "bitim yo'q" : "нет сделок"}
            </span>
          </td>
        );
      }
      return <td className="num"><MarketChangeBadge value={row.changeValue} percent={row.changePercent} language={lang} /></td>;
    },
    open: (row) => <td className="num">{(() => { const v = row.openPrice !== null ? row.openPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    high: (row) => <td className="num">{(() => { const v = row.highPrice !== null ? row.highPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    low: (row) => <td className="num">{(() => { const v = row.lowPrice !== null ? row.lowPrice : marketDisplayPrice(row); return v == null ? "—" : formatMarketNumber(v, lang); })()}</td>,
    volume: (row) => (
      <td className="num">
        {row.stockVolume !== null ? formatRatio(row.stockVolume, 0, lang) : "—"}
        {row.stockTradeCount !== null && <span>{formatRatio(row.stockTradeCount, 0, lang)} {tradeCountLabel(row.stockTradeCount, lang)}</span>}
      </td>
    ),
    volQty: (row) => <td className="num">{row.stockQuantity !== null ? formatRatio(row.stockQuantity, 0, lang) : "—"}</td>,
    avgShare: (row) => { const v = Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row); return <td className="num">{v === null || v === undefined ? neverTraded(row) : formatMarketNumber(v, lang)}</td>; },
    avgTrade: (row) => <td className="num">{avgTradeValue(row) !== null ? formatRatio(avgTradeValue(row), 0, lang) : neverTraded(row)}</td>,
    bigTrade: (row) => (
      <td className="num">
        {row.ts && Number.isFinite(row.ts.largest_value) ? (
          <>
            {formatRatio(row.ts.largest_value, 0, lang)}
            <span>
              {Number.isFinite(row.ts.largest_qty) ? `${formatRatio(row.ts.largest_qty, 0, lang)} ${mt(lang, "tradeQtyUnit")}` : ""}
              {Number.isFinite(row.ts.largest_pct_value) ? ` · ${formatRatio(row.ts.largest_pct_value, 1, lang)}%` : ""}
            </span>
          </>
        ) : neverTraded(row)}
      </td>
    ),
    volShare: (row) => <td className="num">{(() => {
      // Share of the LATEST session's turnover: an untraded security's
      // backfilled old-day volume contributes 0% of today, by definition.
      if (stats.boardDay && marketRowDay(row) !== stats.boardDay) return `0%`;
      return Number.isFinite(row.stockVolume) && stats.totalVolume > 0 ? `${formatRatio(row.stockVolume / stats.totalVolume * 100, 2, lang)}%` : "—";
    })()}</td>,
    finRevenue: (row) => finCell(row, "revenue"),
    // Bank/insurer/fund filings have no gross-profit or operating-income
    // lines (their reporting form differs) — when the issuer's top line IS
    // published but the form carries no such line, say "not applicable"
    // instead of an ambiguous dash.
    finGross: (row) => finCell(row, "gross_profit", { naWhenTopLine: true }),
    finCash: (row) => finCell(row, "cash"),
    finLiab: (row) => finCell(row, "total_liabilities"),
    finNet: (row) => finCell(row, "net_income"),
    finOperating: (row) => finCell(row, "operating_income", { naWhenTopLine: true }),
    mktCap: (row) => <td className="num">{(() => { const v = mktCapOf(row); return v == null ? noSecLabel(row) : formatRatio(v, 0, lang); })()}</td>,
    pe: (row) => {
      const m = valuationOf(row).pe;
      if (m?.value == null) return multipleCell(row, m, 1);
      // Name the earnings period on the cell: this is the one multiple whose
      // denominator can come from a different filing than the row's own figures.
      const period = m.base_period || earningsOf(row).period;
      const months = m.base_months || earningsOf(row).months;
      return (
        <td className="num" title={period ? `${lang === "ru" ? "прибыль за" : lang === "uz" ? "foyda" : "earnings for"} ${period}${months ? ` · ${months} ${lang === "ru" ? "мес." : lang === "uz" ? "oy" : "months"}` : ""}` : undefined}>
          <strong>{formatRatio(m.value, 1, lang)}×</strong>
          {period && <span className="fin-cell-period">{period}</span>}
        </td>
      );
    },
    pb: (row) => multipleCell(row, valuationOf(row).pb, 2),
    roe: (row) => multipleCell(row, multiplesOf(row)?.roe
      ?? { value: ratioOf(row.ticker)?.roe, status: "ok" }, 2, ""),
    roa: (row) => multipleCell(row, multiplesOf(row)?.roa
      ?? { value: ratioOf(row.ticker)?.roa, status: "ok" }, 2, ""),
    netMargin: (row) => <td className="num">{(() => {
      const v = ratioOf(row.ticker)?.net_profit_margin;
      if (v != null) return formatRatio(v, 2, lang);
      // Margin is undefined at zero revenue (e.g. the National Investment
      // Fund) — say so instead of showing an ambiguous dash.
      if (finOf(row.ticker)?.revenue === 0) return lang === "ru" ? "н/п" : lang === "uz" ? "t/e" : "n/a";
      return "—";
    })()}</td>,
    debtEq: (row) => <td className="num">{(() => { const v = ratioOf(row.ticker)?.debt_to_equity; return v == null ? "—" : formatRatio(v, 2, lang); })()}</td>,
    date: (row) => (
      <td>
        {/* The live feed reports last_trade_date=null for some securities
            that did trade — the backfilled day stats carry the real date. */}
        <strong>{row.last_trade_date || tsDate(row) || mt(lang, "noTrade")}</strong>
        {row.close_date && <span>{mt(lang, "closeDate")} {row.close_date}</span>}
      </td>
    ),
    source: (row) => (
      <td>
        {row.url ? (
          <a className="market-source-link" href={row.url} target="_blank" rel="noreferrer">{mt(lang, "source")}</a>
        ) : "—"}
      </td>
    ),
  };

  // One header row, rendered twice: in the table itself and in the pinned bar
  // (MarketStickyHead), so both carry the same sort and drag-reorder handlers.
  const headCells = [
    sortTh("ticker", mt(lang, "ticker")),
    sortTh("company", mt(lang, "company")),
    ...visibleOrder.map((k) => sortTh(k, LABEL_OF[k], { movable: true, num: NUM_COLS.has(k) })),
  ];

  return (
    <section className="market-layout">
      <article className="panel market-hero-panel">
        <div className="market-hero-copy">
          <div className="panel-label">{mt(lang, "nav")}</div>
          <h1>{mt(lang, "title")}</h1>
          <p>{mt(lang, "subtitle")}</p>
        </div>
        {/* Operator controls, not reader information: the collector's stamp and
            the manual re-pull answer "did OUR 08:00/13:00/16:10 run land", a
            question only an admin can act on. Readers get the session date on
            the board itself. */}
        {isAdmin && (
          <div className="market-hero-actions">
            {/* When WE last refreshed the board (the collector's 08:00 / 13:00 /
                16:10 runs), not when someone else's mirror refreshed its cache —
                the second is what this used to show, and it can never report our
                schedule. The mirror's stamp and the session it describes stay in
                the tooltip; the feed stamp is the fallback if the trade-stats call
                has not landed yet. */}
            <span className="status-badge muted" title={marketStampTitle(meta, lang)}>
              {mt(lang, "updated")}: {formatMarketTimestamp(meta?.refreshed_at || meta?.updated_at, lang)}
            </span>
            <button className="ghost-btn" type="button" onClick={onRefresh} disabled={loading}>
              {loading ? mt(lang, "loading") : mt(lang, "refresh")}
            </button>
          </div>
        )}
      </article>

      <div className="market-stats-grid">
        <MarketStatCard label={mt(lang, "instruments")} value={formatRatio(prepared.length || meta?.count || 0, 0, lang)} sub={message || mt(lang, "ready")} />
        <MarketStatCard label={mt(lang, "traded")} value={formatRatio(stats.traded, 0, lang)} sub={mt(lang, "date")} />
        <MarketStatCard label={mt(lang, "advancers")} value={formatRatio(stats.advancers, 0, lang)} sub={formatLeader(stats.topGrowth)} tone="good" />
        <MarketStatCard label={mt(lang, "decliners")} value={formatRatio(stats.decliners, 0, lang)} sub={formatLeader(stats.topDrop)} tone="danger" />
        <MarketStatCard label={mt(lang, "unchanged")} value={formatRatio(stats.unchanged, 0, lang)} sub={mt(lang, "date")} />
        {/* ТЗ §8: the market's capitalisation is its ACTIVE SHARES. The client
            sum counted bonds, which carry no ownership, and dormant listings —
            23 of them, 29 088 bn — inside a figure labelled "the market". The
            server now answers with the total and with what it left out. */}
        {(() => {
          const server = marketSummary?.market_cap;
          const value = server?.value ?? stats.totalMarketCap;
          if (!(value > 0)) return null;
          const ex = server?.excluded || {};
          const excludedNote = [
            ex.bonds?.instruments ? `${lang === "ru" ? "облигации" : lang === "uz" ? "obligatsiyalar" : "bonds"}: ${ex.bonds.instruments}` : null,
            ex.inactive_listings?.instruments ? `${lang === "ru" ? "неактивные" : lang === "uz" ? "faol emas" : "inactive"}: ${ex.inactive_listings.instruments}` : null,
          ].filter(Boolean).join(", ");
          return (
            <MarketStatCard
              label={mt(lang, "marketCap")}
              value={formatCompactVolume(value, lang)}
              sub={excludedNote ? `UZS · ${lang === "ru" ? "без" : lang === "uz" ? "hisobsiz" : "excl."} ${excludedNote}` : "UZS"} />
          );
        })()}
        {/* The day's turnover is the sum of the rows below it, not a separate
            feed's idea of the day: the mirror's /trades snapshot covers a fixed
            44 securities and called 31.07 "120,7 млн over ~900 trades" while the
            board it sits above listed 1,56 млрд over 6 507 — and it cannot
            answer per tab, so the shares view was quoting bond turnover too. */}
        {stats.totalVolume > 0 && <MarketStatCard label={mt(lang, "volume")} termId="volume" lang={lang} value={formatCompactVolume(stats.totalVolume, lang)} sub={stats.totalTrades ? `${formatRatio(stats.totalTrades, 0, lang)} ${tradeCountLabel(stats.totalTrades, lang)}` : null} />}
      </div>

      {viewMode === "table" && (stats.topGainers.length > 0 || stats.topLosers.length > 0) && (
        <div className="market-top-movers">
          {[
            { key: "up", title: mt(lang, "topGainers"), rows: stats.topGainers },
            { key: "down", title: mt(lang, "topLosers"), rows: stats.topLosers },
          ].map((col) => (
            <article className={`panel market-movers-col ${col.key}`} key={col.key}>
              <div className="market-movers-head">
                <span className={`market-movers-dot ${col.key}`} />
                <h3>{col.title}</h3>
              </div>
              <ul className="market-movers-list">
                {col.rows.length ? col.rows.map((r) => (
                  <li key={r.ticker}>
                    <button
                      type="button"
                      className="market-movers-item"
                      onClick={() => onOpenCompany ? onOpenCompany(r.ticker) : onAnalyze(r.ticker)}
                    >
                      <span className="market-movers-tk">
                        <CompanyLogo logo={smap[r.ticker]?.logo_url} name={r.name || r.ticker} ticker={r.ticker} />
                        <span className="market-movers-name">{r.ticker}</span>
                      </span>
                      <span className={`market-movers-chg ${col.key}`}>
                        {col.key === "up" ? "+" : ""}{formatRatio(r.changePercent, 2, lang)}%
                      </span>
                    </button>
                  </li>
                )) : <li className="market-movers-empty">—</li>}
              </ul>
            </article>
          ))}
        </div>
      )}

      <article className="panel market-board">
        <div className="market-board-head">
          <div>
            <div className="panel-label">{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</div>
            <h2>{viewMode === "heatmap" ? (lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка") : mt(lang, "tableTitle")}</h2>
          </div>
          <div className="market-board-head-right">
            <div className="market-view-toggle">
              <button
                type="button"
                className={viewMode === "table" ? "active" : ""}
                onClick={() => setViewMode("table")}
                title={lang === "en" ? "Table view" : lang === "uz" ? "Jadval ko'rinishi" : "Таблица"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="2" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="6.6" width="13" height="1.8" rx="0.9"/>
                  <rect x="1" y="11.2" width="13" height="1.8" rx="0.9"/>
                </svg>
              </button>
              <button
                type="button"
                className={viewMode === "heatmap" ? "active" : ""}
                onClick={() => setViewMode("heatmap")}
                title={lang === "en" ? "Market map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка"}
              >
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="1" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="1" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                  <rect x="8.2" y="8.2" width="5.8" height="5.8" rx="1.2"/>
                </svg>
              </button>
            </div>
            {viewMode === "table" && (
              <span className="status-badge muted">{mt(lang, "showing")}: {visibleRows.length}/{prepared.length}</span>
            )}
          </div>
        </div>

        {/* Every filter the board has — instrument class, share class, favourites,
            search, the column picker and the sector chips — lives in one block so
            it can stick under the topbar as a unit. Scrolling to row 300 must not
            cost the reader the controls that put those rows on screen. */}
        <div className="market-filterbar">
        <div className="market-controls">
          {/* Level 1: instrument class — stocks vs bonds are not comparable
              (price/capitalisation vs coupon/maturity), so they never share a table. */}
          <div className="market-type-levels">
            <div className="segmented-control market-type-control">
              {[
                ["stock", mt(lang, "stocks")],
                ["bond", mt(lang, "bonds")],
              ].map(([value, label]) => {
                const active = value === "bond" ? type === "bond" : type !== "bond";
                return (
                  <button key={value} type="button" className={active ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>
                );
              })}
            </div>
            {/* Level 2: share class — only meaningful inside stocks. */}
            {type !== "bond" && (
              <div className="segmented-control market-subtype-control">
                {[
                  ["stock", mt(lang, "all")],
                  ["ordinary", mt(lang, "ordinaryStocks")],
                  ["preferred", mt(lang, "preferredStocks")],
                ].map(([value, label]) => (
                  <button key={value} type="button" className={type === value ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>
          {viewMode === "table" && (
            <button
              type="button"
              className={`market-fav-filter ${favOnly ? "active" : ""}`}
              aria-pressed={favOnly}
              onClick={() => setFavOnly((v) => !v)}
              title={lang === "en" ? "Show favorites only" : lang === "uz" ? "Faqat tanlanganlar" : "Только избранное"}
            >
              <span className="fav-star">{favOnly ? "★" : "☆"}</span>
              <span className="market-btn-label">{lang === "en" ? "Favorites" : lang === "uz" ? "Tanlanganlar" : "Избранное"}</span>
            </button>
          )}
          {/* ТЗ §4: dormant listings are hidden, not dropped — the count says
              how many, so their absence is a stated fact rather than a silence. */}
          {dormantCount > 0 && (
            <button
              type="button"
              className={`market-fav-filter ${showInactive ? "active" : ""}`}
              aria-pressed={showInactive}
              onClick={() => setShowInactive((v) => !v)}
              title={lang === "en" ? "No trades for 90 days"
                : lang === "uz" ? "90 kun bitimlarsiz" : "Без сделок более 90 дней"}
            >
              <span className="market-btn-label">
                {lang === "en" ? "Inactive" : lang === "uz" ? "Faol emas" : "Неактивные"}
                {` (${dormantCount})`}
              </span>
            </button>
          )}
          {viewMode === "table" && (
            <label className="market-search">
              <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} />
            </label>
          )}
          {viewMode === "table" && (
            <button type="button" className="market-fav-filter market-export-btn" onClick={exportCsv} title={mt(lang, "exportCsv")}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>
              <span className="market-btn-label">{mt(lang, "exportCsv")}</span>
            </button>
          )}
          {viewMode === "table" && (
            <div className="market-cols-wrap">
              <button
                type="button"
                ref={colsBtnRef}
                className={`market-cols-btn ${colsOpen ? "active" : ""}`}
                aria-haspopup="true" aria-expanded={colsOpen}
                onClick={() => setColsOpen((o) => !o)}
                title={lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"}
              >
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
              </button>
              {colsOpen && (
                <MarketColsPopover
                  anchorRef={colsBtnRef}
                  onClose={() => setColsOpen(false)}
                  title={lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"}
                  closeLabel={lang === "en" ? "Close" : lang === "uz" ? "Yopish" : "Закрыть"}
                >
                  <>
                    <div className="market-cols-search">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
                      <input
                        type="text"
                        value={colsSearch}
                        onChange={(e) => setColsSearch(e.target.value)}
                        placeholder={lang === "en" ? "Search" : lang === "uz" ? "Qidirish" : "Поиск"}
                      />
                    </div>
                    {/* Its own scrollport: the groups scroll here, the search box
                        and the reset footer stay put, and `overscroll-behavior`
                        (CSS) stops the page behind from taking over the gesture. */}
                    <div className="market-cols-body">
                    {(() => {
                      const q = colsSearch.trim().toLowerCase();
                      const matches = (label) => !q || label.toLowerCase().includes(q);
                      const anyMatch = CORE_COLS.some(([, l]) => matches(l)) || MARKET_COLS.some(([, l]) => matches(l));
                      if (!anyMatch) {
                        return <div className="market-cols-empty">{lang === "en" ? "Nothing found" : lang === "uz" ? "Hech narsa topilmadi" : "Ничего не найдено"}</div>;
                      }
                      return (
                        <>
                          {!q && (
                            <div className="market-cols-group">
                              <div className="market-cols-group-body">
                                {CORE_COLS.map(([k, label]) => (
                                  <label key={k} className="market-cols-row market-cols-row-locked">
                                    <input type="checkbox" checked disabled readOnly />
                                    <span>{label}</span>
                                    {/* Same ⓘ as the column header: this panel is where a
                                        reader decides whether a column is worth its width,
                                        which is exactly when they need to know what it
                                        means — before it is on screen to be hovered. */}
                                    <TermInfo termId={k} lang={lang} label={label} />
                                  </label>
                                ))}
                              </div>
                            </div>
                          )}
                          {COL_GROUPS.map((group) => {
                            const cols = group.cols.filter(([, label]) => matches(label));
                            if (!cols.length) return null;
                            const open = q ? true : openGroups.has(group.key);
                            const allOn = group.cols.every(([k]) => visibleCols.has(k));
                            const someOn = group.cols.some(([k]) => visibleCols.has(k));
                            const shownInGroup = group.cols.filter(([k]) => visibleCols.has(k)).length;
                            const setGroupAll = () => setVisibleCols((prev) => {
                              const n = new Set(prev);
                              group.cols.forEach(([k]) => { if (allOn) n.delete(k); else n.add(k); });
                              return n;
                            });
                            return (
                              <div className="market-cols-group" key={group.key}>
                                <button
                                  type="button"
                                  className="market-cols-group-head"
                                  onClick={() => toggleGroup(group.key)}
                                  aria-expanded={open}
                                >
                                  <span className="market-cols-group-title">{group.title}</span>
                                  <span className="market-cols-group-meta">
                                    <span className="market-cols-group-badge">{shownInGroup}</span>
                                    <span className={`market-cols-group-chevron${open ? " open" : ""}`}>›</span>
                                  </span>
                                </button>
                                {open && (
                                  <div className="market-cols-group-body">
                                    {!q && (
                                      <label className="market-cols-row market-cols-all">
                                        <input
                                          type="checkbox"
                                          checked={allOn}
                                          ref={(el) => { if (el) el.indeterminate = someOn && !allOn; }}
                                          onChange={setGroupAll}
                                        />
                                        <span>{lang === "en" ? "All" : lang === "uz" ? "Hammasi" : "Все"}</span>
                                      </label>
                                    )}
                                    {cols.map(([k, label]) => (
                                      <label key={k} className="market-cols-row">
                                        <input
                                          type="checkbox"
                                          checked={visibleCols.has(k)}
                                          onChange={() => toggleCol(k)}
                                        />
                                        <span>{label}</span>
                                        {/* The picker's column key IS the glossary id, so the
                                            row asks for its own definition. A column that is
                                            not an economic term (Источник) renders no marker.
                                            The ⓘ is a <button>: per the HTML spec a label does
                                            not activate for events aimed at interactive
                                            descendants, so asking what P/E means does not
                                            toggle the P/E column. */}
                                        <TermInfo termId={k} lang={lang} label={label} />
                                      </label>
                                    ))}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </>
                      );
                    })()}
                    </div>
                    <div className="market-cols-footer">
                      {/* The two things the headers do that a header does not look
                          like it does. This panel is where a reader comes looking
                          for table controls, so both are stated here as well. */}
                      <span className="market-cols-hint">
                        <span>{lang === "en" ? "Drag column headers to reorder" : lang === "uz" ? "Tartib uchun sarlavhalarni torting" : "Перетаскивайте заголовки для порядка"}</span>
                        <span>{coarsePointer
                          ? (lang === "en" ? "Press and hold a header to sort by two columns"
                            : lang === "uz" ? "Ikki ustun bo‘yicha saralash — sarlavhani uzoq bosing"
                            : "Долгое нажатие — сортировка по двум колонкам")
                          : (lang === "en" ? "Shift + click to sort by two columns"
                            : lang === "uz" ? "Shift + bosish — ikki ustun bo‘yicha saralash"
                            : "Shift + клик — сортировка по двум колонкам")}</span>
                      </span>
                      <button type="button" className="market-cols-reset" onClick={resetColOrder}>
                        {lang === "en" ? "Reset order" : lang === "uz" ? "Tartibni tiklash" : "Сбросить порядок"}
                      </button>
                    </div>
                  </>
                </MarketColsPopover>
              )}
            </div>
          )}
        </div>

        {presentSectors.length > 0 && viewMode === "table" && (
          <div className="sector-filter market-sector-filter">
            <button
              type="button"
              className={`sector-chip${!marketSector ? " active" : ""}`}
              onClick={() => setMarketSector(null)}
            >
              {sectorLabel(lang, "all")}
            </button>
            {presentSectors.map((s) => (
              <button
                key={s}
                type="button"
                className={`sector-chip${marketSector === s ? " active" : ""}`}
                onClick={() => setMarketSector(marketSector === s ? null : s)}
              >
                {sectorLabel(lang, s)}
              </button>
            ))}
          </div>
        )}

        {/* A sort built from two headers is invisible once you scroll — the carets
            are off in the columns that made it. Spell the chain out, in order, with
            one control back to the board's default order.

            It shows from the FIRST sorted column, not the second, for two reasons:
            until now a header click could never be undone (there was no way back to
            "latest session first"), and one sorted column is exactly the moment the
            reader is ready to be told a second one can be added. */}
        {viewMode === "table" && sortKeys.length > 0 && (
          <div className="market-sort-chain">
            <span className="market-sort-chain-label">
              {lang === "en" ? "Sorted by" : lang === "uz" ? "Saralash" : "Сортировка"}:
            </span>
            {sortKeys.map(({ key, dir }, i) => (
              <button
                key={key}
                type="button"
                className="market-sort-chain-chip"
                onClick={() => onSort(key, true)}
                title={lang === "en" ? "Click to flip, again to remove"
                  : lang === "uz" ? "Yoʻnalishni almashtirish uchun bosing, olib tashlash uchun yana bosing"
                  : "Клик — сменить направление, ещё раз — убрать"}
              >
                {sortKeys.length > 1 && <span className="market-sort-chain-rank">{i + 1}</span>}
                <span>{SORT_LABEL_OF[key] || key}</span>
                <span className="market-sort-caret">{dir === "asc" ? "▲" : "▼"}</span>
              </button>
            ))}
            {sortKeys.length === 1 && !sortHintSeen && (
              <span className="market-sort-teach">
                {coarsePointer ? (
                  lang === "en" ? <>press and hold another column to sort by <b>two</b></>
                    : lang === "uz" ? <>ikkinchi kalit uchun boshqa ustunni <b>uzoq bosing</b></>
                    : <>удерживайте другую колонку, чтобы сортировать по <b>двум</b></>
                ) : (
                  lang === "en" ? <><kbd>Shift</kbd> + click another column to sort by <b>two</b></>
                    : lang === "uz" ? <><kbd>Shift</kbd> + boshqa ustunni bosing — <b>ikkita</b> kalit</>
                    : <><kbd>Shift</kbd> + клик по другой колонке — сортировка по <b>двум</b></>
                )}
                <button
                  type="button"
                  className="market-sort-teach-close"
                  onClick={dismissSortHint}
                  aria-label={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                  title={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                >×</button>
              </span>
            )}
            <button type="button" className="market-sort-chain-reset" onClick={clearSort}>
              {lang === "en" ? "Reset" : lang === "uz" ? "Tiklash" : "Сбросить"}
            </button>
          </div>
        )}
        </div>

        {/* ТЗ Дополнение 1 §А.2: bonds get their own table, not a row in the
            equity board — an issue has a value rather than a capitalisation, and
            no earnings for a multiple to divide by. */}
        {viewMode === "table" && type === "bond" ? (
          <BondsTable language={lang} onOpen={onAnalyze} />
        ) : viewMode === "heatmap" ? (
          loading ? (
            <p className="market-empty-cell">{mt(lang, "loading")}</p>
          ) : (
            <MarketHeatmap rows={prepared} companies={companies} securitiesMap={smap} language={lang} onAnalyze={onAnalyze} type={type} mapData={mapData} />
          )
        ) : (
          <>
          <div className="market-table-wrap" ref={wrapRef}>
            <table className="market-table">
              <thead>
                <tr>{headCells}</tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={colSpan} className="market-empty-cell">{mt(lang, "loading")}</td></tr>
                ) : visibleRows.length ? (
                  visibleRows.map((row) => {
                    const sec = smap[row.ticker] || {};
                    const logo = sec.logo_url;
                    const isPreferred = sec.is_preferred || row.share_type === "preferred";
                    const isFav = hasFav(row.ticker);
                    return (
                    <tr key={`${row.ticker}-${row.isin}`}>
                      <td className="market-ticker-cell">
                        <button
                          type="button"
                          className={`market-fav-btn ${isFav ? "is-fav" : ""}`}
                          aria-pressed={isFav}
                          title={isFav
                            ? (lang === "en" ? "Remove from favorites" : lang === "uz" ? "Tanlanganlardan olib tashlash" : "Убрать из избранного")
                            : (lang === "en" ? "Add to favorites" : lang === "uz" ? "Tanlanganlarga qo'shish" : "В избранное")}
                          onClick={(e) => { e.stopPropagation(); onToggleFavorite && onToggleFavorite(row.ticker, row.name); }}
                        >
                          {isFav ? "★" : "☆"}
                        </button>
                        <CompanyLogo logo={logo} name={row.name || row.ticker} ticker={row.ticker} />
                        <div className="market-ticker-info">
                          <button type="button" className="market-ticker-btn" onClick={() => onOpenCompany ? onOpenCompany(row.ticker) : onAnalyze(row.ticker)}>
                            {row.ticker || "—"}
                          </button>
                          <span>{(row.type === "bond" || sec.type === "bond")
                            ? mt(lang, "bondOne")
                            : isPreferred ? mt(lang, "preferred")
                            : row.share_type ? mt(lang, row.share_type)
                            : (row.type || "—")}</span>
                        </div>
                        <button
                          type="button"
                          className="market-info-btn"
                          title={lang === "en" ? "Company info" : lang === "uz" ? "Kompaniya ma'lumoti" : "О компании"}
                          onClick={() => openPanel(row.ticker)}
                        >ℹ</button>
                      </td>
                      <td>
                        <button type="button" className="market-company-name-btn" onClick={() => onOpenCompany && onOpenCompany(row.ticker)}>
                          {row.name || "—"}
                        </button>
                        <span>{row.isin || "—"}</span>
                      </td>
                      {visibleOrder.map((k) => React.cloneElement(CELL_OF[k](row), { key: k }))}
                    </tr>
                    );
                  })
                ) : (
                  <tr><td colSpan={colSpan} className="market-empty-cell">{favOnly
                    ? (lang === "en" ? "No favorites yet — tap ☆ next to a company to track it."
                       : lang === "uz" ? "Hali tanlanganlar yo'q — kuzatish uchun kompaniya yonidagi ☆ ni bosing."
                       : "Пока нет избранного — нажмите ☆ рядом с компанией, чтобы следить за ней.")
                    : mt(lang, "empty")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
          <MarketStickyHead
            wrapRef={wrapRef}
            cells={headCells}
            colSignature={visibleOrder.join("|")}
            rowCount={visibleRows.length}
            loading={loading}
          />
          <MarketFloatScroll
            wrapRef={wrapRef}
            colSignature={visibleOrder.join("|")}
            rowCount={visibleRows.length}
            loading={loading}
          />
          </>
        )}
      </article>

      {panelTicker && (
        <CompanyInfoPanel
          ticker={panelTicker}
          secInfo={smap[panelTicker]}
          wikiInfo={panelWiki}
          language={language}
          onClose={() => { setPanelTicker(null); setPanelWiki(null); }}
          loading={panelWikiLoading}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// CatalogView helpers
// ---------------------------------------------------------------------------

function PriceSparkline({ points, language }) {
  if (!points || points.length < 2) return null;
  const closes = points.map((p) => p.close).filter((v) => v != null && v > 0);
  if (closes.length < 2) return null;
  const W = 280, H = 64, PAD = 4;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const xs = closes.map((_, i) => PAD + (i / (closes.length - 1)) * (W - PAD * 2));
  const ys = closes.map((v) => PAD + (1 - (v - min) / range) * (H - PAD * 2));
  const polyline = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  const areaPath = `M${xs[0]},${H} ` + xs.map((x, i) => `L${x},${ys[i]}`).join(" ") + ` L${xs[xs.length - 1]},${H} Z`;
  const first = closes[0], last = closes[closes.length - 1];
  const pct = ((last - first) / first * 100).toFixed(1);
  const tone = last >= first ? "pos" : "neg";
  const color = tone === "pos" ? "#6ef0c1" : "#f87171";
  const firstDate = points[0]?.date;
  const lastDate = points[points.length - 1]?.date;
  return (
    <div className="catalog-sparkline">
      <div className="catalog-sparkline-meta">
        <span className="catalog-sparkline-price">{last.toLocaleString(language === "en" ? "en-US" : "ru-RU")} сум</span>
        <span className={`catalog-sparkline-change ${tone}`}>{tone === "pos" ? "+" : ""}{pct}%</span>
        <span className="catalog-sparkline-period muted">{firstDate} – {lastDate}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="catalog-sparkline-svg" preserveAspectRatio="none">
        <defs>
          <linearGradient id="spk-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#spk-grad)" />
        <polyline points={polyline} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// CatalogView
// ---------------------------------------------------------------------------

function clg(language, key) {
  const parts = key.split(".");
  let cur = (TEXTS[language] || TEXTS.ru).catalog;
  for (const part of parts) {
    if (!cur || typeof cur !== "object") return key;
    cur = cur[part];
  }
  return cur !== undefined ? cur : key;
}

// The catalog tables label their rows with the filing's own field names; the
// glossary keys them by term. One map, used by both tables.
const FIN_TERM_OF = {
  revenue: "finRevenue",
  net_income: "finNet",
  total_assets: "totalAssets",
  equity: "equity",
  total_liabilities: "finLiab",
};

function CatalogRatioTable({ result, language }) {
  const lang = language;
  const metrics = result.metrics || {};
  const prevMetrics = result.prev_metrics || {};
  const vals = result.source_values || {};
  const labelMap = (TEXTS[lang] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[lang] || TEXTS.ru).catalog.dynamicsLabels;
  const fmt = (v) => (v === null || v === undefined ? clg(lang, "noValue") : `${Number(v).toFixed(1)}%`);
  const fmtDE = (v) => (v === null || v === undefined ? clg(lang, "noValue") : Number(v).toFixed(2));
  const fmtRaw = (v) => {
    if (v === null || v === undefined) return clg(lang, "noValue");
    return new Intl.NumberFormat(lang === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };

  const renderCard = (k, v) => {
    const prev = prevMetrics[k];
    const hasDelta = prev !== null && prev !== undefined && v !== null && v !== undefined;
    const delta = hasDelta ? (Number(v) - Number(prev)).toFixed(1) : null;
    const up = delta !== null && Number(delta) > 0;
    const down = delta !== null && Number(delta) < 0;
    const sectorVal = result.sector_avg?.[k];
    return (
      <div key={k} className="catalog-ratio-card">
        <span className="ratio-name">{labelMap[k] || k}</span>
        <strong className="ratio-value">{k === "debt_to_equity" ? fmtDE(v) : fmt(v)}</strong>
        {delta !== null && (
          <div className={`ratio-delta ${up ? "pos" : down ? "neg" : "neutral"}`}>
            {up ? "↑" : down ? "↓" : "→"} {up ? "+" : ""}{delta}{k !== "debt_to_equity" ? "%" : ""}
            <span className="ratio-delta-label"> vs {result.prev_year}</span>
          </div>
        )}
        {sectorVal !== undefined && sectorVal !== null && (
          <div className="ratio-sector-avg">
            ∅ {k === "debt_to_equity" ? fmtDE(sectorVal) : fmt(sectorVal)}
            {result.sector_avg?.n ? <span className="ratio-delta-label"> ({result.sector_avg.n})</span> : null}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="catalog-result-body">
      <div className="catalog-ratio-grid">
        {Object.entries(metrics).map(([k, v]) => renderCard(k, v))}
      </div>
      <table className="catalog-source-table">
        <tbody>
          {Object.entries(vals).filter(([, v]) => v !== null).map(([k, v]) => (
            <tr key={k}><td>{valLabels[k] || k}<TermInfo termId={FIN_TERM_OF[k]} lang={lang} label={valLabels[k]} /></td><td className="num">{fmtRaw(v)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CatalogDynamicsTable({ result, language }) {
  const years = result.years || [];
  const series = result.series || {};
  const quarterly = result.quarterly || [];
  const labels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const metricKeys = Object.keys(labels);
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  if (!years.length && !quarterly.length) return <p className="muted">{clg(language, "noReports")}</p>;
  return (
    <div className="catalog-result-body">
      {years.length > 0 && (
        <div className="catalog-table-wrap">
          <table className="market-table">
            <thead>
              <tr>
                <th>{language === "ru" ? "Показатель" : language === "uz" ? "Ko'rsatkich" : "Metric"}</th>
                {years.map((y) => <th key={y} className="num">{y}</th>)}
              </tr>
            </thead>
            <tbody>
              {Object.entries(series).map(([key, vals]) => (
                <tr key={key}>
                  <td>{labels[key] || key}</td>
                  {vals.map((v, i) => <td key={i} className="num">{fmtN(v)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {quarterly.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <div className="panel-label" style={{ marginBottom: 8 }}>
            {language === "ru" ? "Поквартальная динамика" : language === "uz" ? "Choraklik dinamika" : "Quarterly dynamics"}
          </div>
          <div className="catalog-table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{language === "ru" ? "Период" : "Period"}</th>
                  {metricKeys.map((m) => <th key={m} className="num">{labels[m] || m}</th>)}
                </tr>
              </thead>
              <tbody>
                {quarterly.map((row) => (
                  <tr key={row.label}>
                    <td>{row.label}</td>
                    {metricKeys.map((m) => <td key={m} className="num">{fmtN(row[m])}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {result.seasonality && (
        <div style={{ marginTop: 20 }}>
          <div className="panel-label" style={{ marginBottom: 8 }}>
            {language === "ru" ? "Сезонность (выручка по кварталам)" : language === "uz" ? "Mavsumiylik (choraklar bo'yicha daromad)" : "Seasonality (revenue by quarter)"}
          </div>
          {result.seasonality.insufficient ? (
            <p className="muted">
              {language === "ru"
                ? "Недостаточно данных для сезонного анализа (требуется ≥3 лет истории)."
                : language === "uz"
                ? "Mavsumiy tahlil uchun ma'lumot yetarli emas (≥3 yil tarix kerak)."
                : "Insufficient data for seasonal analysis (≥3 years of history required)."}
            </p>
          ) : (
            <div className="catalog-table-wrap">
              <table className="market-table">
                <thead>
                  <tr>{[1, 2, 3, 4].map((q) => <th key={q} className="num">Q{q}</th>)}</tr>
                </thead>
                <tbody>
                  <tr>{[1, 2, 3, 4].map((q) => <td key={q} className="num">{fmtN(result.seasonality.quarter_avg?.[q])}</td>)}</tr>
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CatalogCompareTable({ result, language }) {
  const p1 = result.period1 || {};
  const p2 = result.period2 || {};
  const m1 = p1.metrics || {};
  const m2 = p2.metrics || {};
  const v1 = p1.source_values || {};
  const v2 = p2.source_values || {};
  const ratioLabels = (TEXTS[language] || TEXTS.ru).catalog.ratioLabels;
  const valLabels = (TEXTS[language] || TEXTS.ru).catalog.dynamicsLabels;
  const periodLabel = (p) => p.quarter > 0 ? `Q${p.quarter} ${p.year}` : `${p.year}`;
  const fmt = (v, isPercent = true) => (v === null || v === undefined ? "—" : isPercent ? `${v}%` : String(v));
  const fmtN = (v) => {
    if (v === null || v === undefined) return "—";
    return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(v);
  };
  const diff = (a, b) => {
    if (a === null || b === null || a === undefined || b === undefined) return null;
    return Math.round((a - b) * 100) / 100;
  };
  return (
    <div className="catalog-result-body">
      <div className="catalog-table-wrap">
        <table className="market-table">
          <thead>
            <tr>
              <th>{language === "ru" ? "Показатель" : "Metric"}</th>
              <th className="num">{periodLabel(p1)}</th>
              <th className="num">{periodLabel(p2)}</th>
              <th className="num">{language === "ru" ? "Изменение" : "Change"}</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys({ ...v1, ...v2 }).map((k) => (
              <tr key={k}>
                <td>{valLabels[k] || k}<TermInfo termId={FIN_TERM_OF[k]} lang={normalizeLanguage(language)} label={valLabels[k]} /></td>
                <td className="num">{fmtN(v1[k])}</td>
                <td className="num">{fmtN(v2[k])}</td>
                <td className={`num ${diff(v1[k], v2[k]) > 0 ? "tone-good" : diff(v1[k], v2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(v1[k], v2[k]) !== null ? fmtN(diff(v1[k], v2[k])) : "—"}
                </td>
              </tr>
            ))}
            {Object.entries(ratioLabels).map(([k]) => (
              <tr key={`r-${k}`}>
                <td>{ratioLabels[k]}</td>
                <td className="num">{fmt(m1[k], k !== "debt_to_equity")}</td>
                <td className="num">{fmt(m2[k], k !== "debt_to_equity")}</td>
                <td className={`num ${diff(m1[k], m2[k]) > 0 ? "tone-good" : diff(m1[k], m2[k]) < 0 ? "tone-danger" : ""}`}>
                  {diff(m1[k], m2[k]) !== null ? `${diff(m1[k], m2[k])}${k !== "debt_to_equity" ? "%" : ""}` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CatalogView({ language, companies, token, addToast, onNavigateToAnalysis, initialStatus, user }) {
  const lang = normalizeLanguage(language);
  const [status, setStatus] = useState(initialStatus || null);
  const [catalogComps, setCatalogComps] = useState([]);
  const [compsLoading, setCompsLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [ticker, setTicker] = useState("");
  const [index, setIndex] = useState(null);
  const [indexLoading, setIndexLoading] = useState(false);
  const [form, setForm] = useState("NSBU");
  const [year, setYear] = useState("");
  const [quarter, setQuarter] = useState(0);
  const [analysisType, setAnalysisType] = useState("financial");
  const [compareTicker, setCompareTicker] = useState("");
  const [compareYear, setCompareYear] = useState("");
  const [compareQuarter, setCompareQuarter] = useState(0);
  const [result, setResult] = useState(null);
  const [resultLoading, setResultLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sparkline, setSparkline] = useState(null);
  const [sparklineLoading, setSparklineLoading] = useState(false);

  const apiFetch = (path, options = {}) => {
    const stored = localStorage.getItem(STORAGE_KEY) || "";
    return fetch(path, { ...options, headers: { "Content-Type": "application/json", ...(stored ? { Authorization: `Bearer ${stored}` } : {}), ...(options.headers || {}) } });
  };

  const loadStatus = async () => {
    try {
      const res = await apiFetch("/api/catalog/status");
      const data = await res.json();
      if (res.ok) setStatus(data);
    } catch { /* optional */ }
  };

  const loadCatalogComps = async () => {
    setCompsLoading(true);
    try {
      const res = await apiFetch("/api/catalog/companies");
      const data = await res.json();
      if (res.ok) setCatalogComps(data.companies || []);
    } catch { /* ignore */ }
    finally { setCompsLoading(false); }
  };

  const loadIndex = async (t) => {
    setIndexLoading(true);
    setIndex(null);
    setYear("");
    setQuarter(0);
    setResult(null);
    try {
      const res = await apiFetch(`/api/catalog/index/${t}`);
      const data = await res.json();
      if (res.ok) setIndex(data);
    } catch { /* ignore */ }
    finally { setIndexLoading(false); }
  };

  useEffect(() => { loadStatus(); loadCatalogComps(); }, []);
  useEffect(() => { if (ticker) loadIndex(ticker); else { setIndex(null); setYear(""); setQuarter(0); setResult(null); } }, [ticker]);
  useEffect(() => { setYear(""); setQuarter(0); setResult(null); }, [form, ticker]);
  useEffect(() => {
    if (!ticker) { setSparkline(null); return; }
    setSparklineLoading(true);
    setSparkline(null);
    apiFetch(`/api/price-history/${ticker}`)
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.points?.length >= 2) setSparkline(d.points); })
      .catch(() => {})
      .finally(() => setSparklineLoading(false));
  }, [ticker]);

  const handleSync = async (specificTicker = null) => {
    if (!token) { addToast(lang === "ru" ? "Войдите для синхронизации" : "Sign in to sync", "error"); return; }
    setSyncing(true);
    try {
      const body = { force: true, ...(specificTicker ? { ticker: specificTicker } : {}) };
      const res = await apiFetch("/api/catalog/sync", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sync failed");
      addToast(clg(lang, "syncDone"), "success");
      loadStatus();
      loadCatalogComps();
      if (ticker) loadIndex(ticker);
    } catch (err) { addToast(err.message, "error"); }
    finally { setSyncing(false); }
  };

  const handleRunAnalysis = async () => {
    if (!token) { addToast(lang === "ru" ? "Войдите для анализа" : "Sign in to analyze", "error"); return; }
    if (!ticker || !year) return;
    setResultLoading(true);
    setResult(null);
    try {
      const body = {
        ticker, year: parseInt(year), quarter, form, analysis_type: analysisType, language: lang,
        ...(compareTicker ? { compare_ticker: compareTicker } : {}),
        ...(compareYear ? { compare_year: parseInt(compareYear), compare_quarter: compareQuarter } : {}),
      };
      const res = await apiFetch("/api/catalog/analyze", { method: "POST", body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Analysis failed");
      setResult(data);
    } catch (err) { addToast(err.message, "error"); }
    finally { setResultLoading(false); }
  };

  // Derived availability helpers
  const avail = index?.availability || {};
  const formAvail = avail[form] || { annual: [], quarter: [] };
  const availYears = [...new Set([...(formAvail.annual || []), ...(formAvail.quarter || [])].map((r) => r.year))].filter(Boolean).sort((a, b) => b - a);
  const availQuarters = year ? (formAvail.quarter || []).filter((r) => r.year === parseInt(year)).map((r) => r.quarter).sort() : [];
  const isAnnualAvail = year ? (formAvail.annual || []).some((r) => r.year === parseInt(year)) : false;
  const isCurrentAvail = year ? (quarter === 0 ? isAnnualAvail : (formAvail.quarter || []).some((r) => r.year === parseInt(year) && r.quarter === quarter)) : false;
  const currentReport = year ? (quarter === 0
    ? (formAvail.annual || []).find((r) => r.year === parseInt(year))
    : (formAvail.quarter || []).find((r) => r.year === parseInt(year) && r.quarter === quarter)
  ) : null;

  const needsComparePeriod = ["quarter_compare", "annual_compare"].includes(analysisType);
  const needsCompareTicker = analysisType === "multi_company";

  const filteredComps = catalogComps.filter((c) => {
    const q = search.toLowerCase();
    return !q || c.ticker.toLowerCase().includes(q) || (c.company_name || "").toLowerCase().includes(q);
  });

  const analysisTypesObj = (TEXTS[lang] || TEXTS.ru).catalog.analysisTypes;
  const formsObj = (TEXTS[lang] || TEXTS.ru).catalog.forms;
  const periodsObj = (TEXTS[lang] || TEXTS.ru).catalog.periods;

  const renderResult = () => {
    if (!result) return null;
    const type = result.analysis_type;

    if (type === "ratio") return <CatalogRatioTable result={result} language={lang} />;
    if (type === "dynamics") return <CatalogDynamicsTable result={result} language={lang} />;
    if (type === "quarter_compare" || type === "annual_compare") return <CatalogCompareTable result={result} language={lang} />;

    // AI analysis — three distinct lenses on one computed report:
    //   financial      → полный финансовый разбор (статья с таблицами)
    //   swot           → сильные/слабые стороны и катализаторы
    //   recommendation → скоринг, оценка цены и итоговый вердикт
    const sections = result.sections || {};
    const TYPE_SECTIONS = {
      financial: ["ДОСЬЕ", "ЧТО_С_ДЕНЬГАМИ", "ТРЕНД", "ЭФФЕКТИВНОСТЬ", "ОЦЕНКА_ЦЕНЫ", "РЫНОЧНЫЕ_ДАННЫЕ"],
      swot: ["СИЛЬНЫЕ_СТОРОНЫ", "СЛАБЫЕ_СТОРОНЫ", "КАТАЛИЗАТОРЫ"],
      recommendation: ["СКОРИНГ", "ОЦЕНКА_ЦЕНЫ", "ВЕРДИКТ", "ИТОГ"],
    };
    const wanted = TYPE_SECTIONS[type] || null;

    // SWOT & recommendation: curated raw sections rendered as expandable cards.
    if (wanted && type !== "financial") {
      const picked = wanted.filter((k) => typeof sections[k] === "string" && sections[k].trim());
      if (picked.length) {
        return (
          <div className="catalog-result-body">
            {picked.map((k, i) => (
              <SectionCard key={k} title={getSectionTitle(lang, k)} body={sections[k]} index={i} open language={lang} />
            ))}
          </div>
        );
      }
    }

    // financial (and fallback): article report with tables, filtered to the lens.
    const allArticle = result.article_report?.sections || [];
    const articleSections = wanted ? allArticle.filter((s) => wanted.includes(s.id)) : allArticle;
    const hasArticle = articleSections.length > 0;
    const allEntries = Object.entries(sections).filter(([, v]) => v && typeof v === "string");
    const sectionEntries = wanted ? allEntries.filter(([k]) => wanted.includes(k)) : allEntries;
    return (
      <div className="catalog-result-body">
        {hasArticle ? articleSections.map((section, i) => (
          <div key={section.id || i} className="catalog-section">
            <div className="panel-label">{section.title || getSectionTitle(lang, section.id)}</div>
            <div className="catalog-section-text">
              <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`cat-${i}`} />
            </div>
          </div>
        )) : sectionEntries.map(([key, text], i) => (
          <SectionCard key={key} title={getSectionTitle(lang, key)} body={text} index={i} open language={lang} />
        ))}
        {!hasArticle && !sectionEntries.length && (
          <p className="muted">{lang === "ru" ? "Нет данных для отображения" : "No data to display"}</p>
        )}
      </div>
    );
  };

  return (
    <section className="catalog-layout">
      {/* Status bar */}
      <article className="panel catalog-header">
        <div className="catalog-header-copy">
          <div className="panel-label">{clg(lang, "title")}</div>
          <p className="muted">{clg(lang, "subtitle")}</p>
        </div>
        <div className="catalog-header-stats">
          {status ? (
            <>
              <span className="status-badge">{status.companies_synced} {clg(lang, "companies")} · {status.total_reports} {clg(lang, "totalReports")}</span>
              {status.last_sync && <span className="status-badge muted">{clg(lang, "lastSync")}: {formatMarketTimestamp(status.last_sync, lang)}</span>}
            </>
          ) : <span className="status-badge muted">{clg(lang, "loading")}</span>}
          {/* ТЗ Дополнение 1 §Б.6: «Синхронизировать всё» calls an administrative
              route and belongs in the administrative section. It stood in the
              public interface, where any visitor could start a full re-sync. */}
          {user?.is_admin && (
            <button className="ghost-btn" type="button" onClick={() => handleSync()} disabled={syncing}>
              {syncing ? clg(lang, "syncing") : clg(lang, "syncAll")}
            </button>
          )}
        </div>
      </article>

      <div className="catalog-body">
        {/* Sidebar: company list */}
        <aside className="catalog-sidebar">
          <input
            className="search-input"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={clg(lang, "searchPlaceholder")}
          />
          {compsLoading ? (
            <div className="catalog-list-loading">{clg(lang, "loading")}</div>
          ) : filteredComps.length === 0 ? (
            <div className="catalog-list-empty">
              {catalogComps.length === 0 ? clg(lang, "empty") : clg(lang, "noReports")}
            </div>
          ) : (
            <div className="catalog-company-list">
              {filteredComps.map((c) => (
                <button
                  key={c.ticker}
                  type="button"
                  className={`catalog-company-item ${ticker === c.ticker ? "active" : ""}`}
                  onClick={() => setTicker(c.ticker)}
                >
                  <CompanyLogo logo={c.logo} name={c.company_name} ticker={c.ticker} />
                  <div className="catalog-company-item-body">
                    <div className="catalog-company-item-head">
                      <strong>{c.ticker}</strong>
                      <em>{c.total_count || 0} {clg(lang, "reports")}</em>
                    </div>
                    <span className="catalog-company-name">{c.company_name}</span>
                    {c.total_count > 0 && (
                      <div className="catalog-company-badges">
                        {c.nsbu_count > 0 && <span className="catalog-form-badge">{formsObj.NSBU} {c.nsbu_count}</span>}
                        {c.msfo_count > 0 && <span className="catalog-form-badge">{formsObj.MSFO} {c.msfo_count}</span>}
                        {c.audit_count > 0 && <span className="catalog-form-badge">{formsObj.Audition} {c.audit_count}</span>}
                      </div>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* Main area */}
        <main className="catalog-main">
          {!ticker ? (
            <div className="empty-state"><p className="empty-copy">{clg(lang, "selectCompany")}</p></div>
          ) : indexLoading ? (
            <div className="catalog-loading">{clg(lang, "loading")}</div>
          ) : (
            <>
              {/* Company header */}
              <div className="catalog-company-header">
                <div>
                  <h2>{index?.company_name || ticker}</h2>
                  <span className="status-badge muted">{ticker}</span>
                  {index?.sector && <span className="status-badge">{sectorLabel(lang, index.sector)}</span>}
                  {index?.last_synced_at && <span className="status-badge muted">{clg(lang, "lastSync")}: {formatMarketTimestamp(index.last_synced_at, lang)}</span>}
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <button className="ghost-btn" type="button" onClick={() => handleSync(ticker)} disabled={syncing}>
                    {syncing ? clg(lang, "syncing") : clg(lang, "syncCompany")}
                  </button>
                  {onNavigateToAnalysis && (
                    <button className="ghost-btn" type="button" onClick={() => onNavigateToAnalysis(ticker)}>
                      {lang === "ru" ? "Открыть в Анализе" : lang === "uz" ? "Tahlilda ochish" : "Open in Analysis"}
                    </button>
                  )}
                </div>
              </div>

              {/* Price sparkline */}
              {(sparkline || sparklineLoading) && (
                <div className="catalog-sparkline-wrap">
                  {sparklineLoading
                    ? <div className="catalog-list-loading">{lang === "ru" ? "Загрузка графика..." : "Loading chart..."}</div>
                    : <PriceSparkline points={sparkline} language={lang} />}
                </div>
              )}

              {/* Form tabs */}
              <div className="catalog-form-tabs">
                {["NSBU", "MSFO", "Audition"].map((f) => (
                  <button key={f} type="button" className={`tab-btn ${form === f ? "active" : ""}`} onClick={() => setForm(f)}>
                    {formsObj[f]}
                  </button>
                ))}
              </div>

              {/* Year selector */}
              {availYears.length > 0 ? (
                <div className="catalog-year-row">
                  {availYears.map((y) => (
                    <button key={y} type="button"
                      className={`catalog-year-btn ${year === String(y) ? "active" : ""}`}
                      onClick={() => { setYear(String(y)); setQuarter(0); setResult(null); }}>
                      {y}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="muted catalog-no-form">{clg(lang, "notPublished")}</p>
              )}

              {/* Quarter selector for NSBU */}
              {year && form === "NSBU" && (
                <div className="catalog-quarter-row">
                  <button type="button"
                    className={`catalog-period-btn ${quarter === 0 ? "active" : ""} ${isAnnualAvail ? "" : "unavailable"}`}
                    onClick={() => { setQuarter(0); setResult(null); }}>
                    {periodsObj.annual}
                  </button>
                  {[1, 2, 3].map((q) => {
                    const qAvail = availQuarters.includes(q);
                    return (
                      <button key={q} type="button"
                        className={`catalog-period-btn ${quarter === q ? "active" : ""} ${qAvail ? "" : "unavailable"}`}
                        onClick={() => { if (qAvail) { setQuarter(q); setResult(null); } }}>
                        {periodsObj[`q${q}`]}
                      </button>
                    );
                  })}
                </div>
              )}

              {/* Availability indicator */}
              {year && (
                <div className={`catalog-avail ${isCurrentAvail ? "avail-yes" : "avail-no"}`}>
                  {isCurrentAvail ? (
                    <>
                      <span>{clg(lang, "available")}</span>
                      {/* openinfo's /reports/to_pdf{id} route is keyed on an id space
                          that doesn't match the accounting-report id, so NSBU PDFs
                          often resolve to the wrong company or 500. The export-excel
                          API is correct (verified per company), so prefer Excel and
                          only show a PDF when it's a real document URL (MSFO/Audit). */}
                      {/* openinfo's export-excel returns the full NSBU report (balance +
                          income) in one workbook, so form1/form2 ids are usually identical.
                          Show the second link only if it's genuinely a different file. */}
                      {currentReport?.excel_url && (
                        <a className="ghost-btn catalog-pdf-btn" href={currentReport.excel_url} target="_blank" rel="noreferrer">
                          {(currentReport?.excel_url_form1 && currentReport.excel_url_form1 !== currentReport.excel_url) ? clg(lang, "excelIncome") : clg(lang, "excelReport")}
                        </a>
                      )}
                      {currentReport?.excel_url_form1 && currentReport.excel_url_form1 !== currentReport.excel_url && (
                        <a className="ghost-btn catalog-pdf-btn" href={currentReport.excel_url_form1} target="_blank" rel="noreferrer">
                          {clg(lang, "excelBalance")}
                        </a>
                      )}
                      {currentReport?.pdf_url && !currentReport.pdf_url.includes("/reports/to_pdf") && (
                        <a className="ghost-btn catalog-pdf-btn" href={currentReport.pdf_url} target="_blank" rel="noreferrer">
                          {clg(lang, "pdfReport")}
                        </a>
                      )}
                    </>
                  ) : (
                    <span>{clg(lang, "notPublished")}</span>
                  )}
                </div>
              )}

              {/* Analysis controls */}
              {year && isCurrentAvail && (
                <div className="catalog-analysis-controls">
                  <label className="catalog-field">
                    <span>{clg(lang, "analysisLabel")}</span>
                    <select value={analysisType} onChange={(e) => { setAnalysisType(e.target.value); setResult(null); }}>
                      {Object.entries(analysisTypesObj).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </label>

                  {needsCompareTicker && (
                    <label className="catalog-field">
                      <span>{clg(lang, "compareWith")}</span>
                      <select value={compareTicker} onChange={(e) => setCompareTicker(e.target.value)}>
                        <option value="">—</option>
                        {filteredComps.filter((c) => c.ticker !== ticker).map((c) => (
                          <option key={c.ticker} value={c.ticker}>{c.ticker} — {c.company_name}</option>
                        ))}
                      </select>
                    </label>
                  )}

                  {needsComparePeriod && (
                    <div className="catalog-compare-period">
                      <span>{clg(lang, "comparePeriod")}</span>
                      <div className="catalog-compare-period-row">
                        <select value={compareYear} onChange={(e) => setCompareYear(e.target.value)}>
                          <option value="">—</option>
                          {availYears.map((y) => <option key={y} value={y}>{y}</option>)}
                        </select>
                        {form === "NSBU" && (
                          <select value={compareQuarter} onChange={(e) => setCompareQuarter(parseInt(e.target.value))}>
                            <option value={0}>{periodsObj.annual}</option>
                            {[1, 2, 3].map((q) => <option key={q} value={q}>{periodsObj[`q${q}`]}</option>)}
                          </select>
                        )}
                      </div>
                    </div>
                  )}

                  <button className="primary-btn" type="button" onClick={handleRunAnalysis} disabled={resultLoading}>
                    {resultLoading ? clg(lang, "analysisLoading") : clg(lang, "runAnalysis")}
                  </button>
                </div>
              )}

              {/* Result */}
              {result && (
                <article className="panel catalog-result-panel" id="catalog-print-target">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{analysisTypesObj[result.analysis_type] || result.analysis_type}</div>
                      <h3>{result.company_name || ticker} · {result.year}{result.quarter > 0 ? ` Q${result.quarter}` : ""}</h3>
                      {result.sector && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{result.sector}</div>}
                    </div>
                    <button className="ghost-btn catalog-export-btn no-print" type="button" onClick={() => window.print()}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="15" height="15"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                      {clg(lang, "exportPdf")}
                    </button>
                  </div>
                  {renderResult()}
                </article>
              )}
            </>
          )}
        </main>
      </div>
    </section>
  );
}

function App() {
  // Thresholds and flags are fetched once, before anything reads them, so the
  // interface applies the SAME numbers the calculation layer did (ТЗ §10.10).
  useEffect(() => { loadConfig(); }, []);  const defaultReportYear = Math.max(2000, new Date().getFullYear() - 1);
  const reportYearOptions = Array.from({ length: 12 }, (_, index) => String(defaultReportYear + 1 - index));
  const [language, setLanguage] = useState(() => normalizeLanguage(localStorage.getItem(LANGUAGE_KEY) || "ru"));
  const [theme, setTheme] = useState(() => {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return "dark"; // Default to dark theme (Finam AI style)
  });
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [activeView, setActiveView] = useState(() => pathToView(window.location.pathname).view);
  const [notifCount, setNotifCount] = useState(0);
  const [notifItems, setNotifItems] = useState([]);
  const [notifOpen, setNotifOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [catalogStatus, setCatalogStatus] = useState(null);
  const [authTab, setAuthTab] = useState("login");
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ full_name: "", email: "", password: "" });
  const [authMessage, setAuthMessage] = useState("");
  const [analysisCompany, setAnalysisCompany] = useState("");
  const [companyTicker, setCompanyTicker] = useState(() => pathToView(window.location.pathname).ticker);
  const [newsId, setNewsId] = useState(() => pathToView(window.location.pathname).newsId);
  const [adminSection, setAdminSection] = useState(
    () => pathToView(window.location.pathname).adminSection || "overview");
  const [prevView, setPrevView] = useState("market");
  const [selectedSector, setSelectedSector] = useState(null);
  const [includeAllExcelReports, setIncludeAllExcelReports] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [excelReportLimit, setExcelReportLimit] = useState("");
  const [reportAnalysisType, setReportAnalysisType] = useState("latest");
  const [reportQuarter, setReportQuarter] = useState("1");
  const [reportCurrentYear, setReportCurrentYear] = useState(String(defaultReportYear));
  const [reportPreviousYear, setReportPreviousYear] = useState(String(defaultReportYear - 1));
  const [reportForm, setReportForm] = useState("NAS");
  const [availablePeriods, setAvailablePeriods] = useState(null);
  const [periodsLoading, setPeriodsLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisMessage, setAnalysisMessage] = useState("");
  const [compareCompanies, setCompareCompanies] = useState(["", "", "", "", ""]);
  const [compareResult, setCompareResult] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareMessage, setCompareMessage] = useState("");
  const [compareAiSummary, setCompareAiSummary] = useState(true);
  const [profileForm, setProfileForm] = useState({ full_name: "" });
  const [profileAvatarFile, setProfileAvatarFile] = useState(null);
  const [profileAvatarPreview, setProfileAvatarPreview] = useState("");
  const [showProfileEdit, setShowProfileEdit] = useState(false);
  const [profileAvatarCleared, setProfileAvatarCleared] = useState(false);
  const [historySearch, setHistorySearch] = useState("");
  const [historyMode, setHistoryMode] = useState("all");
  const [marketRows, setMarketRows] = useState([]);
  const [marketMeta, setMarketMeta] = useState({ updated_at: null, count: 0 });
  const [marketType, setMarketType] = useState("stock");
  const [marketQuery, setMarketQuery] = useState("");
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketMessage, setMarketMessage] = useState("");
  const [securitiesMap, setSecuritiesMap] = useState({});
  const [marketFinancials, setMarketFinancials] = useState({});
  const [marketTradeStats, setMarketTradeStats] = useState({});
  const [toasts, setToasts] = useState([]);

  // Dynamic year/quarter options: fallback to static list until per-company periods are fetched
  const annualYearOptions = availablePeriods?.annual_years?.map(String) || reportYearOptions;
  const quarterlyYearOptions = availablePeriods
    ? [...new Set(availablePeriods.quarterly.map((q) => q.year))].sort((a, b) => b - a).map(String)
    : reportYearOptions;
  const availableQuartersForYear = availablePeriods
    ? availablePeriods.quarterly.filter((q) => String(q.year) === reportCurrentYear).map((q) => q.quarter).sort((a, b) => a - b)
    : [1, 2, 3];

  useEffect(() => {
    const lang = normalizeLanguage(language);
    localStorage.setItem(LANGUAGE_KEY, lang);
    document.documentElement.lang = lang;
    document.title = t(lang, "pageTitle");
  }, [language]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (themeMeta) {
      themeMeta.setAttribute("content", theme === "dark" ? "#0a0f1a" : "#f8fafc");
    }
    localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  // Anything that pins itself under the topbar (the board's filter bar, the
  // mirrored column header) needs the topbar's live height, and that height is
  // not a constant: 80px on a desktop, 60px below 1180px, and taller again the
  // moment a language switch wraps the nav. Measure it once here and publish it
  // as --topbar-h so the CSS never has to restate the breakpoints.
  useEffect(() => {
    const bar = document.querySelector(".topbar");
    if (!bar) return undefined;
    let raf = 0;
    const apply = () => {
      raf = 0;
      const h = Math.round(bar.getBoundingClientRect().height);
      if (h > 0) document.documentElement.style.setProperty("--topbar-h", `${h}px`);
    };
    const schedule = () => { if (!raf) raf = requestAnimationFrame(apply); };
    apply();
    const ro = new ResizeObserver(schedule);
    ro.observe(bar);
    window.addEventListener("resize", schedule);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", schedule);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const oauthError = hash.get("oauth_error") || hash.get("error");
    const oauthCode = hash.get("oauth_code");
    const provider = hash.get("provider") || hash.get("oauth");

    const finishLogin = (newToken, providerName) => {
      setToken(newToken);
      localStorage.setItem(STORAGE_KEY, newToken);
      const providerLabel = providerName === "google" ? "Google" : providerName || "";
      addToast(providerLabel ? `${providerLabel}: ${t(language, "auth.messages.loginOk")}` : t(language, "auth.messages.loginOk"), "success");
      setActiveView("profile");
    };

    if (oauthError) {
      addToast(decodeURIComponent(oauthError.replace(/\+/g, " ")), "error");
      clearHash();
    } else if (oauthCode) {
      // The redirect carries a short-lived one-time code, never the token
      // itself (a token in the URL survives in history/logs). Exchange it.
      clearHash();
      fetch("/api/auth/oauth/exchange", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: oauthCode }),
      })
        .then((r) => r.json())
        .then((d) => {
          if (d.ok && d.token) finishLogin(d.token, d.provider || provider);
          else addToast(d.detail || "Sign-in failed", "error");
        })
        .catch(() => addToast("Sign-in failed", "error"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadCompanies().catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language]);

  useEffect(() => {
    if (!token) {
      setUser(null);
      setProfile(null);
      setAnalysisResult(null);
      setCompareResult(null);
      return;
    }
    refreshSession().catch(() => {
      setToken("");
      localStorage.removeItem(STORAGE_KEY);
      setUser(null);
      setProfile(null);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  useEffect(() => {
    if (!user) return;
    loadProfile().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, language]);

  useEffect(() => {
    if (profile?.user?.full_name || profile?.user?.email) {
      setProfileForm((prev) =>
        prev.full_name && prev.full_name !== ""
          ? prev
          : {
              full_name: profile.user.full_name || "",
            }
      );
    }
  }, [profile]);

  useEffect(() => {
    setHistorySearch("");
  }, [activeView]);

  // Keep the browser URL in sync with the active view (push a history entry).
  useEffect(() => {
    const target = viewToPath(activeView, companyTicker, newsId, adminSection);
    if (window.location.pathname !== target) {
      window.history.pushState({ view: activeView }, "", target);
    }
  }, [activeView, companyTicker, newsId, adminSection]);

  // React to browser back/forward by restoring the view from the URL.
  useEffect(() => {
    const onPop = () => {
      const { view, ticker, newsId: popNewsId, adminSection: popSection } = pathToView(window.location.pathname);
      if (ticker) setCompanyTicker(ticker);
      if (popNewsId) setNewsId(popNewsId);
      if (popSection) setAdminSection(popSection);
      setActiveView(view);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  useEffect(() => {
    apiFetch("/api/catalog/status")
      .then((r) => r.json())
      .then((d) => { if (d.ok) setCatalogStatus(d); })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!token) { setNotifCount(0); setNotifItems([]); return; }
    const fetchNotifs = () => {
      apiFetch("/api/notifications")
        .then((r) => r.json())
        .then((d) => { if (d.ok) { setNotifCount(d.count || 0); setNotifItems(d.items || []); } })
        .catch(() => {});
    };
    fetchNotifs();
    const id = setInterval(fetchNotifs, 5 * 60 * 1000);
    return () => clearInterval(id);
  }, [token]);

  // The company page reads the board too — price, previous close, the day's
  // OHLC, turnover, capitalisation and share count all come from it. Opening
  // /company/UZTL directly used to skip this load entirely, so the header had no
  // quote and the Детали box silently dropped its capitalisation row.
  useEffect(() => {
    if (activeView !== "market" && activeView !== "heatmap" && activeView !== "company") return;
    loadMarketStocks().catch((error) => {
      addToast(error.message, "error");
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, marketType, language]);

  useEffect(() => {
    apiFetch("/api/securities")
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.securities) setSecuritiesMap(d.securities); })
      .catch(() => {});
  }, []);

  // NSBU headline indicators (cached, all companies). Refetched when entering the
  // market view so the progressively-filled cache stays reasonably current.
  useEffect(() => {
    if (activeView !== "market" && activeView !== "heatmap" && activeView !== "company") return;
    apiFetch("/api/market/financials")
      .then((r) => r.json())
      .then((d) => { if (d.ok && d.financials) setMarketFinancials(d.financials); })
      .catch(() => {});
    apiFetch("/api/market/trade-stats")
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) return;
        if (d.stats) setMarketTradeStats(d.stats);
        // When OUR pipeline last wrote the board. Merged into the market meta
        // rather than kept apart, because the header badge reads one object.
        setMarketMeta((prev) => ({ ...prev, refreshed_at: d.refreshed_at || null, trade_date: d.trade_date || null }));
      })
      .catch(() => {});
  }, [activeView]);

  // Fetch available periods whenever the analysis company changes
  useEffect(() => {
    const query = analysisCompany.trim();
    if (!query) {
      setAvailablePeriods(null);
      return;
    }
    let cancelled = false;
    setPeriodsLoading(true);
    setAvailablePeriods(null);
    fetch(`/api/periods?company=${encodeURIComponent(query)}`)
      .then((res) => res.json())
      .then((data) => {
        if (cancelled || !data.ok || !data.periods) return;
        setAvailablePeriods(data.periods);
      })
      .catch(() => {}) // fail silently — static fallback remains active
      .finally(() => { if (!cancelled) setPeriodsLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisCompany]);

  // Auto-select the latest available year/quarter when periods arrive for a new company
  useEffect(() => {
    if (!availablePeriods) return;
    if (reportAnalysisType === "quarterly" && availablePeriods.latest_quarterly) {
      const { year, quarter } = availablePeriods.latest_quarterly;
      setReportCurrentYear(String(year));
      setReportQuarter(String(quarter));
      setReportPreviousYear(String(year - 1));
    } else if (reportAnalysisType !== "latest" && availablePeriods.latest_annual_year) {
      const yr = availablePeriods.latest_annual_year;
      setReportCurrentYear(String(yr));
      setReportPreviousYear(String(yr - 1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [availablePeriods]);

  const addToast = (message, tone = "info") => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 3600);
  };

  const clearHash = () => {
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  };

  const apiFetch = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    return fetch(path, { ...options, headers });
  };

  const refreshSession = async () => {
    if (!token) return;
    const res = await apiFetch("/api/auth/me");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Session is invalid");
    setUser(data.user);
  };

  const loadCompanies = async () => {
    const res = await apiFetch("/api/companies");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load companies");
    setCompanies(data.companies || []);
  };

  const openCompanyPage = (ticker) => {
    setPrevView(activeView);
    setCompanyTicker(ticker);
    setActiveView("company");
  };

  // A story opens on our own /news/{id} page instead of jumping to the outlet.
  const openNewsArticle = (item) => {
    const id = item && (item.id != null ? item.id : item);
    if (id == null || id === "") return;
    setNewsId(String(id));
    setActiveView("newsArticle");
  };

  const loadMarketStocks = async () => {
    setMarketLoading(true);
    setMarketMessage(mt(language, "loading"));
    try {
      const params = new URLSearchParams();
      // "ordinary"/"preferred" are share-type subsets the server can't filter (it
      // only knows stock/bond), so fetch stocks and narrow client-side.
      const apiType = (marketType === "preferred" || marketType === "ordinary") ? "stock" : marketType;
      params.set("type", apiType);
      const res = await apiFetch(`/api/market/stocks${params.toString() ? `?${params}` : ""}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not load stock prices");
      setMarketRows(Array.isArray(data.stocks) ? data.stocks : []);
      // Merge, don't replace: `refreshed_at`/`trade_date` come from the
      // trade-stats call, which runs on its own and must survive a reload here.
      setMarketMeta((prev) => ({ ...prev, updated_at: data.updated_at || null, count: data.count || 0, type: data.type || marketType }));
      setMarketMessage(mt(language, "ready"));
    } catch (error) {
      setMarketMessage(error.message);
      throw error;
    } finally {
      setMarketLoading(false);
    }
  };

  const loadProfile = async () => {
    if (!token) return;
    const res = await apiFetch("/api/profile");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not load profile");
    setProfile(data);
    if (data?.user) {
      setProfileForm({ full_name: data.user.full_name || "" });
    }
    return data;
  };

  const setAuthSuccess = (data) => {
    if (data.token) {
      setToken(data.token);
      localStorage.setItem(STORAGE_KEY, data.token);
    }
    if (data.user) {
      setUser(data.user);
      setProfileForm({ full_name: data.user.full_name || "" });
    }
    setAuthMessage(t(language, "auth.messages.loginOk"));
    addToast(t(language, "auth.messages.loginOk"), "success");
    setActiveView("profile");
  };

  const handleLogin = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.loginOk"));
      await loadProfile();
    } catch (error) {
      setAuthMessage(error.message);
      addToast(error.message, "error");
    }
  };

  const handleRegister = async (event) => {
    event.preventDefault();
    setAuthMessage("...");
    try {
      const res = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(registerForm),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Request failed");
      setAuthSuccess(data);
      setAuthMessage(t(language, "auth.messages.registerOk"));
      await loadProfile();
    } catch (error) {
      setAuthMessage(error.message);
      addToast(error.message, "error");
    }
  };

  const handleGoogleLogin = () => {
    window.location.href = "/api/auth/oauth/google/start";
  };

  const handleLogout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore
    }
    localStorage.removeItem(STORAGE_KEY);
    setToken("");
    setUser(null);
    setProfile(null);
    setAnalysisResult(null);
    setCompareResult(null);
    setActiveView("auth");
    addToast(t(language, "auth.messages.logoutOk"), "info");
  };

  const handleAnalysisSubmit = async (event, companyOverride) => {
    if (event && event.preventDefault) event.preventDefault();
    const company = (typeof companyOverride === "string" ? companyOverride : analysisCompany).trim();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    if (!company) {
      addToast(t(language, "analysis.resultEmpty"), "error");
      return;
    }
    if (reportAnalysisType !== "latest" && reportCurrentYear === reportPreviousYear) {
      addToast(language === "en" ? "Choose two different years" : language === "uz" ? "Ikki xil yilni tanlang" : "Выберите два разных года", "error");
      return;
    }

    setAnalysisLoading(true);
    setAnalysisMessage(t(language, "analysis.resultLoading"));
    try {
      const res = await apiFetch("/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          company,
          language,
          include_raw: false,
          force_refresh: forceRefresh,
          include_all_excel_reports: includeAllExcelReports,
          report_analysis_type: reportAnalysisType,
          report_form: reportForm,
          ...(reportAnalysisType !== "latest" ? {
            report_current_year: Number(reportCurrentYear),
            report_previous_year: Number(reportPreviousYear),
          } : {}),
          ...(reportAnalysisType === "quarterly" ? { report_quarter: Number(reportQuarter) } : {}),
          ...(includeAllExcelReports && excelReportLimit.trim() ? { excel_report_limit: Number(excelReportLimit) } : {}),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the analysis");
      setAnalysisResult(data);
      setAnalysisMessage(t(language, "analysis.completed"));
      addToast(`${t(language, "analysis.completed")}: ${data.company_name || company}`, "success");
      setActiveView("analysis");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setAnalysisMessage(error.message);
      setAnalysisResult(null);
    } finally {
      setAnalysisLoading(false);
    }
  };

  // Export the current analysis result to .xlsx (ТЗ §3.13).
  const [exportingExcel, setExportingExcel] = useState(false);
  const handleExportExcel = async () => {
    if (!analysisResult) return;
    setExportingExcel(true);
    try {
      const res = await apiFetch("/api/analyze/export/excel", {
        method: "POST",
        body: JSON.stringify({ result: analysisResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const name = (analysisResult.company_name || analysisResult.input || "analysis").replace(/[^\w-]/g, "_").slice(0, 40);
      link.download = `${name}_analysis.xlsx`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingExcel(false);
    }
  };

  // Server-side PDF export (ТЗ §3.13 / C5) — a generated report, not a browser print.
  const [exportingPdf, setExportingPdf] = useState(false);
  const handleExportPdf = async () => {
    if (!analysisResult) return;
    setExportingPdf(true);
    try {
      const res = await apiFetch("/api/analyze/export/pdf", {
        method: "POST",
        body: JSON.stringify({ result: analysisResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const name = (analysisResult.company_name || analysisResult.input || "analysis").replace(/[^\w-]/g, "_").slice(0, 40);
      link.download = `${name}_analysis.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingPdf(false);
    }
  };

  // Re-run a stored history query with fresh data (ТЗ Блок 5: «Повторить запрос»).
  const handleRepeatAnalysis = (item) => {
    const company = (item?.ticker || item?.company_input || item?.company_name || "").trim();
    if (!company) return;
    setAnalysisCompany(company);
    setActiveView("analysis");
    handleAnalysisSubmit(null, company);
  };

  const updateCompareCompany = (index, value) => {
    setCompareCompanies((current) => current.map((item, itemIndex) => (itemIndex === index ? value : item)));
  };

  const addQuickCompareCompany = (ticker) => {
    setCompareCompanies((current) => {
      const normalized = String(ticker || "").trim();
      if (!normalized) return current;
      if (current.some((item) => item.trim().toLowerCase() === normalized.toLowerCase())) return current;
      const next = [...current];
      const emptyIndex = next.findIndex((item) => !item.trim());
      if (emptyIndex >= 0) {
        next[emptyIndex] = normalized;
      } else {
        next[2] = normalized;
      }
      return next;
    });
  };

  // Server-side comparison export (ТЗ §3.6 / §3.13) — Excel + PDF of the matrix.
  const [exportingCompare, setExportingCompare] = useState("");
  const handleCompareExport = async (kind) => {
    if (!compareResult) return;
    setExportingCompare(kind);
    try {
      const res = await apiFetch(`/api/compare/export/${kind}`, {
        method: "POST",
        body: JSON.stringify({ result: compareResult, language }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `comparison.${kind === "excel" ? "xlsx" : "pdf"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (error) {
      addToast(error.message, "error");
    } finally {
      setExportingCompare("");
    }
  };

  const handleCompareSubmit = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(ct(language, "authRequired"), "error");
      setActiveView("auth");
      return;
    }

    const cleaned = [];
    const seen = new Set();
    for (const item of compareCompanies) {
      const value = String(item || "").trim();
      const key = value.toLowerCase();
      if (value && !seen.has(key)) {
        cleaned.push(value);
        seen.add(key);
      }
    }

    if (cleaned.length < 2) {
      addToast(ct(language, "minRequired"), "error");
      return;
    }

    setCompareLoading(true);
    setCompareMessage(ct(language, "loading"));
    try {
      const res = await apiFetch("/api/compare", {
        method: "POST",
        body: JSON.stringify({
          companies: cleaned.slice(0, 5),
          language,
          include_market_context: false,
          include_ai_summary: compareAiSummary,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not complete the comparison");
      setCompareResult(data);
      setCompareMessage(ct(language, "ready"));
      addToast(`${ct(language, "ready")}: ${cleaned.join(" / ")}`, "success");
      setActiveView("compare");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
      setCompareMessage(error.message);
      setCompareResult(null);
    } finally {
      setCompareLoading(false);
    }
  };

  const handleToggleFavorite = async (ticker, companyName = "") => {
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    const normalized = String(ticker || "").trim();
    if (!normalized) return;
    try {
      const res = await apiFetch("/api/favorites/toggle", {
        method: "POST",
        body: JSON.stringify({ ticker: normalized, company_name: companyName || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not update favorites");
      addToast(`${normalized} ${data.favorited ? "saved" : "removed"}`, "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const handleProfileSave = async (event) => {
    event.preventDefault();
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      return;
    }

    const payload = {};
    const nextName = profileForm.full_name.trim();
    const currentName = user?.full_name?.trim() || "";

    if (nextName !== currentName) {
      payload.full_name = nextName;
    }

    if (profileAvatarFile) {
      payload.avatar_data_url = await readFileAsDataUrl(profileAvatarFile);
    } else if (profileAvatarCleared) {
      payload.avatar_data_url = null;
    }

    if (!Object.keys(payload).length) {
      addToast("No changes", "info");
      return;
    }

    try {
      const res = await apiFetch("/api/profile", {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not save profile");
      setUser(data.user);
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      setProfileAvatarCleared(false);
      setProfileForm({ full_name: data.user.full_name || "" });
      addToast(t(language, "profile.save"), "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const availableSectors = [...new Set(companies.map((c) => c.sector).filter(Boolean))];

  const filteredCompanies = companies
    .filter((item) => {
      const q = analysisCompany.trim().toLowerCase();
      const matchSearch = !q || item.ticker.toLowerCase().includes(q) || item.company_name.toLowerCase().includes(q);
      const matchSector = !selectedSector || item.sector === selectedSector;
      return matchSearch && matchSector;
    })
    .slice(0, 48);

  const resolveTicker = (value) => {
    const normalized = String(value || "").trim();
    if (!normalized) return "";
    const upper = normalized.toUpperCase();
    const match = companies.find((item) => item.ticker.toUpperCase() === upper || item.company_name.toLowerCase() === normalized.toLowerCase());
    return match?.ticker || upper;
  };

  const favoriteTickers = new Set((profile?.favorites || []).map((item) => String(item?.ticker || "").trim().toUpperCase()).filter(Boolean));
  const recentAnalyses = (profile?.recent_analyses || []).filter((item) => {
    const match = `${item?.company_name || ""} ${item?.company_input || ""} ${item?.ticker || ""}`.toLowerCase().includes(historySearch.trim().toLowerCase());
    const fav = !favoriteTickers.size || favoriteTickers.has(String(item?.ticker || "").trim().toUpperCase());
    return match && (historyMode === "favorites" ? fav : true);
  });

  const chartData = buildSeriesChart(analysisResult?.ifrs_snapshot?.series?.annual || [], language);
  const analysisLabel = analysisResult?.company_name || analysisResult?.input || t(language, "analysis.resultEmpty");
  const analysisTicker = analysisResult?.ticker || resolveTicker(analysisResult?.input || analysisCompany || analysisResult?.company_name);
  const resultScore = analysisResult?.summary?.score ?? analysisResult?.metrics?.total_score?.score ?? null;
  const resultGrade = analysisResult?.summary?.grade ?? analysisResult?.metrics?.total_score?.grade ?? "—";
  const resultCacheText = analysisResult ? (analysisResult.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")) : t(language, "analysis.resultCacheWaiting");

  const metricCards = (() => {
    if (!analysisResult?.metrics) return [];
    const metrics = analysisResult.metrics;
    const cards = [];
    const push = (label, value, sub, tone = "warning") => {
      if (value === undefined || value === null || value === "") return;
      cards.push({ label, value, sub, tone });
    };

    // Composite total_score / attractiveness grade and the DCF valuation card
    // removed for ТЗ compliance: no directional/forecast signals, no DCF model
    // in the served UI. Replaced with the factual EBITDA-margin metric (§3.3).
    const inc = analysisResult?.ifrs_snapshot?.income_statement || {};
    if (inc.ebitda_margin_pct !== undefined && inc.ebitda_margin_pct !== null) {
      push(
        language === "en" ? "EBITDA margin" : language === "uz" ? "EBITDA marjasi" : "Маржа EBITDA",
        `${formatRatio(inc.ebitda_margin_pct, 1, language)}%`,
        inc.debt_to_ebitda != null ? `${language === "en" ? "Debt/EBITDA" : "Долг/EBITDA"}: ${formatRatio(inc.debt_to_ebitda, 2, language)}×` : "",
        inc.ebitda_margin_pct >= 15 ? "good" : inc.ebitda_margin_pct >= 5 ? "warning" : "danger"
      );
    }
    const industry = metrics.industry || {};
    push(
      t(language, "metrics.industry"),
      industry.sector_name ?? "—",
      [industry.verdict || "", `${industry.good_count ?? 0} / ${industry.weak_count ?? 0}`].filter(Boolean).join(" · "),
      industry.good_count > industry.weak_count ? "good" : "warning"
    );
    const debtEq = industry.debt_equity || {};
    if (debtEq.value !== undefined && debtEq.value !== null) {
      const burden = debtEq.burden || {};
      push(
        t(language, "metrics.debt_burden"),
        burden[language] || burden.ru || "—",
        `D/E: ${debtEq.value}×`,
        debtEq.rating === "good" ? "good" : debtEq.rating === "ok" ? "warning" : "danger"
      );
    }
    const liquidity = metrics.market_liquidity || {};
    push(
      t(language, "metrics.market_liquidity"),
      liquidity.liquidity_label ?? "—",
      [`${t(language, "analysis.signalLatest")}: ${liquidity.trade_days ?? "—"}/30`, liquidity.avg_trade_value ? formatCompactNumber(liquidity.avg_trade_value, language) : ""].filter(Boolean).join(" · "),
      liquidity.liquidity_label === "high" ? "good" : "warning"
    );
    return cards;
  })();

  const profileStats = profile?.stats || {};
  const profileUser = profile?.user || user;
  const profileAvatar = profileUser?.avatar_data_url;
  const profileCreated = profileUser?.created_at;
  const activitySeries = buildActivitySeries(profile?.recent_analyses || [], language);
  const activitySparkline = activitySeries.days.map((day) => day.count);
  const cachedSparkline = activitySeries.days.map((day) => day.cached);
  const scoreSparkline = activitySeries.days.map((day) => day.avgScore).filter((value) => value !== null);
  const companySparkline = companies.length ? activitySeries.days.map(() => companies.length) : [];
  const dashboardCards = [
    {
      label: t(language, "dashboard.cards.companies"),
      value: companies.length || 0,
      sub: t(language, "analysis.availableTitle"),
      tone: "good",
      sparkline: companySparkline,
    },
    {
      label: t(language, "dashboard.cards.analyses"),
      value: profileStats.total_analyses ?? 0,
      sub: profile ? vt(language, "dashboardPeriod") : t(language, "profile.empty"),
      tone: "warning",
      sparkline: activitySparkline,
    },
    {
      label: t(language, "dashboard.cards.avgScore"),
      value: profile ? profileStats.avg_score ?? "—" : "—",
      sub: profile ? t(language, "profile.stats.avgScore") : t(language, "analysis.resultEmpty"),
      tone: "good",
      sparkline: scoreSparkline,
    },
    {
      label: t(language, "dashboard.cards.cached"),
      value: profileStats.cached_analyses ?? 0,
      sub: profile ? t(language, "analysis.resultCacheHit") : t(language, "dashboard.trend"),
      tone: "neutral",
      sparkline: cachedSparkline,
    },
  ];
  const disclosure = disclosureText(language);
  const comparison = compareResult?.comparison || null;
  const compareCharts = Array.isArray(comparison?.charts) ? comparison.charts : [];
  const compareTables = comparison?.tables || {};
  const compareSummary = comparison?.summary || {};
  const compareAi = comparison?.comparative_ai_summary || {};
  const compareErrors = Array.isArray(comparison?.errors) ? comparison.errors : [];
  const comparePrimaryChart = compareCharts.find((chart) => chart.id === "normalized_radar") || compareCharts[0];
  const compareSecondaryCharts = compareCharts.filter((chart) => chart !== comparePrimaryChart);
  const compareQuickCompanies = companies.slice(0, 18);

  const navItems = token
    ? ["main", "market", "heatmap", "catalog", "news", "profile", "analysis", "compare"]
    : ["main", "market", "heatmap", "catalog", "news", "auth", "analysis", "compare"];

  const onAvatarChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) {
      setProfileAvatarFile(null);
      setProfileAvatarPreview("");
      return;
    }
    setProfileAvatarFile(file);
    try {
      const dataUrl = await readFileAsDataUrl(file);
      setProfileAvatarPreview(dataUrl);
      setProfileAvatarCleared(false);
    } catch (error) {
      addToast(error.message, "error");
    }
  };

  const removeAvatar = () => {
    setProfileAvatarFile(null);
    setProfileAvatarPreview("");
    setProfileAvatarCleared(true);
    addToast(language === "ru" ? "Текущий аватар будет удален после сохранения" : language === "uz" ? "Joriy avatar saqlangandan so'ng o'chiriladi" : "Current avatar will be removed after saving", "info");
  };

  const toggleTheme = () => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  };

  return (
    <div className="app-shell-wrap">
      <div className="bg-glow bg-glow-a" />
      <div className="bg-glow bg-glow-b" />

      <div className="app-shell">
        <header className={`topbar${mobileNavOpen ? " is-nav-open" : ""}`}>
          <button
            className="topbar-burger"
            type="button"
            aria-label={mobileNavOpen ? (language === "en" ? "Close menu" : language === "uz" ? "Menyuni yopish" : "Закрыть меню") : (language === "en" ? "Open menu" : language === "uz" ? "Menyuni ochish" : "Открыть меню")}
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen((v) => !v)}
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M3 12h18M3 18h18" /></svg>
          </button>
          <div className="topbar-brand">
            <img src={logoIcon} alt="UZ Stock Analyzer" className="brand-icon" />
            <div className="brand-copy">
              <div className="brand-title">{t(language, "brand")}</div>
              <div className="brand-subtitle">{t(language, "subtitle")}</div>
            </div>
          </div>

          <button className="topbar-nav-scrim" type="button" aria-hidden="true" tabIndex={-1} onClick={() => setMobileNavOpen(false)} />
          <nav className="topbar-nav">
            {navItems.map((key) => (
              <button key={key} className={`topbar-nav-btn ${activeView === key || (key === "news" && activeView === "newsArticle") ? "active" : ""}`} type="button" onClick={() => { setActiveView(key); setMobileNavOpen(false); }}>
                {key === "catalog" ? (
                  <span className="nav-catalog-wrap">
                    {t(language, "nav.catalog")}
                    {(() => {
                      if (!catalogStatus?.last_sync) return null;
                      const ageH = (Date.now() - new Date(catalogStatus.last_sync).getTime()) / 3600000;
                      return ageH > 24 ? <span className="nav-stale-dot" title={language === "ru" ? "Каталог устарел" : "Catalog stale"} /> : null;
                    })()}
                  </span>
                ) : key === "market" ? mt(language, "nav") : key === "heatmap" ? (language === "ru" ? "Карта рынка" : language === "uz" ? "Bozor xaritasi" : "Market Map") : key === "compare" ? ct(language, "nav") : t(language, `nav.${key}`)}
              </button>
            ))}
          </nav>

          {token && (
            <div className="notif-wrap">
              <button className="notif-bell" type="button" onClick={() => setNotifOpen((o) => !o)} aria-label="Notifications">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="20" height="20">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                </svg>
                {notifCount > 0 && <span className="notif-badge">{notifCount > 9 ? "9+" : notifCount}</span>}
              </button>
              {notifOpen && (
                <div className="notif-panel panel">
                  <div className="notif-panel-header">
                    <span className="panel-label">{clg(language, "notifications")}</span>
                    <button className="icon-btn" type="button" onClick={() => setNotifOpen(false)}>✕</button>
                  </div>
                  {notifItems.length === 0 ? (
                    <p className="muted notif-empty">{clg(language, "notifEmpty")}</p>
                  ) : (
                    <ul className="notif-list">
                      {notifItems.map((n, i) => (
                        <li key={i} className="notif-item">
                          <div className="notif-item-title">{n.ticker} · {n.report_form} · {n.year || "—"}{n.quarter > 0 ? ` Q${n.quarter}` : ""}</div>
                          <div className="notif-item-sub muted">{n.title || clg(language, "notifNewReport")} · {n.detected_at?.slice(0, 10)}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="topbar-meta">
            <div className="topbar-controls">
              {/* The panel is not a product section, so it stays out of the main
                  nav — but an administrator should not have to type the URL. The
                  label collapses to the icon on narrow widths, where the topbar
                  has no room to spare (see mobile.css §2). */}
              {user?.is_admin && (
                <button
                  className={`topbar-admin${activeView === "admin" ? " active" : ""}`}
                  type="button"
                  onClick={() => { setActiveView("admin"); setMobileNavOpen(false); }}
                  title={language === "en" ? "Admin panel" : language === "uz" ? "Admin paneli" : "Админ-панель"}
                  aria-label={language === "en" ? "Admin panel" : language === "uz" ? "Admin paneli" : "Админ-панель"}
                >
                  <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect width="7" height="9" x="3" y="3" rx="1" />
                    <rect width="7" height="5" x="14" y="3" rx="1" />
                    <rect width="7" height="9" x="14" y="12" rx="1" />
                    <rect width="7" height="5" x="3" y="16" rx="1" />
                  </svg>
                  <span>{language === "en" ? "Admin" : language === "uz" ? "Admin" : "Админка"}</span>
                </button>
              )}

              <label className="topbar-language">
                <select
                  id="languageSelect"
                  className="select-field"
                  value={language}
                  onChange={(event) => setLanguage(normalizeLanguage(event.target.value))}
                >
                  <option value="ru">RU</option>
                  <option value="en">EN</option>
                  <option value="uz">UZ</option>
                </select>
              </label>

              <button className="theme-toggle" type="button" onClick={toggleTheme} title={theme === "dark" ? t(language, "theme.light") : t(language, "theme.dark")}>
                <strong>{theme === "dark" ? "☀" : "☾"}</strong>
              </button>
            </div>
          </div>
        </header>

        <main className="content">
          {activeView === "main" && (
            <>
              {/* Hero Section */}
              <section className="hero-panel">
                <div className="hero-copy-block">
                  <div className="eyebrow">{t(language, "subtitle")}</div>
                  <h1>{t(language, "hero.title")}</h1>
                  <p>{t(language, "hero.copy")}</p>
                  <div className="hero-actions">
                    <button className="primary-btn" type="button" onClick={() => setActiveView("analysis")}>
                      {TEXTS[language].hero.ctas.analysis}
                    </button>
                    <button className="ghost-btn" type="button" onClick={() => setActiveView("profile")}>
                      {TEXTS[language].hero.ctas.profile}
                    </button>
                  </div>
                  <div className="hero-badges">
                    {TEXTS[language].hero.badges.map((badge) => (
                      <span key={badge}>{badge}</span>
                    ))}
                  </div>
                </div>
                <div className="hero-image">
                  <img src={heroImage} alt="Stock Analysis Dashboard" />
                </div>
              </section>

              {/* Features Section */}
              <section className="landing-features">
                <div className="section-header">
                  <h2>{t(language, "main.title")}</h2>
                  <p>{t(language, "main.copy")}</p>
                </div>
                <div className="features-grid">
                  {TEXTS[language].main.features.map((feature) => (
                    <article className="feature-card" key={feature.title}>
                      <div className="feature-icon">{Icons[feature.icon]}</div>
                      <h3>{feature.title}</h3>
                      <p>{feature.copy}</p>
                    </article>
                  ))}
                </div>
              </section>

              {/* How It Works Section */}
              <section className="landing-how-it-works">
                <div className="section-header">
                  <h2>{TEXTS[language].main.howItWorks.title}</h2>
                </div>
                <div className="steps-grid">
                  {TEXTS[language].main.howItWorks.steps.map((step) => (
                    <article className="step-card" key={step.num}>
                      <div className="step-number">{step.num}</div>
                      <h3>{step.title}</h3>
                      <p>{step.copy}</p>
                    </article>
                  ))}
                </div>
              </section>

              {/* Stats Section */}
              <section className="landing-stats">
                <div className="section-header">
                  <h2>{TEXTS[language].main.stats.title}</h2>
                </div>
                <div className="stats-grid">
                  {TEXTS[language].main.stats.items.map((stat) => (
                    <article className="stat-card" key={stat.label}>
                      <div className="stat-value">{stat.value}</div>
                      <div className="stat-label">{stat.label}</div>
                    </article>
                  ))}
                </div>
              </section>

              {/* CTA Section */}
              <section className="landing-cta">
                <div className="cta-content">
                  <h2>{TEXTS[language].main.cta.title}</h2>
                  <p>{TEXTS[language].main.cta.copy}</p>
                  <button className="primary-btn cta-btn" type="button" onClick={() => setActiveView("analysis")}>
                    {TEXTS[language].main.cta.button}
                  </button>
                </div>
              </section>
            </>
          )}

          {activeView === "catalog" && (
            <CatalogView
              language={language}
              companies={companies}
              token={token}
              addToast={addToast}
              onNavigateToAnalysis={(t) => { setAnalysisCompany(t); setActiveView("analysis"); }}
              initialStatus={catalogStatus}
              user={user}
            />
          )}

          {/* Reached by direct link only — it is deliberately absent from
              navItems, because it is a tool for whoever maintains the data. */}
          {/* The panel is a page of the site, so it renders in the same content
              column as every other view. A non-admin who guesses the URL is told
              plainly rather than redirected: silently bouncing a signed-in user
              reads as a bug, and the page is not secret — its data is guarded on
              the server, where guarding belongs. */}
          {activeView === "admin" && (
            user?.is_admin ? (
              <AdminPanel
                apiFetch={apiFetch}
                language={language}
                section={adminSection}
                onSectionChange={setAdminSection}
              />
            ) : (
              <div className="panel" style={{ textAlign: "center", padding: 48 }}>
                <div className="panel-label">
                  {language === "en" ? "Internal" : language === "uz" ? "Xizmat" : "Служебное"}
                </div>
                <h2 style={{ margin: "0 0 8px" }}>
                  {language === "en" ? "Administrators only"
                    : language === "uz" ? "Faqat administratorlar uchun"
                      : "Только для администраторов"}
                </h2>
                <p className="muted" style={{ margin: "0 auto 18px", maxWidth: "48ch" }}>
                  {language === "en" ? "This page maintains the data behind the site. Your account does not have access to it."
                    : language === "uz" ? "Bu sahifa sayt ma'lumotlarini boshqaradi. Hisobingizda unga kirish huquqi yo'q."
                      : "Эта страница обслуживает данные сайта. У вашей учётной записи нет к ней доступа."}
                </p>
                <button type="button" className="primary-btn" onClick={() => setActiveView("main")}>
                  {language === "en" ? "Back to the site" : language === "uz" ? "Saytga qaytish" : "Вернуться на сайт"}
                </button>
              </div>
            )
          )}

          {activeView === "news" && <NewsView language={language} onOpenCompany={openCompanyPage} onOpenNews={openNewsArticle} user={user} apiFetch={apiFetch} />}

          {activeView === "newsArticle" && newsId && (
            <NewsArticleView
              key={newsId}
              newsId={newsId}
              language={language}
              securitiesMap={securitiesMap}
              onOpenCompany={openCompanyPage}
              onOpenNews={openNewsArticle}
              onBack={() => setActiveView("news")}
            />
          )}

          {activeView === "company" && companyTicker && (
            <CompanyPage
              key={companyTicker}
              ticker={companyTicker}
              securitiesMap={securitiesMap}
              language={language}
              marketRows={marketRows}
              financials={marketFinancials}
              tradeStats={marketTradeStats}
              favoriteTickers={favoriteTickers}
              onToggleFavorite={handleToggleFavorite}
              signedIn={Boolean(token)}
              onOpenCompany={openCompanyPage}
              onBack={() => setActiveView(prevView || "market")}
              onAnalyze={(t) => { setAnalysisCompany(t); setActiveView("analysis"); }}
            />
          )}

          {(activeView === "market" || activeView === "heatmap") && (
            <MarketView
              rows={marketRows}
              meta={marketMeta}
              loading={marketLoading}
              message={marketMessage}
              query={marketQuery}
              onQueryChange={setMarketQuery}
              type={marketType}
              onTypeChange={setMarketType}
              onRefresh={() => { loadMarketStocks().catch((error) => addToast(error.message, "error")); }}
              onAnalyze={(ticker) => {
                setAnalysisCompany(ticker || "");
                setActiveView("analysis");
              }}
              onOpenCompany={openCompanyPage}
              language={language}
              companies={companies}
              securitiesMap={securitiesMap}
              financials={marketFinancials}
              tradeStats={marketTradeStats}
              favoriteTickers={favoriteTickers}
              onToggleFavorite={handleToggleFavorite}
              viewMode={activeView === "heatmap" ? "heatmap" : "table"}
              onViewModeChange={(m) => setActiveView(m === "heatmap" ? "heatmap" : "market")}
              isAdmin={Boolean(user?.is_admin)}
            />
          )}

          {activeView === "auth" && (
            <section className="auth-layout">
              <article className="panel auth-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.auth")}</div>
                    <h2>{t(language, "auth.title")}</h2>
                  </div>
                  <span className={`status-badge ${token ? "" : "muted"}`}>{token ? t(language, "auth.signedIn") : t(language, "auth.signedOut")}</span>
                </div>

                <div className="segmented-control">
                  <button type="button" className={authTab === "login" ? "active" : ""} onClick={() => setAuthTab("login")}>
                    {t(language, "auth.loginTab")}
                  </button>
                  <button type="button" className={authTab === "register" ? "active" : ""} onClick={() => setAuthTab("register")}>
                    {t(language, "auth.registerTab")}
                  </button>
                </div>

                {authTab === "login" ? (
                  <form className="form-grid" onSubmit={handleLogin}>
                    <label>
                      <span>{t(language, "auth.login.email")}</span>
                      <input
                        type="email"
                        value={loginForm.email}
                        onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
                        placeholder="you@example.com"
                        required
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.login.password")}</span>
                      <input
                        type="password"
                        value={loginForm.password}
                        onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
                        placeholder="••••••••"
                        required
                      />
                    </label>
                    <button className="primary-btn" type="submit">
                      {t(language, "auth.login.submit")}
                    </button>
                  </form>
                ) : (
                  <form className="form-grid" onSubmit={handleRegister}>
                    <label>
                      <span>{t(language, "auth.register.fullName")}</span>
                      <input
                        type="text"
                        value={registerForm.full_name}
                        onChange={(event) => setRegisterForm({ ...registerForm, full_name: event.target.value })}
                        placeholder={t(language, "auth.register.fullName")}
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.register.email")}</span>
                      <input
                        type="email"
                        value={registerForm.email}
                        onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })}
                        placeholder="you@example.com"
                        required
                      />
                    </label>
                    <label>
                      <span>{t(language, "auth.register.password")}</span>
                      <input
                        type="password"
                        value={registerForm.password}
                        onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })}
                        placeholder="••••••••"
                        required
                      />
                    </label>
                    <button className="primary-btn" type="submit">
                      {t(language, "auth.register.submit")}
                    </button>
                  </form>
                )}

                <div className="oauth-block">
                  <div className="oauth-label">{t(language, "auth.oauthLabel")}</div>
                  <button className="oauth-btn oauth-google" type="button" onClick={handleGoogleLogin}>
                    {t(language, "auth.google")}
                  </button>
                </div>

                <div className="helper-text">{authMessage}</div>
              </article>

              <article className="panel auth-side-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "nav.auth")}</div>
                    <h2>{t(language, "auth.signedInAs")}</h2>
                  </div>
                </div>
                {token && profileUser ? (
                  <div className="user-card">
                    <div className="user-line">
                      <span className="muted">{t(language, "auth.signedInAs")}</span>
                      <strong>{profileUser.full_name || profileUser.email}</strong>
                    </div>
                    <div className="user-line">
                      <span className="muted">Email</span>
                      <strong>{profileUser.email}</strong>
                    </div>
                    <button className="ghost-btn" type="button" onClick={handleLogout}>
                      {t(language, "auth.logout")}
                    </button>
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "auth.messages.authRequired")}</p>
                  </div>
                )}
              </article>
            </section>
          )}

          {activeView === "profile" && (
            <>
              {/* Profile Header Card */}
              {profileUser && (
                <section className="profile-header-card">
                  <div className="profile-header-bg" />
                  <div className="profile-header-content">
                    <div className="profile-header-avatar" style={profileAvatarPreview || profileAvatar ? {} : { background: `linear-gradient(135deg, hsl(${hashToHue(profileUser.email)} 70% 60%), hsl(${(hashToHue(profileUser.email) + 45) % 360} 70% 50%))` }}>
                      {profileAvatarPreview ? <img src={profileAvatarPreview} alt="" /> : profileAvatar ? <img src={profileAvatar} alt="" /> : getProfileInitials(profileUser)}
                    </div>
                    <div className="profile-header-info">
                      <h1>{profileUser.full_name || profileUser.email.split('@')[0]}</h1>
                      <p className="profile-header-email">{profileUser.email}</p>
                      <div className="profile-header-meta">
                        <span className="profile-header-badge">{t(language, "auth.signedIn")}</span>
                      </div>
                    </div>
                    <div className="profile-header-actions">
                      <button className="primary-btn" type="button" onClick={() => setActiveView("analysis")}>
                        {t(language, "profile.analyze")}
                      </button>
                      <button className="ghost-btn" type="button" onClick={() => setShowProfileEdit(!showProfileEdit)}>
                        {showProfileEdit ? (language === "en" ? "Cancel" : language === "uz" ? "Bekor qilish" : "Отмена") : (language === "en" ? "Edit Profile" : language === "uz" ? "Tahrirlash" : "Редактировать")}
                      </button>
                    </div>
                  </div>
                  {/* Inline Edit Form */}
                  {showProfileEdit && (
                    <div className="profile-edit-inline">
                      <form className="profile-settings-form" onSubmit={handleProfileSave}>
                        <div className="profile-form-group">
                          <label>{t(language, "profile.name")}</label>
                          <input
                            type="text"
                            value={profileForm.full_name}
                            onChange={(event) => setProfileForm({ full_name: event.target.value })}
                            placeholder={t(language, "profile.name")}
                          />
                        </div>
                        <div className="profile-form-group">
                          <label>{t(language, "profile.avatar")}</label>
                          <div className="profile-avatar-upload">
                            <input type="file" accept="image/*" onChange={onAvatarChange} id="avatar-input" />
                            <label htmlFor="avatar-input" className="profile-avatar-btn">
                              {language === "en" ? "Choose file" : language === "uz" ? "Fayl tanlash" : "Выбрать файл"}
                            </label>
                            {(profileAvatarPreview || profileAvatar) && (
                              <button type="button" className="profile-avatar-remove" onClick={removeAvatar}>
                                {t(language, "profile.clearAvatar")}
                              </button>
                            )}
                          </div>
                        </div>
                        <div className="profile-form-actions">
                          <button className="primary-btn" type="submit">
                            {t(language, "profile.save")}
                          </button>
                        </div>
                      </form>
                    </div>
                  )}
                </section>
              )}

              {/* Stats Overview */}
              <section className="profile-stats-section">
                <div className="profile-stats-grid">
                  {dashboardCards.map((card) => (
                    <DashboardMetricCard key={card.label} {...card} language={language} />
                  ))}
                </div>
              </section>

              {/* Activity Chart */}
              <section className="profile-activity-section">
                <article className="panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "dashboard.activityTitle")}</div>
                      <h2>{t(language, "dashboard.activityTitle")}</h2>
                    </div>
                    <span className="profile-activity-total">
                      {activitySeries?.total ? `${activitySeries.total} ${language === "uz" ? "tahlil" : language === "en" ? "analyses" : "анализов"}` : ""}
                    </span>
                  </div>
                  <ActivityChart series={activitySeries} language={language} />
                </article>
              </section>

              {/* Favorites */}
              <section className="profile-favorites-section">
                <article className="panel favorites-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "profile.favoritesTitle")}</div>
                    <h2>{t(language, "profile.favoritesTitle")}</h2>
                  </div>
                </div>
                {profile?.favorites?.length ? (
                  <div className="favorites-list">
                    {profile.favorites.map((item) => (
                      <div className="favorite-item favorite-item--clickable" key={`${item.ticker}-${item.created_at}`}
                        role="button" tabIndex={0}
                        title={language === "en" ? "Open company" : language === "uz" ? "Kompaniyani ochish" : "Открыть компанию"}
                        onClick={() => openCompanyPage(item.ticker)}
                        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCompanyPage(item.ticker); } }}>
                        <div className="favorite-main">
                          <strong>{item.company_name || item.ticker}</strong>
                          <span>{item.ticker} · {formatDateLabel(item.created_at, language)}</span>
                        </div>
                        <button className="ghost-btn" type="button" onClick={(e) => { e.stopPropagation(); handleToggleFavorite(item.ticker, item.company_name); }}>
                          {t(language, "profile.remove")}
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{t(language, "profile.favoritesEmpty")}</p>
                  </div>
                )}
                </article>
              </section>

              {/* History */}
              <section className="profile-history-section">
                <article className="panel history-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "profile.historyTitle")}</div>
                      <h2>{t(language, "profile.historyTitle")}</h2>
                    </div>
                  </div>
                  <div className="panel-toolbar history-filters">
                    <input
                      type="search"
                      value={historySearch}
                      onChange={(event) => setHistorySearch(event.target.value)}
                      placeholder={t(language, "profile.filters.search")}
                    />
                    <select value={historyMode} onChange={(event) => setHistoryMode(event.target.value)}>
                      <option value="all">{t(language, "profile.filters.all")}</option>
                      <option value="favorites">{t(language, "profile.filters.favorites")}</option>
                    </select>
                  </div>
                  {recentAnalyses.length ? (
                    <div className="history-list">
                      {recentAnalyses.map((item) => (
                        <article className="history-item" key={`${item.created_at}-${item.company_input}`}>
                          <div className="history-main">
                            <div>
                              <div className="history-title">{item.company_name || item.company_input || t(language, "profile.empty")}</div>
                              <div className="history-sub">
                                {item.ticker || "—"} · {item.from_cache ? t(language, "analysis.resultCacheHit") : t(language, "analysis.resultFresh")}
                              </div>
                            </div>
                            {/* Composite score removed for ТЗ compliance (2026-07-09). */}
                          </div>
                          <div className="history-meta">
                            <span>{formatDateLabel(item.created_at, language)}</span>
                            <button
                              type="button"
                              className="history-repeat-btn"
                              onClick={() => handleRepeatAnalysis(item)}
                              disabled={analysisLoading}
                              title={t(language, "profile.repeat")}
                            >
                              ↻ {t(language, "profile.repeat")}
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="empty-state">
                      <p className="empty-copy">{profile ? t(language, "profile.historyEmpty") : t(language, "profile.empty")}</p>
                    </div>
                  )}
                </article>
              </section>
            </>
          )}

          {activeView === "analysis" && (
            <section className="analysis-layout">
              <article className="panel analysis-panel analysis-hero">
                <div className="analysis-hero-header">
                  <div className="analysis-hero-icon">
                    {Icons.chart}
                  </div>
                  <div className="analysis-hero-text">
                    <h1>{t(language, "analysis.title")}</h1>
                    <p>{language === "en" ? "Get comprehensive financial analysis powered by AI" : language === "uz" ? "AI yordamida moliyaviy tahlil oling" : "Получите комплексный финансовый анализ на основе ИИ"}</p>
                  </div>
                  {analysisLoading && <span className="status-badge analysis-loading-badge">{t(language, "analysis.loadingChart")}</span>}
                </div>

                <form className="analysis-form-modern" onSubmit={handleAnalysisSubmit}>
                  <div className="analysis-input-group">
                    <label>{t(language, "analysis.company")}</label>
                    <div className="analysis-input-wrapper">
                      <span className="analysis-input-icon">{Icons.target}</span>
                      <input
                        list="companiesList"
                        value={analysisCompany}
                        onChange={(event) => setAnalysisCompany(event.target.value)}
                        placeholder={language === "en" ? "Enter company name or ticker..." : language === "uz" ? "Kompaniya nomi yoki ticker kiriting..." : "Введите название компании или тикер..."}
                        autoComplete="off"
                        required
                      />
                    </div>
                    <datalist id="companiesList">
                      {companies.map((company) => (
                        <option key={company.ticker} value={company.ticker}>
                          {company.company_name}
                        </option>
                      ))}
                    </datalist>
                  </div>

                  <div className="analysis-period-picker">
                    <div className="analysis-input-group">
                      <label>{t(language, "analysis.reportType")}</label>
                      <select value={reportAnalysisType} onChange={(event) => setReportAnalysisType(event.target.value)}>
                        <option value="latest">{t(language, "analysis.fullAnalysis")}</option>
                        <option value="quarterly">{t(language, "analysis.quarterlyReport")}</option>
                        <option value="annual">{t(language, "analysis.annualReport")}</option>
                      </select>
                    </div>
                    {reportAnalysisType !== "latest" ? (
                      <div className="analysis-input-group">
                        <label>{t(language, "analysis.reportingForm")}</label>
                        <select
                          value={reportForm}
                          onChange={(event) => {
                            setReportForm(event.target.value);
                            if (event.target.value === "IFRS" && reportAnalysisType === "quarterly") {
                              setReportAnalysisType("annual");
                            }
                          }}
                        >
                          <option value="NAS">{t(language, "analysis.reportFormNAS")}</option>
                          <option value="IFRS">{t(language, "analysis.reportFormIFRS")}</option>
                        </select>
                        <span className="analysis-form-hint">{t(language, "analysis.reportFormHint")}</span>
                      </div>
                    ) : (
                      <div className="analysis-input-group analysis-source-note">
                        <span className="analysis-source-badge">
                          {language === "en" ? "Data source" : language === "uz" ? "Ma'lumot manbai" : "Источник данных"}:
                          {" "}<strong>{language === "en" ? "NAS structured reports" : language === "uz" ? "MHBS tizimli hisobotlar" : "НСБУ структурированная отчётность"}</strong>
                        </span>
                        <span className="analysis-form-hint">{t(language, "analysis.reportFormLatestNote")}</span>
                      </div>
                    )}
                    {reportAnalysisType === "quarterly" ? (
                      <div className="analysis-input-group">
                        <label>{t(language, "analysis.quarter")}</label>
                        <select value={reportQuarter} onChange={(event) => setReportQuarter(event.target.value)} disabled={periodsLoading}>
                          {availableQuartersForYear.length > 0
                            ? availableQuartersForYear.map((q) => (
                                <option key={q} value={String(q)}>
                                  {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                </option>
                              ))
                            : [1, 2, 3].map((q) => (
                                <option key={q} value={String(q)}>
                                  {language === "en" ? `Q${q}` : language === "uz" ? `${q}-chorak` : `${q} квартал`}
                                </option>
                              ))}
                        </select>
                        {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                      </div>
                    ) : null}
                    {reportAnalysisType !== "latest" ? (
                      <>
                        <div className="analysis-input-group">
                          <label>{t(language, "analysis.currentYear")}</label>
                          <select value={reportCurrentYear} onChange={(event) => setReportCurrentYear(event.target.value)} disabled={periodsLoading}>
                            {(reportAnalysisType === "quarterly" ? quarterlyYearOptions : annualYearOptions).map((year) => (
                              <option key={`current-${year}`} value={year}>{year}</option>
                            ))}
                          </select>
                          {periodsLoading && <span className="analysis-periods-loading">{language === "en" ? "Loading periods…" : language === "uz" ? "Davrlar yuklanmoqda…" : "Загрузка периодов…"}</span>}
                        </div>
                        <div className="analysis-input-group">
                          <label>{t(language, "analysis.previousYear")}</label>
                          <select value={reportPreviousYear} onChange={(event) => setReportPreviousYear(event.target.value)} disabled={periodsLoading}>
                            {annualYearOptions.map((year) => (
                              <option key={`previous-${year}`} value={year}>{year}</option>
                            ))}
                          </select>
                        </div>
                      </>
                    ) : null}
                  </div>

                  <div className="analysis-options-row">
                    <div className="analysis-input-group">
                      <label>{t(language, "analysis.mode")}</label>
                      <select defaultValue="full">
                        <option value="quick">{t(language, "analysis.quick")}</option>
                        <option value="full">{t(language, "analysis.full")}</option>
                      </select>
                    </div>
                    <label className="analysis-checkbox">
                      <input type="checkbox" checked={forceRefresh} onChange={(event) => setForceRefresh(event.target.checked)} />
                      <span>{t(language, "analysis.forceRefresh")}</span>
                    </label>
                  </div>

                  <div className={`analysis-deep-excel ${includeAllExcelReports ? "is-active" : ""}`}>
                    <label className="analysis-checkbox analysis-deep-checkbox">
                      <input type="checkbox" checked={includeAllExcelReports} onChange={(event) => setIncludeAllExcelReports(event.target.checked)} />
                      <span>{language === "en" ? "Deep Excel analysis: use all available XLSX reports" : language === "uz" ? "Deep Excel tahlil: barcha mavjud XLSX hisobotlardan foydalanish" : "Глубокий Excel-анализ: использовать все доступные XLSX-отчеты"}</span>
                    </label>
                    {includeAllExcelReports ? (
                      <div className="analysis-input-group analysis-excel-limit">
                        <label>{language === "en" ? "Optional XLSX cap" : language === "uz" ? "Ixtiyoriy XLSX chegarasi" : "Ограничение XLSX, необязательно"}</label>
                        <input
                          type="number"
                          min="1"
                          max="100"
                          value={excelReportLimit}
                          onChange={(event) => setExcelReportLimit(event.target.value)}
                          placeholder={language === "en" ? "Leave empty = all found" : language === "uz" ? "Bo'sh qoldiring = hammasi" : "Пусто = все найденные"}
                        />
                      </div>
                    ) : null}
                    <p>
                      {language === "en"
                        ? "Leave the limit empty to parse every found XLSX report. This mode is slower on first run, then snapshots are cached."
                        : language === "uz"
                          ? "Barcha topilgan XLSX hisobotlarni olish uchun limitni bo'sh qoldiring. Bu rejim birinchi ishga tushishda sekinroq, keyin snapshot keshdan olinadi."
                          : "Оставьте лимит пустым, чтобы разобрать все найденные XLSX-отчёты. Этот режим медленнее при первом запуске, после парсинга snapshot берется из кэша."}
                    </p>
                  </div>

                  <button className="primary-btn analysis-submit-btn" type="submit" disabled={analysisLoading}>
                    {Icons.zap}
                    <span>{analysisLoading ? (language === "en" ? "Analyzing..." : language === "uz" ? "Tahlil qilinmoqda..." : "Анализируем...") : t(language, "analysis.submit")}</span>
                  </button>
                </form>

                <div className="analysis-companies-section">
                  <div className="analysis-companies-header">
                    <h3>{t(language, "analysis.availableTitle")}</h3>
                    <span className="analysis-companies-count">{filteredCompanies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                  </div>
                  <div className="sector-filter">
                    <button
                      className={`sector-chip${!selectedSector ? " active" : ""}`}
                      type="button"
                      onClick={() => setSelectedSector(null)}
                    >
                      {sectorLabel(language, "all")}
                    </button>
                    {availableSectors.map((sector) => (
                      <button
                        key={sector}
                        className={`sector-chip${selectedSector === sector ? " active" : ""}`}
                        type="button"
                        onClick={() => setSelectedSector(selectedSector === sector ? null : sector)}
                      >
                        {sectorLabel(language, sector)}
                      </button>
                    ))}
                  </div>
                  <div className="analysis-companies-grid">
                    {filteredCompanies.map((company) => (
                      <button
                        key={company.ticker}
                        className="analysis-company-chip"
                        type="button"
                        onClick={() => setAnalysisCompany(company.ticker)}
                      >
                        <CompanyLogo logo={company.logo} name={company.company_name} ticker={company.ticker} />
                        <span className="chip-ticker">{company.ticker}</span>
                        <span className="chip-name">{company.company_name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </article>

              {(analysisResult || analysisLoading) && (
                <article className={`panel result-hero ${analysisLoading ? "is-loading" : ""}`}>
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{t(language, "analysis.resultTitle")}</div>
                      <h2>{analysisLabel}</h2>
                    </div>
                    {analysisResult ? <span className="status-badge muted">{resultCacheText}</span> : null}
                  </div>

                  {analysisLoading ? (
                    <ResultSkeleton language={language} />
                  ) : (
                  <>
                    <HeroKpiStrip
                      analysisResult={analysisResult}
                      chartData={chartData}
                      language={language}
                    />
                    <div className="chart-card">
                      <div className="chart-head">
                        <div>
                          <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
                          <h3>{t(language, "analysis.chartTitle")}</h3>
                        </div>
                        <span className="status-badge muted">{chartData ? `${chartData.filtered[0].year}–${chartData.filtered.at(-1).year}` : t(language, "analysis.chartMetaEmpty")}</span>
                      </div>
                      <AnalysisChart chartData={chartData} language={language} />
                    </div>

                    <BankMetricsPanel analysisResult={analysisResult} language={language} />

                    <FinancialVisuals result={analysisResult} language={language} score={resultScore} />

                    <RiskProfilePanel analysisResult={analysisResult} language={language} />

                    <ObservationsPanel analysisResult={analysisResult} language={language} />

                    <StructureCharts analysisResult={analysisResult} language={language} />

                    <div className="meta-grid">
                      <button
                        id="resultFavoriteBtn"
                        className={`ghost-btn result-favorite-btn ${analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? "is-active" : ""}`}
                        type="button"
                        onClick={() => analysisResult && handleToggleFavorite(analysisTicker, analysisResult.company_name || analysisResult.input || "")}
                      >
                        {analysisTicker && favoriteTickers.has(String(analysisTicker).trim().toUpperCase()) ? t(language, "analysis.favoriteRemove") : t(language, "analysis.favoriteAdd")}
                      </button>
                      <button
                        className="ghost-btn result-export-btn no-print"
                        type="button"
                        onClick={handleExportExcel}
                        disabled={exportingExcel || !analysisResult}
                      >
                        {exportingExcel
                          ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                          : (language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel")}
                      </button>
                      <button
                        className="ghost-btn result-export-btn no-print"
                        type="button"
                        onClick={handleExportPdf}
                        disabled={exportingPdf || !analysisResult}
                      >
                        {exportingPdf
                          ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                          : (language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF")}
                      </button>
                    </div>
                  </>
                )}
                </article>
              )}
            </section>
          )}

          {activeView === "analysis" && (analysisResult || analysisLoading) && (
            <section className="results-grid">
              <HeroVerdictBlock analysisResult={analysisResult} language={language} />
              <article className="panel metrics-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.metricsTitle")}</div>
                    <h2>{t(language, "analysis.metricsTitle")}</h2>
                  </div>
                </div>
                {metricCards.length ? (
                  <div className="metrics-grid">
                    {metricCards.map((item) => (
                      <MetricCard key={item.label} {...item} />
                    ))}
                  </div>
                ) : (
                  <div className="empty-state">
                    <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingMetrics") : t(language, "analysis.resultEmpty")}</p>
                  </div>
                )}
              </article>

              {analysisResult?.sections && <ReportArticleView analysisResult={analysisResult} language={language} />}

              <article className="panel sections-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{t(language, "analysis.sectionsTitle")}</div>
                    <h2>{t(language, "analysis.sectionsTitle")}</h2>
                  </div>
                </div>
                {analysisResult?.sections ? (() => {
                  const { primary, supplementary } = splitSections(analysisResult.sections);
                  return (
                    <div className="sections-wrap">
                      {primary.map(([key, value], index) => (
                        <SectionCard
                          key={key}
                          title={getSectionTitle(language, key)}
                          body={value || t(language, "analysis.noData")}
                          index={index}
                          open={index === 0}
                          language={language}
                        />
                      ))}
                      {supplementary.length > 0 && (
                        <details className="section-card section-card--supplementary fade-in">
                          <summary>
                            <span className="section-number">{SUPPLEMENTARY_LABELS[language] || SUPPLEMENTARY_LABELS.ru}</span>
                            <span className="section-title-text">
                              {language === "en"
                                ? "Additional analysis blocks"
                                : language === "uz"
                                ? "Qo'shimcha tahlil bloklari"
                                : "Дополнительные блоки анализа"}
                            </span>
                          </summary>
                          <div className="section-content">
                            <div className="sections-wrap sections-wrap--nested">
                              {supplementary.map(([key, value], idx) => (
                                <SectionCard
                                  key={key}
                                  title={getSectionTitle(language, key)}
                                  body={value || t(language, "analysis.noData")}
                                  index={primary.length + idx}
                                  language={language}
                                />
                              ))}
                            </div>
                          </div>
                        </details>
                      )}
                    </div>
                  );
                })() : (
                  <div className="empty-state">
                    <p className="empty-copy">{analysisLoading ? t(language, "analysis.loadingSections") : t(language, "analysis.resultEmpty")}</p>
                  </div>
                )}
              </article>

              {analysisResult && <DisclaimerNote language={language} variant="report" />}
            </section>
          )}

          {activeView === "compare" && (
            <section className="compare-layout">
              <article className="panel analysis-panel analysis-hero">
                <div className="analysis-hero-header">
                  <div className="analysis-hero-icon">
                    {Icons.users}
                  </div>
                  <div className="analysis-hero-text">
                    <h1>{ct(language, "title")}</h1>
                    <p>{ct(language, "subtitle")}</p>
                  </div>
                  {compareLoading && <span className="status-badge analysis-loading-badge">{ct(language, "loading")}</span>}
                </div>

                <form className="analysis-form-modern" onSubmit={handleCompareSubmit}>
                  <div className="compare-inputs-grid">
                    {compareCompanies.map((value, index) => (
                      <div className="analysis-input-group" key={index}>
                        <label>
                          {ct(language, `company${index + 1}`)}
                          {index >= 2 && <span className="optional-tag">{ct(language, "optional")}</span>}
                        </label>
                        <div className="analysis-input-wrapper">
                          <span className="analysis-input-icon">{Icons.target}</span>
                          <input
                            list="compareCompaniesList"
                            value={value}
                            onChange={(event) => updateCompareCompany(index, event.target.value)}
                            placeholder={ct(language, "placeholder")}
                            autoComplete="off"
                            required={index < 2}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <datalist id="compareCompaniesList">
                    {companies.map((company) => (
                      <option key={company.ticker} value={company.ticker}>
                        {company.company_name}
                      </option>
                    ))}
                  </datalist>

                  <div className="analysis-options-row">
                    <label className="analysis-checkbox">
                      <input type="checkbox" checked={compareAiSummary} onChange={(event) => setCompareAiSummary(event.target.checked)} />
                      <span>{ct(language, "includeAi")}</span>
                    </label>
                  </div>

                  <button className="primary-btn analysis-submit-btn" type="submit" disabled={compareLoading}>
                    {Icons.zap}
                    <span>{compareLoading ? ct(language, "loading") : ct(language, "submit")}</span>
                  </button>
                </form>

                <div className="analysis-companies-section">
                  <div className="analysis-companies-header">
                    <h3>{ct(language, "quick")}</h3>
                    <span className="analysis-companies-count">{companies.length} {language === "en" ? "companies" : language === "uz" ? "kompaniya" : "компаний"}</span>
                  </div>
                  <div className="analysis-companies-grid">
                    {compareQuickCompanies.map((company) => (
                      <button
                        key={company.ticker}
                        className="analysis-company-chip"
                        type="button"
                        onClick={() => addQuickCompareCompany(company.ticker)}
                      >
                        <span className="chip-ticker">{company.ticker}</span>
                        <span className="chip-name">{company.company_name}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </article>

              {(compareResult || compareLoading) && (
                <article className={`panel compare-overview-panel ${compareLoading ? "is-loading" : ""}`}>
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "overview")}</div>
                      <h2>{compareResult ? ct(language, "ready") : ct(language, "empty")}</h2>
                    </div>
                    {compareMessage ? <span className="status-badge muted">{compareMessage}</span> : null}
                    {compareResult && !compareLoading && (
                      <div className="compare-export-actions no-print">
                        <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("excel")} disabled={!!exportingCompare}>
                          {exportingCompare === "excel"
                            ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                            : (language === "en" ? "⤓ Download Excel" : language === "uz" ? "⤓ Excel yuklab olish" : "⤓ Скачать Excel")}
                        </button>
                        <button className="ghost-btn result-export-btn" type="button" onClick={() => handleCompareExport("pdf")} disabled={!!exportingCompare}>
                          {exportingCompare === "pdf"
                            ? (language === "en" ? "Preparing…" : language === "uz" ? "Tayyorlanmoqda…" : "Готовим…")
                            : (language === "en" ? "⤓ Download PDF" : language === "uz" ? "⤓ PDF yuklab olish" : "⤓ Скачать PDF")}
                        </button>
                      </div>
                    )}
                  </div>

                  {compareLoading ? (
                    <div className="compare-loading-grid">
                      <div />
                      <div />
                      <div />
                    </div>
                  ) : comparison ? (
                    <>
                      <div className="compare-summary-card">
                        <p>{compareSummary.short || ct(language, "noData")}</p>
                        <span>{ct(language, "normalizedNote")}</span>
                      </div>
                      <CompareLeaderCards leaders={comparison.leaders} language={language} />
                      <div className="compare-ranking-grid">
                        <CompareRanking title={ct(language, "ranking")} rows={comparison.ranking} scoreKey="score" language={language} />
                        <CompareRanking title={ct(language, "normalizedRanking")} rows={comparison.normalized_ranking} scoreKey="composite_score" language={language} />
                      </div>
                    </>
                  ) : (
                    <div className="empty-state">
                      <p className="empty-copy">{ct(language, "empty")}</p>
                    </div>
                  )}
                </article>
              )}
            </section>
          )}

          {activeView === "compare" && (compareResult || compareLoading) && (
            <section className="compare-results-grid">
              <article className="panel compare-chart-main">
                {comparePrimaryChart ? <CompareChartCard chart={comparePrimaryChart} language={language} /> : (
                  <div className="empty-state">
                    <p className="empty-copy">{compareLoading ? ct(language, "loading") : ct(language, "noData")}</p>
                  </div>
                )}
              </article>

              <article className="panel compare-ai-panel">
                <div className="panel-head">
                  <div>
                    <div className="panel-label">{ct(language, "aiSummary")}</div>
                    <h2>{ct(language, "aiSummary")}</h2>
                  </div>
                  {compareAi?.model ? <span className="status-badge muted">{compareAi.model}</span> : null}
                </div>
                <CompareSummaryText summary={compareAi} language={language} />
                {compareSummary.methodology ? (
                  <div className="compare-methodology">
                    <strong>{ct(language, "methodology")}</strong>
                    <p>{compareSummary.methodology}</p>
                  </div>
                ) : null}
                {compareErrors.length ? (
                  <div className="compare-errors">
                    <strong>{ct(language, "errors")}</strong>
                    {compareErrors.map((error) => (
                      <p key={`${error.company}-${error.error}`}>{error.company}: {error.error}</p>
                    ))}
                  </div>
                ) : null}
              </article>

              {compareSecondaryCharts.length ? (
                <article className="panel compare-charts-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "charts")}</div>
                      <h2>{ct(language, "charts")}</h2>
                    </div>
                  </div>
                  <div className="compare-chart-grid">
                    {compareSecondaryCharts.map((chart) => (
                      <CompareChartCard key={chart.id || chart.title} chart={chart} language={language} />
                    ))}
                  </div>
                </article>
              ) : null}

              {Object.keys(compareTables).length ? (
                <article className="panel compare-tables-panel">
                  <div className="panel-head">
                    <div>
                      <div className="panel-label">{ct(language, "tables")}</div>
                      <h2>{ct(language, "tables")}</h2>
                    </div>
                  </div>
                  <div className="compare-tables-grid">
                    {Object.entries(compareTables).map(([key, table]) => (
                      <CompareTable key={key} table={table} title={compareTableTitle(language, key)} language={language} />
                    ))}
                  </div>
                </article>
              ) : null}
            </section>
          )}
        </main>

        <footer className="app-footer">
          <DisclaimerNote language={language} variant="footer" />
        </footer>
      </div>

      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((current) => current.filter((item) => item.id !== id))} language={language} />
      {/* No advertising on the maintenance page: it is staff-facing, it covers
          the bottom-right of the findings table, and there is nobody there to
          sell to. */}
      {activeView !== "admin" && <SponsorOverlay language={language} />}
    </div>
  );
}

// Floating sponsor unit — the format the reference used: a small player that
// sits over the page, starts muted on its own, counts down, and can be closed.
//
// Rules it keeps, because an ad that breaks them is a bug: sound never starts
// on its own (browsers refuse it anyway, and it is rude); the close control
// always arrives, on a visible countdown; once dismissed or finished it stays
// gone for the rest of the session; and a reader who asked the OS for reduced
// motion gets the poster with a play button instead of a moving picture.
//
// What the countdown promises is the first SPONSOR_CLOSE_AFTER seconds of the
// clip, not fifteen seconds of a frozen first frame — so while it runs the unit
// cannot be stopped. A click may still START it, and the sound toggle stays
// live; only the pause is withheld, and only until the × arrives.
const SPONSOR_SEEN_KEY = "uz_sponsor_seen";
const SPONSOR_DELAY_MS = 2500;   // let the page settle before anything moves
const SPONSOR_CLOSE_AFTER = 15;  // seconds before the × replaces the countdown

function SponsorOverlay({ language }) {
  const [open, setOpen] = useState(false);
  const [muted, setMuted] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [left, setLeft] = useState(SPONSOR_CLOSE_AFTER);
  const [progress, setProgress] = useState(0);
  // Bumped by a click the countdown refused: it replays the pill's pulse, so a
  // click that does nothing still points at the reason it did nothing.
  const [nudge, setNudge] = useState(0);
  const videoRef = useRef(null);
  const reduced = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // The mandatory window. Reduced motion is exempt: that reader was never given
  // a playing clip to stop, only the poster and a play button.
  const locked = open && !reduced && left > 0;

  useEffect(() => {
    try { if (sessionStorage.getItem(SPONSOR_SEEN_KEY)) return undefined; } catch (e) { /* ignore */ }
    const id = setTimeout(() => setOpen(true), SPONSOR_DELAY_MS);
    return () => clearTimeout(id);
  }, []);

  const dismiss = () => {
    setOpen(false);
    try { sessionStorage.setItem(SPONSOR_SEEN_KEY, "1"); } catch (e) { /* ignore */ }
  };

  // Muted autoplay is the only autoplay a browser allows. If it is refused
  // anyway (some mobile data-saver modes), fall back to the poster and a play
  // button rather than leaving a dead black rectangle on the page.
  useEffect(() => {
    if (!open || reduced) return;
    const v = videoRef.current;
    if (!v) return;
    v.muted = true;
    v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  }, [open, reduced]);

  // The countdown runs on the wall clock, not on playback: a clip that never
  // starts must still become closable.
  useEffect(() => {
    if (!open) return undefined;
    setLeft(SPONSOR_CLOSE_AFTER);
    const id = setInterval(() => setLeft((n) => (n <= 1 ? 0 : n - 1)), 1000);
    return () => clearInterval(id);
  }, [open]);

  // Our own click handler is not the only way to stop a video: OS media keys,
  // the picture-in-picture window and a phone's app switcher all pause it. While
  // the countdown runs the unit puts itself back — the guard lives on the `pause`
  // event, so it holds whatever route the pause arrived by.
  useEffect(() => {
    if (!locked) return undefined;
    const v = videoRef.current;
    if (!v) return undefined;
    const resume = () => {
      // The pause that closes a clip is it finishing, not a viewer stopping it.
      if (v.ended || (v.duration && v.currentTime >= v.duration - 0.25)) return;
      // If the browser refuses (a data-saver mode, a backgrounded tab), show the
      // ▶ again rather than leaving a still frame nobody can restart.
      v.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
    };
    // Coming back to a backgrounded tab: the browser paused it there and does not
    // resume on its own, which would otherwise hand back a way to sit out the
    // window with the clip stopped.
    const onVisible = () => { if (!document.hidden && v.paused) resume(); };
    v.addEventListener("pause", resume);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      v.removeEventListener("pause", resume);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [locked]);

  if (!open) return null;

  const label = language === "en" ? "Advertisement" : language === "uz" ? "Reklama" : "Реклама";
  const closeLabel = language === "en" ? "Close" : language === "uz" ? "Yopish" : "Закрыть";
  const soundLabel = muted
    ? (language === "en" ? "Sound on" : language === "uz" ? "Ovozni yoqish" : "Включить звук")
    : (language === "en" ? "Sound off" : language === "uz" ? "Ovozni o'chirish" : "Выключить звук");

  const toggleSound = () => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !v.muted;
    setMuted(v.muted);
    if (!v.muted && v.paused) v.play().then(() => setPlaying(true)).catch(() => {});
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    // Starting it is always allowed — it is the stopping that the countdown
    // withholds, and a clip whose autoplay was refused still needs a way in.
    if (v.paused) { v.play().then(() => setPlaying(true)).catch(() => {}); return; }
    if (locked) { setNudge((n) => n + 1); return; }
    v.pause();
    setPlaying(false);
  };

  return createPortal(
    <aside className="sponsor-overlay" role="complementary" aria-label={label}>
      <div className="sponsor-overlay-frame">
        <video
          ref={videoRef}
          src={promoVideo}
          poster={promoPoster}
          muted={muted}
          playsInline
          preload="auto"
          className={locked && playing ? "is-locked" : undefined}
          onClick={togglePlay}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            if (v.duration) setProgress((v.currentTime / v.duration) * 100);
          }}
          onEnded={dismiss}
        />

        <button type="button" className="sponsor-overlay-sound" onClick={toggleSound} title={soundLabel} aria-label={soundLabel}>
          {muted ? "🔇" : "🔊"}
        </button>

        {left > 0 ? (
          /* Keyed on the nudge counter so a refused click remounts the pill and
             replays its pulse — a CSS animation does not restart on a class that
             is already there. */
          <span key={nudge} className={`sponsor-overlay-count${nudge ? " is-nudged" : ""}`} aria-hidden="true">{left}</span>
        ) : (
          <button type="button" className="sponsor-overlay-close" onClick={dismiss} title={closeLabel} aria-label={closeLabel}>×</button>
        )}

        {!playing && (
          <button type="button" className="sponsor-overlay-play" onClick={togglePlay} aria-label={closeLabel === "Close" ? "Play" : "Смотреть"}>▶</button>
        )}

        <span className="sponsor-overlay-label">{label}</span>
        <div className="sponsor-overlay-bar"><i style={{ width: `${progress}%` }} /></div>
      </div>
    </aside>,
    document.body
  );
}

function SignalCard({ label, value, sub, tone = "neutral" }) {
  return (
    <article className={`mini-market-card tone-${tone}`} data-tone={tone}>
      <span className="mini-market-label">{label}</span>
      <strong>{value}</strong>
      <p>{sub}</p>
    </article>
  );
}

const HERO_LABELS = {
  ru: { revenue: "Выручка", profit: "Чистая прибыль", roe: "Доходность капитала (ROE)", noData: "Нет данных" },
  en: { revenue: "Revenue", profit: "Net income", roe: "Return on equity (ROE)", noData: "No data" },
  uz: { revenue: "Daromad", profit: "Sof foyda", roe: "Kapital rentabelligi (ROE)", noData: "Maʼlumot yoʻq" },
};

function HeroKpiTile({ label, value, year, change, tone = "neutral", hint }) {
  const arrow = change == null ? null : change > 0 ? "▲" : change < 0 ? "▼" : "→";
  const yoyText = change == null ? null : `${arrow} ${formatSignedPercent(change)}`;
  return (
    <article className={`hero-kpi-tile tone-${tone}`}>
      <span className="hero-kpi-label">{label}</span>
      <strong className="hero-kpi-value">{value}</strong>
      <div className="hero-kpi-foot">
        {yoyText && <span className={`hero-kpi-yoy tone-${tone}`}>{yoyText}</span>}
        {year && <span className="hero-kpi-year">{year}</span>}
        {hint && !year && <span className="hero-kpi-year">{hint}</span>}
      </div>
    </article>
  );
}

const BANK_METRIC_LABELS = {
  ru: {
    title: "Банковские коэффициенты",
    car: "Достаточность капитала",
    nim: "Чистая процентная маржа",
    ldr: "Кредиты / депозиты",
    cir: "Cost-to-Income",
  },
  en: {
    title: "Banking ratios",
    car: "Capital adequacy",
    nim: "Net interest margin",
    ldr: "Loan-to-deposit",
    cir: "Cost-to-Income",
  },
  uz: {
    title: "Bank koeffitsientlari",
    car: "Kapital yetarliligi",
    nim: "Sof foiz marjasi",
    ldr: "Kreditlar / depozitlar",
    cir: "Cost-to-Income",
  },
};

function BankMetricCell({ label, value, tone = "neutral", note, language }) {
  return (
    <article className={`bank-metric-cell tone-${tone}`}>
      <span className="bank-metric-label">{label}</span>
      <strong className="bank-metric-value">{value ?? "—"}</strong>
      {note && <p className="bank-metric-note">{note}</p>}
    </article>
  );
}

function BankMetricsPanel({ analysisResult, language }) {
  const bank = analysisResult?.ifrs_snapshot?.bank;
  if (!bank || !bank.is_bank) return null;
  const lbl = BANK_METRIC_LABELS[language] || BANK_METRIC_LABELS.ru;
  const tones = bank.tones || {};
  const notes = bank.notes || {};
  const fmt = (v) => v == null ? "—" : `${formatRatio(v, 1, language)}%`;
  return (
    <article className="panel bank-metrics-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{lbl.title}</div>
          <h3>{lbl.title}</h3>
        </div>
      </div>
      <div className="bank-metrics-grid">
        <BankMetricCell label={lbl.car} value={fmt(bank.car_simple_pct)} tone={tones.car_simple_pct} note={notes.car_simple_pct} language={language} />
        <BankMetricCell label={lbl.nim} value={fmt(bank.nim_pct)} tone={tones.nim_pct} note={notes.nim_pct} language={language} />
        <BankMetricCell label={lbl.ldr} value={fmt(bank.ldr_pct)} tone={tones.ldr_pct} note={notes.ldr_pct} language={language} />
        <BankMetricCell label={lbl.cir} value={fmt(bank.cir_pct)} tone={tones.cir_pct} note={notes.cir_pct} language={language} />
      </div>
    </article>
  );
}

const RISK_PANEL_TITLE = { ru: "Профиль риска", en: "Risk profile", uz: "Risk profili" };

// ТЗ §3.4 — structured 3-axis risk profile (financial / market / informational),
// each Low/Medium/High with the concrete drivers behind it. Data comes from the
// backend `risk_profile` field; purely factual, no recommendation.
function RiskProfilePanel({ analysisResult, language }) {
  const rp = analysisResult?.risk_profile;
  if (!rp || !Array.isArray(rp.axes) || !rp.axes.length) return null;
  const title = RISK_PANEL_TITLE[language] || RISK_PANEL_TITLE.ru;
  const toneOf = (lvl) => (lvl === "high" ? "danger" : lvl === "medium" ? "warning" : lvl === "low" ? "good" : "neutral");
  const dl = rp.debt_load;
  const dlLabel = language === "en" ? "Debt load" : language === "uz" ? "Qarz yuki" : "Долговая нагрузка";
  return (
    <article className="panel bank-metrics-panel risk-profile-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
        {dl && (
          <span className={`debt-load-badge tone-${dl.tone}`}>
            {dlLabel}: <strong>{dl.label}</strong>
            {dl.debt_to_ebitda != null ? ` · Долг/EBITDA ${dl.debt_to_ebitda}×` : dl.debt_to_equity != null ? ` · D/E ${dl.debt_to_equity}×` : ""}
          </span>
        )}
      </div>
      <div className="bank-metrics-grid risk-profile-grid">
        {rp.axes.map((ax) => (
          <div key={ax.key} className={`bank-metric-cell tone-${toneOf(ax.level)}`}>
            <div className="bank-metric-label">{ax.label}</div>
            <div className="bank-metric-value">{ax.level_label}</div>
            {Array.isArray(ax.drivers) && ax.drivers.length > 0 && (
              <ul className="risk-drivers">
                {ax.drivers.map((d, i) => <li key={i}>{d}</li>)}
              </ul>
            )}
          </div>
        ))}
      </div>
    </article>
  );
}

const OBS_TITLE = { ru: "Статистические наблюдения", en: "Statistical observations", uz: "Statistik kuzatuvlar" };

// ТЗ §3.5 — factual statistical observations (anomaly vs own history, joint
// multi-metric shift, sector deviation). Facts, not diagnoses. Hidden if empty.
function ObservationsPanel({ analysisResult, language }) {
  const obs = analysisResult?.observations;
  if (!Array.isArray(obs) || !obs.length) return null;
  const title = OBS_TITLE[language] || OBS_TITLE.ru;
  return (
    <article className="panel observations-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
      </div>
      <ul className="observations-list">
        {obs.map((o, i) => (
          <li key={i} className={`observation-item tone-${o.tone || "neutral"}`}>{o.text}</li>
        ))}
      </ul>
    </article>
  );
}

const STRUCT_TITLE = { ru: "Структура баланса по годам", en: "Balance structure by year", uz: "Balans tuzilmasi (yillar bo'yicha)" };
const STRUCT_LEGEND = {
  ru: { equity: "Капитал", liabilities: "Обязательства" },
  en: { equity: "Equity", liabilities: "Liabilities" },
  uz: { equity: "Kapital", liabilities: "Majburiyatlar" },
};

// ТЗ §3.4 — stacked structural chart: equity + liabilities = assets, per year,
// so the capital structure's evolution is visible at a glance. Data from the
// annual series (segment revenue is not collected, so segments are omitted).
function StructureCharts({ analysisResult, language }) {
  const annual = analysisResult?.ifrs_snapshot?.series?.annual;
  if (!Array.isArray(annual) || annual.length < 2) return null;
  const rows = annual
    .map((r) => {
      const assets = safeNumber(r.total_assets ?? r.assets);
      const equity = safeNumber(r.equity);
      let liab = safeNumber(r.total_liabilities);
      if (liab === null && assets !== null && equity !== null) liab = Math.max(0, assets - equity);
      const total = assets ?? ((equity || 0) + (liab || 0));
      return { year: r.year, equity: equity || 0, liabilities: liab || 0, total };
    })
    .filter((r) => r.total && r.total > 0);
  if (rows.length < 2) return null;
  const maxA = Math.max(...rows.map((r) => r.total));
  const leg = STRUCT_LEGEND[language] || STRUCT_LEGEND.ru;
  const title = STRUCT_TITLE[language] || STRUCT_TITLE.ru;
  const W = 640, H = 240, PAD_B = 26, PAD_T = 12;
  const slot = (W - 20) / rows.length;
  const bw = Math.min(64, slot - 16);
  const scale = (H - PAD_B - PAD_T) / maxA;
  return (
    <article className="panel structure-panel">
      <div className="panel-head">
        <div>
          <div className="panel-label">{title}</div>
          <h3>{title}</h3>
        </div>
        <div className="structure-legend">
          <span className="structure-legend-item"><i className="structure-swatch structure-swatch--equity" />{leg.equity}</span>
          <span className="structure-legend-item"><i className="structure-swatch structure-swatch--liab" />{leg.liabilities}</span>
        </div>
      </div>
      <div className="structure-chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} className="structure-svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label={title}>
          {rows.map((r, i) => {
            const x = 10 + i * slot + (slot - bw) / 2;
            const eqH = Math.max(0, r.equity * scale);
            const liH = Math.max(0, r.liabilities * scale);
            return (
              <g key={r.year}>
                <rect x={x} y={H - PAD_B - eqH} width={bw} height={eqH} className="structure-bar-equity" rx="2" />
                <rect x={x} y={H - PAD_B - eqH - liH} width={bw} height={liH} className="structure-bar-liab" rx="2" />
                <text x={x + bw / 2} y={H - PAD_B + 15} className="structure-year">{r.year}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </article>
  );
}

function HeroKpiStrip({ analysisResult, chartData, language }) {
  const lbl = HERO_LABELS[language] || HERO_LABELS.ru;
  const ifrs = analysisResult?.ifrs_snapshot || {};
  const quality = ifrs.quality || {};
  const latest = chartData?.latest;
  const noData = lbl.noData;

  // Revenue
  const revenue = latest && Number.isFinite(latest.revenue) ? latest.revenue : null;
  const revenueChange = chartData?.revenueChange;
  const revenueTone = revenueChange == null ? "neutral" : revenueChange >= 10 ? "good" : revenueChange >= 0 ? "warning" : "danger";

  // Net income
  const profit = latest && Number.isFinite(latest.profit) ? latest.profit : null;
  const profitChange = chartData?.profitChange;
  const profitTone = profitChange == null ? "neutral" : profitChange >= 10 ? "good" : profitChange >= 0 ? "warning" : "danger";

  // ROE
  const roe = Number(quality.roe_pct);
  const haveRoe = Number.isFinite(roe);
  const roeTone = !haveRoe ? "neutral" : roe >= 15 ? "good" : roe >= 5 ? "warning" : "danger";

  return (
    <div className="hero-kpi-strip">
      <HeroKpiTile
        label={lbl.revenue}
        value={revenue != null ? formatCompactNumber(revenue, language) : noData}
        year={latest?.year ?? null}
        change={revenueChange}
        tone={revenueTone}
      />
      <HeroKpiTile
        label={lbl.profit}
        value={profit != null ? formatCompactNumber(profit, language) : noData}
        year={latest?.year ?? null}
        change={profitChange}
        tone={profitTone}
      />
      <HeroKpiTile
        label={lbl.roe}
        value={haveRoe ? `${formatRatio(roe, 1, language)}%` : noData}
        year={null}
        change={null}
        tone={roeTone}
      />
    </div>
  );
}

function MetricRing({ label, percent, display, tone = "neutral", termId, lang }) {
  const value = clampPercent(percent);
  const radius = 38;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - ((value ?? 0) / 100) * circumference;

  return (
    <div className={`metric-ring tone-${tone}`}>
      <svg viewBox="0 0 104 104" role="img" aria-label={label}>
        <circle className="metric-ring-track" cx="52" cy="52" r={radius} />
        <circle
          className="metric-ring-progress"
          cx="52"
          cy="52"
          r={radius}
          style={{ strokeDasharray: circumference, strokeDashoffset: dashOffset }}
        />
      </svg>
      <div className="metric-ring-center">
        <strong>{display}</strong>
      </div>
      <span>{label}{termId && <TermInfo termId={termId} lang={lang} label={label} />}</span>
    </div>
  );
}

function FinancialVisuals({ result, language, score }) {
  if (!result) return null;

  const snapshot = result?.ifrs_snapshot || {};
  const metrics = result?.metrics || {};
  const annualSeries = Array.isArray(snapshot?.series?.annual) ? snapshot.series.annual : [];
  const latestAnnual = annualSeries.at(-1) || {};
  const income = snapshot?.income_statement || {};
  const balance = snapshot?.balance_sheet || {};
  const pickNumber = (...values) => {
    for (const value of values) {
      const number = safeNumber(value);
      if (number !== null) return number;
    }
    return null;
  };
  const makeRow = (key, value, tone = "neutral") => ({
    key,
    label: vt(language, key),
    value,
    tone,
  });

  const revenue = pickNumber(latestAnnual.revenue, income.revenue, income.sales);
  const ebitda = pickNumber(income.ebitda);
  const netIncome = pickNumber(latestAnnual.net_income, income.net_income, income.profit);
  const assets = pickNumber(latestAnnual.assets, latestAnnual.total_assets, balance.assets, balance.total_assets);
  const equity = pickNumber(latestAnnual.equity, latestAnnual.total_equity, balance.equity, balance.total_equity);
  const debt = pickNumber(latestAnnual.debt, latestAnnual.total_debt, latestAnnual.total_liabilities, balance.debt, balance.total_debt, balance.total_liabilities);
  const rows = [
    makeRow("revenue", revenue, "good"),
    makeRow("ebitda", ebitda, "good"),
    makeRow("netIncome", netIncome, netIncome === null ? "neutral" : netIncome >= 0 ? "good" : "danger"),
    makeRow("assets", assets, "neutral"),
    makeRow("equity", equity, "good"),
    makeRow("debt", debt, "warning"),
  ].filter((row) => row.value !== null);
  const maxAbs = Math.max(1, ...rows.map((row) => Math.abs(row.value)));

  const roePct = pickNumber(result?.ifrs_snapshot?.quality?.roe_pct, latestAnnual?.roe_pct);
  const netMarginPct = pickNumber(result?.ifrs_snapshot?.income_statement?.net_margin_pct, latestAnnual?.net_margin_pct);
  const debtToEquity = pickNumber(balance?.debt_to_equity, latestAnnual?.debt_to_equity);
  const ebitdaMarginPct = pickNumber(income?.ebitda_margin_pct);
  const debtToEbitda = pickNumber(income?.debt_to_ebitda);
  // ТЗ compliance: the composite total_score ring is dropped (it's an
  // attractiveness verdict). Rings show only factual ratios. EBITDA-margin and
  // Debt/EBITDA appear only when the filing disclosed D&A (§3.3).
  const rings = [
    {
      label: language === "en" ? "ROE" : language === "uz" ? "ROE" : "ROE",
      termId: "roe",
      percent: roePct === null ? null : Math.min(100, Math.max(0, roePct / 30 * 100)),
      display: roePct === null ? "—" : `${formatRatio(roePct, 1, language)}%`,
      tone: roePct === null ? "neutral" : roePct >= 15 ? "good" : roePct >= 5 ? "warning" : "danger",
    },
    {
      label: language === "en" ? "Net margin" : language === "uz" ? "Sof marja" : "Чистая маржа",
      termId: "netMargin",
      percent: netMarginPct === null ? null : Math.min(100, Math.max(0, netMarginPct / 25 * 100)),
      display: netMarginPct === null ? "—" : `${formatRatio(netMarginPct, 1, language)}%`,
      tone: netMarginPct === null ? "neutral" : netMarginPct >= 10 ? "good" : netMarginPct >= 3 ? "warning" : "danger",
    },
    ebitdaMarginPct === null ? null : {
      label: language === "en" ? "EBITDA margin" : language === "uz" ? "EBITDA marjasi" : "Маржа EBITDA",
      termId: "ebitda",
      percent: Math.min(100, Math.max(0, ebitdaMarginPct / 40 * 100)),
      display: `${formatRatio(ebitdaMarginPct, 1, language)}%`,
      tone: ebitdaMarginPct >= 15 ? "good" : ebitdaMarginPct >= 5 ? "warning" : "danger",
    },
    {
      label: vt(language, "leverage"),
      termId: "debtEq",
      percent: debtToEquity === null ? null : 100 / (1 + Math.max(0, debtToEquity)),
      display: debtToEquity === null ? "—" : `D/E ${formatRatio(debtToEquity, 2, language)}`,
      tone: debtToEquity === null ? "neutral" : debtToEquity <= 1 ? "good" : debtToEquity <= 2 ? "warning" : "danger",
    },
    debtToEbitda === null ? null : {
      label: language === "en" ? "Debt/EBITDA" : language === "uz" ? "Qarz/EBITDA" : "Долг/EBITDA",
      termId: "debtEbitda",
      percent: Math.min(100, Math.max(0, 100 - debtToEbitda / 6 * 100)),
      display: `${formatRatio(debtToEbitda, 2, language)}×`,
      tone: debtToEbitda <= 2 ? "good" : debtToEbitda <= 4 ? "warning" : "danger",
    },
  ].filter(Boolean);

  return (
    <div className="financial-visual-grid">
      <article className="visual-panel financial-bars-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "financialStructure")}</h3>
          </div>
          <span>{vt(language, "financialStructureCopy")}</span>
        </div>
        {rows.length ? (
          <div className="financial-bars">
            {rows.map((row) => (
              <div key={row.key} className={`financial-bar-row tone-${row.tone}`}>
                <div className="financial-bar-label">
                  <span>{row.label}</span>
                  <strong>{formatCompactNumber(row.value, language)}</strong>
                </div>
                <div className="financial-bar-track">
                  <span className={row.value < 0 ? "is-negative" : ""} style={{ width: `${Math.max(4, (Math.abs(row.value) / maxAbs) * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="visual-empty">{vt(language, "noVisualData")}</div>
        )}
      </article>

      <article className="visual-panel metric-rings-panel">
        <div className="visual-panel-head">
          <div>
            <div className="panel-label">{vt(language, "latestPeriod")}</div>
            <h3>{vt(language, "scoreAndRisk")}</h3>
          </div>
          <span>{vt(language, "scoreAndRiskCopy")}</span>
        </div>
        <div className="metric-rings-grid">
          {rings.map((ring) => (
            <MetricRing key={ring.label} {...ring} lang={normalizeLanguage(language)} />
          ))}
        </div>
      </article>
    </div>
  );
}

function AnalysisChart({ chartData, language }) {
  if (!chartData) {
    return (
      <div className="analysis-chart empty-state">
        <p className="empty-copy">{t(language, "analysis.chartEmpty")}</p>
      </div>
    );
  }

  const { width, height, filtered, areaPath, revenuePath, profitPath, debtPath, yTicks, x, y, revenueChange, profitChange, debtChange, latest } = chartData;

  return (
    <div className="analysis-chart">
      <svg className="result-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "analysis.chartTitle")}>
        <defs>
          <linearGradient id="revenueAreaGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#6ef0c1" stopOpacity="0.42" />
            <stop offset="100%" stopColor="#6ef0c1" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {yTicks.map((tick, index) => (
          <g key={index}>
            <line x1="74" y1={tick.y} x2={width - 24} y2={tick.y} className="chart-grid-line" />
            <text x="64" y={tick.y + 4} className="chart-axis-label chart-axis-label-y" textAnchor="end">
              {formatCompactNumber(tick.value, language)}
            </text>
          </g>
        ))}
        <path d={areaPath} className="chart-area" />
        <path d={revenuePath} className="chart-line chart-line-revenue" />
        <path d={profitPath} className="chart-line chart-line-profit" />
        <path d={debtPath} className="chart-line chart-line-debt" />
        {filtered.map((point, index) => (
          <g key={`${point.year}-${index}`}>
            <circle cx={x(index)} cy={y(point.revenue ?? 0)} r="4.8" className="chart-dot chart-dot-revenue" />
            <circle cx={x(index)} cy={y(point.profit ?? 0)} r="4.8" className="chart-dot chart-dot-profit" />
            <circle cx={x(index)} cy={y(point.debt ?? 0)} r="4.8" className="chart-dot chart-dot-debt" />
          </g>
        ))}
        {filtered.map((point, index) => (
          <text key={`${point.year}-label`} x={x(index)} y={height - 16} className="chart-axis-label chart-axis-label-x" textAnchor="middle">
            {point.year}
          </text>
        ))}
      </svg>

      <div className="chart-legend">
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-revenue" />
          <span className="legend-label">{t(language, "analysis.signalRevenue")}</span>
          <strong className="legend-value">{formatCompactNumber(latest.revenue, language)}</strong>
          <span className={`legend-delta ${revenueChange === null ? "" : revenueChange >= 0 ? "is-up" : "is-down"}`}>
            {revenueChange === null ? "—" : formatSignedPercent(revenueChange)}
          </span>
        </div>
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-profit" />
          <span className="legend-label">{t(language, "analysis.signalLatest")}</span>
          <strong className="legend-value">{latest.profit != null ? formatCompactNumber(latest.profit, language) : "—"}</strong>
          <span className={`legend-delta ${profitChange === null ? "" : profitChange >= 0 ? "is-up" : "is-down"}`}>
            {profitChange === null ? "—" : formatSignedPercent(profitChange)}
          </span>
        </div>
        <div className="legend-chip">
          <span className="legend-swatch legend-swatch-debt" />
          <span className="legend-label">{t(language, "analysis.signalDebt")}</span>
          <strong className="legend-value">{latest.debt != null ? formatCompactNumber(latest.debt, language) : "—"}</strong>
          <span className={`legend-delta ${debtChange === null ? "" : debtChange >= 0 ? "is-down" : "is-up"}`}>
            {debtChange === null ? "—" : formatSignedPercent(debtChange)}
          </span>
        </div>
      </div>

      <div className="chart-axis-note">
        <span>{filtered[0]?.year || ""}</span>
        <span>{filtered.at(-1)?.year || ""}</span>
      </div>
    </div>
  );
}

function ActivityChart({ series, language }) {
  const hasData = Boolean(series?.days?.some((day) => day.count > 0));

  if (!hasData) {
    return (
      <div className="activity-chart empty-state">
        <p className="empty-copy">{t(language, "dashboard.activityEmpty")}</p>
      </div>
    );
  }

  const width = 1000;
  const height = 280;
  const padding = { left: 20, right: 20, top: 20, bottom: 44 };
  const innerWidth = width - padding.left - padding.right;
  const innerHeight = height - padding.top - padding.bottom;
  const barGap = 12;
  const barWidth = (innerWidth - barGap * (series.days.length - 1)) / series.days.length;

  return (
    <div className="activity-chart">
      <svg className="activity-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t(language, "dashboard.activityTitle")}>
        <defs>
          <linearGradient id="activityBarGradient" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#2563eb" stopOpacity="0.92" />
            <stop offset="100%" stopColor="#10b981" stopOpacity="0.34" />
          </linearGradient>
        </defs>
        {series.days.map((day, index) => {
          const barHeight = ((day.count || 0) / series.maxCount) * innerHeight;
          const x = padding.left + index * (barWidth + barGap);
          const y = padding.top + innerHeight - barHeight;
          const hasActivity = day.count > 0;
          return (
            <g key={day.key}>
              <rect x={x} y={padding.top} width={barWidth} height={innerHeight} rx="16" className={`activity-bar-track ${hasActivity ? "has-activity" : ""}`} />
              {hasActivity && <rect x={x} y={y} width={barWidth} height={barHeight} rx="16" className="activity-bar" />}
              <text x={x + barWidth / 2} y={height - 16} textAnchor="middle" className={`activity-axis-label ${hasActivity ? "has-activity" : ""}`}>
                {day.shortLabel}
              </text>
              <text x={x + barWidth / 2} y={Math.max(y - 10, 16)} textAnchor="middle" className={`activity-value ${hasActivity ? "has-activity" : ""}`}>
                {day.count}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="activity-footer">
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.activityCopy")}</span>
          <strong>{series.total}</strong>
        </div>
        <div>
          <span className="activity-footer-label">{t(language, "dashboard.peak")}</span>
          <strong>{series.peak ? series.peak.label : "—"}</strong>
        </div>
      </div>
    </div>
  );
}

function ResultSkeleton({ language }) {
  return (
    <>
      <div className="score-strip">
        <div className="score-card skeleton-card">
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-sm" />
        </div>
        <div className="score-meta">
          <div className="grade-pill skeleton-pill" />
          <div className="skeleton-line skeleton-line-lg" />
          <div className="skeleton-line skeleton-line-md" />
        </div>
      </div>
      <div className="chart-card">
        <div className="chart-head">
          <div>
            <div className="panel-label">{t(language, "analysis.chartTitle")}</div>
            <div className="skeleton-line skeleton-line-md" />
          </div>
          <div className="skeleton-pill" />
        </div>
        <div className="chart-skeleton">
          <div className="chart-skeleton-grid">
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="chart-skeleton-wave">
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
      <div className="market-strip">
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
        <div className="mini-market-card skeleton-card" />
      </div>
    </>
  );
}

export default App;
