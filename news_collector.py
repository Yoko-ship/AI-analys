"""News collector — the off-Railway orchestrator (collector-push model).

Runs on a host that can reach the sources (openinfo blocks Railway's IP, so news
collection follows the same collector-push pattern as ``collector_financials.py``):

    load news_sources.json (enabled sources)
      → fetch each (RSS today; openinfo/html/telegram adapters below)
      → drop items already seen (skip re-classifying — saves LLM spend)
      → classify each new item with DeepSeek (Layer A)
      → store locally + push to POST /api/admin/news

Legal invariant: we keep headline + our own summary + link only — never article body.

CLI:
    python news_collector.py                 # collect, classify, store, push
    python news_collector.py --no-push       # local only (no prod push)
    python news_collector.py --dry-run       # fetch+classify, print, don't store/push
    python news_collector.py --limit 20      # cap items per source
    python news_collector.py --source cbu    # one source only
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests

import news_store
import reports_catalog as rc
from news_classifier import classify_item

logger = logging.getLogger(__name__)

SOURCES_FILE = Path(__file__).resolve().parent / "news_sources.json"
DEFAULT_PUSH_URL = os.getenv(
    "NEWS_PUSH_URL",
    os.getenv("FINANCIALS_PUSH_URL", "https://ai-analys-production.up.railway.app"),
).rstrip("/")
DEFAULT_UA = "Mozilla/5.0 (compatible; UZSE-Analytics-NewsBot/1.0)"


# --------------------------------------------------------------------------- #
# source loading + issuer universe
# --------------------------------------------------------------------------- #
def load_sources(only: str | None = None) -> list[dict[str, Any]]:
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    out = []
    for s in data.get("sources", []):
        if only and s.get("id") != only:
            continue
        if only or s.get("enabled"):
            out.append(s)
    return out


def build_universe() -> dict[str, str]:
    """ticker → company name, for constraining the classifier's ticker tags."""
    universe: dict[str, str] = {}
    try:
        conn = rc.get_catalog_conn()
        for r in conn.execute("SELECT ticker, company_name FROM catalog_companies").fetchall():
            if r["ticker"]:
                universe[r["ticker"].upper()] = r["company_name"] or r["ticker"]
        conn.close()
    except Exception:  # noqa: BLE001 — fall back to the static catalog
        logger.exception("catalog universe query failed; using static catalog")
    if not universe:
        universe = {t.upper(): n for t, n in rc._TICKER_TO_NAME.items()}
    return universe


# --------------------------------------------------------------------------- #
# fetchers (one per source type)
# --------------------------------------------------------------------------- #
def _iso(struct_time: Any) -> str | None:
    if not struct_time:
        return None
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", struct_time)
    except (TypeError, ValueError):
        return None


