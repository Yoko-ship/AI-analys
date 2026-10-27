// Language-prefixed URLs (frontend/src/lib/languagePath.js, frontend/src/app/routing.jsx).
// Russian owns the bare paths; Uzbek owns the same paths under /uz so search
// engines can index it. The router must read and write both forms.
import { strict as assert } from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { register } from "node:module";
import { describe, it } from "node:test";
import { NEWS_TABS, newsTabFromLocation } from "../frontend/src/features/news/newsRouting.js";

// routing.jsx holds no JSX; let Node load it as the plain module it is.
register("data:text/javascript," + encodeURIComponent(`export async function load(url, context, next) {
  return url.endsWith(".jsx") ? next(url, { ...context, format: "module" }) : next(url, context);
}`));

const lib = await import("../frontend/src/lib/languagePath.js");
const routing = await import("../frontend/src/app/routing.jsx");
const { HIDDEN_VIEWS, URL_LANGUAGES, VIEW_PATHS, localizedPath, pathToView, splitLanguagePath, viewToPath } = routing;

describe("splitLanguagePath", () => {
  it("reads the /uz prefix as a whole segment", () => {
    assert.deepEqual(splitLanguagePath("/uz"), { language: "uz", path: "/" });
    assert.deepEqual(splitLanguagePath("/uz/"), { language: "uz", path: "/" });
    assert.deepEqual(splitLanguagePath("/uz/market"), { language: "uz", path: "/market" });
    assert.deepEqual(splitLanguagePath("/uz/company/AGBA"), { language: "uz", path: "/company/AGBA" });
  });

  it("leaves bare paths, and paths that merely start with the letters, alone", () => {
    for (const p of ["/", "/market", "/uzbek-something", "/uzx", "/uz-market", "/market/uz", "/company/UZTL"]) {
      assert.deepEqual(splitLanguagePath(p), { language: null, path: p }, p);
    }
    assert.deepEqual(splitLanguagePath(""), { language: null, path: "/" });
    assert.deepEqual(splitLanguagePath(undefined), { language: null, path: "/" });
  });
});

describe("localizedPath", () => {
  it("adds the prefix for a language with URLs of its own", () => {
    assert.equal(localizedPath("/market", "uz"), "/uz/market");
    assert.equal(localizedPath("/", "uz"), "/uz");
    assert.equal(localizedPath("/company/AGBA", "uz"), "/uz/company/AGBA");
    assert.equal(localizedPath("/uzbek-something", "uz"), "/uz/uzbek-something");
  });

  it("keeps the query string and hash after the path", () => {
    assert.equal(localizedPath("/news?tab=calendar", "uz"), "/uz/news?tab=calendar");
    assert.equal(localizedPath("/?utm_source=x", "uz"), "/uz?utm_source=x");
    assert.equal(localizedPath("/company/AGBA#ai", "uz"), "/uz/company/AGBA#ai");
    assert.equal(localizedPath("/uz/news?tab=calendar", "ru"), "/news?tab=calendar");
  });

  it("is idempotent and switches between forms", () => {
    assert.equal(localizedPath("/uz/market", "uz"), "/uz/market");
    assert.equal(localizedPath("/uz/market", "ru"), "/market");
    assert.equal(localizedPath("/uz", "ru"), "/");
    assert.equal(localizedPath(localizedPath("/market", "uz"), "ru"), "/market");
  });

  it("gives Russian, English and an unknown language the bare path", () => {
    for (const language of ["ru", "en", null, undefined, "de"]) {
      assert.equal(localizedPath("/market", language), "/market", String(language));
      assert.equal(localizedPath("/", language), "/", String(language));
    }
  });
});

