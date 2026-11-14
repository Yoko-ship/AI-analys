import {useEffect, useRef, useState} from 'react';
import {normalizeHistory} from './returnsModel.js';

export function useReturnsData(tickers, apiFetch) {
  const [histories,setHistories] = useState({});
  const [options,setOptions] = useState([]);
  const [optionsError,setOptionsError] = useState(false);
  const [attempt,setAttempt] = useState(0);
  const cache = useRef({});
  const key = tickers.join(',');
  useEffect(() => {
    const controller = new AbortController();
    setOptionsError(false);
    apiFetch('/api/company-comparison/options',{signal:controller.signal})
      .then(async r => {const body=await r.json();if(!r.ok || !body.ok || !Array.isArray(body.companies))throw new Error('options');return body.companies;})
      .then(data => {if(!controller.signal.aborted)setOptions(data);})
      .catch(() => {if(!controller.signal.aborted)setOptionsError(true);});
    return () => controller.abort();
  },[apiFetch,attempt]);
  useEffect(() => {
    const controller = new AbortController();
    for (const ticker of key.split(',').filter(Boolean)) {
      if(cache.current[ticker]) {
        setHistories(previous => ({...previous,[ticker]:cache.current[ticker]}));
        continue;
      }
      setHistories(previous => ({...previous,[ticker]:{status:'loading',points:[]}}));
      apiFetch(`/api/price-history/${encodeURIComponent(ticker)}?months=240`,{signal:controller.signal})
        .then(async r => {
          const body=await r.json();
          if(!r.ok || !body.ok || !Array.isArray(body.points) || (body.ticker && body.ticker!==ticker))throw new Error('history');
          const marketDate=/^20\d{2}-\d{2}-\d{2}$/.test(body.as_of) ? body.as_of : undefined;
          const points=normalizeHistory(body.points,marketDate);
          return {status:'ready',points,asOf:marketDate || points.at(-1)?.date,adjustments:body.adjustments || []};
        })
        .then(data => {
          if(controller.signal.aborted)return;
          cache.current[ticker]=data;
          setHistories(previous => ({...previous,[ticker]:data}));
        })
        .catch(() => {if(!controller.signal.aborted)setHistories(previous => ({...previous,[ticker]:{status:'error',points:[]}}));});
    }
    return () => controller.abort();
  },[key,apiFetch,attempt]);
  const selected = tickers.map(t => histories[t]);
  const asOf = selected.map(h=>h?.asOf).filter(Boolean).sort()[0] || '';
  const first = selected.flatMap(h=>h?.points?.[0]?.date || []).sort()[0] || '';
  return {histories,options,optionsError,asOf,first,
    loading:selected.some(h=>!h || h.status==='loading'),
    failed:tickers.filter(t=>histories[t]?.status==='error'),
    retry:()=>setAttempt(n=>n+1)};
}
