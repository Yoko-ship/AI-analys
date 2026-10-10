// The news section's tabs (customer, 2026-10-08). Each one is a server-side
// category (news_store.NEWS_CATEGORIES): every story sits under exactly one.
// «Все» asks for no category; «Календарь» is not a feed and fetches its own.
// `primary` tabs sit in the bar; the rest fold into its «Ещё» menu so the bar
// stays one short row. Every tab stays reachable and linkable either way.
export const NEWS_TABS = [
  { key: "all", category: null, primary: true },
  { key: "economy", category: "economy", primary: true },
  { key: "markets", category: "markets", primary: true },
  { key: "corporate", category: "corporate", primary: true },
  { key: "reporting", category: "reports" },
  { key: "companies", category: "companies" },
  { key: "politics", category: "politics" },
  { key: "technology", category: "technology" },
  { key: "other", category: "other" },
  { key: "calendar", category: null, primary: true },
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
