# Deploy

## 1. Prepare server

Install Docker and Docker Compose plugin on the VPS.

Clone the repository and enter the project directory.

## 2. Configure environment

Create `.env` from `.env.example`:

```bash
cp .env.example .env
```

Set at least:

```env
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
FEEDBACK_USERNAME=@your_username
```

## 3. Start bot

```bash
docker compose up -d --build
```

## 4. Check logs

```bash
docker compose logs -f
```

## 5. Update deployment

```bash
git pull
docker compose up -d --build
```

## Storage

No separate DB server is required for the bot runtime.

Runtime files live under `APP_DATA_DIR` (defaults to `./data`, and to the
Railway volume mount when one is attached — see below):
- `users.db`
- `analysis_cache.db`
- `securities.db` — securities catalog + `volume_records` (record turnover)
- `reports_catalog.db` — report catalog, cached ratios, and the NSBU
  financials cache (`catalog_financials`) shown in the market table
- `org_cache.json`
- `report.html`

All of these resolve under `APP_DATA_DIR`, so a single mounted volume persists
everything across deploys.

## Recommended VPS

Minimum:
- 1 vCPU
- 1-2 GB RAM
- 10+ GB SSD

Comfortable:
- 2 vCPU
- 2-4 GB RAM

## Notes

- The image is prepared for production use on a simple VPS.
- `.env` is not committed to Git.
- The bot runs as a non-root user inside Docker.

## Railway

The repository includes `railway.json`, so Railway can deploy it directly from the root.

Recommended setup:

1. Create a Railway service from this repo.
2. Attach a Volume to the service.
3. Mount the Volume to `/app/data`.
4. Add service variables:

```env
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
FEEDBACK_USERNAME=@your_username
ADMIN_TELEGRAM_ID=123456789
RAILWAY_RUN_UID=0
APP_MODE=bot
```

Optional variables:

```env
FREE_DAILY_LIMIT=3
CACHE_TTL_DAYS=7
APP_DATA_DIR=/app/data
USERS_DB_PATH=users.db
CACHE_DB_PATH=analysis_cache.db
ORG_CACHE_PATH=org_cache.json
OUTPUT_PATH=report.html
```

Notes:
- the app is a Telegram polling worker, so no public domain or HTTP healthcheck is required for the bot service
- without a Volume, SQLite files and caches will not persist between deployments

The web frontend is built with React + Vite during the Docker build and is served from the API service root.

## API

If you want to run the website API as a separate Railway service:

1. Create a second service from the same repo.
2. Set `APP_MODE=api`.
3. Add `OPENAI_API_KEY`, `OPENAI_MODEL=gpt-5.4-mini`, `DATABASE_URL` and `CORS_ORIGINS`.
4. If you want Google login, also add `GOOGLE_REDIRECT_URI`, `PUBLIC_BASE_URL`, `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
5. **Attach a Volume and mount it at `/app/data`** (set `APP_DATA_DIR=/app/data`).
   Without it the securities, report catalog, and NSBU **financials** caches
   reset on every redeploy and must be rebuilt from scratch.

### Market financials cache

The market table's "Financials" columns are served from `catalog_financials`,
filled from NSBU Excel reports. On a fresh backend the cache is empty and
**populates itself progressively**: each visit to the market view triggers a
bounded, lock-guarded background pass that syncs a few companies into the report
catalog and extracts their indicators (no Selenium required — the sync path is
pure HTTP). Full coverage of ~55 companies is reached after a handful of visits.

To warm it up in one shot instead of waiting, call `POST /api/catalog/sync`
once after deploy, then open the market view.

Tunable via env (optional): `FINANCIALS_TTL_DAYS` (default 14),
`FINANCIALS_BATCH` (12), `FINANCIALS_SYNC_BATCH` (8).

Note: keep `ANTHROPIC_API_KEY` for the Telegram bot service; the API service uses OpenAI and Railway Postgres for website users.

## Data pipeline (self-discovering ingestion)

The market/financials data is now driven by the **UZSE feed as the source of
truth** rather than a hardcoded company list:

- `entity_resolver.resolve_all()` discovers every listed security and resolves it
  to an openinfo issuer `org_id` (autofill on the feed name, with
  `company_catalog.COMPANY_CATALOG` as an override and preferred→ordinary
  inheritance). A newly-listed company is picked up automatically — no code change.
- `reports_catalog.sync_all()` (default path) discovers + upserts every ticker,
  then syncs one report set per distinct issuer org. Preferred shares and bonds
  inherit their issuer's financials via `get_all_financials`.
- `data_sources.py` is a **source-adapter registry**: each source is a small
  `Collector` that lands generic *facts* `(entity, dataset, field, period, value,
  source)` in the `facts` table. Adding a source (or a new field on an existing
  source) needs no schema change or core edit — it flows in automatically.
  Surfaced at `GET /api/facts/{ticker}`.
- `GET /api/coverage` reports, per listed security, which datasets are filled
  (price / volume / financials / reports) + resolution status + any sync error —
  so gaps are visible, never silent.

### openinfo reachability (probe before assuming a block)

Openinfo reachability from any deployment can be checked live at any time:

```bash
curl -H "X-Admin-Secret: $ADMIN_API_SECRET" \
  https://YOUR-API-URL/api/admin/openinfo-probe
