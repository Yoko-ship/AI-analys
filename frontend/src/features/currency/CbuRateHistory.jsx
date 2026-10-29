import {useEffect, useMemo, useRef, useState} from 'react';
import {useMediaQuery} from '../../shared/useMediaQuery.js';
import {formatRatio} from '../../shared/format.jsx';
import {historyScale, historySeries} from './historyChart.js';
import {useEarlierHistory} from './useEarlierHistory.js';
import LwCanvas from '../../charts/LwCanvas.jsx';
import './cbuRateHistory.css';

const copy = {
  ru: {earlierLoading:'Загружаем более ранние курсы…', earlierError:'Более ранние курсы недоступны', earlierRetry:'Повторить загрузку ранних курсов', official:'Официальный курс ЦБ Узбекистана', reset:'Сбросить вид', desktopHint:'Перетаскивайте график · Ctrl + прокрутка — масштаб', touchHint:'Сдвигайте график · Сведите или разведите пальцы для масштаба', title:'История курса ЦБ', short:'История курса', unit:'за 1', period:'за период', effective:'Действует с', loading:'Загружаем ежедневные курсы…', empty:'Исторические курсы недоступны', retry:'Повторить', unavailable:'Нет данных', gaps:n=>`Нет данных за ${n} дн.`, source:'Источник: ЦБ Узбекистана', hint:'Наведите или нажмите на график', keys:'Стрелки — выбрать дату', inspect:'Курс по дням', changeMissing:'Недостаточно данных для изменения за период', range:'Период', latest:'Последний доступный курс'},
  en: {earlierLoading:'Loading earlier rates…', earlierError:'Earlier rates unavailable', earlierRetry:'Retry earlier rates', official:'Official Central Bank rate', reset:'Reset view', desktopHint:'Drag to pan · Ctrl + scroll to zoom', touchHint:'Swipe to pan · Pinch to zoom', title:'CBU rate history', short:'Rate history', unit:'per 1', period:'over period', effective:'Effective from', loading:'Loading daily rates…', empty:'Historical rates unavailable', retry:'Retry', unavailable:'Unavailable', gaps:n=>`${n} ${n===1?'day':'days'} unavailable`, source:'Source: Central Bank of Uzbekistan', hint:'Hover or tap to inspect', keys:'Arrow keys select a date', inspect:'Daily exchange rate', changeMissing:'Not enough data for the period change', range:'Period', latest:'Latest available rate'},
  uz: {earlierLoading:'Oldingi kurslar yuklanmoqda…', earlierError:'Oldingi kurslar mavjud emas', earlierRetry:'Oldingi kurslarni qayta yuklash', official:'O‘zbekiston Markaziy bankining rasmiy kursi', reset:'Ko‘rinishni tiklash', desktopHint:'Grafikni suring · Ctrl + aylantirish — masshtab', touchHint:'Surish — tarix · Ikki barmoq bilan masshtab', title:'MB kursi tarixi', short:'Kurs tarixi', unit:'1 birlik uchun', period:'davr davomida', effective:'Amal qilish sanasi', loading:'Kunlik kurslar yuklanmoqda…', empty:'Tarixiy kurslar mavjud emas', retry:'Qayta urinish', unavailable:'Ma’lumot yo‘q', gaps:n=>`${n} kun uchun ma’lumot yo‘q`, source:'Manba: O‘zbekiston Markaziy banki', hint:'Ko‘rish uchun grafikni bosing', keys:'Sanani yo‘nalish tugmalari bilan tanlang', inspect:'Kunlik valyuta kursi', changeMissing:'Davr o‘zgarishi uchun ma’lumot yetarli emas', range:'Davr', latest:'Oxirgi mavjud kurs'},
};
const locale = language => language==='en'?'en-GB':language==='uz'?'uz-UZ':'ru-RU';
function dateLabel(day, language, year=false) {
  return new Intl.DateTimeFormat(locale(language), {day:'numeric',month:'short', ...(year?{year:'numeric'}:{}),timeZone:'UTC'}).format(new Date(day+'T12:00:00Z'));
}

