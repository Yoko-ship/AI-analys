export const NEWS_TABS = [{
  key: "all",
  type: null
}, {
  key: "economy",
  type: "economy"
},
// market + regulatory
{
  key: "corporate",
  type: "corporate"
},
// corporate_event + financial_report
{
  key: "reporting",
  type: "financial_report"
}, {
  key: "regulator",
  type: "regulatory"
}, {
  key: "calendar",
  type: null
} // forward-looking: meetings + dividends
];
export const NEWS_INSTRUMENTS = ["all", "stock", "bond"];
export function newsInstrumentFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("instrument");
  return NEWS_INSTRUMENTS.includes(wanted) ? wanted : "all";
}
export function newsTabFromLocation() {
  if (typeof window === "undefined") return "all";
  const wanted = new URLSearchParams(window.location.search).get("tab");
  return NEWS_TABS.some(t => t.key === wanted) ? wanted : "all";
}
