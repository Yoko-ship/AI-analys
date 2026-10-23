# Catalog terminal — requirements

Source: «ТЗ: терминал каталога UZStock с логированием» (14.10.2026, amended
15.10.2026, 21 pages). Visual reference: `UZStock_terminal_TZ_maket.html`
(15.10), sent with the ТЗ.

## Implementation review — 2026-10-23

Compared the supplied `ТЗ_терминал_каталога_UZStock_с_логированием_1.pdf`
and `UZStock_terminal_TZ_maket (3).html` against the application. The PDF
sets requirements; the HTML supplies layout and dated example values. Its
embedded issuer/CBU data are **test evidence**, not a production data source.
The detailed fundamental-only scope takes precedence over the introductory
mentions of quotes: the catalogue price chart was removed. HDS remains
deferred; FV stays behind the human-admin API gate.

The following status describes local implementation, **not production acceptance**.
Existing comparison/account changes in the working tree were preserved.

| TZ tasks | Implementation and remaining acceptance |
|---|---|
| T-01–02 | Existing empty-file rejection and duplicate selection retained. Some named annual filings are empty or mislabelled upstream; do not manufacture replacements. See the measured Stage C results in `02-data.md`. |
| T-03 | **Still open:** the earlier D4 decision requires review before automatic value quarantine. The measured false positives and proposed source-arithmetic checks are in `quarantine-review-2026-10-17.md`. This change does not silently enable those thresholds. |
| T-04–05 | Existing comparative backfill and discrete-quarter derivation retained; coverage now distinguishes loaded, comparative, missing, unregistered and unavailable periods. Production history must be refreshed and checked. |
| T-06 | Existing IFRS ingestion retained. UZMT's complete 2020–2025 publication coverage was not established in this local workspace. |
| T-07 | High risk now requires attention, including without a comparable period. Medium risk and profit-direction constraints remain. Shared annualised NIM/cost-of-risk and P1–P8 names added; report calculation version is `nsbu-core-2.5`. |
| T-08 | Existing fund routing/share-reconciliation guard retained. Terminal summary treats equity as NAV and suppresses corporate revenue for funds. A missing verified share basis still prevents NAV/share. |
| T-09 | Existing keyboard/command parser extended to working market screens and complete URL context. LAST/HELP retained. |
| T-10 | EQS, MON, SUM, RAT, RV and REC wired to real APIs; shared PL, BS, DVD, CF, CN and DQ reused. Peer selection matches type, standard, scope and year. DQ fails visibly if either financial-history request fails. |
| T-11 | Terminal tables export BOM-prefixed, formula-safe Cyrillic CSV. Exports preserve reporting context, currency and historical FX dates. CF/CN remain connected to existing sources. |
| T-12 | Four independent panels; guest persistence in the browser and authenticated save/load through validated profile preferences. Direct PNL links wait for issuer data. |
| T-13 | Existing journal extended with exact standard/period filters and durable deduplication. Publication, high P/B, insurer checks and governed rule activation now emit events. Not every catalogue event has been reproduced on production. |
| T-14 | Admin terminal summary, coverage, error filters/full CSV, usage 7/30 days, templates and private FV views. Staff commands excluded from usage. Coverage excludes periods absent from the source registry and does not call a failed source clean. |
| T-15 | Persistent critical-alert cooldown/retry and 09:00 Tashkent digest runner implemented and tested with an injected sender. **Needs a configured destination and host schedule; no external messages sent in this work.** |
| T-16 | Existing checked issuer capitalisation/share-class grouping and dividend snapshot used. Newer stored quotes take precedence. Production reconciliation of the named issuers remains an acceptance task. |
| T-17 | D/E withheld for financial organisations; bank NIM/cost-of-risk use the shared calculation engine. RAT renders validated sector ratios; EQS/RV retain explicit missing values when inputs are absent. |
| T-18 | Exact 3/5-year CAGR endpoints, nominal/inflation-adjusted/USD calculations. Only complete stored inflation paths and period-end FX permit adjusted results. Current CBU inflation pages alone do not supply every historical year. |
| T-19 | Discrete quarters, same-quarter YoY, contiguous four-quarter LTM, seasonality and heatmap; cumulative IFRS series are explicitly not treated as standalone quarters. |
| T-20 | Admin-only peer bands, bank justified P/B and Gordon scenarios, applicability checks, dated assumptions and governed parameter drafts. **Public release still requires ten-issuer validation.** Initial assumptions are labelled as the dated TZ reference, not live estimates. |
| T-21–22 | Official monthly NPL, bank main indicators/market shares, loan/deposit structure; all 17 September NPL examples verified. Source dates remain distinct from filing dates. Sector capital/liquidity/profitability spreadsheet adapters added. Full 2020+ production backfill is pending. |
| T-23–24 | Rates SDMX and CBU historical FX archive; USD conversion at each statement-end date. DVD/EQS compare dated deposit rates with E/P and recent dividend decisions. Dividend yield is explicitly the latest positive decision within 366 days, not an invented sum of overlapping payouts. |
| T-25 | Rates SDMX, strict FSI SDMX validation, sector spreadsheet fallback and industry lending collector. The official FSI URL returned HTTP 404 during validation; this is retained as an error, not counted as a successful load. |
| T-26 | Assignment reasons, formula catalogue/version and existing governed enterprise and financial-sector formula/template workflow exposed in ADM. FV parameters use the same draft/test/review/activation flow. Financial formula drafts accept only known source fields and retain denominator, annualisation, IFRS 17 and gross-up guards. |
| T-27 | NSBU insurer ratios verified against all five supplied H1 2026 examples. Nonpositive/missing denominators stay unavailable; NSBU formulas are not applied to IFRS 17. |
| T-28 | Existing balance mapping retained; retention/cession jumps and annual-close versus quarter-opening reserve/balance discrepancies checked and journaled. Full production reparse and six-issuer source audit still require acceptance. |

### Operational handoff

New modules live under `server/terminal/`; historic FX is in
`server/currency/history.py`. New source fixtures and regression tests use the
actual supplied insurer cases and official CBU spreadsheets. No production
service, database, scheduler or deployment was changed.

Run from the **active application directory** with its normal environment:

```sh
# Monthly observation collection (repeat safely; failed parses do not replace data)
.venv/bin/python -m scripts.terminal_cbu_sync
# Explicit historical run; inspect errors because older source layouts can differ
.venv/bin/python -m scripts.terminal_cbu_sync --from-month 2020-01 --through-month 2026-10
# Run once a minute only after the operator configures the alert destination
.venv/bin/python -m server.terminal.alerts
```

The collector returns nonzero if any requested source fails, including FSI
SDMX, even when the other tables succeed. Historical year-end USD rates are
cached separately. Source pages/attachments and dated observations are stored
with the data. The current verified inflation scrape contains 2023–2025
December observations; earlier missing years are not filled from the mockup.

`TERMINAL_ALERT_WEBHOOK` (HTTPS) and optional `TERMINAL_ALERT_TOKEN` are private
runtime settings documented without values in `.env.example`. The alert runner
posts a JSON object with `kind=critical` or `kind=daily_digest` to that configured
receiver. It has no implicit recipient. Set the monthly collector and minute
alert schedule using the host's existing service manager **after inspecting the
active directory and services**; do not use Railway. The three 09:00 deliveries,
seven critical-free production days, historical completeness, first-load
latency, ten FV issuers, and D4 quarantine review remain explicit acceptance
gates. No task is marked “Принято” solely because unit tests pass.

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
