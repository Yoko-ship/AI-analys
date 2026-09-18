# Bank financial ingestion: operational contract

Deployment target: the existing uzstock.uz VPS, `/root/uzstock/app`, Docker
`uzstock-web`, persistent `uzstock_data:/app/data`. Not Railway.

## Data path and ownership

```text
OpenInfo MSFO + Audit catalog entries
        ↓ discover by issuer + URL (not guessed financial year)
Persistent FETCH jobs → SHA-256 addressed original PDFs
        ↓ EXTRACT jobs, native text + bounded English/Russian OCR
Immutable candidates → deterministic checks → explicit evidence review
        ↓ explicit publish command; ONE database transaction per issuer
Immutable published snapshots + replaceable period heads → annual IFRS API
```

`financial_ingestion/store.py` owns jobs, source versions, reviews, events and
snapshot pointers in the existing catalog database. `documents.py` owns original
bytes, stored in `/app/data/financial_artifacts`. Both must be backed up.
`extract.py` proposes values; `validation.py` checks periods, units, signs,
balance identity and page/column evidence. `publication.py` alone changes heads.

NSBU remains on the existing workbook collector and its existing provenance.
The bank-history job now **queues IFRS discovery**, not legacy IFRS publication.
The separate `ifrs_history` status must not be inferred from NSBU job success.
Existing legacy IFRS values remain readable until the issuer is explicitly
migrated. First migration refuses to hide any previously published annual year.
The new snapshots currently feed annual financial-series and passport endpoints;
this is not a migration of the market-wide valuation/calculation ledger.

## Safety properties

- No publication from OCR, download success, a scheduled job, or an empty review
  result. Native/OCR drafts always require review. Checked-in visual reviews are
  bound to issuer, exact source URL, SHA-256 and page count; they still require
  a separate publication command.
- A replacement PDF creates a new version. Published old numbers remain with
  their exact archived evidence, while status flags the publication as stale.
- Money inside candidates/snapshots is decimal text. Full UZS normalization is
  explicit; the existing reader's thousands-UZS compatibility conversion occurs
  only at the boundary. Missing is never zero.
- Consolidated and separate accounts are separate publication keys. The public
  reader selects one issuer-wide perimeter, never silently mixes years from both.
- Primary, comparative and restated columns carry distinct roles and document
  years. This release publishes completed calendar-year IFRS only; interim and
  NSBU candidates do not take over existing public paths.
- Approval corrections append new candidates. Replacing published figures needs
  explicit candidate selection and `--replace`. Rollback moves heads to retained
  snapshots and records actor/reason; it does not delete history.
- Jobs are deduplicated, leased for 15 minutes, recovered after crashes, and
  retried at most three times with backoff. Old lease holders cannot commit.
  Parser/review changes create new extraction jobs using archived originals.
- The hourly worker is limited to four jobs, half a CPU, 768 MB, 128 processes,
  and 30 minutes. OCR examines at most eight pages within its own time budget.
  A malformed/long document may need manual handling; limits are not a promise
  to extract every bank layout automatically.

## Operating the worker

Run commands inside a container sharing the persistent volume. Never run a
production migration against a disposable collector database. The checked-in CI
workflow installs `uzstock-financial-ingestion.service` and `.timer`, hourly at
minute 35 UTC, with `cycle --max-jobs 4 --ocr`. The worker stages only.

```sh
docker exec uzstock-web python -m financial_ingestion.worker discover --ticker BRBN
docker exec uzstock-web python -m financial_ingestion.worker work --max-jobs 4 --ocr
docker exec uzstock-web python -m financial_ingestion.worker status --ticker BRBN
docker exec uzstock-web python -m financial_ingestion.worker candidates --ticker BRBN
```

The heavier OCR work should normally run in the resource-limited systemd worker,
not the web container. `discover` scans the local catalog; source catalog sync is
still performed by the existing reports/bank-history collectors. Discovery does
not guarantee OpenInfo exposed every historical filing.

For a reviewed correction, supply a JSON object with `classification` and
`figures`, using an existing candidate as the immutable source version:

```sh
python -m financial_ingestion.worker propose --id CANDIDATE --file reviewed.json --actor REVIEWER --reason 'Checked original pages and year columns'
python -m financial_ingestion.worker approve --id NEW_CANDIDATE --actor REVIEWER --reason 'Verified issuer, scope, dates, units and figures'
python -m financial_ingestion.worker publish --ticker BRBN --actor PUBLISHER --id NEW_CANDIDATE
```

Select every required candidate on first migration (`--id` is repeatable), or
omit `--id` only when approved candidates are unambiguous. To supersede an
existing period add `--replace`. Never approve based only on passing arithmetic;
read the source pages. Do not combine separately reported interest components
and label the result as a directly reported raw figure.

```sh
python -m financial_ingestion.worker rollback --id OLD_SNAPSHOT --actor OPERATOR --reason 'Incorrect review reverted'
python -m financial_ingestion.worker retry --id FAILED_JOB --actor OPERATOR --reason 'Source access restored'
```

## Monitoring and recovery

`status` reports pending/failed jobs, unreviewed sources, approved-but-unpublished
candidates, stale published versions and sources overdue for refresh. `PROCESSED`
means the discovered workload is processed, **not** complete financial coverage.
Partial statements and undiscovered years can still exist.

The authenticated `GET /api/admin/financial-ingestion/status` exposes detailed
failures. Annual MSFO responses include a public `ingestion` summary and report
`PARTIAL` when work remains. No external notification destination is configured
by this change: connect that endpoint to the team's alerting system. Alert on
failed jobs, stale publications, increasing overdue counts, disk pressure and
the timer ceasing to run. Review backlog is expected, not successful coverage.

Before deployment, inspect the live directory/service manager, take a SQLite
online backup and verify `PRAGMA integrity_check`. Before any cleanup, back up
the database **and** originals; no evidence-retention deletion is implemented.
For a restore drill, restore both into an isolated directory, read every
referenced hash, run the focused tests, and verify a sampled passport against
its original PDF. An archive integrity failure blocks publication/downloads.

Required CI gate: `tests/test_financial_ingestion.py`,
`tests/test_ifrs_financials.py`, `tests/test_bank_history_repair.py`. The wider
suite has pre-existing failures and is not a substitute for this required gate.

## Initial reviewed scope

The existing seven BRBN reviews are retained. Additional reviews cover BRBN
2025 (nine figures) and OCBK 2025 (five directly reported figures: assets,
liabilities, equity, cash and net income). OCBK interest aggregates and operating
totals are deliberately not fabricated. Other bank PDFs remain review work;
adding this architecture does not claim their historical gaps are filled.
