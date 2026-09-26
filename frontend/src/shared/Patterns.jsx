import React from "react";
import { toTime as lwTime } from "../charts/lwCore.js";
import { patternName } from "../lib/patterns.js";

// ── Chart patterns (pattern_engine.py, /api/company/{t}/patterns) ─────────
// Annotation, not advice. Each figure on the chart is listed beside how that
// figure has actually done on liquid UZSE shares and how often an ordinary
// session reaches the same target by chance — on this market usually more
// often. No arrows, no «купить»: the list states the record and stops there.
const PATTERN_SENSITIVITY = [
  ["low", "Низкая", "Past", "Low"],
  ["medium", "Средняя", "O'rta", "Medium"],
  ["high", "Высокая", "Yuqori", "High"],
];

const patternKey = (s) => `${s.type}:${s.signal_date}`;

/** A security's detected patterns at one sensitivity, fetched when first asked for. */
function usePatterns(ticker, enabled, sensitivity = "medium") {
  const [cache, setCache] = React.useState({});
  const up = String(ticker || "").toUpperCase();
  React.useEffect(() => { setCache({}); }, [up]);
  const data = cache[sensitivity] || null;
  React.useEffect(() => {
    if (!enabled || !up || data) return undefined;
    let alive = true;
    const keep = (d) => { if (alive) setCache((c) => ({ ...c, [sensitivity]: d })); };
    fetch(`/api/company/${encodeURIComponent(up)}/patterns?sensitivity=${sensitivity}`)
      .then((r) => r.json())
      .then((d) => keep(d && d.ok ? d : { status: "ERROR", signals: [] }))
      .catch(() => keep({ status: "ERROR", signals: [] }));
    return () => { alive = false; };
  }, [up, enabled, data, sensitivity]);
  return data;
}

/**
 * What the patterns add to the price series. A figure is shaded over its
 * extent, drawn through its turning points (dotted) with its neckline or
 * edges (solid) and marked at the session whose close completed it; a candle
 * model is only marked. Figures completing on one session share one marker,
 * and names are written only when `labels` is set — on a multi-year view they
 * would print over each other. The `selected` pattern also gets its target and
 * stop, drawn across the horizon it was scored over.
 */
function patternOverlay(signals, times, lang, labels = true, selected = null, horizon = 20) {
  const known = new Set(times);
  const segments = [];
  const boxes = [];
  const marks = new Map();
  const at = (p) => ({ time: lwTime(p.date), value: p.price });
  (signals || []).forEach((s) => {
    const t = lwTime(s.signal_date);
    if (!known.has(t)) return;
    const up = s.direction === "bullish";
    const solid = up ? "rgba(47,197,132,0.95)" : "rgba(238,106,96,0.95)";
    const faint = up ? "rgba(47,197,132,0.5)" : "rgba(238,106,96,0.5)";
    (s.lines || []).forEach((l) => segments.push({ from: at(l.from), to: at(l.to), color: solid, width: 1.6 }));
    if (s.family === "chart") {
      (s.points || []).slice(1).forEach((p, i) => segments.push({
        from: at(s.points[i]), to: at(p), color: faint, width: 1, dash: [3, 3] }));
      if (s.box) {
        boxes.push({ from: lwTime(s.box.from), to: lwTime(s.box.to), high: s.box.high, low: s.box.low,
          fill: up ? "rgba(47,197,132,0.07)" : "rgba(238,106,96,0.07)" });
      }
    }
    const key = `${t}:${s.direction}`;
    const mark = marks.get(key) || { time: t, position: up ? "belowBar" : "aboveBar", color: solid,
      shape: "circle", size: 0.7, names: [] };
    mark.names.push(patternName(s.type, lang));
    marks.set(key, mark);
  });
  if (selected && known.has(lwTime(selected.signal_date))) {
    const i = times.indexOf(lwTime(selected.signal_date));
    const end = times[Math.min(times.length - 1, i + horizon)];
    const from = times[i];
    const up = selected.direction === "bullish";
    const fmt = (v) => Number(v).toLocaleString(lang === "en" ? "en-US" : "ru-RU", { maximumFractionDigits: 2 });
    const tgt = lang === "en" ? "target" : lang === "uz" ? "maqsad" : "цель";
    segments.push({ from: { time: from, value: selected.target }, to: { time: end, value: selected.target },
      color: up ? "rgba(47,197,132,0.95)" : "rgba(238,106,96,0.95)", width: 1.4, dash: [6, 4],
      label: `${tgt} ${fmt(selected.target)}` });
    segments.push({ from: { time: from, value: selected.stop }, to: { time: end, value: selected.stop },
      color: "rgba(245,158,11,0.95)", width: 1.4, dash: [6, 4], label: `${lang === "uz" ? "stop" : lang === "en" ? "stop" : "стоп"} ${fmt(selected.stop)}` });
  }
  const markers = [...marks.values()].map(({ names, ...m }) => ({ ...m, text: labels ? names.join(" · ") : "" }));
  return { segments, markers, boxes };
}

