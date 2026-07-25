"""Layer A — per-item news classifier (the cheap, high-volume path).

Three gates, cheapest first, because this path runs once per collected item and the
enabled feeds are whole-site feeds where most items are not market news at all:

  0. ``prefilter_reject`` — free, code only. Drops obvious non-market items (sport,
     horoscopes, weather, accidents, culture) that carry no market signal.
  1. ``triage_item`` — one tiny LLM call: pass/score only, no issuer universe in the
     prompt, ~20 output tokens.
  2. the full classification — class, tone, impact, direction, issuer links and our own
     summary, and ONLY for items that survive triage.

The expensive constant (the ~93-line issuer universe) sits in the SYSTEM message so it
is an identical prefix on every call and the provider's prompt cache can serve it: on
grok-4.3 cached input is $0.20/M vs $1.25/M, on DeepSeek V4-Flash $0.0028/M vs $0.14/M.

Provider: the classifier takes its own config (``NEWS_CLASSIFIER_*``) so this high-volume
path can run on a cheap model while Layer-B search stays on Grok.

Compliance (TZ §3.11): every output is a *statistical/analytical signal, not a
diagnosis*. We never assert manipulation or an "attack". The price-direction
field is an explicit model estimate the UI must show with a disclaimer.
"""
from __future__ import annotations

import logging
import os
import re
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


# --------------------------------------------------------------------------- #
# provider (own config: the classifier is the high-volume path)
# --------------------------------------------------------------------------- #
_CLS_MODEL = os.getenv("NEWS_CLASSIFIER_MODEL", "").strip()
_CLS_BASE_URL = os.getenv("NEWS_CLASSIFIER_BASE_URL", "").strip()
_CLS_API_KEY = (os.getenv("NEWS_CLASSIFIER_API_KEY", "").strip()
                or os.getenv("DEEPSEEK_API_KEY", "").strip())
_client: LLMClient | None = None


def get_classifier_client() -> LLMClient:
    """The classifier's client: ``NEWS_CLASSIFIER_MODEL`` / ``_BASE_URL`` / ``_API_KEY``
    if configured, else the generic ``LLM_*`` one. Lets Layer A run on a cheap model
    (DeepSeek V4-Flash, $0.14/$0.28 per M) while Layer-B search stays on Grok.

    A half-configured override (model/base_url set but no key for that provider) falls
    back to the generic client rather than failing the whole run with an auth error.
    """
    global _client
    if _client is not None:
        return _client
    if (_CLS_MODEL or _CLS_BASE_URL) and not _CLS_API_KEY:
        logger.warning("NEWS_CLASSIFIER_MODEL/BASE_URL set without NEWS_CLASSIFIER_API_KEY "
                       "(or DEEPSEEK_API_KEY) — falling back to the generic LLM_* client")
        _client = get_client()
    elif _CLS_MODEL or _CLS_BASE_URL or _CLS_API_KEY:
        _client = LLMClient(api_key=_CLS_API_KEY or None,
                            base_url=_CLS_BASE_URL or None,
                            model=_CLS_MODEL or None)
        logger.info("classifier provider: model=%s", _client.model)
    else:
        _client = get_client()
    return _client


# --------------------------------------------------------------------------- #
# gate 0 — free, code-only prefilter
# --------------------------------------------------------------------------- #
# The enabled feeds are whole-site feeds: kursiv's carries sport, horoscopes, weather and
# traffic notices, and paying a model to read a horoscope is pure waste. Deliberately
# asymmetric — an item is dropped ONLY when it matches a junk pattern AND carries no
# market signal at all, so a wrong guess costs a missed item, never a wrong verdict.
# Dropped items are not stored, so they are simply re-filtered (for free) next run.
_MARKET_RE = re.compile(
    r"банк|кредит|ставк|процентн|инфляц|акци|облигац|бирж|дивиденд|эмитент|инвестиц|налог"
    r"|тариф|экспорт|импорт|ввп|\bсум\b|сумов|валют|доллар|прибыл|выручк|убыт|актив|капитал"
    r"|финанс|бюджет|долг|займ|лизинг|страхов|цемент|\bгаз|нефт|золот|уран|металл|энерг"
    r"|рынок|торги|листинг|депозит|ипотек|регулятор|минфин|приватизац|аукцион|тендер"
    r"|монопол|пошлин|субсиди|котировк|капитализац|эмисси|ipo\b|spo\b|компани|предприят"
    r"|bank|kredit|foiz|inflyatsiya|aksiya|obligatsiya|birja|dividend|emitent|investitsiya"
    r"|soliq|tarif|eksport|import|valyuta|dollar|foyda|tushum|aktiv|kapital|moliya|budjet"
    r"|qarz|sug|sement|neft|oltin|bozor|savdo|listing|depozit|ipoteka|korxona|kompaniya"
    r"|credit|inflation|bond|exchange|issuer|invest|tax|tariff|export|import|\bgdp\b"
    r"|currency|profit|revenue|asset|capital|financ|budget|debt|insur|cement|\boil\b"
    r"|\bgold\b|energy|market|trading|deposit|mortgage|central bank",
    re.I)
