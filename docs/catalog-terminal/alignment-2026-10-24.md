# Catalog mockup alignment — 24 October 2026

Authority: the user's `ТЗ_терминал_каталога_UZStock_с_логированием_1.pdf`
(21 pages), `UZStock_terminal_TZ_maket (3).html`, and the screenshot of the
incorrect HMKB FV screen. Embedded mockup figures are dated regression inputs,
never a substitute for the financial publication APIs.

The user's later overrides remain in force: no market section in Compare,
no four sector CBU accordions in RAT, and quarterly profit/LTM displayed in
billions of UZS. Percentage columns remain unscaled. The user explicitly
confirmed that financial reports remain public, as in the newest version; FV
and administrative operations retain their separate access controls.

## Verified gaps and repairs in this working tree

- FV previously showed an empty manual admin form and mixed issuer totals,
  P/B multiples and per-share prices. The catalog now automatically reads
  configured assumptions, displays six summary cards, method ranges and
  formulas, and explains unavailable methods. Raw model outputs remain for
  versioned admin rules; an explicit UZS/share projection alone feeds the
  chart, median and price-to-value comparison. Manual scenarios remain in ADM.
- Peer selection retains type, standard, scope and year. Quarantined sources
  cannot participate through cached ratios. The mockup's low-ROE P/B guard
  is checked against its AGBA and HMKB examples. No arbitrary P/B or P/E
  caps were introduced: the prior source-quality policy retains verified
  high multiples and flags them instead of silently deleting evidence.
- The catalog uses the supplied compact dark terminal palette, sidebar
  filters, compact issuer context and wrapping function tabs. Light mode
  remains supported. FV is still restricted to administrators.
- SUM now uses six period-consistent KPI cards, separate conclusion/risk
  cards, annual income/profit and balance charts, explicit missing years,
  a history table/CSV and dated year-end USD conversion. Latest-report
  figures are converted from their declared units; a statutory P2 ratio is
  never relabelled as ROE. The old analysis form and report table belong to CF.
- PL adds the published-line profit bridge, explicitly marked reconciliation
  residuals and annual margins. BS adds asset composition and appropriate
  stability ratios. Both expose the latest report's current/prior facts with
  their comparison basis and declared units. Financial-company views do not
  inherit corporate D/E; RAT labels annual ratios separately from interim
  sector metrics. Missing calendar years or observations break financial
  history lines instead of implying an uninterrupted trend.
- Standard and scope controls sit above the function tabs. Administrators can
  open FV in saved panels and filter EQS using the same protected calculation.
  Its join requires matching ticker, year, standard and scope. Historical EQS
  years disable the current valuation filter and do not retain its exclusion.
- Sector checks now use the real HMKB and UZAS filings and the audited UZNF
  2025 snapshot. Insurers show earned premiums, loss and combined ratios,
  and an insurance-specific profit bridge. Banks show an explicitly named
  profit/income ratio rather than corporate margins. The shared annual and
  quarterly history API removes corporate net-margin fields for banks,
  insurers and funds and carries sector-specific income labels.
- Fund template aliases resolve to the fund view. SUM shows NAV, NAV/share,
  price/NAV, premium/discount, profit and portfolio/assets. Per-share figures
  use the existing verified share reconciliation; quote and filing dates
  remain distinct. PL separates dividends, unrealised revaluation, expenses
  and tax; BS exposes the investment portfolio. Missing inputs remain gaps.
- Bank SUM restores monthly CBU context, source dates, asset market share,
  NPL, and rank against the complete CBU bank table, including unlisted
  banks. Monthly history lists only published observations. The September
  2026 source fixture contains 35 ranked banks; the UI does not hardcode 36.
- Follow-up inspection found genuine T-16 defects among the old failures.
  Reviewed parts of the saved dividend/listing work have been reconciled:
  repeated dividend filings collapse per issuer and share class, including
  snapshots written before the fix; pinned ISINs retain the matching card's
  share class/count; an empty bank balance no longer displaces dated indicator
  values. A new guard preserves distinct valid decisions sharing one payment
  window. Real ORFI, ORFIP, OCBK and other issuer cases plus nearby listing and
  capitalisation checks passed (150 checks). The stored-history regression was
  also run against the unfixed HEAD and failed before being accepted.
- Legacy insurer extraction now retains short-term investments from line 460
  in structured filings and the corresponding workbook row. The real TMYS H1
  2026 amount and adjacent statement parsing checks passed (76 checks). No
  revenue formula or reported balance total was changed to satisfy older tests.

## TZ completion audit

This is a local implementation audit. The 23 October release evidence remains
dated evidence; production acceptance is not inferred from mocked browser tests.
The local full-suite gate below now passes. Production acceptance remains a
separate, dated observation.

