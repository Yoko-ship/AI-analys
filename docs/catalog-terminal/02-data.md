# 02 — Data correctness

ТЗ tasks: T-01…T-06, T-16, T-28 and data rules 1–7, 12.

**The common gap:** most of these checks already exist, but they run when a
page is **read**, not when a filing is **loaded**. So nothing is recorded,
the PM cannot see them, and the same problem is rediscovered on every
request. The general fix: move each check into the load path, record its
outcome as a journal event (04), and let the read path use the stored
outcome.

## R-D1 Empty source files (T-01) — PARTIAL

- **Intent:** an empty downloaded file is detected at load and re-fetched;
  SQBN 2024, UZNGP 2021–2025 and KSCM 2021 must stop showing
  `EMPTY_SOURCE_FILING`.
- **Already there:** at read time, `server/company/financials.py:409-420,454`
  purges all-zero years and emits `EMPTY_SOURCE_FILING`;
  `catalogue/ratios.py:455-477` returns `empty_filing`.
- **Gap:** `collectors/openinfo/spreadsheets.py:41-53` checks only a maximum
  size, never emptiness. Its cache is keyed on the parser version
  (`:37-39`), so an empty file is never re-downloaded.
- **Approach:** an emptiness check in the spreadsheet loader → `load_empty`
  (Критично) plus evicting that cache entry, so the next run fetches the file
  again. Then re-run the three named cases. Do not hardcode them; they are
  the acceptance check.

## R-D2 Duplicate filings (T-02) — PARTIAL

- **Intent:** two filings for one period → the latest published wins (today
  UTYK 2023 and MXUS 2025 are missing from the history), and the choice is
  logged.
- **Already there:** `catalog_reports` is unique on
  `(ticker, report_form, period_type, year, quarter)`
  (`catalogue/schema.py:158`); the later `published_at` wins in
  `financial_ingestion/period_repair.py:105,129-137`;
  `server/company/financials.py:35-69` drops a *copied* year
  (`UNSUPPORTED_DUPLICATE_PERIOD`). FIN-14 is at `audit/checks.py:284`.
- **Gap:** find why UTYK 2023 / MXUS 2025 are dropped. The likely cause is
  the copied-year rule firing on a genuine refile. No event records which
  version lost.
- **Approach:** first reproduce on those two cases, then fix the rule. Log
  `load_duplicate` (Внимание) with both filing ids.

## R-D3 Units and quarantine (T-03) — PARTIAL

- **Intent:** a value that fails a unit check or a jump check is not shown
  and goes to the journal. KVTS 2020 and ODMP 2020–21 must end up within
  their assets.
- **Already there:** `fundamentals.py:456-458` blocks net income > 100×
  assets; `fundamentals.py:431` checks net income > 1.5× revenue; FIN-06
  (`audit/checks.py:172-199`) flags revenue 1000× off the sector median;
  `data_quality.py:997` auto-fixes ×1000 issues; publication holds are at
  `data_quality.py:178,406`.
- **Gap:** no "profit or equity > 1.5× assets" rule and no year-on-year
  > 20× jump rule; nothing is quarantined per value.
- **Approach:** add both rules to the existing `data_quality` hold mechanism,
  not as a new store. **Measure first** (CLAUDE.md): run them over the whole
  stored history, then list what fires and what must not fire (faithful
  extremes such as UZIR and GRBK, and negative-equity issuers), and cover
  both sides with tests. Log `value_quarantine` (Критично). See README D4.

## R-D4 Fill a missing year from «прошлый год» (T-04) — PARTIAL

- **Intent:** if an annual report is missing or empty, take the figures from
  the next report's prior-year column, marked with their source; otherwise
  leave a gap and draw nothing. Named: UTGA, KSCM, AGMKP, BECM, BNGP, ALSM,
  TMYS, UZGFP, UZML.
- **Already there:** NSBU keeps the prior-year column as `prior`
  (`catalogue/snapshots.py:341-349`), used for YoY and TTM only; IFRS
  columns are tagged PRIMARY/COMPARATIVE/RESTATEMENT
  (`financial_ingestion/statements.py:423-429`).
