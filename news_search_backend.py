"""Web-search backends for the ``search_news`` agent.

DeepSeek (like any LLM) cannot browse — so the ``search_news`` tool is backed by
a real search API. The backend is pluggable behind ``SearchBackend`` so the
provider is a config swap and the rest of the agent never changes.

  * ``TavilyBackend``  — LLM-oriented search, clean extracts, generous free tier.
  * ``NullBackend``    — no key configured: returns nothing and logs, so the whole
                         news module still runs (Layer A) without a search key.

Select with env ``NEWS_SEARCH_BACKEND`` (tavily | none); the factory falls back
to Null when the chosen backend has no key.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = float(os.getenv("NEWS_SEARCH_TIMEOUT", "20"))

# Bias search toward Uzbek market sources; the agent can still override per query.
# A source taken off the feed is off this list too (kursiv.media, 2026-08-11) — otherwise
# the outlet we stopped publishing would come back through the search answer instead.
_DEFAULT_INCLUDE_DOMAINS = [
    "spot.uz", "gazeta.uz", "kun.uz", "uzdaily.uz", "review.uz",
    "uza.uz", "cbu.uz", "uzse.uz", "openinfo.uz",
]


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = ""
    published: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title, "url": self.url, "snippet": self.snippet,
            "source": self.source, "published": self.published,
        }


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 6, days: int | None = None) -> list[SearchResult]:
        ...


class NullBackend:
    """No search provider configured — a safe no-op so Layer A still works."""

    name = "null"

    def search(self, query: str, *, max_results: int = 6, days: int | None = None) -> list[SearchResult]:
        logger.warning(
            "search_news called but no search backend is configured "
            "(set NEWS_SEARCH_BACKEND=tavily + TAVILY_API_KEY). Returning no results."
        )
        return []


class TavilyBackend:
    """Tavily Search API (https://api.tavily.com/search)."""

    name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str, include_domains: list[str] | None = None) -> None:
        self._api_key = api_key
        self._include_domains = include_domains if include_domains is not None else _DEFAULT_INCLUDE_DOMAINS

    def search(self, query: str, *, max_results: int = 6, days: int | None = None) -> list[SearchResult]:
        payload: dict[str, Any] = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max(1, min(max_results, 10)),
            "topic": "news",
        }
        if days:
            payload["days"] = days
        if self._include_domains:
            payload["include_domains"] = self._include_domains
        try:
            resp = httpx.post(self._ENDPOINT, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Tavily search failed for %r: %s", query, exc)
            return []
        out: list[SearchResult] = []
        for r in data.get("results", []):
            url = r.get("url", "")
            out.append(SearchResult(
                title=r.get("title", "").strip(),
                url=url,
                snippet=(r.get("content") or "").strip()[:600],
                source=_host(url),
                published=r.get("published_date"),
            ))
        return out


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:  # noqa: BLE001
        return ""


def get_backend() -> SearchBackend:
    """Build the configured backend, falling back to Null when no key is present."""
    choice = os.getenv("NEWS_SEARCH_BACKEND", "tavily").strip().lower()
    if choice == "tavily":
        key = os.getenv("TAVILY_API_KEY")
        if key:
            return TavilyBackend(key)
        logger.warning("NEWS_SEARCH_BACKEND=tavily but TAVILY_API_KEY is unset; using NullBackend.")
    return NullBackend()
