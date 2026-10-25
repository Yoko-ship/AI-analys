# IFRS investor interface

Implementation contract: `UZStock_IFRS_Investor_UI_Final.html`, provided on
2026-10-25. The user selected both the public Company → Finance → IFRS screen
and the catalog terminal, including its panels. This supersedes the previous
IFRS presentation, while NSBU and catalog access permissions remain intact.

The supplied file explicitly uses synthetic numbers. Adopt its layout and
sector-specific field lists, not its simulated values, artificial ratios,
assumed share count, funding proportions, or invented segment disclosures.

Acceptance criteria:

- Shared investor UI at both entry points, issuer/scope context, annual,
  interim/TTM and quarterly controls, light/dark and mobile layouts.
- Six sector-aware KPI cards, real period/date captions and comparable growth.
- Nine working sections: overview, PL, BS, CF, equity, ratios, dashboards,
  notes and quality. Source fields, subtotals and detail rows follow the sample.
- Amounts in billion UZS, preserving source currency/scale and original values
  in the passport. Missing/blocked values never become zero.
- Annual history retains the user's latest two years plus current-period rule.
  Interim flows can include separately labelled TTM, calculated from actual
  compatible periods. BS always uses reporting dates, never TTM sums.
- Overview revenue/profit chart, finance composition, evidence-based summary,
  disclosed segments, and educational cards. Dashboards add signed CF bars,
  ratio summaries and debt/liquidity context.
- Applicable ratios with formulas, inputs and source links. Average denominators
  must match the numerator's period and ownership basis. No demo shortcuts.
- Notes expose actual source text/tables and PDF pages; missing disclosures are
  explicit. Quality uses actual arithmetic/coverage/audit evidence.
- Clickable number passports; keyboard/touch dismissal and focus handling;
  source links, row detail toggle, CSV of displayed rows, PDF/print styling.
- Scope/issuer/mode transitions clear stale data, errors offer retry, and
  existing NSBU behavior remains covered.
- Tests must fail before implementation; full Python suite, frontend checks,
  browser interactions and visual inspection precede release to uzstock.uz.

Verification evidence (2026-10-25):

- Shared React screen exercised through public finance, catalog BS and saved
  workspace panels. All nine sections, six KPIs, scope switches, annual/interim
  labels, source dialog, CSV content, retry, deep links, notes/PDF and print
  controls have browser coverage. NSBU remains covered by existing regressions.
- Approved HMKB 2024/2025 source fixtures verify billions conversion and exact
  provenance. Audited UZNF registry records remain available with their actual
  first reporting period, 24.12.2024–31.12.2025. No company-specific UI branch.
- Backend regressions observed failing before implementation: projection,
  missing/conflicting values, scope separation, flow-only TTM, signed-expense
  arithmetic, reference aliases, and opening balances. Combined fields cannot
  consume narrower source subtotals. Incomplete inputs stay unavailable.
- Light/dark desktop and 390px mobile screenshots inspected. Fixed an issuer
  select overflowing its container; the browser test reproduces and guards it.
- Full JavaScript suite: 284 passed. Build passed; lint has no errors (one
  existing AdvancedChart rounding warning). Full Python suite before the final
  alias/opening additions: 3,724 passed, 85 skipped; final CI runs the complete
  suite again. Full browser regression result is recorded in the CI run.
- A pre-existing mobile sorting test tapped the definition marker at the center
  of a header. It now taps the header corner, like the adjacent touch test;
  the original failure and the corrected interaction were both reproduced.

Source limitations are visible in the product: many issuers have no approved
IFRS imports, while legacy HMKB imports cover only selected statement totals.
Missing CF, equity movements, segment disclosures and notes remain explicit.
The sample's synthetic figures, inferred shares, invented earning assets and
segment proportions are never used. PDF export invokes the browser print
workflow for the current screen. Full financial source approval/import is a
separate data operation; this UI does not automatically approve new filings.
