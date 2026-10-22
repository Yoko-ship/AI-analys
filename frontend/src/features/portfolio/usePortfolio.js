import { useCallback, useEffect, useRef, useState } from 'react';

/** Refresh our private snapshot; never trigger collection or call OpenInfo. */
export function usePortfolio(apiFetch, enabled) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshError, setRefreshError] = useState(false);
  const request = useRef(null);
  const active = useRef(false);
  const mutation = useRef(false);
  const refresh = useCallback(async () => {
    if (!enabled || !active.current) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const response = await apiFetch('/api/portfolio', { signal: controller.signal, cache: 'no-store' });
      const body = await response.json();
      if (!response.ok || !body?.ok) throw new Error('Portfolio unavailable');
      if (active.current && request.current === controller) {
        setData(body);
        setRefreshError(false);
      }
    } catch (error) {
      if (active.current && request.current === controller && error.name !== 'AbortError') setRefreshError(true);
    } finally {
      if (active.current && request.current === controller) {
        request.current = null;
        setLoading(false);
      }
    }
  }, [apiFetch, enabled]);
  useEffect(() => {
    active.current = true;
    setData(null);
    setLoading(enabled);
    setRefreshError(false);
    if (enabled) refresh();
    const check = () => {
      if (document.visibilityState === 'visible' && !request.current && !mutation.current) refresh();
    };
    const timer = enabled ? setInterval(check, 30_000) : null;
    document.addEventListener('visibilitychange', check);
    window.addEventListener('focus', check);
    return () => {
      active.current = false;
      request.current?.abort();
      request.current = null;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('focus', check);
    };
  }, [enabled, refresh]);
  const beginMutation = () => {
    mutation.current = true;
    request.current?.abort();
    request.current = null;
  };
  const endMutation = () => { mutation.current = false; };
  return { data, loading, refreshError, refresh, beginMutation, endMutation };
}
