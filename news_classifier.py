"""Layer A — per-item news classifier (the cheap, high-volume path).

One structured DeepSeek call per collected item: is it market-relevant, which of
the four TZ §3.11 classes, what tone, which issuers, and a short factual summary
we author ourselves (so nothing of the source's article body is ever stored).

Compliance (TZ §3.11): every output is a *statistical/analytical signal, not a
diagnosis*. We never assert manipulation or an "attack". The price-direction
field is an explicit model estimate the UI must show with a disclaimer.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from llm_client import LLMClient, Usage, get_client

logger = logging.getLogger(__name__)

# The four TZ §3.11 news classes (финотчётность / корпсобытие / регуляторика / рынок).
NewsType = Literal["financial_report", "corporate_event", "regulatory", "market"]
Tone = Literal["positive", "neutral", "negative"]
Impact = Literal["high", "medium", "low", "none"]
Direction = Literal["up", "down", "mixed", "unclear"]

# Grok returns null/empty for these constrained fields on off-topic items; coerce to
# the field default so an irrelevant item validates cleanly instead of raising (which
# would drop it to a generic classification_failed and spam the logs).
_ENUM_DEFAULTS = {"type": "market", "tone": "neutral", "impact": "none", "direction": "unclear"}


class NewsClassification(BaseModel):
    relevant: bool = Field(description="True if this item plausibly affects any UZSE-listed issuer or the market.")
    relevance_score: float = Field(ge=0.0, le=1.0, default=0.0)
    type: NewsType = "market"
    tone: Tone = "neutral"
    tone_score: float = Field(ge=-1.0, le=1.0, default=0.0)
    impact: Impact = "none"
    direction: Direction = "unclear"
    tickers: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    summary_ru: str = Field(default="", description="Our own 1-2 sentence factual summary in Russian.")
    reason: str = Field(default="", description="Brief why-this-class/tone note.")

    @field_validator("tickers", "sectors", mode="before")
    @classmethod
    def _coerce_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("type", "tone", "impact", "direction", mode="before")
    @classmethod
    def _coerce_enum(cls, v: Any, info: Any) -> Any:
        # Off-topic items come back with null here; fall back to the field default.
        if v is None or (isinstance(v, str) and not v.strip()):
            return _ENUM_DEFAULTS[info.field_name]
        return v

    @field_validator("relevance_score", "tone_score", mode="before")
    @classmethod
    def _coerce_score(cls, v: Any) -> Any:
        return 0.0 if v is None or v == "" else v


_SYSTEM = """You are a financial-news triage engine for a Uzbekistan stock-market platform
covering ~93 issuers on the Tashkent exchange (UZSE / RFB "Toshkent"): banks
(Hamkorbank, Ipoteka, Kapitalbank…), cement/industrials (Qizilqumsement, Kvarts…),
and state issuers heading for IPO.

For each news item decide, as a STATISTICAL/ANALYTICAL SIGNAL (never a diagnosis,
never a claim of manipulation or "attack"):

1. relevant — could this move a listed price or the market? News with no plausible
   link to a listed issuer, a sector, monetary policy, FX, or the exchange is NOT relevant.
2. type — exactly one of:
   - "financial_report"  : earnings, filings, financial results, dividends declared/paid
   - "corporate_event"   : share issuance, M&A/stakes, listings, management/ownership changes, IPO/SPO
   - "regulatory"        : central-bank rate, regulator (NAPP) rules, laws/decrees, tariffs, state programs
   - "market"            : trading/liquidity, FX/sum moves, commodity prices, sector/macro conditions
3. tone — positive / neutral / negative FOR INVESTORS IN THE AFFECTED ISSUERS, and tone_score in [-1,1].
4. impact — high / medium / low / none (how strongly it could move price).
5. direction — up / down / mixed / unclear (estimated price effect; this is a hint, not advice).
6. tickers — ONLY symbols from the provided issuer universe that the item is genuinely about. Empty if none.
7. sectors — affected sectors (e.g. "banking", "cement", "energy"), if any.
8. summary_ru — YOUR OWN 1-2 sentence factual summary in Russian. Do NOT copy the source's wording.

Reply with ONLY a JSON object with keys:
relevant, relevance_score, type, tone, tone_score, impact, direction, tickers, sectors, summary_ru, reason."""


def _format_universe(universe: dict[str, str] | None, limit: int = 120) -> str:
    if not universe:
        return "(no issuer universe provided — infer sectors only, leave tickers empty)"
    lines = [f"{t} — {name}" for t, name in list(universe.items())[:limit]]
    return "\n".join(lines)


def _format_item(item: dict[str, Any]) -> str:
    parts = [
        f"SOURCE: {item.get('source', '')}",
        f"LANG: {item.get('lang', '')}",
        f"PUBLISHED: {item.get('published', '')}",
        f"TITLE: {item.get('title', '')}",
    ]
    snippet = (item.get("snippet") or item.get("summary") or "").strip()
    if snippet:
        parts.append(f"SNIPPET: {snippet[:1200]}")
    parts.append(f"URL: {item.get('url', '')}")
    return "\n".join(parts)


def classify_item(
    item: dict[str, Any],
    universe: dict[str, str] | None = None,
    *,
    client: LLMClient | None = None,
    usage: Usage | None = None,
) -> NewsClassification:
    """Classify one news item. Returns a validated ``NewsClassification``.

    On an LLM or validation failure, returns a safe ``relevant=False`` default so a
    single bad item never breaks a batch (the collector logs and skips it).
    """
    client = client or get_client()
    user = (
        f"ISSUER UNIVERSE (ticker — name):\n{_format_universe(universe)}\n\n"
        f"NEWS ITEM:\n{_format_item(item)}"
    )
    try:
        raw = client.complete_json(_SYSTEM, user, usage=usage)
        return NewsClassification.model_validate(raw)
    except ValidationError as exc:
        logger.warning("classification validation failed for %s: %s", item.get("url"), exc)
    except Exception as exc:  # noqa: BLE001 — one bad item must not kill the batch
        logger.warning("classification LLM error for %s: %s", item.get("url"), exc)
    return NewsClassification(relevant=False, reason="classification_failed")
