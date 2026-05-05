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
- SQLite for local runtime storage
- Docker / Docker Compose for deployment

No external database server is required. Runtime files are stored in `./data`.

## Environment

Create `.env` from `.env.example`:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
FEEDBACK_USERNAME=@your_username
FREE_DAILY_LIMIT=3
CACHE_TTL_DAYS=7
APP_DATA_DIR=./data
USERS_DB_PATH=users.db
CACHE_DB_PATH=analysis_cache.db
ORG_CACHE_PATH=org_cache.json
OUTPUT_PATH=report.html
```

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
