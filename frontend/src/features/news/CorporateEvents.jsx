import { CorporateStoryMedia } from './CorporateStoryMedia.jsx';
import { CorporateEventArticle } from './CorporateEventArticle.jsx';
import { SourceDateEvidence } from './SourceDateEvidence.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { interceptNav } from './editorial.jsx';
import { localizedPath } from '../../lib/languagePath.js';
import { safeHref } from '../../lib/safeHref.js';
import { addDays, tashkentToday, formatDay } from './calendarEvents.js';
import './corporate-events.css';
import {rankEvent} from './eventPersonalization.js';

const COPY = {
  ru: { title:'Корпоративные события', search:'Компания, тикер или ISIN', sort:'Порядок событий', recent:'По времени', priority:'По важности', subscriptions:'Сначала мои компании', from:'Опубликовано с', to:'По', filters:'Расширенные фильтры', code:'Тип по OpenInfo', any:'Все', security:'Вид бумаги', ordinary:'Простые акции', preferred:'Привилегированные акции', share:'Акции (класс не указан)', bond:'Облигации', published:'Опубликовано', decision:'Решение принято', event:'Дата события', payment_start:'Начало окна выплат', payment_end:'Конец окна выплат', source:'Первоисточник OpenInfo', documents:'Документы и история', docCount:'док.', close:'Закрыть', review:'Проверяется', confirmed:'Подтверждено источником', provisional:'Предварительный приоритет по типу раскрытия', note:'Краткое изложение UZStock. Официальный текст — в первоисточнике. Приоритет показывает внимание к раскрытию, а не направление цены.', proposal:'Предложение не означает утверждённую выплату.', agenda:'Вопрос в повестке не означает принятого решения.', loading:'Загрузка событий…', empty:'По выбранным фильтрам событий нет.', error:'Не удалось загрузить события.', retry:'Повторить', partial:'Часть источников временно недоступна.', reset:'Сбросить фильтры', refresh:'Проверить документ', checking:'Проверяем…', refreshError:'Документ временно недоступен. Первоначальная запись сохранена.', original:'Оригинальное название', changes:'История изменений', observed:'Обнаружено', record:'Дата права на дивиденды',unit:'сум на бумагу', stages:{approved:'Утверждено',paying:'Выплачивается',paid:'Выплачено',proposed:'Предложение',agenda:'Повестка',announced:'Объявлено',decision_disclosed:'Решение раскрыто',scheduled:'Сроки определены',accrued:'Начислено',payment_disclosed:'Данные о выплатах',disclosed:'Раскрыто'}, priorities:['Критично','Важно','Наблюдать','Справочно'] },
  en: { title:'Corporate events', search:'Company, ticker or ISIN', sort:'Event order', recent:'Latest first', priority:'By importance', subscriptions:'My companies first', from:'Published from', to:'To', filters:'Advanced filters', code:'OpenInfo type', any:'All', security:'Security class', ordinary:'Ordinary shares', preferred:'Preferred shares', share:'Shares (class unspecified)', bond:'Bonds', published:'Published', decision:'Decision made', event:'Event date', payment_start:'Payment window opens', payment_end:'Payment window ends', source:'Original on OpenInfo', documents:'Documents & history', docCount:'docs', close:'Close', review:'Under review', confirmed:'Source confirmed', provisional:'Provisional priority based on disclosure type', note:'UZStock summary. The source carries the official text. Priority indicates attention to a disclosure, not price direction.', proposal:'A proposal is not an approved payment.', agenda:'An agenda item is not a decision.', loading:'Loading events…', empty:'No events match these filters.', error:'Could not load events.', retry:'Retry', partial:'Some sources are temporarily unavailable.', reset:'Reset filters', refresh:'Check document', checking:'Checking…', refreshError:'Document temporarily unavailable. The original record is preserved.', original:'Original title', changes:'Revision history', observed:'Observed', record:'Dividend entitlement date',unit:'UZS per security', stages:{approved:'Approved',paying:'Partially paid',paid:'Paid',proposed:'Proposed',agenda:'Agenda',announced:'Announced',decision_disclosed:'Decision disclosed',scheduled:'Scheduled',accrued:'Accrued',payment_disclosed:'Payment data',disclosed:'Disclosed'}, priorities:['Critical','Important','Watch','Reference'] },
  uz: { title:'Korporativ voqealar', search:'Kompaniya, tiker yoki ISIN', sort:'Voqealar tartibi', recent:'Vaqt bo‘yicha', priority:'Muhimlik bo‘yicha', subscriptions:'Avval mening kompaniyalarim', from:'E’lon qilingan sana: dan', to:'Gacha', filters:'Qo‘shimcha filtrlar', code:'OpenInfo turi', any:'Barchasi', security:'Qimmatli qog‘oz turi', ordinary:'Oddiy aksiyalar', preferred:'Imtiyozli aksiyalar', share:'Aksiyalar (turi ko‘rsatilmagan)', bond:'Obligatsiyalar', published:'E’lon qilindi', decision:'Qaror qabul qilindi', event:'Voqea sanasi', payment_start:'To‘lov davri boshlanishi', payment_end:'To‘lov davri tugashi', source:'OpenInfo birlamchi manbasi', documents:'Hujjatlar va tarix', docCount:'hujjat', close:'Yopish', review:'Tekshirilmoqda', confirmed:'Manba tasdiqlagan', provisional:'Ma’lumot turi bo‘yicha dastlabki ustuvorlik', note:'UZStock qisqa bayoni. Rasmiy matn birlamchi manbada. Ustuvorlik narx yo‘nalishini emas, voqeaga e’tiborni bildiradi.', proposal:'Taklif tasdiqlangan to‘lov degani emas.', agenda:'Kun tartibidagi masala qabul qilingan qaror emas.', loading:'Voqealar yuklanmoqda…', empty:'Ushbu filtrlarga mos voqealar yo‘q.', error:'Voqealarni yuklab bo‘lmadi.', retry:'Qayta urinish', partial:'Ayrim manbalar vaqtincha mavjud emas.', reset:'Filtrlarni tozalash', refresh:'Hujjatni tekshirish', checking:'Tekshirilmoqda…', refreshError:'Hujjat vaqtincha mavjud emas. Asl yozuv saqlangan.', original:'Asl sarlavha', changes:'O‘zgarishlar tarixi', observed:'Aniqlandi', record:'Dividend huquqi sanasi',unit:'so‘m / qimmatli qog‘oz', stages:{approved:'Tasdiqlandi',paying:'Qisman to‘landi',paid:'To‘landi',proposed:'Taklif',agenda:'Kun tartibi',announced:'E’lon qilindi',decision_disclosed:'Qaror e’lon qilindi',scheduled:'Muddatlar belgilandi',accrued:'Hisoblandi',payment_disclosed:'To‘lov ma’lumotlari',disclosed:'E’lon qilindi'}, priorities:['Jiddiy','Muhim','Kuzatish','Ma’lumot'] },
};
const DETAIL_COPY = {
  ru: { back: 'К корпоративным новостям', missing: 'Событие не найдено.', latest: 'Последние раскрытия', count: 'событий' },
  en: { back: 'Back to corporate news', missing: 'Event not found.', latest: 'Latest disclosures', count: 'events' },
  uz: { back: 'Korporativ yangiliklarga qaytish', missing: 'Voqea topilmadi.', latest: 'So‘nggi oshkor qilishlar', count: 'voqea' },
};
const pick = (value, lang) => typeof value === 'string' ? value : value?.[lang] || value?.ru || '';
function Amounts({ document, tx, locale }) {
  return <div className="ce-amounts">{(document.amounts || []).map(a => <span key={a.security}>{tx[a.security] || a.security}: <strong>{new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(a.amount)}</strong> {tx.unit}</span>)}</div>;
}
function Evidence({ document: d, tx, lang, locale, hideIntro = false }) {
  return <>
    {!hideIntro && <><span className="ce-stage">{tx.stages[d.stage] || tx.review}</span><h3>{pick(d.title, lang)}</h3></>}
    {d.stage === 'proposed' && <p className="ce-caution">{tx.proposal}</p>}
    {d.stage === 'agenda' && <p className="ce-caution">{tx.agenda}</p>}
    {!hideIntro&&d.summary&&<p>{pick(d.summary,lang)}</p>}
    {d.priority_explanation&&<p className="ce-priority-explanation"><b>P{d.priority} · </b>{pick(d.priority_explanation,lang)}</p>}
    {d.facts?.length>0&&<dl className="ce-extracted-fields">{d.facts.map(f=><div key={f.source_field}><dt>{pick(f.label,lang)}</dt><dd>{typeof f.value==='number'?new Intl.NumberFormat(locale,{maximumFractionDigits:6}).format(f.value):f.value}{f.unit==='percent'?'%':f.unit==='thousand_uzs'?` ${lang==='en'?'thousand UZS':lang==='uz'?'ming so‘m':'тыс. сум'}`:f.unit==='source_units'?` (${lang==='en'?'source units':lang==='uz'?'manba birliklari':'единицы источника'})`:f.unit==='uzs_per_security'?` ${tx.unit}`:''}</dd></div>)}</dl>}
    <Amounts document={d} tx={tx} locale={locale} />
    {d.isins?.length>0&&<p>ISIN: {d.isins.join(', ')}</p>}
    {d.payment&&<dl className="ce-dates">{[['calculated',lang==='en'?'Accrued':lang==='uz'?'Hisoblangan':'Начислено'],['paid',lang==='en'?'Paid':lang==='uz'?'To‘langan':'Выплачено'],['debt',lang==='en'?'Outstanding':lang==='uz'?'Qarzdorlik':'Задолженность']].map(([key,label])=><div key={key}><dt>{label}</dt><dd>{d.payment[key]==null?'—':new Intl.NumberFormat(locale).format(d.payment[key]).replaceAll('\u00a0',' ')} {lang==='en'?'thousand UZS':lang==='uz'?'ming so‘m':'тыс. сум'}</dd></div>)}</dl>}
    {d.capitalization_disclosed&&<p className="ce-caution">{lang==='en'?'The decision includes dividend capitalization; it is not all cash income.':lang==='uz'?'Qarorda dividend kapitalizatsiyasi bor; hammasi pul daromadi emas.':'Решение включает капитализацию дивидендов; это не только денежная выплата.'}</p>}
    {d.evidence?.length>0&&<details><summary>{lang==='en'?'Source wording':lang==='uz'?'Manbadagi matn':'Формулировки первоисточника'}</summary>{d.evidence.map((text,i)=><blockquote key={i}>{text}</blockquote>)}</details>}
    <dl className="ce-dates">{[['published_at','published'],['event_date','event'],['decision_date','decision'],['payment_start','payment_start'],['payment_end','payment_end'],['record_date','record']].filter(([key])=>d[key]).map(([key,label]) => <div key={key}><dt>{tx[label]}</dt><dd>{formatDay(d[key].slice(0,10),locale)}</dd></div>)}</dl>
    {d.meeting_time && <p className="ce-meeting-time">{tx.event}: {d.meeting_time} (UTC+5)</p>}
    <SourceDateEvidence document={d} language={lang} />
    <p className="ce-confidence">{d.confidence === 'confirmed' ? tx.confirmed : tx.review}{d.code ? ` · OpenInfo № ${d.code}` : ''}</p>
    {d.original_title && <p className="ce-original"><b>{tx.original}:</b> {d.original_title}</p>}
    <a href={safeHref(d.source_url)} target="_blank" rel="noreferrer">{tx.source} ↗</a>
    {d.pdf_url && <a href={safeHref(d.pdf_url)} target="_blank" rel="noreferrer">PDF ↗</a>}
  </>;
}
function StoryDialog({ story, onClose, tx, lang, locale, onUpdated }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog=ref.current;
    const previous=document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
  return createPortal(<dialog ref={ref} className="ce-dialog" aria-labelledby="ce-dialog-title" onCancel={onClose} onClick={e=>{ if(e.target===e.currentTarget) onClose(); }}>
    <header><div><span className="ce-eyebrow">{tx.documents}</span><h2 id="ce-dialog-title">{story.organization}</h2></div><button type="button" className="ghost-btn" onClick={onClose}>{tx.close} ×</button></header>
    <StoryDocuments story={story} tx={tx} lang={lang} locale={locale} onUpdated={onUpdated} />
    <p className="ce-note">{tx.note}</p>
  </dialog>, document.body);
}
function StoryDocuments({ story, tx, lang, locale, onUpdated, article = false }) {
  const [documents,setDocuments] = useState(story.documents?.length?story.documents:[story]);
  const [busy,setBusy] = useState('');
  const [error,setError] = useState(false);
  const refresh = async d => {
    setBusy(d.id); setError(false);
    try {
      const r=await fetch(`/api/news/corporate-events/detail?source=${encodeURIComponent(d.source_url)}`);
      const data=await r.json();
      if (!r.ok || !data.ok || !data.item) throw new Error();
      setDocuments(ds=>ds.map(x=>x.id===d.id?data.item:x));
      onUpdated();
    } catch { setError(true); }
    finally { setBusy(''); }
  };
  return <>
    <div className="ce-history">{documents.map((d,i)=><section key={d.id} id={article ? `ce-document-${i}` : undefined} className="ce-document">
      <Evidence document={d} tx={tx} lang={lang} locale={locale} hideIntro={article && documents.length===1} />
      {d.confidence !== 'confirmed' && <button type="button" className="ghost-btn" disabled={!!busy} onClick={()=>refresh(d)}>{busy===d.id?tx.checking:tx.refresh}</button>}
      {d.revisions?.length > 1 && <details><summary>{tx.changes} · {d.revisions.length}</summary>{d.revisions.map((r,i)=><div className="ce-revision" key={i}><p>{tx.observed}: {new Date(r.observed_at).toLocaleString(locale,{timeZone:'Asia/Tashkent'})} (UTC+5)</p><Evidence document={r.document} tx={tx} lang={lang} locale={locale} /></div>)}</details>}
    </section>)}</div>
    {error && <p role="alert">{tx.refreshError}</p>}
  </>;
}

