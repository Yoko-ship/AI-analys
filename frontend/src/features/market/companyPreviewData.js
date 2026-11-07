import { useEffect, useState } from 'react';

// The board owns this cache: hovering a row again reuses its requests, while a
// new visit gets fresh data. Failed requests are retried on the next opening.
export function usePreviewResource(url, cache) {
  const [state, setState] = useState({ status: 'loading', data: null });
  useEffect(() => {
    let alive = true;
    let entry = cache.get(url);
    if (!entry || entry.expires < Date.now()) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12000);
      entry = { expires: Date.now() + 60000, controller };
      entry.promise = fetch(url, { signal: controller.signal })
        .then(async response => {
          if (!response.ok) throw new Error('Preview unavailable');
          const data = await response.json();
          if (data.ok === false) throw new Error('Preview unavailable');
          return { status: 'ready', data };
        })
        .catch(() => {
          if (cache.get(url) === entry) cache.delete(url);
          return { status: 'error', data: null };
        })
        .finally(() => clearTimeout(timeout));
      if (cache.size >= 40) cache.delete(cache.keys().next().value);
      cache.set(url, entry);
    }
    entry.promise.then(result => { if (alive) setState(result); });
    return () => { alive = false; };
  }, [url, cache]);
  return state;
}
