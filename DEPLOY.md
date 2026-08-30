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

### Admin service monitoring and recovery

The administrator's **System → Railway** page (`/admin/railway`) reads the selected
environment, shows current deployment status and recent deployment history, and
loads runtime/build log excerpts on demand. It refreshes every 30 seconds while
the page is visible; it does not provide background notifications or an independent
uptime monitor. The last ten deployments are retained only as long as Railway
retains them. Scheduled jobs are labelled **Scheduled**, not assumed to be running
between executions. A deployment timestamp is not the time of the latest cron run.

Set these variables **on the website API service only**:

```dotenv
ADMIN_RAILWAY_TOKEN=<project token for this production environment>
ADMIN_RAILWAY_PROJECT_ID=4a7a725a-4ab6-46f6-b958-b9ee670d78a6
ADMIN_RAILWAY_ENVIRONMENT_ID=439885d9-1d11-425d-930e-c1ffe90fe793
ADMIN_RAILWAY_RECOVERY_SERVICES=53a76ca7-6a21-4866-b71d-6c33a9fcc678,5771b303-95a1-4eb8-9e7a-526949b92951,6398d729-72ab-4b6e-b429-d1349bdb8874,a5fe649f-b952-43cf-921f-14c12008889e,abb44b45-95e9-46a9-9f59-b2a2eebb3000,bc26feb5-c268-4fd8-8a2d-ba3fda0541ec,f8c44bc3-0626-4414-a08f-64794e855940
```

These IDs are for the existing `terrific-freedom` / `production` project. The recovery
list includes collector, quotes-1610/2130/1300, news-collector, reports-watch and
bank-fx. It deliberately excludes Postgres and the website API. Resolve IDs again
for a different project; never copy this list into another environment blindly.
The project/environment overrides may be omitted when monitoring the API service's
own Railway environment. Create a project token under **Project settings → Tokens**
and scope it to production. Store it as a Railway service variable, never in the
browser, Git, logs, or a chat message. An explicitly configured server-side
`ADMIN_RAILWAY_API_TOKEN` (account/workspace/OAuth token) is supported as an
alternative, but has broader access; prefer the project token. There is no fallback
to a developer's local CLI credentials in the application.

Only signed-in users in `ADMIN_EMAILS` can read this data or recover a service.
The collector `X-Admin-Secret` cannot use these endpoints. With an empty recovery
allowlist the screen is read-only. A crashed deployment offers **Restart**; a failed
build/deployment offers **Redeploy** only if Railway permits it. Both require a
confirmation, a fresh check that the deployment is still the latest failed one,
and a durable admin audit record in the existing Postgres audit table. If the audit
database is unavailable, no mutation is sent. A per-service 60-second cooldown
prevents duplicate actions in the current single-worker API. Before scaling to
multiple workers/replicas, move this cooldown and request reservation into a shared
store. A lost response is reported as unconfirmed, never automatically retried.

The UI distinguishes an accepted recovery request from a verified running service.
Restarting reuses the same deployment; it does not repair code/configuration and
can repeat a collector's writes. Log excerpts are evidence of possible causes,
not a guaranteed diagnosis. Known secret values and common credential formats are
masked, but logs remain sensitive internal data. There is no arbitrary service URL
or GraphQL input accepted from the browser.

If the website API or its authentication database is down, this page is unavailable.
Recover those services in Railway directly. Monitoring/recovery during a complete
website outage requires a separate control service with separate authentication.

Validation before rollout: run the Railway API tests and the admin UI browser tests,
then deploy the API/frontend together. Check `/admin/railway` with an administrator
session, confirm all nine production services appear, and inspect a failed service's
logs. Do not restart production services merely as a smoke test.

API references: [authentication](https://docs.railway.com/integrations/api) and
[deployments/logs/recovery](https://docs.railway.com/integrations/api/manage-deployments).

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
trade-stats + adapter facts + listings + ГЦБ auctions) and pushes to the API
service via the admin endpoints (`/api/admin/financials`, `/api/admin/trade-stats`,
`/api/admin/quotes`, `/api/admin/facts`, `/api/admin/listings`,
`/api/admin/gov-auctions`, all authenticated with `ADMIN_API_SECRET`):

```bash
python collector_financials.py                # full pipeline + push
python collector_financials.py --facts-only   # only re-run source adapters
python collector_financials.py --no-facts     # financials + trade-stats only
python collector_financials.py --trades-only  # only the day's quotes/turnover (~7 min)
python collector_financials.py --trades-only --no-quotes  # …without the per-security quote pass
python collector_financials.py --watch-filings # only the issuers that just filed (~1 min)
python collector_financials.py --gov-auctions-only # only ГЦБ auctions + key rate from cbu.uz (~10 s)
python collector_financials.py --bank-fx-only # only commercial-bank exchange rates (~5 s)
```

The ГЦБ step reads the Central Bank's fiscal-agent page (auction results: tenor,
maturity, placed volume, weighted-average rate) and the key rate from the front
page. Auctions are monthly, the read is cheap, and re-pushing what prod already
holds is a no-op — so it simply rides in the daily `collector` cron.

