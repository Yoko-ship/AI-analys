# 01 — Terminal UI

ТЗ tasks: T-09 (command line + navigation), T-10 (screens), T-11 (export,
CF, CN), T-12 (panels), T-19 (quarterly block), T-24 (сум/$, deposit
comparison).

**Stage B1, implemented 2026-10-17:**
- Command line with suggestions: `lib/terminalCommands.js` plus
  `features/catalog/terminal/`.
- Esc, LAST and HELP; the 1–9/0 keys; `/` focuses the command line.
- Every screen is in the URL (`/catalog?t=SQBN&f=PL&std=MSFO&h=all`).
- History from 2020 by default, with a 2015 option (README D2).
- Screens: SUM, PL, BS, RAT (the shared `IssuerFinancials` view, also used
  by the company page), DVD, CF, CN and DQ. FV, RV and REC are recognised
  and marked «скоро».
- Client events go to the journal (`lib/terminalJournal.js`).
- EQS, MON, PNL, ADM, export and сум/$ remain.

The ТЗ also allows taking the mock-up module `uzterminal.js` whole. We should
**not**: it carries its own data. The terminal must read the existing
endpoints, so that one number has one source on the whole site.

## R-U1 Command line — PARTIAL

- **Intent:** one input. `TICKER FUNC` (+ optional standard, e.g.
  `AGBA MSFO PL`) and Enter open a screen. A market function needs no ticker
  (`CAT`, `EQS`, `MON`, `ADM`). An unknown command shows a message and
  logs `cmd_unknown`.
- **Already there:** `/catalog` is `frontend/src/features/catalog/CatalogView.jsx`.
  Its header is already styled as a "terminal" (`catalog-terminal-head`,
  ~l.887), and it already has a search box, sector/form/year filters and an
  issuer list (~904–947). The ticker substring filter is at ~804–817.
- **Gap:** no command input, no parser, no keyboard model. The only global
  key handler closes menus on Escape (`frontend/src/app/useShell.jsx:36`).
- **Approach:** add a pure `parseCommand(text, tickers, functions)` →
  `{ticker, func, form}` module with unit tests, and a command bar at the top
  of `CatalogView`. Each command maps onto the existing URL state
  (`app/useNavigation.jsx` pushState), so every screen stays linkable and the
  browser Back button keeps working.

## R-U2 Autocomplete — PARTIAL

- **Intent:** suggestions drop down while typing (tickers, then functions),
  chosen with the arrow keys.
- **Already there:** plain `<datalist>` inputs
  (`features/research/AnalysisWorkspace.jsx:131,144`,
  `ComparisonWorkspace.jsx:73`). The issuer list is already loaded on
  /catalog from `/api/catalog/companies` (`server/catalog/routes.py:664`).
- **Gap:** no reusable combobox with keyboard navigation. The only server
  search, `/api/admin/companies/search`, is admin-only.
- **Approach:** a client-side combobox over the list already loaded (about
  65 issuers, so no new endpoint is needed), reusable by the research pages
  that use `<datalist>` today.

## R-U3 Esc / LAST / HELP / tabs 1–9, 0 — PARTIAL

- **Intent:** Esc goes back one screen; LAST lists the last 8 screens; HELP
  lists functions and keys; number keys switch issuer tabs.
- **Already there:** pushState/popstate navigation and a single `prevView`
  (`app/useNavigation.jsx:46,51,82`).
- **Gap:** only one step of history is kept, and there is no screen list.
- **Approach:** keep a screen stack (last 8, in sessionStorage) beside the
  URL. Esc = history back. HELP is generated from the same function registry
  as the parser, so the help can never drift from the commands.

## R-U4 Screens — mostly EXISTS as data, needs terminal views

The function registry maps each code to an existing endpoint:

