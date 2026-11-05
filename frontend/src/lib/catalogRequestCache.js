export async function readJson(url, {validate, ...options} = {}, fetcher = fetch) {
  const response = await fetcher(url, options);
  const data = await response.json().catch(error => {
    if (response.ok) throw error;
    return null;
  });
  if (!response.ok || data == null || data?.ok === false || (validate && !validate(data))) {
    throw Object.assign(new Error(response.ok ? 'Invalid API response' : `HTTP ${response.status}`), {errorId:data?.error_id});
  }
  return data;
}

// A catalog visit owns this cache. No persisted data or cross-session sharing.
// Keep in-flight reads when tabs unmount so the next screen can reuse them.
export function createCatalogRequestCache({fetcher = fetch, now = Date.now, ttl = 60_000, maxEntries = 64} = {}) {
  const entries = new Map();
  const peek = url => {
    const entry = entries.get(url);
    return entry?.expiresAt > now() ? entry.data : null;
  };
  const trim = () => {
    for (const [url, entry] of entries) {
      if (entries.size <= maxEntries) break;
      if (entry.expiresAt !== undefined) entries.delete(url);
    }
  };
  const read = (url, {validate} = {}) => {
    let entry = entries.get(url);
    if (entry && (entry.expiresAt === undefined || entry.expiresAt > now())) {
      entries.delete(url); entries.set(url, entry);
      return entry.promise;
    }
    const controller = new AbortController();
    entry = {controller};
    entries.delete(url); entries.set(url, entry);
    entry.promise = readJson(url, {signal:controller.signal, validate}, fetcher).then(data => {
      if (entries.get(url) === entry) {
        entry.data = data; entry.expiresAt = now() + ttl; trim();
      }
      return data;
    }, error => {
      if (entries.get(url) === entry) entries.delete(url);
      throw error;
    });
    return entry.promise;
  };
  const clear = () => {
    for (const entry of entries.values()) entry.controller.abort();
    entries.clear();
  };
  return {read, peek, clear};
}
