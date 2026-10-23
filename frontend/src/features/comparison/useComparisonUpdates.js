import { useCallback, useEffect, useRef, useState } from 'react';
import { comparisonQuery } from './model.js';

const path = id => '/api/saved-comparisons/' + encodeURIComponent(id);
async function inspect(apiFetch, id, signal) {
  const response = await apiFetch(path(id) + '/updates', {signal, cache: 'no-store'});
  if (!response.ok) throw new Error('updates');
  const body = await response.json();
  if (!body.ok || body.comparison_id !== id || !Array.isArray(body.changes)) throw new Error('updates');
  return body;
}

export function useComparisonUpdates({userId, apiFetch, saved, selection, menuOpen}) {
  const active = userId ? saved.find(item => item.query === comparisonQuery(selection)) : null;
  const id = active?.id || null;
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [seenError, setSeenError] = useState(false);
  const [checks, setChecks] = useState({});
  const [attempt, setAttempt] = useState(0);
  const alive = useRef(false);
  const acknowledged = useRef({});
  const pending = useRef(null);
  const savedIds = saved.map(item => item.id).join(',');
  useEffect(() => { alive.current = true;return () => {alive.current = false;pending.current?.abort();}; }, []);
  useEffect(() => {
    setDetail(null);setError(false);setSeenError(false);setLoading(Boolean(id));
    pending.current?.abort();
    pending.current = null;
    if (!id) return;
    const controller = new AbortController();let current = true;
    inspect(apiFetch, id, controller.signal)
      .then(body => { if (current) setDetail(body); })
      .catch(e => { if (current && e.name !== 'AbortError') setError(true); })
      .finally(() => { if (current) setLoading(false); });
    return () => { current = false;controller.abort(); };
  }, [id, apiFetch, attempt]);

  useEffect(() => {
    if (!userId || !menuOpen || !savedIds) return;
    const controller = new AbortController();let current = true;
    const queue = savedIds.split(',');
    // A large saved list must not launch fifty simultaneous filing reads.
    const worker = async () => {
      while (current && queue.length) {
        const identifier = queue.shift();
        try {
          const body = await inspect(apiFetch, identifier, controller.signal);
          if (current) setChecks(values => ({...values, [identifier]: {
            updated: body.updated && acknowledged.current[identifier] !== body.snapshot_key}}));
        } catch (e) {
          if (current && e.name !== 'AbortError') setChecks(values => ({...values, [identifier]: {failed: true}}));
        }
      }
    };
    worker();worker();
    return () => { current = false;controller.abort(); };
  }, [userId, apiFetch, menuOpen, savedIds, attempt]);

  const visibleDetail = detail?.comparison_id === id ? detail : null;
  const markSeen = useCallback(async () => {
    if (!visibleDetail || pending.current) return;
    const controller = new AbortController();pending.current = controller;
    try {
      const response = await apiFetch(path(visibleDetail.comparison_id) + '/seen', {method: 'POST', signal: controller.signal,
        body: JSON.stringify({snapshot_key: visibleDetail.snapshot_key, baseline_key: visibleDetail.baseline_key})});
      if (!response.ok) throw new Error('seen');
      if (!alive.current || controller.signal.aborted) return;
      acknowledged.current[visibleDetail.comparison_id] = visibleDetail.snapshot_key;
      setChecks(values => ({...values, [visibleDetail.comparison_id]: {updated: false}}));
    } catch (e) { if (alive.current && !controller.signal.aborted && e.name !== 'AbortError') setSeenError(true); }
    // Keep the controller after completion to prevent duplicate acknowledgements.
    // Changing the selected comparison or retrying aborts and clears it below.
  }, [visibleDetail, apiFetch]);
  const retry = () => {pending.current?.abort();pending.current = null;setAttempt(value => value + 1);};
  return {id, detail: visibleDetail, loading: Boolean(id) && loading, error: Boolean(id) && error,
    seenError, checks, markSeen, retry};
}
