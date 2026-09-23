# UZStock project status

Last updated: 2026-09-23

## Production target

The site runs on the **uzstock.uz VPS**, not Railway.

- Public site: `https://uzstock.uz`
- SSH: key-only. Host, port and user are `DEPLOY_SSH_HOST`, `DEPLOY_SSH_PORT`
  and `DEPLOY_SSH_USER` in the local, git-ignored `.env` — never in tracked files.
- Application checkout: `/root/uzstock/app`, branch `API`
- Web container: `uzstock-web`, published on `127.0.0.1:8001` behind the VPS
  Nginx, which itself sits behind an external OpenResty (Nginx Proxy Manager)
  front proxy that terminates public TLS with its own certificate
- Persistent data: Docker volume `uzstock_data` mounted at `/app/data`
- Scheduled workers: systemd timers `uzstock-*` running the same image

Railway material still present in older documentation (`railway*.json`,
`admin_railway.py`, parts of `DEPLOY.md`) is legacy and not the deployment path.

## How changes reach production

1. Push to `API`. The repository is public, so GitHub Actions minutes are free.
2. CI runs the secret scan, backend tests, frontend lint/unit/build/e2e smoke and
   the Docker image check. **Any failure blocks the deploy.**
3. The `Deploy production` job updates the VPS checkout, builds the image,
   replaces `uzstock-web` (about 7 s of API downtime), rewrites the systemd units
   and the Nginx snippet, and verifies `/` and `/health`.

`main` is not the deployment branch and is intentionally left untouched.

## Completed

### 2026-09-23 — security, reliability and speed

- **Secrets:** leaked credentials were revoked and purged from every branch by a
  history rewrite; `.gitignore` covers env files, keys, dumps and backups; every
  push is scanned by gitleaks in CI and by GitHub secret scanning with push
  protection. Dependabot alerts and security updates are enabled.
- **Server access:** SSH password login disabled; stale temporary keys removed.
- **Restored the September 19 fixes**, which later feature-branch deploys had
  dropped: bulk financial collection, NSBU history and period mapping, and
  inactive-preferred capitalization. OpenInfo-reported class capitalization stays
  authoritative; the inactive-preferred exclusion applies only where no such cap
  exists.
- **Nightly jobs:** the financial-ingestion job failed because its module was
  missing from the image; the full collector exited 1 because its facts step
  depended on the retired market mirror. Both fixed.
- **Retired mirror:** the Railway market mirror no longer exists; it is off unless
  `UZSE_STOCK_API_BASE` is set, and stored listings plus exchange quotes are used.
  Registry-only listings (e.g. DRBK) are now catalogued.
- **Defects found by the test suite:** v3 pipeline writes, provenance backfill,
  audit-blocked display flag; three stale or date-dependent tests corrected.
  The suite is green (1,873 tests).
- **Performance** (measured on the live site):

  | | Before | After |
  |---|---|---|
  | First visit transfer (gzip at Nginx) | ~1.4 MB | ~385 KB |
  | Market board | 0.74 s | 0.05–0.08 s |
  | Company AI summary | 1.1 s | 0.2–0.4 s |
  | Full AI report | 2.5 s | 0.5–0.6 s |
  | Docker daemon CPU (Netdata polled it every second) | ~78% | ~1% |

  Report latency came from per-call schema replay in `data_quality`, repeated SQL
  tokenising in `dbx`, and re-parsing the 14 MB OpenInfo Excel cache on every read.

### Financial history and IFRS ingestion

- Durable bank IFRS ingestion pipeline: source discovery, immutable original PDFs,
  SHA-256 identity, extraction jobs, validation, human review, explicit
  publication, rollback, monitoring and verified backups.
- Dynamic parsing of annual and interim statements, including scanned/OCR layouts,
  appendix statements, wrapped date headers and mixed annual/interim columns.
- Future IFRS ingestion is OpenInfo-only; downloading or parsing never publishes.
- 187 reviewed historical IFRS period heads are published.
- Resumable all-issuer bulk command with a persistent coverage/gap report — see
  `docs/bulk-financial-collection.md`. Nightly at 02:00 Asia/Tashkent, two
  workers, OCR, 1 CPU, 3 GiB, 24-hour limit.

### NSBU history

- Historical annual and quarterly NSBU discovery from OpenInfo workbooks with
  source-aware checkpoints and safe repeat runs.
- UZIR/UZIRP repaired on 2026-09-19 (41 periods reparsed, 21 quarter links added).
- Reviewed annual-year corrections in `reviewed_nsbu_periods.json`.
- Known gaps stay explicit (e.g. UZIR 2017 Q3/FY conflict, no Q2 filing).

### Market valuation and public contract

- Inactive preferred classes no longer block P/E and P/B of a traded ordinary
  class; the narrower basis is disclosed.
- Honest non-calculated states for missing/stale prices, losses, unverified
  financials, conflicts and out-of-range values.

Evidence: `docs/*-2026-09-19.json`, `docs/audits/valuation-all-companies-2026-09-19.md`,
`docs/bank-ifrs-review-2026-09-18.md`.

## Remaining work and known limitations

- **Backups are not offsite.** PostgreSQL (accounts, sessions, analytics) is
  dumped nightly at 00:40 UTC by `scripts/backup_postgres.sh` (verified with
  `pg_restore --list`, 14 kept, `/root/uzstock/backups/postgres`), and the
  financial evidence at 01:00 UTC — but both live on the VPS disk. Offsite copy
  needs a destination decision.
- Confirm the first nightly runs after the fixes: financial ingestion (21:00 UTC)
  and the full collector (03:00 UTC).
- GitHub Support has not yet purged cached views of the pre-rewrite commits
  referenced by closed PRs #1 and #3 (the credentials in them are revoked).
- The front proxy (the hosting provider's gateway, 10.100.0.201) overrides cache
  headers for JS/CSS/images with a daily expiry (00:30 GMT). Impact is small:
  after expiry browsers revalidate and get 304 with no body (ETag passes
  through). Optional: ask the provider to disable "Cache Assets" for uzstock.uz.
- Company logos were shrunk from 4.6 MB to 1.2 MB (2026-09-23).
- Background loops (catalog sync, news calendar, sector worker) share the single
  web process.
- Human-review valid IFRS candidates before publication; a completed bulk run or
  passing arithmetic is not authorization to publish.
- Continue closing genuine source gaps; several issuers lack a recent
  ordinary-share price, and some ratios correctly remain unavailable.
