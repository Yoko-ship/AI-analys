import React from 'react';
import {words} from '../../../shared/TerminalTables.jsx';
import {metricApplies} from '../../../lib/terminalWorkspace.js';
import {MetricValue} from './MetricValue.jsx';
import './peerComparison.css';

export function PeerComparisonTable({rows,metrics,ticker,lang,onOpen,formatValue}) {
  const title=words(lang,'Сравнение показателей','Ko‘rsatkichlarni taqqoslash','Ratio comparison');
  const selected=words(lang,'Выбранный эмитент','Tanlangan emitent','Selected issuer');
  return <section className="terminal-peer-card">
    <header className="terminal-peer-card-head">
      <h4>{title}</h4>
      <p className="terminal-peer-meta">
        <span>{words(lang,'Эмитентов','Emitentlar','Issuers')}: <strong>{rows.length}</strong></span>
        <span>{selected}: <strong>{ticker}</strong></span>
      </p>
    </header>
    <div className="terminal-table-wrap terminal-peer-scroll" role="region" aria-label={title} tabIndex={0}>
      <table className="terminal-table terminal-peer-table">
        <caption className="sr-only">{title}</caption>
        <thead><tr><th scope="col">{words(lang,'Эмитент','Emitent','Issuer')}</th>{metrics.map(([key,label])=><th scope="col" key={key}>{label}</th>)}</tr></thead>
        <tbody>{rows.map(row=><tr key={row.ticker} className={row.ticker===ticker?'is-selected':undefined}>
          <th scope="row"><button type="button" className="terminal-code" aria-current={row.ticker===ticker?'true':undefined} onClick={()=>onOpen?.(row.ticker)}>{row.ticker}</button></th>
          {metrics.map(([key,label])=><td key={key} className={row[key]==null?'is-missing':undefined}
            title={key==='npl'&&metricApplies(row,key)?row.cbu?.npl?.date:key==='dy'?row.dividend?.decision?.decision_date:undefined}>
            <MetricValue row={row} metric={key} label={label} lang={lang} text={formatValue(row[key],key)}/>
            {key==='npl'&&metricApplies(row,key)&&row.cbu?.npl?.npl_flag?' ⚑':''}
          </td>)}
        </tr>)}</tbody>
      </table>
    </div>
  </section>;
}
