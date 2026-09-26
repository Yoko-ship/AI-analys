"""News delivery operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

import collectors.news.settings as collectors_news_settings
import os
import requests
import time


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
    url = collectors_news_settings.DEFAULT_PUSH_URL + path
    delay = 5.0
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.request(method, url, headers={"X-Admin-Secret": secret},
                                    timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == attempts:
                collectors_news_settings.logger.warning("prod %s %s failed after %d attempt(s): %s",
                               method, path, attempts, exc)
                return None
            collectors_news_settings.logger.info("prod %s %s failed (%s); retrying in %.0fs", method, path, exc, delay)
            time.sleep(delay)
            delay *= 3
    return None


def push_news(items: list[dict[str, Any]]) -> int:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    url = collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news"
    resp = requests.post(url, json={"items": items}, headers={"X-Admin-Secret": secret}, timeout=120)
    if resp.status_code != 200:
        collectors_news_settings.logger.error("push /api/admin/news failed: HTTP %s %s", resp.status_code, resp.text[:300])
        return 1
    collectors_news_settings.logger.info("push /api/admin/news ok: %s", resp.json())
    return 0


def push_news_usage(record: dict[str, Any]) -> bool:
    """Send one usage record to prod after every collector invocation."""
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push news usage")
        return False
    try:
        resp = requests.post(
            collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/usage",
            json={"record": record},
            headers={"X-Admin-Secret": secret},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.error("push /api/admin/news/usage failed: %s", exc)
        return False
    collectors_news_settings.logger.info("news usage tracked in prod: %s", resp.json())
    return True


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
            collectors_news_settings.logger.warning("prod dedup check unavailable; using local history only — this run "
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
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push images")
        return 0
    try:
        resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/images",
                             json={"images": images, "replace": replace},
                             headers={"X-Admin-Secret": secret}, timeout=120)
    except requests.RequestException as exc:
        collectors_news_settings.logger.error("push /api/admin/news/images failed: %s", exc)
        return 0
    if resp.status_code != 200:
        collectors_news_settings.logger.error("push /api/admin/news/images failed: HTTP %s %s",
                     resp.status_code, resp.text[:300])
        return 0
    try:
        updated = int((resp.json() or {}).get("updated") or 0)
    except ValueError:
        collectors_news_settings.logger.error("push /api/admin/news/images: non-JSON 200 body")
        return 0
    collectors_news_settings.logger.info("push /api/admin/news/images ok: %d row(s) updated in prod", updated)
    return updated


def push_snippets(snippets: dict[str, str]) -> int:
    """Push snippet-only updates (url → snippet) and return the rows prod changed.

    Deliberately NOT /api/admin/news, for the same reason as ``push_images``: a full upsert
    there would rewrite the stored classification from these partial records.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push snippets")
        return 0
    try:
        resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/snippets",
                             json={"snippets": snippets},
                             headers={"X-Admin-Secret": secret}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.error("push /api/admin/news/snippets failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)


def push_translations(translations: dict[str, dict[str, str]]) -> int:
    """Push translation-only updates (url → {en, uz}) and return the rows prod changed.

    Deliberately NOT /api/admin/news, for the same reason as ``push_images``: a full upsert
    there would rewrite the stored classification from these partial records.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push translations")
        return 0
    try:
        resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/translations",
                             json={"translations": translations},
                             headers={"X-Admin-Secret": secret}, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.error("push /api/admin/news/translations failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)


def push_details(details: dict[str, dict[str, str]], *, replace: bool = False) -> int:
    """Push detail-only updates (url → {ru, en, uz}) and return the rows prod changed.

    Its own endpoint rather than /api/admin/news, for the same reason as the images and the
    translations: a full upsert from these partial records would rewrite the classification.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_news_settings.logger.error("ADMIN_API_SECRET is not set — cannot push details")
        return 0
    try:
        resp = requests.post(collectors_news_settings.DEFAULT_PUSH_URL + "/api/admin/news/details",
                             json={"details": details, "replace": replace},
                             headers={"X-Admin-Secret": secret}, timeout=180)
        resp.raise_for_status()
    except requests.RequestException as exc:
        collectors_news_settings.logger.error("push /api/admin/news/details failed: %s", exc)
        return 0
    return int((resp.json() or {}).get("updated") or 0)
