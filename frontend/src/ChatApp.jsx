import React, {
  useState,
  useEffect,
  useRef,
  useMemo,
  useCallback,
} from "react";
import {
  GLOSSARY,
  DisclaimerNote,
  ToastStack,
  HeroVerdictBlock,
  ReportArticleView,
  FinancialVisuals,
  BankMetricsPanel,
  CompareLeaderCards,
  CompareRanking,
  CompareChartCard,
  CompareTable,
  CompareSummaryText,
  CompanyPage,
  CompanyDividendsTab,
  enrichMarketStock,
  STORAGE_KEY,
  LANGUAGE_KEY,
  THEME_KEY,
} from "./App.jsx";

/* ══════════════════════════════════════════════════════════════════════════
   Localization for the chat shell (cards localize themselves via `language`).
   ══════════════════════════════════════════════════════════════════════════ */
const L = {
  ru: {
    title: "Аналитический AI-скринер",
    sub: "Рынок РФБ «Тошкент»",
    placeholder: "Спросите про компанию, сектор или рынок…",
    welcomeTitle: "С чего начнём?",
    welcomeSub:
      "Задайте вопрос про эмитента, сравните компании или посмотрите рынок. Я отвечаю фактами по отчётности и котировкам — без инвестиционных рекомендаций.",
    newChat: "Новый чат",
    quick: "Быстрые действия",
    recent: "История",
    signIn: "Войти",
    account: "Аккаунт",
    signOut: "Выйти",
    thinking: "Анализирую…",
    send: "Отправить",
    hint: "AI может ошибаться и не даёт инвестиционных рекомендаций.",
    and: "и",
    exAnalyze: "Проанализируй",
    exCompare: "Сравни",
    exMarket: "Что сейчас на рынке?",
    exScreener: "Самые дешёвые по P/E",
    exAnalyzeF: "Проанализируй эмитента",
    exCompareF: "Сравни две компании",
    labels: {
      analyze: "Анализ отчётности",
      compare: "Сравнение",
      market: "Обзор рынка",
      company: "Карточка эмитента",
      dividends: "Дивиденды",
      screener: "Скринер",
      glossary: "Справочник",
      listings: "Листинг",
      help: "Помощь",
    },
    marketTitle: "Обзор рынка",
    advancers: "Растут",
    decliners: "Падают",
    unchanged: "Без изменений",
    volume: "Оборот",
    instruments: "Инструменты",
    topGainers: "Лидеры роста",
    topLosers: "Лидеры падения",
    noMarket: "Рыночные данные сейчас недоступны.",
    screenerCheap: "Самые низкие P/E",
    screenerLargest: "Крупнейшие по капитализации",
    screenerGainers: "Лидеры роста",
    screenerLosers: "Лидеры падения",
    screenerEmpty: "Не нашёл бумаг под этот запрос.",
    listingNew: "Недавно в листинге",
    listingInactive: "Без сделок (неактивные)",
    listingEmpty: "Данных по листингу пока нет.",
    dividendsFor: "Дивиденды",
    glossaryNotFound:
      "Не нашёл точный термин. Вот несколько понятий из справочника:",
    helpText:
      "Я умею: разбирать отчётность эмитента, сравнивать компании, показывать обзор рынка и скринер по P/E, дивиденды, листинг и объяснять термины. Просто напишите тикер или вопрос.",
    errorGeneric: "Не удалось выполнить запрос. Попробуйте ещё раз.",
    emailPh: "Эл. почта",
    passwordPh: "Пароль",
    namePh: "Имя",
    login: "Вход",
    register: "Регистрация",
    google: "Продолжить с Google",
    or: "или",
    signedInAs: "Вы вошли как",
  },
  en: {
    title: "AI analytical screener",
    sub: "RSE «Toshkent» market",
    placeholder: "Ask about a company, a sector, or the market…",
    welcomeTitle: "Where shall we start?",
    welcomeSub:
      "Ask about an issuer, compare companies, or check the market. I answer with facts from filings and quotes — no investment advice.",
    newChat: "New chat",
    quick: "Quick actions",
    recent: "History",
    signIn: "Sign in",
    account: "Account",
    signOut: "Sign out",
    thinking: "Thinking…",
    send: "Send",
    hint: "AI can make mistakes and does not give investment advice.",
    and: "and",
    exAnalyze: "Analyze",
    exCompare: "Compare",
    exMarket: "What's on the market now?",
    exScreener: "Cheapest by P/E",
    exAnalyzeF: "Analyze an issuer",
    exCompareF: "Compare two companies",
    labels: {
      analyze: "Report analysis",
      compare: "Comparison",
      market: "Market overview",
      company: "Company page",
      dividends: "Dividends",
      screener: "Screener",
      glossary: "Glossary",
      listings: "Listings",
      help: "Help",
    },
    marketTitle: "Market overview",
    advancers: "Advancers",
    decliners: "Decliners",
    unchanged: "Unchanged",
    volume: "Turnover",
    instruments: "Instruments",
    topGainers: "Top gainers",
    topLosers: "Top losers",
    noMarket: "Market data is unavailable right now.",
    screenerCheap: "Lowest P/E",
    screenerLargest: "Largest by market cap",
    screenerGainers: "Top gainers",
    screenerLosers: "Top losers",
    screenerEmpty: "No securities matched that query.",
    listingNew: "Recently listed",
    listingInactive: "Inactive (no trades)",
    listingEmpty: "No listing data yet.",
    dividendsFor: "Dividends",
    glossaryNotFound: "No exact term found. Here are a few glossary entries:",
    helpText:
      "I can: analyze an issuer's filings, compare companies, show a market overview and a P/E screener, dividends, listings, and explain terms. Just type a ticker or a question.",
    errorGeneric: "Could not complete the request. Please try again.",
    emailPh: "Email",
    passwordPh: "Password",
    namePh: "Name",
    login: "Log in",
    register: "Register",
    google: "Continue with Google",
    or: "or",
    signedInAs: "Signed in as",
  },
  uz: {
    title: "AI tahliliy skrineri",
    sub: "RFB «Toshkent» bozori",
    placeholder: "Kompaniya, sektor yoki bozor haqida so'rang…",
    welcomeTitle: "Nimadan boshlaymiz?",
    welcomeSub:
      "Emitent haqida so'rang, kompaniyalarni solishtiring yoki bozorni ko'ring. Men hisobot va kotirovka faktlari bilan javob beraman — investitsiya tavsiyasisiz.",
    newChat: "Yangi chat",
    quick: "Tez amallar",
    recent: "Tarix",
    signIn: "Kirish",
    account: "Hisob",
    signOut: "Chiqish",
    thinking: "Tahlil qilyapman…",
    send: "Yuborish",
    hint: "AI xato qilishi mumkin va investitsiya tavsiyasi bermaydi.",
    and: "va",
    exAnalyze: "Tahlil qil",
    exCompare: "Solishtir",
    exMarket: "Bozorda nima bo'lyapti?",
    exScreener: "P/E bo'yicha eng arzonlari",
    exAnalyzeF: "Emitentni tahlil qil",
    exCompareF: "Ikki kompaniyani solishtir",
    labels: {
      analyze: "Hisobot tahlili",
      compare: "Taqqoslash",
      market: "Bozor sharhi",
      company: "Emitent kartasi",
      dividends: "Dividendlar",
      screener: "Skriner",
      glossary: "Lug'at",
      listings: "Listing",
      help: "Yordam",
    },
    marketTitle: "Bozor sharhi",
    advancers: "O'smoqda",
    decliners: "Tushmoqda",
    unchanged: "O'zgarishsiz",
    volume: "Aylanma",
    instruments: "Instrumentlar",
    topGainers: "O'sish liderlari",
    topLosers: "Tushish liderlari",
    noMarket: "Bozor ma'lumotlari hozircha mavjud emas.",
    screenerCheap: "Eng past P/E",
    screenerLargest: "Kapitalizatsiya bo'yicha eng yiriklari",
    screenerGainers: "O'sish liderlari",
    screenerLosers: "Tushish liderlari",
    screenerEmpty: "Bu so'rov bo'yicha qog'ozlar topilmadi.",
    listingNew: "Yaqinda listingda",
    listingInactive: "Nofaol (savdosiz)",
    listingEmpty: "Listing ma'lumoti yo'q.",
    dividendsFor: "Dividendlar",
    glossaryNotFound: "Aniq atama topilmadi. Mana lug'atdan bir nechta atama:",
    helpText:
      "Men: emitent hisobotini tahlil qilaman, kompaniyalarni solishtiraman, bozor sharhi va P/E skriner, dividendlar, listing va atamalarni tushuntiraman. Tiker yoki savol yozing.",
    errorGeneric: "So'rovni bajarib bo'lmadi. Qayta urinib ko'ring.",
    emailPh: "Email",
    passwordPh: "Parol",
    namePh: "Ism",
    login: "Kirish",
    register: "Ro'yxatdan o'tish",
    google: "Google bilan davom etish",
    or: "yoki",
    signedInAs: "Kirdingiz:",
  },
};
const lang3 = (l) => (L[l] ? l : "ru");

