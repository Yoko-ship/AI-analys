import {useRef,useState,useEffect} from 'react';
import {createPortal} from 'react-dom';
import './investor-workspace.css';
export const INTERESTS=[
 ['dividends','Дивидендные акции','Dividend shares','Dividend aksiyalari'],['telecom','Телеком','Telecom','Telekom'],
 ['fundamentals','Фундаментальный анализ','Fundamental analysis','Fundamental tahlil'],['banks','Банки','Banks','Banklar'],
 ['insurance','Страхование','Insurance','Sug‘urta'],['energy','Энергетика','Energy','Energetika'],
 ['industry','Промышленность','Industry','Sanoat'],['bonds','Облигации','Bonds','Obligatsiyalar'],
 ['low_volatility','Низкая волатильность','Low volatility','Past o‘zgaruvchanlik'],['growth','Высокий рост','High growth','Yuqori o‘sish'],
 ['corporate','Корпоративные события','Corporate events','Korporativ voqealar']];
export function InvestmentInterests({language,values=[],apiFetch,onRefresh,onExplore}){
 const [editing,setEditing]=useState(false),[selected,setSelected]=useState(values),[busy,setBusy]=useState(false),[error,setError]=useState(false);
 const dialog=useRef(null),opener=useRef(null);
 const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 const label=row=>row[language==='en'?2:language==='uz'?3:1];
 useEffect(()=>{if(!editing)return;const trigger=opener.current;dialog.current?.showModal();return()=>trigger?.focus();},[editing]);
 const close=()=>{if(!busy)setEditing(false);};
 const save=async()=>{
  setBusy(true);setError(false);
  try{const r=await apiFetch('/api/profile/preferences',{method:'PATCH',body:JSON.stringify({investment_interests:selected})});if(!r.ok)throw Error();await onRefresh();setEditing(false);}
  catch{setError(true);}finally{setBusy(false);}
 };
 return <section className="iw-card" data-testid="investment-interests"><header><h2>{t('Инвестиционные интересы','Investment interests','Investitsiya qiziqishlari')}</h2><button ref={opener} type="button" className="ghost-btn" onClick={()=>{setSelected(values);setError(false);setEditing(true);}}>{t('Изменить интересы','Edit interests','Qiziqishlarni o‘zgartirish')}</button></header>
  <div className="iw-chips">{INTERESTS.filter(row=>values.includes(row[0])).map(row=><span key={row[0]}>{label(row)}</span>)}</div>
  {!values.length&&<p>{t('Выберите темы для персональной ленты.','Choose topics for your personal feed.','Shaxsiy lenta uchun mavzularni tanlang.')}</p>}
  <button className="ghost-btn" type="button" onClick={onExplore}>{t('Открыть мою ленту','Open my feed','Shaxsiy lentani ochish')} →</button>
  {editing&&createPortal(<dialog className="iw-dialog" ref={dialog} aria-labelledby="interests-title" onCancel={e=>{e.preventDefault();close();}}>
   <header><h2 id="interests-title">{t('Инвестиционные интересы','Investment interests','Investitsiya qiziqishlari')}</h2><button type="button" className="ghost-btn" disabled={busy} onClick={close}>{t('Закрыть','Close','Yopish')}</button></header>
   <p>{t('Темы сохраняются в аккаунте. Они помогают отбирать новости; это не инвестиционная рекомендация.','Topics are saved to your account and filter your feed; they are not investment advice.','Mavzular hisobda saqlanib, yangiliklarni saralaydi; bu investitsiya tavsiyasi emas.')}</p>
   <div className="iw-interest-options">{INTERESTS.map(row=><label key={row[0]}><input type="checkbox" disabled={busy} checked={selected.includes(row[0])} onChange={e=>setSelected(old=>e.target.checked?[...old,row[0]]:old.filter(x=>x!==row[0]))}/>{label(row)}</label>)}</div>
   {error&&<p role="alert">{t('Не удалось сохранить. Попробуйте ещё раз.','Could not save. Please retry.','Saqlab bo‘lmadi. Qayta urinib ko‘ring.')}</p>}
   <button type="button" className="primary-btn" disabled={busy} onClick={save}>{t('Сохранить интересы','Save interests','Qiziqishlarni saqlash')}</button>
  </dialog>,document.body)}
 </section>;
}
export function AccountSecuritySummary({language,security={},onOpen}){
 const t=(ru,en,uz)=>language==='en'?en:language==='uz'?uz:ru;
 return <section className="iw-card" data-testid="account-security-summary"><header><h2>{t('Безопасность','Security','Xavfsizlik')}</h2><button className="ghost-btn" type="button" onClick={onOpen}>{t('Настроить','Manage','Sozlash')}</button></header>
 <p>{security.email_verified?t('Email подтверждён','Email verified','Email tasdiqlangan'):t('Email не подтверждён','Email not verified','Email tasdiqlanmagan')}</p>
 <p>{security.two_factor_enabled?t('Двухфакторная защита включена','Two-factor on','Ikki bosqichli himoya yoqilgan'):t('Двухфакторная защита выключена','Two-factor off','Ikki bosqichli himoya o‘chirilgan')}</p>
 </section>;
}
