// Shared news-feed helpers (ТЗ §3.11).
//
// The feed arrives ranked by likely price impact, and the page spends that
// ranking on one masthead story plus a stack. The only judgement here is which
// story gets the masthead when the top-ranked one cannot be illustrated.

// How far down the ranking the lead slot may look for a story with a picture.
// Small on purpose: the masthead should still be one of the most important
// stories, not the best-illustrated one.
export const LEAD_LOOKAHEAD = 5;

/**
 * Index of the story that should lead the page.
 *
 * Half the feed will never carry a picture — issuer filings on openinfo,
 * central-bank notices, rating actions — and under «Корпоративные» that is 28 of
 * 49 stories, so the impact ranking regularly puts an imageless one first and the
 * tab opens on a bare headline while forty per cent of it is illustrated.
 *
 * A placeholder slab was tried and rejected: it only announces the absence. So
 * the lead moves instead, and only within the top `lookahead` of the ranking —
 * far enough to find a picture on a normal day, not far enough for a photo to
 * outrank relevance. When nothing near the top has one, the ranking wins and the
 * lead is imageless, which is the honest outcome for a feed of filings.
 *
 * Never drops a story: the caller renders every other index as the stack.
 */
export function pickLeadIndex(items, lookahead = LEAD_LOOKAHEAD) {
  const list = Array.isArray(items) ? items : [];
  if (!list.length || list[0]?.image_url) return 0;
  const found = list.slice(0, Math.max(1, lookahead)).findIndex((i) => i?.image_url);
  return found > 0 ? found : 0;
}
