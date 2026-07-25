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
    python news_collector.py --backfill-images  # images for stored items (no LLM calls)
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv

# Before the repo imports: reports_catalog resolves DB paths and llm_client reads the
# API key at import time, and the push needs ADMIN_API_SECRET. Without this, a CLI run
# from a fresh shell silently has no LLM key (every item → classification_failed) and
# no push credentials — the failure mode the collector docs describe.
load_dotenv()

import news_store  # noqa: E402  (after load_dotenv)
import reports_catalog as rc  # noqa: E402  (after load_dotenv)
from news_classifier import classify_item  # noqa: E402  (after load_dotenv)

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


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_text(value: Any) -> str:
    """Feed text → plain text: unescape entities, drop markup, collapse whitespace.

    Feeds are inconsistent: spot/gazeta double-escape (``&amp;nbsp;`` arrives as a
    literal ``&nbsp;``) and several embed an ``<img>`` in the description. Stored raw,
    that renders as visible entity/tag noise in the card and pollutes classifier input.
    """
    if not value:
        return ""
    text = _TAG_RE.sub(" ", html.unescape(html.unescape(str(value))))
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


def _rss_image(entry: Any) -> str | None:
    """Best-effort thumbnail from a feed entry — media:content/thumbnail, an
    enclosure, or an <img> the source embedded in its own summary/content. This only
    ever uses the source's OWN published image (see ``_og_image`` for the fallback
    when a feed ships none)."""
    for attr in ("media_content", "media_thumbnail"):
        media = getattr(entry, attr, None)
        if isinstance(media, list):
            for m in media:
                u = (m.get("url") or "").strip()
                if u:
                    return u
    for enc in (getattr(entry, "enclosures", None) or []):
        u = (enc.get("href") or enc.get("url") or "").strip()
        typ = enc.get("type") or ""
        if u and (typ.startswith("image") or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", u, re.I)):
            return u
    for lk in (getattr(entry, "links", None) or []):
        if lk.get("rel") == "enclosure":
            u = (lk.get("href") or "").strip()
            typ = lk.get("type") or ""
            if u and (typ.startswith("image") or re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", u, re.I)):
                return u
    for field in ("content", "summary"):
        val = getattr(entry, field, None)
        if isinstance(val, list) and val:
            val = (val[0] or {}).get("value")
        if isinstance(val, str):
            m = re.search(r'<img[^>]+src=["\']([^"\']+)', val)
            if m:
                return m.group(1).strip()
    return None


# ── preview images ────────────────────────────────────────────────────────── #
# Several feeds carry no <media:*>/enclosure at all (kursiv, cbu, kun) even though
# the article page publishes a preview image for link unfurls — the og:image meta
# tag. For sources flagged ``"page_image": true`` we read the page's <head> and take
# that URL. Only the head is read (the response is streamed and cut at </head>) and
# only the image URL is kept — no article text is downloaded or stored, so the legal
# invariant (headline + our own summary + link) is unchanged.
_OG_IMAGE_PATTERNS = (
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url|:secure_url)?|twitter:image(?::src)?)["\']'
    r'[^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)='
    r'["\'](?:og:image(?::url|:secure_url)?|twitter:image(?::src)?)["\']',
)
# A site-wide share card (cbu.uz serves one social.jpg for every article) is worse
# than no image: the same picture would repeat down the whole feed. Skip those.
_GENERIC_IMAGE_RE = re.compile(
    r"(?:^|[/_-])(?:social|share|default|placeholder|logo|preview|banner|no[_-]?image)[\w-]*"
    r"\.(?:jpe?g|png|webp|gif|svg)$", re.I)
_HEAD_MAX_BYTES = 150_000


def _og_image(session: requests.Session, page_url: str, timeout: int = 15) -> str | None:
    """The article page's own preview image (og:image / twitter:image), or None."""
    try:
        resp = session.get(page_url, timeout=timeout, stream=True)
        if resp.status_code != 200:
            resp.close()
            return None
        buf = bytearray()
        for chunk in resp.iter_content(8192):
            buf += chunk
            if len(buf) >= _HEAD_MAX_BYTES or b"</head" in buf.lower():
                break
        resp.close()
    except requests.RequestException as exc:
        logger.debug("page-image fetch failed for %s: %s", page_url, exc)
        return None
    head = bytes(buf).decode("utf-8", "replace")
    for pattern in _OG_IMAGE_PATTERNS:
        match = re.search(pattern, head, re.I)
        if not match:
            continue
        img = urljoin(page_url, html.unescape(match.group(1).strip()))
        if not img.lower().startswith(("http://", "https://")):
            return None
        if _GENERIC_IMAGE_RE.search(urlparse(img).path):
            logger.debug("ignoring site-wide share image %s", img)
            return None
        return img
    return None


def enrich_images(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]],
                  *, max_fetch: int | None = None) -> int:
    """Fill ``image_url`` from the article page for items whose feed shipped none.

    Opt-in per source (``"page_image": true``), paced by that source's
    ``crawl_delay_s``, and capped per run (``NEWS_OG_MAX_FETCH``, default 40) so a
    large batch can never turn into a crawl. Returns the number of images found.
    """
    if max_fetch is None:
        max_fetch = int(os.getenv("NEWS_OG_MAX_FETCH", "40"))
    todo = [it for it in items
            if it.get("url") and not it.get("image_url")
            and (sources.get(it.get("source_id")) or {}).get("page_image")]
    if not todo or max_fetch <= 0:
        return 0
    if len(todo) > max_fetch:
        logger.info("page-image pass: %d candidate(s); fetching %d (NEWS_OG_MAX_FETCH), "
                    "the rest keep the category placeholder", len(todo), max_fetch)
    session = requests.Session()
    last_hit: dict[str, float] = {}
    filled = 0
    for it in todo[:max_fetch]:
        src = sources.get(it.get("source_id")) or {}
        session.headers["User-Agent"] = src.get("user_agent", DEFAULT_UA)
        host = urlparse(it["url"]).netloc
        if host in last_hit:
            wait = float(src.get("crawl_delay_s", 2) or 0) - (time.monotonic() - last_hit[host])
            if wait > 0:
                time.sleep(min(wait, 30))
        last_hit[host] = time.monotonic()
        img = _og_image(session, it["url"])
        if img:
            it["image_url"] = img
            filled += 1
    session.close()
    logger.info("page-image pass: %d of %d fetched item(s) got an image",
                filled, min(len(todo), max_fetch))
    return filled


