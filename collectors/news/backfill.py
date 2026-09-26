"""News backfill operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from news_classifier import translate_summaries
import collectors.news.delivery as collectors_news_delivery
import collectors.news.enrichment as collectors_news_enrichment
import collectors.news.facts as collectors_news_facts
import collectors.news.filings as collectors_news_filings
import collectors.news.images as collectors_news_images
import collectors.news.settings as collectors_news_settings
import collectors.news.sources as collectors_news_sources
import json
import news_store
import os
import requests


def purge_failed(*, push: bool = True) -> dict[str, Any]:
    """Delete locally (and in prod) the items whose classification failed, so the next
    run re-fetches and re-classifies them. No LLM calls."""
    local = news_store.delete_failed_classifications()
    collectors_news_settings.logger.info("purge-failed: %d row(s) deleted locally %s", local["deleted"],
                local["by_source"] or "")
    prod: dict[str, Any] = {"deleted": 0}
    if push:
        secret = os.getenv("ADMIN_API_SECRET", "").strip()
        if not secret:
            collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot purge in prod")
        else:
            try:
                resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/purge-failed",
                                     headers={"X-Admin-Secret": secret}, timeout=120)
                if resp.status_code != 200:
                    collectors_news_settings.logger.error("purge-failed in prod: HTTP %s %s",
                                 resp.status_code, resp.text[:300])
                else:
                    prod = resp.json() or {}
                    collectors_news_settings.logger.info("purge-failed in prod: %s deleted %s",
                                prod.get("deleted"), prod.get("by_source") or "")
            except (requests.RequestException, ValueError) as exc:
                collectors_news_settings.logger.error("purge-failed in prod failed: %s", exc)
    return {"local": local, "prod": prod}


def rejudge_source(source_id: str, *, days: int = 60, push: bool = True) -> dict[str, Any]:
    """Delete one source's rejected rows here and in prod, so the next run judges them again.

    For when the gate changed, not the item: a source that gains ``skip_triage_filter``, or an
    authoritative source whose model verdict is now overridden, has a backlog of items its old
    gate buried — and a stored verdict is never revisited on its own. Relevant rows are never
    touched, so nothing already on the feed can disappear. No LLM calls here; the re-reading
    happens on the next ordinary run, which pays for the items once.
    """
    local = news_store.delete_rejected_from_source(source_id, days=days)
    collectors_news_settings.logger.info("rejudge %s: %d rejected row(s) deleted locally", source_id, local["deleted"])
    prod: dict[str, Any] = {"deleted": 0}
    if push:
        secret = os.getenv("ADMIN_API_SECRET", "").strip()
        if not secret:
            collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot rejudge in prod")
        else:
            try:
                resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/rejudge",
                                     json={"source_id": source_id, "days": days},
                                     headers={"X-Admin-Secret": secret}, timeout=120)
                if resp.status_code != 200:
                    collectors_news_settings.logger.error("rejudge in prod: HTTP %s %s", resp.status_code, resp.text[:300])
                else:
                    prod = resp.json() or {}
                    collectors_news_settings.logger.info("rejudge %s in prod: %s row(s) deleted",
                                source_id, prod.get("deleted"))
            except (requests.RequestException, ValueError) as exc:
                collectors_news_settings.logger.error("rejudge in prod failed: %s", exc)
    return {"local": local, "prod": prod}


def _source_registry() -> dict[str, dict[str, Any]]:
    """id → source config for EVERY registered source, enabled or not: a stored item
    may come from a source that has since been disabled."""
    data = json.loads(collectors_news_settings.SOURCES_FILE.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data.get("sources", []) if s.get("id")}


def _prod_items_without_image(days: int) -> list[dict[str, Any]]:
    """Backfill candidates read from prod's public feed — the rows users actually see
    (the local DB can lag behind it, e.g. items pushed from another host)."""
    try:
        resp = requests.get(f"{collectors_news_settings.DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        collectors_news_settings.logger.warning("could not read the prod feed for backfill candidates: %s", exc)
        return []
    return [{"url": it.get("url"), "source_id": it.get("source_id"), "image_url": None}
            for it in items if it.get("url") and not it.get("image_url")]


def backfill_images(*, limit: int = 40, days: int = 90, push: bool = True) -> dict[str, Any]:
    """Fill preview images on already-stored items — those collected before the
    page-image pass existed. Images only: no classification, so no LLM spend, and the
    stored tone/impact is never touched."""
    # Prod's feed first: those are the cards users see, so they get the fetch budget
    # ahead of local rows (which include items the classifier filtered out).
    remote = _prod_items_without_image(days) if push else []
    candidates = {it["url"]: it for it in remote}
    for r in news_store.rows_without_image(limit=limit, days=days):
        candidates.setdefault(r["url"], {"url": r["url"], "source_id": r["source_id"],
                                         "image_url": None})
    collectors_news_settings.logger.info("image backfill: %d from the prod feed + %d local-only candidate(s)",
                len(remote), len(candidates) - len(remote))
    # Anything a previous run already fetched is reused, not fetched again — a re-run
    # (e.g. after a failed push) costs no requests.
    for url, img in news_store.image_urls_for(list(candidates)).items():
        candidates[url]["image_url"] = img
    # Every candidate goes to `enrich_images`, which applies the cap ITSELF, and does it
    # to the list it has already narrowed to page-image sources. Capping here instead
    # spent the whole budget on openinfo filings — the largest group with no image and
    # the one group that can never have one — and the two outlets that do publish a
    # preview never made the list.
    items = list(candidates.values())
    found = collectors_news_images.enrich_images(items, _source_registry(), max_fetch=limit)
    images = {it["url"]: it["image_url"] for it in items if it.get("image_url")}
    return {
        "candidates": len(items), "found": found,
        "updated_local": news_store.set_image_urls(images),
        "updated_prod": collectors_news_delivery.push_images(images) if (push and images) else 0,
    }


def _prod_items_with_image(days: int) -> list[dict[str, Any]]:
    """Feed rows that HAVE an image — the upgrade pass's work list."""
    try:
        resp = requests.get(f"{collectors_news_settings.DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        collectors_news_settings.logger.warning("could not read the prod feed for image-upgrade candidates: %s", exc)
        return []
    return [{"url": it.get("url"), "source_id": it.get("source_id"),
             "image_url": it.get("image_url")}
            for it in items if it.get("url") and it.get("image_url")]


def upgrade_stored_images(*, days: int = 90, push: bool = True) -> dict[str, Any]:
    """Replace already-stored thumbnails with the full-size originals behind them.

    For the rows collected before the upgrade rules existed. Only sources that declare
    ``image_upgrade`` are touched, every replacement is verified to exist first, and a row
    whose image is already the upgraded one is left alone — so a re-run is free.
    """
    remote = _prod_items_with_image(days) if push else []
    candidates: dict[str, dict[str, Any]] = {it["url"]: it for it in remote}
    for r in news_store.rows_with_upgradable_image(days=days):
        candidates.setdefault(r["url"], r)
    items = list(candidates.values())
    upgraded = collectors_news_images.upgrade_images(items, _source_registry())
    if not upgraded:
        collectors_news_settings.logger.info("image upgrade: nothing to replace across %d row(s)", len(items))
        return {"candidates": len(items), "upgraded": 0,
                "updated_local": 0, "updated_prod": 0}
    images = {it["url"]: it["image_url"] for it in items if it.get("image_url")}
    return {
        "candidates": len(items), "upgraded": upgraded,
        "updated_local": news_store.set_image_urls(images, replace=True),
        "updated_prod": collectors_news_delivery.push_images(images, replace=True) if push else 0,
    }


def _prod_items_without_translation(days: int) -> list[dict[str, Any]]:
    """Backfill candidates read from prod's public feed — the cards users actually see."""
    try:
        resp = requests.get(f"{collectors_news_settings.DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        collectors_news_settings.logger.warning("could not read the prod feed for translation candidates: %s", exc)
        return []
    return [{"url": it.get("url"), "summary_ru": it.get("summary_ru")}
            for it in items
            if it.get("url") and (it.get("summary_ru") or "").strip()
            and not ((it.get("summary_en") or "").strip() and (it.get("summary_uz") or "").strip())]


def backfill_translations(*, limit: int = 60, days: int = 90, push: bool = True,
                          dry_run: bool = False) -> dict[str, Any]:
    """Give rows stored before the English and Uzbek columns existed their translations.

    New items need none of this — the classifier writes all three summaries in the same call
    that classifies them. This is the one-off for history, and it re-translates nothing: only
    rows whose ``summary_en``/``summary_uz`` are still empty are sent, and the store writes
    only into empty columns, so a re-run after a failed push costs nothing.

    The classification is never touched: this pushes to /api/admin/news/translations, not to
    /api/admin/news, so an item's tone, impact and issuer links cannot move.
    """
    remote = _prod_items_without_translation(days) if push else []
    candidates = {it["url"]: it for it in remote}
    for r in news_store.rows_missing_translations(limit=limit, days=days):
        candidates.setdefault(r["url"], {"url": r["url"], "summary_ru": r["summary_ru"]})
    items = [it for it in candidates.values() if (it.get("summary_ru") or "").strip()][:limit]
    collectors_news_settings.logger.info("translation backfill: %d from the prod feed + %d local-only, %d to translate",
                len(remote), len(candidates) - len(remote), len(items))
    if not items:
        return {"candidates": 0, "translated": 0, "updated_local": 0, "updated_prod": 0}

    from llm_client import LLMError, Usage  # local, like the other LLM-spending backfill

    usage = Usage()
    try:
        results = translate_summaries(items, usage=usage)
    except LLMError as exc:
        # No key configured. translate_summaries survives a failed CALL, but acquiring the
        # client happens before any of that, and a cron should read the reason rather than a
        # traceback. Nothing is stored, so re-running once the key is set costs nothing.
        collectors_news_settings.logger.error("translation backfill: %s", exc)
        return {"candidates": len(items), "translated": 0,
                "updated_local": 0, "updated_prod": 0, "error": str(exc)}
    translations = {
        it["url"]: {"en": got.get("en", ""), "uz": got.get("uz", "")}
        for it, got in zip(items, results)
        if got.get("en") or got.get("uz")
    }
    collectors_news_settings.logger.info("translation backfill: %d of %d item(s) translated "
                "(%d tokens, ~$%.4f)", len(translations), len(items),
                usage.total_tokens, usage.est_cost_usd())
    if dry_run:
        for url, langs in list(translations.items())[:5]:
            collectors_news_settings.logger.info("  %s\n    en: %s\n    uz: %s", url, langs["en"][:90], langs["uz"][:90])
        return {"candidates": len(items), "translated": len(translations),
                "updated_local": 0, "updated_prod": 0, "dry_run": True}
    return {
        "candidates": len(items), "translated": len(translations),
        "updated_local": news_store.set_translations(translations),
        "updated_prod": collectors_news_delivery.push_translations(translations) if (push and translations) else 0,
    }


def _prod_detail_candidates(days: int, *, source_id: str | None = None,
                            include_existing: bool = False) -> list[dict[str, Any]]:
    """Long-read candidates read from prod's feed — the cards a reader can actually open."""
    try:
        resp = requests.get(f"{collectors_news_settings.DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        collectors_news_settings.logger.warning("could not read the prod feed for detail candidates: %s", exc)
        return []
    # The feed reports whether an item HAS a long read, not its text — three languages of
    # prose over 200 items would be a megabyte of response for a list that shows none of it.
    # snippet and summary come along because an item with no article page is written from
    # exactly those two fields (news_classifier.write_brief_detail) — without them the
    # page-less route would have nothing to lay out on a candidate read from prod.
    return [{"url": it.get("url"), "title": it.get("title"), "source": it.get("source"),
             "source_id": it.get("source_id"), "snippet": it.get("snippet"),
             "summary_ru": it.get("summary_ru"), "tickers": it.get("tickers"),
             "published_at": it.get("published_at")}
            for it in items
            if it.get("url")
            and (not source_id or it.get("source_id") == source_id)
            and (include_existing or not it.get("has_detail"))]


def backfill_details(*, limit: int | None = None, days: int = 30, push: bool = True,

                     dry_run: bool = False, usage: Any = None,

                     source_id: str | None = None, replace: bool = False) -> dict[str, Any]:

    """Write the story-page long read for feed items that have none yet.



    The pass that makes an opened story worth opening: a feed teaser is one sentence, the

    article behind it is five paragraphs, and until now the reader got the sentence. For each

    candidate it opens the source's article page once, hands the prose to the model, and

    stores OUR OWN 3-5 paragraph account of it in all three UI languages — the article text

    itself is never written anywhere (see ``_article_text``).



    Ordered by the prod feed first, so the day's cap is spent on cards that are actually on

    the page — but a share of every run is reserved for the OLDEST items still without one.

    Newest-first alone never converges while the cap is under the day's inflow: the shortfall

    lands on the same items every time and three weeks of stories stay bare. Normal runs fill

    only empty columns. ``replace`` is an explicit one-source migration after an extractor

    improves; it is never enabled by the daily pass.

    """

    limit = collectors_news_enrichment._DETAIL_CAP if limit is None else limit

    if replace and not source_id:

        raise ValueError("replacing details requires an explicit source_id")

    remote = _prod_detail_candidates(

        days, source_id=source_id, include_existing=replace

    ) if push else []

    candidates: dict[str, dict[str, Any]] = {it["url"]: it for it in remote if it.get("url")}

    registry = _source_registry()

    if source_id and source_id not in registry:

        raise ValueError(f"unknown news source: {source_id}")

    local_only = 0

    source_ids = [source_id] if source_id else None

    for r in news_store.rows_without_detail(

        limit=max(limit * 2, 20), days=days, source_ids=source_ids,

        include_existing=replace,

    ):

        if r["url"] not in candidates:

            candidates[r["url"]] = r

            local_only += 1

    # The tail slice is taken from the store rather than from the prod feed: the feed is

    # ranked and capped at 200, so its own oldest is not the corpus's oldest.

    tail_n = 0 if replace else int(max(0.0, min(collectors_news_enrichment._DETAIL_TAIL_SHARE, 1.0)) * limit)

    tail = [r for r in news_store.rows_without_detail(

        limit=max(tail_n, 1), days=days, source_ids=source_ids, oldest_first=True

    )][:tail_n]

    head = [c for c in candidates.values()

            if c["url"] not in {t["url"] for t in tail}][:max(1, limit - len(tail))]

    items = head + tail

    collectors_news_settings.logger.info("detail backfill: %d from the prod feed + %d local-only, "

                "%d to write (%d newest, %d from the backlog)",

                len(remote), local_only, len(items), len(head), len(tail))

    if not items:

        return {"candidates": 0, "written": 0, "updated_local": 0, "updated_prod": 0}



    from llm_client import LLMError, Usage



    own_usage = usage is None

    usage = Usage() if own_usage else usage

    try:

        details = collectors_news_enrichment.enrich_details(items, registry, max_fetch=limit, usage=usage)

    except LLMError as exc:

        # No key configured — the same shape as the translation backfill: say why, store

        # nothing, and let a re-run once the key is set cost nothing.

        collectors_news_settings.logger.error("detail backfill: %s", exc)

        return {"candidates": len(items), "written": 0,

                "updated_local": 0, "updated_prod": 0, "error": str(exc)}

    if own_usage:

        collectors_news_settings.logger.info("detail backfill: %d long read(s) written (%d tokens, ~$%.4f)",

                    len(details), usage.total_tokens, usage.est_cost_usd())

    if dry_run:

        for url, langs in list(details.items())[:3]:

            collectors_news_settings.logger.info("  %s\n    ru: %s…", url, langs["ru"][:200])

        return {"candidates": len(items), "written": len(details),

                "updated_local": 0, "updated_prod": 0, "dry_run": True}

    return {

        "candidates": len(items), "written": len(details),

        "updated_local": news_store.set_details(details, replace=replace),

        "updated_prod": collectors_news_delivery.push_details(details, replace=replace) if (push and details) else 0,

    }


def backfill_facts(*, limit: int = 60, push: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """Re-read the openinfo filings we already store and replace their bare snippets.

    Items collected before the figures pass existed say only "Существенный факт №21 …
    Подано 8 сообщений за день", and dedup means a normal run will never look at them again.
    This re-runs the same fetch (which now enriches), keeps the items whose URL is ALREADY
    stored, and pushes snippet-only updates. No classification, so no LLM spend, and the
    stored tone/impact is untouched.

    Reaches as far back as the facts API's recent window — raise ``OPENINFO_FACTS_PAGES`` to
    cover older rows.
    """
    sources = collectors_news_sources.load_sources("openinfo_facts")
    if not sources:
        return {"candidates": 0, "updated_local": 0, "updated_prod": 0}
    items = collectors_news_filings.fetch_openinfo(sources[0], limit)
    # Only the items that actually gained figures are worth an update; the rest would
    # rewrite a row with the text it already has.
    enriched = {it["url"]: it["snippet"] for it in items
                if it.get("snippet") and collectors_news_facts._FIGURE_FORMATTERS.get(it.get("fact_number_hint"))}
    if not enriched:
        enriched = {it["url"]: it["snippet"] for it in items if it.get("snippet")}
    known = news_store.existing_urls(list(enriched))
    if push:
        known |= collectors_news_delivery.known_urls_in_prod(list(enriched))
    updates = {u: t for u, t in enriched.items() if u in known}
    collectors_news_settings.logger.info("fact backfill: %d fetched, %d already stored → %d snippet update(s)",
                len(items), len(known), len(updates))
    if dry_run:
        for url, text in list(updates.items())[:10]:
            collectors_news_settings.logger.info("  %s -> %s", url, text[:220])
        return {"candidates": len(updates), "updated_local": 0, "updated_prod": 0, "dry_run": True}
    return {
        "candidates": len(updates),
        "updated_local": news_store.set_snippets(updates),
        "updated_prod": collectors_news_delivery.push_snippets(updates) if (push and updates) else 0,
    }
