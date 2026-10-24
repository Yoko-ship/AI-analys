import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {historyRows,HISTORY_FIELDS} from '../../../lib/terminalSummary.js';
import {periodEnd} from '../../../lib/terminalCurrency.js';
import {useScreenData} from './TerminalPanels.jsx';
import {financialsUrl} from '../../../lib/financialHistoryRequest.js';

function AnnualChart({rows,fields,stacked=false,title,fmt,divisor}) {
  const values=rows.flatMap(row=>stacked?(row.balance_complete?[Math.max(0,row.total_liabilities)+Math.max(0,row.total_equity),Math.min(0,row.total_liabilities)+Math.min(0,row.total_equity)]:[]):fields.map(f=>row[f.key]).filter(v=>v!=null));
  const max=Math.max(0,...values),min=Math.min(0,...values),span=max-min||1;
  const y=v=>20+(max-v)/span*155;
  const slot=520/Math.max(rows.length,1);
  const width=Math.min(55,slot*.7);
  const ticks=[max,0,...(min<0?[min]:[])].filter((v,i,a)=>a.indexOf(v)===i);
  const zeroLabelFits=ticks.every(value=>value===0||Math.abs(y(value)-y(0))>=14);
  return <svg className="terminal-history-chart" viewBox="0 0 600 220" role="img" aria-label={title}>
    <title>{title}</title>
    {ticks.map(value=><g key={value}><line x1="60" x2="580" y1={y(value)} y2={y(value)} className="terminal-chart-grid"/>{(value!==0||zeroLabelFits)&&<text x="52" y={y(value)+4} textAnchor="end">{fmt(value/divisor)}</text>}</g>)}
    {rows.map((row,i)=>{
      const x=60+slot*i+(slot-width)/2;
      let positive=0,negative=0;
      return <g key={row.period}><text x={60+slot*(i+.5)} y="204" textAnchor="middle">{row.label||row.period}</text>
        {fields.map((field,n)=>{
          const value=stacked&&!row.balance_complete?null:row[field.key];
          if(value==null)return <text key={field.key} x={x+width/2} y={y(0)-6-n*12} textAnchor="middle" className="terminal-chart-gap">—</text>;
          let from=0;
          if(stacked){from=value>=0?positive:negative;if(value>=0)positive+=value;else negative+=value;}
          const top=y(Math.max(from,from+value)),bottom=y(Math.min(from,from+value));
          const barWidth=stacked?width:width/fields.length;
          return <rect key={field.key} x={x+(stacked?0:n*barWidth)} y={value===0?y(0)-1:top} width={Math.max(1,barWidth-1)} height={Math.max(2,bottom-top)} fill={value<0?'var(--negative)':field.color}>
            <title>{row.label||row.period} · {field.label}: {fmt(value/divisor)}</title>
          </rect>;
        })}
      </g>;
    })}
  </svg>;
}

