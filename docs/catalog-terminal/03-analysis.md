# 03 — Analysis and ratios

ТЗ tasks: T-07, T-08, T-17, T-18, T-20, T-26, T-27, plus data rules 6, 8, 9
and 11. Excluded by the ТЗ: EPS, EV, EV/EBITDA, DCF, price forecasts.

**The common gap:** the same ratio is computed in several places
(`fundamentals.py`, `catalogue/ratios.py`, `server/catalog/analysis.py`,
`financial_analysis/sector_calculations.py`, legacy `reporting/`), and they
already disagree (see R-A2, R-A9). The terminal must read **one**
definition per ratio. New ratios go into that one place, not into a fifth.

## R-A1 Verdict rules (T-07, rule 8) — EXISTS

- **Intent:** risk high → «Требует внимания»; medium risk or falling profit
  → not above «Смешанно»; rising profit forbids «Ухудшение». Acceptance:
  zero `verdict_conflict` events.
- **Already there:** `financial_analysis/sector_verdict.py:207-287`.
- **Gap:** only a high *red flag* leads to «Требует внимания»; a high *risk*
  signal caps at «Смешанно» (README D5). There is no post-hoc validator.
- **Approach:** a validator that checks the published verdict against the
  rules and emits `verdict_conflict` (Критично).

## R-A2 Annualising (rule 6) — PARTIAL

- **Intent:** ROE/ROA for an incomplete period × 12 / months; margins are
  not rescaled.
- **Already there:** TTM with a ×12/months fallback in `fundamentals.py:139-160`,
  `catalogue/ratios.py:543-603` and `server/catalog/analysis.py:197,228`.
- **Gap:** the sector AI report (`sector_calculations.py:62-63`) does not
  annualise, so the same issuer shows two different ROEs.
- **Approach:** make the sector report call the shared annualiser.

## R-A3 Ratio names (rule 9) — PARTIAL

- **Intent:** the API returns a Russian name for each ratio (today P1–P8
  come without names).
- **Already there:** names exist only in the frontend
  (`frontend/src/analysis/VerifiedReport.jsx:9-16`).
- **Approach:** move the names into the API payload (`name_ru`, `name_uz`,
  `name_en`) next to `metric_code`. The frontend then reads them from there.

## R-A4 Bank set (T-17) — PARTIAL

- **Intent:** P/B, P/E, ROE, ROA, NIM, cost of risk, reserves/loans,
  reserves/NII, cost/income, loans/deposits, liquid/deposits,
  capital/assets, FX and fee income share. No D/E for banks.
- **Already there:** `sector_calculations.py:61-75` (most of the set);
  cost of risk in `server/catalog/analysis.py:176,207`. D/E is already
  hidden for banks.
- **Gap:** no NIM in the verified report (the legacy NIM uses
  gross_profit/assets as a proxy, which is wrong); FX and fee income share
  are missing.
- **Approach:** NIM = net interest income / average interest-earning assets
  (or average assets, stated). Verify 5 banks by hand (T-17 acceptance).

## R-A5 Company set — PARTIAL

- **Intent:** P/E, P/B, P/S, ROE, ROA, margins, D/E (≤1 low, >2 flag),
  liquidity, interest coverage, dividend yield, payout.
- **Already there:** `/api/market/multiples` → `fundamentals.issuer_multiples`
  (`fundamentals.py:814-1046`); liquidity in `sector_calculations.py`.
- **Gap:** payout is missing; dividend yield is computed only client-side
  (`features/company/keyStats.jsx:378`); interest coverage exists only in
  legacy `reporting/`; D/E does not appear on the public endpoints.
- **Approach:** server-side dividend yield and payout next to the
  multiples, and D/E (liabilities / equity) for non-banks, so the screener
  (EQS) can filter on them. The P/E display rule depends on README D1.

## R-A6 CAGR (T-18) — MISSING

- **Intent:** 3- and 5-year CAGR, nominal, real (after inflation) and in $;
  a loss at either end shows a label instead of a number. Acceptance: SQBN
  equity +12.1% nominal, ≈ +2% real.