| Task | Local implementation/evidence and acceptance boundary |
|---|---|
| T-01 | Existing empty-source rejection retained; unusable source filings remain gaps. |
| T-02 | Existing filing selection and duplicate-period checks retained. |
| T-03 | Existing reviewed-value quarantine and journal retained; `test_terminal_quarantine.py`. |
| T-04 | Existing comparative-year backfill retained; `test_comparative_backfill.py`. |
| T-05 | Discrete quarters and missing-input rules retained; `test_quarterly_series.py`. |
| T-06 | Reviewed IFRS publication and scope isolation retained; `test_ifrs_financials.py`. No new source publication. |
| T-07 | Shared verdict/annualisation rules retained; `test_terminal_verdict.py` and sector contract checks. |
| T-08 | Corrected fund SUM/PL/BS mapping and verified NAV/share behavior; real UZNF fixture. |
| T-09 | Command, keyboard, URL context and issuer navigation covered by terminal command/workspace checks. |
| T-10 | Repaired mockup SUM/PL/BS/FV presentation; other existing screen routes retained. Sector applicability exercised for bank, insurer, fund and industry. |
| T-11 | Existing safe CSV, context and currency export behavior retained; catalog/browser export checks. |
| T-12 | Independent panels retained and FV added through its existing admin gate; workspace checks. |
| T-13 | Existing event journal, deduplication and quality events retained; journal/quality-event tests. |
| T-14 | Existing admin summary, coverage and usage retained; terminal dashboard tests. |
| T-15 | Existing alerts/scheduling retained; alert/schedule tests. Three actual morning deliveries are production acceptance, not verified here. |
| T-16 | Capitalisation/share-class rules retained, pinned-ISIN classification and old duplicate dividend snapshots repaired. Saved tests now exercise the current latest-ordinary-decision contract and checked market prices, rather than the removed trailing-year helper API. |
| T-17 | Sector-specific KPI applicability corrected in summaries and history. Existing canonical ratios remain the calculation source. |
| T-18 | Existing exact-period CAGR, inflation and FX calculations retained; analytics/currency-history tests. |
| T-19 | Quarterly profit/LTM display in billion UZS; percentages unchanged. Missing quarters and CSV covered. |
| T-20 | Automatic protected FV, consistent UZS/share methods, matching peers, missing-basis rules, median and ranges checked against mockup and real screener inputs. |
| T-21 | CBU source adapters retained; complete-bank asset rank and monthly SUM history added with dated source fixtures. |
| T-22 | NPL source/date isolation retained and exposed separately in bank SUM. |
| T-23 | Existing deposit-rate source and comparisons retained; terminal CBU/analytics tests. |
| T-24 | UZS/USD history conversion uses verified period-end rates; absent rates hide amounts. |
| T-25 | Existing sector CBU ingestion retained. Four catalog accordions removed as the user's explicit override. |
| T-26 | Existing versioned formula/template approval flow retained; governed-formula tests. No rule activated by this task. |
| T-27 | Insurer ratios come from canonical checked report values; UZAS combined/loss ratios and PL bridge exercised. |
| T-28 | Existing insurer balance checks retained; portfolio/asset presentation does not change source balances. Source discrepancies documented on 23 October remain open. |

The seven-day production error observation, live first-load timing and named
source-file acceptance gaps are not replaced by this local implementation audit.

## Verification

Regression tests were run before their fixes. FV backend examples include
HMKB/AGBA from the supplied mockup, missing market basis, a single dividend
method and quarantined peers. Browser tests cover automatic FV loading,
export, standard/ticker changes, error retry, access control and desktop/mobile
rendering. SUM checks use the repository's real UZMK report fixture plus
explicit annual missing-year and loss/zero cases.

PL/BS use the real UZMK, HMKB and UZAS report fixtures and the audited UZNF
snapshot. Annual chart feeds in browser tests are controlled synthetic inputs;
they are not additional historical filings. EQS and saved-panel browser
tests exercise authenticated requests, filtering and screen navigation. All
browser API responses in those regressions are mocked: they establish rendered
behavior and request contracts, not independent production source accuracy.

A separate read-only public screener snapshot on 24 October supplied 65 real
issuers to the new calculation, with 50 having at least one applicable method.
All returned per-share ranges were finite and ordered. These checks used the
TZ's dated reference assumptions, not a current macro forecast. Evidence is
in `tmp/catalog-alignment/live-valuation-check.json`.

The local workspace run before publication: **3,618 passed, 85 skipped, no failures**
(`.venv/Scripts/python.exe -X utf8 -m pytest -q`, on Windows).
`pytest.ini` declares the same `tests` directory used by CI; saved worktree and
audit copies are not additional test suites. No test is excluded within that
root. The complete result is `.git/catalog-public-final-python.log`.

