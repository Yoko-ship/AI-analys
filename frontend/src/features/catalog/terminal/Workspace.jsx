import { BankComparison } from './BankComparison.jsx';
import React from "react";
import { filterRows, normalizeLayout, profitSparkline } from "../../../lib/terminalWorkspace.js";
import { ISSUER_FUNCTIONS, functionLabel } from "../../../lib/terminalCommands.js";
import { reportScreenLoad } from "../../../lib/terminalJournal.js";
import { safeHref } from "../../../lib/safeHref.js";
import { IssuerFinancials, IssuerDividends } from "../../company/index.js";
import { NewsScreen, QualityScreen, useScreenData } from "./TerminalPanels.jsx";
import { words } from "../../../shared/TerminalTables.jsx";
import "../../../shared/terminalWorkspace.css";

const fmt = (n, lang, key) => n == null ? "—" : key === "pe" && n > 100 ? ">100" : Number(n).toLocaleString(lang === "en" ? "en-US" : "ru-RU",{maximumFractionDigits:2});
const labels = {net_profit:["Чистая прибыль","Sof foyda","Net profit"],net_revenue:["Выручка","Tushum","Revenue"],total_assets:["Активы","Aktivlar","Assets"],total_equity:["Капитал / NAV","Kapital / NAV","Equity / NAV"],total_liabilities:["Обязательства","Majburiyatlar","Liabilities"]};
const label = (key,lang) => words(lang,...(labels[key] || [key,key,key]));
function State({data,error,lang,children}) {
  if(error)return <p role="alert" className="terminal-empty">{words(lang,"Не удалось загрузить данные. Обновите экран.","Ma’lumotlar yuklanmadi. Yangilang.","Could not load data. Refresh this screen.")}</p>;
  if(!data)return <p role="status" className="terminal-empty">{words(lang,"Загрузка…","Yuklanmoqda…","Loading…")}</p>;
  return children;
}

export function ContextControls({form,scope,onForm,onScope,lang}) {
  return <div className="terminal-controls">
    <label>{words(lang,"Стандарт","Standart","Standard")}<select value={form} onChange={e=>onForm(e.target.value)}><option>NSBU</option><option>MSFO</option></select></label>
    {form==="MSFO"&&<label>{words(lang,"Периметр","Qamrov","Scope")}<select value={scope} onChange={e=>onScope(e.target.value)}><option value="separate">{words(lang,"Отдельная","Alohida","Separate")}</option><option value="consolidated">{words(lang,"Консолидированная","Konsolidatsiyalangan","Consolidated")}</option></select></label>}
  </div>;
}

