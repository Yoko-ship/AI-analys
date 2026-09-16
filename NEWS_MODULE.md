# §3.11 News module — Codex-powered collection and classification

Editorial-news layer for the UZSE platform: it **collects** Uzbek market news,
**classifies/sorts** each item with subscription-backed Codex (type, tone, impact,
issuer links), and publishes it through the
existing collector-push → prod-serve architecture (see `news_ai_module_scope.md`).

## Collector pipeline

`news_collector.py`
pulls the enabled feeds in `news_sources.json`, drops already-seen URLs, and puts each new
item through three gates, cheapest first, before storing it and pushing to
`POST /api/admin/news`. This is the coverage backbone. The model never browses or fetches
here — it only judges what the collector pulled.

| Gate | Cost | What it does |
|---|---|---|
| 0. `prefilter_reject` | free | Regex: drops sport/horoscope/weather/accident/culture/municipal items that carry no market signal and name no issuer. Asymmetric — a junk match with any market signal is kept. Dropped items aren't stored, so they're re-filtered free next run. |
| 1. `screen_items` | ~1,800 input / ~240 output per **20 items** | Batched triage: `{"pass": bool, "score": 0-1}` per item, no issuer universe in the prompt. Fails open (a broken gate passes items on). Rejections ARE stored, so we never re-pay for them. |
| 2. `classify_items` | ~3,000 input / ~3,800 output per **10 items** | Batched full classification — class, tone, impact, direction, issuer links, our own `summary_ru` — only for triage survivors. |
| 2b. `classify_filings` | ~800 input per **10 filings** | Issuer filings take a compact prompt with **no issuer universe at all**: their ticker and class come from the filing, so the model only rates tone/impact/direction and writes the summary. |

Batching is what makes this cheap: on the 2026-07-25 run the ~2,200-token constant prefix went
out 31 times and was 68% of all input, while the news text itself was 2%. Batch size is
`NEWS_BATCH_SIZE` (10) and `NEWS_TRIAGE_BATCH_SIZE` (20). Every batch reply is mapped back by
the `n` it echoes — never by position — and anything missing, unparseable or failing
validation is retried as a single call, because a mis-attributed verdict is far worse than a
second request. A filing whose rating fails is stored **unrated** rather than lost.

## Files

| File | Role |
|---|---|
| `news_sources.json` | Source registry (feed URLs, type, lang, coverage weight, legal flag, enabled) |
| `codex_client.py` | Hardened `codex exec` adapter with structured output, isolated environment, token accounting, and a second Codex-model fallback |
| `llm_client.py` | Shared usage accounting and classification error type |
| `news_classifier.py` | The three gates: `prefilter_reject` (free), batched triage, and Pydantic-validated full classification |
| `news_lang.py` | Code-only language detection (`detect_lang`, `is_foreign`) — no model, no network |
| `frontend/src/lib/translate.js` | The browser's own on-device translator (Chrome/Edge `Translator`), as a progressive enhancement |
| `news_store.py` | `news` / `news_nlp` / `news_entities` upsert + read helpers |
| `news_collector.py` | Orchestrator + CLI (fetch → dedup → classify → store → push) |
| `reports_catalog.py` | Schema for the three news tables (in `_init_schema`) |
| `api.py` | `GET /api/news/feed`, `GET /api/news/item/{id}`, `GET /api/news/ticker/{ticker}`, `POST /api/admin/news`, `POST /api/admin/news/images`, `POST /api/admin/news/translations` |

## Setup

```bash
pip install -r requirements.txt
NEWS_CODEX_MODEL=gpt-5.6-luna
NEWS_CODEX_REASONING=low
NEWS_CODEX_FALLBACK_MODEL=gpt-5.6-terra
NEWS_CODEX_TIMEOUT=180
# CODEX_HOME points to private persistent storage containing auth.json.
ADMIN_API_SECRET=...                    # required to push to prod (shared with financials)
NEWS_PUSH_URL=https://<your-api>.up.railway.app
```

## Run

```bash
python news_collector.py --dry-run          # fetch + classify, print, store nothing
python news_collector.py --no-push          # store locally only
python news_collector.py                    # collect, classify, store, push to prod
python news_collector.py --source cbu        # one source
python news_collector.py --backfill-images   # images for stored items (no LLM calls)
python news_collector.py --purge-failed      # drop failed classifications so they retry
```

Serve: `GET /api/news/feed?limit=60&days=30`, `GET /api/news/item/106`, `GET /api/news/ticker/HMKB`.

