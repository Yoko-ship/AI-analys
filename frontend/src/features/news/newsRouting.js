// News feeds and the events calendar share one navigation row.
export const NEWS_TABS = [
  { key: "general", section: "general" },
  { key: "corporate", section: "corporate" },
  { key: "calendar", section: null },
];
// Old report links open issuer news; other retired topics open general news.
const LEGACY_TABS = { reporting: "corporate", reports: "corporate" };
export const NEWS_INSTRUMENTS = ["all", "stock", "bond"];
export function newsInstrumentFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("instrument");
  return NEWS_INSTRUMENTS.includes(wanted) ? wanted : "all";
}
export function newsTabFromLocation() {
  if (typeof window === "undefined") return "general";
  const raw = new URLSearchParams(window.location.search).get("tab");
  const wanted = LEGACY_TABS[raw] || raw;
  return NEWS_TABS.some(t => t.key === wanted) ? wanted : "general";
}
