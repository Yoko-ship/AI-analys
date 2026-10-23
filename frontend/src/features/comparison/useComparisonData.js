import { useEffect, useState } from 'react';
import { apiQuery, comparisonMatches } from './model.js';

export function useComparisonData(state, apiFetch) {
  const [data,setData]=useState(null);
  const [options,setOptions]=useState({companies:[],periods:[]});
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState(false);
  const [optionsError,setOptionsError]=useState(false);
  const [attempt,setAttempt]=useState(0);
  const query=apiQuery(state);
  const hasSelection=state.tickers.length>0;
  useEffect(()=>{
    const controller=new AbortController();let alive=true;
    setOptionsError(false);
    apiFetch('/api/company-comparison/options'+query,{signal:controller.signal})
      .then(async response=>{if(!response.ok)throw new Error('options');const body=await response.json();if(!body.ok||!Array.isArray(body.companies)||!Array.isArray(body.periods))throw new Error('options');return body;})
      .then(body=>{if(alive)setOptions(body);})
      .catch(e=>{if(alive&&e.name!=='AbortError')setOptionsError(true);});
    return()=>{alive=false;controller.abort();};
  },[query,apiFetch,attempt]);
  useEffect(()=>{
    const controller=new AbortController();let alive=true;
    setData(null);setError(false);setLoading(hasSelection);
    if(hasSelection){
      apiFetch('/api/company-comparison'+query,{signal:controller.signal})
        .then(async response=>{if(!response.ok)throw new Error('comparison');const body=await response.json();if(!comparisonMatches(body,state))throw new Error('comparison');return body;})
        .then(body=>{if(alive)setData(body);})
        .catch(e=>{if(alive&&e.name!=='AbortError')setError(true);})
        .finally(()=>{if(alive)setLoading(false);});
    }
    return()=>{alive=false;controller.abort();};
    // query contains every server-side selector; display units do not affect data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[query,apiFetch,attempt,hasSelection]);
  return {data,options,loading,error:error||optionsError,retry:()=>setAttempt(value=>value+1)};
}
