import {useState,useEffect,useRef} from 'react';
import {MarketHeatmap} from '../market/index.js';
import {sectorOf} from '../../lib/sectors.js';
import {sectorLabel} from '../../shared/marketCopy.jsx';
import {CHANGE_PERIODS,changePeriodLabel} from '../../shared/marketPeriods.jsx';
export function HomeMarketDashboard({rows,stats,companies,securitiesMap,language,onOpenCompany,onNavigate,period,onPeriod,changes}){
 const [query,setQuery]=useState(''),[sector,setSector]=useState(''),[mapData,setMapData]=useState(null),[expanded,setExpanded]=useState(false);
 const panel=useRef(null);const lang=language;const t=(ru,en,uz)=>lang==='en'?en:lang==='uz'?uz:ru;
 useEffect(()=>{const c=new AbortController();fetch('/api/heatmap',{signal:c.signal}).then(r=>r.json()).then(d=>{if(d.ok)setMapData(d);}).catch(()=>{});return()=>c.abort();},[]);
 useEffect(()=>{if(!expanded)return;const close=e=>{if(e.key==='Escape')setExpanded(false);};window.addEventListener('keydown',close);return()=>window.removeEventListener('keydown',close);},[expanded]);
 const companyMap=Object.fromEntries((companies||[]).map(c=>[c.ticker,c]));
 const sectors=[...new Set(rows.map(r=>sectorOf(r.ticker,securitiesMap,companyMap)))];
 const visible=rows.filter(r=>r.type!=='bond'&&(!sector||sectorOf(r.ticker,securitiesMap,companyMap)===sector)&&`${r.ticker} ${r.name||''} ${companyMap[r.ticker]?.company_name||''}`.toLowerCase().includes(query.toLowerCase())).map(r=>period==='1d'?r:{...r,changePercent:changes[r.ticker]?.[period]?.pct??null,stockVolume:changes[r.ticker]?.stats?.[period]?.value??null});
 return <section className="hd-dashboard" data-testid="home-market-dashboard">
 <div className="hd-stats">{[[t('Бумаги на рынке','Market securities','Bozordagi qog‘ozlar'),rows.filter(r=>r.type!=='bond').length],[t('Бумаги в плюсе','Gainers','O‘sayotganlar'),stats.advancers],[t('Бумаги в минусе','Decliners','Pasayayotganlar'),stats.decliners],[t('Без изменения','Unchanged','O‘zgarmaganlar'),stats.unchanged]].map(([label,value])=><article key={label}><span>{label}</span><strong>{rows.length?value:'—'}</strong><small>{(stats.boardDay?.length===8?`${stats.boardDay.slice(6,8)}.${stats.boardDay.slice(4,6)}.${stats.boardDay.slice(0,4)}`:stats.boardDay)||t('Ожидание котировок','Waiting for quotes','Kotirovkalar kutilmoqda')}</small></article>)}</div>
 <section ref={panel} className={`hd-map-card${expanded?' is-expanded':''}`}>
 <header><div><span className="hd-eyebrow">{t('Визуальная аналитика','Visual analytics','Vizual tahlil')}</span><h2>{t('Карта рынка · тепловая карта','Market map · heatmap','Bozor xaritasi')}</h2></div><div><button className="ghost-btn" type="button" onClick={()=>onNavigate('heatmap')}>{t('Весь рынок','Full market','Butun bozor')} →</button><button className="ghost-btn" type="button" aria-pressed={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?t('Свернуть','Collapse','Yig‘ish'):t('Развернуть','Expand','Kengaytirish')}</button></div></header>
 <div className="hd-toolbar"><input type="search" aria-label={t('Поиск на карте','Search map','Xaritada qidirish')} placeholder={t('Тикер или эмитент','Ticker or issuer','Tiker yoki emitent')} value={query} onChange={e=>setQuery(e.target.value)}/>
 <select aria-label={t('Отрасль на карте','Map sector','Xarita tarmog‘i')} value={sector} onChange={e=>setSector(e.target.value)}><option value="">{t('Все отрасли','All sectors','Barcha tarmoqlar')}</option>{sectors.map(s=><option key={s} value={s}>{sectorLabel(lang,s)}</option>)}</select>
 <select aria-label={t('Период карты','Map period','Xarita davri')} value={period} onChange={e=>onPeriod(e.target.value)}>{CHANGE_PERIODS.map(p=><option key={p.code} value={p.code}>{changePeriodLabel(p.code,lang)}</option>)}</select>
 <button className="ghost-btn" type="button" onClick={()=>onNavigate('market')}>{t('Таблица и скринер','Table & screener','Jadval va skriner')} →</button></div>
 {rows.length&&!visible.length?<p>{t('Нет бумаг по выбранным фильтрам.','No securities match these filters.','Filtrlarga mos qog‘ozlar yo‘q.')}</p>:<MarketHeatmap rows={visible} companies={companies} securitiesMap={securitiesMap} language={lang} onOpenCompany={onOpenCompany} type="stock" mapData={mapData} stats={stats} period={period} initialArea="turnover"/>}
 </section></section>;
}
