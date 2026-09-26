from __future__ import annotations

from functools import partial
from typing import Any
import asyncio
import news_store
import os
import server.http as http


def _issuer_universe() -> dict[str, str]:
    """ticker → name, to constrain the classifier's ticker tags (mirrors the collector)."""
    import reports_catalog as rc
    import catalogue.settings as catalogue_settings
    import catalogue.storage as catalogue_storage
    universe: dict[str, str] = {}
    try:
        conn = catalogue_storage.get_catalog_conn()
        for r in conn.execute("SELECT ticker, company_name FROM catalog_companies").fetchall():
            if r["ticker"]:
                universe[r["ticker"].upper()] = r["company_name"] or r["ticker"]
        conn.close()
    except Exception:  # noqa: BLE001 — fall back to the static catalog
        http.logger.exception("issuer universe query failed; classifier will infer sectors only")
    if not universe:
        try:
            universe = {t.upper(): n for t, n in catalogue_settings._TICKER_TO_NAME.items()}
        except Exception:  # noqa: BLE001
            pass
    return universe


def _news_search_sync(query: str, days: int, store: bool) -> dict[str, Any]:
    """Run the Layer-B search agent, classify each hit, and (by default) store it.

    Blocking (network + LLM) — called via run_in_executor. Reuses the collector's
    classify → upsert path so agent-found items are indistinguishable from
    feed-collected ones (same tables, same /api/news/feed). Already-stored URLs are
    skipped so we never re-pay to classify them.
    """
    from news_agent import find_news
    from news_classifier import classify_item
    from llm_client import Usage

    findings = find_news(query, days=days)
    universe = _issuer_universe()
    usage = Usage()
    model = os.getenv("NEWS_CLASSIFIER_MODEL", "").strip() or os.getenv("LLM_MODEL", "grok-4.3")

    seen = news_store.existing_urls([it["url"] for it in findings.items if it.get("url")])
    records: list[dict[str, Any]] = []
    for it in findings.items:
        if not it.get("url") or it["url"] in seen:
            continue
        # triage=False: the admin asked for this company by name, so relevance is already
        # established — the cheap gate exists for whole-feed collection, not targeted search.
        cls = classify_item({**it, "lang": None}, universe, usage=usage, triage=False)
        records.append({
            "url": it["url"],
            "title": it.get("title", ""),
            "snippet": it.get("snippet", ""),
            "source": it.get("source") or "grok-search",
            "source_id": "grok_search",
            "lang": None,
            "image_url": it.get("image_url"),
            "published_at": it.get("published"),
            "coverage_weight": 0.5,
            "model": model,
            **cls.model_dump(),
        })

    stored = news_store.upsert_news(records) if (store and records) else 0
    relevant = [r for r in records if r.get("relevant")]
    return {
        "query": query,
        "backend": findings.backend,
        "note": findings.note,
        "queries": findings.queries,
        "found": len(findings.items),
        "new": len(records),
        "already_stored": len(findings.items) - len(records),
        "relevant": len(relevant),
        "stored": stored,
        "items": [{
            "url": r["url"], "title": r["title"], "source": r["source"],
            "published_at": r["published_at"], "relevant": r.get("relevant"),
            "type": r.get("type"), "tone": r.get("tone"), "impact": r.get("impact"),
            "direction": r.get("direction"), "tickers": r.get("tickers"),
            "summary_ru": r.get("summary_ru"), "image_url": r.get("image_url"),
        } for r in records],
        "tokens": findings.usage.total_tokens + usage.total_tokens,
    }