_JUNK_RE = re.compile(
    # 'арбитр' is spelled out per-form on purpose: a bare stem also matches "арбитраж",
    # i.e. commercial arbitration, which is regulatory news. 'борьба' is left out entirely —
    # wrestling and "борьба с коррупцией" are indistinguishable by stem.
    r"гороскоп|футбол|матч|чемпионат|олимпиад|спортсмен|\bспорт|тренер|бокс|шахмат"
    r"|арбитр(?:ы|ов|а|у|ом|е)?\b"
    r"|погод|дождь|жара|\bдтп\b|аварии|столкновени|погиб|задержан|наркотик|кража"
    r"|ограблен|убийств|приговор|концерт|фестивал|\bкино\b|сериал|актер|актрис|певиц|певец"
    r"|музыкант|свадьб|туристическ\w+ поезд|розыгрыш|конкурс красоты"
    r"|futbol|chempionat|musobaqa|\bsport|ob-havo|halok|jinoyat|\bkino\b|konsert|festival"
    r"|sayli|bayram"
    r"|football|championship|olympic|weather|accident|crime|concert|festival|movie"
    r"|celebrity|horoscope",
    re.I)
_GENERIC_NAME_TOKENS = {
    "акционерное", "общество", "компания", "предприятие", "узбекистан", "узбекистана",
    "республики", "имени", "завод", "фабрика", "холдинг", "группа", "банк", "корпорация",
    "aksiyadorlik", "jamiyati", "korxonasi", "uzbekistan", "company", "joint", "stock",
}


def _issuer_terms(universe: dict[str, str] | None) -> set[str]:
    """Lowercase issuer identifiers worth matching in free text: tickers plus the
    distinctive tokens of company names (generic corporate words excluded)."""
    terms: set[str] = set()
    for ticker, name in (universe or {}).items():
        if ticker and len(ticker) >= 3:
            terms.add(ticker.lower())
        for token in re.split(r"[^\wЀ-ӿ]+", (name or "").lower()):
            if len(token) >= 5 and token not in _GENERIC_NAME_TOKENS:
                terms.add(token)
    return terms


def prefilter_reject(item: dict[str, Any], universe: dict[str, str] | None = None) -> str | None:
    """The junk pattern that got this item dropped before any LLM call, or None to keep.

    Keeps anything naming an issuer we cover, and keeps anything it has no opinion about —
    only positive junk evidence rejects. Two tiers, because the headline is what states the
    topic: a junk headline with no market word IN THE HEADLINE is dropped even if the
    snippet happens to contain one (kun.uz's "melon festival" carried a trade word in its
    description and slipped through), while for the snippet the old, gentler rule stands.
    """
    title = str(item.get("title") or "").strip()
    text = f"{title} {item.get('snippet') or ''}".strip()
    if not text:
        return None
    if any(term in text.lower() for term in _issuer_terms(universe)):
        return None
    title_junk = _JUNK_RE.search(title)
    if title_junk and not _MARKET_RE.search(title):
        return title_junk.group(0).lower()
    if _MARKET_RE.search(text):
        return None
    match = _JUNK_RE.search(text)
    return match.group(0).lower() if match else None


