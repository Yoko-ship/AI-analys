import {useEffect, useState} from 'react';
const EMPTY = {};
const TECHNICAL_TIMEOUT_MS = 30_000;

export function useMarketTechnical({enabled, needed, accountKey, apiFetch, loadVersion}) {
  const [state, setState] = useState({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled || !needed || !loadVersion) return;
    const controller = new AbortController();
    const {signal} = controller;
    const request = {owner:accountKey, version:loadVersion};
    const showError = () => setState({...request, status:'error'});
    setState({...request, status:'loading'});
    const deadline = setTimeout(() => {
      controller.abort();
      showError();
    }, TECHNICAL_TIMEOUT_MS);
    apiFetch('/api/market/technical', {signal}).then(async response => {
      if (!response.ok) throw new Error('Technical request failed');
      const body = await response.json();
      if (!body.ok || !body.technical || typeof body.technical !== 'object' || Array.isArray(body.technical)) throw new Error('Technical data unavailable');
      if (!signal.aborted) setState({...request, status:'ready', data:body.technical, asOf:body.as_of});
    }).catch(() => {
      if (!signal.aborted) showError();
    }).finally(() => clearTimeout(deadline));
    return () => {
      clearTimeout(deadline);
      controller.abort();
    };
  }, [enabled, needed, accountKey, apiFetch, loadVersion, attempt]);
  const current = enabled && needed && state.owner === accountKey && state.version === loadVersion;
  return {data:current && state.data || EMPTY, asOf:current && state.asOf,
    status:current ? state.status : needed && enabled ? 'loading' : 'idle',
    retry:() => setAttempt(value => value + 1)};
}
