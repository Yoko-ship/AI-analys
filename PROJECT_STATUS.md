# UZStock project status

Last updated: 2026-09-23

## Production target

We are working on the existing **uzstock.uz production server**, not Railway.

- Public site: `https://uzstock.uz`
- SSH host, port and user: `DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT` and
  `DEPLOY_SSH_USER` in the local, git-ignored `.env` (never in tracked files)
- Last recorded active application directory: `/root/uzstock/app`
- Last recorded web container: `uzstock-web`
- Persistent application data: `uzstock_data:/app/data`

Before every production deployment, inspect the live host to confirm the active
application directory, container layout, and service manager. Back up and verify
the live databases and original financial documents before changing production.
Do not use Railway deployment, monitoring, or recovery tools for this project.
Any Railway material still present in older repository documentation is legacy
information and is not the current deployment procedure.

## What we have completed so far

### Financial history and IFRS ingestion

- Built a durable bank IFRS ingestion pipeline with source discovery, immutable
  original PDFs, SHA-256 source identity, extraction jobs, validation, human
  review, explicit publication, rollback, monitoring, and verified backups.
- Added dynamic parsing for annual and interim statements, including difficult
  scanned/OCR layouts, appendix statements, wrapped date headers, comparative
  columns, and mixed annual/interim income columns.
- Made future IFRS ingestion OpenInfo-only while preserving already published
  legacy history. Publication remains an explicit reviewed operation; downloading
  or parsing a document never publishes it automatically.
- Recovered and published reviewed historical IFRS periods. The September 19
  production record shows 187 published period heads preserved during the bulk
  worker deployment.
- Added public provenance and ingestion status so partial, stale, unreviewed,
  unpublished, and missing data are not presented as complete coverage.
- Prevented obsolete parser jobs from consuming the active work budget and added
  stronger handling for replacement source files and OCR recovery passes.

### NSBU history

- Added historical annual and quarterly NSBU discovery and parsing from OpenInfo
  workbooks, with source-aware checkpoints and safe repeat runs.
- Repaired UZIR/UZIRP production history on September 19: 41 periods were
  reparsed, 21 historical quarter links were added, and a repeat run skipped all
  41 completed periods.
- Corrected reviewed annual-year mappings for mislabeled OpenInfo records without
  changing the source financial figures.
- Kept known gaps explicit. For example, UZIR 2017 still has a Q3/FY conflict and
  no Q2 filing in the unified history, so unsupported Q3/Q4 flows remain absent.

### Market valuation and public financial contract

- Corrected issuer capitalization so confirmed inactive preferred shares do not
  block or distort P/E and P/B for an actively traded ordinary share. The excluded
  class and narrower capitalization basis are disclosed in the API.
- Verified the production result across all 100 share listings representing 68
  companies. The September 19 audit found no remaining inactive-preferred-share
  blockers, no arithmetic differences against the published inputs, and no
  mismatch between the market page and its API.
- Retained honest non-calculated states for missing/stale prices, losses,
  unverified financials, conflicts, and configured out-of-range values.

### News and report presentation

- Improved issuer-news deduplication and prioritization of report analysis.
- Added database-dialect coverage for news deduplication behavior.
- Updated the frontend report experience in the latest committed work.

### Production work already verified

The recorded September 19 VPS work included:

- verified financial backups before changes;
- deployment of the bulk financial worker and nightly schedule;
- the UZIR NSBU repair;
- the inactive-preferred capitalization fix;
- API health checks and browser verification on `uzstock.uz`;
- preservation of the existing published IFRS heads and persistent data volume.

Supporting evidence is in:

- `docs/bulk-production-deployment-2026-09-19.json`
- `docs/nsbu-production-repair-2026-09-19.json`
- `docs/preferred-production-deployment-2026-09-19.json`
- `docs/audits/valuation-all-companies-2026-09-19.md`
- `docs/bank-ifrs-review-2026-09-18.md`

## What we are currently working on

The current local working tree contains an uncommitted integration batch. Some
parts correspond to targeted changes already recorded as deployed on September
19, but the batch as a whole must not be treated as a new production release.

Current work includes:

- finishing the resumable all-issuer bulk command that refreshes the catalog,
  collects NSBU history, discovers every permitted IFRS/audit PDF, downloads and
  parses queued documents, and writes a persistent coverage/gap report;
- moving the financial ingestion service to a bounded nightly 02:00 Asia/Tashkent
  run with two workers, OCR, NSBU history, a 24-hour timeout, 1 CPU, 3 GiB RAM,
  and the shared production data volume;
- completing source-scoped queue processing so concurrent workers handle only the
  selected issuers and stages;
- improving NSBU period resolution, annual-year clamping, workbook balance-line
  extraction, commercial-company operating-expense parsing, and source linkage;
- preserving all IFRS source URLs when several filings or revisions map to the
  same catalog year;
- refining multilingual duplicate detection for syndicated credit-rating news;
- consolidating the preferred-share capitalization contract and its regression
  coverage;
- expanding tests for bulk reporting, bulk collection, NSBU history, IFRS source
  listing, public-contract behavior, annual-year handling, and news deduplication.

The detailed operator guide for this work is `docs/bulk-financial-collection.md`.

## Remaining work and known limitations

- Review and commit the current integration batch, then run its focused and broad
  test suites before considering another deployment.
- Re-inspect the live VPS immediately before deployment; do not assume the recorded
  September 19 paths and service state are unchanged.
- Verify a fresh database/original-document backup and a rollback image before
  replacing the web image or systemd worker definition.
- Resume durable collection for pending/retry jobs and inspect terminal failures;
  failed jobs require an explicit retry.
- Human-review valid IFRS candidates before publication. A completed bulk run or
  passing arithmetic is not authorization to publish.
- Continue closing genuine source gaps. A zero-exit bulk run means selected work
  was processed, not that every issuer and historical period exists.
- Several issuers still lack a usable recent ordinary-share price, and some ratios
  correctly remain unavailable, unverified, loss-making, or out of range.
- Local verified backups protect against processing errors but are not offsite
  disaster recovery.

## Safe next production sequence

1. Connect to the VPS (`DEPLOY_SSH_*` in `.env`) and inspect the active directory,
   running containers, systemd units/timers, data mounts, disk space, and health.
2. Run the relevant tests locally and review the exact release diff.
3. Create and verify backups of the live catalog/database and every referenced
   original document; retain the current image as the rollback target.
4. Deploy only to the `uzstock.uz` VPS using its confirmed application layout.
5. Verify API health, financial-ingestion status, timer state, logs, and affected
   browser pages. Record the deployed image, backup, assertions, and rollback
   target in a new dated production evidence file.