const METRICS=[['roe','ROE, %'],['roa','ROA, %'],['pe','P/E'],['ep','E/P, %'],['pb','P/B'],['de','D/E'],['dy','DVD¹, %'],['cg5','CAGR 5Y, %'],['npl','NPL, %'],['nim','NIM, %'],['cost_of_risk','CoR, %']];
export function MarketScreen({mode,terminal,lang}) {
  const [year,setYear]=React.useState("");
  const [filters,setFilters]=React.useState({});
  const [sort,setSort]=React.useState({key:"roe",desc:true});
  const [metric,setMetric]=React.useState("roe");
  const [name,setName]=React.useState("");
  const [saved,setSaved]=React.useState(()=>{try{return JSON.parse(localStorage.getItem("uz_terminal_screens")||"{}");}catch{return {};}});
  const [notice,setNotice]=React.useState("");
  const {form,scope}=terminal;
  const {data,error}=useScreenData(`/api/terminal/screener?form=${form}&scope=${scope}${year?`&year=${year}`:""}`,{func:mode,form});
  const rows=filterRows(data?.rows||[],filters,data?.deposit_rate).sort((a,b)=>{
    if(a[sort.key]==null)return b[sort.key]==null?0:1;if(b[sort.key]==null)return -1;
    return (typeof a[sort.key]==="number" ? a[sort.key]-b[sort.key] : String(a[sort.key]).localeCompare(String(b[sort.key])))*(sort.desc?-1:1);
  });
  const update=(k,v)=>setFilters(f=>({...f,[k]:v}));
  return <section className="panel terminal-market-screen">
    <header className="terminal-section-head"><h2>{mode} · {functionLabel(mode,lang)}</h2><span className="muted">{rows.length} / {data?.rows?.length||0}</span></header>
    <p className="muted">{words(lang,"Годовая отчётность; P/E и P/B — текущая капитализация к последнему годовому отчёту. Пропуски не заменяются нулём.","Yillik hisobotlar; P/E va P/B oxirgi yil bo‘yicha. Bo‘sh qiymatlar nol emas.","Annual statements; P/E and P/B use current capitalisation and the latest annual. Missing values are not zero.")}</p>
    <p className="muted">{words(lang,"¹ Последнее положительное дивидендное решение за 366 дней / текущая цена. Это не сумма выплат за год. NPL — отдельная месячная дата ЦБ.","¹ Oxirgi 366 kundagi dividend qarori / joriy narx. NPL — MB oylik sanasi.","¹ Latest positive dividend decision within 366 days / current price; not annual payouts. NPL has its own monthly CBU date.")}</p>
    <div className="terminal-controls">
      <ContextControls form={form} scope={scope} onForm={terminal.setForm} onScope={terminal.setScope} lang={lang}/>
      <label>{words(lang,"Год","Yil","Year")}<select value={year} onChange={e=>setYear(e.target.value)}><option value="">{words(lang,"Последний","Oxirgi","Latest")}</option>{(data?.years||[]).map(y=><option key={y}>{y}</option>)}</select></label>
      <label>{words(lang,"Поиск","Qidiruv","Search")}<input type="search" value={filters.query||""} onChange={e=>update("query",e.target.value)}/></label>
      <label>{words(lang,"Тип","Tur","Type")}<select value={filters.kind||""} onChange={e=>update("kind",e.target.value)}><option value="">{words(lang,"Все","Barchasi","All")}</option>{[...new Set((data?.rows||[]).map(r=>r.kind))].map(k=><option key={k}>{k}</option>)}</select></label>
      {mode==="MON"&&<label>{words(lang,"Показатель","Ko‘rsatkich","Metric")}<select value={metric} onChange={e=>setMetric(e.target.value)}>{METRICS.filter(([k])=>["roe","dy","cg5"].includes(k)).map(([k,l])=><option key={k} value={k}>{l}</option>)}</select></label>}
    </div>
    {mode==="EQS"&&<>
      <div className="terminal-controls terminal-numeric-filters">{[["cbu_assets_share_pct_min",words(lang,"Доля активов ЦБ ≥","MB aktivlar ulushi ≥","CBU asset share ≥")],["roe_min","ROE ≥"],["pb_max","P/B ≤"],["pe_max","P/E ≤"],["dy_min","DVD ≥"],["de_max","D/E ≤"],["cg5_min","CAGR 5Y ≥"],["npl_max","NPL ≤"],["nim_min","NIM ≥"],["cost_of_risk_max","CoR ≤"]].map(([k,l])=><label key={k}>{l}<input type="number" step="any" value={filters[k]??""} onChange={e=>update(k,e.target.value)}/></label>)}</div>
      <div className="terminal-controls"><label className="terminal-check"><input type="checkbox" checked={!!filters.above_deposit} onChange={e=>update("above_deposit",e.target.checked)}/>{words(lang,"Дивиденд выше депозита","Dividend depozitdan yuqori","Dividend above deposit")}</label>
        <span className="muted">{data?.deposit_rate==null?words(lang,"Ставка ЦБ не загружена — сравнение недоступно.","Markaziy bank stavkasi yo‘q.","CBU deposit rate unavailable; no comparison can be made."):`${fmt(data.deposit_rate,lang)}% · ${data.deposit?.period||""}`}</span></div>
      <div className="terminal-controls"><label>{words(lang,"Шаблон","Andoza","Template")}<input maxLength={60} value={name} onChange={e=>setName(e.target.value)}/></label>
        <button className="ghost-btn" disabled={!name.trim()} onClick={()=>{const next={...saved,[name.trim()]:filters};try{localStorage.setItem("uz_terminal_screens",JSON.stringify(next));setSaved(next);setNotice(words(lang,"Сохранено в этом браузере","Shu brauzerda saqlandi","Saved in this browser"));}catch{setNotice(words(lang,"Не удалось сохранить","Saqlanmadi","Save failed"));}}}>{words(lang,"Сохранить фильтры","Filtrlarni saqlash","Save filters")}</button>
        <select aria-label={words(lang,"Сохранённые фильтры","Saqlangan filtrlar","Saved filters")} value="" onChange={e=>{setFilters(saved[e.target.value]||{});setName(e.target.value);}}><option value="">{words(lang,"Выбрать шаблон","Andozani tanlang","Load template")}</option>{Object.keys(saved).map(k=><option key={k}>{k}</option>)}</select>
        <button className="ghost-btn" onClick={()=>setFilters({})}>{words(lang,"Сбросить","Tozalash","Reset")}</button>{notice&&<span role="status">{notice}</span>}
      </div>
    </>}
    <State data={data} error={error} lang={lang}>{mode==="MON"?<div className="terminal-monitor">{rows.map(r=><button key={r.ticker} className={`terminal-monitor-tile ${r[metric]==null?"":r[metric]<0?"negative":r[metric]>=10?"positive":""}`} onClick={()=>terminal.go({ticker:r.ticker,func:"SUM"})}><strong>{r.ticker}</strong><span>{r.name}</span><b>{fmt(r[metric],lang)}{r[metric]!=null?"%":""}</b><small>{r.period||"—"} · {r.standard}</small><ProfitSparkline values={r.profit_history} lang={lang}/></button>)}</div>:
      <div className="terminal-table-wrap"><table className="terminal-table terminal-screener"><thead><tr>{[["ticker",words(lang,"Эмитент","Emitent","Issuer")],["period",words(lang,"Период","Davr","Period")],...METRICS].map(([k,l])=><th key={k} aria-sort={sort.key===k?(sort.desc?"descending":"ascending"):"none"}><button onClick={()=>setSort({key:k,desc:sort.key===k?!sort.desc:true})}>{l} {sort.key===k?(sort.desc?"↓":"↑"):""}</button></th>)}</tr></thead><tbody>{rows.map(r=><tr key={r.ticker}><td><button className="terminal-code" onClick={()=>terminal.go({ticker:r.ticker,func:"SUM"})}>{r.ticker}</button><small>{r.name}</small>{r.issues?.length>0&&<span title={r.issues.map(i=>i.code).join(", ")}> ⚑</span>}</td><td>{r.period||"—"}</td>{METRICS.map(([k])=><td key={k} title={k==="npl"?r.cbu?.npl?.date:k==="dy"?r.dividend?.decision?.decision_date:undefined}>{fmt(r[k],lang,k)}{k==="npl"&&r.cbu?.npl?.npl_flag?" ⚑":""}</td>)}</tr>)}</tbody></table></div>}
      {mode==="EQS"&&<BankComparison rows={rows} lang={lang} sectorSeries={data?.sector_series}/>}
      {!rows.length&&<p className="terminal-empty">{words(lang,"Нет эмитентов по этим фильтрам","Mos emitentlar yo‘q","No issuers match these filters")}</p>}
    </State>
  </section>;
}