The user resolved the access-policy conflict in favor of public reports.
The four statement/passport checks and analysis-route check now enforce public
access, including after sign-out; creating a saved comparison still requires
sign-in. An isolated obsolete sign-in gate made all five public-access cases
fail, demonstrating the checks detect a regression. This verification did not
change production access code.

The remaining saved tests were reconciled to the current contracts:

- Dividend checks use the live latest-decision calculation and checked prices,
  including UZAS, stale ORFI, repeated UVGT, old UTGA and invalid DORI dates.
  They no longer require the removed trailing-dividend/payout helper.
- Insurer revenue means earned premiums (010), with line 060 retained for its
  own ratios. KFSK's 2024 component/subtotal discrepancy is explicitly tested;
  the parser is not forced to invent a balancing amount.
- Historical IFRS constants cannot overwrite NSBU data without a reviewed
  publication. Missing financial fields remain marked as missing.
- The saved standalone insurance adapter is tested as an adapter; the current
  application continues to serve its canonical sector-analysis route.
- Trade pagination retains the newest version's half-second pause. Notice
  content retains the source language; no translation provider was added.
- POSIX permission tests still assert actual mode 0600 on POSIX systems and
  assert the requested creation mode on Windows, where `stat` cannot report
  POSIX permissions. No production permission code was changed.

Two actual defects surfaced during this reconciliation. The daily OpenInfo
counter now uses a file lock on Windows as well as POSIX, with a three-process
regression verifying no counts are lost. The announcement cache now writes
entries after obtaining its shared session; notice/language separation and
expiry are checked. Both regressions failed against the unfixed code. The
final affected API/cache/counter group passed **23/23** after the negative
checks. Evidence: `.git/catalog-public-access-red.log`,
`.git/catalog-counter-concurrency-red.log`, `.git/catalog-notice-cache-red.log`
and `.git/catalog-public-final-focused.log`.

The pre-pull stash remains intact. Only individually reviewed source fixes
were restored; unrelated saved work was not bulk-applied.

The existing 23 October release report is prior evidence, not proof of these
local changes. Production, the three-day alert delivery window, seven-day
error observation and all named source-file acceptance cases are not
re-certified by this UI work. No deployment has been performed.

Final checks: JavaScript **271 passed**; complete browser suite **242 passed,
11 skipped**. After visual review, the affected catalog/comparison set passed
**49/49** with fixes for opaque hover overlays and readable mobile chart labels.
The final sector summary/history/statement set passed **9/9**; its backend
sector-history and adjacent financial API set passed **57/57**. Production
build and diff checks pass; lint has no errors and one
pre-existing AdvancedChart rounding warning.

Inspected FV, SUM, PL and BS at desktop and 390px mobile sizes, including light
mode FV, exports and error/retry behavior. Current screenshots are under
`output/catalog-final-check/` (FV/PL/BS) and
`output/catalog-final-history/` (SUM and final history charts). No document-wide
horizontal overflow was observed; wide charts/tables scroll within their cards.
EQS shows the assumption date/version and identifies reference-only inputs.
Bank, insurer and fund mobile summaries were inspected after the sector
corrections; final screenshots and the full browser run are in
`output/catalog-completion/`. Final logs are `.git/catalog-completion-*.log`.
The intermediate source-repair suite is
`.git/catalog-source-completion-python.log`; its 22 then-remaining failures
were subsequently resolved as documented above. The final full result is
`.git/catalog-public-final-python.log`.

**QA outcome: PASS for the local catalog changes and full automated suite.**
Live deployment and the multi-day production acceptance observations remain
outside this local sign-off. No manual production deployment was performed.

## API publication check

The selected commit was exported into an isolated directory containing only
tracked and staged files, without the local `.env` or unrelated drafts.
The complete Python suite in that directory passed **3,516 tests, with 86
skipped**. JavaScript **271/271**, the frontend build, the server dependency
check and lint passed (one existing AdvancedChart rounding warning).
Evidence: `.git/catalog-push-python-final.log`, `.git/catalog-push-unit.log`,
`.git/catalog-push-build.log` and `.git/catalog-push-lint.log`.

The workspace count above also included older standalone insurance adapters,
experimental tools and their draft tests. Those files remain local. The TMYS
investment-import regression is included directly with its source fixture;
both adapter tests failed against the unfixed importers and pass with this
change. The commit includes all active catalog dependencies.

Pushing API starts the existing CI workflow, which inspects the configured
application directory and service manager before deploying to uzstock.uz.
This document does not claim that the new deployment has completed.
