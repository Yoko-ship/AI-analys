# Bulk financial document collection

Run the OpenInfo NSBU history and IFRS/audit PDF sweep from the project directory, using
the application's Python environment and catalog database:

```sh
python -m financial_ingestion.bulk --workers 2 --ocr --nsbu-history
```

This refreshes the issuer/report catalog, groups securities by issuer, discovers
direct PDF filings and all available annual-report attachments, downloads and
parses the queued documents, and writes `data/bulk-financial-report.json`.
Discovery covers nonbank issuers too; unfamiliar statement layouts remain
explicit extraction/review gaps. With `--nsbu-history`, the sweep first discovers historical NSBU quarters and
parses all catalogued annual and quarterly workbooks. It refreshes ordinary and
preferred shares together, validates replacements, and checkpoints completed
periods by source and parser version. Incomplete periods are retried next run.
Without this flag, the command collects PDF documents only. This command does not
collect quotes, news, or other market datasets.

PDFs with the same catalog year are registered independently by issuer and URL.
Every source allowed by the existing OpenInfo policy is retained. Concurrent
downloads share the OpenInfo pacing gate; retries retain the durable queue's
backoff and three-attempt limit. PDF parsing/OCR runs in separate processes.
`--workers` controls each pool and defaults to two, avoiding excessive memory
use on the VPS. `--ocr` requires Tesseract; omit it for native text extraction.

The command keeps processing until the selected queue drains, including
scheduled retries. Repeating it resumes durable work; completed jobs are not
reset. With `--ocr`, native-only incomplete candidates receive one additional
OCR job per parser/document version. Reviewed evidence, original files and
published snapshots remain intact. Terminal failures require an explicit
`--retry-failed` run.

Useful variants:

```sh
# Resume using the existing catalog; still discover its PDF attachments.
python -m financial_ingestion.bulk --skip-sync --workers 2 --ocr

# Refresh upstream listings even when the catalog's freshness TTL has not expired.
python -m financial_ingestion.bulk --force-sync --workers 2 --ocr

# Process a subset; preferred shares and ordinary shares share issuer coverage.
python -m financial_ingestion.bulk --ticker DRBK --ticker SQBN --ocr

# Stop scheduling after one hour and resume later with the same command.
python -m financial_ingestion.bulk --skip-sync --max-seconds 3600 --ocr

# Produce the missing-data/review inventory without fetching or parsing.
python -m financial_ingestion.bulk --report-only --report data/financial-gaps.json
```

The time budget is a scheduling limit, not a process kill timeout. Catalog sync
the optional NSBU history stage, and already running network/PDF operations
finish before exit. Progress is
logged and the report is replaced atomically during discovery and processing;
the final report contains issuer aliases, source URLs/hashes, failed downloads,
disclosure errors, candidate periods/scopes, missing fields, validation errors,
review status and unpublished approved candidates. Annual gaps are reported
only between observed years within the same accounting standard and scope.
Unpublished, unreviewed and missing data are distinct states.

Exit status is `0` for completed selected processing/inventory, `1` for errors
or unresolved issuers, `2` when the budget leaves pending work, and `130` after
interruption. A zero exit status does not mean every historical filing exists
or every candidate has been reviewed. PDF candidates are not published automatically. The optional NSBU stage updates
the existing NSBU financial cache from source workbooks.

Use `CATALOG_DB_PATH` and `FINANCIAL_ARTIFACT_DIR` to select an isolated test
catalog and originals directory. On the existing `uzstock.uz` deployment, use
the active application's environment and run as its application user so PDF
originals stay readable. Deployment of code is a separate operation; inspect
the active directory and service manager before deploying as required by
`AGENTS.md`.

The VPS deployment workflow runs this command in
`uzstock-financial-ingestion.service`, sharing `uzstock_data:/app/data`, with
two workers, OCR, NSBU history, 1 CPU and 3 GiB memory. Its timer runs nightly at 02:00 Tashkent;
systemd keeps a running sweep as the sole instance. A sweep can run up to 24
hours and its queue resumes on the next scheduled invocation after interruption.
The full report is `/app/data/bulk-financial-report.json` in the data volume.

Reviewed annual-period corrections are recorded in `reviewed_nsbu_periods.json`.
Each correction matches an exact organization, source record and old label,
with links and audit evidence. For UZIR, audit conclusions identify record 3109
as FY2017 and record 3110 as FY2018 despite later OpenInfo labels. The same
resolved fiscal year applies to both income and balance statements. Financial
figures remain parsed from the original workbooks.