describe("pathToView / viewToPath", () => {
  it("open the same view from either language's URL, with or without a trailing slash", () => {
    for (const [view, bare] of Object.entries(VIEW_PATHS)) {
      const expected = view === "admin" ? "admin" : view;
      for (const p of [bare, `${bare}/`, localizedPath(bare, "uz"), `${localizedPath(bare, "uz")}/`]) {
        assert.equal(pathToView(p).view, expected, p);
      }
    }
    assert.equal(pathToView("/uz").view, "main");
    assert.equal(pathToView("/uz/").view, "main");
  });

  it("strip the prefix before reading a ticker, story or admin section", () => {
    assert.deepEqual(pathToView("/uz/company/AGBA"), { view: "company", ticker: "AGBA", newsId: null });
    assert.deepEqual(pathToView("/uz/chart/HMKB/"), { view: "chart", ticker: "HMKB", newsId: null });
    assert.deepEqual(pathToView("/uz/bond/X"), { view: "bond", ticker: "X", newsId: null });
    assert.deepEqual(pathToView("/uz/news/42"), { view: "newsArticle", ticker: null, newsId: "42" });
    assert.deepEqual(pathToView("/uz/news/announcement/5"), { view: "announcementArticle", ticker: null, newsId: "5" });
    assert.equal(pathToView("/uz/admin/users").adminSection, "users");
    assert.equal(pathToView("/uz/bonds").view, "market");
  });

  it("do not read a lookalike segment as the prefix", () => {
    assert.equal(pathToView("/uzmarket").view, "main");
    assert.equal(pathToView("/uzbek-something/company/AGBA").view, "main");
  });

  it("write each view in the requested language and read it back", () => {
    const cases = [
      ...Object.keys(VIEW_PATHS).map((view) => [view, null, null, null]),
      ["company", "AGBA", null, null], ["chart", "HMKB", null, null], ["bond", "UZ6011340002", null, null],
      ["newsArticle", null, "42", null], ["announcementArticle", null, "5", null], ["admin", null, null, "users"],
    ];
    for (const [view, ticker, newsId, section] of cases) {
      const ru = viewToPath(view, ticker, newsId, section, "ru");
      const uz = viewToPath(view, ticker, newsId, section, "uz");
      assert.equal(viewToPath(view, ticker, newsId, section), ru, view);
      assert.equal(viewToPath(view, ticker, newsId, section, "en"), ru, view);
      assert.equal(uz, localizedPath(ru, "uz"), view);
      assert.ok(uz === "/uz" || uz.startsWith("/uz/"), uz);
      for (const p of [ru, uz]) {
        const back = pathToView(p);
        assert.equal(back.view, view, p);
        if (ticker) assert.equal(back.ticker, ticker, p);
        if (newsId) assert.equal(back.newsId, newsId, p);
        if (section) assert.equal(back.adminSection, section, p);
      }
    }
    assert.equal(viewToPath("main", null, null, null, "uz"), "/uz");
    for (const hidden of HIDDEN_VIEWS) assert.equal(viewToPath(hidden, null, null, null, "uz"), "/uz");
  });
});

describe("one list of URL languages", () => {
  it("the router re-exports the list it routes by", () => {
    assert.equal(URL_LANGUAGES, lib.URL_LANGUAGES);
    assert.deepEqual(URL_LANGUAGES, ["uz"]);
  });

  it("no frontend code writes an internal path past localizedPath", () => {
    // A literal internal path in an href or a history call would drop the
    // reader's /uz prefix on that one link; every such path is built with
    // localizedPath (or viewToPath) instead.
    const root = "frontend/src";
    const files = [];
    const walk = (dir) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const file = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(file);
        else if (/\.[jt]sx?$/.test(entry.name)) files.push(file);
      }
    };
    walk(root);
    const literalPath = /(?:pushState|replaceState)\([^;]*?,\s*["'`]\/(?!api\/)|href=["'`{]+\/(?!api\/|\/)/;
    const offenders = [];
    for (const file of files) {
      fs.readFileSync(file, "utf8").split("\n").forEach((line, i) => {
        if (literalPath.test(line)) offenders.push(`${file}:${i + 1}: ${line.trim()}`);
      });
    }
    assert.deepEqual(offenders, []);
  });
});

it('opens the portfolio workspace from bookmarks and navigation', () => {
  for (const pathname of ['/portfolio', '/portfolio/', '/uz/portfolio', '/uz/portfolio/']) {
    assert.equal(pathToView(pathname).view, 'portfolio');
  }
  assert.equal(viewToPath('portfolio'), '/portfolio');
  assert.equal(viewToPath('portfolio', null, null, null, 'uz'), '/uz/portfolio');
  assert.ok(!HIDDEN_VIEWS.has('portfolio'));
});
it("news offers two reading sections and preserves old links", () => {
  assert.deepEqual(NEWS_TABS.map(tab => tab.key), ["general", "corporate"]);
  const previous = globalThis.window;
  try {
    for (const [query, expected] of [
      ["", "general"], ["?tab=all", "general"], ["?tab=economy", "general"],
      ["?tab=technology", "general"], ["?tab=regulator", "general"],
      ["?tab=reporting", "corporate"], ["?tab=corporate", "corporate"],
      ["?tab=calendar", "calendar"],
    ]) {
      globalThis.window = { location: { search: query } };
      assert.equal(newsTabFromLocation(), expected, query);
    }
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});