export function SummaryHistory({ticker,form,scope,lang,kind,fromYear}) {
  const {data,error}=useScreenData(financialsUrl(ticker,form,scope),{ticker,form,func:'SUM'});
  const {data:quarterly,error:currentError}=useScreenData(financialsUrl(ticker,form,scope,true),{ticker,form,func:'SUM'});
  const [currency,setCurrency]=React.useState('UZS');
  const [rates,setRates]=React.useState({key:'',values:{},loading:false});
  const rawRows=historyRows(data,fromYear,quarterly);
  const periods=rawRows.filter(row=>row.published).map(row=>row.period);
  const rateKey=periods.join(',');
  React.useEffect(()=>{
    if(currency!=='USD')return undefined;
    const controller=new AbortController(),pending=rateKey.split(',').filter(Boolean),values={};
    setRates({key:rateKey,values:{},loading:true});
    async function worker(){
      while(pending.length&&!controller.signal.aborted){
        const period=pending.shift(),day=periodEnd(period);
        try{
          const response=await fetch(`/api/currency/rates?as_of=${day}`,{signal:controller.signal});
          if(!response.ok)continue;
          const payload=await response.json(),usd=payload.rates?.find(row=>row.ccy==='USD');
          if(payload.as_of===day&&usd?.effective_date<=day&&Number.isFinite(usd?.per_unit)&&usd.per_unit>0)values[period]=usd;
        }catch{/* Missing FX keeps that year's amounts unavailable. */}
      }
    }
    Promise.all(Array.from({length:4},worker)).then(()=>{if(!controller.signal.aborted)setRates({key:rateKey,values,loading:false});});
    return()=>controller.abort();
  },[currency,rateKey]);
  const fx=rates.key===rateKey?rates.values:{};
  // Convert the complete YTD amount at its reporting date, not each discrete
  // quarter at a different exchange rate before adding it to the chart.
  const rows=rawRows.map(row=>currency!=='USD'?row:{...row,...Object.fromEntries(HISTORY_FIELDS.map(field=>[
    field,row[field]!=null&&fx[row.period]?.per_unit>0?row[field]/fx[row.period].per_unit:null,
  ]))});
  const current=rawRows.find(row=>row.current);
  const t=(ru,uz,en)=>words(lang,ru,uz,en);
  const fmt=value=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
  const divisor=currency==='UZS'?1e9:1e6;
  const unit=currency==='UZS'?t('млрд UZS','mlrd UZS','UZS billion'):t('млн USD','mln USD','USD million');
  const incomeKey=kind==='bank'&&form==='MSFO'?'interest_income':'net_revenue';
  const incomeLabel=kind==='bank'?t(form==='MSFO'?'Процентные доходы':'Совокупные доходы',form==='MSFO'?'Foiz daromadi':'Jami daromad',form==='MSFO'?'Interest income':'Total income'):kind==='insurance'?t('Заработанные премии','Ishlab topilgan mukofotlar','Earned premiums'):t('Выручка','Tushum','Revenue');
  const incomeFields=[...(kind==='fund'?[]:[{key:incomeKey,label:incomeLabel,color:'var(--terminal-chart,#4bb8e8)'}]),{key:'net_profit',label:t('Чистая прибыль','Sof foyda','Net profit'),color:'var(--positive,#3fbf6a)'}];
  const balanceFields=[{key:'total_liabilities',label:t('Обязательства','Majburiyatlar','Liabilities'),color:'var(--accent)'},{key:'total_equity',label:t('Капитал','Kapital','Equity'),color:'var(--positive,#3fbf6a)'}];
  const title=kind==='fund'?t('Чистая прибыль по годам','Yillar bo‘yicha sof foyda','Annual net profit'):kind==='bank'?t('Доходы и прибыль по годам','Yillar bo‘yicha daromad va foyda','Annual income and profit'):kind==='insurance'?t('Премии и прибыль по годам','Yillar bo‘yicha mukofot va foyda','Annual premiums and profit'):t('Выручка и прибыль по годам','Yillar bo‘yicha tushum va foyda','Annual revenue and profit');
  const balanceTitle=t('Структура баланса по годам','Yillar bo‘yicha balans tarkibi','Annual balance structure');
  const gaps=rows.filter(row=>!row.published).map(row=>row.period);
  return <section className="terminal-summary-history" data-currency={currency}>
    <div className="terminal-controls"><label>{t('Валюта истории','Tarix valyutasi','History currency')}<select value={currency} onChange={e=>setCurrency(e.target.value)}><option>UZS</option><option>USD</option></select></label><span className="terminal-context">{form} · {scope} · {t('Годовые отчёты','Yillik hisobotlar','Annual filings')} · {unit}</span></div>
    {current&&<p className="terminal-context">{t('Текущий отчёт','Joriy hisobot','Current report')}: {current.label} · {t('Доходы и прибыль — с начала года; баланс на','Daromad va foyda — yil boshidan; balans sanasi','Income and profit are year-to-date; balance as of')} {periodEnd(current.period)}.</p>}
    {currentError&&<p role="alert">{t('Не удалось загрузить текущий отчёт.','Joriy hisobot yuklanmadi.','Could not load the current report.')}</p>}
    {currency==='USD'&&<details className="terminal-fx-rates"><summary>{t('Курсы ЦБ на конец каждого периода','Har davr oxiridagi MB kursi','CBU rates at each period end')}</summary>{rates.loading?<p role="status">{t('Загрузка курсов…','Kurslar yuklanmoqda…','Loading rates…')}</p>:<ul>{periods.map(period=><li key={period}>{periodEnd(period)} · {fx[period]?`1 USD = ${fmt(fx[period].per_unit)} UZS (${fx[period].effective_date})`:t('Курс отсутствует — суммы скрыты','Kurs yo‘q — summalar yashirildi','Rate missing — amounts unavailable')}</li>)}</ul>}</details>}
    {error?<p role="alert">{t('Не удалось загрузить историю.','Tarix yuklanmadi.','Could not load financial history.')}</p>:!data?<p role="status">{t('Загрузка истории…','Tarix yuklanmoqda…','Loading history…')}</p>:!rows.length?<p className="muted">{t('Нет опубликованной годовой истории.','E’lon qilingan yillik tarix yo‘q.','No published annual history.')}</p>:<>
      {gaps.length>0&&<p className="terminal-warning terminal-history-gap">{t('Нет годового отчёта за','Yillik hisobot yo‘q','Annual filing missing for')}: {gaps.join(', ')}. {t('Пропуски не заменяются нулём.','Bo‘sh qiymatlar nol bilan almashtirilmaydi.','Gaps are not replaced with zero.')}</p>}
      <div className="terminal-summary-charts">{[[title,incomeFields,false],[balanceTitle,balanceFields,true]].map(([name,fields,stacked])=><section key={name} className="terminal-summary-card"><h3>{name}</h3><p className="muted">{unit}</p><AnnualChart rows={rows} fields={fields} stacked={stacked} title={name} fmt={fmt} divisor={divisor}/><div className="terminal-chart-legend">{fields.map(field=><span key={field.key}><i style={{background:field.color}}/>{field.label}</span>)}</div></section>)}</div>
      <details className="terminal-history-data"><summary>{t('Таблица истории','Tarix jadvali','History table')}</summary><div className="terminal-table-wrap"><table className="terminal-table terminal-history-table"><thead><tr><th>{t('Период','Davr','Period')}</th>{[...incomeFields,...balanceFields].map(field=><th key={field.key}>{field.label}, {unit}</th>)}</tr></thead><tbody>{rows.map(row=><tr key={row.period}><th>{row.label||row.period}</th>{[...incomeFields,...balanceFields].map(field=><td key={field.key}>{row[field.key]==null?'—':fmt(row[field.key]/divisor)}</td>)}</tr>)}</tbody></table></div></details>
    </>}
  </section>;
}
