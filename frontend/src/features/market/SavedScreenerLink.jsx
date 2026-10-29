import { useEffect, useRef } from 'react';
import { useSavedScreeners } from './useSavedScreeners.js';
// Preserve existing profile links without rendering controls on the market board.
export function SavedScreenerLink({ onApply, accountKey, apiFetch, onSaved }) {
  const {saved,ready}=useSavedScreeners(accountKey,apiFetch,onSaved);
  const applied=useRef('');
  useEffect(()=>{
    const id=new URLSearchParams(window.location.search).get('screener');
    const item=ready&&saved.find(s=>s.id===id);
    if(item&&applied.current!==id){applied.current=id;onApply(item.filters);}
  },[ready,saved,onApply]);
  return null;
}
