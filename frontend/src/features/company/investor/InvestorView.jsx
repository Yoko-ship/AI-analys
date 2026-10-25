import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {SourcePassport} from '../FinancialColumns.jsx';
import {Statements} from './Statements.jsx';
import {Trend,Funding,CashFlows} from './Charts.jsx';
import {Ratios,Notes,Quality,DebtLiquidity} from './Evidence.jsx';
import {amount,selectedColumn,metricRow,fieldValue,primaryField,growth,notesPages} from './model.js';
import './investor.css';

const TABS=[
  ['overview','Обзор','Umumiy','Overview'],['pl','PL Прибыль и убыток','PL Foyda va zarar','PL Profit or loss'],
  ['bs','BS Баланс','BS Balans','BS Balance'],['cf','CF Денежные потоки','CF Pul oqimlari','CF Cash flows'],
  ['equity','EQ Капитал','EQ Kapital','EQ Equity'],['rat','RAT Коэффициенты','RAT Koeffitsiyentlar','RAT Ratios'],
  ['dashboard','Дашборды','Panellar','Dashboards'],['notes','Примечания','Izohlar','Notes'],['quality','Качество','Sifat','Quality'],
];
function Overview({data,t,format}) {
  const change=growth(data,primaryField(data)),column=selectedColumn(data,'stock'),equity=fieldValue(data,'equity',column),assets=fieldValue(data,'assets',column);
  const pages=notesPages(data),segmentPages=pages.filter(p=>/segment|сегмент|портфел/i.test(p.text||''));
  return <><div className="investor-grid"><Trend data={data} t={t} format={format}/><section className="investor-panel investor-pad"><small>{t('Финансовое резюме','Moliyaviy xulosa','Financial summary')}</small><h2>{t('Что изменилось в бизнесе','Biznesdagi o‘zgarishlar','What changed in the business')}</h2><p className="investor-insight">{change==null?t('Для сравнения роста нужны два сопоставимых отчётных периода.','O‘sishni taqqoslash uchun ikkita mos hisobot davri kerak.','Two comparable reporting periods are required to measure growth.'):t(`Изменение доходной базы к сопоставимому периоду: ${format(change)}%.`,`Mos davrga nisbatan daromad o‘zgarishi: ${format(change)}%.`,`Income change against the comparable period: ${format(change)}%.`)}</p><p className="investor-insight">{t('Доля капитала в активах','Kapitalning aktivlardagi ulushi','Equity as a share of assets')}: <b>{assets>0&&equity!=null?format(equity/assets*100)+'%':'—'}</b> · {column?.end}</p><p className="investor-insight">{t('Сравнивайте прибыль с денежными потоками и раскрытиями в примечаниях.','Foydani pul oqimlari va izohlardagi ma’lumotlar bilan solishtiring.','Compare profit with cash flows and the disclosures in the notes.')}</p></section></div><div className="investor-grid"><Funding data={data} t={t} format={format}/><section className="investor-panel investor-pad"><small>{t('В разрезе сегментов','Segmentlar bo‘yicha','By segment')}</small><h2>{t('Структура бизнеса','Biznes tarkibi','Business composition')}</h2>{segmentPages.length?segmentPages.map((p,i)=><details className="investor-note" key={i}><summary>{t('Раскрытие · страница','Ma’lumot · sahifa','Disclosure · page')} {p.page}</summary><pre>{p.text}</pre></details>):<p className="investor-empty">{t('Проверенная разбивка по сегментам не раскрыта в загруженных источниках.','Yuklangan manbalarda tekshirilgan segment taqsimoti yo‘q.','No verified segment breakdown is available in the imported sources.')}</p>}</section></div><Education t={t}/></>;
}
function Education({t}) {
  return <div className="investor-education">{[
    [t('01 / Рентабельность','01 / Rentabellik','01 / Profitability'),t('Эффективность капитала','Kapital samaradorligi','Capital efficiency'),t('ROE и ROA требуют средней базы за тот же период.','ROE va ROA shu davrning o‘rtacha bazasini talab qiladi.','ROE and ROA require an average balance covering the same period.')],
    [t('02 / Денежные потоки','02 / Pul oqimlari','02 / Cash flows'),t('Подтверждение прибыли деньгами','Foydaning pul bilan tasdig‘i','Profit and cash generation'),t('Потоки и вложенные итоги представлены отдельно, без повторного сложения.','Oqimlar va oraliq yakunlar takror qo‘shilmaydi.','Flows and nested totals are shown separately without double counting.')],
    [t('03 / Примечания','03 / Izohlar','03 / Notes'),t('Что стоит за цифрами','Raqamlar ortidagi ma’lumot','Behind the figures'),t('Проверяйте долг, риски, сегменты и события по первоисточнику.','Qarz, xatar, segment va voqealarni asl manbadan tekshiring.','Inspect debt, risks, segments and events in the original disclosure.')],
  ].map(([over,title,body])=><article className="investor-panel investor-pad" key={over}><small>{over}</small><h3>{title}</h3><p>{body}</p></article>)}</div>;
}
function Kpis({data,t,format,open}) {
  const flow=selectedColumn(data),stock=selectedColumn(data,'stock'),kind=data.display_template;
  const second=kind==='bank'?'bankOperatingIncome':kind==='insurance'?'insServiceResult':kind==='fund'?'pretax':'op';
  const entries=[{field:primaryField(data),column:kind==='fund'?stock:flow},{field:second,column:flow},{field:'profit',column:flow},{field:'assets',column:stock},{ratio:'roe',column:flow},{field:kind==='fund'?'equity':'cfo',column:kind==='fund'?stock:flow}];
  return <div className="investor-kpis">{entries.map((entry,i)=>{const row=entry.ratio?(data.ratios||[]).find(r=>r.metric_id===entry.ratio):metricRow(data,entry.field);const cell=row?.cells[entry.column?.key];return <article key={i}><span>{row?.label||entry.ratio?.toUpperCase()||entry.field}</span><button type="button" className="investor-number" onClick={()=>row&&open(row,cell,entry.column)} disabled={!row}>{format(amount(cell,row?.unit))}<small>{entry.ratio?'%':t('млрд','mlrd','bn')}</small></button><p>{entry.column?.label||'—'} {entry.column?.basis==='ytd'?'· YTD':''}</p></article>;})}</div>;
}
export function InvestorView({ticker,lang='ru',scope='',onScopeChange,onStandardChange,initialTab='overview',initialMode='annual',companies=[],onTickerChange,onLoad}) {
  const t=(...args)=>words(lang,...args), panelId=React.useId();
  const [ownScope,setOwnScope]=React.useState(scope),[mode,setMode]=React.useState(initialMode),[tab,setTab]=React.useState(initialTab),[loaded,setLoaded]=React.useState(null),[retry,setRetry]=React.useState(0),[passport,setPassport]=React.useState(null);
  React.useEffect(()=>{setOwnScope(scope);},[scope]);
  React.useEffect(()=>{setTab(initialTab);},[initialTab]);
  const selectedScope=onScopeChange?scope:ownScope;
  const params=new URLSearchParams({form:'MSFO',view:'investor',freq:mode});if(selectedScope)params.set('scope',selectedScope);
  const url=`/api/company/${encodeURIComponent(ticker)}/financials/columns?${params}`;
  const onLoadRef=React.useRef(onLoad);onLoadRef.current=onLoad;
  React.useEffect(()=>{
    const controller=new AbortController(),startedAt=performance.now();setPassport(null);
    fetch(url,{signal:controller.signal}).then(async r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);const value=await r.json();if(value.presentation!=='investor')throw new Error('Invalid investor response');return value;}).then(data=>{if(!controller.signal.aborted){setLoaded({url,data});onLoadRef.current?.({startedAt});}}).catch(error=>{if(!controller.signal.aborted){setLoaded({url,error:true});onLoadRef.current?.({startedAt,error:error.message});}});
    return ()=>controller.abort();
  },[url,retry]);
  const current=loaded?.url===url?loaded:null,data=current?.data;
  const format=value=>value==null?'—':new Intl.NumberFormat(lang==='en'?'en-US':lang==='uz'?'uz-UZ':'ru-RU',{maximumFractionDigits:2}).format(value);
  const trigger=React.useRef(null);
  const open=(row,cell,column)=>{trigger.current=document.activeElement;setPassport({row,cell:cell||{value:null,quality:'missing',reason:'SOURCE_VALUE_MISSING'},end:column?.end,standard:'MSFO',scope:data.scope});};
  const close=()=>{setPassport(null);requestAnimationFrame(()=>trigger.current?.focus());};
  const hasRows=!!data?.rows?.length;
  const passportFormat=value=>value==null?'—':new Intl.NumberFormat(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2}).format(Number(value));
  return <section className="ifrs-investor" data-testid="ifrs-investor" aria-label="IFRS investor">
    <header className="investor-header"><div><small>{t('Финансовый профиль эмитента','Emitent moliyaviy profili','Issuer financial profile')}</small><h1>{data?.issuer_name||ticker}</h1><p><b>{ticker}</b> · IFRS / {data?.scope||selectedScope||t('По отчётности','Hisobot bo‘yicha','As reported')}</p></div><div className="investor-actions"><button type="button" onClick={()=>window.print()}>{t('Экспорт PDF / печать','PDF / chop etish','PDF / Print')}</button><button type="button" onClick={()=>setTab('quality')}>{t('Об отчётности','Hisobot haqida','About the reports')}</button></div></header>
    <div className="investor-filters"><div className="investor-actions">{onTickerChange&&<label>{t('Эмитент','Emitent','Issuer')}<select aria-label={t('Эмитент','Emitent','Issuer')} value={ticker} onChange={e=>onTickerChange(e.target.value)}>{[...new Map([{ticker,company_name:data?.issuer_name||ticker},...(companies||[])].filter(c=>c.ticker).map(c=>[c.ticker,c])).values()].map(c=><option key={c.ticker} value={c.ticker}>{c.ticker} · {c.company_name||c.name||c.ticker}</option>)}</select></label>}{onStandardChange&&<button type="button" onClick={()=>onStandardChange('NSBU')}>{t('НСБУ','BHMS','NSBU')}</button>}<span className="investor-standard">МСФО / IFRS</span><label>{t('Периметр','Qamrov','Scope')}<select aria-label={t('Периметр','Qamrov','Scope')} value={selectedScope||data?.scope||''} onChange={e=>onScopeChange?onScopeChange(e.target.value):setOwnScope(e.target.value)}><option value="">{t('По отчётности','Hisobot bo‘yicha','As reported')}</option><option value="consolidated">{t('Консолидированная','Konsolidatsiyalangan','Consolidated')}</option><option value="separate">{t('Отдельная','Alohida','Separate')}</option></select></label></div><div className="investor-modes">{[['annual','Годовые','Yillik','Annual'],['interim','6М / 9М / TTM','6M / 9M / TTM','6M / 9M / TTM'],['quarter','Кварталы','Choraklar','Quarters']].map(([id,...label])=><button key={id} type="button" aria-pressed={mode===id} onClick={()=>setMode(id)}>{t(...label)}</button>)}</div></div>
    {!current&&<p role="status">{t('Загрузка отчётности…','Hisobot yuklanmoqda…','Loading reports…')}</p>}{current?.error&&<p role="alert">{t('Не удалось загрузить МСФО.','MHXS hisobotini yuklab bo‘lmadi.','Could not load IFRS reports.')} <button type="button" onClick={()=>setRetry(n=>n+1)}>{t('Повторить','Qayta urinish','Retry')}</button></p>}
    {hasRows&&<Kpis data={data} t={t} format={format} open={open}/>}
    <nav className="investor-tabs" role="tablist" aria-label={t('Финансовый анализ','Moliyaviy tahlil','Financial analysis')}>{TABS.map(([id,...label])=><button type="button" role="tab" key={id} aria-selected={tab===id} aria-controls={panelId} id={`${panelId}-${id}`} tabIndex={tab===id?0:-1} onKeyDown={e=>{const n=TABS.findIndex(v=>v[0]===id);const next=e.key==='ArrowRight'?(n+1)%TABS.length:e.key==='ArrowLeft'?(n+TABS.length-1)%TABS.length:e.key==='Home'?0:e.key==='End'?TABS.length-1:null;if(next!=null){e.preventDefault();setTab(TABS[next][0]);e.currentTarget.parentElement.children[next].focus();}}} onClick={()=>setTab(id)}>{t(...label)}</button>)}</nav>
    {data&&<div role="tabpanel" id={panelId} aria-labelledby={`${panelId}-${tab}`} className="investor-workspace">{!hasRows&&<p className="investor-panel investor-empty">{t('Нет утверждённых строк источника в этом периметре.','Bu qamrovda tasdiqlangan manba qatorlari yo‘q.','No approved source rows for this scope.')}</p>}{tab==='notes'?<Notes data={data} t={t}/>:tab==='quality'?<Quality data={data} t={t} format={format}/>:!hasRows?null:tab==='overview'?<Overview data={data} t={t} format={format}/>:['pl','bs','cf','equity'].includes(tab)?<Statements data={data} tab={tab} t={t} format={format} open={open}/>:tab==='rat'?<Ratios data={data} t={t} format={format} open={open} lang={lang}/>:tab==='notes'?<Notes data={data} t={t}/>:tab==='quality'?<Quality data={data} t={t} format={format}/>:<><div className="investor-grid"><Trend data={data} t={t} format={format}/><Funding data={data} t={t} format={format}/></div><div className="investor-grid"><CashFlows data={data} t={t} format={format}/><Ratios data={data} t={t} format={format} open={open} lang={lang} compact/></div><DebtLiquidity data={data} t={t} format={format} open={open}/><Education t={t}/></>}</div>}
    {passport&&<SourcePassport item={passport} close={close} t={t} format={passportFormat}/>}
  </section>;
}
