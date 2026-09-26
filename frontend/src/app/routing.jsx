

// --- Client-side routing: each view maps to a real URL path ------------------
const VIEW_PATHS = {
  main: "/",
  market: "/market",
  heatmap: "/heatmap",
  catalog: "/catalog",
  news: "/news",
  feedback: "/feedback",
  // Commercial-bank exchange rates — reached from the «Рынок» drop-down and
  // the CBU strip on the board, not from the top-level nav row.
  bankfx: "/currency",
  profile: "/profile",
  auth: "/login",
  // Internal, reached by direct link, not from the nav: the admin panel lives at
  // /admin/{section}. The old secret-in-a-field audit screen used to own
  // /admin/audit, so that path is kept and now opens the panel's Аудит section.
  admin: "/admin",
};

// These workspaces are currently unavailable in the public interface. Keeping
// this rule beside the route table makes old bookmarks land safely on the home
// page and prevents in-app callbacks from reopening a hidden workspace.
const HIDDEN_VIEWS = new Set(["analysis", "compare", "portfolio"]);

function viewToPath(view, ticker, newsId, adminSection) {
  if (HIDDEN_VIEWS.has(view)) return "/";
  if (view === "company" && ticker) return `/company/${encodeURIComponent(ticker)}`;
  // The advanced chart is a page, not a tab: it has its own toolbar state and
  // that state lives in the query string, so the view has to be linkable.
  if (view === "chart" && ticker) return `/chart/${encodeURIComponent(ticker)}`;
  // One bond issue on its own page, like /company/{T} for an issuer.
  if (view === "bond" && ticker) return `/bond/${encodeURIComponent(ticker)}`;
  if (view === "newsArticle" && newsId) return `/news/${encodeURIComponent(newsId)}`;
  if (view === "announcementArticle" && newsId) {
    return `/news/announcement/${encodeURIComponent(newsId)}`;
  }
  if (view === "admin") {
    return adminSection && adminSection !== "overview" ? `/admin/${adminSection}` : "/admin";
  }
  return VIEW_PATHS[view] || "/";
}

function pathToView(pathname) {
  const clean = (pathname || "/").replace(/\/+$/, "") || "/";
  if (clean.startsWith("/company/")) {
    return { view: "company", ticker: decodeURIComponent(clean.slice("/company/".length)), newsId: null };
  }
  if (clean.startsWith("/chart/")) {
    return { view: "chart", ticker: decodeURIComponent(clean.slice("/chart/".length)), newsId: null };
  }
  if (clean.startsWith("/bond/")) {
    return { view: "bond", ticker: decodeURIComponent(clean.slice("/bond/".length)), newsId: null };
  }
  // The bonds list is the market page's own «Облигации» segment, not a page of
  // its own — an old /bonds link lands on the board with that segment selected.
  if (clean === "/bonds") {
    return { view: "market", ticker: null, newsId: null };
  }
  // Calendar notices and editorial stories are different resources. Check the
  // longer announcement path first so its id is not mistaken for "announcement".
  if (clean.startsWith("/news/announcement/")) {
    const id = decodeURIComponent(clean.slice("/news/announcement/".length)).split("/")[0];
    return id ? { view: "announcementArticle", ticker: null, newsId: id }
              : { view: "news", ticker: null, newsId: null };
  }
  // /news is the feed; /news/{id} is one editorial story on its own page.
  if (clean.startsWith("/news/")) {
    const id = decodeURIComponent(clean.slice("/news/".length)).split("/")[0];
    return id ? { view: "newsArticle", ticker: null, newsId: id }
              : { view: "news", ticker: null, newsId: null };
  }
  if (clean === "/admin" || clean.startsWith("/admin/")) {
    const raw = clean.slice("/admin".length).replace(/^\//, "");
    // Preserve registry deep links, including the dedicated audit screen.
    const section = raw || "overview";
    return { view: "admin", ticker: null, newsId: null, adminSection: section };
  }
  const found = Object.entries(VIEW_PATHS).find(([, p]) => p === clean);
  return { view: found ? found[0] : "main", ticker: null, newsId: null };
}

export { HIDDEN_VIEWS, VIEW_PATHS, pathToView, viewToPath };
