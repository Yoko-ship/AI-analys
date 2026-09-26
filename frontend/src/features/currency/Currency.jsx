import { normalizeLanguage } from "../../shared/i18n.jsx";
import { useEffect, useState } from "react";
import { formatRatio } from "../../shared/format.jsx";

// Official CBU (cbu.uz) daily rates in a single thin strip — one row where
// the full-size cards used to stand. Self-fetching: the server caches the
// bank's JSON, so this costs one cheap request per mount. The rates are set
// once per business day — the date in the label is CBU's own, never "live". The day
// change reads as a percent of the previous fix — shorter than сумы in a
// one-line strip; the exact сум difference stays in the item's tooltip.
//
// The topbar still opens on USD, but the market desk deliberately repeats it:
// a rotating header quote is easy to miss and this module must be complete on
// its own. The feed contains USD/EUR/RUB in that order; the explicit priority
// also keeps the desk stable if an environment widens the currency set later.
function FxRatesBar({ language, onOpenBanks }) {
  const lang = normalizeLanguage(language);
  const [fx, setFx] = useState(null);
  useEffect(() => {
    let alive = true;
    fetch("/api/currency/rates")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok && (d.rates || []).length) setFx(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);
  if (!fx) return null;
  const priority = { USD: 0, EUR: 1, RUB: 2 };
  const rates = [...fx.rates].sort((a, b) => (priority[a.ccy] ?? 99) - (priority[b.ccy] ?? 99));
  if (!rates.length) return null;
  const src = lang === "uz" ? "O‘zR MB" : lang === "en" ? "CBU" : "ЦБ РУз";
  const official = lang === "uz" ? "Rasmiy kurs" : lang === "en" ? "Official FX" : "Официальный курс";
  return (
    <section className="fx-bar" aria-label={`${official} · ${src}`}>
      <div className="fx-bar-label">
        <span className="fx-bar-label-mark" aria-hidden="true">FX</span>
        <span className="fx-bar-label-copy">
          <strong>{official}</strong>
          <span>{src}{fx.date ? ` · ${fx.date.slice(0, 5)}` : ""}</span>
        </span>
      </div>
      <div className="fx-bar-quotes">
        {rates.map((r) => {
          const name = lang === "uz" ? r.name_uz : lang === "en" ? r.name_en : r.name_ru;
          const prev = Number.isFinite(r.diff) ? r.rate - r.diff : null;
          const pct = prev > 0 && r.diff !== 0 ? (r.diff / prev) * 100 : 0;
          const code = (r.nominal || 1) > 1 ? `${formatRatio(r.nominal, 0, lang)} ${r.ccy}` : r.ccy;
          const title = pct !== 0
            ? `${name || r.ccy} · ${r.diff > 0 ? "+" : "−"}${formatRatio(Math.abs(r.diff), 2, lang)} UZS`
            : name || r.ccy;
          return (
            <div key={r.ccy} className="fx-bar-item" title={title}>
              <span className="fx-bar-flag"><FxFlagIcon ccy={r.ccy} /></span>
              <span className="fx-bar-quote">
                <span className="fx-bar-quote-head">
                  <span className="fx-bar-ccy">{code}</span>
                  <span className={`fx-bar-pct ${pct > 0 ? "is-up" : pct < 0 ? "is-down" : "is-flat"}`}>
                    <span aria-hidden="true">{pct > 0 ? "↗" : pct < 0 ? "↘" : "→"}</span>
                    {formatRatio(Math.abs(pct), 2, lang)}%
                  </span>
                </span>
                <span className="fx-bar-rate">
                  {formatRatio(r.rate, 2, lang)} <small>UZS</small>
                </span>
              </span>
            </div>
          );
        })}
      </div>
      {onOpenBanks && (
        <button
          type="button"
          className="fx-bar-banks"
          onClick={onOpenBanks}
          title={lang === "en" ? "Commercial banks' cash rates"
            : lang === "uz" ? "Tijorat banklarining kurslari"
            : "Курсы коммерческих банков"}
        >
          <span>
            <small>{lang === "en" ? "Cash exchange" : lang === "uz" ? "Naqd ayirboshlash" : "Наличный обмен"}</small>
            <strong>{lang === "en" ? "Bank rates" : lang === "uz" ? "Bank kurslari" : "Курсы банков"}</strong>
          </span>
          <span className="fx-bar-banks-arrow" aria-hidden="true">↗</span>
        </button>
      )}
    </section>
  );
}

// The currency the topbar ticker opens on. It cycles through everything the
// feed returns; this only fixes where it starts.
const TOPBAR_FX_CCY = "USD";

// How long one currency holds the header. Six seconds reads a number twice
// over without making a reader who wants the euro feel stuck; the cycle also
// stops while the pointer is on the widget.
const TOPBAR_FX_ROTATE_MS = 6000;

// Flags drawn rather than fetched — an emoji flag renders as bare letters on
// Windows, and a remote image would put a third-party request in the header of
// every page. Simplified on purpose: at 21px wide the US flag's thirteen
// stripes and the EU's twelve stars are a smear, so seven stripes and eight
// dots read better than the accurate count. A currency with no drawing falls
// back to its code, which is never wrong.
function FxFlagIcon({ ccy }) {
  const box = { className: "topbar-fx-flag", viewBox: "0 0 30 20", width: 21, height: 14, "aria-hidden": "true", focusable: "false" };
  if (ccy === "USD") {
    return (
      <svg {...box}>
        <rect width="30" height="20" fill="#fff" />
        {[0, 2, 4, 6].map((i) => (
          <rect key={i} y={i * (20 / 7)} width="30" height={20 / 7} fill="#b22234" />
        ))}
        <rect width="13" height={20 * (4 / 7)} fill="#3c3b6e" />
      </svg>
    );
  }
  if (ccy === "EUR") {
    return (
      <svg {...box}>
        <rect width="30" height="20" fill="#039" />
        {Array.from({ length: 8 }, (_, i) => {
          const a = (i / 8) * 2 * Math.PI;
          return <circle key={i} cx={15 + 5.5 * Math.sin(a)} cy={10 - 5.5 * Math.cos(a)} r="1.1" fill="#fc0" />;
        })}
      </svg>
    );
  }
  if (ccy === "RUB") {
    return (
      <svg {...box}>
        <rect width="30" height="20" fill="#fff" />
        <rect y="6.67" width="30" height="6.67" fill="#0039a6" />
        <rect y="13.33" width="30" height="6.67" fill="#d52b1e" />
      </svg>
    );
  }
  return <span className="topbar-fx-code" aria-hidden="true">{ccy}</span>;
}

// The rate ticker in the topbar (customer request 2026-08-19, after finko.uz;
// made to cycle the same day): the numbers most readers open the site for,
// kept in the sticky header so they survive the scroll and every page, not
// just /market. One currency at a time, rotating — the header has room for one
// but the reader wants all three. CBU's official daily fix; a click leads to
// the bank rates, which is the question a reader asks next: where to change it.
function TopbarFxTicker({ language, onOpen }) {
  const lang = normalizeLanguage(language);
  const [fx, setFx] = useState(null);
  const [idx, setIdx] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    let alive = true;
    fetch("/api/currency/rates")
      .then((r) => r.json())
      .then((d) => {
        if (!alive || !d || !d.ok || !(d.rates || []).length) return;
        setFx(d);
        // Open on the dollar wherever the feed happens to put it.
        const start = d.rates.findIndex((r) => r.ccy === TOPBAR_FX_CCY);
        if (start > 0) setIdx(start);
      })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const rates = fx?.rates || [];
  useEffect(() => {
    if (rates.length < 2 || paused) return;
    const id = setInterval(() => setIdx((i) => (i + 1) % rates.length), TOPBAR_FX_ROTATE_MS);
    return () => clearInterval(id);
  }, [rates.length, paused]);

  if (!rates.length) return null;
  const row = rates[idx % rates.length];

  const name = (lang === "uz" ? row.name_uz : lang === "en" ? row.name_en : row.name_ru) || row.ccy;
  const diff = Number.isFinite(row.diff) ? row.diff : 0;
  const prev = diff ? row.rate - diff : null;
  const pct = prev > 0 ? (diff / prev) * 100 : 0;
  // A nominal above one is the whole point of the label: 1000 RUB and 1 RUB
  // are different numbers, and the header would otherwise state the wrong one.
  const unit = (row.nominal || 1) > 1 ? `${formatRatio(row.nominal, 0, lang)} ${row.ccy}` : row.ccy;
  // The header shows the сум difference, as the reference site does; the
  // percent and the source stay in the tooltip, where there is room to be
  // explicit about whose rate this is and for which day.
  const src = lang === "uz" ? "O‘zR MB" : lang === "en" ? "CBU" : "ЦБ РУз";
  const title = [
    `${name} (${unit}) · ${src}${fx.date ? ` · ${fx.date}` : ""}`,
    pct ? `${pct > 0 ? "+" : "−"}${formatRatio(Math.abs(pct), 2, lang)}%` : null,
    lang === "en" ? "Bank exchange rates →" : lang === "uz" ? "Bank kurslari →" : "Курсы банков →",
  ].filter(Boolean).join("\n");

  return (
    <button
      type="button"
      className="topbar-fx"
      onClick={onOpen}
      title={title}
      // A reader who stops to read should not have the number taken away
      // mid-glance; focus counts as reading too, for the keyboard.
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      {/* Keyed by currency so React replaces the node and the fade replays on
          every turn of the cycle. */}
      <span className="topbar-fx-slide" key={row.ccy}>
        <FxFlagIcon ccy={row.ccy} />
        <span className="topbar-fx-body">
          <span className="topbar-fx-name">{(row.nominal || 1) > 1 ? `${name}, ${unit}` : name}</span>
          <span className="topbar-fx-nums">
            <span className="topbar-fx-rate">{formatRatio(row.rate, 2, lang)}</span>
            {diff !== 0 && (
              <span className={`topbar-fx-diff ${diff > 0 ? "is-up" : "is-down"}`}>
                <span aria-hidden="true">{diff > 0 ? "▲" : "▼"}</span>
                {formatRatio(Math.abs(diff), 2, lang)}
              </span>
            )}
          </span>
        </span>
      </span>
      {/* Which of the three is on screen, and how far the cycle has to go.
          Three dots cost 14px and answer "is it going to change again?" */}
      {rates.length > 1 && (
        <span className="topbar-fx-dots" aria-hidden="true">
          {rates.map((r, i) => (
            <i key={r.ccy} className={i === idx % rates.length ? "is-on" : ""} />
          ))}
        </span>
      )}
    </button>
  );
}

// The three sale channels bankxizmatlari.uz publishes for every bank. The
// order is the portal's own; a bank that publishes none of a channel simply
// has no row under that chip.
const BANK_FX_CHANNELS = ["BANK", "APP", "ATM"];

function bankFxChannelLabel(channel, lang) {
  const labels = {
    BANK: { ru: "Обменный пункт", uz: "Ayirboshlash shoxobchasi", en: "Exchange office" },
    APP: { ru: "Приложение", uz: "Ilova", en: "Mobile app" },
    ATM: { ru: "Банкомат", uz: "Bankomat", en: "ATM" },
  };
  return labels[channel]?.[lang] || labels[channel]?.ru || channel;
}

// The bank's own stated update time arrives as ISO with a +05:00 offset.
// Rendered from the STRING, not through Date: it is Tashkent wall-clock the
// bank printed on its card, and shifting it into the reader's zone would show
// a time the bank never stated.
function bankFxStamp(iso) {
  if (!iso || iso.length < 16) return "—";
  return `${iso.slice(11, 16)}, ${iso.slice(8, 10)}.${iso.slice(5, 7)}`;
}

// Same three Russian forms as tradeCountLabel, for the bank counter in the head.
function bankCountLabel(n, lang) {
  if (lang === "uz") return "bank";
  if (lang === "en") return n === 1 ? "bank" : "banks";
  const m10 = n % 10; const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return "банк";
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return "банка";
  return "банков";
}

// A stable monogram colour per bank: the three-digit bank code drives a
// golden-angle hue, so a bank keeps its colour across visits without a
// hand-kept palette.
function bankBadgeStyle(code) {
  const n = parseInt(code, 10) || 0;
  return { background: `hsl(${(n * 137) % 360} 48% 38%)` };
}

function bankInitials(name) {
  const words = String(name || "").replace(/["«»']/g, "").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

// The bank's real logo, captured from bankxizmatlari.uz into our own static
// (frontend/public/bank-logos/{code}.png, normalized to 128px on white) — no
// hotlinking, so their server changing paths cannot blank our page. A bank
// without a captured file falls back to the coloured monogram.
function BankFxLogo({ code, name }) {
  const [broken, setBroken] = useState(false);
  if (broken || !code) {
    return <span className="bankfx-rank-badge" style={bankBadgeStyle(code)} aria-hidden="true">{bankInitials(name)}</span>;
  }
  return (
    <img
      className="bankfx-rank-logo"
      src={`/bank-logos/${code}.png`}
      alt=""
      loading="lazy"
      onError={() => setBroken(true)}
    />
  );
}

// «Где выгоднее обменять» — a page of its own at /currency, reached from the
// «Рынок» drop-down and the «Курсы банков» button on the CBU strip. The page
// answers the reader's question rather than showing a directory: the amount
// and direction are set on top, banks are RANKED by the resulting sum, and
// the lag from the leader is stated in soums (variant Б of the mockups,
// chosen by the customer 2026-08-19). Rates come from bankxizmatlari.uz.
function BankFxPage({ language }) {
  const lang = normalizeLanguage(language);
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [cbu, setCbu] = useState(null);
  const [ccy, setCcy] = useState("USD");
  const [channel, setChannel] = useState("BANK");
  // "sell" = the reader sells currency (the bank BUYS at cell.buy);
  // "buy" = the reader buys it (the bank SELLS at cell.sell).
  const [mode, setMode] = useState("sell");
  const [amountDigits, setAmountDigits] = useState("1000");
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch("/api/bank-fx")
      .then((r) => r.json())
      .then((d) => { if (!alive) return; if (d && d.ok) setData(d); else setFailed(true); })
      .catch(() => { if (alive) setFailed(true); });
    // The official CBU rate anchors the ranking — a bank's rate means little
    // without the reference level it sits against.
    fetch("/api/currency/rates")
      .then((r) => r.json())
      .then((d) => { if (alive && d && d.ok) setCbu(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, []);

  const banks = data?.banks || [];
  const ccySet = new Set();
  banks.forEach((b) => Object.keys(b.rates || {}).forEach((c) => ccySet.add(c)));
  const ccys = ["USD", "EUR", "RUB"].filter((c) => ccySet.has(c))
    .concat([...ccySet].filter((c) => !["USD", "EUR", "RUB"].includes(c)).sort());
  const activeCcy = ccys.includes(ccy) ? ccy : (ccys[0] || ccy);

  const side = mode === "sell" ? "buy" : "sell";
  // An emptied field falls back to ONE unit: the list then ranks by the bare
  // rate instead of multiplying everything by zero into a tie of «лучший»-s.
  const amount = parseInt(amountDigits, 10) || 1;

  const rows = banks
    .map((b) => {
      const cell = b.rates?.[activeCcy]?.[channel];
      if (!cell || cell[side] === null || cell[side] === undefined) return null;
      return { code: b.bank_code, name: b.bank_name, updated: b.updated_at, value: cell[side], flag: cell.flag };
    })
    .filter(Boolean);
  // Selling: the highest buy rate wins; buying: the lowest sell rate. Flagged
  // (wide-spread) quotes sink below the clean ones whatever their number says —
  // an implausible rate must not top a ranking a reader acts on, but it stays
  // on the list, marked, as published (ТЗ: show, flag, never hide).
  const dir = mode === "sell" ? -1 : 1;
  rows.sort((a, b) => ((a.flag ? 1 : 0) - (b.flag ? 1 : 0)) || dir * (a.value - b.value)
    || String(a.name).localeCompare(String(b.name), "ru"));

  const best = data?.best?.[activeCcy]?.[channel] || {};
  const bestVal = (mode === "sell" ? best.best_buy : best.best_sell)?.value ?? null;
  const cbuRate = cbu?.rates?.find((r) => r.ccy === activeCcy) || null;
  // Averages (and the CBU comparison) only over clean quotes, and only when
  // the CBU rate is per ONE unit — a nominal-100 quote would compare apples
  // to hundredweights.
  const cleanVals = rows.filter((r) => !r.flag).map((r) => r.value);
  const avg = cleanVals.length ? cleanVals.reduce((s, v) => s + v, 0) / cleanVals.length : null;
  const cbuComparable = cbuRate && (cbuRate.nominal || 1) === 1 ? cbuRate.rate : null;

  // Bar lengths: best clean quote = full bar, worst = short but visible. The
  // bar ranks, the numbers speak — flagged rows just clamp into range.
  const scores = cleanVals.map((v) => dir * -v);
  const hiScore = scores.length ? Math.max(...scores) : 0;
  const loScore = scores.length ? Math.min(...scores) : 0;
  const barWidth = (v) => {
    if (hiScore === loScore) return 100;
    const s = dir * -v;
    return Math.max(8, Math.min(100, 15 + 85 * ((s - loScore) / (hiScore - loScore))));
  };

  const sumWord = lang === "en" ? "UZS" : lang === "uz" ? "so'm" : "сум";
  const title = lang === "en" ? "Where to exchange best" : lang === "uz" ? "Qayerda almashtirgan ma'qul" : "Где выгоднее обменять";
  const flagTitle = lang === "en" ? "Unusually wide spread — under review, excluded from the ranking's top"
    : lang === "uz" ? "G'ayrioddiy keng spred — tekshirilmoqda, reyting yuqorisiga kirmaydi"
    : "Аномально широкий спред — котировка проверяется и не участвует в верхушке рейтинга";
  const updWord = lang === "en" ? "updated" : lang === "uz" ? "yangilangan" : "обновлено";
  const rateWord = lang === "en" ? "rate" : lang === "uz" ? "kurs" : "курс";
  const visible = showAll ? rows : rows.slice(0, 12);

  const sellWord = lang === "en" ? "Sell" : lang === "uz" ? "Sotish" : "Продать";
  const buyWord = lang === "en" ? "Buy" : lang === "uz" ? "Olish" : "Купить";

  return (
    <section className="bankfx-page">
      <article className="panel">
        <div className="panel-head">
          <div>
            <div className="panel-label">{lang === "en" ? "Currency" : lang === "uz" ? "Valyuta" : "Валюта"}</div>
            <h2>{title}</h2>
            <p className="bankfx-page-sub">
              {lang === "en"
                ? "Cash rates published by Uzbekistan's commercial banks, ranked by what your amount actually comes to."
                : lang === "uz"
                  ? "O'zbekiston tijorat banklari e'lon qilgan naqd kurslar — summangiz amalda nechaga chiqishi bo'yicha saralangan."
                  : "Наличные курсы коммерческих банков Узбекистана — по тому, во что реально превращается ваша сумма."}
              {" "}
              {lang === "en" ? "Source" : lang === "uz" ? "Manba" : "Источник"}: bankxizmatlari.uz
            </p>
          </div>
          {rows.length > 0 && (
            <span className="status-badge muted">{rows.length} {bankCountLabel(rows.length, lang)}</span>
          )}
        </div>

        <div className="bankfx-calc">
          <div className="segmented-control" role="group" aria-label={lang === "en" ? "Direction" : lang === "uz" ? "Yo'nalish" : "Направление"}>
            <button type="button" className={mode === "sell" ? "active" : ""} aria-pressed={mode === "sell"}
              onClick={() => setMode("sell")}>{sellWord}</button>
            <button type="button" className={mode === "buy" ? "active" : ""} aria-pressed={mode === "buy"}
              onClick={() => setMode("buy")}>{buyWord}</button>
          </div>
          <label className="bankfx-amount">
            <input
              value={amountDigits ? formatRatio(parseInt(amountDigits, 10), 0, lang) : ""}
              inputMode="numeric"
              aria-label={lang === "en" ? "Amount" : lang === "uz" ? "Summa" : "Сумма"}
              placeholder="1 000"
              onChange={(e) => setAmountDigits(e.target.value.replace(/\D/g, "").slice(0, 9))}
            />
            <span className="bankfx-amount-ccy">{activeCcy}</span>
          </label>
          <div className="segmented-control" role="group" aria-label={lang === "en" ? "Currency" : lang === "uz" ? "Valyuta" : "Валюта"}>
            {(ccys.length ? ccys : ["USD", "EUR", "RUB"]).map((c) => (
              <button key={c} type="button" className={c === activeCcy ? "active" : ""}
                aria-pressed={c === activeCcy} onClick={() => setCcy(c)}>{c}</button>
            ))}
          </div>
          <div className="segmented-control" role="group" aria-label={lang === "en" ? "Channel" : lang === "uz" ? "Kanal" : "Канал"}>
            {BANK_FX_CHANNELS.map((ch) => (
              <button key={ch} type="button" className={ch === channel ? "active" : ""}
                aria-pressed={ch === channel} onClick={() => setChannel(ch)}>{bankFxChannelLabel(ch, lang)}</button>
            ))}
          </div>
          {cbuComparable !== null && (
            <p className="bankfx-calc-note">
              {lang === "en" ? "CBU rate" : lang === "uz" ? "MB kursi" : "Курс ЦБ"}: <b>{formatRatio(cbuComparable, 2, lang)}</b>
              {avg !== null && Math.round(Math.abs(cbuComparable - avg)) > 0 && (
                mode === "sell"
                  ? (lang === "en"
                      ? ` · banks buy on average ${formatRatio(Math.abs(cbuComparable - avg), 0, lang)} UZS ${avg < cbuComparable ? "below" : "above"} it`
                      : lang === "uz"
                        ? ` · banklar o'rtacha ${formatRatio(Math.abs(cbuComparable - avg), 0, lang)} so'm ${avg < cbuComparable ? "past" : "yuqori"} oladi`
                        : ` · банки покупают в среднем на ${formatRatio(Math.abs(cbuComparable - avg), 0, lang)} сум ${avg < cbuComparable ? "ниже" : "выше"}`)
                  : (lang === "en"
                      ? ` · banks sell on average ${formatRatio(Math.abs(avg - cbuComparable), 0, lang)} UZS ${avg > cbuComparable ? "above" : "below"} it`
                      : lang === "uz"
                        ? ` · banklar o'rtacha ${formatRatio(Math.abs(avg - cbuComparable), 0, lang)} so'm ${avg > cbuComparable ? "yuqori" : "past"} sotadi`
                        : ` · банки продают в среднем на ${formatRatio(Math.abs(avg - cbuComparable), 0, lang)} сум ${avg > cbuComparable ? "выше" : "ниже"}`)
              )}
            </p>
          )}
        </div>

        {failed ? (
          <p className="bankfx-empty">
            {lang === "en" ? "Could not load the rates. Try again later."
              : lang === "uz" ? "Kurslarni yuklab bo'lmadi. Keyinroq urinib ko'ring."
              : "Не удалось загрузить курсы. Попробуйте позже."}
          </p>
        ) : !data ? (
          <p className="bankfx-empty">{lang === "en" ? "Loading..." : lang === "uz" ? "Yuklanmoqda..." : "Загрузка..."}</p>
        ) : !rows.length ? (
          <p className="bankfx-empty">
            {lang === "en" ? "No published rates for this currency and channel yet."
              : lang === "uz" ? "Bu valyuta va kanal uchun e'lon qilingan kurslar hozircha yo'q."
              : "Опубликованных курсов для этой валюты и канала пока нет."}
          </p>
        ) : (
          <div className="bankfx-rank">
            {visible.map((r, i) => {
              const isLead = !r.flag && bestVal !== null && r.value === bestVal;
              const diff = bestVal === null ? null : Math.round((r.value - bestVal) * amount);
              return (
                <div key={r.code} className={`bankfx-rank-row${isLead ? " is-lead" : ""}`}>
                  <span className="bankfx-rank-pos">{i + 1}</span>
                  <BankFxLogo code={r.code} name={r.name} />
                  <span className="bankfx-rank-name">
                    {r.name}
                    {r.flag && <span className="bankfx-flag" title={flagTitle}> ⚠</span>}
                    {/* At the page's single type size this line outgrows a
                        phone column and ellipsizes — the title keeps the
                        stamp reachable there. */}
                    <span
                      className="bankfx-rank-sub"
                      title={`${rateWord} ${formatRatio(r.value, 2, lang)} · ${updWord} ${bankFxStamp(r.updated)}`}
                    >
                      {rateWord} {formatRatio(r.value, 2, lang)} · {updWord} {bankFxStamp(r.updated)}
                    </span>
                  </span>
                  <span className="bankfx-rank-bar" aria-hidden="true"><i style={{ width: `${barWidth(r.value)}%` }} /></span>
                  <span
                    className="bankfx-rank-sum"
                    title={mode === "sell"
                      ? (lang === "en" ? "You receive" : lang === "uz" ? "Siz olasiz" : "Вы получите")
                      : (lang === "en" ? "You pay" : lang === "uz" ? "Siz to'laysiz" : "Вы заплатите")}
                  >
                    {formatRatio(Math.round(r.value * amount), 0, lang)} {sumWord}
                  </span>
                  {r.flag ? (
                    <span className="bankfx-rank-diff is-flagged" title={flagTitle}>⚠</span>
                  ) : isLead || diff === 0 ? (
                    <span className="bankfx-rank-diff is-lead">{lang === "en" ? "best" : lang === "uz" ? "eng yaxshi" : "лучший"}</span>
                  ) : (
                    <span className="bankfx-rank-diff">
                      {mode === "sell" ? "−" : "+"}{formatRatio(Math.abs(diff), 0, lang)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {rows.length > visible.length && (
          <button type="button" className="bankfx-more" onClick={() => setShowAll(true)}>
            {lang === "en" ? `${rows.length - visible.length} more banks ↓`
              : lang === "uz" ? `Yana ${rows.length - visible.length} bank ↓`
              : `Ещё ${rows.length - visible.length} ${bankCountLabel(rows.length - visible.length, lang)} ↓`}
          </button>
        )}

        {/* The footnote that stood here (how the sum is computed, whose clock
            the times are, what ⚠ means) was removed at the customer's request
            2026-08-19. The ⚠ badge keeps its own tooltip. */}
      </article>
    </section>
  );
}

export { BankFxPage, FxRatesBar, TopbarFxTicker };
