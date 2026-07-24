"""Grok-native news discovery via xAI's Agent Tools API (Layer B, Grok path).

Grok's differentiator over DeepSeek/Kimi is server-side live search: give it the
``web_search`` and ``x_search`` tools and xAI runs the whole search→read→refine
loop on its side, returning a synthesised answer with citations — no separate
search API (Tavily) and no client-side tool loop.

Note this is xAI's **Responses API** (`/v1/responses`, `input`/`tools`), not the
OpenAI-compatible chat-completions surface the classifier uses, and its tool
types (`web_search`/`x_search`) are xAI-specific — so it lives in its own module
rather than going through ``llm_client.run_tool_loop``. (xAI retired the older
``search_parameters`` Live Search in Jan 2026; this uses the current Agent Tools.)

We only parse the model's final text (asked to be JSON), not the internal tool
results, so this is robust to the exact tool-result shape. Verify end-to-end with
a live XAI_API_KEY: the Responses envelope parsing is defensive but unproven here.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

import httpx

from news_agent import AgentFindings, _extract_json

logger = logging.getLogger(__name__)

_ENDPOINT = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/") + "/responses"
# grok-4.5 = xAI's current flagship agentic model (server-side web_search/x_search
# tools). The old grok-4-1-fast id retired 2026-05-15; override via GROK_SEARCH_MODEL.
_MODEL = os.getenv("GROK_SEARCH_MODEL", "grok-4.5")
_TIMEOUT = float(os.getenv("NEWS_SEARCH_TIMEOUT", "45"))
_API_KEY = os.getenv("XAI_API_KEY") or os.getenv("LLM_API_KEY") or os.getenv("api_key")

_SYSTEM = """You are a market-news research agent for a Uzbekistan stock platform (UZSE issuers).
Use web and X search to find the most market-relevant, recent news for the user's request
(company, ticker, or topic). Prefer official/primary and established Uzbek business sources.

Reply with ONLY a JSON object:
{"items": [{"title": "...", "url": "...", "snippet": "...", "source": "...", "published": "YYYY-MM-DD or null", "image": "https image URL or null"}],
 "note": "one-line summary"}
Include only items that plausibly affect a listed price or the market. Only return RECENT items
inside the requested time window — SKIP anything older, and skip items you cannot date. Every item
must come from a real search result — do not invent items, URLs, or images; set "image" only when the
source itself provides one (its article/preview image), otherwise null. Always keep the real source."""


def _final_text(resp_json: dict[str, Any]) -> str:
    """Pull the assistant's final text out of an xAI Responses envelope, defensively."""
    if isinstance(resp_json.get("output_text"), str):
        return resp_json["output_text"]
    chunks: list[str] = []
    for item in resp_json.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and isinstance(c.get("text"), str):
                    chunks.append(c["text"])
    if chunks:
        return "\n".join(chunks)
    # Last resort: some deployments mirror chat-completions' choices[].message.content.
    try:
        return resp_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def grok_find_news(
    request: str,
    *,
    days: int = 7,
    allowed_domains: list[str] | None = None,
    x_handles: list[str] | None = None,
) -> AgentFindings:
    """Discover news for a request using Grok's native web + X search."""
    if not _API_KEY:
        logger.warning("XAI_API_KEY not set — Grok native search unavailable; returning nothing.")
        return AgentFindings(note="no XAI_API_KEY", backend="grok-native")

    from_date = (date.today() - timedelta(days=max(1, days))).isoformat()
    web_tool: dict[str, Any] = {"type": "web_search"}
    if allowed_domains:
        web_tool["allowed_domains"] = allowed_domains[:5]  # xAI caps at 5
    x_tool: dict[str, Any] = {"type": "x_search", "from_date": from_date}
    if x_handles:
        x_tool["allowed_x_handles"] = x_handles[:10]

    payload = {
        "model": _MODEL,
        "input": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": f"Request: {request}\nTime window: last {days} days."},
        ],
        "tools": [web_tool, x_tool],
    }
    headers = {"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"}
    try:
        resp = httpx.post(_ENDPOINT, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Grok native search failed for %r: %s", request, exc)
        return AgentFindings(note=f"error: {exc}", backend="grok-native")

    parsed = _extract_json(_final_text(data))
    items: list[dict[str, Any]] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        for it in parsed["items"]:
            if isinstance(it, dict) and it.get("url"):
                items.append({
                    "title": str(it.get("title", "")).strip(),
                    "url": str(it["url"]).strip(),
                    "snippet": str(it.get("snippet", "")).strip(),
                    "source": str(it.get("source", "")).strip(),
                    "published": it.get("published"),
                    "image_url": (str(it.get("image") or "").strip() or None),
                })
    usage_raw = data.get("usage") or {}
    findings = AgentFindings(
        items=items,
        note=str(parsed.get("note", "")) if isinstance(parsed, dict) else "",
        queries=[f"(grok native web+x search, from {from_date})"],
        backend="grok-native",
    )
    findings.usage.prompt_tokens = usage_raw.get("input_tokens", 0) or usage_raw.get("prompt_tokens", 0) or 0
    findings.usage.completion_tokens = usage_raw.get("output_tokens", 0) or usage_raw.get("completion_tokens", 0) or 0
    findings.usage.calls = 1
    return findings
