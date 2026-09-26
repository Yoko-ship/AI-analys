"""News http operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

import collectors.news.settings as collectors_news_settings


def _source_headers(source: dict[str, Any]) -> dict[str, str]:
    """Request headers for one source: our UA unless it overrides, plus any it declares.

    Some publishers sit behind an edge that answers 403 to anything not shaped like a
    browser — S&P Global rejects a bare User-Agent (ours *or* a Chrome string) and serves
    the same sitemap its own robots.txt advertises the moment the usual browser navigation
    headers come with it. ``headers`` in the registry is that, per source and written down
    next to the evidence, rather than a global disguise.
    """
    headers = {"User-Agent": source.get("user_agent", collectors_news_settings.DEFAULT_UA)}
    headers.update({str(k): str(v) for k, v in (source.get("headers") or {}).items()})
    return headers
