import React from "react";
import { TerminalRules } from "./TerminalRules.jsx";
import { TerminalValuation } from "../shared/TerminalValuation.jsx";
import "../shared/terminalWorkspace.css";
import { safeHref } from "../lib/safeHref.js";
import { words, useTableExports } from "../shared/TerminalTables.jsx";

export function TerminalAdmin({apiFetch,language="ru"}) {
  const lang=language;
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const [tab,setTab]=React.useState("summary");
  const [days,setDays]=React.useState(7);
  const [form,setForm]=React.useState("NSBU");
  const [filters,setFilters]=React.useState({});
  const [offset,setOffset]=React.useState(0);
  const [data,setData]=React.useState(null);
  const [error,setError]=React.useState("");
  const [refresh,setRefresh]=React.useState(0);
  const [exporting,setExporting]=React.useState(false);
  const root=React.useRef(null);
  useTableExports(root,{function:"ADM",standard:form});
  const params=new URLSearchParams();
  for(const [key,value] of Object.entries(filters))if(value)params.set(key,value);
  if(!filters.level){params.append("level","critical");params.append("level","warning");}
  const query=params.toString();
  const url=["templates","fv"].includes(tab)?"/api/admin/terminal/templates":tab==="coverage"?`/api/admin/terminal/coverage?form=${form}`:tab==="journal"?`/api/admin/terminal/events?${query}&offset=${offset}`:`/api/admin/terminal/dashboard?days=${days}`;
  React.useEffect(()=>{
    let alive=true;setData(null);setError("");
    apiFetch(url).then(async r=>{if(!r.ok)throw new Error(r.status===401||r.status===403?t("Нужны права администратора","Administrator huquqi kerak","Administrator access required"):`HTTP ${r.status}`);return r.json();})
      .then(d=>{if(alive)setData(d);}).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;};
  // Translation is a pure lookup; language is the dependency.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[url,apiFetch,refresh,lang]);
  const update=(key,value)=>{setFilters(f=>({...f,[key]:value}));setOffset(0);};
  const exportJournal=async()=>{
    setExporting(true);try{const response=await apiFetch(`/api/admin/terminal/export?${query}`);if(!response.ok)throw new Error(`HTTP ${response.status}`);const blob=await response.blob();const u=URL.createObjectURL(blob);const a=document.createElement("a");a.href=u;a.download="terminal-journal.csv";a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}catch(e){setError(e.message);}finally{setExporting(false);}
  };
  const fmt=n=>n==null?"—":Number(n).toLocaleString(lang==="en"?"en-US":"ru-RU",{maximumFractionDigits:2});
  const summary=data?.summary||{};
  const metrics=[
    [t("Новые значения в карантине","Yangi karantin qiymatlari","New quarantines"),summary.quarantine,"0",summary.quarantine>0],
    [t("Конфликты вердикта","Xulosa ziddiyatlari","Verdict conflicts"),summary.verdict_conflicts,"0",summary.verdict_conflicts>0],
    [t("Опубликовано анализов за сутки","Kunlik tahlillar","Analyses published in 24h"),summary.ai_published,"↑",summary.ai_published_change<0],
    [t("Изменение публикаций за сутки","Nashrlar o‘zgarishi","Change in daily publications"),summary.ai_published_change,"≥ 0",summary.ai_published_change<0],
    [t("Ошибки экранов за час, %","Soatlik xatolar, %","Screen errors in last hour, %"),summary.hour_error_pct,"≤ 1%",summary.hour_error_pct>1],
    [t("Медленные экраны, %","Sekin ekranlar, %","Slow screens, %"),summary.slow_pct,"< 5% / > 10%",summary.slow_pct>10],
  ];
  return <section className="panel terminal-market-screen" ref={root}>
    <header className="terminal-section-head"><h2>ADM · {t("Терминал","Terminal","Terminal")}</h2><button className="ghost-btn" onClick={()=>setRefresh(n=>n+1)}>{t("Обновить","Yangilash","Refresh")}</button></header>
    <div className="terminal-admin-tabs" role="group" aria-label={t("Разделы терминала","Terminal bo‘limlari","Terminal sections")}>
      {[["templates",t("Шаблоны","Andozalar","Templates")],["fv","FV"],["summary",t("Сводка","Xulosa","Summary")],["coverage",t("Покрытие","Qamrov","Coverage")],["journal",t("Ошибки и журнал","Xatolar va jurnal","Errors and journal")],["usage",t("Использование","Foydalanish","Usage")]].map(([key,name])=><button key={key} className={tab===key?"primary-btn":"ghost-btn"} aria-pressed={tab===key} onClick={()=>setTab(key)}>{name}</button>)}
    </div>
    {tab==="usage"&&<div className="terminal-controls"><label>{t("Дней","Kunlar","Days")}<select value={days} onChange={e=>setDays(Number(e.target.value))}><option value="7">7</option><option value="30">30</option></select></label></div>}
    {tab==="coverage"&&<><div className="terminal-controls"><select aria-label={t("Стандарт","Standart","Standard")} value={form} onChange={e=>setForm(e.target.value)}><option>NSBU</option><option>MSFO</option></select></div><p className="muted">{t("✓ — загружено; ↳ — из прошлого года; ! — пропуск; ? — источник недоступен. Нажмите ячейку, чтобы открыть журнал.","✓ — yuklangan; ↳ — oldingi yil; ! — bo‘sh; ? — manba yo‘q.","✓ loaded; ↳ comparative column; ! gap; ? source unavailable. Click a cell for its journal.")}</p></>}
    {tab==="journal"&&<><div className="terminal-controls">{[["since",t("С даты","Boshlanish","From"),"date"],["until",t("По дату","Tugash","Until"),"date"],["ticker",t("Тикер","Tiker","Ticker"),"text"],["event",t("Событие","Hodisa","Event"),"text"],["period",t("Период","Davr","Period"),"text"]].map(([key,name,type])=><label key={key}>{name}<input type={type} value={filters[key]||""} onChange={e=>update(key,e.target.value)}/></label>)}
      <label>{t("Уровень","Daraja","Level")}<select value={filters.level||""} onChange={e=>update("level",e.target.value)}><option value="">{t("Критично + Внимание","Kritik + Ogohlantirish","Critical + Warning")}</option><option value="critical">{t("Критично","Kritik","Critical")}</option><option value="warning">{t("Внимание","Ogohlantirish","Warning")}</option><option value="info">{t("Инфо","Axborot","Info")}</option></select></label>
      <button className="ghost-btn" disabled={exporting} onClick={exportJournal}>{t("Выгрузить весь журнал CSV","Jurnalni CSV yuklash","Export full journal CSV")}</button></div></>}
    {error?<p role="alert">{error}</p>:!data?<p role="status">{t("Загрузка…","Yuklanmoqda…","Loading…")}</p>:<>
      {tab==="templates"&&<TerminalRules apiFetch={apiFetch} lang={lang} data={data}/>}
      {tab==="fv"&&<TerminalValuation apiFetch={apiFetch} lang={lang}/>}
      {tab==="summary"&&<><p className="muted">{t("За последние 24 часа; время Ташкента. Без действий сотрудников. API-ошибки доступны в журнале отдельно от ошибок экранов.","Oxirgi 24 soat, Toshkent vaqti.","Last 24 hours, Tashkent time. Staff activity excluded. API and screen errors remain distinct.")}</p><table className="terminal-table"><thead><tr><th>{t("Показатель","Ko‘rsatkich","Metric")}</th><th>{t("Сейчас","Hozir","Current")}</th><th>{t("Норма / тревога","Me’yor / ogohlantirish","Norm / alarm")}</th></tr></thead><tbody>{metrics.map(([name,value,norm,alarm])=><tr key={name}><th>{name}</th><td>{alarm?"⚑ ":""}{fmt(value)}</td><td>{norm}</td></tr>)}</tbody></table></>}
      {tab==="coverage"&&<><p className="muted">{t("✓ загружено · ↳ сравнительная колонка · ! ошибка · — не опубликовано в реестре · ? источник недоступен. Покрытие — среди опубликованных периодов.","✓ yuklandi · ↳ taqqoslama · ! xato · — e’lon qilinmagan · ? manba yo‘q.","✓ loaded · ↳ comparative · ! gap · — not published in registry · ? unavailable. Coverage counts published periods.")}</p><p>{t("Покрытие годовых","Yillik qamrov","Annual coverage")}: {fmt(data.annual_coverage_pct)}% · {t("Порог: 95%","Chegara: 95%","Threshold: 95%")}</p><div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{t("Эмитент","Emitent","Issuer")}</th>{data.periods?.map(p=><th key={p}>{p}</th>)}</tr></thead><tbody>{data.rows?.map(r=><tr key={r.ticker}><th title={r.name}>{r.ticker}</th>{data.periods?.map(p=><td key={p}><button className={`terminal-coverage-cell ${r.cells[p]}`} title={`${r.ticker} ${p}: ${r.cells[p]}`} onClick={()=>{setFilters({ticker:r.ticker,period:p,standard:form,level:r.cells[p]==="loaded"||r.cells[p]==="backfill"?"info":""});setOffset(0);setTab("journal");}}>{{loaded:"✓",backfill:"↳",gap:"!",unavailable:"?",unpublished:"—"}[r.cells[p]]||"—"}</button></td>)}</tr>)}</tbody></table></div></>}
      {tab==="journal"&&<><div className="terminal-table-wrap"><table className="terminal-table" data-own-export><thead><tr>{["UTC+5",t("Уровень","Daraja","Level"),t("Событие","Hodisa","Event"),t("Тикер / период","Tiker / davr","Ticker / period"),"ms","error_id",t("Описание / источник","Tavsif / manba","Description / source")].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{data.items?.map(r=><tr key={r.id}><td>{r.ts}</td><td>{r.level_label}</td><td>{r.event}</td><td>{r.ticker} {r.standard} {r.period}</td><td>{fmt(r.duration_ms)}</td><td>{r.error_id||"—"}</td><td>{r.message}{r.source_url&&<a href={safeHref(r.source_url)} target="_blank" rel="noreferrer"> ↗</a>}</td></tr>)}</tbody></table></div><div className="terminal-controls"><button className="ghost-btn" disabled={!offset} onClick={()=>setOffset(n=>Math.max(0,n-100))}>←</button><span>{offset}–{offset+(data.items?.length||0)} / {data.total}</span><button className="ghost-btn" disabled={offset+100>=data.total} onClick={()=>setOffset(n=>n+100)}>→</button></div></>}
      {tab==="usage"&&<><p>{t("Команды","Buyruqlar","Commands")}: {data.usage?.commands} · {t("Неизвестные","Noma’lum","Unknown")}: {data.usage?.unknown} ({fmt(data.usage?.unknown_pct)}%)</p><div className="terminal-panel-grid">{["functions","tickers"].map(key=><table key={key} className="terminal-table"><caption>{key==="functions"?t("Функции","Funksiyalar","Functions"):t("Эмитенты","Emitentlar","Issuers")}</caption><tbody>{data.usage?.[key]?.map(r=><tr key={r.name}><th>{r.name}</th><td>{r.count}</td></tr>)}</tbody></table>)}</div></>}
    </>}
  </section>;
}
