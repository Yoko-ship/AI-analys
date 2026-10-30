# Catalog terminal — requirements

Source: «ТЗ: терминал каталога UZStock с логированием» (14.10.2026, amended
15.10.2026, 21 pages). Visual reference: `UZStock_terminal_TZ_maket.html`
(15.10), sent with the ТЗ.

## Public catalog access

The catalog at `/catalog` is available to guests and signed-in users, with a
navigation entry on desktop and mobile. Browsing reports does not require an
administrator account or a paid plan. Bookmarks also work while session
verification is pending and after logout.

Administration (`ADM`), full catalog synchronization, and unvalidated valuation
models remain restricted to administrators. Source refresh and analysis retain
their existing authentication and API permission checks.

For local viewing, run the API on port 8000 and `npm run dev`, then open
`http://localhost:5173/catalog`. Production builds provide the same public access.

## Implementation review — 2026-10-23

Compared the supplied `ТЗ_терминал_каталога_UZStock_с_логированием_1.pdf`
and `UZStock_terminal_TZ_maket (3).html` against the application. The PDF
sets requirements; the HTML supplies layout and dated example values. Its
embedded issuer/CBU data are **test evidence**, not a production data source.
The detailed fundamental-only scope takes precedence over the introductory
mentions of quotes: the catalogue price chart was removed. HDS remains
deferred; FV stays behind the human-admin API gate.

The following status describes implementation; production evidence and remaining
acceptance limits are recorded in the release report.
Existing comparison/account changes in the working tree were preserved.

