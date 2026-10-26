import {useEffect,useState} from 'react';
import {formatMarketNumber,formatSignedPercent} from '../../shared/format.jsx';
import {profileMarketQuote} from '../../shared/marketModel.jsx';
export {UpcomingEventsCard} from '../news/index.js';
export function WatchlistCard({language,favorites=[],marketRows,securitiesMap,onOpenCompany,onNavigate}){
 const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 return <section className="concept-card"><header><div><h2>{t('Моё избранное','My watchlist','Mening tanlanganlarim')}</h2><p>{t('Ваши бумаги','Your securities','Sizning qog‘ozlaringiz')}</p></div><button className="concept-link" onClick={()=>onNavigate('profile')}>{t('Управлять','Manage','Boshqarish')} →</button></header>
 {favorites.length?favorites.slice(0,5).map(f=>{const q=profileMarketQuote(f.ticker,marketRows,securitiesMap);return <button className="concept-watch-row" key={f.ticker} onClick={()=>onOpenCompany(f.ticker)}><span className="concept-icon">{f.ticker.slice(0,2)}</span><span><strong>{f.ticker}</strong><small>{f.company_name}</small></span><span><b>{formatMarketNumber(q.price,language)}</b><small className={q.change>0?'is-up':q.change<0?'is-down':''}>{formatSignedPercent(q.change,2)}</small></span></button>;}):<p>{t('Добавьте компании в избранное, чтобы видеть их здесь.','Add companies to your watchlist to see them here.','Kompaniyalarni tanlanganlarga qo‘shing.')}</p>}
 <button className="concept-link" onClick={()=>onNavigate('market')}>{t('Найти компанию','Find a company','Kompaniya topish')} →</button></section>;
}
export function CurrencyCard({language,onNavigate}){
 const [data,setData]=useState(null),[error,setError]=useState(false);const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 useEffect(()=>{const c=new AbortController();fetch('/api/currency/rates',{signal:c.signal}).then(async r=>{if(!r.ok)throw Error();return r.json();}).then(d=>setData(d)).catch(e=>{if(e.name!=='AbortError')setError(true);});return()=>c.abort();},[]);
 return <section className="concept-card" data-testid="home-currency-card"><header><div><h2>{t('Курсы валют','Exchange rates','Valyuta kurslari')}</h2><p>{t('Центральный банк','Central Bank','Markaziy bank')}{data?.date?` · ${data.date}`:''}</p></div><button className="concept-link" onClick={()=>onNavigate('bankfx')}>{t('Банки и конвертер','Banks & converter','Banklar va konverter')} →</button></header>
 {(data?.rates||[]).filter(r=>['USD','EUR','RUB','CNY'].includes(r.ccy)).map(r=><div className="concept-currency-row" key={r.ccy}><b>{r.nominal>1?`${r.nominal} `:''}{r.ccy}/UZS</b><strong>{formatMarketNumber(r.rate,language)}</strong></div>)}
 {!data&&<p role="status">{error?t('Курсы недоступны.','Rates unavailable.','Kurslar mavjud emas.'):t('Загрузка…','Loading…','Yuklanmoqda…')}</p>}</section>;
}
