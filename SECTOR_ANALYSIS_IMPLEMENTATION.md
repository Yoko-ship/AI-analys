# Sector analysis v2.2 — implementation and verification

Date: 2026-08-30. Requirement source: `final-technical-specification-sector-ai-analysis (1).html`, version 2.2 FINAL.

**Implementation QA: PASS WITH LIMITATIONS.** The core analysis, financial safety fixes, company reports, bond safeguards and monitoring are implemented locally. This is not certification of all 97 acceptance criteria or of 95% issuer coverage. This record initially covered local implementation. The API-branch release verification is recorded below. No source-data backfill or role assignment was performed. Existing unrelated workspace changes were preserved.

## Implemented behavior

- Regular analysis uses cumulative NSBU periods; IFRS remains separate. UZNF uses its verified audited annual IFRS statement. Unsupported consolidated scope is blocked.
- Legal organization type precedes OKED routing. Unknown classifications use a conservative generic template; conflicting classifications block publication. Dated, evidenced issuer overrides are versioned and audited.
- Source cells preserve blanks and zero. Balance and income sections in combined workbooks are separated before mapping, so repeated line codes cannot cross between forms. Insurance reserves are net of reinsurers and included in liabilities.
- Financial arithmetic uses Decimal before display conversion. Balance validation enforces both the rounding-unit and relative tolerance. Extreme cross-form scale discrepancies block the report and market multiples rather than being explained as growth.
- Nonfinancial P1–P8 and liquidity calculations expose their exact source lines, numerator, denominator, formula and method version. Financial organizations do not receive enterprise liquidity ratios.
- Earnings quality, operating performance, FX movements, low-base/sign-change effects and equity movements feed the banner and full report consistently. Unsupported universal cash-flow/earnings substitutes and supervisory ratios are excluded from the new sector report.
- Risks carry evidence, period, threshold/comparison, consequence and source. Issues include a verified or unknown cause, an approved analytical response, monitoring metrics and verdict. Insufficient evidence produces `no_signal`, without invented problems or solutions.
- Unavailable reports show a coded reason, source period and next action. The last good publication remains dated and available; an old restored publication cannot appear current. Empty detail dialogs are not offered.
- UZNF displays audited NAV, unrealized revaluation, dividend income, Level 3 and concentration separately. Price/NAV is withheld until an evidenced share conversion reconciles and the quote is recent, positive and applicable to that share basis.
- Bond freshness is independent of schedule completeness. Inferred schedules are labeled indicative. No-trade yields/duration, unsupported day-count calculations and unknown future floating coupons are withheld. Verified accrual can exist without a trade, but dirty price cannot.
- Exact bond calculations require sourced future flows, principal reconciliation and verified options. G-spread requires the same date, currency and compounding basis; effective annual corporate yield is converted to continuous compounding.
- Bond details resolve an exact issuer identity and open its shared financial report. Two issues share one calculated issuer snapshot while keeping their own cash flows, market dates and instrument verdicts. Bond principal is not added to reported liabilities.
- Source ingestion queues automatic RU/UZ analysis, with leases, retries, deduplication and an incident state after the retry limit. EN is available on demand. Rule activation is gated by the runtime regression pack. Versioned publications, rollback, audit history and issuer-scoped recalculation are available in monitoring.
- Monitoring reuses the existing access system: viewer = read; analyst = read/retry; rule_editor and administrator = rule activation/rollback as well. An explicit lower role overrides the legacy administrator allowlist. Collector credentials cannot open this interface.

## Public and administrative entry points

- Company overview → **Подробнее**: sourced sector report with expandable facts and formulas.
- Existing `/api/analyze`: adapts the verified report to the established response shape; it no longer calls the universal LLM narrative path.
- `/api/v1/issuers/{issuer}/ai-report`, `/credit-profile`, `/bonds`: report and shared issuer context.
- `/bond/{ticker}` and `/api/bonds/{ticker}`: independent bond calculations plus shared issuer report.
- `/admin/analysis`: monitoring embedded in the existing administrator page.
- `/admin/sector-analysis`: dedicated monitoring page for the permitted viewer/analyst/editor/administrator roles.
- `/api/admin/sector-analysis`: runs, failures, overrides, retry and rollback. Authorization is enforced server-side; computed facts cannot be manually edited here.