The bank-fx step reads bankxizmatlari.uz's `/ru/rates/` page — the Central
Bank's own retail-services portal, which already carries every commercial
bank's rate matrix (USD/EUR/RUB x buy/sell x обменный пункт/приложение/банкомат)
as `data-*` attributes on one server-rendered page, plus each bank's own
stated update time. It runs on its **own hourly cron** (`bank-fx` in the table
below), separate from the daily pipeline, because banks move their rates
through the business day rather than once a day like a filing. See
`bank_fx_collector.py` for the parse and why a wide bid/ask spread is flagged
rather than dropped (a thin RUB market can genuinely be that wide; there is no
authoritative "correct" level to check a bank against, so the guard is
peer-relative within the same poll, never a silent deletion).

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
  their own services — they run `--trades-only` and cost nothing else). That run has
  two halves: the execution feed (`uzse.uz/trade_results`, the day's turnover per
  security) and then one `uzse.uz/isu_infos` page per security **the board serves**,
  which is the only publisher of the previous close the exchange measures the day's
  move against — it carries that close forward through sessions with no trades, so
  nothing derived from executions can stand in for it. Every listed security is read,
  not only the ones that traded: the page also states, in its own daily history, the
  date a quiet security last traded and that session's close, change, quantity and
  turnover, so a security nobody has traded in a month is still priced by the
  exchange rather than from a registry row. That history is what makes a finished
  session readable the next morning, after the page's session table has rolled over
  to a day with no trades yet:

  | Service | `APP_MODE` | Cron (UTC) | Tashkent | Scope |
  | --- | --- | --- | --- | --- |
  | `collector` | `collector` | `0 3 * * 1-5` | 08:00 Mon–Fri | full pipeline |
  | `quotes-1300` | `quotes` | `0 8 * * 2-6` | 13:00 Tue–Sat | quotes/turnover, mid-session |
  | `quotes-1610` | `quotes` | `10 11 * * 1-6` | 16:10 Mon–Sat | quotes/turnover, trading over but **not yet published** |
  | `quotes-2130` | `quotes` | `30 16 * * 1-6` | 21:30 Mon–Sat | quotes/turnover, the session as the exchange finally published it |
  | `reports-watch` | `reports-watch` | `0 4-18 * * 1-6` | hourly 09:00–23:00 Mon–Sat | issuers that filed since the last sweep |
  | `bank-fx` | `bank-fx` | `0 3-13 * * *` | hourly 08:00–18:00 daily | commercial-bank exchange rates |
  | `news-collector` | `news-collector` | `10 11 * * *` | 16:10 daily | §3.11 news feed (see NEWS_MODULE.md) |

  **16:10 is not "after the close" in any useful sense, and this table said it was for
  two weeks.** Trading ends around 16:00 — but uzse.uz publishes the executions hours
  later, and until it does, neither the trade feed nor the `isu_infos` page knows the
  day's closing price. Measured on 2026-08-07 from the feed's own two timestamps
  (`me_processing_time`, when the trade matched; `created_at`, when the record
  appeared): 9 000 executions matched between 10:25 and **16:02**, and the same
  records were published between 15:20 and **20:57** — 1 839 of them in one batch at
  20:1x. O'zbektelekom's closing print (UZTL, 12 000, trade #1259) matched at 16:02:00
  and reached the feed at 20:57:16, a lag of 4h55m. At 17:25, when the 16:10 run had
  finished reading pages, uzse still quoted UZTL at 10 800,77 (+8%) — the exchange's
  own daily bulletin closed it at 12 000, **+20%, the day's top gainer**. Four of the
  bulletin's twenty movers were missing from the board and one (TNBNP) had the wrong
  sign. `quotes-2130` exists to read the published session; every run before it is
  reading an unfinished one, which is fine as long as nobody mistakes it for the close.
  The lag varies (20:57 on Fri 07.08, at least 19:19 on Thu 06.08), so 21:30 carries
  deliberate margin.

  `news-collector` shares 16:10 with `quotes-1610` deliberately: after the close the site
  refreshes prices and the feed at the same moment, so a reader is not comparing a fresh
  board against a feed from that morning. (It ran at 07:30 until 2026-07-31.)

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

  **The report catalog is kept current by the API itself, not by a cron service.**
  `catalog_reports` — what /catalog lists and what a company page's «Отчётность» tab
  reads — lives in the API's database, and none of the collectors can write it: they
  have no volume and no `DATABASE_URL`, they POST results over HTTP, and the catalog is
  not among what they post. `collector` does call `rc.sync_all()`, but against its own
  throwaway container scratch, which is why that call never showed up in production.
  The catalog therefore only ever moved when an admin pressed «Синхронизировать всё» —
  last pressed 2026-07-21, while fifty issuers filed their half-year report between 13
  July and 5 August. None of them were on the site.

  So the API runs the watcher in-process (`_catalog_watch_loop`, started at boot after a
  90 s delay, then hourly). Each pass does two bounded things: it reads the same filing
  feed `reports-watch` uses and re-syncs the issuers that filed — usually nobody, one
  openinfo request — and then refreshes the `CATALOG_WATCH_BATCH` (8) issuers that have
  gone longest without a sync. The second half is what makes the schedule survive being
  interrupted: whatever a redeploy cut short is simply the stalest thing an hour later,
  and sixty-six issuers at eight an hour is a working day.

  Once a day the pass runs the FULL sweep instead — the only thing that discovers an
  issuer we have never catalogued and refreshes the audit opinions, whose endpoint has no
  per-issuer filter. Its completion is recorded in `catalog_state`, not inferred: the
  company timestamps cannot answer "has a sweep finished" (the hourly pass keeps the
  newest one minutes old, and the oldest belongs to a preferred ticker the sweep skips on
  purpose), and a sweep a redeploy interrupted must count as not done or the issuers it
  never reached wait another day.

  Knobs: `CATALOG_WATCH` (`0` disables), `CATALOG_WATCH_INTERVAL_MIN` (60),
  `CATALOG_WATCH_WINDOW_HOURS` (12 — wider than the interval so a missed tick heals),
  `CATALOG_WATCH_BATCH` (8), `CATALOG_FULL_SYNC_HOURS` (24). Force a pass and see the
  outcome with `POST /api/admin/catalog-watch?hours=N` (admin secret);
  `POST /api/admin/catalog-sync` still starts a full sweep in the background.

  **Two dialect bugs were hiding under all of this, and they are the reason nothing
  worked even when the sync was called.** `catalog_reports`' upsert asked
  `... AND year IS ?` (SQLite's null-safe equality — a syntax error in PostgreSQL, whose
  `IS` takes only NULL/TRUE/FALSE) and then `pdf_url = COALESCE(excluded.pdf_url, pdf_url)`
  (a bare column PostgreSQL cannot tell from `excluded`). Both raise rather than degrade,
  so every `sync_company` had been failing since the 2026-08-01 cutover — silently, because
  nothing called it. If you add SQL to a sync path, `EXPLAIN` it against the real database
  first: it plans without executing, and it is how these were found.

  It lives in the API and not in a cron service for a second reason: the API is the only
  service that redeploys on a push. `reports-watch` has no deployment trigger and is
  pinned to whatever commit was last deployed by hand.

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
    likewise get nothing (Monday's own trades start publishing ~15:00). **That is no longer a
    failure.** The exchange answering "nothing traded" is an empty session, not a fault: the
    run keeps the stored session, still audits it, and exits 0. A red card now means the feed
    did not answer at all, stopped mid-session (a truncated read is refused rather than
    published short), or the board disagrees with the exchange.
  - The same distinction governs the quote pass. Before the day's first execution every
    security's page reads 0/0/0, which is what the 08:00 run meets every weekday; it takes
    each page's settled history row instead and exits 0. Only a pass where **no page at all**
    could be read is an error.
  - **A run waits for uzse.uz before calling it down.** The site goes away for minutes at a
    time — it was unreachable for over an hour on the evening of 2026-08-04, from Railway as
    well as from a home connection — and giving up on the first miss costs a whole slot,
    which is hours for quotes and a day for the collector. The trade feed and the quote pass
    each retry `UZSE_RETRY_ATTEMPTS` times (default 3) with `UZSE_RETRY_WAIT_SECONDS`
    between them (default 300), and the quote pass re-asks only the pages that could not be
    READ — a page that answered "no session" answered. Worst case a step spends ten minutes
    waiting; the tightest gap in the schedule is 08:00 to 13:00, and Railway skips a run
    whose predecessor is still going, so the bound matters.
  - Friday's finished session is picked up by **`quotes-2130` on Friday evening**, and
    again by `quotes-1300` on Saturday. Until 2026-08-07 the Saturday run was the only one
    that could see it at all, which is why quotes-1300 runs Tue–Sat rather than Mon–Fri.
  - `quotes-1300` audits a session that is *still being traded*: the feed is summed at 13:00
    and the pages are read minutes later, so a page ahead of the feed is the session
    continuing, not a disagreement (on 2026-08-04 that reported 16 false mismatches, all
    settled by 16:10). Mid-session the audit only fails a page that is BEHIND the executions;
    once the day has turned, equality is required again and the 08:00 run enforces it.

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
