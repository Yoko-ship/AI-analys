// Where a tap on a notification leads. Every notification has a destination:
// the server names it outright with `href` (operational alerts for admins),
// and anything else is about a listed company, so it opens that company.
// Routing by the item rather than by its `kind` keeps a new kind of alert
// from arriving as a dead row in the bell — reports and price alerts once did.
export function notificationPath(notification) {
  const href = String(notification?.href || "").trim();
  if (href.startsWith("/")) return href;
  const ticker = String(notification?.ticker || "").trim().toUpperCase();
  if (ticker && ticker !== "ADMIN") return `/company/${encodeURIComponent(ticker)}`;
  return null;
}
