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
