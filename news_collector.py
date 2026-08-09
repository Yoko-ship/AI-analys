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
    python news_collector.py --backfill-translations  # EN/UZ summaries for older rows
    python news_collector.py --backfill-details  # story-page long read (1 call/item)
    python news_collector.py --backfill-facts   # figures for stored filings (no LLM calls)
    python news_collector.py --purge-failed   # drop failed classifications so they retry
    python news_collector.py --rejudge thediplomat  # re-judge one source's rejected items
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlparse, urlsplit, urlunsplit

import requests
from dotenv import load_dotenv

# Before the repo imports: reports_catalog resolves DB paths and llm_client reads the
# API key at import time, and the push needs ADMIN_API_SECRET. Without this, a CLI run
# from a fresh shell silently has no LLM key (every item → classification_failed) and
# no push credentials — the failure mode the collector docs describe.
load_dotenv()

import news_lang  # noqa: E402  (after load_dotenv)
import news_store  # noqa: E402  (after load_dotenv)
import reports_catalog as rc  # noqa: E402  (after load_dotenv)
from news_classifier import (  # noqa: E402  (after load_dotenv)
    NewsClassification,
    classify_filings,
    classify_items,
    prefilter_reject,
    screen_items,
    translate_summaries,
    write_brief_detail,
    write_detail,
)
from runtime_preflight import NEWS_REQUIREMENTS, preflight  # noqa: E402  (after load_dotenv)

logger = logging.getLogger(__name__)

SOURCES_FILE = Path(__file__).resolve().parent / "news_sources.json"
DEFAULT_PUSH_URL = os.getenv(
    "NEWS_PUSH_URL",
    os.getenv("FINANCIALS_PUSH_URL", "https://ai-analys-production.up.railway.app"),
).rstrip("/")
DEFAULT_UA = "Mozilla/5.0 (compatible; UZSE-Analytics-NewsBot/1.0)"


def _source_headers(source: dict[str, Any]) -> dict[str, str]:
    """Request headers for one source: our UA unless it overrides, plus any it declares.

    Some publishers sit behind an edge that answers 403 to anything not shaped like a
    browser — S&P Global rejects a bare User-Agent (ours *or* a Chrome string) and serves
    the same sitemap its own robots.txt advertises the moment the usual browser navigation
    headers come with it. ``headers`` in the registry is that, per source and written down
    next to the evidence, rather than a global disguise.
    """
    headers = {"User-Agent": source.get("user_agent", DEFAULT_UA)}
    headers.update({str(k): str(v) for k, v in (source.get("headers") or {}).items()})
    return headers


# --------------------------------------------------------------------------- #
# source loading + issuer universe
# --------------------------------------------------------------------------- #
def load_sources(only: str | None = None) -> list[dict[str, Any]]:
    """The sources a run collects from.

    ``paywall: true`` is skipped even when the source is still enabled: the read path hides
    those items (``news_store.paywalled_source_ids``), so collecting them would spend a
    classifier call per item on cards nobody will ever be shown. Naming the source explicitly
    (``--source trend``) still works — that is how you check a source you are considering
    bringing back.
    """
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    out = []
    for s in data.get("sources", []):
        if only and s.get("id") != only:
            continue
        if only:
            out.append(s)
        elif s.get("enabled") and not s.get("paywall"):
            out.append(s)
    return out


