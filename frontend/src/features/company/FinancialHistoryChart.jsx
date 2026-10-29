import React from 'react';
import {chartWindow, chartScale, defaultChartMetrics} from './financialChartViewport.js';
import { financialChartRows } from './financialColumnChart.js';
import { financialGroup } from './financialColumnGroups.js';

// Shared theme colours identify series, never whether a financial value is good.
const COLORS = [
  'var(--chart-primary)', 'var(--chart-secondary)', 'var(--chart-tertiary)', 'var(--danger)',
  'color-mix(in srgb, var(--chart-primary), var(--chart-secondary) 50%)',
  'color-mix(in srgb, var(--chart-primary), var(--danger) 50%)',
  'color-mix(in srgb, var(--chart-secondary), var(--chart-tertiary) 50%)',
  'color-mix(in srgb, var(--chart-tertiary), var(--danger) 50%)',
];
const valueOf = cell => cell?.value != null && cell.value !== '' &&
  ['valid', 'warn'].includes(cell.quality) && Number.isFinite(Number(cell.value)) ? Number(cell.value) : null;
const unitOf = row => row.unit === '%' ? 'percent' : row.unit || 'UZS_thousand';
const unitLabel = (unit, t) => unit === 'percent' ? '%' : unit === 'ratio' ? '×' :
  unit === 'UZS_per_share' ? 'UZS / share' : unit === 'UZS_thousand' ? t('тыс. UZS', 'ming UZS', 'thousands UZS') : unit;

