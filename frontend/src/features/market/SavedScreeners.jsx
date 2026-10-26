import { useState } from 'react';
import { readScreeners, saveScreener, removeScreener } from './savedScreeners.js';
import './saved-screeners.css';
export function SavedScreeners({ lang, filters, onDirection, onApply, onReset }) {
  const t=(ru,en,uz)=>lang==='en'?en:lang==='uz'?uz:ru;
  const [saved,setSaved]=useState(()=>readScreeners(window.localStorage));
  const [name,setName]=useState(''), [selected,setSelected]=useState(''), [error,setError]=useState('');
  const act=fn=>{try{fn();setError('');}catch{setError(t('Не удалось сохранить в браузере.','Could not save in this browser.','Brauzerda saqlab bo‘lmadi.'));}};
  return <section className="saved-screeners" data-testid="saved-screeners" aria-label={t('Скринер','Screener','Skriner')}>
    <div className="screener-direction" role="group" aria-label={t('Динамика цены','Price direction','Narx yo‘nalishi')}>
      {[['all',t('Все','All','Barchasi')],['gain',t('Растущие','Gainers','O‘sayotgan')],['loss',t('Снижающиеся','Decliners','Pasayayotgan')]].map(([key,label])=><button key={key} type="button" aria-pressed={filters.direction===key} onClick={()=>onDirection(key)}>{label}</button>)}
    </div>
    <details><summary>{t('Сохранённые скринеры','Saved screeners','Saqlangan skrinerlar')} · {saved.length}</summary>
      <div className="screener-save-controls">
        <label>{t('Название фильтра','Filter name','Filtr nomi')}<input maxLength={70} value={name} onChange={e=>setName(e.target.value)} /></label>
        <button type="button" className="ghost-btn" disabled={!name.trim()} onClick={()=>act(()=>{const rows=saveScreener(window.localStorage,name,filters);setSaved(rows);setSelected(rows[0].id);setName('');})}>{t('Сохранить фильтр','Save filter','Filtrni saqlash')}</button>
        <label>{t('Сохранённые скринеры','Saved screeners','Saqlangan skrinerlar')}<select value={selected} onChange={e=>setSelected(e.target.value)}><option value="">{t('Выбрать…','Select…','Tanlash…')}</option>{saved.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
        <button type="button" className="ghost-btn" disabled={!saved.some(s=>s.id===selected)} onClick={()=>onApply(saved.find(s=>s.id===selected).filters)}>{t('Применить','Apply','Qo‘llash')}</button>
        <button type="button" className="ghost-btn" disabled={!selected} onClick={()=>act(()=>{setSaved(removeScreener(window.localStorage,selected));setSelected('');})}>{t('Удалить','Delete','O‘chirish')}</button>
        <button type="button" className="ghost-btn" onClick={onReset}>{t('Сбросить','Reset','Tozalash')}</button>
      </div>
      <p>{t('Фильтры хранятся только в этом браузере. Повторное сохранение с тем же названием обновляет фильтр.','Filters are stored only in this browser. Saving the same name updates its filter.','Filtrlar faqat shu brauzerda saqlanadi. Bir xil nom bilan saqlash filtrni yangilaydi.')}</p>
      {error&&<p role="alert">{error}</p>}
    </details>
  </section>;
}
