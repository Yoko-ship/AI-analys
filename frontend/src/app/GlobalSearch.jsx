import {useState,useRef,useEffect} from 'react';
import {createPortal} from 'react-dom';
export function GlobalSearch({language,securities={},companies=[],onCompany,onNews}){
 const [open,setOpen]=useState(false),[query,setQuery]=useState(''),[news,setNews]=useState([]),[newsError,setNewsError]=useState(false);
 const ref=useRef(null),button=useRef(null);const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 useEffect(()=>{const key=e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();setOpen(true);}};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key);},[]);
 useEffect(()=>{if(!open)return;const opener=button.current;ref.current.showModal();const c=new AbortController();setNewsError(false);
 fetch('/api/news/feed?limit=60&days=30',{signal:c.signal}).then(async r=>{if(!r.ok)throw Error();return r.json();}).then(d=>setNews(d.items||[])).catch(e=>{if(e.name!=='AbortError')setNewsError(true);});
 return()=>{c.abort();opener?.focus();};},[open]);
 const all=new Map(companies.map(c=>[c.ticker,{...c,name:c.company_name}]));for(const [ticker,s] of Object.entries(securities))all.set(ticker,{...all.get(ticker),...s,ticker});
 const q=query.trim().toLowerCase();const securitiesFound=q?[...all.values()].filter(s=>[s.ticker,s.name,s.company_name,s.isin].join(' ').toLowerCase().includes(q)).slice(0,8):[];
 const stories=q?news.filter(s=>[s.title,s['title_'+language],...(s.tickers||[])].join(' ').toLowerCase().includes(q)).slice(0,5):[];
 return <><button ref={button} type="button" className="global-search-trigger" aria-label={t('Поиск по сайту','Search site','Saytda qidirish')} onClick={()=>setOpen(true)}><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg><span>{t('Компания, тикер, новость…','Company, ticker, news…','Kompaniya, tiker, yangilik…')}</span><kbd>⌘ K</kbd></button>
 {open&&createPortal(<dialog ref={ref} className="iw-dialog global-search-dialog" aria-labelledby="global-search-title" onCancel={()=>setOpen(false)}><header><h2 id="global-search-title">{t('Поиск по сайту','Search site','Saytda qidirish')}</h2><button className="ghost-btn" type="button" onClick={()=>setOpen(false)}>{t('Закрыть','Close','Yopish')}</button></header>
 <input autoFocus type="search" value={query} onChange={e=>setQuery(e.target.value)} aria-label={t('Компания, тикер или новость','Company, ticker or news','Kompaniya, tiker yoki yangilik')}/>
 {securitiesFound.map(s=><button className="gs-result" type="button" key={s.ticker} onClick={()=>{setOpen(false);onCompany(s.ticker);}}><b>{s.ticker}</b><span>{s.name||s.company_name}</span></button>)}
 {stories.map(s=><button className="gs-result" type="button" key={s.id} onClick={()=>{setOpen(false);onNews(s.slug||s.id);}}>{s['title_'+language]||s.title}</button>)}
 {q&&!securitiesFound.length&&!stories.length&&<p>{t('Совпадений нет.','No matches.','Mos natija yo‘q.')}</p>}
 {newsError&&<p role="status">{t('Поиск новостей временно недоступен.','News search temporarily unavailable.','Yangiliklar qidiruvi vaqtincha mavjud emas.')}</p>}
 </dialog>,document.body)}</>;
}
