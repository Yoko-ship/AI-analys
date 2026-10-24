import React from "react";
import { convertSeries, periodEnd } from "../../lib/terminalCurrency.js";
import { CompanyFinancialsTab } from "./Financials.jsx";
import { financialsUrl } from '../../lib/financialHistoryRequest.js';

// The Финансы tab together with the data behind it. The company page and the
// catalog terminal (PL / BS / RAT) both open it, so it owns its own requests:
// one implementation of "which series, which standard, which scope" serves
// both, and the two cannot drift apart.
//
// IFRS and NSBU are separate accounting contours, so a change of standard or
// scope drops the cached series; keeping NSBU rows while the header says IFRS
// would be worse than a moment of loading. The quarterly series and the splits
// register are their own requests, made only when that view is opened.

function useControllable(value, onChange, initial) {
  const [own, setOwn] = React.useState(initial);
  return value === undefined ? [own, setOwn] : [value, onChange || (() => {})];
}

function IssuerFinancials({ ticker, lang, ratios, standard: standardProp, onStandardChange,
  scope: scopeProp, onScopeChange, freq: freqProp, onFreqChange, initialFreq = "annual", section, onSectionChange, onLoad, fromYear = null, showContextControls = true }) {
  const [standard, setStandard] = useControllable(standardProp, onStandardChange, "NSBU");
  const [freq, setFreq] = useControllable(freqProp, onFreqChange, initialFreq);
  const [scope, setScope] = useControllable(scopeProp, onScopeChange, "");
  const [currency, setCurrency] = React.useState("UZS");
  const [fx, setFx] = React.useState({});
  const [fxLoading, setFxLoading] = React.useState(false);
  const [annual, setAnnual] = React.useState(null);
  const [quarterly, setQuarterly] = React.useState(null);
  const [splits, setSplits] = React.useState(null);
  const [ownRatios, setOwnRatios] = React.useState(null);
  const onLoadRef = React.useRef(onLoad);
  onLoadRef.current = onLoad;

  React.useEffect(() => {
    setAnnual(null);
    setQuarterly(null);
    setSplits(null);
  }, [ticker, standard, scope]);

  const wantQuarterly = freq === "quarterly";
  const series = wantQuarterly ? quarterly : annual;

  React.useEffect(() => {
    if (!ticker || series !== null) return undefined;
    let alive = true;
    const setter = wantQuarterly ? setQuarterly : setAnnual;
    const startedAt = performance.now();
    fetch(financialsUrl(ticker, standard, scope, wantQuarterly))
      .then(async (r) => {
        const d = await r.json().catch(() => null);
        if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { errorId: d?.error_id });
        return d;
      })
      .then((d) => {
        if (!alive) return;
        setter(d?.ok ? d : { periods: [], series: {} });
        onLoadRef.current?.({ startedAt });
      })
      .catch((error) => {
        if (!alive) return;
        setter({ periods: [], series: {} });
        onLoadRef.current?.({ startedAt, error: error.message, errorId: error.errorId });
      });
    return () => { alive = false; };
  }, [ticker, standard, scope, wantQuarterly, series]);

  // The splits register backs the «Сплиты» sub-tab. An error resolves to [],
  // which the table renders as the honest «не зафиксировано».
  React.useEffect(() => {
    if (!ticker || splits !== null) return undefined;
    let alive = true;
    fetch(`/api/company/${encodeURIComponent(ticker)}/splits`)
      .then((r) => r.json())
      .then((d) => { if (alive) setSplits(d.ok ? (d.items || []) : []); })
      .catch(() => { if (alive) setSplits([]); });
    return () => { alive = false; };
  }, [ticker, splits]);

  // The ratios fallback comes from the reports cache. The company page already
  // holds it and passes it in; elsewhere it is fetched here.
  React.useEffect(() => {
    setOwnRatios(null);
    if (!ticker || ratios !== undefined) return undefined;
    let alive = true;
    fetch(`/api/catalog/company/${encodeURIComponent(ticker)}/reports`)
      .then((r) => r.json())
      .then((d) => { if (alive) setOwnRatios(d.ok ? (d.ratios || {}) : {}); })
      .catch(() => { if (alive) setOwnRatios({}); });
    return () => { alive = false; };
  }, [ticker, ratios]);

  // A host may show only recent history (the terminal opens at 2020); the
  // older periods stay loaded and come back when the floor is lifted.
  const recent = (period) => !fromYear || Number(String(period).slice(0, 4)) >= fromYear;
  const periods = (series?.periods || []).filter(recent);
  const dataGaps = (series?.data_gaps || []).filter((gap) => recent(gap.period));

  const periodKey = periods.join(",");
  React.useEffect(() => {
    if (currency !== "USD") return undefined;
    const controller = new AbortController();
    setFx({}); setFxLoading(true);
    const keys = periodKey.split(",").filter(Boolean);
    const results = {};
    async function worker() {
      while (keys.length && !controller.signal.aborted) {
        const p = keys.shift(), day = periodEnd(p);
        if (!day) continue;
        try {
          const response = await fetch(`/api/currency/rates?as_of=${day}`, {signal:controller.signal});
          if (!response.ok) continue;
          const data = await response.json();
          const rate = data.rates?.find(r=>r.ccy === "USD");
          if (data.as_of === day && rate?.effective_date <= day && rate?.per_unit > 0) results[p] = rate;
        } catch { /* A missing historic rate stays missing. */ }
      }
    }
    Promise.all(Array.from({length:4},worker)).then(()=>{
      if (!controller.signal.aborted) {setFx(results);setFxLoading(false);}
    });
    return ()=>controller.abort();
  },[currency,periodKey]);
  const t=(ru,uz,en)=>lang === "uz" ? uz : lang === "en" ? en : ru;
  return (
    <div data-currency={currency} data-terminal-ticker={ticker} data-terminal-standard={standard} data-terminal-scope={scope||series?.scope||"separate"} data-terminal-function={section==="balance"?"BS":"PL"}>
    <div className="terminal-controls"><label>{t("Валюта","Valyuta","Currency")}<select value={currency} onChange={e=>setCurrency(e.target.value)}><option>UZS</option><option>USD</option></select></label></div>
    {currency === "USD" && <details className="terminal-fx-rates" open><summary>{t("Курсы ЦБ на конец каждого периода","Har davr oxiridagi MB kursi","CBU rates at each period end")}</summary>
      {fxLoading ? <p role="status">{t("Загрузка курсов…","Kurslar yuklanmoqda…","Loading rates…")}</p> : <ul>{periods.map(p=><li key={p}>{p} · {periodEnd(p)} · {fx[p] ? `1 USD = ${fx[p].per_unit} UZS (${fx[p].effective_date})` : t("Курс отсутствует — суммы скрыты","Kurs yo‘q — summalar yashirildi","Rate missing — amounts unavailable")} · <a href={`https://cbu.uz/ru/arkhiv-kursov-valyut/json/all/${periodEnd(p)}/`} target="_blank" rel="noreferrer">CBU</a></li>)}</ul>}
    </details>}
    <CompanyFinancialsTab ticker={ticker} ratios={ratios ?? ownRatios ?? {}} lang={lang}
      key={`${ticker}:${standard}:${scope}:${freq}`}
      standard={standard} onStandardChange={showContextControls ? setStandard : undefined}
      scope={scope || series?.scope}
      onScopeChange={showContextControls ? setScope : undefined}
      series={convertSeries(series?.series || {}, fx, currency)}
      organizationType={series?.organization_type}
      currency={currency}
      periods={periods}
      dataGaps={dataGaps}
      periodBasis={series?.period_basis}
      loading={series === null}
      freq={freq} onFreqChange={setFreq} splits={splits}
      section={section} onSectionChange={onSectionChange} />
    </div>
  );
}

export { IssuerFinancials };
