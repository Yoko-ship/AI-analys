# Reporting ownership

`analysis_service.py` coordinates collection, caching, analysis, and comparison.
It retains existing public export functions for compatibility. New consumers
should use the owning module directly, as the HTTP export handlers do.

| Change | Owner |
| --- | --- |
| Build a complete structured article | `article/builder.py` |
| Read spreadsheet values and match statement lines | `article/rows.py`, `article/labels.py` |
| Resolve dates and select comparable filings | `article/periods.py` |
| Build balance, income, trend, and appendix tables | `article/tables.py` |
| Derive signals and explain their meaning | `article/signals.py`, `article/indicators.py`, `article/narrative.py` |
| Render supplied ratios | `article/ratios.py` |
| Prepare financial and market context | `financial_snapshot.py`, `market_context.py` |
| Derive risk and comparative rankings | `risk.py`, `comparison_metrics.py` |
| Format numeric cells and section tables | `numbers.py`, `presentation.py`, `report_tables.py` |
| Render completed results as Excel or PDF | `exports.py` |
| Prepare prompts and call the AI provider | `prompts.py`, `ai.py` |
| Save a report and project its administrative status | `publication.py`, `store.py` |
| Retry queued work | `worker.py` |

Article rendering and document exports consume supplied data. They must not
import collection, HTTP routes, persistence, or the AI adapter. Dependencies
flow toward parsing and formatting; the architecture checks reject cycles.

The content fixtures in `tests/fixtures/article_reports.json` were captured
before extraction. Tests compare all article blocks in three languages, check
that input filings remain unchanged, and inspect generated Excel/PDF content.
Financial interpretation was preserved during extraction; these fixtures do
not independently certify accounting rules.

A report job succeeds only after its authoritative report save succeeds.
Publication errors propagate to the worker's retry mechanism. Administrative
status projection remains best effort after a successful report save.
