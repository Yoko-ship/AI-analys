import { sendActionReceipt } from './actionReceipt.js';

const DECORATIONS = new Set(['uz_pub', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'utm_id', 'fbclid', 'gclid', 'li_fat_id']);

export async function routeFingerprint(url) {
  const pairs = [...url.searchParams].filter(([key]) => !DECORATIONS.has(key));
  pairs.sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0);
  const bytes = new TextEncoder().encode(JSON.stringify([url.pathname, pairs, url.hash]));
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
}

export function capturePublicationLanding() {
  let url, token, used = false, listening = false;
  try {
    url = new URL(window.location.href);
    const tokens = url.searchParams.getAll('uz_pub');
    if (tokens.length === 1 && /^[A-Za-z0-9_-]{32}$/.test(tokens[0])) token = tokens[0];
  } catch { /* No publication tag in this environment. */ }
  // Capture before routing rewrites the URL. A later in-app pageview cannot
  // repeat this arrival, but a new navigation in the same session can.
  return function observe(getContext, language) {
    if (!token || used) return;
    const record = async () => {
      if (used || document.visibilityState === 'hidden') return;
      const context = getContext();
      if (!context) return;
      used = true;
      try {
        const proof = await routeFingerprint(url);
        await sendActionReceipt({ kind: 'publication_visit', publication_token: token, route_fingerprint: proof,
          language: ['ru', 'uz', 'en'].includes(language) ? language : 'ru' }, context);
      } catch { /* Hashing or collection failure leaves coverage incomplete. */ }
    };
    if (document.visibilityState !== 'hidden') void record();
    else if (!listening) {
      listening = true;
      const visible = () => {
        if (document.visibilityState === 'hidden') return;
        document.removeEventListener('visibilitychange', visible);
        listening = false;
        void record();
      };
      document.addEventListener('visibilitychange', visible);
    }
  };
}
