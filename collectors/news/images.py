"""News images operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from urllib.parse import urljoin
from urllib.parse import urlparse
import collectors.news.http as collectors_news_http
import collectors.news.settings as collectors_news_settings
import html
import os
import re
import requests
import time


_OG_IMAGE_PATTERNS = (
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url|:secure_url)?|twitter:image(?::src)?)["\']'
    r'[^>]+content=["\']([^"\']+)',
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)='
    r'["\'](?:og:image(?::url|:secure_url)?|twitter:image(?::src)?)["\']',
)


_GENERIC_IMAGE_RE = re.compile(
    r"(?:^|[/_-])(?:social|share|default|placeholder|logo|preview|banner|no[_-]?image)[\w-]*"
    r"\.(?:jpe?g|png|webp|gif|svg)$", re.I)


_HEAD_MAX_BYTES = 150_000


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
        collectors_news_settings.logger.debug("page-image fetch failed for %s: %s", page_url, exc)
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
            collectors_news_settings.logger.debug("ignoring site-wide share image %s", img)
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
        collectors_news_settings.logger.debug("image upgrade check failed for %s: %s", candidate, exc)
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
        session.headers.update(collectors_news_http._source_headers(src))
        better = _upgrade_image(session, it["image_url"], src)
        if better != it["image_url"]:
            it["image_url"] = better
            upgraded += 1
    session.close()
    if upgraded:
        collectors_news_settings.logger.info("image upgrade: %d of %d thumbnail(s) replaced with the full-size original",
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
        collectors_news_settings.logger.info("page-image pass: %d candidate(s); fetching %d (NEWS_OG_MAX_FETCH), "
                    "the rest keep the category placeholder", len(todo), max_fetch)
    session = requests.Session()
    last_hit: dict[str, float] = {}
    filled = 0
    for it in todo[:max_fetch]:
        src = sources.get(it.get("source_id")) or {}
        session.headers["User-Agent"] = src.get("user_agent", collectors_news_settings.DEFAULT_UA)
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
    collectors_news_settings.logger.info("page-image pass: %d of %d fetched item(s) got an image",
                filled, min(len(todo), max_fetch))
    return filled