| TZ tasks | Implementation and remaining acceptance |
|---|---|
| T-01–02 | Existing empty-file rejection and duplicate selection retained. Some named annual filings are empty or mislabelled upstream; do not manufacture replacements. See the measured Stage C results in `02-data.md`. |
| T-03 | Implemented after the D4 audit: unreviewed profit/equity above 1.5× assets and annual balance spikes above both adjacent years are withheld from financial API series and dependent ratios. Flow/cash jumps are excluded following measured false positives. Exact source-reviewed values remain visible; UZNF 2025Q1 was rechecked against filing 18012. KVTS 2020 liabilities now reconcile the form’s two independent arithmetic witnesses. Originals remain intact; every quarantine is journaled. |
| T-04–05 | Existing comparative backfill and discrete-quarter derivation retained; coverage now distinguishes loaded, comparative, missing, unregistered and unavailable periods. Production annual coverage is 95.39% of registered periods; source gaps remain explicit. |
| T-06 | Six visually checked UZMT 2020–2025 IFRS periods added to the reviewed ledger. USD originals, source hashes/pages and dated CBU year-end conversion evidence are retained. 2020/2023 are explicitly restated comparative columns. The 2021 liabilities total uses disclosed component arithmetic because the printed total contains a typo. Published on production: six periods and 48 verified figures, with a pre-publication backup. |
| T-07 | High risk now requires attention, including without a comparable period. Medium risk and profit-direction constraints remain. Shared annualised NIM/cost-of-risk and P1–P8 names added; report calculation version is `nsbu-core-2.5`. |
| T-08 | Existing fund routing/share-reconciliation guard retained. Terminal summary treats equity as NAV and suppresses corporate revenue for funds. A missing verified share basis still prevents NAV/share. |
| T-09 | Existing keyboard/command parser extended to working market screens and complete URL context. LAST/HELP retained. |
| T-10 | EQS, MON, SUM, RAT, RV and REC wired to real APIs; shared PL, BS, DVD, CF, CN and DQ reused. Peer selection matches type, standard, scope and year. DQ fails visibly if either financial-history request fails. |
| T-11 | Terminal tables export BOM-prefixed, formula-safe Cyrillic CSV. Exports preserve reporting context, currency and historical FX dates. CF/CN remain connected to existing sources. |
| T-12 | Four independent panels; guest persistence in the browser and authenticated save/load through validated profile preferences. Direct PNL links wait for issuer data. |
| T-13 | Existing journal extended with exact standard/period filters and durable deduplication. Publication, high P/B, insurer checks and governed rule activation now emit events. NSBU comparative and reviewed IFRS replacement changes above 1% now emit deduplicated restatement events with old/new values. Not every catalogue event has been reproduced on production. |
| T-14 | Admin terminal summary, coverage, error filters/full CSV, usage 7/30 days, templates and private FV views. Staff commands excluded from usage. Coverage excludes periods absent from the source registry and does not call a failed source clean. |
| T-15 | Telegram delivery with email fallback, persistent cooldown/retry, and 09:00 Tashkent digest are implemented. User selected existing admin Telegram with primary-admin email fallback. Deployment installs a minute timer in the existing VPS service manager. The three-day delivery acceptance window starts after activation. |
| T-16 | Existing checked issuer capitalisation/share-class grouping and dividend snapshot used. Newer stored quotes take precedence. Real production fixtures cover UZAS, OCBK, ORFI, UTGA and UVGT: verified quote shares are used, inactive preferred classes are excluded, and stale prices cannot produce dividend yields. |
| T-17 | D/E withheld for financial organisations; bank NIM/cost-of-risk use the shared calculation engine. RAT renders validated sector ratios; EQS/RV retain explicit missing values when inputs are absent. |
| T-18 | Exact 3/5-year CAGR endpoints, nominal/inflation-adjusted/USD calculations. Only complete stored inflation paths and period-end FX permit adjusted results. Historical CPI pagination now retrieves 2020+. The 2022 portal discrepancy is reconciled against the CBU Q4 monetary report (12.3%, PDF p.15), preserving both source values. |
| T-19 | Discrete quarters, same-quarter YoY, contiguous four-quarter LTM, seasonality and heatmap; cumulative IFRS series are explicitly not treated as standalone quarters. |
| T-20 | Admin-only peer bands, bank justified P/B and Gordon scenarios, applicability checks, dated assumptions and governed parameter drafts. Ten-issuer calculation validation passed; FV retains its human-admin access gate. Initial assumptions are labelled as the dated TZ reference, not live estimates. |
| T-21–22 | Official monthly NPL, bank main indicators/market shares, loan/deposit structure; all 17 September NPL examples verified. Source dates remain distinct from filing dates. Sector capital/liquidity/profitability spreadsheet adapters added. Historical 2020 templates and blank cells for new banks are supported. EQS/RV show four market shares and household/corporate loans/deposits with individual observation dates. Production now contains 556 monthly datasets from January 2020 through September 2026 plus rates, FSI and CPI histories; 11 monthly source/attachment gaps remain explicit. Two historical tables were recovered from their official HTML pages. |
| T-23–24 | Rates SDMX and CBU historical FX archive; USD conversion at each statement-end date. DVD/EQS compare dated deposit rates with E/P and recent dividend decisions. Dividend yield is explicitly the latest positive decision within 366 days, not an invented sum of overlapping payouts. |
| T-25 | Rates SDMX, strict FSI SDMX validation, sector spreadsheet fallback and industry lending collector. The official SDMX catalogue now supplies the current FSI URL (`FSD_Uzbekistan_STA_IMF.xml`); guessed stale URLs were removed. A daily scheduled refresh checks current and previous months for late publications. |
| T-26 | Assignment reasons, formula catalogue/version and existing governed enterprise and financial-sector formula/template workflow exposed in ADM. FV parameters use the same draft/test/review/activation flow. Financial formula drafts accept only known source fields and retain denominator, annualisation, IFRS 17 and gross-up guards. |
| T-27 | NSBU insurer ratios verified against all five supplied H1 2026 examples. Nonpositive/missing denominators stay unavailable; NSBU formulas are not applied to IFRS 17. |
| T-28 | Existing balance mapping retained; retention/cession jumps and annual-close versus quarter-opening reserve/balance discrepancies checked and journaled. The six-issuer audit confirms KFSK assets; UZAS refreshed all 43 periods without errors; its 2025 closing correction entries were rechecked against the annual and next-quarter opening columns. The late-filed 2025Q3 workbook is accepted using its explicit quarter and matching publication date, with conflicting-quarter/year guards retained. Short-term investments c460 are mapped. ALSM has a genuine quarterly source-assets discrepancy, so zero reserve/balance-warning acceptance remains open. |

### Operational handoff

The API release includes the implementation above and its regression fixtures.
Production activation and data acceptance are recorded separately in
[release-2026-10-23.md](release-2026-10-23.md). Deploy to the existing VPS,
never Railway. Existing user/account/comparison changes remain preserved.

```sh
# Daily refresh catches late publication of the previous month.
.venv/bin/python -m scripts.terminal_cbu_sync --refresh
# Historical collection preserves the last good data on parse errors.
.venv/bin/python -m scripts.terminal_cbu_sync --from-month 2020-01 --through-month 2026-10
# Explicit publication checks PDF hashes and backs up the financial database.
.venv/bin/python -m scripts.publish_reviewed_bank_ifrs --apply --ticker UZMT
# Host minute timer executes this inside the web container.
.venv/bin/python -m server.terminal.alerts
```

Set `TERMINAL_ALERT_CHANNEL=telegram` in the private production environment.
It uses `TELEGRAM_TOKEN` and `ADMIN_TELEGRAM_ID`, falling back to the first
`ADMIN_EMAILS` address through the configured SMTP delivery. Optional explicit
recipient overrides and webhook compatibility are documented in `.env.example`.
No recipient addresses or credentials belong in tracked files.

First-load latency, ten-issuer model checks, source coverage and the actual
three-day / seven-day observation windows are acceptance evidence, not inferred
from unit tests. Unpublished or unusable official reports remain visible gaps.

