"""Layer B — the ``search_news`` agent (on-demand, agentic discovery).

Unlike the Layer-A pipeline (which only classifies items the collector already
pulled), this lets the model actively *find* news: given a company or topic it
decides its own search queries, calls the ``search_news`` tool (backed by a real
web-search API), reads results, and returns the market-relevant items it found.

Controls that keep the agent bounded and observable (TZ: "control him"):
  * hard iteration cap (``NEWS_AGENT_MAX_ITERS``) — it can never loop;
  * every query is logged and returned in ``queries`` for audit;
  * token usage is accounted and returned;
  * with no search backend key it degrades to a no-op (empty result), never errors.

The items it returns share the shape the Layer-A classifier consumes, so callers
can feed found items straight into ``classify_item`` and store them like any other.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from llm_client import LLMClient, Usage, get_client
from news_search_backend import SearchBackend, get_backend

logger = logging.getLogger(__name__)

_MAX_ITERS = int(os.getenv("NEWS_AGENT_MAX_ITERS", "6"))
_MAX_RESULTS_PER_SEARCH = int(os.getenv("NEWS_AGENT_MAX_RESULTS", "6"))

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": (
                "Search the web for recent Uzbek business/market news. Call with focused "
                "queries in Russian, Uzbek, or English. Returns title, url, snippet, source, date."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (RU/UZ/EN)."},
                    "days": {"type": "integer", "description": "Restrict to the last N days.", "default": 7},
                },
                "required": ["query"],
            },
        },
    }
]

_SYSTEM = """You are a market-news research agent for a Uzbekistan stock platform (UZSE issuers).
Find the most market-relevant, recent news for the user's request. Use the search_news
tool with focused queries — try Russian and Uzbek phrasings, and the company's ticker and
full legal name. Prefer primary/official and established business sources.

When you have enough, STOP calling tools and reply with ONLY a JSON object:
{"items": [{"title": "...", "url": "...", "snippet": "...", "source": "...", "published": "YYYY-MM-DD or null"}],
 "note": "one-line summary of what you found"}
Include only items that plausibly affect a listed price or the market. Do not invent items
or URLs — every item must come from a search result you actually received."""


@dataclass
class AgentFindings:
    items: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    queries: list[str] = field(default_factory=list)
    iterations: int = 0
    hit_iteration_cap: bool = False
    usage: Usage = field(default_factory=Usage)
    backend: str = ""


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort parse of the agent's final JSON answer."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


def find_news(
    request: str,
    *,
    days: int = 7,
    client: LLMClient | None = None,
    backend: SearchBackend | None = None,
    max_iters: int | None = None,
) -> AgentFindings:
    """Run the search agent for a free-text request (e.g. a company name/ticker).

    Returns the items the agent surfaced, plus the queries it ran and token usage.
    """
    client = client or get_client()
    backend = backend or get_backend()
    queries: list[str] = []

    def _search_news(args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", "")).strip()
        n_days = int(args.get("days", days) or days)
        queries.append(query)
        results = backend.search(query, max_results=_MAX_RESULTS_PER_SEARCH, days=n_days)
        return {"query": query, "results": [r.as_dict() for r in results]}

    result = client.run_tool_loop(
        system=_SYSTEM,
        user=f"Request: {request}\nTime window: last {days} days.",
        tools=_TOOLS,
        tool_impls={"search_news": _search_news},
        max_iters=max_iters or _MAX_ITERS,
    )
    parsed = _extract_json(result.text)
    raw_items = parsed.get("items") if isinstance(parsed, dict) else None
    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict) and it.get("url"):
                items.append({
                    "title": str(it.get("title", "")).strip(),
                    "url": str(it["url"]).strip(),
                    "snippet": str(it.get("snippet", "")).strip(),
                    "source": str(it.get("source", "")).strip(),
                    "published": it.get("published"),
                })
    return AgentFindings(
        items=items,
        note=str(parsed.get("note", "")) if isinstance(parsed, dict) else "",
        queries=queries,
        iterations=result.iterations,
        hit_iteration_cap=result.hit_iteration_cap,
        usage=result.usage,
        backend=backend.name,
    )


if __name__ == "__main__":  # tiny manual smoke test
    import sys

    logging.basicConfig(level=logging.INFO)
    q = " ".join(sys.argv[1:]) or "Kapitalbank"
    out = find_news(q)
    print(json.dumps({
        "backend": out.backend, "queries": out.queries, "items": out.items,
        "note": out.note, "iters": out.iterations, "cap": out.hit_iteration_cap,
        "tokens": out.usage.total_tokens, "est_cost_usd": round(out.usage.est_cost_usd(), 5),
    }, ensure_ascii=False, indent=2))