function HistoryPlot({data, language, t}) {
  const [selected, setSelected] = useState(null);
  const interacted=useRef(false);
  const [visible, setVisible] = useState(null);
  const [resetToken, setResetToken] = useState(0);
  const [focus, setFocus] = useState(null);
  const touch = useMediaQuery('(pointer: coarse)');
  const earlier=useEarlierHistory(data.ccy,data.points);
  const points = earlier.points;
  // A prepend changes every array index. Keep the visible calendar dates
  // stable until the canvas reports its adjusted range, including between commits.
  const from=Math.max(0,points.findIndex(p=>p.date===visible?.fromDate));
  const endIndex=points.findIndex(p=>p.date===visible?.toDate);
  const to=endIndex<0?points.length-1:endIndex;
  const selectedIndex=selected?points.findIndex(p=>p.date===selected):-1;
  const index = selectedIndex<0?to:selectedIndex, point = points[index];
  const number = value=>formatRatio(value,2,language);
  const spec = useMemo(()=>({main:'history', timeScale:{fixRightEdge:true, fixLeftEdge:!earlier.hasEarlier,
    tickMarkFormatter:time=>dateLabel(new Date(time*1000).toISOString().slice(0,10),language)}, series:historySeries(points, {
    priceFormat:{type:'custom', minMove:0.01, formatter:value=>formatRatio(value,2,language)},
    autoscaleInfoProvider:original=>{
      const info=original();
      if(!info)return null;
      const scale=historyScale([info.priceRange.minValue,info.priceRange.maxValue]);
      return {...info,priceRange:{minValue:scale.min,maxValue:scale.max}};
    },
  })}),[points,language,earlier.hasEarlier]);
  const valueText = `${dateLabel(point.date,language,true)}: ${Number.isFinite(point.value)?number(point.value)+' UZS':t.unavailable}`;
  const initialView=useMemo(()=>({from:Date.parse(data.start+'T00:00:00Z')/1000,to:Date.parse(data.end+'T00:00:00Z')/1000}),[data.start,data.end]);
  const loadEarlier=earlier.load;
  useEffect(()=>{
    if(interacted.current&&visible?.anchor===points[0].date&&visible.logicalFrom < -1.5)loadEarlier();
  },[visible?.logicalFrom,visible?.anchor,points,loadEarlier]);
  const selectKey = e=>{
    interacted.current=true;
    const next={ArrowLeft:index-1,ArrowDown:index-1,ArrowRight:index+1,ArrowUp:index+1,Home:0,End:points.length-1};
    if(e.key in next){
      e.preventDefault();
      const chosen=Math.max(0,Math.min(points.length-1,next[e.key]));
      setSelected(points[chosen].date);
      if(chosen<from||chosen>to){
        const span=to-from;
        const first=Math.max(0,Math.min(points.length-1-span,chosen<from?chosen:chosen-span));
        setFocus({from:spec.series[0].data[first].time,to:spec.series[0].data[first+span].time,token:chosen});
      }
    }
    if(e.key==='Escape')setSelected(null);
  };
  return <>
    <div className="cbu-readout" data-testid="history-readout" aria-live="off">
      <span>{dateLabel(point.date,language,true)}</span>
      <strong>{Number.isFinite(point.value)?`${number(point.value)} UZS`:t.unavailable}</strong>
      <small>{point.effective_date && point.effective_date!==point.date?`${t.effective} ${dateLabel(point.effective_date,language,true)}`:'\u00a0'}</small>
    </div>
    <div className="cbu-plot" role="slider" tabIndex={0} aria-orientation="horizontal"
      aria-label={`${t.inspect}, ${data.ccy}/UZS. ${t.keys}`} aria-valuemin={0} aria-valuemax={points.length-1}
      aria-valuenow={index} aria-valuetext={valueText} onKeyDown={selectKey}
      onPointerDown={()=>{interacted.current=true;}} onWheelCapture={e=>{if(e.ctrlKey)interacted.current=true;}} data-segments={spec.series.length-1}>
      <LwCanvas spec={spec} height={220} lang={language} viewKey={`${data.ccy}:${data.days}:${data.start}:${data.end}`}
        resetToken={resetToken} focus={focus} initialView={initialView} preserveTimeOnPrepend aria-hidden="true"
        onHover={reading=>setSelected(reading?points[reading.index]?.date:null)} onClick={reading=>setSelected(points[reading.index]?.date)}
        onRange={range=>setVisible(current=>current?.from===range.from&&current?.to===range.to&&current?.changed===range.changed&&current?.logicalFrom===range.logicalFrom&&current?.anchor===points[0].date?current:{...range,anchor:points[0].date,fromDate:points[range.from].date,toDate:points[range.to].date})}/>
    </div>
    <div className="cbu-navigation">
      <span data-testid="history-visible-range" data-from={points[from].date} data-to={points[to].date}>
        {dateLabel(points[from].date,language)} – {dateLabel(points[to].date,language)}
      </span>
      <button type="button" disabled={!visible?.changed} onClick={()=>{interacted.current=false;setSelected(null);setFocus(null);setResetToken(n=>n+1);}}>{t.reset}</button>
    </div>
    {earlier.status!=='idle'&&<div className="cbu-gaps" role="status">
      <span>{earlier.status==='loading'?t.earlierLoading:t.earlierError}</span>
      {earlier.status==='error'&&<button aria-label={t.earlierRetry} onClick={earlier.retry}>{t.retry}</button>}
    </div>}
    <p className="cbu-hint">{touch?t.touchHint:t.desktopHint}</p>
  </>;
}

