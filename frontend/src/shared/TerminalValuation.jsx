import React from "react";
import { words } from "./TerminalTables.jsx";
import { ValuationDashboard } from "./ValuationDashboard.jsx";
import { reportScreenLoad } from "../lib/terminalJournal.js";

export function TerminalValuation(props) {
  return props.editable ? <ValuationScenario {...props}/> : <AutomaticValuation {...props}/>;
}

function AutomaticValuation({apiFetch,lang="ru",ticker,form="NSBU",scope="separate"}) {
  const [load,setLoad]=React.useState(null);
  const [attempt,setAttempt]=React.useState(0);
  const key=`${ticker}:${form}:${scope}:${attempt}`;
  React.useEffect(()=>{
    let alive=true;
    const started=performance.now();
    const read=async()=>{
      try {
        const query=new URLSearchParams({form,scope});
        const response=await apiFetch(`/api/admin/terminal/valuation/${encodeURIComponent(ticker)}?${query}`);
        if(!response.ok)throw new Error(String(response.status));
        const data=await response.json();
        if(alive){setLoad({key,data});reportScreenLoad({ticker,func:'FV',form,startedAt:started});}
      } catch(error) {
        if(alive){setLoad({key,error:error.message});reportScreenLoad({ticker,func:'FV',form,startedAt:started,error:error.message});}
      }
    };
    read();
    return()=>{alive=false;};
  },[apiFetch,ticker,form,scope,key]);
  const current=load?.key===key?load:null;
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  return <section className="terminal-valuation" aria-label={`FV · ${ticker}`}>
    {!current&&<p role="status">{t('Расчёт оценки…','Baho hisoblanmoqda…','Calculating valuation…')}</p>}
    {current?.error&&<div role="alert" className="terminal-warning">
      <p>{['401','403'].includes(current.error)?t('Войдите как администратор для просмотра оценки.','Bahoni ko‘rish uchun administrator sifatida kiring.','Sign in as an administrator to view the valuation.'):t('Не удалось загрузить оценку. Повторите попытку.','Bahoni yuklab bo‘lmadi. Qayta urinib ko‘ring.','Could not load the valuation. Please retry.')}</p>
      <button type="button" className="ghost-btn" onClick={()=>setAttempt(n=>n+1)}>{t('Повторить','Qayta urinish','Retry')}</button>
    </div>}
    {current?.data&&<ValuationDashboard result={current.data} lang={lang}/>}
  </section>;
}

function ValuationScenario({apiFetch,lang="ru",ticker:initialTicker="",form="NSBU",scope="separate"}) {
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
  return <section className="terminal-valuation"><h3>FV · {t('Оценка по модели','Model bahosi','Model valuation')}</h3>
    <p className="terminal-warning">{t('Расчёт по модели, не рекомендация. Только для администраторов до проверки на 10 эмитентах.','Model hisobi, tavsiya emas. 10 emitent tekshirilguncha faqat administratorlar uchun.','Model calculation, not a recommendation. Administrators only pending validation on ten issuers.')}</p>
    <p className="muted">{configuration?.as_of} · {configuration?.version} · {t('Изменения ниже — сценарий. Постоянные параметры редактируются во вкладке «Шаблоны» через версионный черновик.','Quyidagi o‘zgarishlar ssenariy. Doimiy parametrlar «Andozalar»da.','Changes below are a scenario. Persist parameters as a versioned draft in Templates.')}</p>
    <div className="terminal-controls"><label>{t('Тикер','Tiker','Ticker')}<input value={ticker} maxLength={16} onChange={e=>{setTicker(e.target.value.toUpperCase());setResult(null);}}/></label>
      {[["key_rate",t('Ставка ЦБ, %','MB stavkasi, %','Policy rate, %')],["default_spread",t('Дефолтный спред, %','Defolt spredi, %','Default spread, %')],["equity_premium",t('Премия за риск акций, %','Aksiyalar xatar mukofoti, %','Equity risk premium, %')],["growth",t('Рост g, %','O‘sish g, %','Growth g, %')]].map(([key,name])=><label key={key}>{name}<input type="number" step="0.01" value={params[key]} onChange={e=>{setParams(p=>({...p,[key]:e.target.value}));setResult(null);}}/></label>)}
      <button className="primary-btn" disabled={busy||!ticker||Object.values(params).some(v=>v==='')} onClick={run}>{t('Рассчитать','Hisoblash','Calculate')}</button>
    </div><p className="muted">r = {params.key_rate} − {params.default_spread} + {params.equity_premium}; {t('диапазон чувствительности r ±1 п.п.; аналоги — межквартильный диапазон.','r ±1 foiz punkti; analoglar — kvartillar oralig‘i.','r sensitivity ±1 percentage point; peers use the interquartile range.')}</p>
    {error&&<p role="alert">{error}</p>}{busy&&<p role="status">{t('Расчёт…','Hisoblanmoqda…','Calculating…')}</p>}
    {result&&<ValuationDashboard result={result} lang={lang}/>}
  </section>;
}
