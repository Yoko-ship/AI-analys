# §3.11 News module — DeepSeek-powered collection, classification & search

Editorial-news layer for the UZSE platform: it **collects** Uzbek market news,
**classifies/sorts** each item with DeepSeek (type, tone, impact, issuer links),
and can **actively find** news on demand via a search agent. Built on the
existing collector-push → prod-serve architecture (see `news_ai_module_scope.md`).

## Two layers

**Layer A — collector pipeline (runs itself, scheduled).** `news_collector.py`
pulls the enabled feeds in `news_sources.json`, drops already-seen URLs, sends each
new item through `classify_item` (one DeepSeek JSON call), stores it, and pushes to
`POST /api/admin/news`. This is the coverage backbone. DeepSeek never browses or
fetches here — it only judges what the collector pulled.

**Layer B — `search_news` agent (on demand).** `news_agent.find_news("Kapitalbank")`
gives DeepSeek a `search_news(query, days)` tool backed by a real web-search API
(Tavily). The model chooses its own queries (RU/UZ/EN), reads results, and returns
the market-relevant items it found — which can be fed back through `classify_item`
and stored like any other. Bounded by a hard iteration cap; every query is logged.

## Files

| File | Role |
|---|---|
| `news_sources.json` | Source registry (feed URLs, type, lang, coverage weight, legal flag, enabled) |
| `llm_client.py` | Provider-abstracted DeepSeek client (OpenAI-compatible) — `complete_json`, `run_tool_loop`, retry/backoff, token accounting |
| `news_classifier.py` | Layer A — per-item classification (Pydantic-validated) |
| `news_search_backend.py` | Pluggable search backends for Layer B (`TavilyBackend`, `NullBackend`) |
| `news_agent.py` | Layer B — the `search_news` agentic loop |
| `news_store.py` | `news` / `news_nlp` / `news_entities` upsert + read helpers |
| `news_collector.py` | Orchestrator + CLI (fetch → dedup → classify → store → push) |
| `reports_catalog.py` | Schema for the three news tables (in `_init_schema`) |
| `api.py` | `GET /api/news/feed`, `GET /api/news/ticker/{ticker}`, `POST /api/admin/news` |

## Setup

```bash
pip install -r requirements.txt        # adds feedparser, openai
# .env:
DEEPSEEK_API_KEY=sk-...                 # required for classification
LLM_MODEL=deepseek-v4-flash             # deepseek-chat/reasoner retire 2026-07-24
TAVILY_API_KEY=tvly-...                 # optional — only for the search_news agent
ADMIN_API_SECRET=...                    # required to push to prod (shared with financials)
NEWS_PUSH_URL=https://<your-api>.up.railway.app
```

## Run

```bash
python news_collector.py --dry-run          # fetch + classify, print, store nothing
python news_collector.py --no-push          # store locally only
python news_collector.py                    # collect, classify, store, push to prod
python news_collector.py --source cbu        # one source
python news_agent.py "Hamkorbank dividend"   # try the search agent (needs TAVILY_API_KEY)
```

Serve: `GET /api/news/feed?limit=60&days=30`, `GET /api/news/ticker/HMKB`.

## Cost & control

DeepSeek V4-Flash (`$0.14`/M in, `$0.28`/M out) ≈ **$1–5/month** at MVP volume;
every run logs `tokens` and `est_cost_usd`. The search agent is capped at
`NEWS_AGENT_MAX_ITERS` tool calls and logs each query. Only the search API adds
cost (Tavily's free tier likely covers the MVP).

## Legal invariant

We store **headline + our own `summary_ru` + link + metadata only — never the
source's article body.** This keeps aggregation inside Uzbek copyright's
news-of-the-day / press-review allowances. Per-source stance lives in
`news_sources.json` (`legal`): `safe` / `caution` / `avoid_fulltext` (e.g.
Gazeta.uz bars reproduction — headline+link only). `uzse` requires a browser UA
and a 60 s crawl delay (it blocks AI-labelled bots). Every API response carries a
`disclaimer`: news signals are statistical, not advice or claims of manipulation.

## MVP scope & what's pending

Enabled now: `openinfo_facts`, `cbu`, `uzse`, `kursiv` (covers taxonomy
categories 1–9). Working today: RSS/CBU fetch + classify + store + push + serve +
`search_news`. **Pending adapters** (clearly stubbed, return `[]` with a log):
- **openinfo** — set `OPENINFO_FACTS_ENDPOINT` to the material-facts API path to enable.
- **html** (uzse/daryo sitemap scrape) and **telegram** (t.me mirror) — `fetch_pending`.

Deferred to later phases (`news_ai_module_scope.md` §8): the 4 anomaly detectors
(spike / synchrony / media-attack / anomaly → `news_signals`), which need ≥90 days
of collected history for their statistical thresholds.
