import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { safeHref } from '../../lib/safeHref.js';
import { addDays, tashkentToday, formatDay } from './calendarEvents.js';
import './corporate-events.css';

const COPY = {
  ru: { title:'Корпоративные события', subtitle:'Решения, предложения и выплаты — с отдельными датами и первоисточниками.', all:'Все события', important:'Важное', mine:'Мои компании', calendar:'Календарь', categories:'Категории', allCategories:'Все категории', search:'Компания, тикер или ISIN', sort:'Порядок событий', recent:'По времени', priority:'По важности', subscriptions:'Сначала мои компании', from:'Опубликовано с', to:'По', filters:'Расширенные фильтры', code:'Тип по OpenInfo', any:'Все', security:'Вид бумаги', ordinary:'Простые акции', preferred:'Привилегированные акции', share:'Акции (класс не указан)', bond:'Облигации', published:'Опубликовано', decision:'Решение принято', event:'Дата события', payment_start:'Начало окна выплат', payment_end:'Конец окна выплат', source:'Первоисточник OpenInfo', documents:'Документы и история', docCount:'док.', close:'Закрыть', review:'Проверяется', confirmed:'Подтверждено источником', provisional:'Предварительный приоритет по типу раскрытия', note:'Краткое изложение UZStock. Официальный текст — в первоисточнике. Приоритет показывает внимание к раскрытию, а не направление цены.', proposal:'Предложение не означает утверждённую выплату.', agenda:'Вопрос в повестке не означает принятого решения.', loading:'Загрузка событий…', empty:'По выбранным фильтрам событий нет.', error:'Не удалось загрузить события.', retry:'Повторить', partial:'Часть источников временно недоступна.', noFavorites:'Добавьте компании в избранное, чтобы следить за их событиями.', reset:'Сбросить фильтры', refresh:'Проверить документ', checking:'Проверяем…', refreshError:'Документ временно недоступен. Первоначальная запись сохранена.', original:'Оригинальное название', changes:'История изменений', observed:'Обнаружено', unit:'сум на бумагу', stages:{proposed:'Предложение',agenda:'Повестка',announced:'Объявлено',decision_disclosed:'Решение раскрыто',scheduled:'Сроки определены',accrued:'Начислено',payment_disclosed:'Данные о выплатах',disclosed:'Раскрыто'}, priorities:['Критично','Важно','Наблюдать','Справочно'] },
  en: { title:'Corporate events', subtitle:'Decisions, proposals and payments, with distinct dates and original documents.', all:'All events', important:'Important', mine:'My companies', calendar:'Calendar', categories:'Categories', allCategories:'All categories', search:'Company, ticker or ISIN', sort:'Event order', recent:'Latest first', priority:'By importance', subscriptions:'My companies first', from:'Published from', to:'To', filters:'Advanced filters', code:'OpenInfo type', any:'All', security:'Security class', ordinary:'Ordinary shares', preferred:'Preferred shares', share:'Shares (class unspecified)', bond:'Bonds', published:'Published', decision:'Decision made', event:'Event date', payment_start:'Payment window opens', payment_end:'Payment window ends', source:'Original on OpenInfo', documents:'Documents & history', docCount:'docs', close:'Close', review:'Under review', confirmed:'Source confirmed', provisional:'Provisional priority based on disclosure type', note:'UZStock summary. The source carries the official text. Priority indicates attention to a disclosure, not price direction.', proposal:'A proposal is not an approved payment.', agenda:'An agenda item is not a decision.', loading:'Loading events…', empty:'No events match these filters.', error:'Could not load events.', retry:'Retry', partial:'Some sources are temporarily unavailable.', noFavorites:'Add companies to your watchlist to follow their events.', reset:'Reset filters', refresh:'Check document', checking:'Checking…', refreshError:'Document temporarily unavailable. The original record is preserved.', original:'Original title', changes:'Revision history', observed:'Observed', unit:'UZS per security', stages:{proposed:'Proposed',agenda:'Agenda',announced:'Announced',decision_disclosed:'Decision disclosed',scheduled:'Scheduled',accrued:'Accrued',payment_disclosed:'Payment data',disclosed:'Disclosed'}, priorities:['Critical','Important','Watch','Reference'] },
  uz: { title:'Korporativ voqealar', subtitle:'Qarorlar, takliflar va to‘lovlar — alohida sanalar va birlamchi manbalar bilan.', all:'Barcha voqealar', important:'Muhim', mine:'Mening kompaniyalarim', calendar:'Taqvim', categories:'Toifalar', allCategories:'Barcha toifalar', search:'Kompaniya, tiker yoki ISIN', sort:'Voqealar tartibi', recent:'Vaqt bo‘yicha', priority:'Muhimlik bo‘yicha', subscriptions:'Avval mening kompaniyalarim', from:'E’lon qilingan sana: dan', to:'Gacha', filters:'Qo‘shimcha filtrlar', code:'OpenInfo turi', any:'Barchasi', security:'Qimmatli qog‘oz turi', ordinary:'Oddiy aksiyalar', preferred:'Imtiyozli aksiyalar', share:'Aksiyalar (turi ko‘rsatilmagan)', bond:'Obligatsiyalar', published:'E’lon qilindi', decision:'Qaror qabul qilindi', event:'Voqea sanasi', payment_start:'To‘lov davri boshlanishi', payment_end:'To‘lov davri tugashi', source:'OpenInfo birlamchi manbasi', documents:'Hujjatlar va tarix', docCount:'hujjat', close:'Yopish', review:'Tekshirilmoqda', confirmed:'Manba tasdiqlagan', provisional:'Ma’lumot turi bo‘yicha dastlabki ustuvorlik', note:'UZStock qisqa bayoni. Rasmiy matn birlamchi manbada. Ustuvorlik narx yo‘nalishini emas, voqeaga e’tiborni bildiradi.', proposal:'Taklif tasdiqlangan to‘lov degani emas.', agenda:'Kun tartibidagi masala qabul qilingan qaror emas.', loading:'Voqealar yuklanmoqda…', empty:'Ushbu filtrlarga mos voqealar yo‘q.', error:'Voqealarni yuklab bo‘lmadi.', retry:'Qayta urinish', partial:'Ayrim manbalar vaqtincha mavjud emas.', noFavorites:'Voqealarni kuzatish uchun kompaniyalarni tanlanganlarga qo‘shing.', reset:'Filtrlarni tozalash', refresh:'Hujjatni tekshirish', checking:'Tekshirilmoqda…', refreshError:'Hujjat vaqtincha mavjud emas. Asl yozuv saqlangan.', original:'Asl sarlavha', changes:'O‘zgarishlar tarixi', observed:'Aniqlandi', unit:'so‘m / qimmatli qog‘oz', stages:{proposed:'Taklif',agenda:'Kun tartibi',announced:'E’lon qilindi',decision_disclosed:'Qaror e’lon qilindi',scheduled:'Muddatlar belgilandi',accrued:'Hisoblandi',payment_disclosed:'To‘lov ma’lumotlari',disclosed:'E’lon qilindi'}, priorities:['Jiddiy','Muhim','Kuzatish','Ma’lumot'] },
};
const pick = (value, lang) => typeof value === 'string' ? value : value?.[lang] || value?.ru || '';
function Amounts({ document, tx, locale }) {
  return <div className="ce-amounts">{(document.amounts || []).map(a => <span key={a.security}>{tx[a.security] || a.security}: <strong>{new Intl.NumberFormat(locale, { maximumFractionDigits: 6 }).format(a.amount)}</strong> {tx.unit}</span>)}</div>;
}
function Evidence({ document: d, tx, lang, locale }) {
  return <>
    <span className="ce-stage">{tx.stages[d.stage] || tx.review}</span>
    <h3>{pick(d.title, lang)}</h3>
    {d.stage === 'proposed' && <p className="ce-caution">{tx.proposal}</p>}
    {d.stage === 'agenda' && <p className="ce-caution">{tx.agenda}</p>}
    <Amounts document={d} tx={tx} locale={locale} />
    <dl className="ce-dates">{[['published_at','published'],['event_date','event'],['decision_date','decision'],['payment_start','payment_start'],['payment_end','payment_end']].filter(([key])=>d[key]).map(([key,label]) => <div key={key}><dt>{tx[label]}</dt><dd>{formatDay(d[key].slice(0,10),locale)}</dd></div>)}</dl>
    <p className="ce-confidence">{d.confidence === 'confirmed' ? tx.confirmed : tx.review}{d.code ? ` · OpenInfo № ${d.code}` : ''}</p>
    {d.original_title && <p className="ce-original"><b>{tx.original}:</b> {d.original_title}</p>}
    <a href={safeHref(d.source_url)} target="_blank" rel="noreferrer">{tx.source} ↗</a>
    {d.pdf_url && <a href={safeHref(d.pdf_url)} target="_blank" rel="noreferrer">PDF ↗</a>}
  </>;
}
function StoryDialog({ story, onClose, tx, lang, locale, onUpdated }) {
  const ref = useRef(null);
  const [documents,setDocuments] = useState(story.documents);
  const [busy,setBusy] = useState('');
  const [error,setError] = useState(false);
  useEffect(() => {
    const dialog=ref.current;
    const previous=document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); previous?.focus(); };
  }, []);
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
  return createPortal(<dialog ref={ref} className="ce-dialog" aria-labelledby="ce-dialog-title" onCancel={onClose} onClick={e=>{ if(e.target===e.currentTarget) onClose(); }}>
    <header><div><span className="ce-eyebrow">{tx.documents}</span><h2 id="ce-dialog-title">{story.organization}</h2></div><button type="button" className="ghost-btn" onClick={onClose}>{tx.close} ×</button></header>
    <div className="ce-history">{documents.map(d=><section key={d.id} className="ce-document">
      <Evidence document={d} tx={tx} lang={lang} locale={locale} />
      {d.confidence !== 'confirmed' && <button type="button" className="ghost-btn" disabled={!!busy} onClick={()=>refresh(d)}>{busy===d.id?tx.checking:tx.refresh}</button>}
      {d.revisions?.length > 1 && <details><summary>{tx.changes} · {d.revisions.length}</summary>{d.revisions.map((r,i)=><div className="ce-revision" key={i}><p>{tx.observed}: {new Date(r.observed_at).toLocaleString(locale,{timeZone:'Asia/Tashkent'})} (UTC+5)</p><Evidence document={r.document} tx={tx} lang={lang} locale={locale} /></div>)}</details>}
    </section>)}</div>
    {error && <p role="alert">{tx.refreshError}</p>}
    <p className="ce-note">{tx.note}</p>
  </dialog>, document.body);
}
export function CorporateEvents({ language, favoriteTickers = new Set(), instrument = 'all', onCalendar, onOpenCompany }) {
  const lang=COPY[language]?language:'ru', tx=COPY[lang], locale=lang==='en'?'en-US':lang==='uz'?'uz-UZ':'ru-RU';
  const [data,setData]=useState({items:[]}), [loading,setLoading]=useState(true), [error,setError]=useState(false);
  const [reload,setReload]=useState(0), [category,setCategory]=useState(''), [mode,setMode]=useState('all');
  const [search,setSearch]=useState(''), [code,setCode]=useState(''), [security,setSecurity]=useState(''), [sort,setSort]=useState('recent');
  const [from,setFrom]=useState(()=>addDays(tashkentToday(),-90)), [to,setTo]=useState(tashkentToday);
  const [selected,setSelected]=useState(null);
  useEffect(()=>{
    const controller=new AbortController();
    setLoading(true); setError(false);
    fetch(`/api/news/corporate-events?start=${from}&end=${to}`,{signal:controller.signal}).then(async r=>{
      const body=await r.json(); if(!r.ok || !body.ok) throw new Error(); return body;
    }).then(body=>{setData(body);setLoading(false);}).catch(e=>{if(e.name!=='AbortError'){setError(true);setLoading(false);}});
    return ()=>controller.abort();
  },[from,to,reload]);
  const mine = s => (s.tickers||[]).some(t=>favoriteTickers.has(t));
  const matchesSecurity = d => !security || (d.amounts||[]).some(a=>a.security===security);
  const items=(data.items||[]).filter(s=>{
    const docs=s.documents||[s];
    return (!category||s.category===category) && (mode!=='important'||s.priority<=1) && (mode!=='mine'||mine(s))
      && (!code||docs.some(d=>String(d.code)===code)) && docs.some(matchesSecurity)
      && (instrument==='all'||docs.some(d=>(d.amounts||[]).some(a=>instrument==='bond'?a.security==='bond':a.security!=='bond')))
      && [s.organization,...(s.tickers||[]),...(s.isins||[]),...docs.map(d=>pick(d.title,lang))].join(' ').toLowerCase().includes(search.trim().toLowerCase());
  }).sort((a,b)=>(sort==='priority'?a.priority-b.priority:sort==='subscriptions'?Number(mine(b))-Number(mine(a)):0)||String(b.published_at).localeCompare(String(a.published_at)));
  const reset=()=>{setCategory('');setMode('all');setSearch('');setCode('');setSecurity('');setSort('recent');};
  return <section className="ce-feed" data-testid="corporate-events">
    <header className="ce-heading"><div><span className="ce-eyebrow">OPENINFO · UZSTOCK</span><h2>{tx.title}</h2><p>{tx.subtitle}</p></div><button className="ghost-btn" type="button" onClick={onCalendar}>{tx.calendar} →</button></header>
    <div className="ce-modes" role="group" aria-label={tx.title}>{['all','important','mine'].map(m=><button key={m} type="button" aria-pressed={mode===m} onClick={()=>setMode(m)}>{tx[m]}</button>)}</div>
    <div className="ce-layout"><aside className="ce-categories" aria-label={tx.categories}>
      <button type="button" aria-pressed={!category} onClick={()=>setCategory('')}>{tx.allCategories}</button>
      {Object.entries(data.categories||{}).map(([id,label])=><button key={id} type="button" aria-pressed={category===id} onClick={()=>setCategory(id)}>{pick(label,lang)}</button>)}
    </aside><div className="ce-main">
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
      {loading?<p role="status" className="ce-empty">{tx.loading}</p>:error?<div role="alert" className="ce-empty">{tx.error} <button type="button" className="ghost-btn" onClick={()=>setReload(n=>n+1)}>{tx.retry}</button></div>:items.length?items.map(s=><article className="ce-story" key={s.story_id}>
        <div className="ce-story-meta"><span className="ce-category">{pick(data.categories?.[s.category],lang)||tx.review}</span><span className={`ce-priority ce-p${s.priority}`} title={s.priority_provisional?tx.provisional:undefined}>P{s.priority} · {tx.priorities[s.priority]}{s.priority_provisional?' *':''}</span><span className="ce-stage">{tx.stages[s.stage]||tx.review}</span></div>
        <div className="ce-company">{s.organization}<span>{(s.tickers||[]).map(t=><button type="button" key={t} onClick={()=>onOpenCompany?.(t)}>{t}</button>)}</span></div>
        <h3>{pick(s.title,lang)}</h3><Amounts document={s} tx={tx} locale={locale} />
        {s.stage==='proposed'&&<p className="ce-caution">{tx.proposal}</p>}{s.stage==='agenda'&&<p className="ce-caution">{tx.agenda}</p>}
        <footer><span>{tx.published}: <time dateTime={s.published_at}>{formatDay(s.published_at?.slice(0,10),locale)}</time></span>{s.confidence!=='confirmed'&&<span className="ce-review">{tx.review}</span>}<a href={safeHref(s.source_url)} target="_blank" rel="noreferrer">OpenInfo ↗</a><button type="button" onClick={()=>setSelected(s)}>{tx.documents} · {s.document_count} {tx.docCount} →</button></footer>
      </article>):<p className="ce-empty">{mode==='mine'&&!favoriteTickers.size?tx.noFavorites:tx.empty}</p>}
    </div></div><p className="ce-note">{tx.note}</p>
    {selected&&<StoryDialog key={selected.story_id} story={selected} tx={tx} lang={lang} locale={locale} onClose={()=>setSelected(null)} onUpdated={()=>setReload(n=>n+1)} />}
  </section>;
}
