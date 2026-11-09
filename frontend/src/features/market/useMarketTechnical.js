import {useEffect, useState} from 'react';
const EMPTY = {};

export function useMarketTechnical({enabled, needed, accountKey, apiFetch, loadVersion}) {
  const [state, setState] = useState({});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled || !needed || !loadVersion) return;
    const controller = new AbortController();
    let alive = true;
    setState({owner:accountKey, version:loadVersion, status:'loading'});
    apiFetch('/api/market/technical', {signal:controller.signal}).then(async response => {
      if (!response.ok) throw new Error('Technical request failed');
      const body = await response.json();
      if (!body.ok || !body.technical || typeof body.technical !== 'object' || Array.isArray(body.technical)) throw new Error('Technical data unavailable');
      if (alive) setState({owner:accountKey, version:loadVersion, status:'ready', data:body.technical, asOf:body.as_of});
    }).catch(() => {
      if (alive) setState({owner:accountKey, version:loadVersion, status:'error'});
    });
    return () => { alive = false; controller.abort(); };
  }, [enabled, needed, accountKey, apiFetch, loadVersion, attempt]);
  const current = enabled && needed && state.owner === accountKey && state.version === loadVersion;
  return {data:current && state.data || EMPTY, asOf:current && state.asOf,
    status:current ? state.status : needed && enabled ? 'loading' : 'idle',
    retry:() => setAttempt(value => value + 1)};
}