- **Already there:** only an internal revenue CAGR in the legacy DCF.
- **Approach:** a pure function over the annual series. Inflation by year
  comes from CBU data (05). The $ version needs the FX history (05 R-C3).

## R-A7 Fund template (T-08) — PARTIAL

- **Intent:** UZNF shows NAV, NAV per share and the price premium/discount,
  and never «выручка».
- **Already there:** `fund_analysis.py:26-97` (UZNF, from the audited IFRS
  report); `server/catalog/analysis.py:178,702-727` (ODMP: NAV/share =
  equity × 1000 / listing shares). Commit `68eafe6` leads fund dynamics with
  income.
- **Gap:** two separate implementations with different share bases;
  UZNF P/NAV is blocked (`SHARE_BASIS_NOT_RECONCILED`; README D7).
- **Approach:** a single fund path; the share basis decided once.

## R-A8 Insurer template (T-27) — PARTIAL

- **Intent:** 10 ratios (premium growth, retention, loss ratio, expense
  ratio, combined ratio, investment income/premiums, net reserves/equity,
  reinsurer share, ROE, P/B), annual and quarterly. Acceptance: TMYS, KFSK,
  KASU, UZAS and ALSM for 1H2026 equal the ТЗ table. Self-checks:
  `ins_retention_jump`, `ins_reserves_missing`, `pb_high`.
- **Already there:** lines are read (`sector_report_service.py:792-836`);
  ratios today: ROA, ROE, equity/assets, reinsurer share, reserves/
  liabilities (`sector_calculations.py:70-71,88`). A code comment there says
  the form does not separate claims from premiums. The ТЗ shows it does:
  c070 (claims expense) over c060 (net earned premiums).
- **Approach:** add the remaining ratios exactly per the ТЗ formulas, with
  the ТЗ table as a test fixture.

## R-A9 Templates and auto-assignment (T-26) — PARTIAL

- **Intent:** base set + organisation-type template + OKED add-on, assigned
  from data; a ratio shows only if all its lines exist (otherwise the DQ
  entry «нет строки …»); formulas and templates live in ADM with
  versions; an admin can override the template with a reason.
- **Already there:** `financial_analysis/sector_templates.py:17-35` (types
  and an OKED → profile map); `issuer_financials.py:46-72,142-144`
  (bank/insurance/non_financial only; UZNF and URTS hard-coded at :35-38);
  admin-editable typed rules with test cases (`admin_control/rules.py:11-96`);
  formula versions DRAFT→ACTIVE→ARCHIVED
  (`v3_financial_pipeline.py:152-213`).
- **Gap:** `extractive` and `investment_fund` have no template; there is no
  create/activate endpoint for formula versions; the template is not shown
  on the dashboard.
- **Approach:** extend `sector_templates` (replacing the hard-coded tickers
  with data rules) and expose the existing versioning. Every formula edit
  emits a journal event.

## R-A10 Peers (RV) — EXISTS

- `server/catalog/service.py:225-238,441-450`: same org kind, same form,
  same period, assets within 100×. Fine as it is; an OKED filter is
  optional.

## R-A11 Fair value (T-20) — PARTIAL

- **Intent:** a valuation range labelled «расчёт по модели, не
  рекомендация»; methods: peer multiples, justified P/B for banks, Gordon
  for dividend payers; r = CBU rate − default spread + equity risk premium
  (≈ 19.8%), g = median inflation since 2020 (9.8%); ROE < g → «модель не
  применима»; parameters editable in ADM; admin-only until checked on 10
  issuers.
- **Already there:** peer P/E fair value (`forecast_engine.py:56-65`); a
  legacy DCF with a hard-coded WACC (excluded by the ТЗ).
- **Gap:** no Gordon model or justified P/B; r and g are hard-coded.
- **Approach:** store the parameters in the existing admin-control rules
  store (versioned, audited) instead of a new settings table. Keep the
  screen admin-only behind the existing admin auth.

## R-A12 Dividend yield vs deposit (T-24) — MISSING

- **Intent:** in DVD and EQS, dividend yield and E/P against the deposit
  rate; the screener filter «дивиденд выше депозита».
- **Depends on:** R-A5 (server-side yield) and 05 R-C2 (deposit rates).
