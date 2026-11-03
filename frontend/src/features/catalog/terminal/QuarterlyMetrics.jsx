import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import './ratioOverview.css';

const format=(value,lang)=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});
const tone=value=>value==null?'is-missing':value<0?'negative':value>0?'positive':'';

function QuarterHeatmap({rows,years,lang}) {
  if(!years.length)return null;
  const title=words(lang,'Чистая прибыль · рост г/г, %','Sof foyda · yillik o‘sish, %','Net profit · YoY growth, %');
  return <section className="terminal-ratio-card terminal-heatmap-card">
    <header className="terminal-ratio-card-head">
      <h3>{title}</h3>
      <p className="terminal-ratio-meta">{years[0]}{years.length>1?`–${years.at(-1)}`:''}</p>
    </header>
    <div className="terminal-table-wrap" tabIndex={0} role="region" aria-label={title}>
      <table className="terminal-table terminal-heatmap">
        <caption className="sr-only">{title}</caption>
        <thead><tr><th scope="col">{words(lang,'Год','Yil','Year')}</th>{[1,2,3,4].map(quarter=><th scope="col" key={quarter}>Q{quarter}</th>)}</tr></thead>
        <tbody>{years.map(year=><tr key={year}>
          <th scope="row">{year}</th>
          {[1,2,3,4].map(quarter=>{
            const row=rows.find(row=>row.period===`${year}Q${quarter}`),value=row?.yoy;
            return <td key={quarter} className={tone(value)}
              style={value==null?undefined:{'--heat-strength':`${10+14*Math.min(Math.abs(value)/100,1)}%`}}
              title={`${year}Q${quarter}: ${format(row?.value,lang)} UZS`}>{format(value,lang)}</td>;
          })}
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}

export function QuarterlyMetrics({quarters,lang}) {
  const rows=quarters.rows||[];
  const years=[...new Set(rows.map(row=>row.period.slice(0,4)))].sort();
  const title=words(lang,'Кварталы · чистая прибыль','Choraklar · sof foyda','Quarters · net profit');
  const unit=words(lang,'млрд UZS','mlrd UZS','UZS billion');
  return <div className="terminal-quarterly-overview">
    <QuarterHeatmap rows={rows} years={years} lang={lang}/>
    <section className="terminal-ratio-card terminal-quarterly-card">
      <header className="terminal-ratio-card-head"><h3>{title}</h3><p className="terminal-ratio-meta">{unit}</p></header>
      {quarters.reason&&<p className="terminal-warning">{words(lang,
        'Опубликован накопленный итог: его нельзя показывать как отдельный квартал.',
        'Hisobot jamlangan; alohida chorak emas.',
        'Published amounts are cumulative and cannot be shown as standalone quarters.')}</p>}
      <div className="terminal-table-wrap" tabIndex={0} role="region" aria-label={title}>
        <table className="terminal-table terminal-quarter-map">
          <caption className="sr-only">{title}</caption>
          <thead><tr>
            <th scope="col">{words(lang,'Квартал','Chorak','Quarter')}</th><th scope="col">{unit}</th><th scope="col">YoY, %</th>
            <th scope="col">LTM, {unit}</th><th scope="col">{words(lang,'Доля в году, %','Yildagi ulush, %','Share of year, %')}</th><th scope="col">CAGR 3Y, %</th>
          </tr></thead>
          <tbody>{rows.map(row=><tr key={row.period}>
            <th scope="row">{row.period}</th>
            {[row.value==null?null:row.value/1e9,row.yoy,row.ltm==null?null:row.ltm/1e9,row.seasonality,row.cg3].map((value,i)=><td key={i}
              className={i===1?tone(value):value==null?'is-missing':undefined}>{format(value,lang)}</td>)}
          </tr>)}</tbody>
        </table>
      </div>
    </section>
  </div>;
}