def _prod_request(method: str, path: str, *, attempts: int = 3, timeout: int = 60,
                  **kwargs: Any) -> Any | None:
    """An admin call to prod, retried with backoff. Returns the parsed body, or None.

    Both callers degrade gracefully on None, but degrading is not free: a single 502 while the
    API happens to be redeploying would otherwise cost this run its whole openinfo feed, or
    make it re-classify everything it could not confirm as already stored.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        return None
    url = DEFAULT_PUSH_URL + path
    delay = 5.0
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, headers={"X-Admin-Secret": secret},
                                    timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == attempts:
                logger.warning("prod %s %s failed after %d attempt(s): %s",
                               method, path, attempts, exc)
                return None
            logger.info("prod %s %s failed (%s); retrying in %.0fs", method, path, exc, delay)
            time.sleep(delay)
            delay *= 3
    return None


_prod_issuers: list[dict[str, Any]] | None = None


def issuers_from_prod() -> list[dict[str, Any]]:
    """The issuer catalog (ticker, name, openinfo org_id) read from prod, cached per process.

    A scheduled run has an empty database of its own — a Railway volume mounts to one service
    only — so without this the classifier would fall back to the static ticker list and
    openinfo filings could not be attributed to a ticker at all.
    """
    global _prod_issuers
    if _prod_issuers is not None:
        return _prod_issuers
    body = _prod_request("GET", "/api/admin/catalog/issuers")
    _prod_issuers = (body or {}).get("issuers") or []
    if _prod_issuers:
        logger.info("issuer catalog from prod: %d ticker(s), %d with an openinfo org_id",
                    len(_prod_issuers), sum(1 for i in _prod_issuers if i.get("org_id")))
    return _prod_issuers


def build_universe() -> dict[str, str]:
    """ticker → company name, for constraining the classifier's ticker tags.

    Local catalog first, then prod, then the static list — so a container with no database of
    its own still classifies against the real universe rather than a stale snapshot.
    """
    universe: dict[str, str] = {}
    try:
        conn = rc.get_catalog_conn()
        for r in conn.execute("SELECT ticker, company_name FROM catalog_companies").fetchall():
            if r["ticker"]:
                universe[r["ticker"].upper()] = r["company_name"] or r["ticker"]
        conn.close()
    except Exception:  # noqa: BLE001 — fall back below
        logger.exception("catalog universe query failed; trying prod")
    if not universe:
        universe = {str(r["ticker"]).upper(): (r.get("company_name") or r["ticker"])
                    for r in issuers_from_prod() if r.get("ticker")}
        if universe:
            logger.info("issuer universe: %d ticker(s) from prod (no local catalog)", len(universe))
    if not universe:
        logger.warning("no catalog locally or in prod — falling back to the static ticker list")
        universe = {t.upper(): n for t, n in rc._TICKER_TO_NAME.items()}
    return universe


# --------------------------------------------------------------------------- #
# fetchers (one per source type)
# --------------------------------------------------------------------------- #
_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|yclid|_openstat|from|ref)$", re.I)


def _canonical_url(url: str) -> str:
    """Drop tracking params and the trailing slash so dedup sees one article once.

    Kursiv's feed appends ``?utm_source=rss&utm_medium=rss&utm_campaign=<slug>``: if a
    campaign slug ever changes, exact-URL dedup treats the same article as new and we pay
    to classify it again. Fragments and default ports go too; nothing else is touched, so
    the link still resolves at the source.
    """
    url = (url or "").strip()
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    query = "&".join(f"{k}={v}" for k, v in parse_qsl(parts.query, keep_blank_values=True)
                     if not _TRACKING_PARAMS.match(k))
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, query, ""))


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
# How many stored items the end-of-run retry pass may fetch. Small on purpose: it runs
# every day, so an item that misses today is tried again tomorrow rather than the whole
# backlog being hammered in one pass. The manual `--backfill-images` run is uncapped by
# comparison (`--limit`), for when a source is fixed and the backlog should clear at once.
_BACKFILL_IMAGE_CAP = int(os.getenv("NEWS_BACKFILL_IMAGE_CAP", "12"))


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


def _upgrade_image(session: requests.Session, url: str, source: dict[str, Any]) -> str:
    """The full-size original behind a feed's thumbnail, or ``url`` unchanged.

    Several CMSs put a small derivative in the RSS and keep the real photograph one name
    away: uza.uz ships ``…_small.jpg`` at 320px while ``…_normal.jpg`` is 1024px, spot.uz
    ships ``…_b.jpg`` at 680px against ``…_l.jpg`` at 1200px. A 320px picture stretched across
    a 950px article column is visibly soft, which is what a reader sees and reports.

    The rewrite is a per-source rule in the registry (``image_upgrade``), and it is never
    trusted: the candidate is verified to exist and to be an image before it replaces
    anything, so a CMS that renames its derivatives degrades to the thumbnail we had.
    """
    rule = source.get("image_upgrade") or {}
    pattern, repl = rule.get("from"), rule.get("to")
    if not url or not pattern or not repl:
        return url
    candidate = re.sub(pattern, repl, url)
    if candidate == url:
        return url
    try:
        resp = session.head(candidate, timeout=15, allow_redirects=True)
        if resp.status_code in (403, 405, 501):  # HEAD not served — ask for one byte instead
            resp = session.get(candidate, timeout=15, headers={"Range": "bytes=0-1023"},
                               stream=True)
            resp.close()
        ok = (resp.status_code in (200, 206)
              and (resp.headers.get("content-type") or "").lower().startswith("image/"))
    except requests.RequestException as exc:
        logger.debug("image upgrade check failed for %s: %s", candidate, exc)
        return url
    return candidate if ok else url


def upgrade_images(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> int:
    """Swap every thumbnail we can for its full-size original, in place. Returns the count."""
    todo = [it for it in items
            if it.get("image_url") and (sources.get(it.get("source_id")) or {}).get("image_upgrade")]
    if not todo:
        return 0
    session = requests.Session()
    upgraded = 0
    for it in todo:
        src = sources.get(it.get("source_id")) or {}
        session.headers.update(_source_headers(src))
        better = _upgrade_image(session, it["image_url"], src)
        if better != it["image_url"]:
            it["image_url"] = better
            upgraded += 1
    session.close()
    if upgraded:
        logger.info("image upgrade: %d of %d thumbnail(s) replaced with the full-size original",
                    upgraded, len(todo))
    return upgraded


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


# --------------------------------------------------------------------------- #
# the long read (story page body)
# --------------------------------------------------------------------------- #
# How many article pages one run may open for the detail pass. Each one costs a page fetch
# and a model call, and the pass runs daily, so an item that misses today is picked up
# tomorrow rather than the backlog being hammered at once — the same reasoning as the image
# retry cap above.
#
# 12 was BELOW the inflow, which is a different thing from a cap: the feed takes 16-36
# relevant items a day, so the pass could never converge, and a newest-first work list meant
# the shortfall always landed on the same (older) items. Measured before this changed: 18 of
# 148 eligible items had a long read and all eighteen were from the last two days. 40 clears
# a normal day and leaves room to drain the backlog; the tail share below is what guarantees
# the draining even when a day overruns it.
_DETAIL_CAP = int(os.getenv("NEWS_DETAIL_CAP", "40"))
# What fraction of a run is spent on the OLDEST items without a long read rather than the
# newest. Without it the newest-first list is self-perpetuating — see
# news_store.rows_without_detail.
_DETAIL_TAIL_SHARE = float(os.getenv("NEWS_DETAIL_TAIL_SHARE", "0.35"))
_ARTICLE_MAX_BYTES = 900_000
# Markup that is never article prose. Dropped before the paragraphs are collected, or a
# cookie banner and a "read also" rail end up in the text handed to the model.
_ARTICLE_STRIP = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form",
                  "figure", "figcaption", "iframe", "button", "svg")
# Where the body usually is, best guess first. Falls back to the whole document, which is why
# the paragraph filter below has to stand on its own.
_ARTICLE_ROOTS = ("article", "main", "[itemprop='articleBody']", ".article-content",
                  ".article__content", ".entry-content", ".post-content", ".news-content",
                  ".content__text", "#content")


def _article_text(session: requests.Session, page_url: str, timeout: int = 20) -> str:
    """The readable prose of one article page — held in memory, never stored.

    This is the one place the collector reads a source's body text, and what it is read FOR
    is a model call that writes our own account of it (``news_classifier.write_detail``). The
    text itself does not enter the database, is not pushed, and is not returned to any
    reader; that is what keeps the legal invariant (headline + our own summary + link) intact
    while still giving the story page more than a one-sentence teaser.

    Deliberately dumb extraction: take the paragraphs of the likeliest container and drop the
    short ones. A wrong guess yields navigation noise, which ``write_detail`` is instructed to
    answer with empty strings rather than an invented article.
    """
    try:
        from bs4 import BeautifulSoup  # lazy: only this pass needs it
    except ImportError:
        logger.error("beautifulsoup4 is not installed — run: pip install beautifulsoup4")
        return ""
    try:
        resp = session.get(page_url, timeout=timeout)
        if resp.status_code != 200:
            return ""
        raw = resp.content[:_ARTICLE_MAX_BYTES]
    except requests.RequestException as exc:
        logger.debug("article fetch failed for %s: %s", page_url, exc)
        return ""
    soup = BeautifulSoup(raw.decode(resp.encoding or "utf-8", "replace"), "html.parser")
    for tag in soup(list(_ARTICLE_STRIP)):
        tag.decompose()
    root = None
    for selector in _ARTICLE_ROOTS:
        root = soup.select_one(selector)
        if root is not None:
            break
    paragraphs = [_clean_text(p.get_text(" ", strip=True))
                  for p in (root or soup).find_all("p")]
    # 80 chars keeps datelines, share prompts, photo credits and menu items out while
    # keeping every real paragraph: the shortest genuine one measured across our sources
    # (uza.uz, trend.az, kursiv, spot) was 118.
    body = [p for p in paragraphs if len(p) >= 80]
    return "\n\n".join(body)


def has_article_page(item: dict[str, Any], sources: dict[str, dict[str, Any]]) -> bool:
    """Whether this item's source publishes a body we can read.

    ``article_body: false`` is the flag for that, and it is the ONLY flag for it. This used
    to also treat ``content: "none"`` as "no article page", which conflates two different
    facts: `content` describes what the LISTING or feed ships, `article_body` what stands
    behind the link. They coincide for the rating agencies, so the conflation went unnoticed
    — but napp.uz ships no snippet on its listing page and perfectly readable articles behind
    it (measured 2026-08-09: 756, 1449 and 1084 characters of prose), and every one of its
    regulatory items was being written off as bodyless because of it.

    An openinfo filing is the separate case: it has no page of its own at all, the portal
    404s every per-fact URL.
    """
    src = sources.get(item.get("source_id")) or {}
    return bool(item.get("url")) and not (
        src.get("type") == "openinfo" or src.get("article_body") is False)


def enrich_details(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]],
                   *, max_fetch: int | None = None,
                   usage: Any = None) -> dict[str, dict[str, str]]:
    """``{url: {"ru":…,"en":…,"uz":…}}`` — our own long read, by whichever route an item has.

    Two routes, because "open the source's article page" only exists for some of them:

    * the source publishes a body — read it once, in memory, and have the model write our
      own account of it (:func:`news_classifier.write_detail`);
    * it does not — an openinfo filing or a headline-only source — lay out the material we
      already hold, the disclosure's own figures and our summary
      (:func:`news_classifier.write_brief_detail`), which adds no fact and may return
      nothing when there is nothing to lay out.

    Before this second route, a third of the feed could never have a body at all: 36 of the
    200 items on the live feed are openinfo filings, and a filing's figures are exactly the
    part a holder opens the page for.
    """
    if max_fetch is None:
        max_fetch = _DETAIL_CAP
    todo, brief = [], []
    for it in items:
        (todo if has_article_page(it, sources) else brief).append(it)
    if max_fetch <= 0 or not (todo or brief):
        return {}
    out: dict[str, dict[str, str]] = {}
    # ONE budget across both routes, or a cap of 40 quietly means 80 model calls on a day
    # with filings AND articles. Half each when both have work, and whatever one route does
    # not spend is left to the other.
    brief = [it for it in brief if it.get("url")]        # the url is the write key
    brief_budget = max_fetch if not todo else max(1, max_fetch // 2)
    thin = 0
    for it in brief[:brief_budget]:
        detail = write_brief_detail(it, usage=usage)
        if detail.get("ru"):
            out[it["url"]] = detail
        else:
            thin += 1
    if brief:
        logger.info("detail pass: %d item(s) with no article page; %d laid out from stored "
                    "material%s", len(brief), len(out),
                    f", {thin} too thin to state anything" if thin else "")
    max_fetch -= min(len(brief), brief_budget)
    if not todo or max_fetch <= 0:
        return out
    if len(todo) > max_fetch:
        logger.info("detail pass: %d candidate(s) with an article; reading %d this run "
                    "(NEWS_DETAIL_CAP), the rest on the next one", len(todo), max_fetch)
    session = requests.Session()
    last_hit: dict[str, float] = {}
    empty = wrote = fell_back = 0
    for it in todo[:max_fetch]:
        src = sources.get(it.get("source_id")) or {}
        session.headers.update(_source_headers(src))
        host = urlparse(it["url"]).netloc
        if host in last_hit:
            wait = float(src.get("crawl_delay_s", 2) or 0) - (time.monotonic() - last_hit[host])
            if wait > 0:
                time.sleep(min(wait, 30))
        last_hit[host] = time.monotonic()
        text = _article_text(session, it["url"])
        detail = write_detail(it, text, usage=usage) if text else {"ru": ""}
        # The page was there and gave us nothing readable — a paywall, an SPA shell, an
        # extraction miss. Falling back to the stored material is what stops such an item
        # from being retried forever and reaching the reader as a bare headline every time;
        # it costs the same one call the retry would have cost.
        if not detail.get("ru"):
            detail = write_brief_detail(it, usage=usage)
            fell_back += 1 if detail.get("ru") else 0
        if detail.get("ru"):
            out[it["url"]] = detail
            wrote += 1
        else:
            empty += 1
    session.close()
    logger.info("detail pass: %d of %d article(s) produced a long read%s%s",
                wrote, min(len(todo), max_fetch),
                f" ({fell_back} from stored material)" if fell_back else "",
                f", {empty} yielded nothing" if empty else "")
    return out


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
    feed = feedparser.parse(source["url"], request_headers=_source_headers(source))
    items: list[dict[str, Any]] = []
    for e in feed.entries[:limit]:
        url = (getattr(e, "link", "") or "").strip()
        if not url:
            continue
        items.append({
            "url": _canonical_url(url),
            # The feed's original link, so dedup can also match rows stored before URLs
            # were canonicalised (and we never re-pay for those).
            "raw_url": url,
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


# openinfo's public app is a Next.js SPA: the only working public route for a filing is the
# issuer's own page (verified 2026-07-25 — /ru/organizations/<id> is 200, every deeper
# /facts, /disclosure or /fact/<id> path 404s). The ?fact= hint is ignored by the app but
# keeps the URL unique per filing, which matters because news.url is the dedup key.
_OPENINFO_ORG_URL = "https://openinfo.uz/ru/organizations/{org}?fact={fact_id}"
# openinfo fact_number → our §3.11 class, so the taxonomy comes from the filing itself
# instead of being guessed by the model.
_FACT_TYPE_MAP = {
    32: "financial_report",   # начисление доходов по ценным бумагам
    42: "financial_report",   # дивиденды выплаченные
    49: "financial_report",   # рекомендация НС по распределению чистой прибыли
    50: "financial_report",   # дивиденды, выплаченные акционерам
    25: "corporate_event", 26: "corporate_event",   # выпуск ценных бумаг
    46: "corporate_event", 47: "corporate_event",   # листинг / делистинг
    6: "corporate_event", 7: "corporate_event",     # решения высшего органа управления
    8: "corporate_event", 9: "corporate_event",     # изменения в НС / исполнительном органе
    20: "corporate_event", 21: "corporate_event", 22: "corporate_event",  # крупные сделки
    31: "corporate_event", 36: "corporate_event", 37: "corporate_event",
    51: "corporate_event", 52: "corporate_event", 53: "corporate_event",
    15: "corporate_event", 16: "corporate_event", 17: "corporate_event",  # крупные кредиты
    18: "market", 19: "market",                      # изменение стоимости активов >10%
    14: "regulatory", 23: "regulatory", 24: "regulatory", 34: "regulatory",
    27: "regulatory", 28: "regulatory", 29: "regulatory", 30: "regulatory",
}


def _openinfo_ticker_map() -> dict[str, list[str]]:
    """openinfo organization id → our ticker(s). Several tickers can share one issuer
    (ordinary + preferred, e.g. UZNG/UZNGP), and a fact concerns all of its share classes."""
    mapping: dict[str, list[str]] = {}
    rows: list[Any] = []
    try:
        conn = rc.get_catalog_conn()
        rows = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id <> ''"
        ).fetchall()
        conn.close()
    except Exception:  # noqa: BLE001 — fall back to prod below
        logger.exception("could not read local catalog org ids; trying prod")
    if not rows:
        # A scheduled container has no catalog of its own; without this openinfo — the most
        # valuable source — would be skipped entirely on every scheduled run.
        rows = [r for r in issuers_from_prod() if r.get("org_id") and r.get("ticker")]
    for r in rows:
        mapping.setdefault(str(r["org_id"]).strip(), []).append(r["ticker"])
    return mapping


# Two fact types are filed as structured NUMBERS rather than prose, so their filings can be
# reported instead of merely announced:
#   32 "Начисление доходов по ценным бумагам" — the declaration, carrying the amount PER
#      SHARE or PER BOND, which is the figure a holder actually wants;
#   42 "Дивиденды, выплаченные акционерам"    — the payment report: declared vs actually paid,
#      what is still owed, and the issuer's own reason for not paying.
# Without this, a dividend only a third paid and one paid in full render as the identical flat
# headline. Every other fact type stays title-only: a second call would learn nothing new.
# The issuer's own words for why it did not pay. Kept short: it is a filing field, not an
# article, and the card needs the reason, not the paragraph.
_NON_PAYMENT_MAX = 220


def _amount_uz(value):
    """'161662245000.00' → '161 662 245 000 сум'; '612.1253' → '612,1253 сум'.

    Per-share amounts are filed to four decimals and totals to two, so trailing zeros are
    dropped rather than fixed at a width that would misrepresent one of them.
    """
    try:
        num = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    text = f"{num:,.4f}".replace(",", " ").rstrip("0").rstrip(".")
    return f"{text.replace('.', ',')} сум"


def _pct(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _ru_date(value):
    """'2026-07-24' → '24.07.2026'; anything else is returned as filed."""
    text = str(value or "").strip()[:10]
    if not text:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" if match else text


def _fmt_accrual(facts):
    fact = facts[0]
    """Fact 32 — the amount accrued per security, plus the payment window.

    Shares file ``sum_aksiya`` with the window in ``*_common_shares``; bonds file ``sum_per``
    with the window in ``*_other_securities`` (verified 2026-07-25 across AGAT CREDIT, CONTACT
    FINANCE, UZUM SARMOYA and ToshuyjoyLITI). The ``*2`` variants hold a second class, but the
    API's own naming does not separate ordinary from preferred reliably, so they are left out
    rather than guessed at and mislabelled.
    """
    if _pct(fact.get("sum_aksiya")):
        amount, unit = _amount_uz(fact.get("sum_aksiya")), "на акцию"
        start, end = fact.get("start_date_common_shares"), fact.get("end_date_common_shares")
        nominal = _pct(fact.get("one_procent"))
    elif _pct(fact.get("sum_per")):
        amount, unit = _amount_uz(fact.get("sum_per")), "на облигацию"
        start, end = (fact.get("start_date_other_securities"),
                      fact.get("end_date_other_securities"))
        nominal = _pct(fact.get("percentage_nominal"))
    else:
        return None
    if not amount:
        return None

    text = f"Начислено {amount} {unit}"
    if nominal:
        text += f" ({nominal:.2f}% номинала)"
    window = " — ".join(d for d in (_ru_date(start), _ru_date(end)) if d)
    if window:
        text += f", выплата {window}"
    return text + "."


def _fmt_dividend_payment(facts):
    fact = facts[0]
    """Fact 42 — declared vs actually paid, what is still owed, and why."""
    declared = _amount_uz(fact.get("overall_calculated_sum"))
    paid_pct = _pct(fact.get("overall_paid_percent"))
    parts = []
    if declared:
        parts.append(f"начислено {declared}")
    if paid_pct is not None:
        paid_sum = _amount_uz(fact.get("overall_paid_sum"))
        parts.append(f"выплачено {paid_pct:.2f}%" + (f" ({paid_sum})" if paid_sum else ""))
    end = _ru_date(fact.get("payment_end_date"))
    if end:
        parts.append(f"срок выплаты до {end}")
    if not parts:
        return None

    text = "Дивиденды: " + ", ".join(parts) + "."
    # The unpaid remainder carries the signal, so it gets its own sentence rather than being
    # buried in the list. Reported exactly as filed — several issuers file paid=0 alongside
    # debt=0, and inferring the shortfall would contradict their own numbers.
    debt_pct = _pct(fact.get("overall_debt_percent"))
    if debt_pct:
        debt_sum = _amount_uz(fact.get("overall_debt_sum"))
        text += f" Не выплачено {debt_pct:.2f}%" + (f" ({debt_sum})" if debt_sum else "") + "."
        reason = _clean_text(str(fact.get("non_payment_explanation") or "")).strip(" -—")
        if reason:
            text += f" Причина по данным эмитента: {reason[:_NON_PAYMENT_MAX]}"
            if len(reason) > _NON_PAYMENT_MAX:
                text += "…"
    return text


def _org_short(name):
    """'Общество с ограниченной ответственностью «Бухарский НПЗ»' → 'Бухарский НПЗ'.

    Counterparties are filed with their full legal form, which is most of the string and none
    of the information. The quoted trade name is what identifies the party.
    """
    text = _clean_text(str(name or "")).strip()
    if not text:
        return None
    quoted = re.search(r"[«\"]([^»\"]{2,})[»\"]", text)
    if quoted:
        return quoted.group(1).strip()
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _plural_ru(n, forms):
    """(1, 2-4, 5+) — 'сделка' / 'сделки' / 'сделок'. Machine-generated text still has to
    read like Russian, or the card looks broken."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def _join_few(values, limit=3):
    """'A, B, C и др.' — enough to see who is involved, not a wall of names."""
    seen = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    if not seen:
        return None
    head = ", ".join(seen[:limit])
    return head + (" и др." if len(seen) > limit else "")


