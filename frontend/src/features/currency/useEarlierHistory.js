import {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {mergeHistoryPoints, historyContiguousTail} from './historyChart.js';

// Fetch one earlier month as the reader approaches the loaded edge.
// Period changes unmount this hook, aborting its requests and scheduled retries.
export function useEarlierHistory(ccy, current) {
  const [older,setOlder]=useState([]);
  const [status,setStatus]=useState('idle');
  const [request,setRequest]=useState(null);
  const inFlight=useRef(false);
  const points=useMemo(()=>mergeHistoryPoints(older,current),[older,current]);
  const first=points[0].date;
  const hasEarlier=first>'2000-01-01';
  const load=useCallback(()=>{
    if(status!=='idle'||inFlight.current||!hasEarlier)return;
    inFlight.current=true;
    const previous=new Date(Date.parse(first+'T00:00:00Z')-86400000).toISOString().slice(0,10);
    // The final 31-day page may overlap existing observations at the archive limit.
    setRequest({end:previous<'2000-01-31'?'2000-01-31':previous,attempt:0});
    setStatus('loading');
  },[first,hasEarlier,status]);
  const retry=()=>{
    if(inFlight.current)return;
    inFlight.current=true;
    setStatus('loading');
    setRequest(value=>({...value,attempt:0}));
  };
  useEffect(()=>{
    if(!request)return undefined;
    const controller=new AbortController();
    let timer;
    fetch(`/api/currency/history?ccy=${encodeURIComponent(ccy)}&days=30&end=${request.end}`,{signal:controller.signal,cache:'no-cache'})
      .then(async response=>{if(!response.ok)throw Error('history');return response.json();})
      .then(data=>{
        if(controller.signal.aborted)return;
        if(!data.points?.some(p=>p.date<=request.end&&Number.isFinite(p.value)))throw Error('empty history');
        const ready=historyContiguousTail(data.points.filter(p=>p.date<=request.end));
        if(ready.length)setOlder(previous=>mergeHistoryPoints(previous,ready));
        if(data.pending_days>0&&request.attempt<5){
          timer=setTimeout(()=>setRequest(previous=>({...previous,attempt:previous.attempt+1})),1000);
        }else {inFlight.current=false;setStatus(data.missing_days>0?'error':'idle');}
      })
      .catch(()=>{if(!controller.signal.aborted){inFlight.current=false;setStatus('error');}});
    return ()=>{controller.abort();clearTimeout(timer);};
  },[ccy,request]);
  return {points,status,load,retry,hasEarlier};
}
