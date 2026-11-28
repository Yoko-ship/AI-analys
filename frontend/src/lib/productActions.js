import { productContext } from './track.js';
import { sendActionReceipt } from './actionReceipt.js';

const KINDS = new Set(['issuer_open', 'news_open', 'chart_open', 'report_open', 'search', 'search_empty', 'search_open', 'favorite']);
let pendingResult = null;

// A result click is only intent. The destination's visible, loaded content confirms it.
export function markSearchResult(object) {
  pendingResult = { ...object, until: Date.now() + 60000 };
}

export function clearSearchResult(object) {
  if (pendingResult && ((object.news_id && object.news_id === pendingResult.news_id)
      || (object.ticker && object.ticker === pendingResult.ticker))) pendingResult = null;
}

function cleanAction(raw) {
  if (!KINDS.has(raw.kind) || !['ru', 'uz', 'en'].includes(raw.language)) return null;
  const value = { kind: raw.kind, language: raw.language };
  if (['issuer_open', 'chart_open', 'favorite', 'report_open'].includes(raw.kind) || (raw.kind === 'search_open' && raw.ticker)) {
    if (!/^[A-Z0-9._-]{1,20}$/.test(raw.ticker || '')) return null;
    value.ticker = raw.ticker;
  }
  if (raw.kind === 'news_open' || (raw.kind === 'search_open' && !raw.ticker)) {
    if (!Number.isSafeInteger(raw.news_id) || raw.news_id < 1) return null;
    value.news_id = raw.news_id;
  }
  if (raw.kind === 'report_open') {
    if (!['nsbu', 'ifrs'].includes(raw.standard) || !['separate', 'consolidated'].includes(raw.scope)
        || !/^\d{4}(Q[1-4])?$/.test(raw.period || '') || !/^[A-Za-z0-9_-]{1,200}$/.test(raw.version || '')) return null;
    Object.assign(value, { standard: raw.standard, scope: raw.scope, period: raw.period, version: raw.version });
  }
  if (['search', 'search_empty', 'search_open'].includes(raw.kind)) {
    if (!['news_feed', 'issuer_directory', 'catalog'].includes(raw.search_area)) return null;
    value.search_area = raw.search_area;
  }
  if (['search', 'search_empty'].includes(raw.kind)) {
    if (!['ticker', 'other'].includes(raw.query_type) || !['complete', 'partial'].includes(raw.search_scope)
        || !Number.isInteger(raw.result_count) || raw.result_count < 0 || raw.result_count > 1000) return null;
    if (raw.kind === 'search_empty' && (raw.result_count !== 0 || raw.search_scope !== 'complete')) return null;
    if (raw.query_type === 'ticker') {
      if (!/^[A-Z0-9._-]{1,20}$/.test(raw.ticker || '')) return null;
      value.ticker = raw.ticker;
    }
    Object.assign(value, { query_type: raw.query_type, result_count: raw.result_count, search_scope: raw.search_scope });
  }
  return value;
}

export async function sendProductAction(raw, options = {}) {
  const action = cleanAction(raw), context = productContext();
  return action && context ? sendActionReceipt(action, context, options) : false;
}

export function trackProductAction(action) {
  if (!cleanAction(action) || !productContext()) return false;
  void sendProductAction(action);
  const match = pendingResult;
  if (match && Date.now() <= match.until && ((action.kind === 'issuer_open' && action.ticker === match.ticker)
      || (action.kind === 'news_open' && action.news_id === match.news_id))) {
    pendingResult = null;
    void sendProductAction({ kind: 'search_open', language: action.language, ticker: match.ticker, news_id: match.news_id, search_area: match.search_area });
  }
  return true;
}