def _fmt_transaction(facts):
    """Facts 20 / 21 — a major or related-party deal: with whom, for what, how much.

    A grouped day is aggregated rather than reported once: O'zbekneftgaz files eight
    related-party notices in an hour, and "eight deals totalling N" is the story — the count
    alone (which is all the card said before) is not.

    Fact 20 also files ``assets_issuer``, the deal's size as a share of the issuer's assets;
    that is the number that separates routine trading from a balance-sheet event, so it is
    kept whenever it is filed.
    """
    total, priced = 0.0, 0
    parties, subjects, assets_pct, when = [], [], None, None
    for f in facts:
        amount = _pct(str(f.get("transaction_amount") or "").replace(" ", ""))
        if amount:
            total += amount
            priced += 1
        parties.append(_org_short(f.get("name_counterparty")))
        subject = _clean_text(str(f.get("subject_matter") or "")).strip()
        if subject:
            subjects.append(subject if len(subject) <= 70 else subject[:69].rstrip() + "…")
        assets_pct = assets_pct or _pct(f.get("assets_issuer"))
        when = when or _ru_date(f.get("date_transaction"))

    who, what = _join_few(parties), _join_few(subjects, 2)
    if len(facts) == 1:
        parts = [p for p in (who and f"контрагент — {who}", what and f"предмет — {what}") if p]
        if priced:
            money = _amount_uz(round(total) if total >= 1000 else total)
            parts.append(f"сумма {money}" + (f" ({assets_pct:.2f}% активов)" if assets_pct else ""))
        if when:
            parts.append(f"дата {when}")
        return ("Сделка: " + ", ".join(parts) + ".") if parts else None

    parts = [f"{len(facts)} {_plural_ru(len(facts), ('сделка', 'сделки', 'сделок'))} за день"]
    if priced:
        rounded = round(total) if total >= 1000 else total
        parts.append(f"на {_amount_uz(rounded)}"
                     + (f" по {priced} из них" if priced < len(facts) else ""))
    text = ", ".join(parts) + "."
    if who:
        text += f" Контрагенты: {who.rstrip('.')}."
    if what:
        text += f" Предмет: {what.rstrip('.')}."
    return text