/** Merge the pattern layer into a spec's price series (mutates the fresh series list). */
function applyPatternOverlay(series, overlay) {
  const price = series[0];
  if (!price || price.key !== "price") return;
  price.segments = [...(price.segments || []), ...overlay.segments];
  price.boxes = [...(price.boxes || []), ...overlay.boxes];
  price.markers = [...(price.markers || []), ...overlay.markers].sort((a, b) => a.time - b.time);
}

/**
 * The switches behind the «Паттерны» button, for either toolbar. `variant`
 * picks the company chart's menu roles or the full-screen chart's menu items.
 */
function PatternMenuItems({ patternsOn, setPatternsOn, sensitivity, setSensitivity, available, lang, variant }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const cpc = variant === "cpc";
  // Two kinds of control in one menu, and they have to look different: three
  // independent switches (a tick each) and one choice of three (a dot). The
  // sensitivity only moves the ZigZag, so it is greyed while figures are off.
  const item = (key, label, checked, onClick, disabled = false, radio = false) => (
    <button key={key} type="button" role={cpc ? (radio ? "menuitemradio" : "menuitemcheckbox") : undefined}
      aria-checked={cpc ? checked : undefined} aria-pressed={cpc ? undefined : checked} disabled={disabled}
      className={`pattern-menu-item ${cpc ? (checked ? "active" : "") : `ac-menu-item ${checked ? "on" : ""}`}`}
      onClick={onClick}>
      <span className={`pattern-menu-mark ${radio ? "is-radio" : "is-check"} ${checked ? "is-on" : ""}`} aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
  const figuresOn = available && patternsOn.chart;
  return (
    <div className="pattern-menu">
      <span className="pattern-menu-head">{t("Показать", "Ko'rsatish", "Show")}</span>
      {item("chart", t("Фигуры", "Shakllar", "Chart figures"), patternsOn.chart,
        () => setPatternsOn((c) => ({ ...c, chart: !c.chart })), !available)}
      {item("candle", t("Свечные модели", "Sham modellari", "Candle models"), patternsOn.candle,
        () => setPatternsOn((c) => ({ ...c, candle: !c.candle })), !available)}
      {item("cycle", t("Цикличность", "Tsikllilik", "Cycles"), patternsOn.cycle,
        () => setPatternsOn((c) => ({ ...c, cycle: !c.cycle })))}
      <span className="pattern-menu-sep" aria-hidden="true" />
      <span className="pattern-menu-head">{t("Чувствительность фигур", "Shakllar sezgirligi", "Figure sensitivity")}</span>
      {PATTERN_SENSITIVITY.map(([key, ru, uz, en]) => item(`s:${key}`, t(ru, uz, en), sensitivity === key,
        () => setSensitivity(key), !figuresOn, true))}
      {available && !patternsOn.chart && (
        <span className="pattern-menu-hint">
          {t("Действует только на фигуры — включите их выше", "Faqat shakllarga ta'sir qiladi — ularni yoqing",
             "Applies to chart figures only — switch them on above")}
        </span>
      )}
      {!available && (
        <span className="pattern-menu-hint">
          {t("Фигуры и свечи — только на дневных свечах в сумах, без сравнения",
             "Shakllar va shamlar — faqat kunlik shamlarda, taqqoslashsiz",
             "Figures and candles: daily bars in сум only, no comparison")}
        </span>
      )}
    </div>
  );
}

const PATTERN_OUTCOME = {
  target: ["цель достигнута", "maqsadga yetdi", "target reached"],
  stop: ["сработал стоп", "stop ishladi", "stop hit"],
  horizon: ["за 20 сессий ни цель, ни стоп", "20 sessiyada na maqsad, na stop", "neither target nor stop in 20 sessions"],
  open: ["ещё в пределах 20 сессий", "hali 20 sessiya ichida", "still within 20 sessions"],
  pending: ["исполнение со следующей сессии", "keyingi sessiyadan", "fills from the next session"],
};

/**
 * The patterns panel under a chart: the figures in view, newest first, each
 * with its UZSE record; the strategy test for the families switched on; the
 * cycle test when asked for.
 */
function PatternList({ data, signals, lang, onPick, visibleFrom, visibleTo, limit = 8, families, selectedKey }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const li = lang === "uz" ? 1 : lang === "en" ? 2 : 0;
  const locale = lang === "en" ? "en-US" : "ru-RU";
  if (!data) return <p className="pattern-note muted">{t("Поиск паттернов…", "Patternlar qidirilmoqda…", "Finding patterns…")}</p>;
  if (data.status === "INSUFFICIENT_LIQUIDITY") {
    return (
      <p className="pattern-note muted" data-testid="pattern-list">
        {t("Паттерны не строятся для этой бумаги — слишком редкие сделки", "Bu qog'oz uchun patternlar qurilmaydi — bitimlar juda kam",
           "No patterns for this security — it trades too rarely")}
        {data.reason ? `: ${data.reason}.` : "."}
      </p>
    );
  }
  if (data.status !== "AVAILABLE") {
    return <p className="pattern-note muted" data-testid="pattern-list">{t("Паттерны недоступны", "Patternlar mavjud emas", "Patterns unavailable")}</p>;
  }
  const showPatterns = families.chart || families.candle;
  const inView = (signals || [])
    .filter((s) => (!visibleFrom || s.signal_date >= String(visibleFrom).slice(0, 10))
      && (!visibleTo || s.signal_date <= String(visibleTo).slice(0, 10)))
    .slice().reverse();
  const stats = data.market_stats || {};
  const meta = data.stats_meta || {};
  const num = (v, d = 0) => (v == null ? "—" : Number(v).toLocaleString(locale, { maximumFractionDigits: d }));
  const pct = (v, d = 0) => (v == null ? "—" : `${num(v, d)}%`);
  const dateOf = (d) => new Date(d).toLocaleDateString(locale, { day: "numeric", month: "short", year: "2-digit" });
  const bt = data.backtest?.[families.chart && families.candle ? "all" : families.chart ? "chart" : "candle"];
  const cyc = data.cycle;
  return (
    <section className="pattern-list" data-testid="pattern-list">
      {showPatterns && (
        <>
          <header>
            <strong>{t("Паттерны на графике", "Grafikdagi patternlar", "Patterns on the chart")}</strong>
            <span className="muted">{inView.length}</span>
          </header>
          {inView.length === 0 && (
            <p className="pattern-note muted">{t("В видимом периоде паттернов нет", "Ko'rinayotgan davrda pattern yo'q", "No patterns in the visible period")}</p>
          )}
          <ul>
            {inView.slice(0, limit).map((s) => {
              const st = stats[s.type] || {};
              // Better or worse than chance only when the gap is well beyond
              // noise: z ≥ 3 over the trades that reached target or stop. With
              // some 25 pattern types tested, z ≥ 2 would crown one by luck.
              const h = (st.hit_rate_pct ?? NaN) / 100, c = (st.chance_pct ?? NaN) / 100, n = st.decided || 0;
              const z = n && c > 0 && c < 1 ? (h - c) / Math.sqrt((c * (1 - c)) / n) : 0;
              const verdict = z >= 3 ? "above" : z <= -3 ? "below" : "same";
              const key = patternKey(s);
              return (
                <li key={key} className={selectedKey === key ? "is-selected" : ""}>
                  <button type="button" onClick={() => onPick?.(s)} aria-pressed={selectedKey === key}>
                    <span className={`pattern-dir ${s.direction === "bullish" ? "up" : "down"}`}>
                      {s.direction === "bullish" ? "↑" : "↓"}
                    </span>
                    <span className="pattern-name">{patternName(s.type, lang)}</span>
                    <span className="pattern-date muted">{dateOf(s.signal_date)}</span>
                    <span className="pattern-outcome muted">{(PATTERN_OUTCOME[s.outcome] || [s.outcome, s.outcome, s.outcome])[li]}</span>
                  </button>
                  <p className="pattern-record">
                    {t("На UZSE цель раньше стопа", "UZSEda maqsad stopdan oldin", "On UZSE, target before stop")}{" "}
                    <b>{pct(st.hit_rate_pct)}</b>{" "}
                    {t("случаев; случайный вход —", "holatda; tasodifiy kirish —", "of cases; a random entry —")}{" "}
                    <b>{pct(st.chance_pct)}</b>
                    <span className={`pattern-verdict ${verdict}`}>
                      {verdict === "above" ? t("лучше случайного", "tasodifiydan yaxshiroq", "better than chance")
                        : verdict === "below" ? t("хуже случайного", "tasodifiydan yomonroq", "worse than chance")
                          : t("не отличается от случайного", "tasodifiydan farq qilmaydi", "no different from chance")}
                    </span>
                    <span className="muted"> · n={st.decided ?? 0}</span>
                  </p>
                </li>
              );
            })}
          </ul>
          {bt && (
            <div className="pattern-backtest" data-testid="pattern-backtest">
              <strong>{t("Проверка на истории этой бумаги", "Bu qog'oz tarixida sinov", "Tested on this security's history")}</strong>
              <p className="muted">
                {t(`Покупка по каждому бычьему сигналу, по одной сделке, вход на следующей сессии, выход по цели, стопу или через ${data.backtest.horizon} сессий; комиссия ${num(data.backtest.fee_bps / 100, 2)}% и проскальзывание ${num(data.backtest.slippage_bps / 100, 2)}% за сторону.`,
                   `Har bir buqa signalida xarid, bitta bitim, keyingi sessiyada kirish, maqsad, stop yoki ${data.backtest.horizon} sessiyadan keyin chiqish; komissiya ${num(data.backtest.fee_bps / 100, 2)}% va sirpanish ${num(data.backtest.slippage_bps / 100, 2)}% har tomonga.`,
                   `A buy on every bullish signal, one trade at a time, entry next session, exit at target, stop or after ${data.backtest.horizon} sessions; fee ${num(data.backtest.fee_bps / 100, 2)}% and slippage ${num(data.backtest.slippage_bps / 100, 2)}% per side.`)}
              </p>
              <dl>
                <div><dt>{t("Сделок", "Bitimlar", "Trades")}</dt><dd>{num(bt.trades)}</dd></div>
                <div><dt>{t("Прибыльных", "Foydali", "Profitable")}</dt><dd>{pct(bt.win_rate_pct)}</dd></div>
                <div><dt>{t("Доходность", "Daromad", "Return")}</dt><dd className={bt.total_return_pct >= 0 ? "pos" : "neg"}>{pct(bt.total_return_pct, 1)}</dd></div>
                <div><dt>{t("Макс. просадка", "Maks. pasayish", "Max drawdown")}</dt><dd>{pct(bt.max_drawdown_pct, 1)}</dd></div>
                <div><dt>{t("Шарп", "Sharp", "Sharpe")}</dt><dd>{num(bt.sharpe, 2)}</dd></div>
              </dl>
            </div>
          )}
        </>
      )}
      {families.cycle && cyc && (
        <div className="pattern-cycle" data-testid="pattern-cycle">
          <strong>{t("Цикличность", "Tsikllilik", "Cycles")}</strong>
          {cyc.status !== "AVAILABLE" ? (
            <p className="muted">{t("Слишком короткая история для поиска цикла.", "Tsikl uchun tarix juda qisqa.", "Too little history to look for a cycle.")}</p>
          ) : (
            <p>
              {t(`Самый сильный период — около ${num(cyc.period_sessions)} сессий (размах ±${num(cyc.amplitude_pct, 1)}%). `,
                 `Eng kuchli davr — taxminan ${num(cyc.period_sessions)} sessiya (±${num(cyc.amplitude_pct, 1)}%). `,
                 `The strongest period is about ${num(cyc.period_sessions)} sessions (±${num(cyc.amplitude_pct, 1)}%). `)}
              {cyc.significant ? (
                <span data-verdict="significant">
                  {t(`Случайное блуждание даёт такой же пик лишь в ${pct(cyc.p_value * 100)} случаев — цикл статистически заметен. Следующий гребень — через ~${num(cyc.next_peak_in)} сессий, впадина — через ~${num(cyc.next_trough_in)}.`,
                     `Tasodifiy yurish bunday cho'qqini faqat ${pct(cyc.p_value * 100)} holatda beradi — tsikl sezilarli. Keyingi cho'qqi ~${num(cyc.next_peak_in)} sessiyadan, chuqurlik ~${num(cyc.next_trough_in)} dan keyin.`,
                     `A random walk produces as strong a peak only ${pct(cyc.p_value * 100)} of the time — the cycle is statistically visible. Next crest in ~${num(cyc.next_peak_in)} sessions, trough in ~${num(cyc.next_trough_in)}.`)}
                </span>
              ) : (
                <span data-verdict="noise">
                  {t(`Но случайное блуждание с теми же дневными движениями даёт такой же пик в ${pct(cyc.p_value * 100)} случаев — это не цикл, а шум. Прогноз по нему не строится.`,
                     `Ammo xuddi shu kunlik harakatlar bilan tasodifiy yurish bunday cho'qqini ${pct(cyc.p_value * 100)} holatda beradi — bu tsikl emas, shovqin. Unga prognoz qurilmaydi.`,
                     `But a random walk with the same daily moves produces as strong a peak ${pct(cyc.p_value * 100)} of the time — this is noise, not a cycle. No forecast is drawn from it.`)}
                </span>
              )}
            </p>
          )}
        </div>
      )}
      <p className="pattern-caption muted">
        {t(`Статистика по ${meta.securities ?? "—"} ликвидным акциям UZSE за всю историю при выбранной чувствительности: вход по закрытию следующей сессии, комиссия и проскальзывание учтены, горизонт 20 сессий; «лучше/хуже случайного» — только при разнице больше трёх стандартных ошибок. Это описание прошлого, не инвестиционная рекомендация.`,
           `UZSEning ${meta.securities ?? "—"} ta likvid aksiyasi bo'yicha tanlangan sezgirlikdagi butun tarix statistikasi: keyingi sessiya yopilishida kirish, komissiya va sirpanish hisobga olingan, ufq 20 sessiya; «tasodifiydan yaxshi/yomon» — faqat farq uch standart xatodan katta bo'lganda. Bu o'tmish tavsifi, investitsiya tavsiyasi emas.`,
           `Statistics over ${meta.securities ?? "—"} liquid UZSE shares, full history, at the chosen sensitivity: entry at the next session's close, fee and slippage included, 20-session horizon; «better/worse than chance» only beyond three standard errors. A description of the past, not investment advice.`)}
      </p>
    </section>
  );
}

export { PatternList, PatternMenuItems, applyPatternOverlay, patternKey, patternOverlay, usePatterns };