def _is_recent(published_at: Any, max_age_days: int) -> bool:
    """True if within the freshness window. Undated / unparseable items are KEPT
    (we skip on proven age, never on a missing date)."""
    if not published_at:
        return True
    s = str(published_at).replace("T", " ").strip()
    dt = None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19] if fmt.endswith("%S") else s[:10], fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return True
    return (datetime.now() - dt).days <= max_age_days


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
            "title": _clean_text(getattr(e, "title", "")),
            # RSS 'summary' is the source's own short description — snippet, not body.
            "snippet": _clean_text(getattr(e, "summary", ""))[:1000],
            "published_at": _iso(getattr(e, "published_parsed", None))
            or _iso(getattr(e, "updated_parsed", None)),
            # "feed_image": false opts a source out entirely (its ToS bars media reuse).
            "image_url": _rss_image(e) if source.get("feed_image", True) else None,
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


def push_images(images: dict[str, str]) -> int:
    """Push image-only updates (url → image_url) and return the rows prod changed.

    Deliberately NOT /api/admin/news: a full upsert there would rewrite the stored
    classification from these image-only records and hide the items from the feed.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        logger.error("ADMIN_API_SECRET is not set — cannot push images")
        return 0
    try:
        resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/images",
                             json={"images": images},
                             headers={"X-Admin-Secret": secret}, timeout=120)
    except requests.RequestException as exc:
        logger.error("push /api/admin/news/images failed: %s", exc)
        return 0
    if resp.status_code != 200:
        logger.error("push /api/admin/news/images failed: HTTP %s %s",
                     resp.status_code, resp.text[:300])
        return 0
    try:
        updated = int((resp.json() or {}).get("updated") or 0)
    except ValueError:
        logger.error("push /api/admin/news/images: non-JSON 200 body")
        return 0
    logger.info("push /api/admin/news/images ok: %d row(s) updated in prod", updated)
    return updated


# --------------------------------------------------------------------------- #
# image backfill (no LLM calls)
# --------------------------------------------------------------------------- #
def _source_registry() -> dict[str, dict[str, Any]]:
    """id → source config for EVERY registered source, enabled or not: a stored item
    may come from a source that has since been disabled."""
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data.get("sources", []) if s.get("id")}


def _prod_items_without_image(days: int) -> list[dict[str, Any]]:
    """Backfill candidates read from prod's public feed — the rows users actually see
    (the local DB can lag behind it, e.g. items pushed from another host)."""
    try:
        resp = requests.get(f"{DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("could not read the prod feed for backfill candidates: %s", exc)
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
    logger.info("image backfill: %d from the prod feed + %d local-only candidate(s)",
                len(remote), len(candidates) - len(remote))
    # Anything a previous run already fetched is reused, not fetched again — a re-run
    # (e.g. after a failed push) costs no requests.
    for url, img in news_store.image_urls_for(list(candidates)).items():
        candidates[url]["image_url"] = img
    items = list(candidates.values())[:limit]
    found = enrich_images(items, _source_registry(), max_fetch=limit)
    images = {it["url"]: it["image_url"] for it in items if it.get("image_url")}
    return {
        "candidates": len(items), "found": found,
        "updated_local": news_store.set_image_urls(images),
        "updated_prod": push_images(images) if (push and images) else 0,
    }


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

    # Skip stale news up front — never classify (or pay for) anything older than the
    # freshness window. Undated items are kept (see _is_recent).
    max_age = int(os.getenv("NEWS_MAX_AGE_DAYS", "30"))
    before_age = len(raw)
    raw = [it for it in raw if _is_recent(it.get("published_at"), max_age)]
    if before_age != len(raw):
        logger.info("recency filter: dropped %d item(s) older than %d days", before_age - len(raw), max_age)

    seen = news_store.existing_urls([it["url"] for it in raw])
    fresh = [it for it in raw if it["url"] not in seen]
    logger.info("fetched %d, %d already stored, %d new to classify", len(raw), len(seen), len(fresh))

    # 2) classify each new item (Layer A).
    from llm_client import Usage
    usage = Usage()
    model = os.getenv("LLM_MODEL", "grok-4.3")
    records: list[dict[str, Any]] = []
    failed = 0
    for it in fresh:
        cls = classify_item(it, universe, usage=usage)
        # A failed classification (no API key, quota, outage) is NOT stored: URL dedup
        # would then bury the item as irrelevant forever. Left unstored, it is simply
        # re-fetched and re-classified on the next run.
        if cls.reason == "classification_failed":
            failed += 1
            continue
        records.append({**it, "model": model, **cls.model_dump()})
    if failed:
        logger.warning("%d item(s) failed classification — not stored, will retry next run", failed)
    relevant = [r for r in records if r.get("relevant")]
    logger.info("classified %d items (%d relevant); ~%d tokens, est $%.4f",
                len(records), len(relevant), usage.total_tokens, usage.est_cost_usd())

    # 2b) preview images, for the RELEVANT items only: those are the cards the feed
    # renders, and a whole-site feed like kursiv's is ~85% off-topic — fetching pages
    # for items about to be filtered out would be almost all of the requests.
    enrich_images(relevant, {s["id"]: s for s in sources})

    if dry_run:
        for r in records:
            print(json.dumps({k: r.get(k) for k in
                              ("source_id", "relevant", "type", "tone", "impact", "direction",
                               "tickers", "title", "summary_ru")},
                             ensure_ascii=False))
        return {"fetched": len(raw), "new": len(fresh), "relevant": len(relevant),
                "with_image": sum(1 for r in relevant if r.get("image_url")), "dry_run": True}

    # 3) store locally (dedup memory) + push to prod.
    stored = news_store.upsert_news(records)
    pushed = 0
    if push and records:
        code = push_news(records)
        pushed = len(records) if code == 0 else 0
    return {
        "fetched": len(raw), "new": len(fresh), "classified": len(records),
        "classify_failed": failed, "with_image": sum(1 for r in relevant if r.get("image_url")),
        "relevant": len(relevant), "stored": stored, "pushed": pushed,
        "tokens": usage.total_tokens, "est_cost_usd": round(usage.est_cost_usd(), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect, classify, and push Uzbek market news.")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=40, help="max items per source")
    ap.add_argument("--no-push", action="store_true", help="store locally, do not push to prod")
    ap.add_argument("--dry-run", action="store_true", help="fetch+classify, print, do not store/push")
    ap.add_argument("--backfill-images", action="store_true",
                    help="fill preview images on already-stored items (no LLM calls)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.backfill_images:
        result = backfill_images(limit=args.limit, push=not args.no_push)
    else:
        result = run(only=args.source, limit=args.limit, push=not args.no_push, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