Storage uses the existing `dbx` adapter. Local monitoring defaults to the application data directory, with `SECTOR_ANALYSIS_DB` available for isolated testing. The worker defaults on and can be disabled using `SECTOR_ANALYSIS_WORKER=0`.

## Source-backed checks

These checks used downloaded source workbooks, not the specification's illustrative values as production data. Cleaned workbook fixtures retain source URLs. The UZNF PDF was downloaded and visually checked against the statements and notes.

| Issuer | Observed result |
|---|---|
| UZMK, 2026 H1 | Operating profit 409,979,351 → 373,505,355 thousand UZS, down 8.90%; net FX movement +499,571,337 thousand UZS; quick ratio 1.01913778. Banner is mixed and identifies the FX/base effect. |
| UZMK, 2026 H1 | Equity 6,059,780,470 → 6,375,622,697.23 thousand UZS; component reconciliation passes. |
| UZAS, 2026 H1 | Net profit 3,501,207.7 → 294,295.9 thousand UZS; operating loss 5,547,703.4 thousand UZS. Assets 332,548,245.7 = equity 147,661,927.4 + liabilities 184,886,318.3. |
| HMKB, 2026 H1 | Assets 41,314,813,995 = liabilities 33,640,142,060 + equity 7,674,671,935 thousand UZS. Interest income 2,994,355,667 and expense 1,520,167,682 are separately mapped. |
| UZNF, first annual period | Audited NAV = 30,286,541 − 425,002 = 29,861,539 million UZS; portfolio/assets ≈99.45%; Level 3 = 100%; top five ≈68.23%. No invented previous period or share conversion. |

Source files and report snapshots are in `audit/sector-v2.2/`. The audited fund register and evidenced activity classifications are in `config/verified_fund_reports.json` and `config/verified_sector_classifications.json`.

**Source-label clarification:** ordinary NSBU Form 1 c130 is total noncurrent assets in the inspected filing; net fixed assets are c012. The implementation preserves the requested P8 formula with c130, but does not mislabel the entire c130 balance as fixed assets.

## Verification evidence

- **269 Python tests passed**, covering sector logic, live-filing fixtures, API adapters, bonds, role restrictions, persistence/retry/rollback, market multiples, filed liquidity and existing financial corrections.
- **13 browser tests passed**, using the real built site with mocked surrounding APIs: company report/source/formula flow; blocked/last-good state; retry recovery; mobile dark tables and persistent close control; admin mutation payload and feedback; viewer restrictions; bond-to-issuer report; nearby company/mobile/bond regressions.
- `npm run build` passed. The existing bundle-size warning remains.
- Targeted ESLint: **0 errors, 54 existing warnings** in the large existing App/AdminPanel files. New report and monitor components have no lint warnings.
- Python compilation and whitespace checks passed for the new/changed analysis modules.
- Visually inspected actual rendered desktop and mobile reports, dark mobile tables, admin rules and bond issuer reports. Screenshots include `report-mobile-dark.png`, `admin-rules.png` and `bond-issuer-report.png` in the audit directory.
- A local preview also exercised the real engine and audited UZNF data with a synthetic surrounding market API; it was not a production integration test.

