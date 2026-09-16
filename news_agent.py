"""Bounded, on-demand discovery of market news."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from llm_client import Usage
from news_search_backend import SearchBackend, get_backend

logger = logging.getLogger(__name__)

_MAX_RESULTS_PER_SEARCH = int(os.getenv("NEWS_AGENT_MAX_RESULTS", "6"))


@dataclass
class AgentFindings:
    items: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    queries: list[str] = field(default_factory=list)
    iterations: int = 0
    hit_iteration_cap: bool = False
    usage: Usage = field(default_factory=Usage)
    backend: str = ""


def find_news(
    request: str,
    *,
    days: int = 7,
    backend: SearchBackend | None = None,
) -> AgentFindings:
    """Search for news and return normalized items for the existing classifier.

    Discovery is intentionally provider-backed: the subsequent classifier decides
    relevance and impact, while this layer returns only links supplied by Tavily.
    """
    backend = backend or get_backend()
    query = request.strip()
    if not query:
        return AgentFindings(backend=backend.name, note="Empty search request.")
    results = backend.search(query, max_results=_MAX_RESULTS_PER_SEARCH, days=days)
    items = [result.as_dict() for result in results if result.url]
    return AgentFindings(
        items=items,
        note=f"Found {len(items)} result(s) from {backend.name}.",
        queries=[query],
        iterations=1,
        backend=backend.name,
    )