| Code | Intent | Existing source | Status |
|---|---|---|---|
| CAT | catalog: search, sector, «has МСФО» | `/api/catalog/companies`; current CatalogView list | EXISTS |
| EQS | screener with filters + saved templates | market table columns (`market/marketColumns.js`), `/api/market/multiples` | PARTIAL: no numeric filters, D/E or dividend-yield columns, or saved screens |
| MON | tiles across issuers by ROE / dividends / profit growth | `/api/heatmap` (`server/market/routes.py:454`) colours by trading, not fundamentals | PARTIAL: needs a fundamentals metric |
| SUM | overview, verdict, risks | CompanyPage overview; AI report verdict | EXISTS |
| PL / BS | P&L bridge, balance structure | `/api/company/{t}/financials` (`server/company/financial_routes.py:27`), `company/Financials.jsx` | EXISTS |
| RAT | ratios, CAGR, quarterly block | `CatalogRatioTable` (`CatalogView.jsx:363`); CAGR missing (see 03) | PARTIAL |
| RV | peers of the same type and standard | `/api/catalog/peers/{t}` (`server/catalog/routes.py:796`) | PARTIAL: used only to pick a compare ticker; needs a peer table |
| DVD | dividends, yield vs deposit | `/api/dividends/{t}` (`server/news/routes.py:620`) | PARTIAL: deposit rate missing (05) |
| CF | filings with links; filings without a year flagged | `/api/catalog/index/{t}` (`server/catalog/routes.py:689`) | EXISTS |
| CN | news for the issuer's tickers | `/api/news/ticker/{t}` (`server/news/routes.py:410`) | PARTIAL: endpoint exists, shown only inside articles |
| REC | НСБУ ↔ МСФО by year | `/financials?form=NSBU` and `form=MSFO` both exist | MISSING: no side-by-side view |
| DQ | data-quality checks + source | `/api/audit/badge/{t}` (public), `/api/admin/issuer/{t}`, `/api/admin/data-quality/*` | PARTIAL: no frontend uses them for an issuer |
| FV | valuation range | see 03 R-A11 | MISSING (admin-only first) |
| HDS | owners ≥5% | — | deferred by the ТЗ |

**Approach:** a screen is a thin view over one endpoint, rendered with the
components the company page already uses (do not fork `Financials.jsx`).
Every screen must reach the ТЗ's "under 2 s" target. A screen that misses it
logs `screen_slow` (04).

## R-U5 Export of any table — PARTIAL

- **Intent:** a CSV button on every table; the file opens in Excel without
  breaking Cyrillic (T-11 acceptance).
- **Already there:** `features/market/marketExport.js:139-146` writes CSV
  with a UTF-8 BOM and CRLF, which is exactly what Excel needs. The server
  already has CSV/XLSX exports in `issuer_analysis_api.py:934`,
  `server/research/routes.py:138,192` and `server/audit/routes.py:169`.
- **Gap:** /catalog tables only offer `window.print()` (~l.1109).
- **Approach:** lift the BOM+CRLF writer out of `marketExport.js` into one
  shared `tableToCsv()` and attach it to every terminal table. Log `export`.

## R-U6 Panels (PNL) — MISSING

- **Intent:** up to 4 screens side by side, each with its own ticker and
  function; the layout survives a reload and is kept in the user profile.
- **Already there:** a server-side preferences store,
  `PATCH /api/profile/preferences` (`server/accounts/routes.py:232`), with a
  fixed whitelist (`routes.py:47-59`, `identity/settings.py:33`).
- **Gap:** no layout model; no layout field on the whitelist.
- **Approach:** add one validated `terminal_layout` preference (at most 4
  panels × `{ticker, func, form}`) to the existing whitelist. Guests keep the
  layout in localStorage. A panel is just a command string, so restoring it
  reuses the parser.

## R-U7 сум / $ toggle — MISSING

- **Intent:** history charts in sums or in dollars at the CBU rate on the
  report date (year end), plus CAGR in $.
- **Already there:** `/api/currency/rates` gives **today's** rates only
  (`server/currency/routes.py:25,77`).
- **Gap:** no rate history by date (05, R-C3).
- **Approach:** after R-C3, the conversion is done client-side, one rate per
  period end, and the screen states the rate and date.

## R-U8 Quarterly block (T-19) — PARTIAL

- **Intent:** growth against the same quarter last year, same-quarter CAGR,
  LTM, seasonality (each quarter's share of the year) and a year × quarter
  heat map, covering 2022–2026.
- **Already there:** discrete quarters (Q4 = year − 9M) in
  `server/company/financials.py:90-227` and `catalogue/ratios.py:735-751`;
  seasonality as an absolute average per quarter (`ratios.py:753-768`),
  shown in `CatalogView.jsx:489-509`; TTM in the multiples.
- **Gap:** seasonality as a share of the year; a standalone-quarter YoY
  series; the heat map.
- **Approach:** derive all of them from the discrete-quarter series that
  already exists. There is no new ingestion.
