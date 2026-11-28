import { useCallback, useEffect, useRef, useState } from 'react';
import { reasonText } from './reasonCopy.js';

export function useMarketing(apiFetch) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [sync, setSync] = useState({ updatedAt: null, error: '' });
  const alive = useRef(true);
  const generation = useRef(0);
  const operations = useRef(0);
  const loaded = useRef(false);
  const read = useCallback(async (path, options = {}) => {
    const response = await apiFetch(`/api/admin/ai-marketing${path}`, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const fields = body.error?.field_errors?.map(field => reasonText(field.message.replace(/^Value error, /, '')));
      throw new Error(fields?.join(' ') || reasonText(body.error?.message) || 'Не удалось выполнить действие. Попробуйте ещё раз.');
    }
    return body;
  }, [apiFetch]);
  const accept = useCallback((value, revision) => {
    if (!alive.current || revision !== generation.current) return;
    loaded.current = true;
    setData(value);
    setSync({ updatedAt: new Date().toISOString(), error: '' });
  }, []);
  const reload = useCallback(async (revision = ++generation.current) => {
    const value = await read('/workspace');
    accept(value, revision);
  }, [read, accept]);
  useEffect(() => {
    alive.current = true;
    reload().catch(e => { if (alive.current) setError(e.message); });
    return () => { alive.current = false; generation.current += 1; };
  }, [reload]);
  useEffect(() => {
    let pending = false, disposed = false;
    async function refresh() {
      if (disposed || pending || !loaded.current || operations.current || document.visibilityState !== 'visible') return;
      pending = true;
      const revision = generation.current;
      try {
        const value = await read('/workspace');
        if (!disposed && !operations.current) accept(value, revision);
      } catch (e) {
        if (!disposed && alive.current && revision === generation.current) setSync(previous => ({ ...previous, error: e.message }));
      } finally { pending = false; }
    }
    const timer = setInterval(refresh, 15000);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('focus', refresh);
    return () => {
      disposed = true;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', refresh);
      window.removeEventListener('focus', refresh);
    };
  }, [read, accept]);
  const request = useCallback(async (path, { method = 'GET', body, refresh = method !== 'GET', message = '' } = {}) => {
    const revision = ++generation.current;
    operations.current += 1;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await read(path, { method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      if (path === '/workspace') accept(result, revision);
      else if (refresh && revision === generation.current) await reload(revision);
      if (alive.current && revision === generation.current) setNotice(message);
      return result;
    } catch (e) {
      if (alive.current && revision === generation.current) setError(e.message);
      return null;
    } finally {
      operations.current -= 1;
      if (alive.current) setBusy(operations.current > 0);
    }
  }, [read, reload, accept]);
  const readFile = useCallback(async path => {
    const response = await apiFetch(`/api/admin/ai-marketing${path}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.error?.message || 'Файл недоступен. Обновите материал и проверьте рендер.');
    }
    return response.blob();
  }, [apiFetch]);
  const downloadFile = useCallback(async (path, filename) => {
    operations.current += 1;
    setBusy(true);
    setError('');
    try {
      const blob = await readFile(path);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { if (alive.current) setError(e.message); }
    finally { operations.current -= 1; if (alive.current) setBusy(operations.current > 0); }
  }, [readFile]);
  return { data, error, notice, busy, sync, request, reload, readFile, downloadFile };
}
