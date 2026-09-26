import { snapPixel } from "../../lib/geometry.js";
import { prepareMarketRows } from "../../lib/marketData.js";
import React from "react";
import { normalizeLanguage } from "../../shared/i18n.jsx";
import { EDNEWS_TX, edHeadline, interceptNav, newsArticlePath, newsRelTime } from "../news/index.js";
import { buildMarketStats, marketDisplayPrice } from "../../shared/marketModel.jsx";
import { marketRowDay } from "../../lib/valuation.js";
import { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { compact as fmtCompact, num as fmtNumber, pct as fmtPct, price as fmtPrice } from "../../lib/format.js";

// ─────────────────────────────────────────────────────────────────────────────
// Landing («Город на рассвете») — the "/" view. A cinematic single-theme page:
// a canvas dawn over the Tashkent skyline whose horizon line is a market chart,
// followed by live previews of the market board, a company page and the news
// feed — every number on it comes from the same endpoints the real views read,
// so the landing can never advertise data the site does not hold.

const LANDING_TX = {
  ru: {
    h1: ["Открытый", "рынок"],
    lede: "Фондовая биржа «Тошкент» — как на ладони: котировки, отчётность эмитентов и новости, влияющие на цену. Официальные данные Узбекистана, собранные в одну платформу.",
    ctaMarket: "Смотреть рынок",
    ctaCompare: "Сравнить компании",
    s2Title: ["Табло", "рынка"],
    s2Sub: "Все бумаги биржи в одной таблице: цена, изменение за день и график за месяц. Сортировка по любой колонке, тепловая карта секторов и фильтры — в один клик.",
    boardTitle: "Итоги сессии",
    thSecurity: "Бумага", thPrice: "Цена, сум", thDay: "За день", th30d: "30 дней",
    footVolume: "Объём торгов", footUp: "Растёт", footDown: "Падает", footFlat: "Без изменения",
    railGainers: "Лидеры дня", railLosers: "Аутсайдеры",
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
    ctaCompare: "Kompaniyalarni solishtirish",
    s2Title: ["Bozor", "taxtasi"],
    s2Sub: "Birjaning barcha qog'ozlari bitta jadvalda: narx, kunlik o'zgarish va oylik grafik. Istalgan ustun bo'yicha saralash, sektorlar xaritasi va filtrlar — bir bosishda.",
    boardTitle: "Sessiya yakunlari",
    thSecurity: "Qog'oz", thPrice: "Narx, so'm", thDay: "Kunlik", th30d: "30 kun",
    footVolume: "Savdo hajmi", footUp: "O'sdi", footDown: "Tushdi", footFlat: "O'zgarishsiz",
    railGainers: "Kun yetakchilari", railLosers: "Autsayderlar",
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
    ctaCompare: "Compare companies",
    s2Title: ["The market", "board"],
    s2Sub: "Every listed security in one table: price, daily change and a one-month chart. Sort by any column, switch to the sector heatmap, filter in one click.",
    boardTitle: "Session results",
    thSecurity: "Security", thPrice: "Price, UZS", thDay: "1 day", th30d: "30 days",
    footVolume: "Turnover", footUp: "Up", footDown: "Down", footFlat: "Unchanged",
    railGainers: "Top gainers", railLosers: "Top losers",
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

// The dawn scene: sky gradient, twinkling stars, an occasional meteor, the
// brand-colour "market chart" horizon line (faded on the left so it never fights the
// headline), and the city silhouette with the Tashkent TV tower.
function LandingSky({ theme }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    const cv = ref.current;
    if (!cv) return undefined;
    const ctx = cv.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Two palettes, one scene: night dawn for dark theme, morning for light.
    // Stars, window lights and meteors belong to the night only.
    const pal = theme === "light" ? {
      sky: [[0, "#d9dcf3"], [0.5, "#e8eafb"], [0.78, "#f5f7fb"], [0.92, "#ddd9ff"], [1, "#b9b1f3"]],
      glow: [[0, "rgba(225, 221, 255, 0.92)"], [0.35, "rgba(98, 87, 217, 0.2)"], [1, "rgba(98, 87, 217, 0)"]],
      night: false,
      line: [[0, "rgba(98, 87, 217, 0.08)"], [0.45, "rgba(98, 87, 217, 0.18)"], [0.62, "rgba(98, 87, 217, 0.52)"], [1, "rgba(98, 87, 217, 0.62)"]],
      dot: "#6257d9", dotGlow: "rgba(98, 87, 217, 0.25)",
      city: "#2c3045",
    } : {
      sky: [[0, "#0b0d12"], [0.52, "#11141b"], [0.78, "#181a2a"], [0.92, "#252348"], [1, "#3a337d"]],
      glow: [[0, "rgba(192, 184, 255, 0.58)"], [0.35, "rgba(139, 124, 255, 0.22)"], [1, "rgba(139, 124, 255, 0)"]],
      night: true,
      line: [[0, "rgba(139, 124, 255, 0.08)"], [0.45, "rgba(139, 124, 255, 0.16)"], [0.62, "rgba(139, 124, 255, 0.5)"], [1, "rgba(139, 124, 255, 0.58)"]],
      dot: "#8b7cff", dotGlow: "rgba(139, 124, 255, 0.26)",
      city: "#080910",
    };
    let stars = [], meteors = [], t0 = 0, lastMeteor = 0, raf = 0, alive = true;
    const pts = [0.0, 0.30, 0.06, 0.26, 0.12, 0.34, 0.18, 0.24, 0.25, 0.30, 0.32, 0.18, 0.40, 0.26,
                 0.48, 0.14, 0.56, 0.22, 0.64, 0.10, 0.72, 0.18, 0.80, 0.06, 0.88, 0.14, 1.0, 0.02];

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = cv.clientWidth, h = cv.clientHeight;
      cv.width = snapPixel(w * dpr);
      cv.height = snapPixel(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      stars = [];
      for (let i = 0; i < 90; i++) {
        stars.push({ x: Math.random() * w, y: Math.random() * h * 0.55, r: Math.random() * 1.1 + 0.2, p: Math.random() * Math.PI * 2 });
      }
    };

    const skyline = (w, h) => {
      const base = h * 0.86;
      ctx.fillStyle = pal.city;
      ctx.beginPath();
      ctx.moveTo(0, h); ctx.lineTo(0, base);
      let x = 0, i = 0;
      while (x < w) {
        const bw = 26 + ((i * 37) % 44);
        const bh = 18 + ((i * 61) % 72);
        ctx.lineTo(x, base - bh); ctx.lineTo(x + bw, base - bh);
        x += bw; i++;
      }
      ctx.lineTo(w, base); ctx.lineTo(w, h);
      ctx.closePath(); ctx.fill();

      const tx = w * 0.72, ty = base, TH = Math.min(h * 0.42, 330);
      ctx.fillStyle = pal.city;
      ctx.beginPath();
      ctx.moveTo(tx - 26, ty); ctx.lineTo(tx - 4, ty - TH * 0.38); ctx.lineTo(tx + 4, ty - TH * 0.38); ctx.lineTo(tx + 26, ty);
      ctx.closePath(); ctx.fill();
      ctx.fillRect(tx - 4, ty - TH * 0.78, 8, TH * 0.44);
      ctx.beginPath(); ctx.ellipse(tx, ty - TH * 0.66, 17, 8, 0, 0, Math.PI * 2); ctx.fill();
      ctx.beginPath(); ctx.ellipse(tx, ty - TH * 0.74, 11, 5, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillRect(tx - 1.5, ty - TH, 3, TH * 0.24);
      ctx.fillStyle = "rgba(255, 120, 120, 0.9)";
      ctx.beginPath(); ctx.arc(tx, ty - TH, 2.6, 0, Math.PI * 2); ctx.fill();

      if (pal.night) {
        ctx.fillStyle = "rgba(255, 196, 120, 0.28)";
        for (let k = 0; k < 60; k++) {
          const wx = ((k * 97) % w), wy = base - 8 - ((k * 53) % 58);
          ctx.fillRect(wx, wy, 2.5, 2.5);
        }
      }
    };

    const draw = (ts) => {
      if (!alive) return;
      const w = cv.clientWidth, h = cv.clientHeight;
      if (!t0) t0 = ts;
      const t = (ts - t0) / 1000;

      const g = ctx.createLinearGradient(0, 0, 0, h);
      pal.sky.forEach(([stop, color]) => g.addColorStop(stop, color));
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, w, h);

      const sx = w * 0.72, sy = h * 0.84;
      const sg = ctx.createRadialGradient(sx, sy, 4, sx, sy, 180);
      pal.glow.forEach(([stop, color]) => sg.addColorStop(stop, color));
      ctx.fillStyle = sg;
      ctx.fillRect(0, 0, w, h);

      if (pal.night) for (let i = 0; i < stars.length; i++) {
        const s = stars[i];
        const a = 0.35 + 0.35 * Math.sin(t * 0.8 + s.p);
        ctx.fillStyle = `rgba(238, 242, 249, ${reduced ? 0.45 : a.toFixed(3)})`;
        ctx.fillRect(s.x, s.y, s.r, s.r);
      }

      if (pal.night && !reduced && t - lastMeteor > 7 && Math.random() < 0.02) {
        lastMeteor = t;
        meteors.push({ x: Math.random() * w * 0.7 + w * 0.15, y: Math.random() * h * 0.25 + 20, vx: -3.4, vy: 1.6, life: 1 });
      }
      for (let m = meteors.length - 1; m >= 0; m--) {
        const mt = meteors[m];
        mt.x += mt.vx * 3; mt.y += mt.vy * 3; mt.life -= 0.02;
        if (mt.life <= 0) { meteors.splice(m, 1); continue; }
        ctx.strokeStyle = `rgba(238, 242, 249, ${(mt.life * 0.7).toFixed(3)})`;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(mt.x, mt.y);
        ctx.lineTo(mt.x - mt.vx * 12, mt.y - mt.vy * 12);
        ctx.stroke();
      }

      const lg = ctx.createLinearGradient(0, 0, w, 0);
      pal.line.forEach(([stop, color]) => lg.addColorStop(stop, color));
      ctx.strokeStyle = lg;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.beginPath();
      const reveal = reduced ? 1 : Math.min(1, t / 3.5);
      const n = Math.max(2, Math.floor((pts.length / 2) * reveal));
      for (let p = 0; p < n; p++) {
        const px = pts[p * 2] * w;
        const py = h * 0.62 - pts[p * 2 + 1] * h * 0.28;
        if (p === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.stroke();
      if (reveal >= 1) {
        const lx = pts[pts.length - 2] * w, ly = h * 0.62 - pts[pts.length - 1] * h * 0.28;
        const pulse = reduced ? 4 : 4 + Math.sin(t * 2.4) * 1.4;
        ctx.fillStyle = pal.dotGlow;
        ctx.beginPath(); ctx.arc(lx, ly, pulse * 2.4, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = pal.dot;
        ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2); ctx.fill();
      }

      skyline(w, h);
      if (!reduced) raf = requestAnimationFrame(draw);
    };

    const onResize = () => { resize(); if (reduced) raf = requestAnimationFrame(draw); };
    resize();
    window.addEventListener("resize", onResize);
    raf = requestAnimationFrame(draw);
    return () => {
      alive = false;
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, [theme]);
  return <canvas ref={ref} className="lv-sky" aria-hidden="true" />;
}

/* The board's 30-day line. The shared <MiniSparkline> is drawn for a metric
   card — a 220×74 viewBox with a 4px non-scaling stroke — and squeezing that
   into a 26px table cell kept the stroke at four literal pixels over a ~19px
   plot, which read as a fat snake rather than a price. This one is authored at
   the size it is shown (1 user unit = 1 CSS pixel, so the hairline stays a
   hairline) and takes its color from the landing's own up/down tokens, so the
   line agrees with the change column beside it. */
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

function LandingView({ language, theme, marketRows, tradeStats, securitiesMap, companies, onNavigate, onOpenCompany, onOpenNews }) {
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
  const periodRail = React.useMemo(() => {
    if (changePeriod === "1d") {
      return { up: stats.topGainers.slice(0, 3), down: stats.topLosers.slice(0, 2) };
    }
    const pool = prepared
      .map((r) => ({ row: r, pct: periodPct(r.ticker) }))
      .filter((x) => Number.isFinite(x.pct));
    return {
      up: pool.filter((x) => x.pct > 0).sort((a, b) => b.pct - a.pct).slice(0, 3).map((x) => x.row),
      down: pool.filter((x) => x.pct < 0).sort((a, b) => a.pct - b.pct).slice(0, 2).map((x) => x.row),
    };
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
    <div className="landing-view" ref={rootRef}>
      {/* ── Сцена ── */}
      <section className="lv-stage">
        <LandingSky theme={theme} />
        <div className="lv-mid">
          <div className="lv-lede">
            <h1 className="lv-h1">{LT.h1[0]}<br />{LT.h1[1]}</h1>
            <p>{LT.lede}</p>
            <div className="lv-actions">
              <button type="button" className="lv-go" onClick={() => onNavigate("market")}>{LT.ctaMarket}</button>
              <button type="button" className="lv-ghost" onClick={() => onNavigate("compare")}>{LT.ctaCompare}</button>
            </div>
          </div>
        </div>
        <span className="lv-cue" aria-hidden="true" />
      </section>

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
              <aside className="lv-rail">
                <h5>{LT.railGainers}{changePeriod !== "1d" && ` · ${changePeriodLabel(changePeriod, lang, "short")}`}</h5>
                {periodRail.up.map((r) => (
                  <button type="button" className="lv-mover" key={r.ticker} onClick={() => onOpenCompany(r.ticker)}>
                    <span className="lv-mover-id"><span className="lv-tk">{r.ticker}</span><span className="lv-nm">{nameOf(r.ticker)}</span></span>
                    <span className="pc lv-u">{fmtPct(shownPct(r), lang, 2)}</span>
                  </button>
                ))}
                <h5>{LT.railLosers}{changePeriod !== "1d" && ` · ${changePeriodLabel(changePeriod, lang, "short")}`}</h5>
                {periodRail.down.map((r) => (
                  <button type="button" className="lv-mover" key={r.ticker} onClick={() => onOpenCompany(r.ticker)}>
                    <span className="lv-mover-id"><span className="lv-tk">{r.ticker}</span><span className="lv-nm">{nameOf(r.ticker)}</span></span>
                    <span className="pc lv-d">{fmtPct(shownPct(r), lang, 2)}</span>
                  </button>
                ))}
              </aside>
            </div>
          </div>
        </div>
      </section>

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
                <a className="lv-news-card lv-reveal" key={item.id || item.url} href={newsArticlePath(item)}
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