export function CorporateEvents({ language, favoriteTickers = new Set(), instrument = 'all', onOpenCompany, apiFetch, signedIn, securitiesMap={} }) {
  const lang=COPY[language]?language:'ru', tx=COPY[lang], locale=lang==='en'?'en-US':lang==='uz'?'uz-UZ':'ru-RU';
  const [data,setData]=useState({items:[]}), [loading,setLoading]=useState(true), [error,setError]=useState(false);
  const [reload,setReload]=useState(0);
  const [search,setSearch]=useState(''), [code,setCode]=useState(''), [security,setSecurity]=useState(''), [sort,setSort]=useState('recent');
  const [from,setFrom]=useState(()=>new URLSearchParams(location.search).get('start') || addDays(tashkentToday(),-90)), [to,setTo]=useState(()=>new URLSearchParams(location.search).get('end') || tashkentToday());
  const [selected,setSelected]=useState(null);
  const [eventId,setEventId]=useState(()=>new URLSearchParams(location.search).get('event'));
  useEffect(()=>{
    const onPop=()=>{
      const query=new URLSearchParams(location.search);
      setEventId(query.get('event'));
      if(query.get('start')) setFrom(query.get('start'));
      if(query.get('end')) setTo(query.get('end'));
    };
    window.addEventListener('popstate',onPop);
    return ()=>window.removeEventListener('popstate',onPop);
  },[]);
  const eventPath = id => {
    const query=new URLSearchParams(location.search);
    query.delete('mode');
    if(id) { query.set('event',id); query.set('start',from); query.set('end',to); }
    else { query.delete('event'); query.delete('start'); query.delete('end'); }
    return localizedPath(`/news?${query}`,lang);
  };
  const navigateEvent = id => {
    window.history.pushState({},'',eventPath(id));
    setEventId(id);
    window.dispatchEvent(new PopStateEvent("popstate"));
    window.scrollTo({top:0,behavior:'auto'});
  };
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true); setError(false);
    fetch(`/api/news/corporate-events?start=${encodeURIComponent(from)}&end=${encodeURIComponent(to)}`,{signal:controller.signal}).then(async r=>{
      const body=await r.json(); if(!r.ok || !body.ok) throw new Error(); return body;
    }).then(body=>{setData(body);setLoading(false);}).catch(e=>{if(e.name!=='AbortError'){setError(true);setLoading(false);}});
    return ()=>controller.abort();
  },[from,to,reload]);
  const [held,setHeld]=useState([]),[holdingsError,setHoldingsError]=useState(false);
  useEffect(()=>{
    if(!signedIn||!apiFetch){setHeld([]);return;}
    const controller=new AbortController();
    apiFetch('/api/portfolio',{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error();return r.json();}).then(d=>{setHeld((d.items||[]).map(i=>i.ticker));setHoldingsError(false);}).catch(e=>{if(e.name!=='AbortError')setHoldingsError(true);});
    return()=>controller.abort();
  },[signedIn,apiFetch]);
  const personalTickers=new Set([...favoriteTickers,...held]);
  const matchesSecurity = d => !security || (d.security_classes||[]).includes(security) || (d.amounts||[]).some(a=>a.security===security);
  const items=(data.items||[]).filter(s=>{
    const docs=s.documents?.length?s.documents:[s];
    return (!code||docs.some(d=>String(d.code)===code)) && docs.some(matchesSecurity)
      && (instrument==='all'||docs.some(d=>(d.security_types||[]).includes(instrument)))
      && [s.organization,...(s.tickers||[]),...(s.isins||[]),...docs.map(d=>pick(d.title,lang))].join(' ').toLowerCase().includes(search.trim().toLowerCase());
  }).sort((a,b)=>(sort==='priority'?a.priority-b.priority:sort==='subscriptions'?rankEvent(b,personalTickers,tashkentToday())-rankEvent(a,personalTickers,tashkentToday()):0)||String(b.published_at).localeCompare(String(a.published_at)));
  const reset=()=>{setSearch('');setCode('');setSecurity('');setSort('recent');};
  if(eventId) {
    const story=(data.items||[]).find(s=>s.story_id===eventId);
    const detailTx=DETAIL_COPY[lang];
    return <section className="ce-feed ce-detail" data-testid="corporate-event-detail">
      <a className="led-back" href={eventPath(null)} onClick={interceptNav(()=>navigateEvent(null))}>← {detailTx.back}</a>
      {loading ? <p role="status" className="ce-empty">{tx.loading}</p> : error ? <div role="alert" className="ce-empty">{tx.error} <button type="button" className="ghost-btn" onClick={()=>setReload(n=>n+1)}>{tx.retry}</button></div> : !story ? <p className="ce-empty">{detailTx.missing}</p> : <>
        <CorporateEventArticle story={story} categories={data.categories} tx={tx} lang={lang} locale={locale} securitiesMap={securitiesMap} onOpenCompany={onOpenCompany}>
          <StoryDocuments key={`${story.story_id}-${reload}`} article story={story} tx={tx} lang={lang} locale={locale} onUpdated={()=>setReload(n=>n+1)} />
        </CorporateEventArticle>
      </>}
    </section>;
  }
  return <section className="ce-feed" data-testid="corporate-events">
    <header className="ce-heading"><h2>{tx.title}</h2></header>
    <div className="ce-main">
      <div className="ce-controls"><label className="ce-search"><span>{tx.search}</span><input type="search" value={search} onChange={e=>setSearch(e.target.value)} /></label>
        <label><span>{tx.sort}</span><select value={sort} onChange={e=>setSort(e.target.value)}>{['recent','priority','subscriptions'].map(s=><option key={s} value={s}>{tx[s]}</option>)}</select></label>
      </div>
      <details className="ce-filters"><summary>{tx.filters}</summary><div className="ce-controls">
        <label><span>{tx.code}</span><select value={code} onChange={e=>setCode(e.target.value)}><option value="">{tx.any}</option>{Object.entries(data.facts||{}).map(([id,f])=><option key={id} value={id}>{id} · {pick(f.title,lang)}</option>)}</select></label>
        <label><span>{tx.security}</span><select value={security} onChange={e=>setSecurity(e.target.value)}><option value="">{tx.any}</option>{['ordinary','preferred','share','bond'].map(s=><option key={s} value={s}>{tx[s]}</option>)}</select></label>
        <label><span>{tx.from}</span><input type="date" value={from} max={to} onChange={e=>e.target.value&&setFrom(e.target.value)} /></label>
        <label><span>{tx.to}</span><input type="date" value={to} min={from} onChange={e=>e.target.value&&setTo(e.target.value)} /></label>
        <button type="button" className="ghost-btn" onClick={reset}>{tx.reset}</button>
      </div></details>
      {Object.values(data.sources||{}).some(s=>s.ok===false)&&<p className="ce-caution">{tx.partial}</p>}
      {holdingsError&&sort==='subscriptions'&&<p role="alert">{lang==='en'?'Portfolio unavailable; sorting by watchlist only.':lang==='uz'?'Portfel mavjud emas; saralash faqat tanlanganlar bo‘yicha.':'Портфель недоступен; сортировка учитывает только избранное.'}</p>}
      <div className="ce-stream newsdesk-feed">
      <div className="newsdesk-feed-head"><span className="newsdesk-live-dot" aria-hidden="true" /><h2>{DETAIL_COPY[lang].latest}</h2>{!loading&&!error&&<span>{items.length} {DETAIL_COPY[lang].count}</span>}</div>
      {loading?<p role="status" className="ce-empty">{tx.loading}</p>:error?<div role="alert" className="ce-empty">{tx.error} <button type="button" className="ghost-btn" onClick={()=>setReload(n=>n+1)}>{tx.retry}</button></div>:items.length?items.map(s=><article className="ce-story" key={s.story_id}>
        <a className="ce-story-media" href={eventPath(s.story_id)} onClick={interceptNav(()=>navigateEvent(s.story_id))} tabIndex={-1} aria-hidden="true"><CorporateStoryMedia story={s} securitiesMap={securitiesMap} /></a>
        <div className="ce-story-content"><div className="ce-story-meta"><span className="ce-category">{pick(data.categories?.[s.category],lang)||tx.review}</span></div>
        <div className="ce-company">{s.organization}<span>{(s.tickers||[]).map(t=><button type="button" key={t} onClick={()=>onOpenCompany?.(t)}>{t}</button>)}</span></div>
        <h3><a className="ce-story-title" href={eventPath(s.story_id)} onClick={interceptNav(()=>navigateEvent(s.story_id))}>{pick(s.title,lang)}</a></h3>{s.summary&&<p className="ce-summary">{pick(s.summary,lang)}</p>}<Amounts document={s} tx={tx} locale={locale} />
        {s.stage==='proposed'&&<p className="ce-caution">{tx.proposal}</p>}{s.stage==='agenda'&&<p className="ce-caution">{tx.agenda}</p>}
        <footer><span>{tx.published}: <time dateTime={s.published_at}>{formatDay(s.published_at?.slice(0,10),locale)}</time></span>{s.confidence!=='confirmed'&&<span className="ce-review">{tx.review}</span>}<button type="button" onClick={()=>setSelected(s)}>{tx.documents} · {s.document_count} {tx.docCount} →</button></footer></div>
      </article>):<p className="ce-empty">{tx.empty}</p>}
    </div></div><p className="ce-note">{tx.note}</p>
    {selected&&<StoryDialog key={selected.story_id} story={selected} tx={tx} lang={lang} locale={locale} onClose={()=>setSelected(null)} onUpdated={()=>setReload(n=>n+1)} />}
  </section>;
}