function HistoryBars({ rows, columns, colors, unit, rawUnit, format, t }) {
  const host=React.useRef(null),gesture=React.useRef(null);
  const [width,setWidth]=React.useState(800),[offset,setOffset]=React.useState(0),[inspected,setInspected]=React.useState(null);
  React.useLayoutEffect(()=>{
    const observer=new ResizeObserver(([entry])=>setWidth(Math.max(240,entry.contentRect.width)));
    observer.observe(host.current);return()=>observer.disconnect();
  },[]);
  const count=width<600?3:8;
  const visible=chartWindow(columns,offset,count),maxOffset=Math.max(0,columns.length-count);
  const actualOffset=Math.min(offset,maxOffset);
  const points=rows.flatMap(row=>visible.map(column=>valueOf(row.cells[column.key]))).filter(value=>value!=null);
  const scale=chartScale(points),left=56,right=12,top=20,bottom=252,height=300;
  const slot=(width-left-right)/Math.max(1,visible.length);
  const barWidth=Math.min(28,slot*.72/rows.length);
  const y=value=>bottom-(value-scale.min)/(scale.max-scale.min)*(bottom-top);
  const x=(column,row)=>left+slot*(column+.5)+(row-rows.length/2)*barWidth;
  const magnitude=Math.max(Math.abs(scale.min),Math.abs(scale.max));
  const divisor=rawUnit==='UZS_thousand'?(magnitude>=1e6?1e6:magnitude>=1e3?1e3:1):1;
  const axisUnit=divisor===1e6?t('млрд UZS','mlrd UZS','UZS billion'):divisor===1e3?t('млн UZS','mln UZS','UZS million'):unit;
  const active=visible.find(column=>column.key===inspected?.column)||visible.at(-1);
  const activeIndex=visible.indexOf(active);
  const describe=(row,column,value)=>`${row.label} · ${column.label}: ${format(value)} ${unit}`;
  const move=direction=>{setOffset(Math.min(maxOffset,Math.max(0,actualOffset+direction*count)));setInspected(null);};
  const inspectAt=event=>{
    const rect=event.currentTarget.getBoundingClientRect();
    const index=Math.min(visible.length-1,Math.max(0,Math.floor(((event.clientX-rect.left)*width/rect.width-left)/slot)));
    if(visible[index])setInspected({column:visible[index].key});
  };
  const keyInspect=(event,index)=>{
    const next={ArrowLeft:index-1,ArrowRight:index+1,Home:0,End:visible.length-1}[event.key];
    if(event.key==='Enter'||event.key===' '){event.preventDefault();setInspected({column:visible[index].key});return;}
    if(next==null)return;
    event.preventDefault();const bounded=Math.max(0,Math.min(visible.length-1,next));
    setInspected({column:visible[bounded].key});
    host.current.querySelectorAll('[data-period-hit]')[bounded]?.focus();
  };
  return <div className="fc-chart-plot" ref={host}>
    <div className="fc-chart-navigation">
      <div><strong className="fc-chart-range">{visible[0]?.label} — {visible.at(-1)?.label}</strong><span className="fc-chart-unit">{axisUnit}</span></div>
      <div className="fc-chart-paging">
        <button type="button" aria-label={t('Предыдущие периоды','Oldingi davrlar','Previous periods')} disabled={actualOffset>=maxOffset} onClick={()=>move(1)}>←</button>
        <button type="button" aria-label={t('Следующие периоды','Keyingi davrlar','Next periods')} disabled={!actualOffset} onClick={()=>move(-1)}>→</button>
        <button type="button" disabled={!actualOffset} onClick={()=>{setOffset(0);setInspected(null);}}>{t('Последние периоды','So‘nggi davrlar','Latest periods')}</button>
      </div>
    </div>
    <div className="fc-chart-scroll" role="region" aria-label={t('История показателей','Ko‘rsatkichlar tarixi','Metric history')}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t('Финансовая история','Moliyaviy tarix','Financial history')}
        data-period-count={visible.length} data-scale-min={scale.min} data-scale-max={scale.max}
        onPointerMove={event=>{if(event.pointerType==='mouse')inspectAt(event);}}
        onPointerDown={event=>{gesture.current=event.clientX;inspectAt(event);}}
        onPointerUp={event=>{if(gesture.current!=null&&Math.abs(event.clientX-gesture.current)>40)move(event.clientX>gesture.current?1:-1);gesture.current=null;}}
        onPointerCancel={()=>{gesture.current=null;}}>
        {scale.ticks.map(value=><g key={value} className={value===0?'fc-chart-zero':''}>
          <line x1={left} x2={width-right} y1={y(value)} y2={y(value)} stroke="var(--chart-grid)"/>
          <text x={left-10} y={y(value)+4} textAnchor="end">{format(value/divisor)}</text>
        </g>)}
        {visible.map((column,i)=><g key={column.key}>
          <rect data-period-hit={column.key} role="button" aria-label={column.label} tabIndex={0}
            x={left+slot*i} y={top} width={slot} height={bottom-top} rx="4"
            fill={activeIndex===i?'var(--accent-light)':'transparent'} opacity={activeIndex===i?.45:1}
            onFocus={()=>setInspected({column:column.key})} onClick={()=>setInspected({column:column.key})} onKeyDown={event=>keyInspect(event,i)}/>
          <text x={left+slot*(i+.5)} y="278" textAnchor="middle" className={activeIndex===i?'fc-chart-active-label':''}>{column.label}</text>
        </g>)}
        {rows.map((row,rowIndex)=><g key={row.id} data-chart-series={row.id} fill={colors.get(row.id)}>
          {visible.map((column,columnIndex)=>{
            const value=valueOf(row.cells[column.key]);if(value==null)return null;
            const label=describe(row,column,value),inspect=()=>setInspected({row:row.id,column:column.key});
            return <rect key={column.key} x={x(columnIndex,rowIndex)} y={Math.min(y(value),y(0))-(value===0?1:0)}
              width={Math.max(1,barWidth-3)} height={Math.max(2,Math.abs(y(value)-y(0)))} rx="3"
              tabIndex={0} aria-label={label} onPointerEnter={inspect} onFocus={inspect} onClick={inspect}><title>{label}</title></rect>;
          })}
        </g>)}
      </svg>
    </div>
    <div className="fc-chart-reading" aria-live="polite">
      <strong>{active?.label}</strong>
      <div className="fc-chart-values">{active&&rows.map(row=><div key={row.id} style={{'--series-color':colors.get(row.id)}}>
        <span><i aria-hidden="true"/>{row.label}</span><strong>{format(valueOf(row.cells[active.key]))} <small>{unit}</small></strong>
      </div>)}</div>
    </div>
    <p className="fc-chart-hint">{t('Наведите или нажмите на период · Листайте периоды стрелками или свайпом','Davr ustiga kursor olib boring yoki bosing · Davrlarni strelka yoki surish bilan almashtiring','Hover or tap a period · Browse with arrows or swipe')}</p>
  </div>;
}