Python command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sector_contract_v22.py tests/test_issuer_analysis_api.py tests/test_sector_analysis_service.py tests/test_bonds_provenance.py tests/test_bond_registry.py tests/test_admin_panel.py tests/test_fundamentals.py tests/test_filed_liquidity_ratios.py tests/test_financial_corrections.py -q -p no:cacheprovider --basetemp=audit/sector-v2.2/pytest-run-11 --tb=short
```

Browser command:

```powershell
npx playwright test e2e/sector-analysis.spec.js e2e/smoke.spec.js --workers=1 --grep "sector report|blocked reports|source error|admin rules|verified financial|a viewer|a bond opens|company overview|company AI insight|company insight remains|profile and analysis workspaces|bonds table"
```

Use a new temporary-test directory on another run. Windows sandbox restrictions required running the build/browser tests and pytest temporary-file operations with elevated sandbox permission. No production data was changed for those checks.

## Limits and remaining acceptance work

1. **Production acceptance is outstanding.** The site was not deployed, PostgreSQL was not exercised against a live isolated database, the complete issuer universe was not backfilled, and 95% coverage has not been measured. The 269 passing tests are not 269 production issuers or a claim that all AT-01–AT-97 passed.
2. **Some exact source cases are not certified.** Live checks used UZAS H1 rather than the specific Q1 example in AT-02. UQEQ's extreme-scale scenario is regression-tested, but its complete live issuer path was unavailable in the local catalog. The exact ANBK3B example needs a verified accrual period and schedule. UZNF's example share conversion is tested as a supplied verified reconciliation, but no verified corporate-action record was inserted into production data; actual Price/NAV remains withheld.
3. **Additional source coverage is needed.** Many filings expose old OKONH rather than OKED. These are not silently converted. Complete MFO/microfinance-bank mappings, aviation/telecom operating disclosures, URTS own-versus-client cash separation and SPV backing evidence require their actual source datasets. Missing supplemental metrics remain null; SPV analysis remains blocked without backing evidence.
4. **Fund ingestion is a verified register, not an automatic PDF extraction service.** The 2025 UZNF annual facts were independently checked and registered. A new annual PDF needs the same verification before activation. Unsupported share-capital changes cannot be unlocked by price data alone.
5. **Advanced workflow scope remains.** Dated per-issuer overrides recalculate their affected issuer. A complete global-rule impact editor, all issuer/ISIN corporate-event dispatch paths, historical risk stability and peer medians are not implemented by this patch. Shared financial changes propagate when instrument reports are read; this is not a claim of a complete persisted event dispatcher.
6. **Unknown floating-rate scenarios remain blocked.** No invented assumptions or yield range is published. Explicit verified benchmark/reset terms and a scenario input model are still needed to deliver AT-78's scenario range. Exact bonds currently support disclosed ACT/365 or ACT/365F; other conventions are withheld rather than silently approximated. The existing auction feed lacks the continuous-compounding metadata required by the new G-spread gate; it is not treated as the same-date CBU zero-coupon curve.
7. **Runtime release checks are intentionally bounded.** The automatic gate is a small version-fingerprinted arithmetic/routing pack. The broader Python/browser suites were run during this implementation; wiring all 97 acceptance cases into a production release pipeline remains outstanding.

The attachment was treated as a requirements document. Examples were used as test cases, not as authority to invent live financial facts, weaken access controls or deploy unrelated pending workspace changes.

## API branch release verification

The release was assembled over API commit `96a3ce5`, including only this feature and its verification fixes. Unfinished news and extended-admin changes were excluded. The sector monitor honors configured `ADMIN_ROLES` and the existing administrator allowlist without requiring the separate extended-admin console. If that console is installed, its persisted access decisions remain authoritative.

- Full isolated backend suite: **1,420 passed, one skipped**. The skipped registry cost test requires a larger local catalog.
- Website unit tests: **92 passed**. Build, targeted lint, and server-dependency verification passed.
- Feature browser checks: **13 passed**, against the built release with mocked APIs.
- Full browser suite: **59 passed, 10 failed**. The failures concern existing landing selectors, chart labels, and market-table controls. They were reproduced against unchanged API commit `96a3ce5`; they are not counted as passing or as regressions introduced by this release.
- Verification fixes preserve missing-reference bond statuses, seed owned provenance test data, avoid an expired news test date, and include local Python packages in the runtime dependency check.

Production rollout and live acceptance remain separate from these local checks. Source-dependent limitations listed above still apply. Raw audit downloads and screenshots are local evidence, not included in the branch commit; the cleaned source fixtures and verified configuration registers are included.
