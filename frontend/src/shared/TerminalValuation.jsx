import React from "react";
import { words } from "./TerminalTables.jsx";

export function TerminalValuation({apiFetch,lang="ru",ticker:initialTicker="",form="NSBU",scope="separate"}) {
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const [ticker,setTicker]=React.useState(initialTicker);
  const [params,setParams]=React.useState({key_rate:14,default_spread:3.06,equity_premium:8.89,growth:9.8});
  const [configuration,setConfiguration]=React.useState(null);
  const [result,setResult]=React.useState(null);
  const [error,setError]=React.useState("");
  const [busy,setBusy]=React.useState(false);
  React.useEffect(()=>setTicker(initialTicker),[initialTicker]);
  React.useEffect(()=>{let alive=true;apiFetch('/api/admin/terminal/templates').then(async r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json();}).then(d=>{if(alive&&d.valuation){setParams(d.valuation.values);setConfiguration(d.valuation);}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[apiFetch]);
  const run=async()=>{setBusy(true);setError('');setResult(null);try{const q=new URLSearchParams({...params,form,scope});const r=await apiFetch(`/api/admin/terminal/valuation/${encodeURIComponent(ticker)}?${q}`);if(!r.ok)throw new Error(`HTTP ${r.status}`);setResult(await r.json());}catch(e){setError(e.message);}finally{setBusy(false);}};
  const fmt=v=>v==null?'—':Number(v).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const names={peers_pb:t('Аналоги · P/B','Analoglar · P/B','Peers · P/B'),peers_pe:t('Аналоги · P/E','Analoglar · P/E','Peers · P/E'),justified_pb:t('Обоснованный P/B','Asoslangan P/B','Justified P/B'),gordon:t('Гордон','Gordon','Gordon')};
  return <section className="terminal-valuation"><h3>FV · {t('Оценка по модели','Model bahosi','Model valuation')}</h3>
    <p className="terminal-warning">{t('Расчёт по модели, не рекомендация. Только для администраторов до проверки на 10 эмитентах.','Model hisobi, tavsiya emas. 10 emitent tekshirilguncha faqat administratorlar uchun.','Model calculation, not a recommendation. Administrators only pending validation on ten issuers.')}</p>
    <p className="muted">{configuration?.as_of} · {configuration?.version} · {t('Изменения ниже — сценарий. Постоянные параметры редактируются во вкладке «Шаблоны» через версионный черновик.','Quyidagi o‘zgarishlar ssenariy. Doimiy parametrlar «Andozalar»da.','Changes below are a scenario. Persist parameters as a versioned draft in Templates.')}</p>
    <div className="terminal-controls"><label>{t('Тикер','Tiker','Ticker')}<input value={ticker} maxLength={16} onChange={e=>{setTicker(e.target.value.toUpperCase());setResult(null);}}/></label>
      {[["key_rate",t('Ставка ЦБ, %','MB stavkasi, %','Policy rate, %')],["default_spread",t('Дефолтный спред, %','Defolt spredi, %','Default spread, %')],["equity_premium",t('Премия за риск акций, %','Aksiyalar xatar mukofoti, %','Equity risk premium, %')],["growth",t('Рост g, %','O‘sish g, %','Growth g, %')]].map(([key,name])=><label key={key}>{name}<input type="number" step="0.01" value={params[key]} onChange={e=>{setParams(p=>({...p,[key]:e.target.value}));setResult(null);}}/></label>)}
      <button className="primary-btn" disabled={busy||!ticker||Object.values(params).some(v=>v==='')} onClick={run}>{t('Рассчитать','Hisoblash','Calculate')}</button>
    </div><p className="muted">r = {params.key_rate} − {params.default_spread} + {params.equity_premium}; {t('диапазон чувствительности r ±1 п.п.; аналоги — межквартильный диапазон.','r ±1 foiz punkti; analoglar — kvartillar oralig‘i.','r sensitivity ±1 percentage point; peers use the interquartile range.')}</p>
    {error&&<p role="alert">{error}</p>}{busy&&<p role="status">{t('Расчёт…','Hisoblanmoqda…','Calculating…')}</p>}
    {result&&<><p>{result.ticker} · {result.period} · {result.standard} · {result.scope} · r = {fmt(result.required_return)}%</p><div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{t('Метод','Usul','Method')}</th><th>{t('Диапазон','Oraliq','Range')}</th><th>{t('Оценка','Baho','Estimate')}</th><th>{t('Единица / причина','Birlik / sabab','Unit / reason')}</th></tr></thead><tbody>{Object.entries(result.models||{}).map(([key,m])=><tr key={key}><th>{names[key]||key}</th><td>{fmt(m.low)} – {fmt(m.high)}</td><td>{fmt(m.value)}</td><td>{m.reason||m.unit}</td></tr>)}</tbody></table></div></>}
  </section>;
}