def _fmt_obligation(facts):
    """Fact 31 — the window in which the issuer must redeem or pay out on a security."""
    fact = facts[0]
    window = " — ".join(d for d in (_ru_date(fact.get("date_begin")),
                                    _ru_date(fact.get("date_end"))) if d)
    if not window:
        return None
    text = f"Срок исполнения обязательств: {window}."
    detail = _clean_text(str(fact.get("description_issuers_obligations") or "")).strip()
    if detail:
        text += f" {detail[:120]}" + ("…" if len(detail) > 120 else "")
    return text


def _fmt_meeting(facts):
    """Fact 6 — a shareholders'/board meeting: when it sat and how much of the register voted.

    The resolutions themselves are filed as arrays that are empty on most records, so only the
    facts that are consistently present are reported. Quorum is the one number here that says
    something on its own: on a register this concentrated, who turned up is a governance
    datapoint.
    """
    fact = facts[0]
    parts = []
    when = _ru_date(fact.get("date_transaction"))
    if when:
        parts.append(f"собрание {when}")
    quorum = _pct(fact.get("quorum_general"))
    if quorum:
        parts.append(f"кворум {quorum:.2f}%")
    minutes = _ru_date(fact.get("date_minutes"))
    if minutes:
        parts.append(f"протокол от {minutes}")
    return (", ".join(parts).capitalize() + ".") if parts else None


def _fmt_license(facts):
    """Fact 22 — which licence, from whom, and how long it runs."""
    fact = facts[0]
    activity = _clean_text(str(fact.get("type_activity") or "")).strip()
    number = _clean_text(str(fact.get("number_licensing") or "")).strip()
    parts = []
    if activity:
        parts.append(f"вид деятельности — {activity[:90]}")
    if number:
        parts.append(f"№ {number}")
    valid = _ru_date(fact.get("validity_license"))
    if valid:
        parts.append(f"действует до {valid}")
    return ("Лицензия: " + ", ".join(parts) + ".") if parts else None


# Only the fact types filed as STRUCTURED FIELDS are worth a second call; for every other type
# the detail adds nothing the headline does not already say, so it is never fetched.
# Deliberately absent: 8 (board changes) and 36 (affiliate lists). Their detail IS available,
# but it is a list of people's names and workplaces — personal data that says nothing about the
# security, so those filings stay title-only on purpose.
_FIGURE_FORMATTERS = {
    6: _fmt_meeting, 20: _fmt_transaction, 21: _fmt_transaction, 22: _fmt_license,
    31: _fmt_obligation, 32: _fmt_accrual, 42: _fmt_dividend_payment,
}
# A grouped day is capped: O'zbekneftgaz's eight filings are worth eight paced calls, a
# pathological hundred are not.
_FIGURE_MAX_FETCH = 8


def _fact_detail(fact_id):
    """One filing's own fields from ``/disclosure/facts/{id}/``, or None on any failure."""
    try:
        import openinfo_http
        from openinfo_collector import OPENINFO_API_BASE

        resp = openinfo_http.get(f"{OPENINFO_API_BASE}/disclosure/facts/{fact_id}/", timeout=40)
        resp.raise_for_status()
        payload = (resp.json() or {}).get("fact") or []
    except Exception as exc:  # noqa: BLE001 — enrichment is never worth failing a run over
        logger.debug("fact detail failed for %s: %s", fact_id, exc)
        return None
    fact = payload[0] if isinstance(payload, list) and payload else payload
    return fact if isinstance(fact, dict) else None


def _fact_figures(fact_number, fact_ids):
    """What the filings in one item actually say, as a sentence — or None.

    One paced call per filing (capped at ``_FIGURE_MAX_FETCH``) using ids the item already
    carries; no model is involved, so this costs the requests and nothing else. Any failure
    returns None and the item keeps its plain snippet: a filing that cannot be enriched must
    still be published.
    """
    formatter = _FIGURE_FORMATTERS.get(fact_number)
    if formatter is None or not fact_ids:
        return None
    facts = [f for f in (_fact_detail(i) for i in fact_ids[:_FIGURE_MAX_FETCH]) if f]
    if not facts:
        return None
    try:
        return formatter(facts)
    except Exception:  # noqa: BLE001 — one malformed filing must not break the run
        logger.debug("fact #%s did not format (%d filing(s))", fact_number, len(facts))
        return None


def _filing_snippet(group, detail, figures):
    """The card text for one filing item: what was filed, then what it says.

    Sentences are joined rather than concatenated, because the pieces come from different
    places and half of them arrive without a full stop — which is how "…по ценным бумагам
    Начислено 2 301,37 сум" happened. The bare filing count is dropped once ``figures`` is
    present, since the figures sentence already opens with it.
    """
    chunks = [f"Существенный факт №{group['fact_number']} на openinfo.uz"]
    if detail:
        chunks.append(detail)
    count = group["count"]
    if count > 1 and not figures:
        word = _plural_ru(count, ("сообщение", "сообщения", "сообщений"))
        chunks.append(f"Подано {count} {word} за день")
    text = ". ".join(c.strip().rstrip(".") for c in chunks if c and c.strip()) + "."
    if figures:
        text += " " + figures.strip()
    return text[:1000]


def fetch_openinfo(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """openinfo material facts — the primary issuer-disclosure channel (§3.11 cats 1–9).

    Reads the newest filings from ``/disclosure/facts/`` (the API returns them newest-first;
    ~21/day across all ~790 filers), keeps those filed by OUR listed issuers via
    ``catalog_companies.org_id``, and collapses same-issuer/same-fact-type/same-day filings
    into one item: O'zbekneftgaz files six affiliate-deal notices in an hour and that is one
    story, not six cards.

    Items come back marked ``always_relevant`` with their tickers already attached — a
    material fact filed by a listed issuer is market news by definition, so it skips the
    prefilter and the triage gate and the model only judges tone/impact and writes the
    summary. All traffic goes through ``openinfo_http`` (paced 350 ms, retries, TLS verify).
    """
    endpoint = os.getenv("OPENINFO_FACTS_ENDPOINT", "/disclosure/facts/").strip()
    pages = max(1, min(int(os.getenv("OPENINFO_FACTS_PAGES", "2")), 6))
    page_size = max(10, min(limit if limit and limit > 10 else 50, 100))
    tickers_by_org = _openinfo_ticker_map()
    if not tickers_by_org:
        # Loud on purpose: this is the highest-value source, and losing it silently for a run
        # looks identical to "no issuer filed anything today".
        logger.error("openinfo facts SKIPPED: no org_id → ticker mapping available, locally or "
                     "from prod. Filings cannot be attributed to a ticker, so nothing is "
                     "collected from the issuer channel this run.")
        return []

    try:
        import openinfo_http
        from openinfo_collector import OPENINFO_API_BASE
    except ImportError as exc:
        logger.warning("openinfo modules unavailable: %s", exc)
        return []

    base = endpoint if endpoint.startswith("http") else f"{OPENINFO_API_BASE}{endpoint}"
    raw: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        try:
            resp = openinfo_http.get(base, params={"page_size": page_size, "page": page}, timeout=40)
            resp.raise_for_status()
            batch = (resp.json() or {}).get("results") or []
        except Exception as exc:  # noqa: BLE001 — one bad page must not kill the run
            logger.warning("openinfo facts page %d failed: %s", page, exc)
            break
        raw.extend(batch)
        if len(batch) < page_size:
            break

    # Group: one card per issuer + fact type + day.
    groups: dict[tuple[str, Any, str], dict[str, Any]] = {}
    unmatched: dict[str, int] = {}
    for rec in raw:
        org = str(rec.get("organization") or "")
        tickers = tickers_by_org.get(org)
        if not tickers:
            name = rec.get("organization_short_name") or org
            unmatched[name] = unmatched.get(name, 0) + 1
            continue
        pub = str(rec.get("pub_date") or "").strip()
        key = (org, rec.get("fact_number"), pub[:10])
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "org": org, "tickers": tickers, "count": 1,
                "fact_id": rec.get("id"),
                # Every filing in the group, newest first: the enrichment sums the day's
                # deals, and one anchor id could only ever describe one of them.
                "fact_ids": [rec.get("id")],
                "fact_number": rec.get("fact_number"),
                "short_title": (rec.get("fact_short_title") or rec.get("fact_title") or "").strip(),
                "full_title": (rec.get("fact_title") or "").strip(),
                "org_name": (rec.get("organization_short_name")
                             or rec.get("organization_name") or "").strip(),
                "pub_date": pub,
            }
        else:
            group["count"] += 1
            group["fact_ids"].append(rec.get("id"))
            # keep the newest filing of the group as its anchor
            if pub > str(group["pub_date"]):
                group["pub_date"], group["fact_id"] = pub, rec.get("id")

    items: list[dict[str, Any]] = []
    for g in sorted(groups.values(), key=lambda x: str(x["pub_date"]), reverse=True)[:limit]:
        if not g["short_title"] or not g["org_name"]:
            continue
        suffix = f" ({g['count']})" if g["count"] > 1 else ""
        detail = g["full_title"] if g["full_title"] and g["full_title"] != g["short_title"] else ""
        figures = _fact_figures(g["fact_number"], g.get("fact_ids") or [g["fact_id"]])
        items.append({
            "url": _OPENINFO_ORG_URL.format(org=g["org"], fact_id=g["fact_id"]),
            "title": f"{g['org_name']}: {g['short_title']}{suffix}",
            # Filing metadata we publish ourselves — no article body is involved.
            "snippet": _filing_snippet(g, detail, figures),
            "published_at": g["pub_date"].replace(" ", "T")[:19] or None,
            "lang": "ru",
            "tickers": g["tickers"],
            "always_relevant": True,
            "type_hint": _FACT_TYPE_MAP.get(g["fact_number"]),
            # Which openinfo fact type this came from — the backfill uses it to tell an item
            # that CAN carry figures from one that never will.
            "fact_number_hint": g["fact_number"],
        })
    logger.info("openinfo facts: %d filings fetched, %d relevant to our issuers "
                "(grouped into %d item(s)); %d filings from %d non-covered filers skipped",
                len(raw), sum(g["count"] for g in groups.values()), len(items),
                sum(unmatched.values()), len(unmatched))
    return items