- **Gap:** `prior` never fills a missing annual; there is no source mark.
- **Approach:** a backfill step writes the year with `source =
  comparative_of:<filing>` and logs `year_backfill` (Инфо). The coverage
  matrix shows it yellow. A real filing always overrides a backfilled one.
  **Not possible for banks** (no comparative column; README D3).

## R-D5 Quarterly reports since 2022 (T-05) — EXISTS

- **Intent:** quarterly history from 2022, Q4 = year − 9M; for 5 random
  issuers the figures match openinfo.
- **Already there:** `server/company/financials.py:90-227`, including the
  `INCONSISTENT_CUMULATIVE_INCOME` guard.
- **Gap:** the backfill defaults to 2023 (`collectors/financials/backfill.py:166`).
- **Approach:** set the floor to 2022 and run the backfill. Verify 5 issuers
  against openinfo, as the acceptance column says.

## R-D6 UZMT IFRS from PDF (T-06) — PARTIAL

- **Intent:** UZMT has an annual IFRS history for 2020–2025.
- **Already there:** a full PDF/OCR ingestion pipeline with review and
  publication (`financial_ingestion/`, `docs/dynamic-ifrs-ingestion.md`).
- **Gap:** UZMT has never been run through it; publication needs a manual
  review.
- **Approach:** run discovery + ingestion for UZMT, then review. No new code
  is expected unless its layout breaks the parser. Until then UZMT uses the
  quarterly NSBU dashboard (data rule 12).

## R-D7 Restatements — PARTIAL

- **Intent:** log `restatement` when a company changes last year's figure by
  more than 1%.
- **Already there:** `reports_watch.py:54-56,219-228` republishes when the
  same period comes back more than 0.5% different.
- **Gap:** nothing compares the comparative column of a new filing with the
  stored prior year.
- **Approach:** on load, compare `prior` against the stored year and emit
  `restatement` (Внимание). Do not overwrite the stored year silently.

## R-D8 One standard, one perimeter (rules 1, 10) — EXISTS

- **Already there:** `form=NSBU|MSFO` and `scope=separate|consolidated`
  (`server/company/financial_routes.py:19,29`); storage key
  `(ticker, form, year, quarter)`.
- **Note:** the ТЗ says the AI analysis takes `standard=ifrs` while the
  financials take `form=MSFO`. Do not add a second name. The terminal parser
  maps `MSFO`/`IFRS` onto `form=MSFO`.

## R-D9 Market cap and dividends (T-16) — PARTIAL

- **Intent:** fix the market cap and dividends of UTGA, OCBK, UZAS and UVGT,
  and ORFI's doubled dividends, so that P/B and dividend yield are sane and
  match openinfo.
- **Already there:** `share_count_consistency` (`fundamentals.py:695-720`);
  uzse share counts (`listings_collector.py:205,331`); dividends keyed
  `(ticker, filing_id)` (`catalogue/schema.py:598`).
- **Gap:** the same dividend filed under two filing ids is not collapsed.
  That is the general cause behind ORFI.
- **Approach:** de-duplicate on (ticker, record date, amount per share), not
  on filing id. Investigate the four caps individually against uzse and
  openinfo, then fix the rule that let each through.

## R-D10 Insurers (T-28) — PARTIAL

- **Intent:** liabilities = net reserves + other; KFSK 2025 assets = 642 bn
  (today 383); no `ins_reserves_missing` events; parse the short-term
  investment line; check line 012; add UZINP.
- **Already there:** insurer lines c011…c320 and c570…c720 are read in
  `sector_report_service.py:792-836`; reserves 580−670 in
  `catalogue/parsing.py:394-517`.
- **Gap:** the **annual** history store carries only revenue, net income and
  reserves, so total assets are understated.
- **Approach:** fix the annual parser to include reserves in liabilities and
  assets, and verify against the quarterly «на начало года» column (the
  ТЗ's own check; > 5% off → `ins_reserves_missing`, Критично). UZINP: see
  README D6.
