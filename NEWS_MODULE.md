# §3.11 News module — DeepSeek-powered collection, classification & search

Editorial-news layer for the UZSE platform: it **collects** Uzbek market news,
**classifies/sorts** each item with DeepSeek (type, tone, impact, issuer links),
and can **actively find** news on demand via a search agent. Built on the
existing collector-push → prod-serve architecture (see `news_ai_module_scope.md`).

## Two layers

**Layer A — collector pipeline (runs itself, scheduled).** `news_collector.py`
pulls the enabled feeds in `news_sources.json`, drops already-seen URLs, and puts each new
item through three gates, cheapest first, before storing it and pushing to
`POST /api/admin/news`. This is the coverage backbone. The model never browses or fetches
here — it only judges what the collector pulled.

| Gate | Cost | What it does |
|---|---|---|
| 0. `prefilter_reject` | free | Regex: drops sport/horoscope/weather/accident/culture items that carry no market signal and name no issuer. Asymmetric — a junk match with any market signal is kept. Dropped items aren't stored, so they're re-filtered free next run. |
| 1. `triage_item` | ~350 input / 20 output tokens | One tiny call: `{"pass": bool, "score": 0-1}`. No issuer universe in the prompt. Fails open (a broken gate passes the item on). Rejections ARE stored, so we never re-pay for them. |
| 2. full classification | ~2,280 input / ~400 output tokens | Class, tone, impact, direction, issuer links, our own `summary_ru` — only for items that survive triage. |

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
| `news_classifier.py` | Layer A — the three gates: `prefilter_reject` (free), `triage_item` (tiny call), full classification (Pydantic-validated); own provider via `NEWS_CLASSIFIER_*` |
| `news_search_backend.py` | Pluggable search backends for Layer B (`TavilyBackend`, `NullBackend`) |
| `news_grok_search.py` | Layer B — Grok-native web + X search (xAI Agent Tools API) |
| `news_agent.py` | Layer B — `find_news` entry point (routes to Grok-native or Tavily) |
| `news_store.py` | `news` / `news_nlp` / `news_entities` upsert + read helpers |
| `news_collector.py` | Orchestrator + CLI (fetch → dedup → classify → store → push) |
| `reports_catalog.py` | Schema for the three news tables (in `_init_schema`) |
| `api.py` | `GET /api/news/feed`, `GET /api/news/ticker/{ticker}`, `POST /api/admin/news`, `POST /api/admin/news/images` |

## Setup

```bash
pip install -r requirements.txt        # adds feedparser, openai
# .env — all on Grok (both layers). This is the configured default:
XAI_API_KEY=xai-...                      # Layer-A classification + Layer-B native search
LLM_BASE_URL=https://api.x.ai/v1
LLM_MODEL=grok-4.3                       # live id; grok-4-fast retired 2026-05-15
GROK_SEARCH_MODEL=grok-4.5               # Layer-B native-search model (optional; defaults to grok-4.5)
NEWS_SEARCH_BACKEND=grok                 # Grok native web+X search (or 'tavily' + TAVILY_API_KEY)
ADMIN_API_SECRET=...                    # required to push to prod (shared with financials)
NEWS_PUSH_URL=https://<your-api>.up.railway.app
# OPTIONAL — move only the high-volume Layer-A path to a cheaper provider. Layer B stays on
# Grok regardless. Worth a few dollars a month; costs you a second provider, key and bill:
#   NEWS_CLASSIFIER_BASE_URL=https://api.deepseek.com
#   NEWS_CLASSIFIER_MODEL=deepseek-v4-flash
#   DEEPSEEK_API_KEY=sk-...
```

## Run

```bash
python news_collector.py --dry-run          # fetch + classify, print, store nothing
python news_collector.py --no-push          # store locally only
python news_collector.py                    # collect, classify, store, push to prod
python news_collector.py --source cbu        # one source
python news_collector.py --backfill-images   # images for stored items (no LLM calls)
python news_collector.py --purge-failed      # drop failed classifications so they retry
python news_agent.py "Hamkorbank dividend"   # try the search agent (needs TAVILY_API_KEY)
```

Serve: `GET /api/news/feed?limit=60&days=30`, `GET /api/news/ticker/HMKB`.

## Card images

The feed cards use the **source's own published image**, in two steps (verified
2026-07-25):

1. **From the feed** — `media:content` / `media:thumbnail`, an `enclosure`, or an
   `<img>` the source put in its own description. Spot.uz, UzDaily and Gazeta.uz ship
   one on every item this way.
2. **From the article's `og:image`** — for sources whose feed carries no image at all
   (Kursiv, Kun.uz), opt in with `"page_image": true` and the collector reads the
   page's `<head>` and takes the preview-image URL the source publishes for link
   unfurls. The response is streamed and cut at `</head>`, and only that URL is kept —
   no article text is fetched or stored, so the legal invariant below is unchanged.
   Paced by the source's `crawl_delay_s`, capped per run by `NEWS_OG_MAX_FETCH`
   (default 40), and run *after* dedup **and** classification — only new, market-relevant
   items cause a page fetch, which for a whole-site feed like kursiv's (~85% off-topic)
   is roughly a sixth of the requests.

Two guards: a site-wide share card is rejected (`social.jpg`, `default.png`, … — cbu.uz
serves one banner for every article, which would repeat down the whole feed), and
`"feed_image": false` opts a source out of images entirely when its ToS bars media
reuse (Gazeta.uz). Items with no usable image get the category-tinted placeholder —
the card design expects that. Images are hotlinked from the source's own CDN, with
`onError` falling back to the placeholder.

