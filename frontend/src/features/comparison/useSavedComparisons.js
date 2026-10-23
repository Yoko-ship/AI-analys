import { useEffect, useRef, useState } from 'react';
import { comparisonQuery, readComparison, readSavedComparisons, SAVED_KEY } from './model.js';

const PATH = '/api/saved-comparisons';
const entryFromServer = entry => ({...entry, query: comparisonQuery(entry.selection)});

// The containing screen is keyed by account id. Never cache account entries in
// browser storage, and ignore replies after sign-out, account switch or unmount.
export function useSavedComparisons(userId, apiFetch) {
  const [saved, setSaved] = useState(() => userId ? [] : readSavedComparisons());
  const [browserSaved, setBrowserSaved] = useState(readSavedComparisons);
  const [loading, setLoading] = useState(Boolean(userId));
  const [loadError, setLoadError] = useState(false);
  const [writeError, setWriteError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const alive = useRef(false);
  const locked = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    if (!userId) return;
    const controller = new AbortController();let active = true;
    setLoading(true);setLoadError(false);
    apiFetch(PATH, {signal: controller.signal, cache: 'no-store'})
      .then(async response => { if (!response.ok) throw new Error('load');return response.json(); })
      .then(body => { if (!body.ok || !Array.isArray(body.comparisons)) throw new Error('load');if (active) setSaved(body.comparisons.map(entryFromServer)); })
      .catch(error => { if (active && error.name !== 'AbortError') setLoadError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false;controller.abort(); };
  }, [userId, apiFetch, attempt]);

  const persistLocal = entries => {
    localStorage.setItem(SAVED_KEY, JSON.stringify(entries));
    setBrowserSaved(entries);
    if (!userId) setSaved(entries);
  };
  const write = async (operation, fn) => {
    if (locked.current) return false;
    locked.current = true;setBusy(true);setWriteError('');
    try { await fn();return alive.current; }
    catch (error) { if (alive.current) setWriteError(error.message === 'limit' ? 'limit' : operation);return false; }
    finally { locked.current = false;if (alive.current) setBusy(false); }
  };
  const post = async (name, selection) => {
    const response = await apiFetch(PATH, {method: 'POST', body: JSON.stringify({name, ...selection})});
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(response.status === 422 && String(body.detail).includes('50 comparisons') ? 'limit' : 'save');
    }
    const body = await response.json();
    if (!body.ok || !body.comparison?.selection) throw new Error('save');
    return entryFromServer(body.comparison);
  };
  const save = (name, selection) => write('save', async () => {
    const query = comparisonQuery(selection);
    if (!userId) {
      persistLocal([{id: String(Date.now()), name, query}, ...saved.filter(entry => entry.query !== query)].slice(0, 10));
      return;
    }
    const entry = await post(name, selection);
    if (alive.current) setSaved(entries => [entry, ...entries.filter(item => item.id !== entry.id)]);
  });
  const remove = id => write('delete', async () => {
    if (!userId) { persistLocal(saved.filter(entry => entry.id !== id));return; }
    const response = await apiFetch(PATH + '/' + encodeURIComponent(id), {method: 'DELETE'});
    if (!response.ok && response.status !== 404) throw new Error('delete');
    if (alive.current) setSaved(entries => entries.filter(entry => entry.id !== id));
  });
  const importBrowser = () => write('import', async () => {
    if (!userId) return;
    for (const local of browserSaved) {
      const entry = await post(local.name, readComparison(local.query));
      if (!alive.current) return;
      setSaved(entries => [entry, ...entries.filter(item => item.id !== entry.id)]);
      // Remove only the successfully persisted item. A partial failure leaves
      // the remaining browser saves available for a safe retry.
      persistLocal(readSavedComparisons().filter(item => item.id !== local.id));
    }
  });
  return {saved, browserSaved, loading, loadError, writeError, busy, save, remove, importBrowser,
    retry: () => setAttempt(value => value + 1), clearError: () => setWriteError('')};
}