/* ── Inline icons ─────────────────────────────────────────────────────────── */
const I = {
  send: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
  ),
  plus: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
  ),
  menu: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" /></svg>
  ),
  sun: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
  ),
  moon: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
  ),
  user: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 21a8 8 0 0 0-16 0" /><circle cx="12" cy="7" r="4" /></svg>
  ),
  spark: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /></svg>
  ),
};

/* ── Error boundary: a bad renderer shows a message, never white-screens ──── */
class AnswerBoundary extends React.Component {
  constructor(p) {
    super(p);
    this.state = { failed: false };
  }
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(err) {
    // eslint-disable-next-line no-console
    console.error("Answer render failed:", err);
  }
  render() {
    if (this.state.failed) {
      return <div className="cx-error">{this.props.fallback || "—"}</div>;
    }
    return this.props.children;
  }
}

/* ── helpers ──────────────────────────────────────────────────────────────── */
let _mid = 0;
const nextId = () => `m${++_mid}`;

function resolveCompanies(text, companies) {
  if (!text || !companies || !companies.length) return [];
  const byTicker = new Map(
    companies.map((c) => [String(c.ticker || "").toUpperCase(), c])
  );
  const up = text.toUpperCase();
  const tokens = up.split(/[^A-ZА-ЯЁ0-9]+/).filter(Boolean);
  const seen = new Set();
  const found = [];
  for (const tk of tokens) {
    if (byTicker.has(tk) && !seen.has(tk)) {
      seen.add(tk);
      found.push(byTicker.get(tk));
    }
  }
  const low = text.toLowerCase();
  for (const c of companies) {
    const nm = String(c.company_name || "").toLowerCase();
    const key = String(c.ticker || "").toUpperCase();
    if (nm.length >= 4 && low.includes(nm) && !seen.has(key)) {
      seen.add(key);
      found.push(c);
    }
  }
  return found;
}

function findGlossaryTerm(text) {
  const low = text.toLowerCase();
  let best = null;
  let bestLen = 0;
  for (const g of GLOSSARY || []) {
    for (const it of g.terms || []) {
      // match on the term's core token (before a space or "(")
      const core = String(it.term).toLowerCase().split(/[\s(]/)[0].trim();
      if (core.length >= 2 && low.includes(core) && core.length > bestLen) {
        best = it;
        bestLen = core.length;
      }
    }
  }
  return best;
}

function detectIntent(text, companies) {
  const s = text.toLowerCase().trim();
  const matched = resolveCompanies(text, companies);
  if (/(сравн|compare|taqqosla|\bvs\b|против|solishtir)/.test(s) && matched.length >= 2)
    return { intent: "compare", companies: matched.slice(0, 5) };
  if (/(дивиденд|dividend)/.test(s) && matched.length >= 1)
    return { intent: "dividends", company: matched[0] };
  if (/(карточк|профил|обзор компан|company page|снапшот|snapshot|karta)/.test(s) && matched.length >= 1)
    return { intent: "company", company: matched[0] };
  if (/(проанализир|анализ|разбор|analyz|analiz|tahlil|отч[её]т|hisobot)/.test(s) && matched.length >= 1)
    return { intent: "analyze", company: matched[0] };
  if (/(листинг|делистинг|listing|delisting|новые бумаг|new listing)/.test(s))
    return { intent: "listings" };
  if (/(что такое|что значит|определение|what is|glossary|нима|ma'nosi|lug'at)/.test(s))
    return { intent: "glossary", term: findGlossaryTerm(text) };
  if (/(дешёв|дешев|cheap|p\/?e\b|мультипликат|крупнейш|largest|biggest|растут|лидеры рост|gainers|падают|losers|скринер|screener|покажи|найди|компании с|eng arzon)/.test(s))
    return { intent: "screener", query: s };
  if (/(рынок|рынк|market|bozor|обзор|индекс|котировк|movers)/.test(s))
    return { intent: "market" };
  if (matched.length >= 2) return { intent: "compare", companies: matched.slice(0, 5) };
  if (matched.length === 1) return { intent: "analyze", company: matched[0] };
  return { intent: "help" };
}

const num = (v) =>
  typeof v === "number" && isFinite(v) ? v : Number.parseFloat(v);
function fmtCompact(v, lang) {
  const n = num(v);
  if (!isFinite(n)) return "—";
  const loc = lang === "en" ? "en-US" : lang === "uz" ? "uz-UZ" : "ru-RU";
  try {
    return new Intl.NumberFormat(loc, { notation: "compact", maximumFractionDigits: 1 }).format(n);
  } catch {
    return String(Math.round(n));
  }
}
const pctStr = (v) => {
  const n = num(v);
  if (!isFinite(n)) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
};

/* ══════════════════════════════════════════════════════════════════════════
   Main component
   ══════════════════════════════════════════════════════════════════════════ */
export default function ChatApp() {
  const [language, setLanguage] = useState(
    () => localStorage.getItem(LANGUAGE_KEY) || "ru"
  );
  const [theme, setTheme] = useState(
    () => document.documentElement.dataset.theme || localStorage.getItem(THEME_KEY) || "light"
  );
  const [token, setToken] = useState(() => localStorage.getItem(STORAGE_KEY) || "");
  const [user, setUser] = useState(null);

  const [companies, setCompanies] = useState([]);
  const [securitiesMap, setSecuritiesMap] = useState({});
  const [marketFinancials, setMarketFinancials] = useState({});
  const [marketTradeStats, setMarketTradeStats] = useState({});
  const [marketRows, setMarketRows] = useState([]);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  const [authOpen, setAuthOpen] = useState(false);
  const [authTab, setAuthTab] = useState("login");
  const [authForm, setAuthForm] = useState({ full_name: "", email: "", password: "" });
  const [authMsg, setAuthMsg] = useState("");
  const [authBusy, setAuthBusy] = useState(false);

  const lx = useCallback((k) => L[lang3(language)][k] ?? L.ru[k], [language]);
  const threadRef = useRef(null);
  const textareaRef = useRef(null);

  /* ---- api helper ---- */
  const apiFetch = useCallback(
    (path, options = {}) => {
      const headers = { ...(options.headers || {}) };
      if (!(options.body instanceof FormData))
        headers["Content-Type"] = headers["Content-Type"] || "application/json";
      if (token) headers.Authorization = `Bearer ${token}`;
      return fetch(path, { ...options, headers });
    },
    [token]
  );

  const addToast = useCallback((message, tone = "info") => {
    const id = nextId();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  /* ---- persist theme & language ---- */
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    localStorage.setItem(THEME_KEY, theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0a0e16" : "#f5f7fa");
  }, [theme]);
  useEffect(() => {
    localStorage.setItem(LANGUAGE_KEY, language);
    document.documentElement.lang = language;
  }, [language]);
  useEffect(() => {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
  }, [token]);

  /* ---- OAuth return (#token=…&provider=…) ---- */
  useEffect(() => {
    if (window.location.hash.includes("token=")) {
      const params = new URLSearchParams(window.location.hash.slice(1));
      const tk = params.get("token");
      if (tk) {
        setToken(tk);
        window.history.replaceState(null, "", window.location.pathname);
      }
    }
  }, []);

  /* ---- initial data loads ---- */
  useEffect(() => {
    let alive = true;
    fetch("/api/companies")
      .then((r) => r.json())
      .then((d) => alive && setCompanies(d.companies || []))
      .catch(() => {});
    fetch("/api/securities")
      .then((r) => r.json())
      .then((d) => alive && setSecuritiesMap(d.securities || {}))
      .catch(() => {});
    fetch("/api/market/financials")
      .then((r) => r.json())
      .then((d) => alive && setMarketFinancials(d.financials || {}))
      .catch(() => {});
    fetch("/api/market/trade-stats")
      .then((r) => r.json())
      .then((d) => alive && setMarketTradeStats(d.stats || {}))
      .catch(() => {});
    fetch("/api/market/stocks")
      .then((r) => r.json())
      .then((d) => alive && setMarketRows(d.stocks || []))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  /* ---- session refresh when token present ---- */
  useEffect(() => {
    if (!token) {
      setUser(null);
      return;
    }
    apiFetch("/api/auth/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setUser(d.user))
      .catch(() => {});
  }, [token, apiFetch]);

  /* ---- autoscroll ---- */
  useEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  /* ---- enriched market rows (memo) ---- */
  const enrichedRows = useMemo(() => {
    if (!marketRows.length) return [];
    try {
      return marketRows.map((r) => {
        const e = enrichMarketStock(r);
        const ts = marketTradeStats[e.isin] || marketTradeStats[r.isin];
        if (ts && ts.total_value) {
          e.stockVolume = ts.total_value;
          e.vwap = ts.vwap;
        }
        return e;
      });
    } catch {
      return marketRows;
    }
  }, [marketRows, marketTradeStats]);

  const examplePrompts = useMemo(() => {
    const a = companies[0]?.ticker;
    const b = companies[1]?.ticker;
    return [
      a ? `${lx("exAnalyze")} ${a}` : lx("exAnalyzeF"),
      a && b ? `${lx("exCompare")} ${a} ${lx("and")} ${b}` : lx("exCompareF"),
      lx("exMarket"),
      lx("exScreener"),
    ];
  }, [companies, lx]);

  /* ---- async dispatchers ---- */
  const doAnalyze = useCallback(
    async (company) => {
      const res = await apiFetch("/api/analyze", {
        method: "POST",
        body: JSON.stringify({
          company,
          language,
          include_raw: false,
          force_refresh: false,
          include_all_excel_reports: false,
          report_analysis_type: "latest",
          report_form: "NAS",
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || data.error || "analyze failed");
      return data;
    },
    [apiFetch, language]
  );

  const doCompare = useCallback(
    async (tickers) => {
      const res = await apiFetch("/api/compare", {
        method: "POST",
        body: JSON.stringify({
          companies: tickers,
          language,
          include_market_context: false,
          include_ai_summary: true,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "compare failed");
      return data.comparison || data;
    },
    [apiFetch, language]
  );

  const doDividends = useCallback(async (ticker) => {
    const res = await fetch(`/api/dividends/${encodeURIComponent(ticker)}`);
    const data = await res.json();
    if (!res.ok) throw new Error("dividends failed");
    return data.dividends || data.items || data || [];
  }, []);

  const doListings = useCallback(async () => {
    const res = await fetch("/api/listings/feed");
    const data = await res.json();
    if (!res.ok) throw new Error("listings failed");
    return data;
  }, []);

  const runScreener = useCallback(
    (query) => {
      const rows = enrichedRows;
      if (!rows.length) return { kind: "empty" };
      const withPE = rows.map((r) => {
        const fin = marketFinancials[String(r.ticker).toUpperCase()];
        const ni = fin ? num(fin.net_income) : NaN;
        const mc = num(r.marketCap);
        const pe = isFinite(ni) && ni > 0 && isFinite(mc) && mc > 0 ? mc / ni : NaN;
        return { ...r, pe };
      });
      let title = lx("screenerCheap");
      let mode = "pe";
      let list;
      if (/(крупнейш|largest|biggest|капитализ|yirik)/.test(query)) {
        title = lx("screenerLargest");
        mode = "mcap";
        list = withPE.filter((r) => isFinite(num(r.marketCap))).sort((a, b) => num(b.marketCap) - num(a.marketCap));
      } else if (/(растут|gainers|лидеры рост|o'sish)/.test(query)) {
        title = lx("screenerGainers");
        mode = "chg";
        list = withPE.filter((r) => isFinite(num(r.changePercent))).sort((a, b) => num(b.changePercent) - num(a.changePercent));
      } else if (/(падают|losers|падени|tushish)/.test(query)) {
        title = lx("screenerLosers");
        mode = "chg";
        list = withPE.filter((r) => isFinite(num(r.changePercent))).sort((a, b) => num(a.changePercent) - num(b.changePercent));
      } else {
        // cheapest by P/E (optionally a "< N" threshold)
        const m = query.match(/<\s*([\d.]+)/);
        const thr = m ? parseFloat(m[1]) : null;
        list = withPE
          .filter((r) => isFinite(r.pe) && (thr == null || r.pe < thr))
          .sort((a, b) => a.pe - b.pe);
      }
      return { kind: "screener", title, mode, rows: (list || []).slice(0, 10) };
    },
    [enrichedRows, marketFinancials, lx]
  );

  const marketSnapshot = useCallback(() => {
    const rows = enrichedRows;
    if (!rows.length) return { kind: "empty" };
    const changed = rows.filter((r) => isFinite(num(r.changePercent)));
    const up = changed.filter((r) => num(r.changePercent) > 0).length;
    const down = changed.filter((r) => num(r.changePercent) < 0).length;
    const flat = changed.length - up - down;
    const turnover = rows.reduce((s, r) => s + (num(r.stockVolume) || 0), 0);
    const gainers = [...changed].sort((a, b) => num(b.changePercent) - num(a.changePercent)).slice(0, 5);
    const losers = [...changed].sort((a, b) => num(a.changePercent) - num(b.changePercent)).slice(0, 5);
    return { kind: "market", count: rows.length, up, down, flat, turnover, gainers, losers };
  }, [enrichedRows]);

  /* ---- the send pipeline ---- */
  const submit = useCallback(
    async (raw) => {
      const text = String(raw || "").trim();
      if (!text || sending) return;
      const userMsg = { id: nextId(), role: "user", text };
      const plan = detectIntent(text, companies);
      const asyncIntents = ["analyze", "compare", "dividends", "listings"];
      const isAsync = asyncIntents.includes(plan.intent);
      const asstId = nextId();
      const pending = {
        id: asstId,
        role: "assistant",
        intent: plan.intent,
        status: isAsync ? "pending" : "done",
        payload: null,
      };

      // synchronous intents render immediately
      if (!isAsync) {
        let payload = null;
        if (plan.intent === "market") payload = marketSnapshot();
        else if (plan.intent === "screener") payload = runScreener(plan.query);
        else if (plan.intent === "company") payload = { kind: "company", ticker: plan.company.ticker };
        else if (plan.intent === "glossary") payload = { kind: "glossary", term: plan.term };
        else payload = { kind: "help" };
        pending.payload = payload;
        setMessages((m) => [...m, userMsg, pending]);
        return;
      }

      setMessages((m) => [...m, userMsg, pending]);
      setSending(true);
      try {
        let payload = null;
        if (plan.intent === "analyze") {
          const data = await doAnalyze(plan.company.ticker || plan.company.company_name);
          payload = { kind: "analyze", result: data };
        } else if (plan.intent === "compare") {
          const cmp = await doCompare(plan.companies.map((c) => c.ticker));
          payload = { kind: "compare", comparison: cmp };
        } else if (plan.intent === "dividends") {
          const items = await doDividends(plan.company.ticker);
          payload = { kind: "dividends", ticker: plan.company.ticker, items };
        } else if (plan.intent === "listings") {
          const feed = await doListings();
          payload = { kind: "listings", feed };
        }
        setMessages((m) =>
          m.map((x) => (x.id === asstId ? { ...x, status: "done", payload } : x))
        );
      } catch (err) {
        setMessages((m) =>
          m.map((x) =>
            x.id === asstId
              ? { ...x, status: "error", error: err.message || lx("errorGeneric") }
              : x
          )
        );
      } finally {
        setSending(false);
      }
    },
    [sending, companies, marketSnapshot, runScreener, doAnalyze, doCompare, doDividends, doListings, lx]
  );

  const onComposerKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit(input);
      setInput("");
      if (textareaRef.current) textareaRef.current.style.height = "auto";
    }
  };
  const onSendClick = () => {
    submit(input);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };
  const onTextareaInput = (e) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };
  const quickSubmit = (text) => {
    setRailOpen(false);
    submit(text);
  };

  /* ---- auth ---- */
  const submitAuth = async (e) => {
    e.preventDefault();
    setAuthBusy(true);
    setAuthMsg("");
    try {
      const path = authTab === "login" ? "/api/auth/login" : "/api/auth/register";
      const body =
        authTab === "login"
          ? { email: authForm.email, password: authForm.password }
          : { full_name: authForm.full_name, email: authForm.email, password: authForm.password };
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "auth failed");
      if (data.token) setToken(data.token);
      if (data.user) setUser(data.user);
      setAuthOpen(false);
      addToast(lx("signedInAs") + " " + (data.user?.email || ""), "success");
    } catch (err) {
      setAuthMsg(err.message || lx("errorGeneric"));
    } finally {
      setAuthBusy(false);
    }
  };
  const logout = async () => {
    try {
      await apiFetch("/api/auth/logout", { method: "POST" });
    } catch {}
    setToken("");
    setUser(null);
    setAuthOpen(false);
  };

  const recent = useMemo(
    () => messages.filter((m) => m.role === "user").slice(-8).reverse(),
    [messages]
  );

  /* ══════════════════════════════════════════════════════════════════════ */
  return (
    <div className={`cx-app${railOpen ? " is-rail-open" : ""}`}>
      <header className="cx-header">
        <button
          className="cx-icon-btn cx-rail-toggle"
          onClick={() => setRailOpen((v) => !v)}
          aria-label="Menu"
          aria-expanded={railOpen}
        >
          {I.menu}
        </button>
        <div className="cx-brand">
          <span className="cx-brand-mark" aria-hidden="true">AI</span>
          <span>
            <span className="cx-brand-name">{lx("title")}</span>
            <span className="cx-brand-sub"> · {lx("sub")}</span>
          </span>
        </div>
        <div className="cx-header-spacer" />
        <div className="cx-header-controls">
          <select
            className="cx-select"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            aria-label="Language"
          >
            <option value="ru">RU</option>
            <option value="en">EN</option>
            <option value="uz">UZ</option>
          </select>
          <button
            className="cx-icon-btn"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? "Light theme" : "Dark theme"}
          >
            {theme === "dark" ? I.sun : I.moon}
          </button>
          <button className="cx-account-btn" onClick={() => setAuthOpen(true)}>
            <span className="cx-account-avatar" aria-hidden="true">
              {user?.avatar_data_url ? (
                <img src={user.avatar_data_url} alt="" />
              ) : user?.full_name ? (
                user.full_name.slice(0, 1).toUpperCase()
              ) : (
                I.user
              )}
            </span>
            <span className="cx-account-label">
              {user ? user.full_name || user.email : lx("signIn")}
            </span>
          </button>
        </div>
      </header>

      <div className="cx-body">
        <button
          className="cx-scrim"
          aria-hidden="true"
          tabIndex={-1}
          onClick={() => setRailOpen(false)}
        />
        <nav className="cx-rail" aria-label={lx("quick")}>
          <button className="cx-newchat" onClick={() => { setMessages([]); setRailOpen(false); }}>
            {I.plus} {lx("newChat")}
          </button>
          <div className="cx-rail-label">{lx("quick")}</div>
          {examplePrompts.map((p, i) => (
            <button key={i} className="cx-thread-item" onClick={() => quickSubmit(p)}>
              {p}
            </button>
          ))}
          {recent.length > 0 && (
            <>
              <div className="cx-rail-label">{lx("recent")}</div>
              {recent.map((m) => (
                <button
                  key={m.id}
                  className="cx-thread-item"
                  onClick={() => quickSubmit(m.text)}
                  title={m.text}
                >
                  {m.text}
                </button>
              ))}
            </>
          )}
        </nav>

        <main className="cx-main">
          <div className="cx-thread" ref={threadRef} role="log" aria-live="polite" aria-relevant="additions">
            {messages.length === 0 ? (
              <Welcome lx={lx} examples={examplePrompts} onPick={quickSubmit} />
            ) : (
              <div className="cx-thread-inner">
                {messages.map((m) =>
                  m.role === "user" ? (
                    <div className="cx-msg cx-msg--user" key={m.id}>
                      <div className="cx-bubble">{m.text}</div>
                    </div>
                  ) : (
                    <div className="cx-msg cx-msg--assistant" key={m.id}>
                      <Answer
                        msg={m}
                        language={language}
                        lx={lx}
                        securitiesMap={securitiesMap}
                        marketFinancials={marketFinancials}
                        marketRows={enrichedRows}
                        onAnalyze={(tk) => quickSubmit(`${lx("exAnalyze")} ${tk}`)}
                        onFollowup={quickSubmit}
                      />
                    </div>
                  )
                )}
              </div>
            )}
          </div>

          <div className="cx-composer">
            <div className="cx-composer-inner">
              {messages.length === 0 && (
                <div className="cx-chips">
                  {examplePrompts.map((p, i) => (
                    <button key={i} className="cx-chip" onClick={() => quickSubmit(p)}>
                      {p}
                    </button>
                  ))}
                </div>
              )}
              <form
                className="cx-composer-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  onSendClick();
                }}
              >
                <label htmlFor="cx-input" className="cx-visually-hidden" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
                  {lx("placeholder")}
                </label>
                <textarea
                  id="cx-input"
                  ref={textareaRef}
                  className="cx-textarea"
                  rows={1}
                  placeholder={lx("placeholder")}
                  value={input}
                  onChange={onTextareaInput}
                  onKeyDown={onComposerKey}
                  disabled={sending}
                />
                <button
                  type="submit"
                  className="cx-send"
                  disabled={sending || !input.trim()}
                  aria-label={lx("send")}
                >
                  {I.send}
                </button>
              </form>
              <p className="cx-composer-hint">{lx("hint")}</p>
            </div>
          </div>
        </main>
      </div>

      {authOpen && (
        <AuthDialog
          lx={lx}
          user={user}
          tab={authTab}
          setTab={setAuthTab}
          form={authForm}
          setForm={setAuthForm}
          msg={authMsg}
          busy={authBusy}
          onSubmit={submitAuth}
          onClose={() => setAuthOpen(false)}
          onLogout={logout}
          onGoogle={() => (window.location.href = "/api/auth/oauth/google/start")}
        />
      )}

      <ToastStack toasts={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} language={language} />
    </div>
  );
}

/* ── Welcome ──────────────────────────────────────────────────────────────── */
function Welcome({ lx, examples, onPick }) {
  return (
    <div className="cx-welcome">
      <div className="cx-welcome-mark" aria-hidden="true">AI</div>
      <h1>{lx("welcomeTitle")}</h1>
      <p>{lx("welcomeSub")}</p>
      <div className="cx-example-grid">
        {examples.map((p, i) => (
          <button key={i} className="cx-example" onClick={() => onPick(p)}>
            <span className="cx-example-title">{p}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Answer dispatcher ────────────────────────────────────────────────────── */
function Answer({ msg, language, lx, securitiesMap, marketFinancials, marketRows, onAnalyze, onFollowup }) {
  const label = lx("labels")[msg.intent] || lx("labels").help;
  return (
    <div className="cx-answer">
      <div className="cx-answer-head">
        <span className="cx-answer-avatar" aria-hidden="true">AI</span>
        <span className="cx-answer-role">{lx("title")}</span>
        <span className="cx-answer-intent">{label}</span>
      </div>
      <div className="cx-answer-body">
        {msg.status === "pending" ? (
          <div className="cx-thinking">
            <span className="cx-dots"><span /><span /><span /></span>
            {lx("thinking")}
          </div>
        ) : msg.status === "error" ? (
          <div className="cx-error">{msg.error || lx("errorGeneric")}</div>
        ) : (
          <AnswerBoundary fallback={lx("errorGeneric")}>
            <AnswerBody
              payload={msg.payload}
              language={language}
              lx={lx}
              securitiesMap={securitiesMap}
              marketFinancials={marketFinancials}
              marketRows={marketRows}
              onAnalyze={onAnalyze}
              onFollowup={onFollowup}
            />
          </AnswerBoundary>
        )}
      </div>
    </div>
  );
}

function AnswerBody({ payload, language, lx, securitiesMap, marketFinancials, marketRows, onAnalyze, onFollowup }) {
  if (!payload) return <div className="cx-error">{lx("errorGeneric")}</div>;

  switch (payload.kind) {
    case "analyze": {
      const r = payload.result || {};
      const score = r.summary?.score ?? r.metrics?.total_score?.score ?? 0;
      return (
        <>
          <AnswerBoundary fallback="—"><HeroVerdictBlock analysisResult={r} language={language} /></AnswerBoundary>
          <AnswerBoundary fallback="—"><FinancialVisuals result={r} language={language} score={score} /></AnswerBoundary>
          <AnswerBoundary fallback="—"><BankMetricsPanel analysisResult={r} language={language} /></AnswerBoundary>
          <AnswerBoundary fallback="—"><ReportArticleView analysisResult={r} language={language} /></AnswerBoundary>
          <DisclaimerNote language={language} variant="report" />
        </>
      );
    }
    case "compare": {
      const c = payload.comparison || {};
      const primary = (c.charts || []).find((x) => x.id === "normalized_radar") || (c.charts || [])[0];
      const tables = c.tables && typeof c.tables === "object" ? Object.entries(c.tables) : [];
      return (
        <>
          {c.leaders && <CompareLeaderCards leaders={c.leaders} language={language} />}
          {c.normalized_ranking && (
            <CompareRanking title="" rows={c.normalized_ranking} scoreKey="composite_score" language={language} />
          )}
          {primary && (
            <div className="cx-card cx-scroll-x">
              <CompareChartCard chart={primary} language={language} />
            </div>
          )}
          {tables.slice(0, 4).map(([key, table]) => (
            <div className="cx-card cx-scroll-x" key={key}>
              <CompareTable table={table} title={key} language={language} />
            </div>
          ))}
          {c.comparative_ai_summary && (
            <CompareSummaryText summary={c.comparative_ai_summary} language={language} />
          )}
          <DisclaimerNote language={language} variant="report" />
        </>
      );
    }
    case "company": {
      return (
        <div className="cx-card cx-card--flush cx-scroll-x">
          <CompanyPage
            ticker={payload.ticker}
            securitiesMap={securitiesMap}
            language={language}
            marketRows={marketRows}
            financials={marketFinancials}
            onBack={() => {}}
            onAnalyze={onAnalyze}
          />
        </div>
      );
    }
    case "dividends": {
      const sec = securitiesMap[String(payload.ticker).toUpperCase()] || {};
      const row = marketRows.find((r) => String(r.ticker).toUpperCase() === String(payload.ticker).toUpperCase());
      return (
        <div className="cx-card">
          <h3 style={{ margin: "0 0 12px" }}>{lx("dividendsFor")} · {payload.ticker}</h3>
          <CompanyDividendsTab
            items={payload.items || []}
            loading={false}
            lang={language}
            isPreferred={!!sec.is_preferred}
            lastPrice={row?.lastPrice ?? sec.last_price}
          />
        </div>
      );
    }
    case "market":
      return <MarketSnapshot data={payload} lx={lx} language={language} onAnalyze={onAnalyze} />;
    case "screener":
      return <ScreenerList data={payload} lx={lx} language={language} onAnalyze={onAnalyze} />;
    case "listings":
      return <ListingsAnswer feed={payload.feed} lx={lx} onAnalyze={onAnalyze} />;
    case "glossary":
      return <GlossaryAnswer term={payload.term} lx={lx} onFollowup={onFollowup} />;
    case "empty":
      return <div className="cx-error">{lx("noMarket")}</div>;
    case "help":
    default:
      return <HelpAnswer lx={lx} onFollowup={onFollowup} />;
  }
}

/* ── Market snapshot ──────────────────────────────────────────────────────── */
function MarketSnapshot({ data, lx, language, onAnalyze }) {
  const Row = ({ r }) => (
    <button className="cx-list-row" onClick={() => onAnalyze(r.ticker)}>
      <span className="cx-list-rank" />
      <span className="cx-list-name">
        <strong>{r.ticker}</strong>
        <span>{r.name}</span>
      </span>
      <span className="cx-list-sub tabnum">{isFinite(num(r.lastPrice)) ? num(r.lastPrice).toLocaleString() : "—"}</span>
      <span
        className="cx-list-metric tabnum"
        style={{ color: num(r.changePercent) > 0 ? "var(--success)" : num(r.changePercent) < 0 ? "var(--danger)" : "var(--muted)" }}
      >
        {pctStr(r.changePercent)}
      </span>
    </button>
  );
  return (
    <>
      <div className="cx-card">
        <h3 style={{ margin: "0 0 14px" }}>{lx("marketTitle")}</h3>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(120px,1fr))", gap: 10 }}>
          <Stat label={lx("instruments")} value={data.count} />
          <Stat label={lx("advancers")} value={data.up} tone="good" />
          <Stat label={lx("decliners")} value={data.down} tone="bad" />
          <Stat label={lx("volume")} value={fmtCompact(data.turnover, language)} />
        </div>
      </div>
      <div className="cx-card">
        <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>{lx("topGainers")}</h3>
        <div className="cx-list">{data.gainers.map((r) => <Row r={r} key={r.ticker} />)}</div>
      </div>
      <div className="cx-card">
        <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>{lx("topLosers")}</h3>
        <div className="cx-list">{data.losers.map((r) => <Row r={r} key={r.ticker} />)}</div>
      </div>
    </>
  );
}
function Stat({ label, value, tone }) {
  const color = tone === "good" ? "var(--success)" : tone === "bad" ? "var(--danger)" : "var(--text)";
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "12px 14px", background: "var(--surface-2)" }}>
      <div style={{ fontSize: "0.72rem", textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--muted)", fontWeight: 700 }}>{label}</div>
      <div className="tabnum" style={{ fontSize: "1.35rem", fontWeight: 700, marginTop: 4, color }}>{value}</div>
    </div>
  );
}

/* ── Screener list ────────────────────────────────────────────────────────── */
function ScreenerList({ data, lx, language, onAnalyze }) {
  if (data.kind === "empty" || !data.rows || !data.rows.length)
    return <div className="cx-error">{lx("screenerEmpty")}</div>;
  return (
    <div className="cx-card">
      <h3 style={{ margin: "0 0 10px" }}>{data.title}</h3>
      <div className="cx-list">
        {data.rows.map((r, i) => (
          <button className="cx-list-row" key={r.ticker} onClick={() => onAnalyze(r.ticker)}>
            <span className="cx-list-rank">{i + 1}</span>
            <span className="cx-list-name">
              <strong>{r.ticker}</strong>
              <span>{r.name}</span>
            </span>
            <span className="cx-list-sub tabnum">
              {data.mode === "mcap"
                ? fmtCompact(r.marketCap, language)
                : data.mode === "chg"
                ? pctStr(r.changePercent)
                : ""}
            </span>
            <span className="cx-list-metric tabnum">
              {data.mode === "pe" ? (isFinite(r.pe) ? `P/E ${r.pe.toFixed(1)}` : "—") : ""}
              {data.mode === "chg" ? (isFinite(num(r.lastPrice)) ? num(r.lastPrice).toLocaleString() : "") : ""}
            </span>
          </button>
        ))}
      </div>
      <p className="cx-disclaimer">{lx("hint")}</p>
    </div>
  );
}

/* ── Listings ─────────────────────────────────────────────────────────────── */
function ListingsAnswer({ feed, lx, onAnalyze }) {
  const listed = feed?.listed || [];
  const inactive = feed?.inactive || [];
  if (!listed.length && !inactive.length) return <div className="cx-error">{lx("listingEmpty")}</div>;
  const Group = ({ title, items, dateKey }) =>
    items.length ? (
      <div className="cx-card">
        <h3 style={{ margin: "0 0 8px", fontSize: "0.95rem" }}>{title}</h3>
        <div className="cx-list">
          {items.slice(0, 10).map((it) => (
            <button className="cx-list-row" key={it.ticker + it[dateKey]} onClick={() => onAnalyze(it.ticker)}>
              <span className="cx-list-rank" />
              <span className="cx-list-name">
                <strong>{it.ticker}</strong>
                <span>{it.name}</span>
              </span>
              <span className="cx-list-sub">{it[dateKey] || ""}</span>
              <span />
            </button>
          ))}
        </div>
      </div>
    ) : null;
  return (
    <>
      <Group title={lx("listingNew")} items={listed} dateKey="listing_date" />
      <Group title={lx("listingInactive")} items={inactive} dateKey="last_trade_date" />
    </>
  );
}

/* ── Glossary ─────────────────────────────────────────────────────────────── */
function GlossaryAnswer({ term, lx, onFollowup }) {
  if (term) {
    return (
      <div className="cx-card cx-term">
        <span className="cx-term-tag">{lx("labels").glossary}</span>
        <h3>{term.term}</h3>
        <p>{term.def}</p>
      </div>
    );
  }
  const sample = (GLOSSARY || []).flatMap((g) => g.terms || []).slice(0, 8);
  return (
    <div className="cx-card">
      <p style={{ margin: "0 0 12px", color: "var(--muted)" }}>{lx("glossaryNotFound")}</p>
      <div className="cx-followups">
        {sample.map((it) => (
          <button key={it.term} className="cx-chip" onClick={() => onFollowup(`Что такое ${it.term}`)}>
            {it.term}
          </button>
        ))}
      </div>
    </div>
  );
}

/* ── Help ─────────────────────────────────────────────────────────────────── */
function HelpAnswer({ lx, onFollowup }) {
  return (
    <div className="cx-card">
      <p style={{ margin: "0 0 12px", lineHeight: 1.6 }}>{lx("helpText")}</p>
      <div className="cx-followups">
        <button className="cx-chip" onClick={() => onFollowup(lx("exMarket"))}>{lx("exMarket")}</button>
        <button className="cx-chip" onClick={() => onFollowup(lx("exScreener"))}>{lx("exScreener")}</button>
      </div>
    </div>
  );
}

/* ── Auth dialog ──────────────────────────────────────────────────────────── */
function AuthDialog({ lx, user, tab, setTab, form, setForm, msg, busy, onSubmit, onClose, onLogout, onGoogle }) {
  const ref = useRef(null);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const el = ref.current?.querySelector("input,button");
    if (el) el.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="cx-dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cx-dialog" role="dialog" aria-modal="true" aria-label={lx("account")} ref={ref} style={{ position: "relative" }}>
        <button className="cx-icon-btn cx-dialog-close" onClick={onClose} aria-label="Close">✕</button>
        {user ? (
          <div className="cx-dialog-signed">
            <span className="cx-account-avatar" style={{ width: 56, height: 56, fontSize: 22 }} aria-hidden="true">
              {user.full_name ? user.full_name.slice(0, 1).toUpperCase() : "U"}
            </span>
            <h2>{user.full_name || user.email}</h2>
            <p className="cx-dialog-sub">{user.email}</p>
            <button className="cx-btn cx-btn--ghost" onClick={onLogout}>{lx("signOut")}</button>
          </div>
        ) : (
          <>
            <h2>{lx("account")}</h2>
            <p className="cx-dialog-sub">{lx("welcomeSub")}</p>
            <div className="cx-tabs" role="tablist">
              <button role="tab" aria-selected={tab === "login"} className={`cx-tab${tab === "login" ? " is-active" : ""}`} onClick={() => setTab("login")}>{lx("login")}</button>
              <button role="tab" aria-selected={tab === "register"} className={`cx-tab${tab === "register" ? " is-active" : ""}`} onClick={() => setTab("register")}>{lx("register")}</button>
            </div>
            <form onSubmit={onSubmit}>
              {tab === "register" && (
                <div className="cx-field">
                  <label htmlFor="cx-name">{lx("namePh")}</label>
                  <input id="cx-name" className="cx-input" value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} autoComplete="name" />
                </div>
              )}
              <div className="cx-field">
                <label htmlFor="cx-email">{lx("emailPh")}</label>
                <input id="cx-email" className="cx-input" type="email" value={form.email} onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} autoComplete="email" required />
              </div>
              <div className="cx-field">
                <label htmlFor="cx-pass">{lx("passwordPh")}</label>
                <input id="cx-pass" className="cx-input" type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} autoComplete={tab === "login" ? "current-password" : "new-password"} required />
              </div>
              <button className="cx-btn" type="submit" disabled={busy}>
                {tab === "login" ? lx("login") : lx("register")}
              </button>
            </form>
            <div className="cx-dialog-or">{lx("or")}</div>
            <button className="cx-btn cx-btn--ghost" onClick={onGoogle}>{lx("google")}</button>
            <p className="cx-dialog-msg" role="alert">{msg}</p>
          </>
        )}
      </div>
    </div>
  );
}
