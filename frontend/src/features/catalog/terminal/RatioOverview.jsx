import React from 'react';
import {RatioInfo} from '../../../shared/RatioInfo.jsx';
import {words} from '../../../shared/TerminalTables.jsx';
import './ratioOverview.css';

const format=(value,lang)=>value==null?'—':Number(value).toLocaleString(lang==='en'?'en-US':'ru-RU',{maximumFractionDigits:2});

export function RatioOverview({snapshot,metrics,growth,form,scope,lang}) {
  const title=words(lang,'Годовые показатели','Yillik ko‘rsatkichlar','Annual ratios');
  const scopeLabel=scope==='consolidated'
    ?words(lang,'Консолидированная','Konsolidatsiyalangan','Consolidated')
    :words(lang,'Отдельная','Alohida','Separate');
  return <div className="terminal-ratio-overview">
    <section className="terminal-ratio-card terminal-annual-card">
      <header className="terminal-ratio-card-head">
        <h3>{title}</h3>
        <p className="terminal-ratio-meta"><strong>{snapshot.period||'—'}</strong><span>{form}</span><span>{scopeLabel}</span></p>
      </header>
      <div className="terminal-table-wrap"><table className="terminal-table terminal-annual-ratios">
        <caption className="sr-only">{title} · {snapshot.period||'—'} · {form} · {scopeLabel}</caption>
        <tbody>{metrics.map(([key,label])=><tr key={key}>
          <th scope="row"><span className="terminal-ratio-label">{label}<RatioInfo metric={key} label={label} lang={lang}/></span></th>
          <td className={snapshot[key]==null?'is-missing':undefined}>{format(snapshot[key],lang)}</td>
        </tr>)}</tbody>
      </table></div>
    </section>
    <section className="terminal-ratio-card terminal-growth-card">
      <header className="terminal-ratio-card-head">
        <h3>CAGR</h3>
        <p className="terminal-ratio-meta">{words(lang,'Среднегодовой рост','O‘rtacha yillik o‘sish','Compound annual growth')}</p>
      </header>
      <div className="terminal-table-wrap"><table className="terminal-table terminal-growth-ratios">
        <thead><tr>
          <th scope="col">{words(lang,'Показатель','Ko‘rsatkich','Metric')}</th>
          <th scope="col">{words(lang,'Период','Davr','Period')}</th>
          <th scope="col">{words(lang,'Номинальный, %','Nominal, %','Nominal, %')}</th>
          <th scope="col">{words(lang,'Реальный, %','Real, %','Real, %')}</th><th scope="col">USD, %</th>
        </tr></thead>
        <tbody>{growth.map(row=><tr key={`${row.field}:${row.years}`}>
          <th scope="row">{row.label}</th><td>{row.start}–{row.end}</td>
          {[row.nominal,row.real,row.usd].map((value,i)=><td key={i} className={value==null?'is-missing':undefined} title={row.reason||undefined}>{format(value,lang)}</td>)}
        </tr>)}</tbody>
      </table></div>
      <p className="terminal-ratio-note">{words(lang,
        'Убыток или отсутствующая граница периода — без расчёта. Реальный рост и рост в USD требуют полного ряда инфляции и курсов ЦБ.',
        'Zarar yoki yetishmagan davr bo‘lsa hisoblanmaydi.',
        'Losses or missing endpoints are not calculated. Real and USD growth require complete inflation and CBU exchange rates.')}</p>
    </section>
  </div>;
}
