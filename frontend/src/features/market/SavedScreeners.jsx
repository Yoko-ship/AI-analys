import { useState, useEffect, useRef } from 'react';
import { readScreeners } from './savedScreeners.js';
import { useSavedScreeners } from './useSavedScreeners.js';
import './saved-screeners.css';
export function SavedScreeners({ lang, filters, onDirection, onApply, onReset, accountKey, apiFetch, onSaved }) {
  const t=(ru,en,uz)=>lang==='en'?en:lang==='uz'?uz:ru;
  const {saved,busy,error,ready,retry,save,remove,importLocal}=useSavedScreeners(accountKey,apiFetch,onSaved);
  const [name,setName]=useState(''), [selected,setSelected]=useState('');
  const applied=useRef('');
  useEffect(()=>{
    const id=new URLSearchParams(window.location.search).get('screener');
    const item=ready&&saved.find(s=>s.id===id);
    if(item&&applied.current!==id){applied.current=id;setSelected(id);onApply(item.filters);}
  },[ready,saved,onApply]);
  return <section className="saved-screeners" data-testid="saved-screeners" aria-label={t('Скринер','Screener','Skriner')}>
    <div className="screener-direction" role="group" aria-label={t('Динамика цены','Price direction','Narx yo‘nalishi')}>
      {[['all',t('Все','All','Barchasi')],['gain',t('Растущие','Gainers','O‘sayotgan')],['loss',t('Снижающиеся','Decliners','Pasayayotgan')]].map(([key,label])=><button key={key} type="button" aria-pressed={filters.direction===key} onClick={()=>onDirection(key)}>{label}</button>)}
    </div>
    <details><summary>{t('Сохранённые скринеры','Saved screeners','Saqlangan skrinerlar')} · {saved.length}</summary>
      <div className="screener-save-controls">
        <label>{t('Название фильтра','Filter name','Filtr nomi')}<input maxLength={70} value={name} onChange={e=>setName(e.target.value)} /></label>
        <button type="button" className="ghost-btn" disabled={!name.trim()||busy||!ready} onClick={async()=>{if(await save(name,filters)){setSelected('');setName('');}}}>{t('Сохранить фильтр','Save filter','Filtrni saqlash')}</button>
        <label>{t('Сохранённые скринеры','Saved screeners','Saqlangan skrinerlar')}<select aria-label={t("Сохранённые скринеры","Saved screeners","Saqlangan skrinerlar")} value={selected} onChange={e=>setSelected(e.target.value)}><option value="">{t('Выбрать…','Select…','Tanlash…')}</option>{saved.map(s=><option value={s.id} key={s.id}>{s.name}</option>)}</select></label>
        <button type="button" className="ghost-btn" disabled={!saved.some(s=>s.id===selected)} onClick={()=>onApply(saved.find(s=>s.id===selected).filters)}>{t('Применить','Apply','Qo‘llash')}</button>
        <button type="button" className="ghost-btn" disabled={!selected||busy||!ready} onClick={async()=>{if(await remove(selected))setSelected('');}}>{t('Удалить','Delete','O‘chirish')}</button>
        <button type="button" className="ghost-btn" onClick={onReset}>{t('Сбросить','Reset','Tozalash')}</button>
      </div>
      <p>{accountKey?t('Сохранено в аккаунте — доступно на всех устройствах.','Saved to your account — available on every device.','Hisobda saqlanadi — barcha qurilmalarda mavjud.'):t('Фильтры хранятся только в этом браузере. Повторное сохранение с тем же названием обновляет фильтр.','Filters are stored only in this browser. Saving the same name updates its filter.','Filtrlar faqat shu brauzerda saqlanadi. Bir xil nom bilan saqlash filtrni yangilaydi.')}</p>
      {accountKey&&readScreeners(localStorage).length>0&&<button type="button" className="ghost-btn" disabled={busy||!ready} onClick={importLocal}>{t('Импортировать фильтры браузера','Import browser filters','Brauzer filtrlarini import qilish')}</button>}
      {busy&&<p role="status">{t('Синхронизация…','Syncing…','Sinxronlanmoqda…')}</p>}
      {error&&<p role="alert">{t('Не удалось синхронизировать фильтры. Повторите попытку.','Could not sync filters. Please retry.','Filtrlarni sinxronlab bo‘lmadi. Qayta urinib ko‘ring.')} {!ready&&<button type="button" onClick={retry}>{t('Повторить','Retry','Qayta urinish')}</button>}</p>}
    </details>
  </section>;
}