```

It runs a connectivity matrix against every openinfo endpoint class the
collector uses (autofill, org list, reports, indicators, Excel export, web) from
the deployment's own egress IP. Verified 2026-07: **Railway reaches openinfo
directly — no proxy needed.** All openinfo traffic goes through the shared paced
client (`openinfo_http.py`): min interval `OPENINFO_MIN_INTERVAL_MS` (350),
retries with backoff `OPENINFO_RETRIES` (3), TLS verification on
(`OPENINFO_VERIFY_SSL=0` to opt out). Keep the pacing — an unthrottled bulk sync
is what gets datacenter IPs blocked.

If a host ever does get blocked, set **`OPENINFO_PROXY`** (or the standard
`HTTPS_PROXY`) to any reachable relay and the same code routes through it:

```env
OPENINFO_PROXY=http://user:pass@your-relay:8080
```

### Scheduling the collector

`collector_financials.py` runs the full pipeline in one invocation (financials +
trade-stats + adapter facts + listings) and pushes to the API service via the
admin endpoints (`/api/admin/financials`, `/api/admin/trade-stats`,
`/api/admin/facts`, `/api/admin/listings`, all authenticated with
`ADMIN_API_SECRET`):

```bash
python collector_financials.py                # full pipeline + push
python collector_financials.py --facts-only   # only re-run source adapters
python collector_financials.py --no-facts     # financials + trade-stats only
python collector_financials.py --trades-only  # only the day's quotes/turnover (~2 min)
python collector_financials.py --watch-filings # only the issuers that just filed (~1 min)
```

Schedule it on any host that can reach openinfo:

- **Railway cron (recommended — no local PC involved)**. Create a service from
  this same repo:
  1. New service → same GitHub repo + **branch as the API service** (`railway add`
     defaults to the repo's default branch, whose `railway.json` may not know these
     modes — verify with `railway service source connect --branch <branch>`).
  2. Variables: `APP_MODE=collector`, `ADMIN_API_SECRET` (same value as the API
     service), `FINANCIALS_PUSH_URL=https://YOUR-API-URL`, `TZ=Asia/Tashkent`.
     The start command in the repo-root `railway.json` branches on `APP_MODE`.
  3. Service settings → **Cron schedule** (UTC, regardless of `TZ`) and
     **Restart policy = Never**. The CLI cannot set either; use the dashboard or
     `serviceInstanceUpdate(environmentId, serviceId, input: {cronSchedule})`.
  4. No volume needed — the collector rebuilds its scratch DB each run and
     pushes results to the API service.

  Live schedule (one cron expression per service, so intraday quote refreshes are
  their own services — they run `--trades-only`, ~2 minutes, and cost nothing else):

  | Service | `APP_MODE` | Cron (UTC) | Tashkent | Scope |
  | --- | --- | --- | --- | --- |
  | `collector` | `collector` | `0 3 * * 1-5` | 08:00 Mon–Fri | full pipeline |
  | `quotes-1300` | `quotes` | `0 8 * * 2-6` | 13:00 Tue–Sat | quotes/turnover, mid-session |
  | `quotes-1610` | `quotes` | `10 11 * * 1-6` | 16:10 Mon–Sat | quotes/turnover, after the close |
  | `reports-watch` | `reports-watch` | `0 4-18 * * 1-6` | hourly 09:00–23:00 Mon–Sat | issuers that filed since the last sweep |

  `reports-watch` exists because reporting deadlines do not respect the daily sweep.
  O'zbektelekom filed its half-year report at 11:27 on 2026-07-29, three hours after
  that morning's `collector` run, and the board would otherwise have shown Q1 until
  the next day — a Friday-evening filing until Monday. It reads openinfo's newest-first
  filing feed (one request for the whole market), keeps the issuers we list, reconciles
  only those, and pushes with `mode=replace`, which clears only the tickers in its own
  payload. A quiet hour reconciles nothing and pushes nothing; on a deadline day it
  refreshes a dozen or so tickers in well under a minute. It holds no cursor — a ticker
  is refreshed when its reconciled period outranks the one prod serves, or when the
  same period comes back restated — so a missed run, a duplicate run, or a fresh
  container all converge on the same answer. `REPORTS_WATCH_HOURS` (default 48) sets
  how far back the feed is read; the window only bounds the scan, never correctness.
  Run it by hand with `python reports_watch.py` to see what it would do without pushing.

  Railway's own constraints on any of these: the shortest gap between runs is **5
  minutes**, the expression is standard five-field cron (no seconds, no `@reboot`)
  evaluated in **UTC** regardless of `TZ`, start times drift by a few minutes, and — the
  one that bites — **a run is skipped entirely if the previous one is still going**. All
  four services here exit when their work is done, which is what makes an hourly
  schedule safe; a mode that hangs would silently stop the schedule rather than pile up.

  The days each service skips are the days uzse has nothing to give. `uzse.uz/trade_results/`
  is a rolling window of about **two calendar days** (yesterday + today), and a session's
  executions keep landing in it until ~21:00 Tashkent — so the *complete* day-N session is
  only readable on day N+1, and by day N+2 it is gone. Consequences worth knowing:

  - Sunday every run sees Sat+Sun and gets nothing; Monday 08:00 and 13:00 see Sun+Mon and
    likewise get nothing (Monday's own trades start publishing ~15:00). An empty fetch makes
    `push_trade_stats` return 1, so the run exits non-zero and Railway paints the cron card
    red — a red `collector` on a Monday morning is this, not a broken pipeline. Everything
    else in that run (financials, facts, listings, reconcile) still collects and pushes.
  - Friday's finished session is picked up by **`quotes-1300` on Saturday**. That is the only
    scheduled run that can see it, which is why quotes-1300 runs Tue–Sat rather than Mon–Fri.

  Re-running the same session is safe by design: `bulk_upsert_trade_stats` accepts
  a same-day correction (a later run sees more executions) and refuses anything
  dated earlier, so an intraday snapshot can only be replaced by a fuller one.
- **Windows** — Task Scheduler running `run_collector.bat` (e.g. daily 06:00).
- **Linux/VPS** — cron: `0 6 * * * cd /app && python collector_financials.py`.

OAuth redirect URI to register in Google:

- `https://YOUR-RAILWAY-API-URL/api/auth/oauth/google/callback`

Important:
- `PUBLIC_BASE_URL` must match the same Railway URL exactly, without a trailing slash.
- `GOOGLE_REDIRECT_URI` is the safest option and should match the exact callback URL registered in Google Console.
- In Google Console, use the exact callback URL above as an authorized redirect URI.

API auth flow:

1. `POST /api/auth/register` or `POST /api/auth/login`
2. `GET /api/auth/oauth/google/start`
3. Save the returned `token`
4. Send `Authorization: Bearer <token>` on `POST /api/analyze`

Open the same Railway API URL in a browser to use the frontend at `/`.