`--backfill-images` fills images on items stored before this pass existed: candidates
come from the local DB plus prod's live feed, and updates go through
`POST /api/admin/news/images`, which only writes `news.image_url` where it is empty.
It never goes through `POST /api/admin/news` — a full upsert there would rewrite the
stored classification and drop the item out of the feed.

## Cost & control

**Measured, not assumed** (2026-07-25). The one telemetered run — 41 items, ~110k tokens —
logged `$0.0177` but really cost **`$0.158`**: `est_cost_usd()` was hardcoded to DeepSeek's
`$0.14`/`$0.28` while the module was running on grok-4.3 at `$1.25`/`$2.50`, understating
every run by 8.9x. That stale figure is where the old "~$1–3/month" claim came from. The
estimator now bills at the active model's rates from a per-model table (override with
`LLM_PRICE_IN`/`_OUT`/`_CACHED`) and counts cached input separately.

Where the tokens went in the old single-call design: of 6,248 input chars per item, the
**news item was 205 (3.3%)** — the rest was the system prompt (27%) and the 93-line issuer
universe (68%), re-sent at full price on every call.

What the three gates do to that, at ~140 genuinely-new items/day across the six feeds
(projection from measured prompt sizes; prefilter drop rate 11% and triage pass rate ~25%
measured on today's feeds):

| Setup | Per 100 fetched items | Per month |
|---|---|---|
| old: one grok-4.3 call per item | `$0.386` | **`$16.20`** |
| gates + grok-4.3 (**the default**) | `$0.129` | `$5.43` |
| gates + grok-4.3, prefix cached | `$0.060` | **`$2.51`** |
| gates + deepseek-v4-flash | `$0.014` | `$0.61` |
| gates + deepseek-v4-flash, prefix cached | `$0.005` | `$0.23` |

So the gates alone bring Grok back to the ~$1–3/month this doc originally (wrongly) claimed.
There is no cheap tier inside xAI to lean on instead: grok-code-fast-1 is `$1.00`/`$2.00`,
only 20% under grok-4.3, and no mini tier exists — the 9x gap is a provider gap, not a
model-choice one. Moving Layer A to DeepSeek is therefore optional and worth a few dollars
a month; Layer-B search stays on Grok either way, since server-side web+X search is the
reason Grok was chosen.

Cache hits are the reason the issuer universe moved into the system message: a byte-identical
prefix is billed at `$0.20`/M on grok-4.3 (`$0.0028`/M on DeepSeek) instead of full price.
Every run logs what share of its input the provider served from cache (`cached_input_pct`) —
**that number is unverified against xAI**; if it stays at 0%, the prefix is being re-billed
and the realistic all-Grok figure is the `$5.43` row, not `$2.51`. Note also that xAI doubles
every rate on prompts of 200k+ tokens — ours are ~2.3k, so this never applies here.

Other controls: `--limit` caps items per source per run, `NEWS_MAX_AGE_DAYS` skips stale
items before any call, `NEWS_TRIAGE_FLOOR` sets how eagerly borderline items get the full
pass, and canonicalised URLs (tracking params stripped) stop `utm_*` variants from being
re-classified as new. Layer B is separate: Grok's native search is billed per search call
($5/1k) and the Tavily backend is capped at `NEWS_AGENT_MAX_ITERS` tool calls with each
query logged.

## Legal invariant

We store **headline + our own `summary_ru` + link + metadata only — never the
source's article body.** This keeps aggregation inside Uzbek copyright's
news-of-the-day / press-review allowances. Per-source stance lives in
`news_sources.json` (`legal`): `safe` / `caution` / `avoid_fulltext` (e.g.
Gazeta.uz bars reproduction — headline+link only). `uzse` requires a browser UA
and a 60 s crawl delay (it blocks AI-labelled bots). Every API response carries a
`disclaimer`: news signals are statistical, not advice or claims of manipulation.

## MVP scope & what's pending

Enabled now: `openinfo_facts`, `cbu`, `uzse`, `kursiv`, `spot`, `kun`, `uzdaily` (covers
taxonomy categories 1–9). Working today: RSS/CBU fetch + classify + store + push + serve +
`search_news`. **Pending adapters** (clearly stubbed, return `[]` with a log):
- **openinfo** — set `OPENINFO_FACTS_ENDPOINT` to the material-facts API path to enable.
- **html** (uzse/daryo sitemap scrape) and **telegram** (t.me mirror) — `fetch_pending`.

Two things that had silently stopped the scheduled runs (both fixed 2026-07-25):
`feedparser` was missing from `requirements-server.txt`, so every RSS source in the
Railway cron image hit the lazy import and returned `[]` — the 6-hourly run "succeeded"
with 0 items; and Kun.uz's feed URL had moved (`/ru/news/rss` now serves the Next.js
HTML page; only `/news/rss` and `/api/rss` return XML). An item whose classification
fails (no key, quota, outage) is now **not stored** — URL dedup would otherwise bury it
as irrelevant permanently; unstored, it is simply retried next run. Rows already buried
that way are cleared with `--purge-failed` (local + prod via
`POST /api/admin/news/purge-failed`), which deletes only rows whose reason is exactly
`classification_failed` — deleting the row *is* the retry, since the feed serves the item
again on the next run.

Deferred to later phases (`news_ai_module_scope.md` §8): the 4 anomaly detectors
(spike / synchrony / media-attack / anomaly → `news_signals`), which need ≥90 days
of collected history for their statistical thresholds.
