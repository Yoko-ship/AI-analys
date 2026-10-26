import { HomeMarketDashboard } from "./HomeMarketDashboard.jsx";
import { LandingUpdates } from "./LandingUpdates.jsx";
import { prepareMarketRows } from "../../lib/marketData.js";
import React from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { EDNEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime } from "../news/index.js";
import { buildMarketStats, marketDisplayPrice } from "../../shared/marketModel.jsx";
import { marketRowDay } from "../../lib/valuation.js";
import { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { MarketMovers } from "../market/index.js";
import { compact as fmtCompact, num as fmtNumber, pct as fmtPct, price as fmtPrice } from "../../lib/format.js";

// ─────────────────────────────────────────────────────────────────────────────
// The market dashboard shares prices, performance periods and source data
// with the full market board. No illustrative prices enter the public view.

const LANDING_TX = {
  ru: {
    h1: ["Открытый", "рынок"],
    lede: "Фондовая биржа «Тошкент» — как на ладони: котировки, отчётность эмитентов и новости, влияющие на цену. Официальные данные Узбекистана, собранные в одну платформу.",
    ctaMarket: "Смотреть рынок",
    s2Title: ["Табло", "рынка"],
    s2Sub: "Все бумаги биржи в одной таблице: цена, изменение за день и график за месяц. Сортировка по любой колонке, тепловая карта секторов и фильтры — в один клик.",
    boardTitle: "Итоги сессии",
    thSecurity: "Бумага", thPrice: "Цена, сум", thDay: "За день", th30d: "30 дней",
    footVolume: "Объём торгов", footUp: "Растёт", footDown: "Падает", footFlat: "Без изменения",
    s3Title: ["Каждая компания —", "с историей"],
    s3Sub: "Страница эмитента собирает всё, что о нём раскрыто официально, — и показывает это так, чтобы выводы напрашивались сами.",
    points: [
      ["Финансы из первоисточника", "Выручка, прибыль, активы и капитал по годам — разобраны из годовых и квартальных отчётов на openinfo.uz."],
      ["Мультипликаторы честно", "P/E, P/B, P/S, ROE и дивидендная доходность рассчитываются по опубликованным данным."],
      ["Дивиденды и события", "История выплат, даты закрытия реестра и корпоративные события — на той же странице, рядом с графиком цены."],
    ],
    barsTitle: "Выручка по годам",
    cardNote: "Данные — из официальных раскрытий openinfo.uz. Нажмите, чтобы открыть страницу компании.",
    s4Title: ["Новости, которые", "двигают цену"],
    s4Sub: "Лента собирается из узбекских и мировых источников. ИИ оценивает каждую новость по возможному влиянию на котировки и привязывает её к тикерам — шум остаётся за бортом.",
    newsAll: "Вся лента новостей",
    steps: [
      ["Найдите бумагу", "На табло рынка — все акции и облигации биржи «Тошкент» с ценами и динамикой за день."],
      ["Изучите компанию", "График цены, финансовая история, мультипликаторы, дивиденды и связанные новости — на одной странице."],
      ["Сравните с рынком", "Наложите конкурентов на один график с общей базой и посмотрите, кто действительно растёт."],
    ],
    stepWord: "Шаг",
    ctaTitle: "Рынок уже открыт",
    ctaText: "Бесплатный доступ к котировкам, отчётности и аналитике — на русском, узбекском и английском.",
    ctaBtn: "Начать с табло рынка",
    sum: "сум",
  },
  uz: {
    h1: ["Ochiq", "bozor"],
    lede: "«Toshkent» fond birjasi — kaftdek ko'rinadi: kotirovkalar, emitentlar hisobotlari va narxga ta'sir qiluvchi yangiliklar. O'zbekistonning rasmiy ma'lumotlari bitta platformada.",
    ctaMarket: "Bozorni ko'rish",
    s2Title: ["Bozor", "taxtasi"],
    s2Sub: "Birjaning barcha qog'ozlari bitta jadvalda: narx, kunlik o'zgarish va oylik grafik. Istalgan ustun bo'yicha saralash, sektorlar xaritasi va filtrlar — bir bosishda.",
    boardTitle: "Sessiya yakunlari",
    thSecurity: "Qog'oz", thPrice: "Narx, so'm", thDay: "Kunlik", th30d: "30 kun",
    footVolume: "Savdo hajmi", footUp: "O'sdi", footDown: "Tushdi", footFlat: "O'zgarishsiz",
    s3Title: ["Har bir kompaniya —", "tarixi bilan"],
    s3Sub: "Emitent sahifasi u haqda rasman oshkor qilingan hamma narsani yig'adi — va xulosa o'z-o'zidan kelib chiqadigan qilib ko'rsatadi.",
    points: [
      ["Moliyaviy ma'lumotlar — birinchi manbadan", "Tushum, foyda, aktivlar va kapital yillar bo'yicha — openinfo.uz dagi yillik va choraklik hisobotlardan olingan."],
      ["Multiplikatorlar halol", "P/E, P/B, P/S, ROE va dividend daromadliligi e'lon qilingan ma'lumotlar asosida hisoblanadi."],
      ["Dividendlar va voqealar", "To'lovlar tarixi, reyestr yopilish sanalari va korporativ voqealar — o'sha sahifada, narx grafigi yonida."],
    ],
    barsTitle: "Yillar bo'yicha tushum",
    cardNote: "Ma'lumotlar — openinfo.uz rasmiy oshkorotlaridan. Kompaniya sahifasini ochish uchun bosing.",
    s4Title: ["Narxni harakatga keltiruvchi", "yangiliklar"],
    s4Sub: "Lenta o'zbek va xalqaro manbalardan yig'iladi. Sun'iy intellekt har bir yangilikni kotirovkalarga ta'siri bo'yicha baholaydi va tikerlarga bog'laydi — shovqin chetda qoladi.",
    newsAll: "Barcha yangiliklar",
    steps: [
      ["Qog'ozni toping", "Bozor taxtasida — «Toshkent» birjasining barcha aksiya va obligatsiyalari, narxlar va kunlik dinamika bilan."],
      ["Kompaniyani o'rganing", "Narx grafigi, moliyaviy tarix, multiplikatorlar, dividendlar va bog'liq yangiliklar — bitta sahifada."],
      ["Bozor bilan solishtiring", "Raqobatchilarni umumiy asosli bitta grafikka qo'ying va kim haqiqatan o'sayotganini ko'ring."],
    ],
    stepWord: "Qadam",
    ctaTitle: "Bozor allaqachon ochiq",
    ctaText: "Kotirovkalar, hisobotlar va tahlillarga bepul kirish — rus, o'zbek va ingliz tillarida.",
    ctaBtn: "Bozor taxtasidan boshlash",
    sum: "so'm",
  },
  en: {
    h1: ["The open", "market"],
    lede: "The Tashkent Stock Exchange at a glance: quotes, issuer financials and the news that moves prices. Uzbekistan's official data, gathered into one platform.",
    ctaMarket: "View the market",
    s2Title: ["The market", "board"],
    s2Sub: "Every listed security in one table: price, daily change and a one-month chart. Sort by any column, switch to the sector heatmap, filter in one click.",
    boardTitle: "Session results",
    thSecurity: "Security", thPrice: "Price, UZS", thDay: "1 day", th30d: "30 days",
    footVolume: "Turnover", footUp: "Up", footDown: "Down", footFlat: "Unchanged",
    s3Title: ["Every company —", "with its history"],
    s3Sub: "The issuer page gathers everything officially disclosed about a company — and lays it out so the conclusions suggest themselves.",
    points: [
      ["Financials from the source", "Revenue, profit, assets and equity by year — parsed from the annual and quarterly filings on openinfo.uz."],
      ["Honest multiples", "P/E, P/B, P/S, ROE and dividend yield are calculated from published data."],
      ["Dividends and events", "Payout history, record dates and corporate events — on the same page, next to the price chart."],
    ],
    barsTitle: "Revenue by year",
    cardNote: "Data comes from official openinfo.uz disclosures. Click to open the company page.",
    s4Title: ["News that", "moves prices"],
    s4Sub: "The feed is gathered from Uzbek and international sources. AI scores every story by its likely impact on quotes and links it to tickers — the noise stays out.",
    newsAll: "Full news feed",
    steps: [
      ["Find a security", "The market board lists every stock and bond on the Tashkent exchange with prices and daily moves."],
      ["Study the company", "Price chart, financial history, multiples, dividends and related news — on one page."],
      ["Compare with the market", "Overlay competitors on one rebased chart and see who is actually growing."],
    ],
    stepWord: "Step",
    ctaTitle: "The market is already open",
    ctaText: "Free access to quotes, filings and analytics — in Russian, Uzbek and English.",
    ctaBtn: "Start with the market board",
    sum: "UZS",
  },
};

function LandingSpark({ values, label }) {
  const w = 104;
  const h = 26;
  const pts = (Array.isArray(values) ? values : [])
    .map((v) => Number(v))
    .filter((v) => Number.isFinite(v));
  if (pts.length < 2) return <span className="lv-spark-none">—</span>;

  // Colored by the window it draws, not by the day's change: this is the
  // 30-day column, so first-to-last is what the line is actually saying.
  const move = pts.at(-1) - pts[0];
  const dir = move > 0 ? "u" : move < 0 ? "d" : "f0";
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const range = max - min || 1;
  // 2px of head-room top and bottom: at stroke-width 1.4 a value sitting on the
  // extreme would otherwise have half its stroke clipped by the viewBox.
  const x = (i) => (i / (pts.length - 1)) * (w - 4) + 2;
  const y = (v) => 2 + ((max - v) / range) * (h - 4);
  const d = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");

  return (
    <svg className={`lv-spark lv-spark-${dir}`} viewBox={`0 0 ${w} ${h}`} width={w} height={h} role="img" aria-label={label}>
      <path d={d} />
      <circle cx={x(pts.length - 1)} cy={y(pts.at(-1))} r="1.9" />
    </svg>
  );
}

function LandingView({ language, marketRows, tradeStats, securitiesMap, companies, onNavigate, onOpenCompany, onOpenNews, favorites, onCalendar }) {
  const lang = normalizeLanguage(language);
  const LT = LANDING_TX[lang] || LANDING_TX.ru;
  const etx = EDNEWS_TX[lang] || EDNEWS_TX.ru;
  const rootRef = React.useRef(null);

  // The exact preparation the market board applies — enriched rows restated
  // against the stored per-trade day statistics, so the landing's movers and
  // totals describe the SAME session as /market.
  const prepared = React.useMemo(() => {
    return prepareMarketRows(marketRows, tradeStats);
  }, [marketRows, tradeStats]);
  const stats = React.useMemo(() => buildMarketStats(prepared), [prepared]);

  const nameOf = (tk) => {
    const s = (securitiesMap || {})[tk];
    if (s && (s.company_name || s.name)) return s.company_name || s.name;
    const c = (companies || []).find((x) => String(x.ticker || "").toUpperCase() === tk);
    return (c && c.company_name) || tk;
  };

  // Tape and board: the latest session's traded securities, largest turnover first.
  const tape = React.useMemo(() => prepared
    .filter((r) => (!stats.boardDay || marketRowDay(r) === stats.boardDay)
      && Number.isFinite(r.changePercent) && marketDisplayPrice(r) != null)
    .sort((a, b) => (b.stockVolume || 0) - (a.stockVolume || 0))
    .slice(0, 14), [prepared, stats]);
  const boardRows = tape.slice(0, 8);

  // The change period the reader chose on /market, honoured here (goal: «дать
  // рынку выбирать периоды их изменений и показывать на главном»). Both screens
  // read and write the one key, so the landing page and the board can never
  // answer «сколько он сделал?» with two different spans.
  const [changePeriod, setChangePeriod] = React.useState(() => {
    try {
      const saved = localStorage.getItem(CHANGE_PERIOD_KEY);
      if (CHANGE_PERIODS.some((p) => p.code === saved)) return saved;
    } catch (e) { /* ignore */ }
    return "1d";
  });
  React.useEffect(() => {
    try { localStorage.setItem(CHANGE_PERIOD_KEY, changePeriod); } catch (e) { /* ignore */ }
  }, [changePeriod]);
  const [changes, setChanges] = React.useState({});
  React.useEffect(() => {
    if (changePeriod === "1d") return undefined;   // the session is on the row already
    let alive = true;
    fetch("/api/market/changes")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setChanges(d.changes || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [changePeriod]);
  const periodPct = (ticker) => {
    if (changePeriod === "1d") return undefined;
    const hit = (changes[String(ticker || "").toUpperCase()] || {})[changePeriod];
    return hit && Number.isFinite(hit.pct) ? hit.pct : null;
  };
  // What the change column and the rail show: the session's own figure, or the
  // window's. `null` is a period the stored closes cannot reach — printed as a
  // dash, never as nought.
  const shownPct = (row) => (changePeriod === "1d" ? row.changePercent : periodPct(row.ticker));
  // The /market leaders strip (рост · падение · ликвидность), over the same
  // span as the board. A window is ranked the way /market ranks it: rows
  // restated for the period, not filtered to who traded this morning.
  const movers = React.useMemo(() => {
    if (changePeriod === "1d") return stats;
    const num = (v) => (Number.isFinite(v) ? v : null);
    const rows = prepared.map((r) => {
      const t = String(r.ticker || "").toUpperCase();
      const st = ((changes[t] || {}).stats || {})[changePeriod] || null;
      const pct = periodPct(r.ticker);
      return {
        ...r,
        changePercent: num(pct),
        periodPct: num(pct),
        stockVolume: num(st?.value),
        periodVolume: num(st?.value),
        periodFrom: st?.from || (changes[t] || {})[changePeriod]?.from || null,
        periodSessions: num(st?.sessions),
      };
    });
    return buildMarketStats(rows, { windowed: true });
  }, [changePeriod, changes, prepared, stats]); // eslint-disable-line react-hooks/exhaustive-deps

  const sparkKey = boardRows.map((r) => r.ticker).join(",");
  const [spark, setSpark] = React.useState({});
  React.useEffect(() => {
    if (!sparkKey) return undefined;
    let alive = true;
    fetch(`/api/quotes/series?tickers=${encodeURIComponent(sparkKey)}&days=30`)
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setSpark(d.series || {}); })
      .catch(() => {});
    return () => { alive = false; };
  }, [sparkKey]);

  // Showcase company: UZTL when it is on the board (a liquid issuer with a
  // long filing history), otherwise the day's top gainer.
  const showTicker = React.useMemo(() => {
    if (prepared.some((r) => r.ticker === "UZTL")) return "UZTL";
    return stats.topGrowth?.ticker || (prepared[0] && prepared[0].ticker) || null;
  }, [prepared, stats]);
  const showRow = prepared.find((r) => r.ticker === showTicker) || null;

  const [fin, setFin] = React.useState(null);
  React.useEffect(() => {
    if (!showTicker) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(showTicker)}/financials`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok) return;
        const values = (d.series && d.series.net_revenue && d.series.net_revenue.values) || {};
        const years = Object.keys(values).sort().slice(-5);
        if (years.length >= 2) setFin({ years, values: years.map((y) => values[y]) });
        else setFin(null);
      })
      .catch(() => { if (alive) setFin(null); });
    return () => { alive = false; };
  }, [showTicker]);

  const [mult, setMult] = React.useState(null);
  React.useEffect(() => {
    if (!showTicker) return undefined;
    let alive = true;
    fetch("/api/market/multiples")
      .then((r) => r.json())
      .then((d) => {
        if (alive && d && d.ok) {
          setMult((d.items || []).find((it) => String(it.ticker || "").toUpperCase() === showTicker) || null);
        }
      })
      .catch(() => { if (alive) setMult(null); });
    return () => { alive = false; };
  }, [showTicker]);

  const [news, setNews] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    fetch("/api/news/feed?limit=6&days=30")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setNews((d.items || []).slice(0, 3)); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  // Sections fade in as they scroll into view. The company card, the bars and
  // the news cards mount only after their fetches land, so the observer re-runs
  // when that content appears — an element observed once keeps its .in and is
  // skipped on the next pass.
  const revealKey = `${boardRows.length}|${Boolean(showRow)}|${Boolean(fin)}|${news.length}`;
  React.useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const els = Array.from(root.querySelectorAll(".lv-reveal:not(.in)"));
    if (!els.length) return undefined;
    if (!("IntersectionObserver" in window)
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      els.forEach((el) => el.classList.add("in"));
      return undefined;
    }
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { threshold: 0.15 });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [revealKey]);

  const sesLabel = stats.boardDay
    ? `${stats.boardDay.slice(6, 8)}.${stats.boardDay.slice(4, 6)}.${stats.boardDay.slice(0, 4)}`
    : null;
  const finMax = fin ? Math.max(...fin.values.filter((v) => Number.isFinite(v)), 1) : 1;
  const chipVal = (m) => (m && Number.isFinite(m.value) ? m.value : null);
  const chips = mult ? [
    ["P/E", chipVal(mult.pe), (v) => fmtNumber(v, lang, 2)],
    ["P/B", chipVal(mult.pb), (v) => fmtNumber(v, lang, 2)],
    ["ROE", chipVal(mult.roe), (v) => `${fmtNumber(v, lang, 1)}%`],
  ].filter(([, v]) => v != null) : [];

  const tapeItems = tape.map((r) => (
    <span className="lv-titem" key={r.ticker}>
      <span className="t">{r.ticker}</span>
      <span className="p">{fmtPrice(marketDisplayPrice(r), lang)}</span>
      <span className={r.changePercent > 0.05 ? "lv-u" : r.changePercent < -0.05 ? "lv-d" : "lv-f0"}>
        {fmtPct(r.changePercent, lang, 2)}
      </span>
    </span>
  ));

  const pointIcons = [
    <svg key="a" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 3v18h18" /><path d="M7 14l4-4 4 4 5-5" /></svg>,
    <svg key="b" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></svg>,
    <svg key="c" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>,
  ];

  return (
    <div className="landing-view concept-home" ref={rootRef}>
      {/* ── Сцена ── */}
      <section className="lv-stage">

        <div className="lv-mid">
          <div className="lv-lede">
            <span className="hd-eyebrow">UZSTOCK · {lang==='en'?'Market intelligence':lang==='uz'?'Bozor tahlili':'Аналитическая платформа'}</span>
            <h1 className="lv-h1">{lang==='en'?'Uzbekistan stock market overview':lang==='uz'?'O‘zbekiston fond bozori sharhi':'Обзор фондового рынка Узбекистана'}</h1>
            <p>{LT.lede}</p>
            <div className="lv-actions">
              <button type="button" className="lv-go" onClick={() => onNavigate("market")}>{LT.ctaMarket}</button>
            </div>
          </div>
        </div>
        <span className="lv-cue" aria-hidden="true" />
      </section>

      <HomeMarketDashboard rows={prepared} stats={stats} companies={companies} securitiesMap={securitiesMap||{}} language={lang} onOpenCompany={onOpenCompany} onNavigate={onNavigate} period={changePeriod} onPeriod={setChangePeriod} changes={changes}/>

      {/* ── Бегущая строка (реальные итоги последней сессии) ── */}
      {tape.length >= 4 && (
        <div className="lv-tape-belt">
          <div className="lv-tape">
            <div className="lv-tape-set">{tapeItems}</div>
            <div className="lv-tape-set" aria-hidden="true">{tapeItems}</div>
          </div>
        </div>
      )}

      {/* ── 02 · Табло рынка ── */}
      <section className="lv-sec">
        <div className="lv-container lv-wide">
          <div className="lv-sec-head lv-reveal">
            <span className="lv-sec-num">02</span>
            <h2 className="lv-sec-title">{LT.s2Title[0]} <em>{LT.s2Title[1]}</em></h2>
          </div>
          <p className="lv-sec-sub lv-reveal">{LT.s2Sub}</p>
          <div className="market-layout lv-movers lv-reveal">
            <MarketMovers
              viewMode="table"
              periodMovers={movers}
              lang={lang}
              changePeriod={changePeriod}
              onOpenCompany={onOpenCompany}
              smap={securitiesMap || {}}
            />
          </div>
          <div className="lv-panel lv-reveal">
            <div className="lv-panel-body">
              <div className="lv-board">
                <div className="lv-board-head">
                  <h4><span className="lv-live" aria-hidden="true" />{LT.boardTitle}</h4>
                  {/* The board is still the day's most liquid securities; the
                      selector changes the SPAN each change is measured over, not
                      which rows are here. */}
                  <div className="lv-period" role="group"
                    aria-label={lang === "en" ? "Change period" : lang === "uz" ? "O'zgarish davri" : "Период изменения"}>
                    {CHANGE_PERIODS.map((p) => (
                      <button key={p.code} type="button"
                        className={changePeriod === p.code ? "active" : ""}
                        aria-pressed={changePeriod === p.code}
                        onClick={() => setChangePeriod(p.code)}>
                        {p.code === "1d"
                          ? (lang === "en" ? "D" : lang === "uz" ? "K" : "Д")
                          : p.code === "ytd" ? "YTD" : changePeriodLabel(p.code, lang)}
                      </button>
                    ))}
                  </div>
                  {sesLabel && <span className="lv-ses">{sesLabel} · 15:30 (UTC+5)</span>}
                </div>
                <table className="lv-table">
                  <thead>
                    <tr><th>{LT.thSecurity}</th><th className="r">{LT.thPrice}</th>
                      <th className="r">{changePeriod === "1d" ? LT.thDay
                        : `${lang === "en" ? "Chg" : lang === "uz" ? "O'zg." : "Изм."} ${changePeriodLabel(changePeriod, lang, "short")}`}</th>
                      <th className="r lv-spark-cell">{LT.th30d}</th></tr>
                  </thead>
                  <tbody>
                    {boardRows.map((r) => (
                      <tr key={r.ticker} onClick={() => onOpenCompany(r.ticker)}>
                        <td><span className="lv-tk">{r.ticker}</span><span className="lv-nm">{nameOf(r.ticker)}</span></td>
                        <td className="r">{fmtPrice(marketDisplayPrice(r), lang)}</td>
                        <td className={`r lv-chg ${shownPct(r) > 0.05 ? "lv-u" : shownPct(r) < -0.05 ? "lv-d" : "lv-f0"}`}>
                          {Number.isFinite(shownPct(r)) ? fmtPct(shownPct(r), lang, 2) : "—"}
                        </td>
                        <td className="r lv-spark-cell">
                          <LandingSpark values={((spark[r.ticker]) || []).map((p) => p[1])} label={`${r.ticker} · ${LT.th30d}`} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="lv-board-foot">
                  <span>{LT.footVolume} · <b>{fmtCompact(stats.totalVolume, lang)} {LT.sum}</b></span>
                  <span>{LT.footUp} · <b className="lv-u">{stats.advancers}</b></span>
                  <span>{LT.footDown} · <b className="lv-d">{stats.decliners}</b></span>
                  <span>{LT.footFlat} · <b>{stats.unchanged}</b></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <LandingUpdates language={language} favorites={favorites} marketRows={marketRows} securitiesMap={securitiesMap} onOpenCompany={onOpenCompany} onNavigate={onNavigate} onCalendar={onCalendar} />

      {/* ── 03 · Компания ── */}
      <section className="lv-sec">
        <div className="lv-container lv-wide">
          <div className="lv-sec-head lv-reveal">
            <span className="lv-sec-num">03</span>
            <h2 className="lv-sec-title">{LT.s3Title[0]} <em>{LT.s3Title[1]}</em></h2>
          </div>
          <div className="lv-company-grid">
            <div className="lv-reveal">
              <p className="lv-sec-sub" style={{ margin: "0 0 6px" }}>{LT.s3Sub}</p>
              <div className="lv-points">
                {LT.points.map(([title, text], i) => (
                  <div className="lv-point" key={title}>
                    <span className="lv-point-ico" aria-hidden="true">{pointIcons[i]}</span>
                    <div><h3>{title}</h3><p>{text}</p></div>
                  </div>
                ))}
              </div>
            </div>
            {showRow && (
              <div className="lv-panel lv-company-card lv-reveal" onClick={() => onOpenCompany(showTicker)}
                role="link" tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter") onOpenCompany(showTicker); }}>
                <div className="lv-cc-top">
                  <span className="lv-tk">{showTicker}</span>
                  <span className="lv-nm">{nameOf(showTicker)}</span>
                  <span className="lv-cc-pr">
                    {fmtPrice(marketDisplayPrice(showRow), lang)} {LT.sum}{" "}
                    <b className={showRow.changePercent > 0.05 ? "lv-u" : showRow.changePercent < -0.05 ? "lv-d" : "lv-f0"}>
                      {fmtPct(showRow.changePercent, lang, 2)}
                    </b>
                  </span>
                </div>
                {chips.length > 0 && (
                  <div className="lv-mchips">
                    {chips.map(([label, v, fmt]) => (
                      <span className="lv-mchip" key={label}>{label} <b>{fmt(v)}</b></span>
                    ))}
                  </div>
                )}
                {fin && (
                  <div className="lv-bars-wrap">
                    <div className="lv-bars-title"><span>{LT.barsTitle}</span><b>{LT.sum}</b></div>
                    <div className="lv-bars">
                      {fin.years.map((y, i) => (
                        <div className="lv-bar" key={y}>
                          <span className="v">{fmtCompact(fin.values[i], lang)}</span>
                          <i style={{ "--h": `${Math.max(6, ((fin.values[i] / finMax) * 88))}%` }} />
                          <span className="y">{y}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                <p className="lv-card-note">{LT.cardNote}</p>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── 04 · Новости ── */}
      {news.length > 0 && (
        <section className="lv-sec">
          <div className="lv-container lv-wide">
            <div className="lv-sec-head lv-reveal">
              <span className="lv-sec-num">04</span>
              <h2 className="lv-sec-title">{LT.s4Title[0]} <em>{LT.s4Title[1]}</em></h2>
            </div>
            <p className="lv-sec-sub lv-reveal">{LT.s4Sub}</p>
            <div className="lv-news-grid">
              {news.map((item) => (
                <a className="lv-news-card lv-reveal" key={item.id || item.url} href={newsArticlePath(item, language)}
                  onClick={interceptNav(() => onOpenNews(item))}>
                  <div className="lv-nc-meta">
                    {item.impact && item.impact !== "none" && (
                      <span className={`lv-impact ${item.impact === "high" ? "hi" : "md"}`}>{etx.impact[item.impact] || item.impact}</span>
                    )}
                    {item.published_at && <span>{newsRelTime(item.published_at, language)}</span>}
                  </div>
                  <h3>{edHeadline(item, lang, null).text}</h3>
                  <div className="lv-byline">{item.source && <b>{item.source}</b>}</div>
                </a>
              ))}
            </div>
            <button type="button" className="lv-news-more lv-reveal" onClick={() => onNavigate("news")}>
              {LT.newsAll} <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>
      )}

      {/* ── Шаги ── */}
      <section className="lv-sec" style={{ paddingTop: 56 }}>
        <div className="lv-container">
          <div className="lv-steps lv-reveal">
            {LT.steps.map(([title, text], i) => (
              <div className="lv-step" key={title}>
                <span className="n">{LT.stepWord} 0{i + 1}</span>
                <h3>{title}</h3>
                <p>{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section className="lv-cta">
        <h2 className="lv-reveal">{LT.ctaTitle}</h2>
        <p className="lv-reveal">{LT.ctaText}</p>
        <button type="button" className="lv-go lv-reveal" onClick={() => onNavigate("market")}>{LT.ctaBtn}</button>
      </section>
    </div>
  );
}

export { LandingView };
