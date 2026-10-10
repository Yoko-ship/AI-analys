

function newsArticlePath(item) {
  return item && item.id ? `/news/${encodeURIComponent(item.id)}` : (item && item.url) || "#";
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
    tabs: { all: "Все", economy: "Экономика", corporate: "Корпоративные", reporting: "Финотчётность", markets: "Рынки", companies: "Компании", politics: "Политика", technology: "Технологии", other: "Прочее", calendar: "Календарь" },
    moreTabs: "Ещё",
    tabHint: {
      all: "Все новости экономики, рынка и эмитентов в одной ленте",
      economy: "Макроэкономика, торговля, инвестиции и отраслевая конъюнктура",
      corporate: "Официальные раскрытия эмитентов с openinfo.uz",
      reporting: "Финансовые результаты, отчётность, рейтинги и выплаты по ценным бумагам",
      markets: "Биржа, акции и облигации, валюта и цены на сырьё",
      companies: "Дела отдельных компаний: сделки, проекты, руководство",
      politics: "Решения государства и регуляторов, законы и программы",
      technology: "IT, телеком, финтех, электронная коммерция и цифровые сервисы",
      other: "Всё, что не вошло в другие разделы",
      calendar: "Собрания, дивиденды, отчётность и существенные факты эмитентов на одной шкале — только даты, которые раскрыли сами компании",
    },
    desk: { updated: "Обновлено", stories: "материалов", main: "Главная тема", marketNow: "Рынок сейчас", days30: "30 дней",
      positive: "Позитивных", neutral: "Нейтральных", negative: "Негативных", latest: "Последние новости",
      important: "важное и свежее", time: "Время", category: "Категория", headline: "Заголовок", instrument: "Инструмент",
      signal: "Сигнал", focus: "В фокусе", events: "событий", calendar: "Календарь", calendarCopy: "Собрания, дивиденды, отчётность и факты эмитентов", openCalendar: "Открыть календарь" },
    emptyTab: "В этом разделе пока пусто — посмотрите «Все».",
    instruments: { all: "Все бумаги", stock: "Акции", bond: "Облигации" },
    instrumentHint: {
      all: "События и отчётность конкретных эмитентов",
      stock: "Дивиденды, собрания, сделки — то, что касается акционера",
      bond: "Купоны, выпуски и погашения — то, что касается держателя облигаций",
    },
    emptyInstrument: "За месяц таких сообщений не было.",
    cat: { report: "Отчётность", listing: "Листинг", delisting: "Делистинг" },
    forms: { NAS: "НСБУ", NSBU: "НСБУ", IFRS: "МСФО", MSFO: "МСФО", Audit: "Аудиторское заключение", Audition: "Аудиторское заключение" },
  },
  en: {
    eyebrow: "Market · Analytical feed", title: "Market News",
    subtitle: "The economy, market and issuer news that matters in Uzbekistan — gathered from Uzbek sources and AI-sorted by likely price impact.",
    latest: "Latest", empty: "No recent news yet. Check back soon.",
    loadingText: "Loading the feed…", error: "Could not load the news feed.",
    tabs: { all: "All", economy: "Economy", corporate: "Corporate", reporting: "Financial reports", markets: "Markets", companies: "Companies", politics: "Politics", technology: "Technology", other: "Other", calendar: "Calendar" },
    moreTabs: "More",
    tabHint: {
      all: "Economy, market and issuer news in one feed",
      economy: "Macro, trade, investment and sector conditions",
      corporate: "Issuers' official disclosures from openinfo.uz",
      reporting: "Financial results, reporting, ratings and security payouts",
      markets: "The exchange, shares and bonds, currency and commodity prices",
      companies: "Individual companies: deals, projects, management",
      politics: "Government and regulatory decisions, laws and programmes",
      technology: "IT, telecom, fintech, e-commerce and digital services",
      other: "Everything the other sections do not cover",
      calendar: "Issuers' meetings, dividends, reports and material facts on one timeline — only dates the companies disclosed themselves",
    },
    desk: { updated: "Updated", stories: "stories", main: "Lead story", marketNow: "Market now", days30: "30 days",
      positive: "Positive", neutral: "Neutral", negative: "Negative", latest: "Latest news",
      important: "important and recent", time: "Time", category: "Category", headline: "Headline", instrument: "Instrument",
      signal: "Signal", focus: "In focus", events: "stories", calendar: "Calendar", calendarCopy: "Meetings, dividends, reports and issuer facts", openCalendar: "Open calendar" },
    emptyTab: "Nothing here yet — try “All”.",
    instruments: { all: "All securities", stock: "Shares", bond: "Bonds" },
    instrumentHint: {
      all: "Events and reporting of individual issuers",
      stock: "Dividends, meetings, transactions — what concerns a shareholder",
      bond: "Coupons, issues and redemptions — what concerns a bondholder",
    },
    emptyInstrument: "No such filing in the past month.",
    cat: { report: "Filing", listing: "Listing", delisting: "Delisting" },
    forms: { NAS: "NAS", NSBU: "NAS", IFRS: "IFRS", MSFO: "IFRS", Audit: "Auditor's report", Audition: "Auditor's report" },
  },
  uz: {
    eyebrow: "Bozor · Tahliliy lenta", title: "Bozor yangiliklari",
    subtitle: "O'zbekiston iqtisodiyoti, bozori va emitentlari bo'yicha muhim yangiliklar — o'zbek manbalaridan yig'iladi va sun'iy intellekt tomonidan ta'sir bo'yicha saralanadi.",
    latest: "So'nggi", empty: "Hozircha yangi yangiliklar yo'q. Keyinroq qayting.",
    loadingText: "Lenta yuklanmoqda…", error: "Yangiliklarni yuklab bo'lmadi.",
    tabs: { all: "Barchasi", economy: "Iqtisodiyot", corporate: "Korporativ", reporting: "Moliyaviy hisobot", markets: "Bozorlar", companies: "Kompaniyalar", politics: "Siyosat", technology: "Texnologiyalar", other: "Boshqa", calendar: "Taqvim" },
    moreTabs: "Yana",
    tabHint: {
      all: "Iqtisodiyot, bozor va emitentlar yangiliklari bitta lentada",
      economy: "Makroiqtisodiyot, savdo, investitsiyalar va tarmoq holati",
      corporate: "Emitentlarning openinfo.uz'dagi rasmiy oshkor qilishlari",
      reporting: "Moliyaviy natijalar, hisobotlar, reytinglar va qimmatli qog'ozlar bo'yicha to'lovlar",
      markets: "Birja, aksiya va obligatsiyalar, valyuta va xomashyo narxlari",
      companies: "Alohida kompaniyalar: bitimlar, loyihalar, rahbariyat",
      politics: "Davlat va regulyator qarorlari, qonunlar va dasturlar",
      technology: "IT, telekom, fintex, elektron tijorat va raqamli xizmatlar",
      other: "Boshqa bo'limlarga kirmagan hammasi",
      calendar: "Emitentlarning yig'ilishlari, dividendlari, hisobotlari va muhim faktlari bitta shkalada — faqat kompaniyalarning o'zi oshkor qilgan sanalar",
    },
    desk: { updated: "Yangilandi", stories: "material", main: "Asosiy mavzu", marketNow: "Bozor hozir", days30: "30 kun",
      positive: "Ijobiy", neutral: "Neytral", negative: "Salbiy", latest: "So'nggi yangiliklar",
      important: "muhim va yangi", time: "Vaqt", category: "Tur", headline: "Sarlavha", instrument: "Instrument",
      signal: "Signal", focus: "Diqqat markazida", events: "voqea", calendar: "Taqvim", calendarCopy: "Yig'ilishlar, dividendlar, hisobotlar va emitent faktlari", openCalendar: "Taqvimni ochish" },
    emptyTab: "Bu bo'limda hozircha bo'sh — «Barchasi»ni ko'ring.",
    instruments: { all: "Barcha qog'ozlar", stock: "Aksiyalar", bond: "Obligatsiyalar" },
    instrumentHint: {
      all: "Aniq emitentlarning voqealari va hisobotlari",
      stock: "Dividendlar, yig'ilishlar, bitimlar — aksiyador uchun",
      bond: "Kuponlar, emissiyalar va to'lovlar — obligatsiya egasi uchun",
    },
    emptyInstrument: "Bir oy ichida bunday xabar bo'lmagan.",
    cat: { report: "Hisobot", listing: "Listing", delisting: "Delisting" },
    forms: { NAS: "NAS", NSBU: "NAS", IFRS: "IFRS", MSFO: "IFRS", Audit: "Auditor xulosasi", Audition: "Auditor xulosasi" },
  },
};

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

export { EDNEWS_TX, NEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime };
