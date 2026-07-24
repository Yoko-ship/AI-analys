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
actively finds news. Two backends (`NEWS_SEARCH_BACKEND`):
- `grok` — **Grok native web + X search** (`news_grok_search.py`, xAI Agent Tools /
  Responses API). xAI runs the whole search loop server-side and returns items with
  citations — no Tavily key, and it reaches X/Twitter. Uses `XAI_API_KEY`.
- `tavily` — provider-agnostic tool loop: the model calls a `search_news(query, days)`
  tool backed by Tavily, bounded by a hard iteration cap with every query logged.
Either way the returned items can be fed back through `classify_item` and stored.

## Files

| File | Role |
|---|---|
| `news_sources.json` | Source registry (feed URLs, type, lang, coverage weight, legal flag, enabled) |
| `llm_client.py` | Provider-abstracted DeepSeek client (OpenAI-compatible) — `complete_json`, `run_tool_loop`, retry/backoff, token accounting |
| `news_classifier.py` | Layer A — per-item classification (Pydantic-validated) |
| `news_search_backend.py` | Pluggable search backends for Layer B (`TavilyBackend`, `NullBackend`) |
| `news_grok_search.py` | Layer B — Grok-native web + X search (xAI Agent Tools API) |
| `news_agent.py` | Layer B — `find_news` entry point (routes to Grok-native or Tavily) |
| `news_store.py` | `news` / `news_nlp` / `news_entities` upsert + read helpers |
| `news_collector.py` | Orchestrator + CLI (fetch → dedup → classify → store → push) |
| `reports_catalog.py` | Schema for the three news tables (in `_init_schema`) |
| `api.py` | `GET /api/news/feed`, `GET /api/news/ticker/{ticker}`, `POST /api/admin/news` |

## Setup

```bash
pip install -r requirements.txt        # adds feedparser, openai
# .env (configured for Grok):
XAI_API_KEY=xai-...                     # classification + Grok native search
LLM_BASE_URL=https://api.x.ai/v1
LLM_MODEL=grok-4.3                       # Layer-A classification (live id; grok-4-fast retired 2026-05-15)
GROK_SEARCH_MODEL=grok-4.5               # Layer-B native-search model (optional; defaults to grok-4.5)
NEWS_SEARCH_BACKEND=grok                 # Grok native web+X search (or 'tavily' + TAVILY_API_KEY)
ADMIN_API_SECRET=...                    # required to push to prod (shared with financials)
NEWS_PUSH_URL=https://<your-api>.up.railway.app
# To use DeepSeek instead: LLM_BASE_URL=https://api.deepseek.com LLM_MODEL=deepseek-v4-flash DEEPSEEK_API_KEY=...
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

Grok 4.3 (`$1.25`/M in, `$2.50`/M out, 1M ctx) ≈ **~$1–3/month** at MVP volume; every
run logs `tokens` and `est_cost_usd`. Provider is a config swap — DeepSeek
(`$0.14`/`$0.28`, ~$1/mo) is cheaper, GPT-5.4-mini (~$8/mo) is stronger on Uzbek.
Grok's native search is billed per search call ($5/1k); the Tavily backend is
capped at `NEWS_AGENT_MAX_ITERS` tool calls with each query logged.

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