# --------------------------------------------------------------------------- #
# gate 1 — one tiny LLM call: is this market news at all?
# --------------------------------------------------------------------------- #
# No issuer universe, no summary, no tone: ~20 output tokens against the ~400 a full
# classification writes, and a fraction of the input. Only survivors reach gate 2.
_TRIAGE_SYSTEM = """You triage news for a Uzbekistan stock-market platform (UZSE / RFB
"Toshkent", ~93 listed issuers: banks, cement and industrials, energy, telecom, insurance,
and state issuers heading for IPO).

Decide ONLY this: could the item plausibly matter to that market? Yes for a listed issuer,
a sector of the exchange, the central bank / monetary policy, FX or the sum, taxes,
tariffs, state economic programs, the exchange itself, or macro conditions that move
prices. No for sport, horoscopes, weather, road accidents, crime, culture, celebrities,
festivals, lifestyle and purely local municipal notices.

If you are genuinely unsure, PASS it (score ~0.4) — a fuller pass decides afterwards.

Reply with ONLY a JSON object: {"pass": true|false, "score": 0.0-1.0}"""

# Anything at or above this passes to the full classification even if 'pass' came back
# false — the cheap gate should never be the last word on a borderline item.
_TRIAGE_FLOOR = float(os.getenv("NEWS_TRIAGE_FLOOR", "0.35"))


def triage_item(item: dict[str, Any], *, client: LLMClient | None = None,
                usage: Usage | None = None) -> tuple[bool, float]:
    """(passes, score) from the cheap gate. On any failure it PASSES the item through:
    a broken gate must not silently swallow market news."""
    client = client or get_classifier_client()
    try:
        raw = client.complete_json(_TRIAGE_SYSTEM, _format_item(item), usage=usage,
                                   max_tokens=60)
    except Exception as exc:  # noqa: BLE001 — never let the cheap gate drop an item
        logger.warning("triage failed for %s (%s) — passing through", item.get("url"), exc)
        return True, 1.0
    score = raw.get("score")
    try:
        score = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    passed = bool(raw.get("pass")) or score >= _TRIAGE_FLOOR
    return passed, score


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


_system_cache: dict[int, str] = {}


def _system_with_universe(universe: dict[str, str] | None) -> str:
    """The full-classification system prompt with the issuer universe appended.

    The universe used to be prepended to the USER message, which made ~69% of every
    request a constant that could never be a shared cache prefix. In the system message
    it is byte-identical across a run, so the provider serves it from its prompt cache
    (grok-4.3 $0.20/M vs $1.25/M; DeepSeek V4-Flash $0.0028/M vs $0.14/M). Memoised so
    the string is also identical object-to-object within a process.
    """
    key = id(universe) if universe else 0
    cached = _system_cache.get(key)
    if cached is None:
        cached = f"{_SYSTEM}\n\nISSUER UNIVERSE (ticker — name):\n{_format_universe(universe)}"
        _system_cache.clear()  # one universe per process in practice
        _system_cache[key] = cached
    return cached


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
    triage: bool = True,
) -> NewsClassification:
    """Classify one news item. Returns a validated ``NewsClassification``.

    With ``triage=True`` (the collector's path) a cheap pass/score call runs first and an
    item it rejects returns immediately, without paying for the full classification.
    Pass ``triage=False`` when the item was explicitly requested (Layer-B search for a
    named company): there the user's query is the relevance signal.

    On an LLM or validation failure, returns a safe ``relevant=False`` default so a
    single bad item never breaks a batch (the collector logs and skips it).
    """
    client = client or get_classifier_client()
    if triage:
        passed, score = triage_item(item, client=client, usage=usage)
        if not passed:
            return NewsClassification(relevant=False, relevance_score=score,
                                      reason="triage: not market-relevant")
    try:
        raw = client.complete_json(_system_with_universe(universe),
                                   f"NEWS ITEM:\n{_format_item(item)}", usage=usage)
        return NewsClassification.model_validate(raw)
    except ValidationError as exc:
        logger.warning("classification validation failed for %s: %s", item.get("url"), exc)
    except Exception as exc:  # noqa: BLE001 — one bad item must not kill the batch
        logger.warning("classification LLM error for %s: %s", item.get("url"), exc)
    return NewsClassification(relevant=False, reason="classification_failed")
