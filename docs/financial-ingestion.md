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
Snapshots feed annual and interim financial-series, passports, and the shared
`get_all_financials("MSFO")` calculation reader. They do not rewrite the separate
market-wide calculation ledger or migrate NSBU storage.

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
  years. Calendar annuals and Jan-to-March/June/September IFRS periods are supported.
  Interim flows stay cumulative YTD, never inferred standalone quarters; the UI
  labels this explicitly and disables QoQ growth. NSBU candidates do not take over
  existing public paths.
- Approval corrections append new candidates. Replacing published figures needs
  explicit candidate selection and `--replace`. Rollback moves heads to retained
  snapshots and records actor/reason; it does not delete history.
- Jobs are deduplicated, leased for 15 minutes, recovered after crashes, and
  retried at most three times with backoff. Old lease holders cannot commit.
  Parser/review changes create new extraction jobs using archived originals.
- The fifteen-minute worker is limited to four jobs, half a CPU, 768 MB, 128 processes,
  and 30 minutes. OCR examines at most eight pages within its own time budget.
  A malformed/long document may need manual handling; limits are not a promise
  to extract every bank layout automatically.

## Operating the worker

Run commands inside a container sharing the persistent volume. Never run a
production migration against a disposable collector database. The checked-in CI
workflow installs `uzstock-financial-ingestion.service` and `.timer`, at minutes
05/20/35/50 UTC, with `cycle --max-jobs 4 --ocr`. The worker stages only.

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
read the source pages. Calculated sums must include `calculation: "sum"` and
each signed component's raw value, label, page and year. The validator requires
an exact decimal sum; passports display the components and calculation formula.
Never label an aggregate as a directly reported total.

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
`PARTIAL` when work remains. The admin dashboard is the selected alert destination:
its overview shows incidents, review backlog and publication counts; admin users
also see incidents in the notification bell. No external messages are sent.
`uzstock-financial-monitor.timer` checks every fifteen minutes for failed jobs,
changed published sources, disk pressure, worker silence (>2 hours), and missing
verified backups (>26 hours). Incidents deduplicate, resolve after recovery, and
reopen as a new occurrence. The dashboard separately warns if the monitor itself
has not completed for an hour. Review backlog is not successful coverage.

`uzstock-financial-backup.timer` runs daily at 01:00 UTC. It takes an online SQLite
snapshot and independent copies of every referenced original, verifies hashes,
restores the database in a temporary directory and checks integrity/foreign keys.
Backups default to `/app/data/financial_backups`; shared immutable backup objects
are separate from live originals. No automatic deletion/retention is enabled.
These are local recovery copies, **not offsite disaster recovery**.

```sh
python -m financial_ingestion.worker backup
python -m financial_ingestion.worker verify-backup --file /app/data/financial_backups/BACKUP_DIRECTORY
python -m financial_ingestion.worker monitor
```

Before deployment, inspect the live directory/service manager, take a SQLite
online backup and verify `PRAGMA integrity_check`. Before any cleanup, back up
the database **and** originals; no evidence-retention deletion is implemented.
For a restore drill, restore both into an isolated directory, read every
referenced hash, run the focused tests, and verify a sampled passport against
its original PDF. An archive integrity failure blocks publication/downloads.

Required CI gate: `tests/test_financial_ingestion.py`, `tests/test_financial_ingestion_recovery.py`,
`tests/test_ifrs_financials.py`, `tests/test_bank_history_repair.py`. The wider
suite has pre-existing failures and is not a substitute for this required gate.

## Reviewed scope

The review ledger covers BRBN 2016–2025; OCBK, DRBK and GRBK 2024–2025;
IPTB 2023–2024; and SQBN 2024H1. Each period has nine evidenced figures.
BRBN 2017/2020 and prior-year comparisons retain their comparative roles.
OCBK interest and operating totals carry explicit component evidence. Primary
published dates override catalog labels only while that source version is current.
Other bank PDFs and older history remain review work; adding this architecture
does not claim every historical gap is filled or that unavailable filings exist.
