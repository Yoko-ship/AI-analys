import {useEffect,useState} from 'react';
import {addDays,tashkentToday,formatDay,eventTitle} from './calendarEvents.js';
import {NEWSCAL_TX} from './calendarCopy.js';
export function UpcomingEventsCard({language,onCalendar}){
 const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 const [events,setEvents]=useState([]),[status,setStatus]=useState('loading'),[reload,setReload]=useState(0);
 useEffect(()=>{const c=new AbortController(),today=tashkentToday();fetch(`/api/news/calendar/events?start=${today}&end=${addDays(today,60)}&types=meeting,dividend`,{signal:c.signal}).then(async r=>{const d=await r.json();if(!r.ok||!d.ok)throw Error();return d;}).then(d=>{setEvents(d.items||[]);setStatus('ready');}).catch(e=>{if(e.name!=='AbortError')setStatus('error');});return()=>c.abort();},[reload]);
 const locale=language==='en'?'en-US':language==='uz'?'uz-UZ':'ru-RU';
 return <section className="concept-card event-preview"><header><div><h2>{t('Календарь событий','Upcoming events','Voqealar taqvimi')}</h2><p>{t('Опубликованные даты эмитентов','Issuer-published dates','Emitentlar e’lon qilgan sanalar')}</p></div><button className="concept-link" onClick={onCalendar}>{t('Календарь','Calendar','Taqvim')} →</button></header>
 {status==='loading'?<p role="status">{t('Загрузка…','Loading…','Yuklanmoqda…')}</p>:status==='error'?<p role="alert">{t('События временно недоступны.','Events temporarily unavailable.','Voqealar vaqtincha mavjud emas.')} <button onClick={()=>setReload(n=>n+1)}>{t('Повторить','Retry','Qayta urinish')}</button></p>:events.length?events.slice(0,5).map(ev=><button className="concept-event-row" key={ev.id} onClick={onCalendar}><time dateTime={ev.date}>{formatDay(ev.date,locale,{day:'numeric',month:'short'})}</time><span><strong>{ev.organization||ev.ticker}</strong><small>{eventTitle(ev,language,NEWSCAL_TX[language]||NEWSCAL_TX.ru,locale)}</small></span><span className="concept-badge">{ev.type==='meeting'?t('Собрание','Meeting','Yig‘ilish'):t('Выплата','Payment','To‘lov')}</span></button>):<p>{t('Нет опубликованных событий на ближайшие 60 дней.','No published events in the next 60 days.','Yaqin 60 kun uchun voqealar yo‘q.')}</p>}
 </section>;
}