def fetch_rss(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    try:
        import feedparser  # lazy: not needed unless an RSS source is enabled
    except ImportError:
        logger.error("feedparser is not installed — run: pip install feedparser")
        return []
    ua = source.get("user_agent", DEFAULT_UA)
    feed = feedparser.parse(source["url"], request_headers={"User-Agent": ua})
    items: list[dict[str, Any]] = []
    for e in feed.entries[:limit]:
        url = (getattr(e, "link", "") or "").strip()
        if not url:
            continue
        items.append({
            "url": url,
            "title": (getattr(e, "title", "") or "").strip(),
            # RSS 'summary' is the source's own short description — snippet, not body.
            "snippet": (getattr(e, "summary", "") or "").strip()[:1000],
            "published_at": _iso(getattr(e, "published_parsed", None))
            or _iso(getattr(e, "updated_parsed", None)),
            "lang": (source.get("lang") or ["ru"])[0],
        })
    return items


def fetch_openinfo(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """openinfo material facts. Reuses the repo's openinfo session/helper.

    The exact facts endpoint is deployment-specific; set ``OPENINFO_FACTS_ENDPOINT``
    (path under the api base, e.g. ``/disclosure/facts/``). Best-effort: on any
    failure it logs and returns [] so the rest of the run proceeds.
    """
    endpoint = os.getenv("OPENINFO_FACTS_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("openinfo facts adapter idle: set OPENINFO_FACTS_ENDPOINT to enable")
        return []
    try:
        from openinfo_collector import _json_get, _make_session
        session = _make_session()
        data = _json_get(session, endpoint, {"page_size": limit})
    except Exception as exc:  # noqa: BLE001
        logger.warning("openinfo facts fetch failed: %s", exc)
        return []
    results = data.get("results") if isinstance(data, dict) else data
    items: list[dict[str, Any]] = []
    for rec in (results or [])[:limit]:
        url = rec.get("url") or rec.get("source_url") or ""
        title = rec.get("title") or rec.get("fact_type") or rec.get("name") or ""
        if not url or not title:
            continue
        items.append({
            "url": str(url), "title": str(title).strip(),
            "snippet": str(rec.get("description") or "")[:1000],
            "published_at": rec.get("published_at") or rec.get("pub_date"),
            "lang": "ru",
        })
    return items


def fetch_pending(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """html (sitemap scrape) and telegram adapters — not yet implemented."""
    logger.info("source '%s' (%s) adapter pending — skipped", source["id"], source["type"])
    return []


_FETCHERS = {"rss": fetch_rss, "openinfo": fetch_openinfo, "html": fetch_pending, "telegram": fetch_pending}


# --------------------------------------------------------------------------- #
# push
# --------------------------------------------------------------------------- #
def push_news(items: list[dict[str, Any]]) -> int:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        logger.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    url = DEFAULT_PUSH_URL + "/api/admin/news"
    resp = requests.post(url, json={"items": items}, headers={"X-Admin-Secret": secret}, timeout=120)
    if resp.status_code != 200:
        logger.error("push /api/admin/news failed: HTTP %s %s", resp.status_code, resp.text[:300])
        return 1
    logger.info("push /api/admin/news ok: %s", resp.json())
    return 0


# --------------------------------------------------------------------------- #
# main run
# --------------------------------------------------------------------------- #
def run(*, only: str | None = None, limit: int = 40, push: bool = True, dry_run: bool = False) -> dict[str, Any]:
    sources = load_sources(only)
    universe = build_universe()
    logger.info("collecting from %d source(s); issuer universe = %d tickers", len(sources), len(universe))

    # 1) fetch everything, then filter to genuinely-new URLs (skip re-classify).
    raw: list[dict[str, Any]] = []
    for src in sources:
        fetcher = _FETCHERS.get(src["type"], fetch_pending)
        try:
            fetched = fetcher(src, limit)
        except Exception:  # noqa: BLE001 — one source must not kill the run
            logger.exception("fetch failed for %s", src["id"])
            fetched = []
        for it in fetched:
            it["source"] = src["name"]
            it["source_id"] = src["id"]
            it["coverage_weight"] = src.get("coverage_weight", 0.5)
        logger.info("  %s: %d items", src["id"], len(fetched))
        raw.extend(fetched)
        time.sleep(min(src.get("crawl_delay_s", 2), 5) if len(sources) > 1 else 0)

    seen = news_store.existing_urls([it["url"] for it in raw])
    fresh = [it for it in raw if it["url"] not in seen]
    logger.info("fetched %d, %d already stored, %d new to classify", len(raw), len(seen), len(fresh))

    # 2) classify each new item (Layer A).
    from llm_client import Usage
    usage = Usage()
    model = os.getenv("LLM_MODEL", "deepseek-v4-flash")
    records: list[dict[str, Any]] = []
    for it in fresh:
        cls = classify_item(it, universe, usage=usage)
        record = {**it, "model": model, **cls.model_dump()}
        records.append(record)
    relevant = [r for r in records if r.get("relevant")]
    logger.info("classified %d items (%d relevant); ~%d tokens, est $%.4f",
                len(records), len(relevant), usage.total_tokens, usage.est_cost_usd())

    if dry_run:
        for r in records:
            print(json.dumps({k: r.get(k) for k in
                              ("source_id", "relevant", "type", "tone", "impact", "direction",
                               "tickers", "title", "summary_ru")},
                             ensure_ascii=False))
        return {"fetched": len(raw), "new": len(fresh), "relevant": len(relevant), "dry_run": True}

    # 3) store locally (dedup memory) + push to prod.
    stored = news_store.upsert_news(records)
    pushed = 0
    if push and records:
        code = push_news(records)
        pushed = len(records) if code == 0 else 0
    return {
        "fetched": len(raw), "new": len(fresh), "classified": len(records),
        "relevant": len(relevant), "stored": stored, "pushed": pushed,
        "tokens": usage.total_tokens, "est_cost_usd": round(usage.est_cost_usd(), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect, classify, and push Uzbek market news.")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=40, help="max items per source")
    ap.add_argument("--no-push", action="store_true", help="store locally, do not push to prod")
    ap.add_argument("--dry-run", action="store_true", help="fetch+classify, print, do not store/push")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(only=args.source, limit=args.limit, push=not args.no_push, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
