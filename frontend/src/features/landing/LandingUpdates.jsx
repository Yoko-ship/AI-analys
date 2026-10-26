import React from 'react';
import { addDays, tashkentToday, formatDay, eventTitle, NEWSCAL_TX } from '../news/index.js';
import { profileMarketQuote } from '../../shared/marketModel.jsx';
import { formatMarketNumber, formatSignedPercent } from '../../shared/format.jsx';
import './landing-updates.css';

export function LandingUpdates({ language, favorites = [], marketRows, securitiesMap, onOpenCompany, onCalendar, onNavigate }) {
  const lang=['ru','en','uz'].includes(language)?language:'ru';
  const t=(ru,en,uz)=>lang==='en'?en:lang==='uz'?uz:ru;
  const [events,setEvents]=React.useState([]),[status,setStatus]=React.useState('loading'),[reload,setReload]=React.useState(0);
  const locale=lang==='en'?'en-US':lang==='uz'?'uz-UZ':'ru-RU';
  React.useEffect(()=>{
    const controller=new AbortController(),today=tashkentToday();
    setStatus('loading');
    fetch(`/api/news/calendar/events?start=${today}&end=${addDays(today,60)}&types=meeting,dividend`,{signal:controller.signal})
      .then(async r=>{const data=await r.json();if(!r.ok||!data.ok)throw Error();return data;})
      .then(data=>{setEvents(data.items.slice(0,4));setStatus(Object.values(data.sources||{}).some(s=>s.ok===false)?'partial':'ready');})
      .catch(e=>{if(e.name!=='AbortError')setStatus('error');});
    return ()=>controller.abort();
  },[reload]);
  return <section className="lv-sec" data-testid="landing-updates"><div className="lv-container lv-wide lu-grid">
    <section className="lu-card"><header><h2>{t('Ближайшие события','Upcoming events','Yaqin voqealar')}</h2><button type="button" onClick={onCalendar}>{t('Календарь событий','Event calendar','Voqealar taqvimi')} <span aria-hidden="true">→</span></button></header>
      {status==='loading'?<p role="status">{t('Загрузка…','Loading…','Yuklanmoqda…')}</p>:status==='error'?<p role="alert">{t('События временно недоступны.','Events temporarily unavailable.','Voqealar vaqtincha mavjud emas.')} <button type="button" onClick={()=>setReload(n=>n+1)}>{t('Повторить','Retry','Qayta urinish')}</button></p>:<>
        {status==='partial'&&<p>{t('Часть источников недоступна.','Some sources are unavailable.','Ayrim manbalar mavjud emas.')}</p>}
        {events.length?events.map(ev=><button type="button" className="lu-event" key={ev.id} onClick={onCalendar}>
          <time dateTime={ev.date}>{formatDay(ev.date,locale,{day:'numeric',month:'short'})}</time>
          <span><strong>{ev.organization||ev.ticker}</strong><small>{eventTitle(ev,lang,NEWSCAL_TX[lang],locale)}</small></span>
        </button>):<p>{t('Нет опубликованных событий на ближайшие 60 дней.','No published events in the next 60 days.','Yaqin 60 kun uchun e’lon qilingan voqealar yo‘q.')}</p>}
      </>}
      <p>{t('Только даты, опубликованные эмитентами.','Only issuer-published dates.','Faqat emitentlar e’lon qilgan sanalar.')}</p>
    </section>
    <section className="lu-card"><header><h2>{t('Моё избранное','My watchlist','Mening tanlanganlarim')}</h2><button type="button" onClick={()=>onNavigate('profile')}>{t('Управлять','Manage','Boshqarish')} →</button></header>
      {favorites.length?favorites.slice(0,5).map(item=>{const quote=profileMarketQuote(item.ticker,marketRows,securitiesMap);return <button type="button" className="lu-watch" key={item.ticker} onClick={()=>onOpenCompany(item.ticker)}><span><strong>{item.ticker}</strong><small>{item.company_name||''}</small></span><span>{formatMarketNumber(quote.price,lang)}<small>{formatSignedPercent(quote.change,2)}</small></span></button>;}):<p>{t('Добавьте компании в избранное, чтобы видеть их здесь.','Add companies to your watchlist to see them here.','Kompaniyalarni bu yerda ko‘rish uchun tanlanganlarga qo‘shing.')}</p>}
      <button className="ghost-btn" type="button" onClick={()=>onNavigate('market')}>{t('Найти компанию','Find a company','Kompaniya topish')} →</button>
    </section>
  </div></section>;
}
