import {useEffect, useMemo, useState} from 'react';
import {num} from '../../lib/format.js';
import {formatChangePercent} from '../../lib/numberFormat.js';
import {buildReturns, rankReturns, readReturns, returnsQuery, shiftMonth, RETURN_LIMIT} from './returnsModel.js';
import {returnsText} from './returnsCopy.js';
import {useReturnsData} from './useReturnsData.js';
import './returns.css';

const COLORS = ['#5b9cf6','#ae82ed','#d49236','#38afa5'];
const calendarMonths = year => Array.from({length:12},(_,i)=>`${year}-${String(i+1).padStart(2,'0')}`);

export function ReturnsComparison({language='ru',apiFetch=fetch,Picker}) {
  const tx = key => returnsText(language,key);
  const [state,setState] = useState(()=>readReturns(window.location.search));
  const [picker,setPicker] = useState(false);
  const [highlight,setHighlight] = useState(null);
  const [detail,setDetail] = useState(null);
  const {histories,options,optionsError,asOf,first,loading,failed,retry} = useReturnsData(state.tickers,apiFetch);
  const latest = asOf.slice(0,7);
  const from = state.from || (latest ? [first.slice(0,7),shiftMonth(latest,-11)].sort().at(-1) : '');
  const to = state.to || latest;
  const invalid = from && to && from>to;
  const tooLong = from && to && ((Number(to.slice(0,4))-Number(from.slice(0,4)))*12+Number(to.slice(5))-Number(from.slice(5)))>=240;
  const update = patch => {setState(s=>({...s,...patch}));setDetail(null);setHighlight(null);};
  useEffect(() => {
    window.history.replaceState(window.history.state,'',window.location.pathname+returnsQuery({...state,from,to})+window.location.hash);
  },[state,from,to]);
  useEffect(() => {
    const restore = () => {setState(readReturns(window.location.search));setDetail(null);};
    window.addEventListener('popstate',restore);
    return () => window.removeEventListener('popstate',restore);
  },[]);
  const results = useMemo(()=>Object.fromEntries(state.tickers.map(t=>[t,asOf && !invalid && !tooLong ? buildReturns(histories[t]?.points,from,to,asOf) : {months:{},years:{},total:null}])),[state.tickers,histories,from,to,asOf,invalid,tooLong]);
  const years = Object.keys(results[state.tickers[0]]?.years || {});
  const percent = value => formatChangePercent(value,language,2);
  const monthFormatter = useMemo(()=>new Intl.DateTimeFormat(language==='en'?'en':language==='uz'?'uz-Latn':'ru',{month:'short',timeZone:'UTC'}),[language]);
  const label = month => monthFormatter.format(new Date(month+'-01T00:00:00Z'));
  function cells(period,kind) {
    const rows = state.tickers.map((ticker,index)=>({ticker,index,...(kind==='total'?results[ticker].total:results[ticker][kind]?.[period])}));
    return (state.layout==='relative'?rankReturns(rows):rows).map(row=> {
      const value = row.value ?? null;
      const pending = !histories[row.ticker] || histories[row.ticker].status==='loading';
      const error = histories[row.ticker]?.status==='error';
      const status = pending?'loading':error?'error':row.status;
      return <button key={row.ticker} type="button" data-testid={`return-${row.ticker}-${period}`}
        className={`rc-cell ${value>0?'rc-gain':value<0?'rc-loss':'rc-neutral'} ${highlight===row.ticker?'rc-highlight':''} ${state.layout==='relative'?'rc-ranked':''}`}
        style={{'--rc-color':COLORS[row.index],'--rc-strength':Math.min(Math.abs(value || 0)/40,1)*0.16+0.06}}
        disabled={pending} aria-label={`${row.ticker} · ${period} · ${percent(value)}${status!=='available'?' · '+tx(status):''}`}
        onMouseEnter={()=>setHighlight(row.ticker)} onMouseLeave={()=>setHighlight(null)} onFocus={()=>setHighlight(row.ticker)} onBlur={()=>setHighlight(null)}
        onClick={()=>setDetail({...row,value,status,period})}>
        <span>{row.ticker}</span><strong>{pending?'…':percent(value)}{row.partial && value!==null?'*':''}{(row.stale || row.staleEnd) && value!==null?'†':''}</strong>
      </button>;
    });
  }
  const showGrid = Boolean(state.tickers.length && from && to && !invalid && !tooLong && asOf);
  return <section className="cc-page rc-page" data-testid="returns-comparison" aria-labelledby="rc-title">
    <header className="cc-page-head"><div><p className="cc-eyebrow">UZSTOCK / {tx('returns')}</p>
      <h1 id="rc-title">{tx('title')}</h1><p className="cc-subtitle">{tx('subtitle')}</p></div>
      {asOf && <p className="rc-asof">{tx('asOf')}<strong>{asOf}</strong></p>}
    </header>
    <div className="rc-selection">
      {state.tickers.map((ticker,index)=><div className="rc-chip" key={ticker} style={{'--rc-color':COLORS[index]}}>
        <span title={options.find(c=>c.ticker===ticker)?.name || ticker}>{ticker}</span>
        <button type="button" aria-label={`${tx('remove')} ${ticker}`} onClick={()=>update({tickers:state.tickers.filter(t=>t!==ticker)})}>×</button>
      </div>)}
      <button type="button" className="cc-button" disabled={state.tickers.length>=RETURN_LIMIT || options.length===0} onClick={()=>setPicker(true)}><span aria-hidden="true">+</span> {tx('add')}</button>
      <small>{state.tickers.length} / {RETURN_LIMIT}</small>
    </div>
    <div className="rc-toolbar">
      <div className="rc-dates">{[['from',from],['to',to]].map(([key,value])=><label key={key}>{tx(key)}
        <input type="month" value={value} aria-label={tx(key)} aria-invalid={Boolean(invalid || tooLong)} aria-describedby={invalid || tooLong?'rc-range-error':undefined}
          onChange={e=>update({[key]:e.target.value})} /></label>)}</div>
      <div className="rc-modes">{[['layout',['heatmap','relative']],['frequency',['monthly','annual']]].map(([key,choices])=><div className="cc-categories" key={key}>
        {choices.map(choice=><button type="button" key={choice} aria-pressed={state[key]===choice} onClick={()=>update({[key]:choice})}>{tx(choice)}</button>)}
      </div>)}</div>
    </div>
    {(invalid || tooLong) && <p role="alert" id="rc-range-error" className="cc-notice">{tx(invalid?'invalid':'tooLong')}</p>}
    {(failed.length>0 || optionsError) && <div className="cc-notice" role="alert"><span>{optionsError?tx('optionsError'):tx('error')}{failed.length>0?' · '+failed.join(', '):''}</span><button className="cc-button" onClick={retry}>{tx('retry')}</button></div>}
    {loading && <p role="status" className="rc-help">{tx('loading')}</p>}
    {!state.tickers.length && <p className="rc-empty">{tx('empty')}</p>}
    {state.tickers.length>0 && !loading && !first && !failed.length && <p className="rc-empty">{tx('noHistory')}</p>}
    {showGrid && <>
      <p className="rc-help">{state.layout==='relative'?tx('ranking'):tx('scroll')}</p>
      <div className="rc-scroll" role="region" aria-label={tx('returns')} tabIndex={0}>
        {state.frequency==='monthly' ? years.map(year=> {
          const months = calendarMonths(year).map(month=>({month,selected:month>=from && month<=to}));
          return <table className="rc-table" key={year} style={{'--rc-months':months.filter(item=>item.selected).length}}>
          <caption>{year}</caption><thead><tr><th scope="col">{tx('year')}</th>
            {months.map(({month,selected})=><th scope="col" key={month} className={selected?undefined:'rc-unselected'}>{label(month)}</th>)}
            <th scope="col">{tx('total')}</th></tr></thead>
          <tbody><tr><th scope="row">{year}</th>{months.map(({month,selected})=><td key={month} className={selected?undefined:'rc-unselected'} data-testid={`returns-period-${month}`}>
            {selected ? cells(month,'months'):<span className="rc-outside" aria-label="—">—</span>}</td>)}
            <td data-testid={`returns-period-${year}`}>{cells(year,'years')}</td></tr></tbody>
        </table>;
        }) : <table className="rc-table rc-annual"><caption>{tx('annual')}</caption><thead><tr>{years.map(year=><th scope="col" key={year}>{year}</th>)}</tr></thead>
          <tbody><tr>{years.map(year=><td key={year} data-testid={`returns-period-${year}`}>{cells(year,'years')}</td>)}</tr></tbody></table>}
      </div>
      <div className="rc-total"><div><h2>{tx('total')}</h2><small>{from} — {to}</small></div><div className="rc-total-cells">{cells('total','total')}</div></div>
      <p className="rc-help">{tx('note')}</p>
      <section className="rc-detail" data-testid="return-detail" aria-live="polite" aria-atomic="true">
        <h2>{detail?`${detail.ticker} · ${detail.period} · ${percent(detail.value)}`:tx('detail')}</h2>
        {!detail ? <p>{tx('select')}</p> : <>
          {detail.status!=='available' && <p>{tx(detail.status)}</p>}
          {detail.base && <p>{tx('base')}: <strong>{num(detail.base.close,language,2)} UZS</strong> · {detail.base.date}</p>}
          {detail.end && <p>{tx('end')}: <strong>{num(detail.end.close,language,2)} UZS</strong> · {detail.end.date}</p>}
          {detail.value!==null && <p>({num(detail.end.close,language,2)} / {num(detail.base.close,language,2)} − 1) × 100 = <strong>{percent(detail.value)}</strong></p>}
          {detail.stale && <p>† {tx('stale')}</p>}{detail.staleEnd && <p>† {tx('staleEnd')}</p>}{detail.partial && <p>* {tx('partial')}</p>}
        </>}
      </section>
    </>}
    <details className="rc-method"><summary>{tx('method')}</summary><p>{tx('explanation')}</p></details>
    {picker && <Picker availableCompanies={options} selected={state.tickers} language={language} description={tx('note')} onClose={()=>setPicker(false)}
      onSelect={ticker=>{update({tickers:[...new Set([...state.tickers,ticker])].slice(0,RETURN_LIMIT)});setPicker(false);}} />}
  </section>;
}
