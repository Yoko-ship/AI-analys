"""News runner operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from collections import Counter
from news_classifier import NewsClassification
from news_classifier import classifier_model_name
from news_classifier import classify_filings
from news_classifier import classify_items
from news_classifier import prefilter_reject
from news_classifier import screen_items
import collectors.news.backfill as collectors_news_backfill
import collectors.news.delivery as collectors_news_delivery
import collectors.news.enrichment as collectors_news_enrichment
import collectors.news.filings as collectors_news_filings
import collectors.news.images as collectors_news_images
import collectors.news.issuers as collectors_news_issuers
import collectors.news.settings as collectors_news_settings
import collectors.news.sources as collectors_news_sources
import json
import news_lang
import news_store
import os
import re
import time


def fetch_pending(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """html (sitemap scrape) and telegram adapters — not yet implemented."""
    collectors_news_settings.logger.info("source '%s' (%s) adapter pending — skipped", source["id"], source["type"])
    return []


_FETCHERS = {"rss": collectors_news_sources.fetch_rss, "openinfo": collectors_news_filings.fetch_openinfo, "html_list": collectors_news_sources.fetch_html_list,
             "sitemap": collectors_news_sources.fetch_sitemap, "html": fetch_pending, "telegram": fetch_pending}


def _split_for_triage(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """``(filings, pre_gated, to_screen)`` — who skips the cheap gate, and why.

    Two kinds of item have already had their relevance established before any model is
    asked. An issuer's own filing is market news by definition. And a rating agency read
    through a ``url_filter`` reached us *because* its URL named one of our issuers — that
    is exactly what makes the source authoritative on the read side
    (``news_store._AUTHORITATIVE_SOURCES``).

    Sending the second kind to triage could only lose. Fitch publishes a rating action as a
    bare, snippet-less entity name ('JSC Uzbek Metallurgical Plant'); asked "could this
    plausibly matter to the market?", a cheap gate reading nothing but that string can
    reasonably say no — and a triage rejection **is stored**, so one wrong verdict buries
    the action for good. They go straight to the full classification, which sees the issuer
    universe and is the right place to decide what the action actually says. It costs one
    extra full call for the handful of items a year that clear the URL filter.
    """
    filings = [it for it in items if it.get("always_relevant")]
    rest = [it for it in items if not it.get("always_relevant")]
    return (filings,
            [it for it in rest if it.get("skip_triage")],
            [it for it in rest if not it.get("skip_triage")])


def _skip_triage(source: dict[str, Any], item: dict[str, Any]) -> bool:
    """Whether this one item bypasses the cheap gate.

    ``skip_triage`` is a property of the whole source (a rating agency read through a
    url_filter: everything that arrives has already been matched to an issuer).
    ``skip_triage_filter`` is the per-item form, for a source whose stream is mostly other
    people's news — The Diplomat covers all of Central Asia, and its Kazakh and Mongolian
    pieces should keep facing the gate, while the ones that name Uzbekistan should not: the
    gate reads a 130-character teaser, has rejected 'Uzbekistan's Nuclear Power Plant Project
    Advances' at 0.2, and a triage rejection is stored for good.
    """
    if source.get("skip_triage"):
        return True
    pattern = source.get("skip_triage_filter")
    if not pattern:
        return False
    text = f"{item.get('title') or ''} {item.get('snippet') or ''} {item.get('url') or ''}"
    return bool(re.search(pattern, text, re.I))


def run(*, only: str | None = None, limit: int = 40, push: bool = True, dry_run: bool = False) -> dict[str, Any]:
    sources = collectors_news_sources.load_sources(only)
    universe = collectors_news_issuers.build_universe()
    collectors_news_settings.logger.info("collecting from %d source(s); issuer universe = %d tickers", len(sources), len(universe))

    # 1) fetch everything, then filter to genuinely-new URLs (skip re-classify).
    raw: list[dict[str, Any]] = []
    for src in sources:
        fetcher = _FETCHERS.get(src["type"], fetch_pending)
        # A source may cap itself tighter than the CLI --limit (whole-site feeds whose
        # extra volume is mostly non-market news); --limit stays the ceiling.
        src_limit = min(limit, int(src.get("max_items") or limit))
        try:
            fetched = fetcher(src, src_limit)
        except Exception:  # noqa: BLE001 — one source must not kill the run
            collectors_news_settings.logger.exception("fetch failed for %s", src["id"])
            fetched = []
        for it in fetched:
            it["source"] = src["name"]
            it["source_id"] = src["id"]
            it["coverage_weight"] = src.get("coverage_weight", 0.5)
            it["skip_triage"] = _skip_triage(src, it)
            # A source read through a url/title filter has had its relevance established
            # before any model saw it — see the gate-2 override below.
            it["filtered_to_our_market"] = bool(
                src.get("skip_triage") and (src.get("url_filter") or src.get("title_filter")))
            # Every adapter stamps the source's DECLARED first language, which is a constant
            # per source and therefore wrong for any outlet that publishes in more than one
            # (kun.uz, spot.uz, uzdaily all declare two or three). Read the item instead;
            # keep the declared value only when the text has no letters to judge by.
            it["lang"] = news_lang.detect_lang(it.get("title"), it.get("snippet")) or it.get("lang")
        by_lang = Counter(it.get("lang") for it in fetched)
        collectors_news_settings.logger.info("  %s: %d items (cap %d)%s", src["id"], len(fetched), src_limit,
                    f" — {dict(by_lang)}" if len(by_lang) > 1 else "")
        raw.extend(fetched)
        time.sleep(min(src.get("crawl_delay_s", 2), 5) if len(sources) > 1 else 0)

    # Skip stale news up front — never classify (or pay for) anything older than the
    # freshness window. Undated items are kept (see _is_recent).
    max_age = int(os.getenv("NEWS_MAX_AGE_DAYS", "30"))
    before_age = len(raw)
    raw = [it for it in raw if collectors_news_sources._is_recent(it.get("published_at"), max_age)]
    if before_age != len(raw):
        collectors_news_settings.logger.info("recency filter: dropped %d item(s) older than %d days", before_age - len(raw), max_age)

    # Within one run, two sources — or two pages of the same source — can surface the same
    # article. Collapsing them here means we never pay to classify it twice (the store's
    # UNIQUE(url) would merge the rows afterwards, but only after the money was spent).
    # Keyed on the canonical form rather than whatever the adapter produced, so this holds
    # even for a fetcher that forgets to canonicalise its links.
    unique: dict[str, dict[str, Any]] = {}
    for it in raw:
        unique.setdefault(collectors_news_sources._canonical_url(it["url"]), it)
    if len(unique) != len(raw):
        collectors_news_settings.logger.info("intra-run dedup: %d duplicate URL(s) inside this run", len(raw) - len(unique))
    raw = list(unique.values())

    # Dedup on the canonical URL, but also on the feed's original link so rows stored
    # before canonicalisation are still recognised instead of re-classified once. Prod is
    # asked too, so a run with no local history (a fresh cron container) is not a blank slate.
    candidates = [it["url"] for it in raw] + [it["raw_url"] for it in raw if it.get("raw_url")]
    seen = news_store.existing_urls(candidates)
    if push:
        try:
            remote_seen = collectors_news_delivery.known_urls_in_prod(sorted(set(candidates)))
        except Exception:  # noqa: BLE001 — a dedup check must never abort the run
            collectors_news_settings.logger.exception("prod dedup check failed; using local history only")
            remote_seen = set()
        if remote_seen - seen:
            collectors_news_settings.logger.info("dedup: %d item(s) already in prod but not in the local history",
                        len(remote_seen - seen))
        seen |= remote_seen
    fresh = [it for it in raw
             if it["url"] not in seen and (it.get("raw_url") or it["url"]) not in seen]
    collectors_news_settings.logger.info("fetched %d, %d already stored, %d new", len(raw), len(raw) - len(fresh), len(fresh))

    # 1b) gate 0 — free code-only prefilter. Whole-site feeds are mostly non-market news;
    # dropping it here costs nothing and never reaches the model. Dropped items are not
    # stored, so a later prefilter change simply reconsiders them next run.
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}
    for it in fresh:
        # An issuer's own filing is market news by definition — never gate it.
        junk = None if it.get("always_relevant") else prefilter_reject(it, universe)
        if junk:
            dropped[junk] = dropped.get(junk, 0) + 1
        else:
            kept.append(it)
    if dropped:
        top = sorted(dropped.items(), key=lambda kv: -kv[1])[:6]
        collectors_news_settings.logger.info("prefilter: dropped %d of %d as non-market before any LLM call (%s)",
                    len(fresh) - len(kept), len(fresh),
                    ", ".join(f"{k}×{v}" for k, v in top))

    # 2) classify what's left (Layer A: cheap triage, then full classification).
    from llm_client import Usage
    usage = Usage()
    # Label rows with the Codex model that actually classified them.
    model = classifier_model_name()
    records: list[dict[str, Any]] = []
    failed = 0
    triaged_out = 0
    kept_by_filter = 0
    # Filings are rated by a separate, compact prompt (no issuer universe — their ticker and
    # class come from the filing) and never face the triage gate.
    filings, pre_gated, to_screen = _split_for_triage(kept)

    # gate 1, batched: many items per call sharing one prompt.
    survivors: list[dict[str, Any]] = list(pre_gated)
    if pre_gated:
        collectors_news_settings.logger.info("triage bypassed for %d item(s) from url-filtered source(s): %s",
                    len(pre_gated),
                    ", ".join(sorted({str(it.get("source_id")) for it in pre_gated})))
    for it, (passed, score) in zip(to_screen, screen_items(to_screen, usage=usage)):
        if passed:
            survivors.append(it)
            continue
        # Rejections ARE stored, so we never pay to triage the same item twice.
        rejected = NewsClassification(relevant=False, relevance_score=score,
                                      reason="triage: not market-relevant")
        records.append({**it, "model": usage.model or model, **rejected.model_dump()})
        triaged_out += 1

    # gate 2, batched.
    for it, cls in zip(survivors, classify_items(survivors, universe, usage=usage)):
        # A failed classification (no API key, quota, outage) is NOT stored: URL dedup
        # would then bury the item as irrelevant forever. Left unstored, it is simply
        # re-fetched and re-classified on the next run.
        if cls.reason == "classification_failed":
            failed += 1
            continue
        record = {**it, "model": usage.model or model, **cls.model_dump()}
        # A rating agency reaches us only through a url/title filter that already matched one
        # of our issuers or the sovereign, which is what makes the source authoritative on the
        # read side. The item it publishes is a bare entity name with no snippet ('JSC Navoi
        # Mining Metallurgical Company'), and asked to classify that string the model can
        # reasonably answer 'no listed issuer or direct market link' — measured, on an item
        # whose sister ('JSC Uzbek Metallurgical Plant') it passed. That verdict is stored and
        # never revisited, so it would bury a rating action for good. The filter wins here: a
        # dull affirmation on the feed costs a reader a scroll, a lost downgrade costs more.
        if record.get("filtered_to_our_market") and not record.get("relevant"):
            record["relevant"] = True
            record["relevance_score"] = max(float(record.get("relevance_score") or 0.0), 0.5)
            record["reason"] = (f"{cls.reason or 'model said not relevant'} — kept: the source "
                                f"filter already matched an issuer")
            kept_by_filter += 1
        records.append(record)

    for it, cls in zip(filings, classify_filings(filings, usage=usage)):
        record = {**it, "model": usage.model or model, **cls.model_dump()}
        # The source told us the issuer and the filing class; those REPLACE anything the
        # model might say (a wrong ticker would attach this filing to another issuer's feed
        # and its sentiment), and a filing is never dropped as "not relevant".
        record["relevant"] = True
        if it.get("tickers"):
            record["tickers"] = sorted(it["tickers"])
        if it.get("type_hint"):
            record["type"] = it["type_hint"]
        records.append(record)

    if failed:
        collectors_news_settings.logger.warning("%d item(s) failed classification — not stored, will retry next run", failed)
    if kept_by_filter:
        collectors_news_settings.logger.info("%d item(s) kept over the model's verdict: their source filter had already "
                    "matched an issuer", kept_by_filter)
    relevant = [r for r in records if r.get("relevant")]
    billing_note = "Codex tokens covered by subscription"
    collectors_news_settings.logger.info("classified %d items (%d stopped at triage, %d relevant); ~%d tokens in "
                "%d calls (%.0f%% of input from prompt cache), est API $%.4f (%s)",
                len(records), triaged_out, len(relevant), usage.total_tokens, usage.calls,
                usage.cache_hit_rate * 100, usage.est_cost_usd(), billing_note)

    # 2b) preview images, for the RELEVANT items only: those are the cards the feed
    # renders, and a whole-site feed like kursiv's is ~85% off-topic — fetching pages
    # for items about to be filtered out would be almost all of the requests.
    by_id = {s["id"]: s for s in sources}
    collectors_news_images.enrich_images(relevant, by_id)
    # And where the feed handed us a thumbnail, take the full-size original instead: a
    # 320px picture stretched across an article column is what a reader notices first.
    collectors_news_images.upgrade_images(relevant, by_id)

    if dry_run:
        for r in records:
            print(json.dumps({k: r.get(k) for k in
                              ("source_id", "relevant", "type", "tone", "impact", "direction",
                               "tickers", "title", "summary_ru")},
                             ensure_ascii=False))
        return {"fetched": len(raw), "new": len(fresh),
                "prefiltered": len(fresh) - len(kept), "triaged_out": triaged_out,
                "relevant": len(relevant),
                "with_image": sum(1 for r in relevant if r.get("image_url")),
                "model": usage.model or model, "calls": usage.calls,
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "cached_input_tokens": usage.cached_prompt_tokens,
                "tokens": usage.total_tokens, "subscription_tokens": usage.subscription_tokens,
                "est_cost_usd": round(usage.est_cost_usd(), 4),
                "dry_run": True}

    # 3) store locally (dedup memory) + push to prod.
    stored = news_store.upsert_news(records)
    pushed = 0
    push_failed = False
    if push and records:
        code = collectors_news_delivery.push_news(records)
        pushed = len(records) if code == 0 else 0
        push_failed = code != 0

    # 4) another attempt at the images that missed. kun.uz answers 200 with a page whose
    # <head> carries no og:image at all — a shell, the same byte count for any article —
    # and then serves the real thing minutes later, so a single attempt at collection time
    # is a coin toss and an item that loses it stays imageless for its whole 30 days. This
    # gives every stored item still without a picture one more chance per run, capped and
    # paced like any other page fetch, and only for the two sources that publish one.
    filled = 0
    if push:
        try:
            filled = collectors_news_backfill.backfill_images(limit=collectors_news_images._BACKFILL_IMAGE_CAP, days=30, push=True).get("found", 0)
        except Exception:  # noqa: BLE001 — a picture is never worth failing the run for
            collectors_news_settings.logger.exception("image backfill pass failed")

    # 5) the long read. Runs after the push, over what the FEED holds rather than over this
    # run's records: a story that missed its article page yesterday (or was collected before
    # this pass existed) is a better use of the day's cap than nothing, and the cap is what
    # keeps this from becoming a crawl. Failure here leaves the old summary-only page.
    detailed = 0
    if push:
        try:
            detailed = collectors_news_backfill.backfill_details(limit=collectors_news_enrichment._DETAIL_CAP, days=30, push=True,
                                        usage=usage).get("written", 0)
        except Exception:  # noqa: BLE001 — the story page still works without it
            collectors_news_settings.logger.exception("detail pass failed")
    return {
        "fetched": len(raw), "new": len(fresh), "prefiltered": len(fresh) - len(kept),
        "classified": len(records), "triaged_out": triaged_out,
        "classify_failed": failed, "with_image": sum(1 for r in relevant if r.get("image_url")),
        "backfilled_images": filled, "detailed": detailed,
        "relevant": len(relevant), "stored": stored, "pushed": pushed,
        "push_failed": push_failed,
        "model": usage.model or model, "calls": usage.calls,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "cached_input_tokens": usage.cached_prompt_tokens,
        "tokens": usage.total_tokens, "cached_input_pct": round(usage.cache_hit_rate * 100, 1),
        "subscription_tokens": usage.subscription_tokens,
        "est_cost_usd": round(usage.est_cost_usd(), 4),
    }