def fetch_pending(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """html (sitemap scrape) and telegram adapters — not yet implemented."""
    logger.info("source '%s' (%s) adapter pending — skipped", source["id"], source["type"])
    return []


# Month names as the listings write them: abbreviated ("17 июл 2026") and spelled out
# ("25 мая 2026") both occur on cbu.uz, so match on the first three letters.
_RU_MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "мая": 5, "май": 5, "июн": 6,
              "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def _parse_list_date(text: str) -> str | None:
    """'17 июл 2026' / '25 мая 2026' / '17.07.2026' → 'YYYY-MM-DD', else None.

    A miss is safe: undated items pass the recency filter (``_is_recent``), so an
    unparseable date costs ranking precision, never the item itself.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None
    numeric = re.match(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})", raw)
    if numeric:
        day, month, year = (int(g) for g in numeric.groups())
    else:
        named = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", raw)
        if not named:
            return None
        month = _RU_MONTHS.get(named.group(2)[:3], 0)
        if not month:
            return None
        day, year = int(named.group(1)), int(named.group(3))
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_html_list(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """A server-rendered listing page read as a feed (§3.11).

    For publishers whose RSS is a stub this is the only way to see their output: cbu.uz's
    feed carries a **single** entry, so a second press release published before the next
    run is lost for good, while its press-centre page lists the last ten. Selectors come
    from the source config (``list_selectors``), so covering another site is configuration,
    not code.

    One GET per run, and only what the listing itself renders — link, headline, date and
    the article's own thumbnail. No article page is opened and no body is stored, so the
    legal invariant (headline + our own summary + link) is untouched.
    """
    try:
        from bs4 import BeautifulSoup  # lazy: only html_list sources need it
    except ImportError:
        logger.error("beautifulsoup4 is not installed — run: pip install beautifulsoup4")
        return []
    selectors = source.get("list_selectors") or {}
    if not selectors.get("item"):
        logger.warning("source '%s' is html_list but has no list_selectors.item — skipped",
                       source["id"])
        return []
    try:
        resp = requests.get(source["url"], timeout=20, headers=_source_headers(source))
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("listing fetch failed for %s: %s", source["id"], exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    pick = lambda node, key: (node.select_one(selectors[key])
                              if selectors.get(key) else None)  # noqa: E731
    items: list[dict[str, Any]] = []
    for node in soup.select(selectors["item"])[:limit]:
        link = node if node.has_attr("href") else node.select_one("a[href]")
        href = (link.get("href") if link else "") or ""
        title_node = pick(node, "title")
        title = _clean_text((title_node or node).get_text(" ", strip=True))
        if not href or not title:
            continue
        text_node = pick(node, "text")
        date_node = pick(node, "date")
        image = None
        # Same opt-out as the feeds: "feed_image": false when a ToS bars media reuse.
        if source.get("feed_image", True):
            img_node = pick(node, "image")
            src = (img_node.get("src") if img_node else "") or ""
            candidate = urljoin(source["url"], src) if src else ""
            if (candidate.lower().startswith(("http://", "https://"))
                    and not _GENERIC_IMAGE_RE.search(urlparse(candidate).path)):
                image = candidate
        url = urljoin(source["url"], href)
        items.append({
            "url": _canonical_url(url),
            "raw_url": url,
            "title": title,
            # Listings publish a blurb only sometimes (cbu.uz renders an empty node), and
            # what is here is the publisher's own teaser — a snippet, never the body.
            "snippet": _clean_text(text_node.get_text(" ", strip=True))[:1000] if text_node else "",
            "published_at": _parse_list_date(date_node.get_text(" ", strip=True)) if date_node else None,
            "image_url": image,
            "lang": (source.get("lang") or ["ru"])[0],
        })
    return items


def _title_from_slug(url: str, strip_pattern: str | None = None) -> str:
    """'…/Moodys-Ratings-affirms-Zeda-Limiteds-Ba3-rating-outlook-stable--PR_514556'
    → 'Moodys Ratings affirms Zeda Limiteds Ba3 rating outlook stable'.

    Publishers that put the headline in the URL let us name an item without opening it.
    """
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    if strip_pattern:
        slug = re.sub(strip_pattern, "", slug)
    return _clean_text(re.sub(r"[-_]+", " ", slug).strip())


# Tokens a slug-derived headline must not be left holding in lower case.
_SLUG_ACRONYMS = {"jsc", "ojsc", "pjsc", "llc", "ltd", "plc", "idr", "idrs", "ifs", "esg",
                  "abs", "rmbs", "cmbs", "sme", "ipo", "gdp", "usd", "eur", "uk", "us", "uae"}
# Fitch writes the grade right after 'at' or 'to' ('…at bb outlook stable'), which is the
# only position where a bare 'a' or 'b' is a rating and not an ordinary word.
_RATING_GRADE = re.compile(r"(?:aaa|aa|a|bbb|bb|b|ccc|cc|c|d)[+-]?$")
_TITLE_SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on",
                      "or", "the", "to", "vs", "with"}


def _recase_title(title: str, mode: str | None) -> str:
    """Give a slug-derived headline back the capitals the URL threw away.

    Fitch lower-cases every research slug, so its headline arrives as 'fitch affirms
    uzbekistan at bb outlook stable' and would sit in the feed next to properly cased ones
    looking broken. Only a source that declares ``title_case`` is touched, and only when the
    title is entirely lower case — Moody's slugs carry their own capitals and rewriting them
    could only do damage.
    """
    if mode != "title" or not title or title != title.lower():
        return title
    words = title.split()
    out: list[str] = []
    for i, word in enumerate(words):
        previous = words[i - 1] if i else ""
        if word in _SLUG_ACRONYMS or (previous in ("at", "to") and _RATING_GRADE.fullmatch(word)):
            out.append(word.upper())
        elif i and word in _TITLE_SMALL_WORDS:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def fetch_sitemap(source: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    """A publisher's XML sitemap read as a feed, filtered to our market before anything costs.

    For publishers with no usable feed that do expose a crawlable sitemap. Moody's
    ``ratingsnewsmap.xml`` is a rolling window of ~183 **global** rating actions with the
    headline in the URL slug — Uzbek issuers are a handful a year in that stream. So
    ``url_filter`` (a plain regex over the URL) runs **here**, ahead of the prefilter, the
    triage gate and any model call: the ~99% that names no issuer of ours costs exactly one
    shared HTTP request and nothing else.

    A **news sitemap** (the ``<news:>`` extension, which S&P Global publishes) carries the
    publisher's own headline and publication date per entry, and its ``<loc>`` is a numeric
    id with no slug in it. Those entries are filtered by ``title_filter`` over that headline
    instead — the same gate, applied to the only field that names anybody. A source must
    declare one filter or the other; a sitemap with neither would send a publisher's whole
    global output to the classifier.

    Nothing is opened: the headline comes from the sitemap itself — ``<news:title>``, or the
    slug where the publisher ships no title (``title_from: "slug"``) — so no article page is
    fetched and no body is stored. Entries without a date arrive undated, which ``_is_recent``
    keeps — correct for a rolling window that only ever lists current actions.

    Dates come from ``<news:publication_date>`` where there is one, then ``slug_date``, then
    ``<lastmod>``. ``slug_date`` exists because Fitch regenerates its research sitemap daily
    and stamps EVERY entry with the generation time, so a rating action published five days
    ago would be served to readers as today's news; its slug ends in the real date
    (``…-23-07-2026``).
    """
    try:
        resp = requests.get(source["url"], timeout=40, headers=_source_headers(source))
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("sitemap fetch failed for %s: %s", source["id"], exc)
        return []

    strip_pattern = source.get("slug_strip")
    title_case = source.get("title_case")
    prefer_slug = source.get("title_from") == "slug"

    entries: list[dict[str, Any]] = []
    for block in re.finditer(r"<url>(.*?)</url>", resp.text, re.S):
        body = block.group(1)
        loc = re.search(r"<loc>\s*([^<]+?)\s*</loc>", body)
        if not loc:
            continue
        url = html.unescape(loc.group(1))
        lastmod = re.search(r"<lastmod>\s*([^<]+?)\s*</lastmod>", body)
        news_title = re.search(
            r"<news:title>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</news:title>", body, re.S)
        news_date = re.search(
            r"<news:publication_date>\s*([^<]+?)\s*</news:publication_date>", body)
        published = html.unescape(news_date.group(1))[:10] if news_date else (
            lastmod.group(1)[:10] if lastmod else None)
        title = html.unescape(news_title.group(1)).strip() if news_title else ""
        if prefer_slug or not title:
            title = _recase_title(_title_from_slug(url, strip_pattern), title_case)
        entries.append({"url": url, "title": title, "published": published,
                        "dated_by_publisher": bool(news_date)})

    url_pattern = source.get("url_filter")
    title_pattern = source.get("title_filter")
    if url_pattern or title_pattern:
        url_matcher = re.compile(url_pattern, re.I) if url_pattern else None
        title_matcher = re.compile(title_pattern, re.I) if title_pattern else None
        kept = [e for e in entries
                if (url_matcher and url_matcher.search(e["url"]))
                or (title_matcher and title_matcher.search(e["title"] or ""))]
        logger.info("  %s: %s filter kept %d of %d sitemap URL(s) — the rest cost nothing",
                    source["id"], "url" if url_matcher else "title", len(kept), len(entries))
        entries = kept
    elif entries:
        logger.warning("source '%s' is a sitemap with no url_filter or title_filter — every "
                       "URL would be classified; refusing to fetch %d item(s)",
                       source["id"], len(entries))
        return []

    slug_date = source.get("slug_date") or {}
    date_pattern = slug_date.get("pattern")
    date_format = slug_date.get("format", "%d-%m-%Y")
    items: list[dict[str, Any]] = []
    for entry in entries[:limit]:
        url, title, published = entry["url"], entry["title"], entry["published"]
        if not title:
            continue
        # A date the publisher stated for THIS item is already the truth; slug_date exists
        # only to overrule a sitemap-wide build timestamp.
        if date_pattern and not entry["dated_by_publisher"]:
            match = re.search(date_pattern, url)
            if match:
                try:
                    published = datetime.strptime(match.group(1), date_format).strftime("%Y-%m-%d")
                except ValueError:
                    logger.warning("  %s: unparseable slug date %r in %s",
                                   source["id"], match.group(1), url)
        items.append({
            "url": _canonical_url(url),
            "raw_url": url,
            "title": title,
            "snippet": "",
            "published_at": published,
            "image_url": None,
            "lang": (source.get("lang") or ["en"])[0],
        })
    return items


_FETCHERS = {"rss": fetch_rss, "openinfo": fetch_openinfo, "html_list": fetch_html_list,
             "sitemap": fetch_sitemap, "html": fetch_pending, "telegram": fetch_pending}


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


def known_urls_in_prod(urls: list[str]) -> set[str]:
    """The subset of ``urls`` prod already stores — dedup memory that does not depend on this
    host's SQLite file.

    Matters for the scheduled deployment: a cron container starts with an empty database, so
    local-only dedup would re-classify every item on every run. Prod's UNIQUE(url) keeps the
    rows correct, but the LLM bill would be paid again each time. Fails soft — on any error we
    fall back to local history and log it, rather than skipping the run.
    """
    if not urls:
        return set()
    found: set[str] = set()
    for i in range(0, len(urls), 500):
        chunk = urls[i:i + 500]
        body = _prod_request("POST", "/api/admin/news/known", json={"urls": chunk})
        if body is None:
            logger.warning("prod dedup check unavailable; using local history only — this run "
                           "may re-classify items prod already has")
            return found
        found.update(body.get("known") or [])
    return found


def push_images(images: dict[str, str], *, replace: bool = False) -> int:
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
                             json={"images": images, "replace": replace},
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


def purge_failed(*, push: bool = True) -> dict[str, Any]:
    """Delete locally (and in prod) the items whose classification failed, so the next
    run re-fetches and re-classifies them. No LLM calls."""
    local = news_store.delete_failed_classifications()
    logger.info("purge-failed: %d row(s) deleted locally %s", local["deleted"],
                local["by_source"] or "")
    prod: dict[str, Any] = {"deleted": 0}
    if push:
        secret = os.getenv("ADMIN_API_SECRET", "").strip()
        if not secret:
            logger.error("ADMIN_API_SECRET is not set — cannot purge in prod")
        else:
            try:
                resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/purge-failed",
                                     headers={"X-Admin-Secret": secret}, timeout=120)
                if resp.status_code != 200:
                    logger.error("purge-failed in prod: HTTP %s %s",
                                 resp.status_code, resp.text[:300])
                else:
                    prod = resp.json() or {}
                    logger.info("purge-failed in prod: %s deleted %s",
                                prod.get("deleted"), prod.get("by_source") or "")
            except (requests.RequestException, ValueError) as exc:
                logger.error("purge-failed in prod failed: %s", exc)
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
    logger.info("rejudge %s: %d rejected row(s) deleted locally", source_id, local["deleted"])
    prod: dict[str, Any] = {"deleted": 0}
    if push:
        secret = os.getenv("ADMIN_API_SECRET", "").strip()
        if not secret:
            logger.error("ADMIN_API_SECRET is not set — cannot rejudge in prod")
        else:
            try:
                resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/rejudge",
                                     json={"source_id": source_id, "days": days},
                                     headers={"X-Admin-Secret": secret}, timeout=120)
                if resp.status_code != 200:
                    logger.error("rejudge in prod: HTTP %s %s", resp.status_code, resp.text[:300])
                else:
                    prod = resp.json() or {}
                    logger.info("rejudge %s in prod: %s row(s) deleted",
                                source_id, prod.get("deleted"))
            except (requests.RequestException, ValueError) as exc:
                logger.error("rejudge in prod failed: %s", exc)
    return {"local": local, "prod": prod}


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
    # Every candidate goes to `enrich_images`, which applies the cap ITSELF, and does it
    # to the list it has already narrowed to page-image sources. Capping here instead
    # spent the whole budget on openinfo filings — the largest group with no image and
    # the one group that can never have one — and the two outlets that do publish a
    # preview never made the list.
    items = list(candidates.values())
    found = enrich_images(items, _source_registry(), max_fetch=limit)
    images = {it["url"]: it["image_url"] for it in items if it.get("image_url")}
    return {
        "candidates": len(items), "found": found,
        "updated_local": news_store.set_image_urls(images),
        "updated_prod": push_images(images) if (push and images) else 0,
    }


def _prod_items_with_image(days: int) -> list[dict[str, Any]]:
    """Feed rows that HAVE an image — the upgrade pass's work list."""
    try:
        resp = requests.get(f"{DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("could not read the prod feed for image-upgrade candidates: %s", exc)
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
    upgraded = upgrade_images(items, _source_registry())
    if not upgraded:
        logger.info("image upgrade: nothing to replace across %d row(s)", len(items))
        return {"candidates": len(items), "upgraded": 0,
                "updated_local": 0, "updated_prod": 0}
    images = {it["url"]: it["image_url"] for it in items if it.get("image_url")}
    return {
        "candidates": len(items), "upgraded": upgraded,
        "updated_local": news_store.set_image_urls(images, replace=True),
        "updated_prod": push_images(images, replace=True) if push else 0,
    }


def push_snippets(snippets: dict[str, str]) -> int:
    """Push snippet-only updates (url → snippet) and return the rows prod changed.

    Deliberately NOT /api/admin/news, for the same reason as ``push_images``: a full upsert
    there would rewrite the stored classification from these partial records.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        logger.error("ADMIN_API_SECRET is not set — cannot push snippets")
        return 0
    try:
        resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/snippets",
                             json={"snippets": snippets},
                             headers={"X-Admin-Secret": secret}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("push /api/admin/news/snippets failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)


def push_translations(translations: dict[str, dict[str, str]]) -> int:
    """Push translation-only updates (url → {en, uz}) and return the rows prod changed.

    Deliberately NOT /api/admin/news, for the same reason as ``push_images``: a full upsert
    there would rewrite the stored classification from these partial records.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        logger.error("ADMIN_API_SECRET is not set — cannot push translations")
        return 0
    try:
        resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/translations",
                             json={"translations": translations},
                             headers={"X-Admin-Secret": secret}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("push /api/admin/news/translations failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)


def _prod_items_without_translation(days: int) -> list[dict[str, Any]]:
    """Backfill candidates read from prod's public feed — the cards users actually see."""
    try:
        resp = requests.get(f"{DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("could not read the prod feed for translation candidates: %s", exc)
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
    logger.info("translation backfill: %d from the prod feed + %d local-only, %d to translate",
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
        logger.error("translation backfill: %s", exc)
        return {"candidates": len(items), "translated": 0,
                "updated_local": 0, "updated_prod": 0, "error": str(exc)}
    translations = {
        it["url"]: {"en": got.get("en", ""), "uz": got.get("uz", "")}
        for it, got in zip(items, results)
        if got.get("en") or got.get("uz")
    }
    logger.info("translation backfill: %d of %d item(s) translated "
                "(%d tokens, ~$%.4f)", len(translations), len(items),
                usage.total_tokens, usage.est_cost_usd())
    if dry_run:
        for url, langs in list(translations.items())[:5]:
            logger.info("  %s\n    en: %s\n    uz: %s", url, langs["en"][:90], langs["uz"][:90])
        return {"candidates": len(items), "translated": len(translations),
                "updated_local": 0, "updated_prod": 0, "dry_run": True}
    return {
        "candidates": len(items), "translated": len(translations),
        "updated_local": news_store.set_translations(translations),
        "updated_prod": push_translations(translations) if (push and translations) else 0,
    }


def push_details(details: dict[str, dict[str, str]]) -> int:
    """Push detail-only updates (url → {ru, en, uz}) and return the rows prod changed.

    Its own endpoint rather than /api/admin/news, for the same reason as the images and the
    translations: a full upsert from these partial records would rewrite the classification.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        logger.error("ADMIN_API_SECRET is not set — cannot push details")
        return 0
    try:
        resp = requests.post(DEFAULT_PUSH_URL + "/api/admin/news/details",
                             json={"details": details},
                             headers={"X-Admin-Secret": secret}, timeout=180)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.error("push /api/admin/news/details failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)


def _prod_items_without_detail(days: int) -> list[dict[str, Any]]:
    """Long-read candidates read from prod's feed — the cards a reader can actually open."""
    try:
        resp = requests.get(f"{DEFAULT_PUSH_URL}/api/news/feed",
                            params={"limit": 200, "days": days}, timeout=60)
        resp.raise_for_status()
        items = (resp.json() or {}).get("items") or []
    except (requests.RequestException, ValueError) as exc:
        logger.warning("could not read the prod feed for detail candidates: %s", exc)
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
            for it in items if it.get("url") and not it.get("has_detail")]


def backfill_details(*, limit: int | None = None, days: int = 30, push: bool = True,
                     dry_run: bool = False, usage: Any = None) -> dict[str, Any]:
    """Write the story-page long read for feed items that have none yet.

    The pass that makes an opened story worth opening: a feed teaser is one sentence, the
    article behind it is five paragraphs, and until now the reader got the sentence. For each
    candidate it opens the source's article page once, hands the prose to the model, and
    stores OUR OWN 3-5 paragraph account of it in all three UI languages — the article text
    itself is never written anywhere (see ``_article_text``).

    Ordered by the prod feed first, so the day's cap is spent on cards that are actually on
    the page — but a share of every run is reserved for the OLDEST items still without one.
    Newest-first alone never converges while the cap is under the day's inflow: the shortfall
    lands on the same items every time and three weeks of stories stay bare. Only empty
    columns are filled, so a re-run after a failed push costs nothing.
    """
    limit = _DETAIL_CAP if limit is None else limit
    remote = _prod_items_without_detail(days) if push else []
    candidates: dict[str, dict[str, Any]] = {it["url"]: it for it in remote if it.get("url")}
    registry = _source_registry()
    local_only = 0
    for r in news_store.rows_without_detail(limit=max(limit * 2, 20), days=days):
        if r["url"] not in candidates:
            candidates[r["url"]] = r
            local_only += 1
    # The tail slice is taken from the store rather than from the prod feed: the feed is
    # ranked and capped at 200, so its own oldest is not the corpus's oldest.
    tail_n = int(max(0.0, min(_DETAIL_TAIL_SHARE, 1.0)) * limit)
    tail = [r for r in news_store.rows_without_detail(limit=max(tail_n, 1), days=days,
                                                      oldest_first=True)][:tail_n]
    head = [c for c in candidates.values()
            if c["url"] not in {t["url"] for t in tail}][:max(1, limit - len(tail))]
    items = head + tail
    logger.info("detail backfill: %d from the prod feed + %d local-only, "
                "%d to write (%d newest, %d from the backlog)",
                len(remote), local_only, len(items), len(head), len(tail))
    if not items:
        return {"candidates": 0, "written": 0, "updated_local": 0, "updated_prod": 0}

    from llm_client import LLMError, Usage

    own_usage = usage is None
    usage = Usage() if own_usage else usage
    try:
        details = enrich_details(items, registry, max_fetch=limit, usage=usage)
    except LLMError as exc:
        # No key configured — the same shape as the translation backfill: say why, store
        # nothing, and let a re-run once the key is set cost nothing.
        logger.error("detail backfill: %s", exc)
        return {"candidates": len(items), "written": 0,
                "updated_local": 0, "updated_prod": 0, "error": str(exc)}
    if own_usage:
        logger.info("detail backfill: %d long read(s) written (%d tokens, ~$%.4f)",
                    len(details), usage.total_tokens, usage.est_cost_usd())
    if dry_run:
        for url, langs in list(details.items())[:3]:
            logger.info("  %s\n    ru: %s…", url, langs["ru"][:200])
        return {"candidates": len(items), "written": len(details),
                "updated_local": 0, "updated_prod": 0, "dry_run": True}
    return {
        "candidates": len(items), "written": len(details),
        "updated_local": news_store.set_details(details),
        "updated_prod": push_details(details) if (push and details) else 0,
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
    sources = load_sources("openinfo_facts")
    if not sources:
        return {"candidates": 0, "updated_local": 0, "updated_prod": 0}
    items = fetch_openinfo(sources[0], limit)
    # Only the items that actually gained figures are worth an update; the rest would
    # rewrite a row with the text it already has.
    enriched = {it["url"]: it["snippet"] for it in items
                if it.get("snippet") and _FIGURE_FORMATTERS.get(it.get("fact_number_hint"))}
    if not enriched:
        enriched = {it["url"]: it["snippet"] for it in items if it.get("snippet")}
    known = news_store.existing_urls(list(enriched))
    if push:
        known |= known_urls_in_prod(list(enriched))
    updates = {u: t for u, t in enriched.items() if u in known}
    logger.info("fact backfill: %d fetched, %d already stored → %d snippet update(s)",
                len(items), len(known), len(updates))
    if dry_run:
        for url, text in list(updates.items())[:10]:
            logger.info("  %s -> %s", url, text[:220])
        return {"candidates": len(updates), "updated_local": 0, "updated_prod": 0, "dry_run": True}
    return {
        "candidates": len(updates),
        "updated_local": news_store.set_snippets(updates),
        "updated_prod": push_snippets(updates) if (push and updates) else 0,
    }


# --------------------------------------------------------------------------- #
# main run
# --------------------------------------------------------------------------- #
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
    sources = load_sources(only)
    universe = build_universe()
    logger.info("collecting from %d source(s); issuer universe = %d tickers", len(sources), len(universe))

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
            logger.exception("fetch failed for %s", src["id"])
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
        logger.info("  %s: %d items (cap %d)%s", src["id"], len(fetched), src_limit,
                    f" — {dict(by_lang)}" if len(by_lang) > 1 else "")
        raw.extend(fetched)
        time.sleep(min(src.get("crawl_delay_s", 2), 5) if len(sources) > 1 else 0)

    # Skip stale news up front — never classify (or pay for) anything older than the
    # freshness window. Undated items are kept (see _is_recent).
    max_age = int(os.getenv("NEWS_MAX_AGE_DAYS", "30"))
    before_age = len(raw)
    raw = [it for it in raw if _is_recent(it.get("published_at"), max_age)]
    if before_age != len(raw):
        logger.info("recency filter: dropped %d item(s) older than %d days", before_age - len(raw), max_age)

    # Within one run, two sources — or two pages of the same source — can surface the same
    # article. Collapsing them here means we never pay to classify it twice (the store's
    # UNIQUE(url) would merge the rows afterwards, but only after the money was spent).
    # Keyed on the canonical form rather than whatever the adapter produced, so this holds
    # even for a fetcher that forgets to canonicalise its links.
    unique: dict[str, dict[str, Any]] = {}
    for it in raw:
        unique.setdefault(_canonical_url(it["url"]), it)
    if len(unique) != len(raw):
        logger.info("intra-run dedup: %d duplicate URL(s) inside this run", len(raw) - len(unique))
    raw = list(unique.values())

    # Dedup on the canonical URL, but also on the feed's original link so rows stored
    # before canonicalisation are still recognised instead of re-classified once. Prod is
    # asked too, so a run with no local history (a fresh cron container) is not a blank slate.
    candidates = [it["url"] for it in raw] + [it["raw_url"] for it in raw if it.get("raw_url")]
    seen = news_store.existing_urls(candidates)
    if push:
        try:
            remote_seen = known_urls_in_prod(sorted(set(candidates)))
        except Exception:  # noqa: BLE001 — a dedup check must never abort the run
            logger.exception("prod dedup check failed; using local history only")
            remote_seen = set()
        if remote_seen - seen:
            logger.info("dedup: %d item(s) already in prod but not in the local history",
                        len(remote_seen - seen))
        seen |= remote_seen
    fresh = [it for it in raw
             if it["url"] not in seen and (it.get("raw_url") or it["url"]) not in seen]
    logger.info("fetched %d, %d already stored, %d new", len(raw), len(raw) - len(fresh), len(fresh))

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
        logger.info("prefilter: dropped %d of %d as non-market before any LLM call (%s)",
                    len(fresh) - len(kept), len(fresh),
                    ", ".join(f"{k}×{v}" for k, v in top))

    # 2) classify what's left (Layer A: cheap triage, then full classification).
    from llm_client import Usage
    usage = Usage()
    # Label rows with the model that actually classified them (the classifier can run on
    # a different, cheaper provider than the generic LLM_* one used by Layer B).
    model = os.getenv("NEWS_CLASSIFIER_MODEL", "").strip() or os.getenv("LLM_MODEL", "grok-4.3")
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
        logger.info("triage bypassed for %d item(s) from url-filtered source(s): %s",
                    len(pre_gated),
                    ", ".join(sorted({str(it.get("source_id")) for it in pre_gated})))
    for it, (passed, score) in zip(to_screen, screen_items(to_screen, usage=usage)):
        if passed:
            survivors.append(it)
            continue
        # Rejections ARE stored, so we never pay to triage the same item twice.
        rejected = NewsClassification(relevant=False, relevance_score=score,
                                      reason="triage: not market-relevant")
        records.append({**it, "model": model, **rejected.model_dump()})
        triaged_out += 1

    # gate 2, batched.
    for it, cls in zip(survivors, classify_items(survivors, universe, usage=usage)):
        # A failed classification (no API key, quota, outage) is NOT stored: URL dedup
        # would then bury the item as irrelevant forever. Left unstored, it is simply
        # re-fetched and re-classified on the next run.
        if cls.reason == "classification_failed":
            failed += 1
            continue
        record = {**it, "model": model, **cls.model_dump()}
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
        record = {**it, "model": model, **cls.model_dump()}
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
        logger.warning("%d item(s) failed classification — not stored, will retry next run", failed)
    if kept_by_filter:
        logger.info("%d item(s) kept over the model's verdict: their source filter had already "
                    "matched an issuer", kept_by_filter)
    relevant = [r for r in records if r.get("relevant")]
    logger.info("classified %d items (%d stopped at triage, %d relevant); ~%d tokens in "
                "%d calls (%.0f%% of input from prompt cache), est $%.4f at %s list prices",
                len(records), triaged_out, len(relevant), usage.total_tokens, usage.calls,
                usage.cache_hit_rate * 100, usage.est_cost_usd(), usage.model or model)

    # 2b) preview images, for the RELEVANT items only: those are the cards the feed
    # renders, and a whole-site feed like kursiv's is ~85% off-topic — fetching pages
    # for items about to be filtered out would be almost all of the requests.
    by_id = {s["id"]: s for s in sources}
    enrich_images(relevant, by_id)
    # And where the feed handed us a thumbnail, take the full-size original instead: a
    # 320px picture stretched across an article column is what a reader notices first.
    upgrade_images(relevant, by_id)

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
                "tokens": usage.total_tokens, "est_cost_usd": round(usage.est_cost_usd(), 4),
                "dry_run": True}

    # 3) store locally (dedup memory) + push to prod.
    stored = news_store.upsert_news(records)
    pushed = 0
    push_failed = False
    if push and records:
        code = push_news(records)
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
            filled = backfill_images(limit=_BACKFILL_IMAGE_CAP, days=30, push=True).get("found", 0)
        except Exception:  # noqa: BLE001 — a picture is never worth failing the run for
            logger.exception("image backfill pass failed")

    # 5) the long read. Runs after the push, over what the FEED holds rather than over this
    # run's records: a story that missed its article page yesterday (or was collected before
    # this pass existed) is a better use of the day's cap than nothing, and the cap is what
    # keeps this from becoming a crawl. Failure here leaves the old summary-only page.
    detailed = 0
    if push:
        try:
            detailed = backfill_details(limit=_DETAIL_CAP, days=30, push=True,
                                        usage=usage).get("written", 0)
        except Exception:  # noqa: BLE001 — the story page still works without it
            logger.exception("detail pass failed")
    return {
        "fetched": len(raw), "new": len(fresh), "prefiltered": len(fresh) - len(kept),
        "classified": len(records), "triaged_out": triaged_out,
        "classify_failed": failed, "with_image": sum(1 for r in relevant if r.get("image_url")),
        "backfilled_images": filled, "detailed": detailed,
        "relevant": len(relevant), "stored": stored, "pushed": pushed,
        "push_failed": push_failed,
        "tokens": usage.total_tokens, "cached_input_pct": round(usage.cache_hit_rate * 100, 1),
        "est_cost_usd": round(usage.est_cost_usd(), 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect, classify, and push Uzbek market news.")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=40, help="max items per source")
    ap.add_argument("--no-push", action="store_true", help="store locally, do not push to prod")
    ap.add_argument("--dry-run", action="store_true", help="fetch+classify, print, do not store/push")
    ap.add_argument("--backfill-images", action="store_true",
                    help="fill preview images on already-stored items (no LLM calls)")
    ap.add_argument("--backfill-facts", action="store_true",
                    help="re-read stored openinfo filings and replace bare snippets with their "
                         "own figures (no LLM calls)")
    ap.add_argument("--backfill-translations", action="store_true",
                    help="give rows stored before the English/Uzbek summary columns existed "
                         "their translations (one small LLM call per 10 items)")
    ap.add_argument("--backfill-details", action="store_true",
                    help="write the story-page long read for feed items without one "
                         "(one page fetch + one LLM call per item, capped by --limit)")
    ap.add_argument("--upgrade-images", action="store_true",
                    help="replace stored feed thumbnails with the full-size originals "
                         "behind them (no LLM calls)")
    ap.add_argument("--purge-failed", action="store_true",
                    help="delete items whose classification failed so the next run retries them")
    ap.add_argument("--rejudge", metavar="SOURCE_ID",
                    help="delete this source's REJECTED items (relevant=0) so the next run "
                         "classifies them again — for when the gate changed, not the item")
    args = ap.parse_args()
    # The log names Russian/Uzbek drop reasons and issuer titles; on Windows the console
    # defaults to a legacy codepage and renders them as mojibake, which makes the prefilter's
    # counts undiagnosable. Force UTF-8 where the stream supports it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):  # not a real console / already fixed
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # feedparser missing from the image made every cron run collect 0 items while
    # exiting 0 — name the gap in the log instead of shrugging it off.
    preflight(NEWS_REQUIREMENTS, label="news-collector")
    if args.rejudge:
        result = rejudge_source(args.rejudge, push=not args.no_push)
    elif args.purge_failed:
        result = purge_failed(push=not args.no_push)
    elif args.backfill_images:
        result = backfill_images(limit=args.limit, push=not args.no_push)
    elif args.upgrade_images:
        result = upgrade_stored_images(push=not args.no_push)
    elif args.backfill_details:
        result = backfill_details(limit=args.limit, push=not args.no_push,
                                  dry_run=args.dry_run)
    elif args.backfill_translations:
        result = backfill_translations(limit=max(args.limit, 60), push=not args.no_push,
                                       dry_run=args.dry_run)
    elif args.backfill_facts:
        result = backfill_facts(limit=max(args.limit, 60), push=not args.no_push,
                                dry_run=args.dry_run)
    else:
        result = run(only=args.source, limit=args.limit, push=not args.no_push, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A run that classified everything correctly and could not hand it to prod has
    # produced nothing a reader will ever see. Exiting 0 made that invisible: the
    # feed stood still from 2026-08-01 to 08-06 behind six green cron cards, because
    # the only symptom was one ERROR line in a log nobody reads on a green run.
    if result.get("push_failed"):
        logger.error("run exiting non-zero: the collection was fine, the push to prod was not")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
