// flags.js — feature flags and thresholds, read from the server (ТЗ §10.10).
//
// Thresholds are configuration in the repository, not constants in code. The
// interface reads the SAME ones the calculation layer applied, so a label can
// never claim a window the server did not use — "MA20" meaning 28 days on one
// side and 134 on the other is precisely the class of bug this closes.
//
// One request, cached for the session. A failure is not fatal: the defaults
// below match `config/thresholds.json`, so the interface degrades to the right
// numbers rather than to none.

const DEFAULTS = {
  flags: {
    catalog_v2: true, metrics_v2: true, tiers_v1: true, multiples_v2: true,
    market_validation_v1: true, map_v2: true, audit_v1: true,
  },
  thresholds: {
    quality: { flat_share_max: 0.5, coverage_min: 0.6 },
    volatility: { window_days: 30, min_observations: 10 },
    moving_average: { ma20_calendar_days: 28, ma50_calendar_days: 70 },
    multiples: { pe_range: [0.5, 200], pb_range: [0.05, 20], roe_abs_max: 100 },
    market_map: { min_trades_confident: 5, min_quantity_confident: 10 },
    bonds: { day_count_basis: "ACT/365" },
  },
};

let cache = null;
let inflight = null;

export async function loadConfig(fetchImpl = fetch) {
  if (cache) return cache;
  if (!inflight) {
    inflight = fetchImpl("/api/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        cache = d && d.ok
          ? { flags: { ...DEFAULTS.flags, ...(d.flags || {}) },
              thresholds: { ...DEFAULTS.thresholds, ...(d.thresholds || {}) } }
          : DEFAULTS;
        return cache;
      })
      .catch(() => {
        cache = DEFAULTS;
        return cache;
      })
      .finally(() => { inflight = null; });
  }
  return inflight;
}

/** Synchronous read of whatever has been loaded — defaults before the response. */
export function config() {
  return cache || DEFAULTS;
}

export function isEnabled(name) {
  return config().flags[name] !== false;
}

/** `threshold("moving_average.ma20_calendar_days")`. */
export function threshold(path, fallback = null) {
  let node = config().thresholds;
  for (const part of String(path || "").split(".")) {
    if (!node || typeof node !== "object" || !(part in node)) return fallback;
    node = node[part];
  }
  return node;
}

export function resetForTests() {
  cache = null;
  inflight = null;
}