export function FinancialHistoryChart({ rows, columns, view, groupLabel, format, lang, t }) {
  const [hiddenChoice, setHidden] = React.useState(null);
  const [grouped, setGrouped] = React.useState(true);
  const colors = React.useRef(new Map());
  const available = financialChartRows(rows, columns);
  for (const row of available) if (!colors.current.has(row.id)) colors.current.set(row.id, COLORS[colors.current.size % COLORS.length]);
  const defaults=new Set(defaultChartMetrics(available).map(row=>row.id));
  const hidden=hiddenChoice || new Set(available.filter(row=>!defaults.has(row.id)).map(row=>row.id));
  const selected = available.filter(row => !hidden.has(row.id));
  const groups = new Map();
  for (const row of available) {
    const key = grouped ? financialGroup(row, view) : '';
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(row);
  }
  const toggle = items => setHidden(previous => {
    const next = new Set(previous || hidden), hide = items.every(row => !(previous || hidden).has(row.id));
    for (const row of items) if (hide) next.add(row.id); else next.delete(row.id);
    return next;
  });
  const setAll = show => setHidden(previous => {
    const next = new Set(previous || hidden);
    for (const row of available) if (show) next.delete(row.id); else next.add(row.id);
    return next;
  });
  const units = [...new Set(selected.map(unitOf))];
  return <section className="fc-chart">
    {available.length === 0 ? <p className="fc-empty">{t('Нет проверенных значений для графика.', 'Grafik uchun tekshirilgan qiymatlar yo‘q.', 'No verified values to chart.')}</p> : <>
      {units.map(unit => <HistoryBars key={unit} rows={selected.filter(row => unitOf(row) === unit)} columns={columns} colors={colors.current}
        rawUnit={unit} unit={unitLabel(unit, t)} format={format} lang={lang} t={t}/>) }
      <div className="fc-chart-controls">
        <div className="fc-segment" role="group" aria-label={t('Группировка показателей', 'Ko‘rsatkichlarni guruhlash', 'Metric grouping')}>
          <button type="button" aria-pressed={grouped} onClick={() => setGrouped(true)}>{t('По разделам', 'Bo‘limlar bo‘yicha', 'By section')}</button>
          <button type="button" aria-pressed={!grouped} onClick={() => setGrouped(false)}>{t('Без группировки', 'Guruhlashsiz', 'Ungrouped')}</button>
        </div>
        <span className="fc-chart-count">{t('Показано', 'Ko‘rsatilgan', 'Shown')} {selected.length} / {available.length}</span>
        <div className="fc-chart-actions">
          <button type="button" disabled={selected.length === available.length} onClick={() => setAll(true)}>{t('Показать все', 'Barchasini ko‘rsatish', 'Show all')}</button>
          <button type="button" disabled={!selected.length} onClick={() => setAll(false)}>{t('Скрыть все', 'Barchasini yashirish', 'Hide all')}</button>
        </div>
      </div>
      <div className="fc-chart-groups">{Array.from(groups, ([key, items]) => {
        const count = items.filter(row => !hidden.has(row.id)).length;
        return <div className="fc-chart-group" key={key}>
          {grouped && <button type="button" className="fc-chart-group-toggle" aria-label={groupLabel(key)}
            aria-pressed={count === items.length ? true : count ? 'mixed' : false} onClick={() => toggle(items)}>
            <span className="fc-chart-group-state" aria-hidden="true">{count === items.length ? '✓' : count ? '−' : ''}</span>
            <span>{groupLabel(key)}</span><small aria-hidden="true">{count} / {items.length}</small>
          </button>}
          <div className="fc-chart-metrics">{items.map(row => <button key={row.id} type="button" className="fc-chart-metric"
            aria-pressed={!hidden.has(row.id)} onClick={() => toggle([row])}>
            <i aria-hidden="true" style={{'--series-color': colors.current.get(row.id)}}/>{row.label}
          </button>)}</div>
        </div>;
      })}</div>
      {!selected.length && <p className="fc-empty" role="status">{t('Выберите показатели выше, чтобы показать график.', 'Grafikni ko‘rsatish uchun yuqoridagi ko‘rsatkichlarni tanlang.', 'Select metrics above to show the chart.')}</p>}

    </>}
  </section>;
}
