import {useEffect,useState} from 'react';
import {readScreeners,saveScreener,removeScreener} from './savedScreeners.js';

// The parent keys this component by account. Private saves never enter browser storage.
export function useSavedScreeners(accountKey,apiFetch,onSaved){
 const [saved,setSaved]=useState(()=>accountKey?[]:readScreeners(localStorage));
 const [busy,setBusy]=useState(Boolean(accountKey));
 const [error,setError]=useState(false);
 const [ready,setReady]=useState(!accountKey);
 const [reload,setReload]=useState(0);
 useEffect(()=>{
  if(!accountKey||accountKey==='pending')return;
  const controller=new AbortController();setBusy(true);setError(false);
  apiFetch('/api/profile',{signal:controller.signal}).then(async r=>{if(!r.ok)throw Error();return r.json();})
   .then(d=>{if(!controller.signal.aborted){setSaved(d.preferences?.saved_screeners||[]);setReady(true);}})
   .catch(e=>{if(e.name!=='AbortError')setError(true);}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return()=>controller.abort();
 },[accountKey,apiFetch,reload]);
 const commit=async next=>{
  if(accountKey){
   const r=await apiFetch('/api/profile/preferences',{method:'PATCH',body:JSON.stringify({saved_screeners:next})});
   if(!r.ok)throw Error(); const body=await r.json();
   if(!body.ok||!Array.isArray(body.preferences?.saved_screeners))throw Error();
   setSaved(body.preferences.saved_screeners);
   // Saving succeeded even if the separate profile summary cannot refresh.
   if(onSaved)await onSaved().catch(()=>{});
  }else setSaved(next);
 };
 const act=async operation=>{
  if(busy||!ready)return false;
  setBusy(true);setError(false);
  try{await operation();return true;}catch{setError(true);return false;}finally{setBusy(false);}
 };
 const memory=()=>({getItem:()=>JSON.stringify(saved),setItem:()=>{}});
 return {saved,busy,error,ready,retry:()=>setReload(n=>n+1),
  save:(name,filters)=>act(()=>commit(saveScreener(accountKey?memory():localStorage,name,filters))),
  remove:id=>act(()=>commit(removeScreener(accountKey?memory():localStorage,id))),
  importLocal:()=>act(()=>{
   const combined=[...saved];for(const row of readScreeners(localStorage))if(!combined.some(s=>s.name===row.name))combined.push({...row,id:crypto.randomUUID()});
   return commit(combined.slice(0,30));
  })};
}