## How to read this

The ТЗ states **intent**, not an implementation spec. Its author did not know
what the server already does, so where it says "create an API", "load X" or
"add a check", the capability often exists already under another name, in
another module, or as a partial version. Every requirement here is therefore
written as:

- **Intent** — what the customer wants to be true, in one or two lines.
- **Already there** — what the codebase does today, with `file:line`.
- **Gap** — what is actually missing.
- **Approach** — how to close the gap by extending what exists, not by
  building a parallel copy.

Status per requirement: **EXISTS** (only wiring/UI left), **PARTIAL**
(logic exists, needs extending or moving), **MISSING** (new work).

The codebase survey behind these files was done 2026-10-17 on commit
`68eafe6`. Re-check the `file:line` references before relying on them.

## Files

| File | Covers ТЗ tasks |
|---|---|
| [01-terminal-ui.md](01-terminal-ui.md) | Command line, navigation, screens, export, panels, сум/$ — T-09…T-12, T-19, T-24 |
| [02-data.md](02-data.md) | Empty files, duplicates, quarantine, backfill, quarters, IFRS, caps/dividends, insurers — T-01…T-06, T-16, T-28 |
| [03-analysis.md](03-analysis.md) | Verdict, annualising, ratio names, bank/company/fund/insurer sets, CAGR, templates, FV — T-07, T-08, T-17, T-18, T-20, T-26, T-27 |
| [04-logging-admin.md](04-logging-admin.md) | Event journal, admin «Терминал», alerts — T-13…T-15 |
| [05-cbu-data.md](05-cbu-data.md) | CBU bank tables, rates, FX archive, SDMX — T-21…T-23, T-25 |

## What the customer wants (short)

1. `/catalog` becomes a Bloomberg-style terminal: type `TICKER FUNC` and press
   Enter (`SQBN FA` opens the bank's financials within 2 s; `SQBN DQ` shows
   the problems in its data). This is fundamental analysis only, with no
   quotes or price charts.
2. Every user action and every data error goes into one journal, which the
   PM reads in the admin panel without developers.
3. The work is accepted when every task is «Принято» against its acceptance
   column, and the terminal logs no «Критично» error for 7 days on the live
   site.

## Order

The ТЗ orders the stages as data → analysis → terminal → control. We change
one thing: the **journal (T-13) goes first**. Every later task emits
events into it (load_empty, value_quarantine, cmd_run…), and building it
last would mean coming back to wire every task again.

1. Journal skeleton + `emit_event()` (04).
2. Data fixes at load time (02).
3. Terminal shell on the existing endpoints (01). This alone makes
   `SQBN FA` / `SQBN DQ` work end to end.
4. Analysis gaps (03) and CBU data (05).
5. Admin «Терминал» screens and alerts (04).

## Decided (2026-10-17)

- **D1:** follow the ТЗ. P/E above 100 prints «>100», and P/E is hidden at
  zero or negative profit. This replaces the «н/зн» practice of 2026-08-12
  for P/E.
- **D2:** the terminal shows 2020+ by default, with an option to extend the
  history back to 2015. The stored data is unchanged.
- **D4:** measure the quarantine rules over the stored history first, review
  what they would hide, and only then switch them on.

## Open decisions (need the customer)

| # | ТЗ says | What we have / why it matters |
|---|---|---|
| D1 | P/E > 100 prints «>100» (data rule 11) | Since 2026-08-12 the customer-approved practice is «н/зн» for out-of-range multiples, with the value in a tooltip; the range today is `pe_range [0.1, 300]` (`config/thresholds.json:43`). Pick one rule for the whole site. |
| D2 | History starts at 2020 annual / 2022 quarterly | We hold filings back to 2015. Proposal: the terminal *defaults* to 2020+ and the data stays. |
| D3 | Missing year → take the next report's «прошлый год» column (rule 3) | The NSBU **bank** form prints no comparative column, so this rule cannot fill bank years. It works for non-banks only. |
| D4 | Quarantine: profit/equity > 1.5× assets or a 20× jump (rule 5) | Must not hide extremes that are faithful to the filing (UZIR, GRBK multiples). The thresholds must be measured on real data before switching on (see 02, R-D3). |
| D5 | Verdict: risk **high** → «Требует внимания» (rule 8) | `financial_analysis/sector_verdict.py` sends only a high *red flag* there; a high *risk* signal caps at «Смешанно». Confirm which "high" is meant. |
| D6 | UZINP as «6th insurer» (T-28) | UZINP is a **preferred** share class. The insurer is its issuer, which is not a separate company. |
| D7 | Fund P/NAV for UZNF | Blocked today until the share basis is reconciled (`SHARE_BASIS_NOT_RECONCILED`). Confirm which share count is authoritative. |
| D8 | HDS (owners ≥5%, board) | Deferred in the ТЗ itself; out of scope. |