export function Reconciliation({ticker,scope,lang}) {
  const {data,error}=useScreenData(`/api/terminal/issuer/${encodeURIComponent(ticker)}/reconciliation?scope=${scope}`,{ticker,func:"REC"});
  return <section className="terminal-reconciliation"><h3>REC · {functionLabel("REC",lang)}</h3><State data={data} error={error} lang={lang}>
    {data&&!data.same_scope&&<p className="terminal-warning">{words(lang,"Периметры различаются: разница не является ростом прибыли или ошибкой отчёта.","Qamrovlar turlicha: farq o‘sish yoki xato emas.","Reporting scopes differ: this difference is neither profit growth nor a filing error.")}</p>}
    <p className="muted">NSBU · {data?.nsbu_scope||"—"} ↔ MSFO · {data?.ifrs_scope||"—"} · UZS</p>
    <div className="terminal-table-wrap"><table className="terminal-table"><thead><tr>{[words(lang,"Показатель","Ko‘rsatkich","Metric"),words(lang,"Год","Yil","Year"),"NSBU, UZS","MSFO, UZS","Δ, UZS"].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{(data?.rows||[]).map(r=><tr key={`${r.field}:${r.period}`}><td>{label(r.field,lang)}</td><td>{r.period}</td>{[r.nsbu,r.ifrs,r.difference].map((n,i)=><td key={i}>{fmt(n,lang)}</td>)}</tr>)}</tbody></table></div>
    {!data?.rows?.length&&<p className="terminal-empty">{words(lang,"Нет сопоставимых опубликованных данных","Taqqoslanadigan ma’lumotlar yo‘q","No published figures to reconcile")}</p>}
  </State></section>;
}

export function AnalyticsScreen({ticker,form,scope,lang,summary=false}) {
  const {data,error}=useScreenData(`/api/terminal/issuer/${encodeURIComponent(ticker)}/analytics?form=${form}&scope=${scope}`,{ticker,form,func:summary?"SUM":"RAT"});
  const snap=data?.snapshot||{};
  return <State data={data} error={error} lang={lang}><div className="terminal-analytics">
    <p className="terminal-context">{snap.period||"—"} · {form} · {scope} · UZS</p>
    <p className="muted">{words(lang,"Шаблон","Andoza","Template")}: <strong>{data?.template?.selected_template}</strong> · {data?.template?.reason_code} · {data?.template?.rule_version}</p>
    <SectorMetrics ticker={ticker} form={form} scope={scope} lang={lang} summary={summary}/>
    <div className="terminal-table-wrap"><table className="terminal-table"><tbody>{(summary?[["net_profit",label("net_profit",lang)],["assets",label("total_assets",lang)],["equity",label("total_equity",lang)]]:METRICS.filter(([k])=>!["pe","pb","dy","npl"].includes(k))).map(([k,l])=><tr key={k}><th>{l}</th><td>{fmt(snap[k],lang)}</td></tr>)}</tbody></table></div>
    {!summary&&<>
      <BankContext data={data?.cbu} sector={data?.sector} lang={lang}/>
      <SectorContext data={data?.sector_series} kind={snap.kind} lang={lang}/>
      <h3>CAGR</h3><p className="muted">{words(lang,"Убыток или отсутствующая граница периода — без расчёта. Реальный рост и рост в USD требуют полного ряда инфляции и курсов ЦБ.","Zarar yoki yetishmagan davr bo‘lsa hisoblanmaydi.","Losses or missing endpoints are not calculated. Real and USD growth require complete inflation and CBU exchange rates.")}</p>
      <div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{words(lang,"Показатель","Ko‘rsatkich","Metric")}</th><th>{words(lang,"Период","Davr","Period")}</th><th>{words(lang,"Номинальный, %","Nominal, %","Nominal, %")}</th><th>{words(lang,"Реальный, %","Real, %","Real, %")}</th><th>USD, %</th></tr></thead><tbody>{(data?.growth||[]).map(r=><tr key={`${r.field}:${r.years}`}><td>{label(r.field,lang)}</td><td>{r.start}–{r.end}</td>{[r.nominal,r.real,r.usd].map((v,i)=><td key={i} title={r.reason||""}>{fmt(v,lang)}</td>)}</tr>)}</tbody></table></div>
      <QuarterHeatmap rows={data?.quarters?.rows||[]} lang={lang}/>
      <h3>{words(lang,"Кварталы · чистая прибыль","Choraklar · sof foyda","Quarters · net profit")}</h3>
      {data?.quarters?.reason&&<p className="terminal-warning">{words(lang,"Опубликован накопленный итог: его нельзя показывать как отдельный квартал.","Hisobot jamlangan; alohida chorak emas.","Published amounts are cumulative and cannot be shown as standalone quarters.")}</p>}
      <div className="terminal-table-wrap"><table className="terminal-table terminal-quarter-map"><thead><tr><th>{words(lang,"Квартал","Chorak","Quarter")}</th><th>UZS</th><th>YoY, %</th><th>LTM, UZS</th><th>{words(lang,"Доля в году, %","Yildagi ulush, %","Share of year, %")}</th><th>CAGR 3Y, %</th></tr></thead><tbody>{(data?.quarters?.rows||[]).map(r=><tr key={r.period}><th>{r.period}</th>{[r.value,r.yoy,r.ltm,r.seasonality,r.cg3].map((n,i)=><td key={i} className={i===1&&n!=null?(n<0?"negative":"positive"):""}>{fmt(n,lang)}</td>)}</tr>)}</tbody></table></div>
    </>}
  </div></State>;
}

export function PeersScreen({ticker,form,scope,lang,onOpen}) {
  const {data,error}=useScreenData(`/api/terminal/screener?form=${form}&scope=${scope}`,{ticker,form,func:"RV"});
  const base=(data?.rows||[]).find(r=>r.ticker===ticker);
  const rows=base?(data?.rows||[]).filter(r=>r.ticker!==ticker&&["kind","standard","scope","period"].every(k=>r[k]===base[k])):[];
  return <section><h3>RV · {functionLabel("RV",lang)}</h3><p className="muted">{words(lang,"Один тип, стандарт, периметр и год.","Bir tur, standart, qamrov va yil.","Same type, standard, scope and year.")} {base?.period} · {base?.kind}</p><State data={data} error={error} lang={lang}>
    <div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{words(lang,"Эмитент","Emitent","Issuer")}</th>{METRICS.map(([k,l])=><th key={k}>{l}</th>)}</tr></thead><tbody>{rows.map(r=><tr key={r.ticker}><td><button className="terminal-code" onClick={()=>onOpen?.(r.ticker)}>{r.ticker}</button></td>{METRICS.map(([k])=><td key={k} title={k==="npl"?r.cbu?.npl?.date:k==="dy"?r.dividend?.decision?.decision_date:undefined}>{fmt(r[k],lang,k)}{k==="npl"&&r.cbu?.npl?.npl_flag?" ⚑":""}</td>)}</tr>)}</tbody></table></div>
    <BankComparison rows={base?[base,...rows]:rows} lang={lang} sectorSeries={data?.sector_series}/>
    {!rows.length&&<p className="terminal-empty">{words(lang,"Сопоставимые эмитенты не найдены","Mos emitentlar topilmadi","No comparable issuers found")}</p>}
  </State></section>;
}

function FilingsScreen({ticker,lang}) {
  const {data,error}=useScreenData(`/api/catalog/index/${encodeURIComponent(ticker)}`,{ticker,func:"CF"});
  const reports=Object.entries(data?.availability||{}).flatMap(([form,groups])=>Object.values(groups||{}).flat().map(r=>({...r,form})));
  return <State data={data} error={error} lang={lang}><table className="terminal-table"><thead><tr><th>{words(lang,"Период","Davr","Period")}</th><th>{words(lang,"Стандарт","Standart","Standard")}</th><th>{words(lang,"Источник","Manba","Source")}</th></tr></thead><tbody>{reports.map((r,i)=><tr key={i}><td>{r.year||words(lang,"Год не указан","Yil yo‘q","Year missing")}{r.quarter?` Q${r.quarter}`:""}</td><td>{r.form}</td><td>{[r.excel_url,r.pdf_url].filter(Boolean).map((url,i)=><a key={url} href={safeHref(url)} target="_blank" rel="noreferrer">{i?"PDF":"Источник"} </a>)}</td></tr>)}</tbody></table></State>;
}

export function PanelScreen({panel,onChange,lang,onOpen}) {
  const {ticker,func,form,scope}=panel;
  if(["PL","BS"].includes(func))return <IssuerFinancials ticker={ticker} lang={lang} standard={form} scope={scope} onScopeChange={v=>onChange({...panel,scope:v})} onStandardChange={v=>onChange({...panel,form:v,scope:"separate"})} section={func==="PL"?"income":"balance"} fromYear={2020} onLoad={load=>reportScreenLoad({ticker,func,form,...load})}/>;
  if(func==="RAT"||func==="SUM")return <AnalyticsScreen {...panel} lang={lang} summary={func==="SUM"}/>;
  if(func==="REC")return <Reconciliation {...panel} lang={lang}/>;
  if(func==="RV")return <PeersScreen {...panel} lang={lang} onOpen={onOpen}/>;
  if(func==="DVD")return <DividendsScreen {...panel} lang={lang}/>;
  if(func==="CN")return <NewsScreen ticker={ticker} lang={lang}/>;
  if(func==="DQ")return <QualityScreen ticker={ticker} form={form} scope={scope} lang={lang} fromYear={2020}/>;
  if(func==="CF")return <FilingsScreen ticker={ticker} lang={lang}/>;
  return <p className="terminal-warning">{words(lang,"Оценка доступна администраторам до проверки моделей на 10 эмитентах.","Baholash tekshiruvgacha administratorlar uchun.","Valuation is restricted to administrators pending validation on ten issuers.")}</p>;
}

export function PanelWorkspace({companies,terminal,lang,user,apiFetch}) {
  const [panels,setPanels]=React.useState([]);
  const [loading,setLoading]=React.useState(true);
  const [error,setError]=React.useState("");
  const [dirty,setDirty]=React.useState(false);
  const [saving,setSaving]=React.useState(false);
  const owner=React.useRef(user?.id);owner.current=user?.id;
  const initial=React.useRef(null);
  initial.current={ticker:terminal.index.get(terminal.ticker)||companies[0]?.ticker,func:"SUM",form:"NSBU",scope:"separate"};
  const ready=!!initial.current.ticker;
  React.useEffect(()=>{
    if(!ready)return undefined;
    let alive=true;setLoading(true);setPanels([]);setError("");setDirty(false);
    const load=async()=>{
      try{
        let layout;
        if(user?.id){const response=await apiFetch("/api/profile");if(!response.ok)throw new Error();const profile=await response.json();layout=profile.preferences?.terminal_layout;}
        else layout=JSON.parse(localStorage.getItem("uz_terminal_layout")||"[]");
        if(alive){const restored=normalizeLayout(layout);setPanels(restored.length?restored:normalizeLayout([initial.current]));}
      }catch{if(alive)setError(words(lang,"Не удалось загрузить раскладку. Обновите страницу.","Panellar yuklanmadi.","Could not load layout. Reload the page."));}
      finally{if(alive)setLoading(false);}
    };load();return()=>{alive=false;};
  },[user?.id,apiFetch,lang,ready]);
  const change=next=>{
    const clean=normalizeLayout(next);setPanels(clean);setDirty(true);
    if(!user?.id){try{localStorage.setItem("uz_terminal_layout",JSON.stringify(clean));setError("");setDirty(false);}catch{setError(words(lang,"Не удалось сохранить раскладку","Saqlash xatosi","Could not save layout"));}}
  };
  const save=async()=>{const id=owner.current;setSaving(true);try{const r=await apiFetch("/api/profile/preferences",{method:"PATCH",body:JSON.stringify({terminal_layout:panels})});if(!r.ok)throw new Error();if(owner.current===id){setDirty(false);setError("");}}catch{if(owner.current===id)setError(words(lang,"Не удалось сохранить. Повторите попытку.","Saqlanmadi. Qayta urinib ko‘ring.","Save failed. Please retry."));}finally{if(owner.current===id)setSaving(false);}};
  return <section className="terminal-panel-workspace"><header className="terminal-section-head"><h2>PNL · {functionLabel("PNL",lang)}</h2><div className="terminal-controls">
    <button className="ghost-btn" disabled={loading||!!error||panels.length>=4||saving} onClick={()=>change([...panels,initial.current])}>{words(lang,"Добавить панель","Panel qo‘shish","Add panel")}</button>
    {user?.id&&<button className="primary-btn" disabled={!dirty||saving} onClick={save}>{words(lang,"Сохранить раскладку","Panellarni saqlash","Save layout")}</button>}</div></header>
    <p className="muted">{user?.id?words(lang,"Раскладка сохраняется в профиле по кнопке «Сохранить».","Panellar profilga saqlanadi.","Save your layout to your account."):words(lang,"Раскладка сохраняется автоматически в этом браузере.","Panellar shu brauzerda avtomatik saqlanadi.","Layout is saved automatically in this browser.")}</p>
    {error&&<p role="alert">{error}</p>}{loading&&<p role="status">{words(lang,"Загрузка…","Yuklanmoqda…","Loading…")}</p>}
    <div className="terminal-panel-grid">{panels.map((panel,i)=><section className="panel terminal-work-panel" key={i} data-terminal-ticker={panel.ticker} data-terminal-function={panel.func} data-terminal-standard={panel.form} data-terminal-scope={panel.scope}>
      <div className="terminal-controls"><label>{words(lang,"Эмитент","Emitent","Issuer")}<select disabled={saving} value={panel.ticker} onChange={e=>change(panels.map((p,n)=>n===i?{...p,ticker:e.target.value}:p))}>{companies.map(c=><option key={c.ticker} value={c.ticker}>{c.ticker} · {c.company_name}</option>)}</select></label>
      <label>{words(lang,"Функция","Funksiya","Function")}<select disabled={saving} value={panel.func} onChange={e=>change(panels.map((p,n)=>n===i?{...p,func:e.target.value}:p))}>{ISSUER_FUNCTIONS.map(f=><option key={f.code} value={f.code}>{f.code} · {functionLabel(f.code,lang)}</option>)}</select></label>
      <button className="ghost-btn" disabled={saving} aria-label={words(lang,"Удалить панель","Panelni o‘chirish","Remove panel")} onClick={()=>change(panels.filter((_,n)=>n!==i))}>×</button></div>
      <ContextControls {...panel} lang={lang} onForm={form=>change(panels.map((p,n)=>n===i?{...p,form,scope:"separate"}:p))} onScope={scope=>change(panels.map((p,n)=>n===i?{...p,scope}:p))}/>
      <PanelScreen panel={panel} lang={lang} onChange={next=>change(panels.map((p,n)=>n===i?next:p))} onOpen={ticker=>terminal.go({ticker,func:"SUM"})}/>
    </section>)}</div>
  </section>;
}

function SectorMetrics({ticker,form,scope,lang,summary}) {
  const {data,error}=useScreenData(`/api/v1/issuers/${encodeURIComponent(ticker)}/ai-report?standard=${form==='MSFO'?'ifrs':'nsbu'}&scope=${scope}&lang=${lang}`,{ticker,form,func:summary?'SUM':'RAT'});
  return <section className="terminal-sector-metrics"><State data={data} error={error} lang={lang}>
    <p className="terminal-context">{words(lang,'Последний разобранный отчёт','Oxirgi tahlil qilingan hisobot','Latest analysed filing')}: {data?.period||'—'} · {data?.scope||scope}</p>
    {summary?<><p>{data?.headline}</p><p>{data?.verdict_line}</p>{data?.risks?.length>0&&<ul>{data.risks.map((r,i)=><li key={i}>{r.text||r.message||r.code}</li>)}</ul>}</>:<div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{words(lang,'Показатель','Ko‘rsatkich','Metric')}</th><th>{data?.period||'—'}</th><th>{words(lang,'Метод / причина пропуска','Usul / bo‘sh qiymat sababi','Method / missing-value reason')}</th></tr></thead><tbody>{(data?.ratios||[]).map((r,i)=><tr key={r.metric_code||i}><th>{r[`name_${lang}`]||r.name_ru||r.metric_code}</th><td>{fmt(r.value??r.raw_result,lang)} {['percent','%'].includes(r.unit)?'%':''}</td><td>{r[`meaning_${lang}`]||r.reason_code||r.reason||r.method_id||'—'}</td></tr>)}</tbody></table></div>}
    {data?.status&& !['available','stale'].includes(data.status)&&<p className="terminal-warning">{data.availability?.reason_text||words(lang,'Отчёт не прошёл проверку данных. Показатели недоступны.','Hisobot tekshiruvdan o‘tmadi.','The filing did not pass data checks. Metrics unavailable.')}</p>}
    {data?.sources?.map((source,i)=>source.url&&<a key={i} href={safeHref(source.url)} target="_blank" rel="noreferrer">{words(lang,'Источник отчёта','Hisobot manbasi','Filing source')} ↗ </a>)}
  </State></section>;
}

const CBU_LABELS={npl_pct:'NPL, %',loans_bn:'Кредиты, млрд UZS',npl_bn:'Проблемные кредиты, млрд UZS',assets_bn:'Активы, млрд UZS',equity_bn:'Капитал, млрд UZS',deposits_bn:'Депозиты, млрд UZS',assets_share_pct:'Доля активов, %',loans_share_pct:'Доля кредитов, %',equity_share_pct:'Доля капитала, %',deposits_share_pct:'Доля депозитов, %',household_loans_bn:'Кредиты физлиц, млрд UZS',company_loans_bn:'Кредиты юрлиц, млрд UZS',household_deposits_bn:'Депозиты физлиц, млрд UZS',company_deposits_bn:'Депозиты юрлиц, млрд UZS'};
function BankContext({data={},sector={},lang}) {
  if(!Object.keys(data||{}).length)return null;
  return <section className="terminal-cbu"><h3>{words(lang,'Банк и сектор · ЦБ','Bank va sektor · MB','Bank and sector · CBU')}</h3>
    {Object.entries(data).map(([kind,row])=><div className="terminal-table-wrap" key={kind}><p><a href={safeHref(row.source_url)} target="_blank" rel="noreferrer">CBU · {row.date} ↗</a>{row.npl_flag&&' · ⚑ NPL > 5%'}</p><table className="terminal-table"><thead><tr><th>{words(lang,'Показатель','Ko‘rsatkich','Metric')}</th><th>{row.ticker}</th><th>{words(lang,'Сектор','Sektor','Sector')}</th></tr></thead><tbody>{Object.entries(row).filter(([key])=>CBU_LABELS[key]).map(([key,value])=><tr key={key}><th>{lang==='ru'?CBU_LABELS[key]:key.replaceAll('_',' ')}</th><td>{fmt(value,lang)}</td><td>{fmt(sector?.[kind]?.[key],lang)}</td></tr>)}</tbody></table></div>)}
  </section>;
}
function QuarterHeatmap({rows,lang}) {
  const years=[...new Set(rows.map(r=>r.period.slice(0,4)))].sort();
  if(!years.length)return null;
  return <div className="terminal-table-wrap"><table className="terminal-table terminal-heatmap"><caption>{words(lang,'Чистая прибыль · рост г/г, %','Sof foyda · yillik o‘sish, %','Net profit · YoY growth, %')}</caption><thead><tr><th>{words(lang,'Год','Yil','Year')}</th>{[1,2,3,4].map(q=><th key={q}>Q{q}</th>)}</tr></thead><tbody>{years.map(y=><tr key={y}><th>{y}</th>{[1,2,3,4].map(q=>{const row=rows.find(r=>r.period===`${y}Q${q}`),v=row?.yoy;return <td key={q} className={v==null?'':v<0?'negative':'positive'} style={{opacity:v==null?1:Math.min(1,.55+Math.abs(v)/100)}} title={`${y}Q${q}: ${fmt(row?.value,lang)} UZS`}>{fmt(v,lang)}</td>;})}</tr>)}</tbody></table></div>;
}

export function DividendsScreen({ticker,form="NSBU",scope="separate",lang}) {
  const {data,error}=useScreenData(`/api/terminal/issuer/${encodeURIComponent(ticker)}/analytics?form=${form}&scope=${scope}`,{ticker,form,func:'DVD'});
  return <><section className="terminal-dividend-comparison"><State data={data} error={error} lang={lang}>
    <p>{words(lang,'Депозиты в UZS · ЦБ','UZS depozitlari · MB','UZS deposits · CBU')}: {fmt(data?.deposit?.value,lang)}% · {data?.deposit?.period||'—'} {data?.deposit?.source_url&&<a href={safeHref(data.deposit.source_url)} target="_blank" rel="noreferrer">CBU ↗</a>}</p>
    <table className="terminal-table"><thead><tr><th>{words(lang,'Показатель','Ko‘rsatkich','Metric')}</th><th>%</th><th>{words(lang,'Разница с депозитом, п.п.','Depozitdan farq, f.p.','Spread to deposits, pp')}</th></tr></thead><tbody>{[['dy',words(lang,'Последний дивиденд / цена','Oxirgi dividend / narx','Latest dividend / price')],['ep','E/P']].map(([key,name])=>{const v=data?.snapshot?.[key],rate=data?.deposit?.value;return <tr key={key}><th>{name}</th><td>{fmt(v,lang)}</td><td>{fmt(v!=null&&rate!=null?v-rate:null,lang)}</td></tr>;})}</tbody></table>
    <p className="muted">{words(lang,'Дивидендное решение за последние 366 дней; годовая прибыль / текущая капитализация. Даты оснований различаются.','Oxirgi 366 kundagi dividend qarori; yillik foyda / joriy kapitalizatsiya.','Dividend decision within 366 days; annual profit / current capitalisation. Observation dates differ.')} {data?.dividend?.decision?.decision_date} · {data?.snapshot?.period} · {data?.snapshot?.market_date}</p>
  </State></section><IssuerDividends ticker={ticker} lang={lang} lastPrice={data?.snapshot?.price}/></>;
}

function SectorContext({data={},kind,lang}) {
  const names={capital:words(lang,'Достаточность капитала','Kapital yetarliligi','Capital adequacy'),liquidity:words(lang,'Ликвидность','Likvidlik','Liquidity'),profitability:words(lang,'Доходность сектора','Sektor rentabelligi','Sector profitability'),industry:words(lang,'Кредиты по отраслям','Tarmoqlar bo‘yicha kreditlar','Lending by industry')};
  return <section className="terminal-sector-context">{Object.entries(data||{}).filter(([key])=>kind==='bank'||key==='industry').map(([key,d])=>{
    const dates=[...new Set((d.rows||[]).flatMap(r=>Object.keys(r.observations)))].sort();
    return <details key={key}><summary>{names[key]} · CBU · {d.date}</summary><p className="muted">{words(lang,'Секторные данные относятся к указанным датам; определения показателей даны в источнике.','Sektor ma’lumotlari ko‘rsatilgan sanalarga tegishli.','Sector observations refer to their own dates and source definitions.')} <a href={safeHref(d.source_url)} target="_blank" rel="noreferrer">CBU ↗</a></p><div className="terminal-table-wrap"><table className="terminal-table"><thead><tr><th>{words(lang,'Показатель / единица','Ko‘rsatkich / birlik','Metric / unit')}</th>{dates.map(day=><th key={day}>{day}</th>)}</tr></thead><tbody>{d.rows?.map((r,i)=><tr key={i}><th>{r.name}<small>{r.unit}</small></th>{dates.map(day=><td key={day}>{fmt(r.observations[day],lang)}</td>)}</tr>)}</tbody></table></div></details>;
  })}</section>;
}


function ProfitSparkline({values,lang}) {
  const chart=profitSparkline(values);
  if(!chart.segments.length)return null;
  const title=words(lang,'Чистая прибыль, UZS','Sof foyda, UZS','Net profit, UZS');
  return <svg viewBox="0 0 100 36" className="terminal-profit-spark" role="img" aria-label={`${title} · ${chart.first}–${chart.last}`}><title>{title} · {chart.first}–{chart.last}</title>{chart.segments.map((segment,i)=>segment.length===1?<circle key={i} cx={segment[0].x} cy={segment[0].y} r="1"/>:<polyline key={i} points={segment.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke="currentColor" strokeWidth="1.5"/>)}</svg>;
}
