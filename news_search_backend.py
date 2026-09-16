"""Web-search backends for the on-demand news search agent.

The agent uses a real web-search provider instead of inventing links.  When no
provider key is configured, the null backend returns no results while leaving
the regular feed collector available.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = float(os.getenv("NEWS_SEARCH_TIMEOUT", "20"))
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
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source": self.source,
            "published": self.published,
        }


class SearchBackend(Protocol):
    name: str

    def search(
        self, query: str, *, max_results: int = 6, days: int | None = None
    ) -> list[SearchResult]:
        ...


class NullBackend:
    """Safe no-op used when a search provider is not configured."""

    name = "null"

    def search(
        self, query: str, *, max_results: int = 6, days: int | None = None
    ) -> list[SearchResult]:
        logger.warning(
            "news search requested without a provider; set NEWS_SEARCH_BACKEND=tavily "
            "and TAVILY_API_KEY to enable it"
        )
        return []


class TavilyBackend:
    """Tavily's news-search API."""

    name = "tavily"
    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str, include_domains: list[str] | None = None) -> None:
        self._api_key = api_key
        self._include_domains = (
            include_domains if include_domains is not None else _DEFAULT_INCLUDE_DOMAINS
        )

    def search(
        self, query: str, *, max_results: int = 6, days: int | None = None
    ) -> list[SearchResult]:
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
            response = httpx.post(self._ENDPOINT, json=payload, timeout=_TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Tavily search failed for %r: %s", query, exc)
            return []

        results: list[SearchResult] = []
        for item in data.get("results", []):
            url = item.get("url", "")
            results.append(
                SearchResult(
                    title=item.get("title", "").strip(),
                    url=url,
                    snippet=(item.get("content") or "").strip()[:600],
                    source=_host(url),
                    published=item.get("published_date"),
                )
            )
        return results


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or ""
    except Exception:  # noqa: BLE001
        return ""


def get_backend() -> SearchBackend:
    """Create the configured backend, without requiring a provider in development."""
    if os.getenv("NEWS_SEARCH_BACKEND", "tavily").strip().lower() == "tavily":
        key = os.getenv("TAVILY_API_KEY")
        if key:
            return TavilyBackend(key)
        logger.warning("TAVILY_API_KEY is unset; using the null news-search backend.")
    return NullBackend()
