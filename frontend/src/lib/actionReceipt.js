// Retries carry the same identity, event ID and timestamp; collection is optional.
export async function sendActionReceipt(action, context, { delay = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  try {
    if (!context) return false;
    const { token, ...identity } = context;
    const body = JSON.stringify({ ...action, ...identity, event_id: crypto.randomUUID(), observed_at: new Date().toISOString() });
    const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch('/api/track/actions', { method: 'POST', headers, body, keepalive: true, signal: AbortSignal.timeout(8000) });
        if (response.ok) return true;
        if (![429, 502, 503, 504].includes(response.status)) return false;
        if (!attempt) await delay(response.status === 429 ? 60000 : 1000);
      } catch {
        if (!attempt) await delay(1000);
      }
    }
  } catch { /* collection must never interrupt the product */ }
  return false;
}