`type` takes a classifier class, a comma-separated list, or one of the two reading groups the
section offers — `economy` (market + regulatory) and `corporate` (corporate_event +
financial_report), which partition all four classes so nothing is unreachable from both tabs.
**A corporate request is served from the disclosure sources alone** (`type: "openinfo"` in the
registry — the issuers' own filings; customer, 2026-08-11): a paper's write-up of a filing is
a retelling that arrives later, names the company loosely and puts a second card under one
fact, while the filing is the record and names its issuer in the very field the Акции/Облигации
split reads. The narrowing is written per *class*, not as a flat `AND` over the query, so a
mixed request still gets its economy half from every source and `type` unset — the «Все» tab —
stays the mixed feed it says it is. Measured on the live feed the day it went in: 82 corporate
items over 60 days, 47 of them filings.

## Ranking & noise control (the read path)

The page promises news *sorted by likely price impact*, so `get_news_feed` ranks rather than
just ordering by date. Three stages, all in one place so every consumer gets them:

1. **Noise floor** — items the classifier passed as relevant but scored below
   `NEWS_MIN_RELEVANCE` (default `0.3`) are skipped. Measured on real rows: genuinely
   relevant items score 0.60–0.85 and rejected ones 0.00–0.10, so the floor sits in an empty
   band. **Issuer filings are exempt** — a disclosure is news because the issuer filed it,
   whatever score a model puts on "change in the list of affiliated persons".
2. **Rank** — `rank_score()` = `0.38·impact + 0.27·relevance + 0.15·source authority +
   0.12·class + 0.08·names-an-issuer`, decayed by age with a 36 h half-life
   (`NEWS_RANK_HALF_LIFE_H`). Deterministic and pure, so an ordering can be explained and
   tested. Each item carries its `rank` in the API response.
3. **Cross-source de-duplication** — the same story from several outlets collapses to the
   best-ranked copy, only within `NEWS_DEDUP_WINDOW_H` (72 h), because identical wording
   months apart is a recurring story, not a duplicate. Similarity is the higher of two
   Jaccard overlaps: significant **title** words (the copied headline) and significant
   `summary_ru` words — the summaries are all our own Russian text from one classifier, so
   they also match a story RETOLD under a rewritten headline or arriving in English/Uzbek,
   which a title comparison can never see. At `NEWS_DEDUP_SIMILARITY` (default `0.55`) the
   match stands alone; in the band `NEWS_DEDUP_BAND`..threshold (default `0.40`..) it
   additionally needs a shared **figure** (integer part of any number in title+summary),
   because there a rewritten retelling and two same-template stories («Узбекистан и X
   обсудили проекты») overlap identically — measured 2026-08-11, what separates them is
   that two tellings of one fact quote the same number and two different stories never do.
   **Issuer disclosures are exempt on both sides**: the same issuer files «Сделка с
   аффилированным лицом» week after week — identical titles, distinct statutory facts, and
   merging them would silently drop a real disclosure.

Ranking runs over a window three times wider than `limit`, so a strong item just outside
today's newest N can still surface. `?order=recent` returns the plain newest-first list —
that is what the sidebar's "latest" panel uses, since the main column is no longer
chronological.

Set `NEWS_MIN_RELEVANCE=0`, `NEWS_DEDUP_SIMILARITY=0` or `NEWS_RANK_HALF_LIFE_H=0` to switch
any stage off without a code change.

## Keeping a Russian-first feed Russian (no model, no translation service)

The feed is Russian-first, but the sources are not. Three layers, cheapest first, and **none
of them calls a model or a translation API** — the whole path stays free.

1. **Read the publisher's own Russian edition where one exists.** The best translation of a
   kun.uz story is kun.uz's. Its Russian feed is `https://kun.uz/api/rss?lang=ru` — the
   language is a *query param*, not a path, which is why `/ru/news/rss` (an HTML page,
   0 entries for feedparser) made this look impossible on 2026-07-25. Same 16 stories,
   Russian titles, `/ru/` links. That removed the only Uzbek source in the registry. Every
   other enabled source is already Russian except Moody's, Fitch and The Diplomat, which
   publish in English and nothing else.
2. **Detect the language per item, not per source** (`news_lang.detect_lang`). `news.lang`
   used to be the source's *declared first* language from `news_sources.json` — a constant,
   so every kun.uz item was stamped `uz` whether it was or not, and a stray English release
   on cbu.uz's Russian listing was stamped `ru`. Detection is code only: script first
   (Cyrillic vs Latin, with Uzbek Cyrillic told from Russian by ў/қ/ғ/ҳ), then function words
   and the oʻ/gʻ apostrophe letters inside Latin. The collector stamps it at fetch time and
   the read path re-derives it, so rows written before this existed are corrected too.
   Deliberately asymmetric in two places, both documented in the module docstring: a quarter
   Cyrillic is enough to call a headline Russian (real ones carry Latin brand names), and an
   undecidable Latin headline is called English, not Uzbek.
3. **Promote `summary_ru` to the headline for what is left.** For a foreign-language item the
   read path returns `title_ru` — the one-sentence Russian summary the classifier *already*
   wrote when the item was collected, which until now sat as small print under an English
   headline. No new call, no new dependency, and it is our own text. On the Russian UI the
   card prints it as the headline and demotes the original to an `EN`-badged attribution
   line; on the English and Uzbek UI the original stays, since swapping in Russian there
   would trade one foreign headline for another.

4. **Offer the browser's own translator for the rest** (`frontend/src/lib/translate.js`).
   Chrome and Edge 138+ expose a `Translator` global whose model runs *on the device*: free
   at any volume, no key, no bill, and the headline never leaves the machine. Strictly a
   progressive enhancement — Safari, Firefox and everything on iOS have no such API and keep
   the summary from step 3, so a card is never blank. A translated headline outranks the
   summary (a headline is a headline; a summary is a sentence about the story) and the
   summary drops back to being the dek. Anything translated this way is labelled
   *«перевод браузера»* so a machine rendering is never mistaken for the publisher's words.

   The automatic pass only ever uses a language pack that is **already installed**. When one
   is merely `downloadable` the story page offers an opt-in button — downloading a pack is a
   real cost and Chrome requires a user gesture for it — and the consent is remembered in
   `localStorage`.

### Serving the feed in all three UI languages

The site is served in ru / en / uz, but every summary we stored was Russian, so the English
and Uzbek versions showed a Russian feed with English chrome around it. Fixed at the source
of the text rather than at the edge:

* **The classifier writes all three summaries in the call it already makes.** `summary_ru`,
  `summary_en` and `summary_uz` come back from one request — no second call, no translation
  provider or API key. The same applies to the compact filing prompt.
* **The read path ships one headline per language.** `title_ru` / `title_en` / `title_uz` are
  each non-null only when the item's own headline is in a *different* language from that
  reader's — so a Russian headline is promoted-over on the English site exactly as an English
  one is on the Russian site. One cached response serves all three; there is no `?lang=`.
* **Missing translations fall back to Russian, never to blank.** Rows collected before the
  columns existed have only `summary_ru`; a reader gets the wrong language, which is
  recoverable, instead of an empty card, which is not.

**Why not the browser here.** The on-device translator carries the Russian site (see the
step-4 note above), but it cannot carry the Uzbek one: checked against real Chrome on
2026-07-29, `ru→uz`, `uz→ru` and `en→uz` all report **`unavailable`** — only `ru↔en` is
offered. Uzbek has no browser-side route at all, so the text has to exist on the server.

**Older rows:** `python news_collector.py --backfill-translations` fills `summary_en` /
`summary_uz` where they are empty, using a translation-only prompt (no issuer universe, no
re-classification). It pushes to `POST /api/admin/news/translations`, not to
`/api/admin/news`, for the same reason as the image and snippet routes — a full upsert would
rewrite the item's classification from a partial record and drop it out of the feed. Only
empty columns are written, so it can never overwrite what the classifier itself produced and
a re-run after a failed push costs nothing.

### Which sources have a Russian edition (audited 2026-07-29)

| Source | Russian edition | Note |
|---|---|---|
| `openinfo_facts` | ✅ native | filings are filed in Russian |
| `cbu` | ✅ `/ru/press_center/news/` | occasionally posts an English release on the Russian listing — caught per item, not per source |
| `cbu_policy` | ✅ `/ru/monetary-policy/publications/press-releases/` | rate decisions, Russian-only listing |
| `cbu_releases` | ✅ `/ru/press_center/releases/` | same caveat as `cbu` |
| `cbu_finstab` | ✅ `/ru/financial-stability/press-releases/` | Russian-only listing |
| `kursiv` | ✅ Russian-only feed | off the site since 2026-08-11 (`hidden: true`) — see *Taking a source off the site* |
| `spot` | ✅ `/rss/` → `/ru/rss/` | |
| `kun` | ✅ **fixed** `/api/rss?lang=ru` | was the only Uzbek source |
| `uzdaily` | ✅ `/rss` is Russian | host not reachable from every network; all stored rows detect `ru` |
| `napp` | ✅ `/ru/…` | Russian titles, Uzbek slugs |
| `uzse` | — | produces **nothing**: `type: "html"` maps to the `fetch_pending` stub, and its sitemap is 68 static pages with no articles. `?locale=ru` exists if it is ever implemented |
| `moodys` | ❌ none | `/ru/ratingsnewsmap.xml`, the `/ru/global/rss` research path and `ratings.moodys.com/ru` all return the English SPA shell |
| `fitch` | ❌ none | `/ru` and `/site/ru` both serve `lang="en"` |
| `thediplomat` | ❌ none | `/ru/` → 403; English-language publication |

So three sources are English with no alternative, all low volume (Moody's and Fitch roughly
one item a week each, The Diplomat about ten per eighteen days).

### Why machine translation is allowed for some of those and not others

Measured 2026-07-29 on a real MT engine, with the exact strings we store:

| In | Out | |
|---|---|---|
| `Central Asia Weighs Its Options as Great Power Competition Intensifies` | «Центральная Азия взвешивает свои варианты, поскольку конкуренция великих держав усиливается» | ✅ clean |
| `Uzbekistan Signs Railway Deal With China and Kyrgyzstan` | «Узбекистан подписал железнодорожную сделку с Китаем и Кыргызстаном» | ✅ clean |
| `fitch affirms uzbekistan at bb outlook stable` | «fitch подтвердило **прогноз** по Узбекистану на уровне bb стабильный» | ❌ Fitch affirmed the **rating**; the stable outlook is a separate fact |
| `Moodys Ratings affirms Zeda Limiteds Ba3 rating outlook stable` | «подтвердило **стабильный прогноз по рейтингу** Ba3» | ❌ same collapse |
| `fitch downgrades garland tx idr to aa rates 75mm gos aa outlook stable` | «…до aa **rates 75mm gos aa** прогноз стабильный» | ❌ untranslated remainder |

The rule is therefore **not** "don't translate English" but *"don't translate a headline the
publisher never wrote"*. Moody's and Fitch reach us through `title_from: "slug"`, and a URL
slug has already lost the case, the punctuation and — critically — the rating notch, since
`+` and `-` do not survive one. MT does not degrade gracefully on that input; it produces
confident Russian that states the wrong fact.

`news_store._SLUG_TITLE_SOURCES` holds those source ids and the read path publishes
`translatable: false` for them, so the decision is made **once on the server** rather than
being re-litigated by every client. The same reasoning rules out a phrase-table translation
of those headlines: a template would print «BB» where the action said "BB-".

Side effect worth knowing: cross-source de-duplication now works for kun.uz. An Uzbek title
could never Jaccard-match the same story's Russian title elsewhere in the feed; a Russian one
can.

## The story page (`/news/{id}`)

A card opens the story **on our own site**, not at the outlet: `/news/{id}` is a real route
(deep-linkable, back/forward works, the SPA fallback in `api.py` serves it), backed by
`GET /api/news/item/{id}` → `news_store.get_news_item` + `get_related_news`.

**It costs nothing per view.** The page is a plain SQLite read of the row the collector
already wrote — headline, our own `summary_ru`, the stored tone / impact / direction /
relevance, the issuers it names, related stories by shared ticker then by class. No model
is called on this path, so opening an article can never move the LLM bill; the §3.11 budget
still depends only on how many *new* items the collector classifies.

**Depth comes from our own data, not from the publisher's text.** Measured 2026-07-25 across
12 live articles, a page's `og:description` is the *same* blurb the feed already gives us —
identical on uzdaily, shorter on spot, absent on kun — so fetching the article on open would
return the text already on screen. The only longer text anywhere is the body itself (kursiv
ships ~2000 chars in `content:encoded`), which is the one thing the invariant rules out.
So the story page adds what a news site cannot: for every issuer it names, its quote
(`/api/securities`, already loaded app-wide, so a cold deep link has prices too), the 90-day
tone of its coverage and its other recent headlines (`/api/news/ticker/{t}`). Issuers with a
known quote sort first, so a story naming four bond series still leads with the bank.

The legal invariant is unchanged: the source's article body is never stored, so it is never
served here. The page shows our own summary and attributes the outlet with an explicit
"read at the source" link out — the one and only off-site jump. `reason` stays server-side:
the classifier prompt declares it an internal note, so `get_news_item` does not return it.

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

## Usage & control

Classification runs through the linked Codex subscription. Operational logs report input,
cached-input, output, call count, and the actual Codex model used; estimated API spend is
always zero because there is no API fallback.

Where the tokens went in the old single-call design: of 6,248 input chars per item, the
**news item was 205 (3.3%)** — the rest was the system prompt (27%) and the 93-line issuer
universe (68%), re-sent at full price on every call.

**First measured run (2026-07-25, before batching):** 77 fetched, 70 new, 5 prefiltered, 34
stopped at triage, 19 relevant, 0 failures → 90 calls, 113,745 tokens, 25%
of input served from cache. Anatomy: fresh input 78% of the bill, output 28%, cached input 4%
— and the constant prefix alone was 68,231 tokens (68% of all input) because it went out once
per item. Batching that same workload gives **6 calls instead of 90**, 12k input instead of
100k, and ~70% less cost; the paid-triage titles from that run also fed 18 new free prefilter
patterns. Two projections that missed: triage survival is ~42%, not the 25% assumed, and
cache came back at 25%, not 90% — after batching the prefix goes out ~6 times, so caching
stops being the lever it looked like.

The issuer universe remains in the system message as a byte-identical prefix across calls,
which improves reuse and keeps prompts stable. Every run logs the cached-input share.

Other controls: `--limit` caps items per source per run and a source can cap itself tighter
with `"max_items"` (kursiv is at 15), `NEWS_MAX_AGE_DAYS` skips stale items before any call,
`NEWS_TRIAGE_FLOOR` sets how eagerly borderline items get the full pass, and canonicalised
URLs (tracking params stripped) stop `utm_*` variants from being re-classified as new.

## Duplicate prevention

Six layers, because a duplicate costs twice — once in LLM spend, once as a repeated card:

| Where | Mechanism |
|---|---|
| Fetch | Tracking params stripped (`utm_*`, `fbclid`, …) so `?utm_campaign=x` is not a new article |
| Within a run | Items collapsed on their **canonical** URL, so two sources (or two pages of one source) that surface the same link are classified once |
| Before classifying | `existing_urls` against the local history **and** `POST /api/admin/news/known` against prod |
| openinfo | Same issuer + fact type + day grouped into one card (8 affiliate-deal notices in an hour → 1) |
| Storage | `news.url` is UNIQUE with `ON CONFLICT DO UPDATE` — the same URL can never become two rows |
| Read (feed) | Same story from several outlets merged by title overlap, best-ranked copy kept |

The prod check is what makes a **scheduled** run safe. The collector's memory of what it has
already classified normally lives in its own SQLite file; a cron container starts without one,
so local-only dedup would re-classify every item on every run — prod's UNIQUE(url) would keep
the rows correct while the LLM bill quietly doubled. The check fails soft: if prod is
unreachable the run continues on local history and logs it, rather than aborting or
re-classifying blindly.

Not deduplicated, on purpose: recurring stories with distinct headlines (a daily FX report is
new each day), and the same story stored from two outlets — both rows are kept, the feed just
shows one.

## Schedule vs feed depth

The `news-collector` service exists (created 2026-07-25 with
`railway add --service news-collector --repo Yoko-ship/AI-analys --branch API`, secrets passed
as `${{AI-analys.VAR}}` references). It uses the **default `railway.json`**, whose start
command branches on `APP_MODE=news-collector`.

> **The dashboard field is the source of truth for the schedule.** `railway.news.json`'s
> `cronSchedule` only applies if a service's custom config path is pointed at it, which is
> itself a dashboard setting — so the file below documents intent, nothing more. Set the real
> schedule at **Service → Settings → Cron Schedule**. No CLI route exists: `railway add` has
> no cron flag, `railway service` has no settings subcommand, `railway variables` cannot set
> it, and `railway config pull` needs the `railway` npm SDK whose IaC loader is broken on
> Windows (it mis-parses its own `index.cjs?namespace=…` module path). The Railway MCP server
> (`railway setup agent -y`) is the remaining option for direct agent control.

Live schedule: **`10 11 * * *` = 11:10 UTC = 16:10 Tashkent**, once daily (Railway evaluates
cron in UTC; the container's `TZ=Asia/Tashkent` does not change that). Set 2026-07-31, moved
there from 02:30 UTC / 07:30 local so the feed refreshes alongside the post-close quotes run
(`quotes-1610`, same 16:10) — a reader who opens the site after the session sees one moment
of data, prices and news together, rather than a board from 16:10 next to a feed from 07:30.

What the earlier slot bought, and what moving it costs: openinfo filings cluster through the
afternoon and evening (14:00–21:12 local in the sampled window), so a 07:30 run always saw a
complete filing day, while a 16:10 run leaves the evening's filings for the next day's run —
up to ~24h later on the feed page. It is a phase change, not a cadence change: the run is
still once a day, so the depth table below is unchanged, and material facts still reach the
board within the hour through `reports-watch`, which is what the news feed's timing was never
responsible for.

**The cadence is bounded by how deep each feed is** — an item that falls off a feed between
runs is lost for good. Measured 2026-07-25:

| Source | Items in feed | Time span | Publishes | Kept at 1 run/day |
|---|---|---|---|---|
| kursiv | 100 | ~79h | ~14–23/day | all (cap raised 15 → 25) |
| spot | 20 | ~32h | ~9/day | all |
| uzdaily | 20 | ~18h | ~27/day | ~20 of 27 |
| **kun** | **15** | **~8h** | **~45/day** | **15 of 45** |
| cbu | **10** (listing) | months | ~2–5/month | all |
| cbu_policy | 10 (listing) | ~20 months | ~1 rate decision/6–8 weeks | all |
| cbu_releases | 10 (listing) | ~3 weeks | ~2–3/week | all |
| cbu_finstab | 10 (listing) | ~years | a few/year | all |
| moodys | 183 global → **filtered** | ~1 day | ~1 Uzbek hit/1–2 weeks | all that match |
| fitch | 502 global → **filtered** | ~5 business days | ~1 Uzbek hit/1–2 weeks | all that match |
| spglobal | 218 global → **filtered** | ~1–2 days | ~1 Uzbek hit/1–2 weeks | all that match |
| napp | 12 (listing) | ~13 days | ~0.5/day | all |
| thediplomat | 96 (Central Asia) | ~96 days | ~1/day | all (cap 15) |
| trend | 25 (Central Asia) | ~10.5h | ~27 Uzbek/day | ~25 of 27 (cap 25) |
| timesca | 10 (Uzbekistan) | ~50h | ~5/day | all (cap 10) |
| uza | 20 (English) | ~30h | ~16/day | ~12 (cap 12) |
| openinfo | paged | months | ~7/day (ours) | all |

Once daily costs the two highest-volume general feeds: Kun.uz truncates at 15 items covering
~8 hours, so a 24-hour gap keeps a third of its output, and UzDaily loses a few. Fetching more
is not possible — those feeds simply end. Kun is also the lowest-relevance source, so in
*relevant* items the loss is smaller than it looks. `30 2,14 * * *` (twice daily) or
`30 2,10,18 * * *` (every 8h) recover that coverage while consuming more subscription usage.

## The English half of the feed (2026-08-07)

The customer asked for roughly **half the page to be English-language / international news**,
and the measurement that prompted it was blunt: of 200 cards live that day, **4** came from an
international source. Two separate causes, both addressed.

**There was almost no English supply.** The rating agencies publish a handful of Uzbek items a
*month* between them. So three English sources with real daily volume were added, each probed
first (feed shape, dates, images, robots.txt):

| id | feed | Uzbek volume | why this feed |
|---|---|---|---|
| `trend` | `en.trend.az/feeds/casia.rss` | **12 of 25 entries in 10.5h** | the Central Asia feed, not the agency-wide one; company results, MoUs, trade and investment. Ships **no description at all**, so the classifier judges the headline — as it already does for the agencies. `feed_image: false`: an agency's photos are its product. |
| `timesca` | `timesca.com/category/news/uzbekistan/feed/` | ~5/day | a dedicated **Uzbekistan category** feed; the site-wide one is regional and would spend gates on Kyrgyz elections. Ships `content:encoded` — we store the teaser only. |
| `uza` | `uza.uz/en/rss` | ~16/day | the state agency's **English** edition (the registry entry used to point at `/ru/rss` and was disabled). Protocol-heavy, so capped at 12 and left facing the full relevance gate. |

`intellinews` was the obvious fourth and is **refused, not deferred**: it answers 200, and its
`robots.txt` disallows `/feed`. It is in the registry disabled with that evidence.

**And the ranking was giving the page away.** `rank_score` rewards naming a ticker, which an
international story rarely does, so even with supply the local firehose would bury it. The feed
read now ranks the two streams separately and interleaves them
(`_balance_origins`, `NEWS_INTERNATIONAL_SHARE`, default `0.5`; `0` restores the plain order).
Membership comes from `origin: "international"` in the registry, so it is a one-word edit per
source, not a hard-coded list. What the balance never does: reorder within a side, hold a slot
open, or shorten the page — a quiet week for the agencies just means the local side fills it.

**The relevance rule had to say what it always meant.** The Diplomat's Uzbekistan items were
reaching the full classifier after `skip_triage_filter` and *still* dying: «Uzbekistan's Nuclear
Power Plant Project Advances» → "No link to listed issuers or sectors", the tax-free crypto
zone → "No link to listed issuers", the China–Kyrgyzstan–Uzbekistan railway → "No direct impact
on listed tickers". The prompt already allowed a *sector* link; the model was reading it as
requiring a named issuer. Rule 1 now says so explicitly — a state programme, law, tariff,
licence or large investment touching a sector on the board is relevant **without** a named
issuer, and names the sectors — while listing what stays out: sport, culture, crime, weather,
human interest, and protocol diplomacy carrying no economic decision (which is what keeps UzA's
handshake wire off the page).

## The story page's long read (2026-08-07)

Opening a story used to give the reader the one sentence the card already showed. The
customer made the point with a UzA item: the page behind it carries the ministry, the
ambassador, the fertiliser exports and the seed-production projects — five paragraphs we had
nowhere.

So the collector now runs a **detail pass** (`enrich_details` → `backfill_details`, and
`--backfill-details` by hand). For each candidate it opens the source's article page **once**,
extracts the prose, and asks the model to retell it: `news_classifier.write_detail` writes
3-5 paragraphs in **all three UI languages**, stored as `news.detail_ru / detail_en /
detail_uz` and served only by `GET /api/news/item/{id}`.

**The article text is never stored.** It exists for the duration of one call; what reaches the
database is our own account of it. That is the same invariant the module has always run on,
and the page now says so under the text (`detailNote`, in place of the old
"краткое изложение" line) rather than implying the paragraphs are the source's.

**The extraction is deliberately dumb and allowed to fail.** It takes the paragraphs of the
likeliest container (`article`, `main`, `.entry-content`, …) and drops everything under 80
characters — measured: the shortest genuine paragraph across our sources is 118, while
datelines, photo credits, "read also" rails and newsletter pitches all fall below. When the
guess is wrong the result is navigation noise, and the prompt's instruction for "this is not
an article" is empty strings, never an invented one. Verified live across every enabled
source: uzdaily 11 paragraphs, spot 11, timesca 11, thediplomat 17, kursiv 8, kun 4, uza 3.

**Who is skipped, and why:**
- `content: "none"` — the rating agencies ship a headline; their pages are SPA shells.
- `type: "openinfo"` — a filing has no page of its own (every per-fact URL 404s), and those
  items already carry the disclosure's own figures.
- `article_body: false` — **trend.az**, whose page is 165 KB of shell around «Get access to all
  paid news on Trend — just $1». Without the flag it would spend the daily cap forever on
  pages that can never yield a body.

**Cost is bounded like the image retry:** `NEWS_DETAIL_CAP` (default 12) articles per run,
prod-feed order first, only items with no long read yet. The feed itself carries a
`has_detail` **flag**, not the text — three languages of prose over 200 items would be a
megabyte the list never renders.

### The picture in the feed is a thumbnail (2026-08-08)

Reported as a blurry photo on a story page; it was **320×213 stretched across a ~950px
column** — the derivative uza.uz puts in its RSS. The full-size file is the same URL with
`_small` → `_normal` (1024×682). spot.uz is the same shape: `_b` is 680×453, `_l` is 1200×800,
`.webp` included. Measured over every image in the live feed, both rewrites hold; the other
sources were already fine (kursiv 1200×630, timesca 1024×682, uzdaily up to 1280×853) and
The Diplomat's equivalent rewrite **404s**, so it has none.

The rule is `image_upgrade: {from, to}` per source, applied at collection time
(`upgrade_images`) and retroactively by `--upgrade-images` (99 of 282 stored rows on the first
sweep). It is never trusted: the candidate must answer **200 with an `image/*` content-type**
before it replaces anything, and the rules are written so they cannot fire twice — a re-run is
a no-op. `set_image_urls(..., replace=True)` (and `{"replace": true}` on the images endpoint)
is the only path that overwrites an image already on a row; the ordinary backfill still cannot.

And the page stops magnifying: an image whose `naturalWidth` is under 760 gets
`.led-art-figure.is-small` and is shown at its own scale. Some sources simply have no larger
file, and 320px across 950 reads as broken whatever the URL says.

## Legal invariant

We store **headline + our own `summary_ru` + link + metadata only — never the
source's article body.** This keeps aggregation inside Uzbek copyright's
news-of-the-day / press-review allowances. Per-source stance lives in
`news_sources.json` (`legal`): `safe` / `caution` / `avoid_fulltext` (e.g.
Gazeta.uz bars reproduction — headline+link only). `uzse` requires a browser UA
and a 60 s crawl delay (it blocks AI-labelled bots). Every API response carries a
`disclaimer`: news signals are statistical, not advice or claims of manipulation.

## Taking a source off the site

Two registry flags, one effect — `paywall: true` (the article page asks the reader for money,
so the card's only action is one the reader cannot take: trend.az, 2026-08-09) and
`hidden: true` (the customer dropped the outlet, with nothing wrong with its pages: kursiv,
2026-08-11). Both also get `enabled: false`.

The suppression is at **read time**, in `news_store.hidden_source_ids()`: the feed filters in
SQL (a dropped row must not eat a slot out of the rank window), and the story page, the
related rail, an issuer's news and the tone aggregate go through `drop_hidden()`. The stored
rows are never deleted, so clearing the flag brings the source's history back with it instead
of leaving a month-shaped hole. `load_sources()` skips a flagged source too — collecting what
nobody is shown would spend a classifier call per item — but `--source <id>` still fetches it
by name, which is how you re-check one before bringing it back.

## MVP scope & what's pending

Enabled now: `openinfo_facts`, `cbu`, `cbu_policy`, `cbu_releases`, `cbu_finstab`, `napp`, `moodys`, `fitch`, `spglobal`, `thediplomat`, `timesca`, `uza`, `uzse`, `spot`, `kun`, `uzdaily` (covers
taxonomy categories 1–9). Off the site: `trend` (paywall, 2026-08-09) and `kursiv` (customer's
decision, 2026-08-11) — see *Taking a source off the site*. Working today: RSS / html_list / sitemap / openinfo fetch + classify + store + push + serve +
`search_news`. **Pending adapters** (clearly stubbed, return `[]` with a log):
- **html** (uzse/daryo sitemap scrape) and **telegram** (t.me mirror) — `fetch_pending`.

**html_list** (`fetch_html_list`) reads a server-rendered listing page as a feed, with the
selectors in `news_sources.json` (`list_selectors`: `item` / `title` / `date` / `image` /
`text`) so another site is configuration, not code. Added for **cbu.uz**, whose RSS is a
stub: verified 2026-07-25 that all three language variants return a **single** entry, so a
second press release published between runs was lost for good, while the press-centre page
lists ten. One GET per run; only link, headline, date and the article's own thumbnail are
read — no article page is opened, so the legal invariant is untouched.

**cbu.uz is FOUR listings, not one** (2026-08-10). The press-centre «Новости» page the
original `cbu` source reads turned out to be nearly dormant — measured that day it held ten
items spanning 28 Apr to 17 Jul 2026, so on most runs nothing of it falls inside the 30-day
window and the central bank was effectively absent from the feed. The bank publishes to
separate sections, and the rate decisions are not among the ones we were reading:

| id | path | what it carries | markup |
|---|---|---|---|
| `cbu` | `/ru/press_center/news/` | general news, sparse | `a.news` |
| `cbu_policy` | `/ru/monetary-policy/publications/press-releases/` | **the policy rate** | `.item.has-date` |
| `cbu_releases` | `/ru/press_center/releases/` | supervision, payments, admin | `a.news` |
| `cbu_finstab` | `/ru/financial-stability/press-releases/` | capital buffer, systemic banks | `.item.has-date` |

The two `/press-releases/` sections use a **different template** from the press centre —
no `a.news` node at all, the headline in `.desc h3 a` and the date in a bare `.item-date`
span — which is why one selector set could never have covered both, and why the gap was
invisible: the `cbu` source was working perfectly on a page that had stopped mattering.
All four are one GET each, no image and no blurb on the `.item.has-date` pair, and readable
article pages throughout (1.5k–3.7k chars measured), so the story-page long read works on
them — none gets `article_body: false`.

The rate decision cross-posts to `cbu_releases` **and** `cbu_policy` under different ids.
Both rows are stored and classified (~8 extra calls a year); the reader sees one card,
because the titles are character-identical and `_dedupe_stories` collapses them at read
time (Jaccard 1.000 vs the 0.55 threshold, verified on the 29 July decision). Dropping
either section would mean betting on which path the bank uses next.

**napp.uz** — the capital-market regulator — uses the same adapter (`.info-in` cards,
Russian titles on `/ru` even though the slugs are Uzbek, real `DD.MM.YYYY` dates, an image on
every card). It is the primary source for the `regulatory` class and it names our issuers
directly: verified 2026-07-25, page one carried Hamkorbank and ASIA ALLIANCE BANK entering the
regulatory sandbox, the approved list of IFIs for bond issuance, and new bonded-warehouse
rules. It has no RSS and no sitemap — every feed path returns the same catch-all HTML — so the
listing page is the only machine-readable route; `robots.txt` is `Disallow:` with an **empty**
value, which permits crawling. It also publishes exam notices and seminars, so unlike `moodys`
it is deliberately **not** exempt from the relevance floor — the classifier sorts it.

### The second rating agency, the regional desk, and two that stay shut (2026-07-28)

**`fitch`** joins `moodys` on the same `sitemap` adapter. Its `/rss/*` paths are dead — both
bounce to the `/redirect/` SPA shell — but `sitemap-research.xml` is live and crawlable
(`robots.txt` disallows only `/page-data/`, `/search`, `/redirect`, `/user-settings`, and we
open no article page, so none of it is touched). It carried 502 URLs when checked, ~100 per
business day, headline in the slug and the date as a `-DD-MM-YYYY` suffix. Fitch does rate this
market — its entity sitemap lists Asaka Bank, and the sovereign and state banks are Fitch-rated
— so the same `url_filter` trick applies: the ~99.8% of global research naming nobody of ours
is dropped before any model call, for one shared request. One new knob was needed:
`slug_date`, because Fitch stamps **every** entry's `<lastmod>` with the sitemap's own
generation time — trusting it would publish a five-day-old rating action as today's news, and
would make the 30-day recency filter a no-op for the handful of 2024–2025 stragglers that sit
in the file. Like `moodys`, `fitch` is exempt from the relevance floor (`news_store.py`):
by the time an item reaches the model, the URL filter has already vouched for it.

**`thediplomat`** is the regional-context desk — reform politics, the China–Kyrgyzstan–Uzbekistan
railway, energy and crypto policy — read from the **Central Asia region feed**, not the
site-wide one: both ship 96 entries, but the site-wide feed is Asia-Pacific (3 mentions of
Uzbekistan against 72) and would spend triage calls on Vietnamese AI law. ~1 item/day over a
96-day window, every entry dated and carrying its own image, teasers of 70–160 characters and
no `content:encoded`, so snippet-only holds by construction. Most items are Kazakh or Kyrgyz,
so it is **not** exempt from the relevance floor. Its `robots.txt` allows `*` everywhere but
`/wp-admin`, while banning AI-labelled crawlers by name (ClaudeBot, GPTBot, anthropic-ai,
CCBot, Google-Extended, Bytespider) and setting `Content-Signal: ai-train=no, use=reference` —
our `DEFAULT_UA` is neutral and must stay that way, we never train on it, and we keep the
headline + link + our own summary only.

**`spglobal` is live since 2026-08-07, and the earlier "no route at all" reading was wrong.**
It was measured with a lone `User-Agent` header. The edge (Akamai) rejects that — ours *and* a
Chrome UA string — but answers **200** to the ordinary browser navigation header set
(`Accept`, `Accept-Language`, `Sec-Fetch-*`, `sec-ch-ua*`, `Upgrade-Insecure-Requests`):
`robots.txt` (9.9 KB), the ratings sitemaps and the ratings-actions page all come back. And
that `robots.txt` **advertises the file we read** — `/ratings/sitemaps/news-sitemap.xml` is one
of its own `Sitemap:` directives, its 118 `Disallow:` rules cover search and identifier-lookup
paths we never touch, and even GPTBot gets a plain `Crawl-delay: 10` rather than a ban. So the
header set is a shape the edge insists on, not a permission being worked around; it lives in
the registry as `headers`, per source, next to that evidence.

What comes back is better than the other two agencies ship: a **Google-news sitemap** (~218
entries the day it was checked) where every entry carries the publisher's own `<news:title>`
and `<news:publication_date>`. No slug to parse and no build-time `lastmod` to overrule. The
`<loc>` is `…/article/-/view/sourceId/101700054` — a number with no words in it — so the gate
here is **`title_filter`**, the same pre-model filter as `url_filter` applied to the only field
that names anybody. A sitemap source must declare one or the other; with neither, `fetch_sitemap`
refuses to fetch rather than send a publisher's global output to the classifier.

**`imf` stays off, and 2026-08-07 established why** — which closes the question the old note
left open ("re-check from the Railway egress, whose IP may not be filtered"). It is not our IP
and not our headers: every `/en/` path answers 403 to `requests` with a bare UA *and* with the
full Chrome header set, while **real Chrome on the same machine and network fetches
`/en/News/RSS?language=eng` at 200 with 56 KB, cookies omitted**. The discriminator is the
TLS/HTTP2 client fingerprint (Akamai bot management), which no header changes and which a
datacenter egress would only make worse. The legacy `/external/` tree is not a way in either:
`/external/rss/feeds.aspx` returns 200 with an **F5 JavaScript challenge** page, not a feed.
And past the wall there is nothing to read anyway — `/en/News/RSS?language=eng` is an HTML
shell titled "RSS" with zero `<item>` elements, and the Uzbekistan country page (405 KB) loads
its document list from a client-side search call, not from `__NEXT_DATA__`. Enabling IMF
therefore needs a browser engine on the collector (Chromium via Playwright) or a
fingerprint-impersonating HTTP client, for about **six Uzbekistan items a year** — deliberately
not built. IMF news about Uzbekistan reaches us second-hand through `uzdaily` and `kursiv`, and
the Layer-B search agent can be pointed at it on demand.

CBU items are **title-only by the publisher**: the listing renders an empty `news__text` and
the article pages carry no `og:description`. That is CBU, not a gap in the adapter — do not
chase a blurb for it. The source now reads the **Russian** edition (`/ru/press_center/news/`),
which matches the RU-first feed; note CBU numbers each language edition separately, so the
one item already stored from the English RSS (`…/en/…/4194168`) is a different URL from its
Russian twin and both will show until the older one leaves the 30-day window.

### What the first live run with both showed (2026-07-29)

The 02:34 UTC run collected from 11 sources. Neither new source put anything on the feed, and
the two reasons are different.

**`fitch` fetched nothing, correctly.** `url filter kept 0 of 502` — the sitemap is a
**~5-business-day window** (that morning: 23–29 July, ~100 entries a day, plus three
2023–2025 stragglers), and no entry in it named one of our issuers. Later the same day Fitch
published `…/research/corporate-finance/jsc-uzbek-metallurgical-plant-29-07-2026` — UZMK, a
listed issuer — which the filter keeps and dates correctly. So the source works; it simply had
nothing to say for a week. Expect that to be normal.

**`thediplomat` fetched 15 and the market gate rejected all 15.** Every item came back
`relevant=false` with a triage score of 0.0–0.3 against the 0.35 floor, was stored as such
(rejections are stored so we never pay to triage the same URL twice), and the feed only serves
`relevant = 1`. That is the gate working: 10 of the 15 were Kazakh, Kyrgyz or Mongolian, and
the rest were politics and society. The two arguable misses — a tax-free crypto mining zone and
the China–Kyrgyzstan–Uzbekistan railway — are policy stories with no issuer in them. This
source is regional *context*, worth roughly one market-relevant Uzbek item a week; it is not a
news feed for the board and it was never exempted from the floor.

**Re-measured 2026-08-07: that reading was too generous to the gate.** Ten days on, the source
had still put **nothing** on the feed — 15 of 15 items in the live window stored as irrelevant,
and among the rejections `Uzbekistan's Nuclear Power Plant Project Advances` (score 0.2, "no
direct link to listed issuers"), the tax-free crypto-mining zone, and the
China–Kyrgyzstan–Uzbekistan railway. A national power-plant programme is not a story the
energy issuers on this board are unaffected by; the gate is reading a 130-character teaser and
answering a question about listed issuers that a teaser cannot answer. Hence
**`skip_triage_filter`**, the per-item form of `skip_triage`: a regex over title + snippet + url,
so the items naming Uzbekistan go straight to the full classification while the Kazakh, Kyrgyz
and Mongolian ones keep facing the cheap gate exactly as before. 5 of 20 items in the live
window match. This is deliberately *not* a floor exemption — The Diplomat is still judged, just
not by the cheapest reader we have.

Two knobs were added off the back of that run, both for the agencies only:

- **`title_case`** — Fitch lower-cases every research slug, so a headline read out of the URL
  arrives as `jsc uzbek metallurgical plant` and would sit among properly cased ones looking
  broken. Opt-in per source, and applied only to an all-lower-case title: Moody's slugs carry
  their own capitals. Acronyms (`JSC`, `IDR`, `ESG`…) are upper-cased, and a rating grade only
  where Fitch writes one — directly after `at` or `to`, the one position where a bare `a` or
  `b` is a grade and not an ordinary word.
- **`skip_triage`** — `moodys` and `fitch` items now go straight to the full classification.
  The `url_filter` kept the URL *because* it names one of our issuers; that is the same fact
  that makes them authoritative on the read path. Putting a snippet-less entity name to a cheap
  "could this plausibly matter?" gate can only lose, and because a triage rejection is stored,
  one wrong verdict would bury a rating action for good. The read-side exemption in
  `news_store._AUTHORITATIVE_SOURCES` was never enough on its own: it waives the *relevance
  floor*, but `get_news_feed` still filters on `relevant = 1`, which a triage rejection sets.
  Cost: one full classification for the handful of items a year that clear the URL filter.

### Rating agencies (`sitemap`)

`fetch_sitemap` reads a publisher's XML sitemap as a feed and — this is the point — applies
`url_filter`, a plain regex over the URL, **before** the prefilter, the triage gate and any
model call. Moody's `ratingsnewsmap.xml` is a rolling window of ~183 *global* rating actions
with the headline in the URL slug; Uzbek issuers are a handful a year in that stream, so the
~99% that names none of ours costs one shared HTTP request and nothing else. A sitemap source
with no `url_filter` refuses to return anything, so this cannot be misconfigured into a bill.
Headline comes from the slug (`title_from`/`slug_strip`, plus `title_case` where the publisher
lower-cases its slugs); no article page is opened. Moody's entries carry no `<lastmod>`, so its
items arrive undated — `_is_recent` keeps undated items, which is correct for a window that
only lists current actions; Fitch stamps a useless one and is dated from the slug instead
(`slug_date`). Both skip the triage gate (`skip_triage`): the URL filter has already
established what a cheap gate would be guessing at.

Verified 2026-07-25 against the live sitemap: 183 URLs in, 0 through the filter (no Uzbek
action that day), 0 classified. The filter was checked against real Moody's Uzbek URLs —
Alokabank, Agrobank and the sovereign banking outlook all match, Zeda and Botswana Development
Corporation do not.

**All three agencies are now read.** `fitchratings.com` — `sitemap-research.xml` carries the
rating actions, and the `/page-data/` its `robots.txt` disallows is only needed to open an
article page, which we never do. `spglobal.com` — 403 to a lone `User-Agent`, 200 to the
browser navigation header set, reading the news sitemap its own `robots.txt` advertises (see
the 2026-08-07 entry above; both earlier "not reachable" readings on this page were measured
with one header and have been corrected).

**A rating action is never dropped on the model's word.** Two of the four Uzbek items Fitch has
published to date are bare entity names — `JSC Uzbek Metallurgical Plant`, `JSC Navoi Mining
Metallurgical Company` — and the full classifier passed the first and rejected the second
("No listed issuer or direct market link"), on strings that differ only in which issuer they
name. `skip_triage` had already removed the cheap gate from this path; the deeper problem is
that `get_news_feed` serves `relevant = 1` and *any* verdict of 0 is stored for good. So for a
source whose `url_filter`/`title_filter` has already matched one of our issuers, a
`relevant = false` verdict is now **overruled at collection time** (`filtered_to_our_market` in
`news_collector.run`, logged per run): the filter is the stronger evidence, a dull affirmation
on the feed costs a reader one scroll, and a lost downgrade costs more. The relevance *score*
survives for ranking.

**When a gate changes, the items it buried need a second reading.** A stored verdict is what
stops us paying twice for the same item, and it is also why a gate that judged wrong keeps that
judgement for the life of the row. `python news_collector.py --rejudge <source_id>` (and
`POST /api/admin/news/rejudge`) deletes that source's `relevant = 0` rows, locally and in prod,
so the next ordinary run fetches and classifies them once more. Rows on the feed are never
touched, so nothing published can disappear this way.

## openinfo material facts (the issuer channel)

**Its link opens the issuer's card, not the filing — and that is openinfo, not a bug.**
Re-verified 2026-07-25: `/ru/facts/{id}`, `/ru/fact/{id}`, `/ru/disclosure/{id}` and
`/ru/organizations/{org}/facts/{id}` all 404; only `/ru/organizations/{org}` is 200. The
`?fact=` hint is ignored by the app but keeps `news.url` unique per filing, which is the dedup
key. The API's `fact_own_link` is not a better target either — sampled over 12 recent filings
it is the issuer's disclosure *index* page at best (`pahta.uz/…/sushchestvennye-fakty/`) and a
bare homepage at worst (`edcom.uz/uz/`, `www.toshuyjoyliti.uz`), so swapping to it would often
be a downgrade. The story page therefore labels the button **"Карточка эмитента на
openinfo.uz"** and says the portal publishes no standalone page per material fact, instead of
promising a full text that does not exist.

`GET /disclosure/facts/{id}/` *does* return the filing's own content (`factscorresponding`,
`factslistaffiliates`, `date_vnesn`, …), one extra paced call per item and no model. The
payload shape differs per fact type across 50+ types, and for the common affiliate-list
filings it is mostly personal names — so this is worth doing per fact type, not generically.

**Figures are pulled for every fact type filed as structured fields (LIVE).** `_fact_figures`
makes one extra paced call to `/disclosure/facts/{id}/` — the id the item already carries — and
appends the filing's own figures to the snippet. No model is involved, so this costs the
request and nothing else; any failure returns None and the item publishes with its plain
snippet.

* **32 — «Начисление доходов по ценным бумагам»**, the declaration, carrying the amount **per
  security**: `Начислено 468 493,16 сум на облигацию (4.68% номинала), выплата 19.07.2026 —
  27.07.2026.` Shares file `sum_aksiya` with the window in `*_common_shares`; bonds file
  `sum_per` with `*_other_securities` (verified across AGAT CREDIT, CONTACT FINANCE, UZUM
  SARMOYA, ToshuyjoyLITI). The `*2` variants hold a second class, but the API's naming does not
  separate ordinary from preferred reliably, so they are left out rather than mislabelled.
* **42 — «Дивиденды, выплаченные акционерам»**, the payment report: `начислено … выплачено
  99.24% … Не выплачено 0.76% … Причина по данным эмитента: …`. Reported exactly as filed —
  several issuers file `paid=0` alongside `debt=0`, and inferring the shortfall would
  contradict their own numbers.

* **20 / 21 — «Крупная сделка» / «Сделка с аффилированным лицом»**: counterparty, subject,
  amount, and for fact 20 `assets_issuer` — the deal as a share of the issuer's assets, which
  is what separates routine trading from a balance-sheet event. A grouped day is **aggregated**,
  because "eight filings" was never the story: `8 сделок за день, на 21 151 806 052 сум по 7 из
  них. Контрагенты: Бухарский нефтеперерабатывающий завод, O'ZLITINEFTGAZ, UzGasTrade и др.`
* **31 — «Сроки исполнения по ц/б»**: the redemption/payment window.
* **6 — «Решения высшего органа управления»**: meeting date, **quorum**, minutes date. The
  resolutions themselves are filed as arrays that are empty on most records, so only the
  consistently-present fields are reported.
* **22 — «Получение лицензии»**: activity, licence number, validity.

**Deliberately not enriched: 8 (board changes) and 36 (affiliate lists).** Their detail *is*
available — `factscaseelection`, `factsmembershipexecutive`, `factslistaffiliates` — but it is
a list of people's names and workplaces: personal data that says nothing about the security.
Those filings stay title-only on purpose. Together with the press sources this is why coverage
is partial by design, not by omission: **6 of the 9 openinfo items live on 2026-07-25 carry
figures; the other 3 are types 8/36.**

Grouping keeps every filing's id (`fact_ids`), not just the newest anchor — one id can only
describe one of eight deals. Fetches are capped at `_FIGURE_MAX_FETCH` (8) per item.

`--backfill-facts` re-reads filings already stored and replaces their bare snippets via
`POST /api/admin/news/snippets` (snippet only, and only when the new text is longer, so a
re-run cannot shrink a row). Needed because dedup means a normal run never revisits a stored
item — without it, everything collected before this pass keeps saying only "Подано 8 сообщений
за день" until it ages out.

The story page shows this under **«Из раскрытия эмитента»**, not «Как сообщает источник», and
shows it unconditionally for filings: the summary only paraphrases figures that are the point.

**Gotcha for whoever builds it:** `organization` is an integer id in `/disclosure/facts/` but a
nested object in `/disclosure/fact42/`, so the org→ticker map must read
`rec["organization"]["id"]` there. Matching the integer form against it silently yields zero
matches. Note also `fact50`/`fact49` have no dedicated endpoint (404) — only some types do.


Live since 2026-07-25. `GET {api}/disclosure/facts/` returns every filing newest-first
(64k+ records, ~21/day across all ~790 filers). The adapter keeps the ones filed by **our**
issuers, attributing each by openinfo `organization` id via `catalog_companies.org_id` —
**68 of 93 tickers have one**, so filings from the remaining 25 are logged and skipped;
backfilling those org_ids is the single cheapest way to widen coverage. Measured overlap:
**~7 filings/day belong to covered issuers**, 20 distinct tickers over a 14-day window.

Filings are treated as authoritative, unlike feed news:

- **grouped** — same issuer + same fact type + same day becomes one card (O'zbekneftgaz
  files eight affiliate-deal notices in an hour; that is one story, not eight);
- **`always_relevant`** — they skip the prefilter and the triage gate entirely, and are
  never dropped as "not relevant";
- **tickers and class come from the filing**, replacing the model's guesses: `fact_number`
  maps to the §3.11 class (`_FACT_TYPE_MAP`), and `org_id` gives the exact ticker(s) —
  including both share classes where an issuer has them (UZNG/UZNGP). The model is left to
  do only what it is good at here: tone, impact, direction and the summary.

Set `OPENINFO_FACTS_ENDPOINT` to override the path, `OPENINFO_FACTS_PAGES` (default 2 × 50
filings ≈ 5 days) to change the lookback. All traffic goes through `openinfo_http` (paced
350 ms, retries, TLS verify) per the project rule.

Link caveat: openinfo's public app is a Next.js SPA whose only working public route for a
filing is the issuer page — `/ru/organizations/<org_id>` is 200, while every deeper
`/facts`, `/disclosure` or `/fact/<id>` path 404s (checked 2026-07-25). Cards therefore link
to the issuer's openinfo page with a `?fact=<id>` hint: the app ignores the param, but it
keeps each card's URL unique, which matters because `news.url` is the dedup key.

## Fixed 2026-07-25

Two things that had silently stopped the scheduled runs:
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