function HistoryData({ccy, period, language, t}) {
  const [state,setState]=useState({loading:true}),[attempt,setAttempt]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    let timer;
    setState(current=>current.data?{...current,refreshing:true}:{loading:true});
    fetch(`/api/currency/history?ccy=${encodeURIComponent(ccy)}&days=${period}`,{signal:controller.signal,cache:'no-cache'})
      .then(async response=>{if(!response.ok)throw Error('history');return response.json();})
      .then(data=>{
        if(controller.signal.aborted)return;
        setState({data});
        // Continue a cold range in bounded batches while keeping available data visible.
        if(data.pending_days>0 && attempt<5)timer=setTimeout(()=>setAttempt(n=>n+1),1000);
      })
      .catch(()=>{if(!controller.signal.aborted)setState({error:true});});
    return ()=>{controller.abort();clearTimeout(timer);};
  },[ccy,period,attempt]);
  if(state.loading)return <p className="cbu-state" role="status">{t.loading}</p>;
  const data=state.data;
  if(!data?.points?.some(p=>Number.isFinite(p.value)))return <div className="cbu-state" role="status"><p>{t.empty}</p><button className="ghost-btn" onClick={()=>setAttempt(n=>n+1)}>{t.retry}</button></div>;
  const summary=data.summary;
  const signed=value=>`${value>0?'+':value<0?'−':''}${formatRatio(Math.abs(value),2,language)}`;
  return <>
    <p className="cbu-rate-basis">{t.official}</p>
    <div className="cbu-latest"><span>UZS · {t.unit} {ccy}</span><strong data-testid="history-latest">{formatRatio(summary.latest,2,language)}</strong><small>{t.latest} · {dateLabel(summary.latest_date,language,true)}</small></div>
    <div className="cbu-change" data-testid="history-change">
      {Number.isFinite(summary.change)?<><strong>{signed(summary.change)} UZS <span>({signed(summary.change_pct)}%)</span></strong><small>{t.period}</small></>:<small>{t.changeMissing}</small>}
    </div>
    <HistoryPlot data={data} language={language} t={t}/>
    {data.missing_days>0&&<div className="cbu-gaps" role="status"><span>{data.pending_days>0&&attempt<5?t.loading:t.gaps(data.missing_days)}</span>{!(data.pending_days>0&&attempt<5)&&<button disabled={state.refreshing} onClick={()=>setAttempt(n=>n+1)}>{t.retry}</button>}</div>}
    <footer className="cbu-source"><a href="https://cbu.uz/ru/arkhiv-kursov-valyut/" target="_blank" rel="noreferrer">{t.source} ↗</a></footer>
  </>;
}

export function CbuRateHistory({language,ccy}) {
  const t=copy[language]||copy.ru;
  const mobile=useMediaQuery('(max-width: 760px)');
  const [expanded,setExpanded]=useState(false),[period,setPeriod]=useState(30);
  const open=!mobile||expanded;
  return <details className="concept-card cbu-history" data-testid="cbu-history" open={open} onToggle={e=>{if(mobile)setExpanded(e.currentTarget.open);}}>
    <summary>{t.short}</summary>
    {open&&<div className="cbu-body"><header className="cbu-heading"><h2>{t.title}</h2><span>{ccy}/UZS</span></header>
      <div className="cbu-period" role="group" aria-label={t.range}>{[[7,'1W'],[30,'1M'],[180,'6M']].map(([days,label])=><button key={days} aria-pressed={period===days} onClick={()=>setPeriod(days)}>{label}</button>)}</div>
      <HistoryData key={`${ccy}:${period}`} ccy={ccy} period={period} language={language} t={t}/>
    </div>}
  </details>;
}
