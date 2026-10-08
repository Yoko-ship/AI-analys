// The news section's tabs (customer, 2026-10-08). Each one is a server-side
// category (news_store.NEWS_CATEGORIES): every story sits under exactly one.
// «Все» asks for no category; «Календарь» is not a feed and fetches its own.
export const NEWS_TABS = [
  { key: "all", category: null },
  { key: "economy", category: "economy" },
  { key: "corporate", category: "corporate" },
  { key: "reporting", category: "reports" },
  { key: "markets", category: "markets" },
  { key: "companies", category: "companies" },
  { key: "politics", category: "politics" },
  { key: "technology", category: "technology" },
  { key: "other", category: "other" },
  { key: "calendar", category: null },
];
// Links written before the tabs were renamed keep landing on the same stories.
const LEGACY_TABS = { regulator: "politics" };
export const NEWS_INSTRUMENTS = ["all", "stock", "bond"];
export function newsInstrumentFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("instrument");
  return NEWS_INSTRUMENTS.includes(wanted) ? wanted : "all";
}
export function newsTabFromLocation() {
  if (typeof window === "undefined") return "all";
  const raw = new URLSearchParams(window.location.search).get("tab");
  const wanted = LEGACY_TABS[raw] || raw;
  return NEWS_TABS.some(t => t.key === wanted) ? wanted : "all";
}
