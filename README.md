# UZ Stock Analyzer Bot

Telegram bot for stock analysis of Uzbek companies.

The bot:
- collects company financial data from `openinfo`
- collects stock liquidity data from `uzse`
- builds a structured investment analysis
- caches completed analyses to reduce token costs

## Stack

- Python 3.12
- `python-telegram-bot`
- Anthropic API
- OpenAI API for the website API
- Railway Postgres for website users/auth
- SQLite for local runtime storage
- Docker / Docker Compose for deployment

No external database server is required. Runtime files are stored in `./data`.

## Environment

Create `.env` from `.env.example`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.4-mini
OPENAI_REASONING_EFFORT=low
FEEDBACK_USERNAME=@your_username
ADMIN_TELEGRAM_ID=123456789
DATABASE_URL=postgresql://user:password@host:5432/database
WEB_SESSION_TTL_DAYS=30
FREE_DAILY_LIMIT=3
CACHE_TTL_DAYS=7
APP_DATA_DIR=./data
USERS_DB_PATH=users.db
CACHE_DB_PATH=analysis_cache.db
ORG_CACHE_PATH=org_cache.json
OUTPUT_PATH=report.html
CORS_ORIGINS=*
```

Notes:
- `APP_DATA_DIR` defaults to `./data` locally
- on Railway, if a Volume is attached, the app can use `RAILWAY_VOLUME_MOUNT_PATH` automatically
- API endpoints can be opened for your website with `CORS_ORIGINS=*` or a comma-separated list of domains
- the Telegram bot still uses Anthropic, while the website API uses `OPENAI_API_KEY`
- website registration/login use `DATABASE_URL` from Railway Postgres

## Local Run

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements-server.txt
python bot.py
```

## Production Run

```bash
cp .env.example .env
docker compose up -d --build
```

Useful commands:

```bash
docker compose logs -f
docker compose restart
docker compose up -d --build
```

## Railway

This project is ready to run on Railway as a persistent worker service.

1. Create a Railway service from this repository.
2. Railway will build it from the root `Dockerfile` and apply `railway.json`.
3. Attach a Volume and mount it to `/app/data`.
4. Add service variables:

```env
TELEGRAM_TOKEN=...
ANTHROPIC_API_KEY=...
FEEDBACK_USERNAME=@your_username
FREE_DAILY_LIMIT=3
CACHE_TTL_DAYS=7
RAILWAY_RUN_UID=0
APP_MODE=bot
```

Optional variables:

```env
ADMIN_TELEGRAM_ID=123456789
APP_DATA_DIR=/app/data
USERS_DB_PATH=users.db
CACHE_DB_PATH=analysis_cache.db
ORG_CACHE_PATH=org_cache.json
OUTPUT_PATH=report.html
```

Important:
- this bot uses Telegram polling, so a public HTTP domain is not required
- without a Volume, SQLite and cache files will be ephemeral
- `RAILWAY_RUN_UID=0` is recommended because Railway mounts Volumes as `root`
- `ADMIN_TELEGRAM_ID` grants admin access automatically after restart

To run the API from the same repo, create a second Railway service and set:

```env
APP_MODE=api
```

Then the service starts `uvicorn api:app --host 0.0.0.0 --port $PORT` automatically.

## API

Run the HTTP API for a website with:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Main endpoints:

```http
GET  /health
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
GET  /api/companies
POST /api/analyze
```

Example request:

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"company":"HMKB","include_html":true}'
```

`POST /api/analyze` requires:

```http
Authorization: Bearer <token>
```

## Server Notes

- external DB is not needed
- all SQLite files and caches live in `./data`
- the Docker image does not install Chrome or Selenium
- the main path uses HTTP APIs; Selenium is only optional fallback in local environments

## GitHub

Before pushing:
- make sure `.env` is not committed
- make sure `data/` is not committed
- rotate secrets if they were ever exposed locally

The repository includes a GitHub Actions workflow for syntax checks and Docker build validation.
