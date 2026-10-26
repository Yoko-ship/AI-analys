import React from 'react';
import {HomeMarketDashboard} from './HomeMarketDashboard.jsx';
import {CurrencyCard,UpcomingEventsCard,WatchlistCard} from './DashboardCards.jsx';
import {prepareMarketRows} from '../../lib/marketData.js';
import {buildMarketStats,marketDisplayPrice} from '../../shared/marketModel.jsx';
import {marketRowDay} from '../../lib/valuation.js';
import {CHANGE_PERIODS,CHANGE_PERIOD_KEY,changePeriodLabel} from '../../shared/marketPeriods.jsx';
import {MarketMovers} from '../market/index.js';
import {price,pct,compact} from '../../lib/format.js';
import {edHeadline,newsRelTime} from '../news/index.js';
function Spark({values}){const nums=(values||[]).map(p=>p[1]).filter(Number.isFinite);if(nums.length<2)return <span>—</span>;const lo=Math.min(...nums),range=Math.max(...nums)-lo||1;return <svg className="concept-spark" viewBox="0 0 100 28" aria-hidden="true"><polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={nums.map((v,i)=>`${2+i/(nums.length-1)*96},${25-(v-lo)/range*22}`).join(' ')}/></svg>;}
export function LandingView({language,marketRows,tradeStats,securitiesMap,companies,onNavigate,onOpenCompany,onOpenNews,favorites,onCalendar}){
 const lang=['ru','en','uz'].includes(language)?language:'ru',t=(ru,en,uz)=>lang==='en'?en:lang==='uz'?uz:ru;
 const prepared=React.useMemo(()=>prepareMarketRows(marketRows,tradeStats),[marketRows,tradeStats]);
 const stats=React.useMemo(()=>buildMarketStats(prepared),[prepared]);
 const [period,setPeriod]=React.useState(()=>{const p=localStorage.getItem(CHANGE_PERIOD_KEY);return CHANGE_PERIODS.some(v=>v.code===p)?p:'1d';});
 const [changes,setChanges]=React.useState({}),[direction,setDirection]=React.useState('all'),[spark,setSpark]=React.useState({}),[news,setNews]=React.useState([]),[newsError,setNewsError]=React.useState(false),[leaders,setLeaders]=React.useState(false);
 React.useEffect(()=>{localStorage.setItem(CHANGE_PERIOD_KEY,period);if(period==='1d')return;const c=new AbortController();fetch('/api/market/changes',{signal:c.signal}).then(r=>r.json()).then(d=>setChanges(d.changes||{})).catch(()=>{});return()=>c.abort();},[period]);
 React.useEffect(()=>{const c=new AbortController();fetch('/api/news/feed?limit=6&days=30',{signal:c.signal}).then(async r=>{if(!r.ok)throw Error();return r.json();}).then(d=>setNews(d.items||[])).catch(e=>{if(e.name!=='AbortError')setNewsError(true);});return()=>c.abort();},[]);
 const board=prepared.filter(r=>r.type!=='bond'&&(!stats.boardDay||marketRowDay(r)===stats.boardDay)&&marketDisplayPrice(r)!=null).sort((a,b)=>(b.stockVolume||0)-(a.stockVolume||0));
 const tickers=board.slice(0,9).map(r=>r.ticker).join(',');
 React.useEffect(()=>{if(!tickers)return;const c=new AbortController();fetch(`/api/quotes/series?tickers=${encodeURIComponent(tickers)}&days=30`,{signal:c.signal}).then(r=>r.json()).then(d=>setSpark(d.series||{})).catch(()=>{});return()=>c.abort();},[tickers]);
 const shownPct=r=>period==='1d'?r.changePercent:changes[r.ticker]?.[period]?.pct??null;
 const movers=period==='1d'?stats:buildMarketStats(prepared.map(r=>({...r,changePercent:shownPct(r),stockVolume:changes[r.ticker]?.stats?.[period]?.value??null})),{windowed:true});
 const nameOf=r=>securitiesMap?.[r.ticker]?.name||companies.find(c=>c.ticker===r.ticker)?.company_name||r.name||r.ticker;
 return <div className="landing-view concept-home reference-home">
 <header className="concept-page-heading"><div><span className="hd-eyebrow">UZSTOCK · {t('АНАЛИТИЧЕСКАЯ ПЛАТФОРМА','MARKET INTELLIGENCE','BOZOR TAHLILI')}</span><h1 className="lv-h1">{t('Обзор фондового рынка Узбекистана','Uzbekistan stock market overview','O‘zbekiston fond bozori sharhi')}</h1><p>{t('Котировки, динамика эмитентов, новости и корпоративные события — в едином рабочем пространстве.','Quotes, issuer performance, news and corporate events in one workspace.','Kotirovkalar, emitentlar dinamikasi, yangiliklar va korporativ voqealar — bir joyda.')}</p></div></header>
 <HomeMarketDashboard rows={prepared} stats={stats} companies={companies} securitiesMap={securitiesMap||{}} language={lang} onOpenCompany={onOpenCompany} onNavigate={onNavigate} period={period} onPeriod={setPeriod} changes={changes}/>
 <div className="concept-content-grid">
 <section className="concept-card" data-testid="home-market-table"><header><div><h2>{t('Рынок сегодня','Market today','Bugungi bozor')}</h2><p>{t('Последняя торговая сессия','Latest trading session','Oxirgi savdo sessiyasi')}</p></div><div className="concept-segment">{[['all',t('Все','All','Barchasi')],['gain',t('Растут','Gainers','O‘sish')],['loss',t('Снижаются','Decliners','Pasayish')]].map(([v,label])=><button key={v} aria-pressed={direction===v} onClick={()=>setDirection(v)}>{label}</button>)}</div></header>
 <div className="lv-period" role="group" aria-label={t('Период изменения','Change period','O‘zgarish davri')}>{CHANGE_PERIODS.map(p=><button key={p.code} aria-pressed={period===p.code} onClick={()=>setPeriod(p.code)}>{changePeriodLabel(p.code,lang)}</button>)}</div>
 <div className="concept-table-scroll"><table className="concept-table lv-table"><thead><tr><th>{t('Тикер / эмитент','Ticker / issuer','Tiker / emitent')}</th><th>{t('Цена, сум','Price, UZS','Narx, so‘m')}</th><th>{t('Изм.','Change','O‘zg.')}</th><th>{t('Объём','Turnover','Hajm')}</th><th>30D</th></tr></thead><tbody>{board.filter(r=>direction==='all'||(direction==='gain'?shownPct(r)>0:shownPct(r)<0)).slice(0,9).map(r=><tr key={r.ticker}><td><button className="concept-security" onClick={()=>onOpenCompany(r.ticker)}><strong>{r.ticker}</strong><span>{nameOf(r)}</span></button></td><td>{price(marketDisplayPrice(r),lang)}</td><td className={shownPct(r)>0?'is-up':shownPct(r)<0?'is-down':''}>{Number.isFinite(shownPct(r))?pct(shownPct(r),lang,2):'—'}</td><td>{compact(r.stockVolume,lang)}</td><td><Spark values={spark[r.ticker]}/></td></tr>)}</tbody></table></div>
 {!board.length&&<p>{t('Котировки пока недоступны.','Quotes are not available yet.','Kotirovkalar hozircha mavjud emas.')}</p>}
 <footer><button className="concept-link" onClick={()=>setLeaders(!leaders)} aria-expanded={leaders}>{t('Лидеры рынка','Market leaders','Bozor yetakchilari')}</button><button className="concept-link" onClick={()=>onNavigate('market')}>{t('Все инструменты','All securities','Barcha qog‘ozlar')} →</button></footer>
 {leaders&&<div className="market-layout lv-movers"><MarketMovers viewMode="table" periodMovers={movers} lang={lang} changePeriod={period} onOpenCompany={onOpenCompany} smap={securitiesMap||{}}/></div>}</section>
 <aside className="concept-stack" data-testid="home-personal-sidebar"><WatchlistCard language={lang} favorites={favorites} marketRows={marketRows} securitiesMap={securitiesMap} onOpenCompany={onOpenCompany} onNavigate={onNavigate}/><CurrencyCard language={lang} onNavigate={onNavigate}/></aside>
 </div>
 <div className="concept-two-grid" data-testid="landing-updates"><section className="concept-card" data-testid="home-focus-news"><header><div><h2>{t('В фокусе','In focus','Diqqat markazida')}</h2><p>{t('Новости и аналитические материалы','News and analysis','Yangiliklar va tahlil')}</p></div><button className="concept-link" onClick={()=>onNavigate('news')}>{t('Все новости','All news','Barcha yangiliklar')} →</button></header>{news.slice(0,4).map(n=><button key={n.id} className="concept-news-row" onClick={()=>onOpenNews(n)}><span className="concept-icon">↗</span><span><strong>{edHeadline(n,lang).text}</strong><small>{newsRelTime(n.published_at,lang)}</small></span><span>→</span></button>)}{!news.length&&<p>{newsError?t('Новости недоступны.','News unavailable.','Yangiliklar mavjud emas.'):t('Нет опубликованных материалов.','No published stories.','E’lon qilingan yangiliklar yo‘q.')}</p>}</section><UpcomingEventsCard language={lang} onCalendar={onCalendar}/></div>
 </div>;
}
