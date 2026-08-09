"""Layer A — per-item news classifier (the cheap, high-volume path).

Three gates, cheapest first, because this path runs once per collected item and the
enabled feeds are whole-site feeds where most items are not market news at all:

  0. ``prefilter_reject`` — free, code only. Drops obvious non-market items (sport,
     horoscopes, weather, accidents, culture) that carry no market signal.
  1. ``triage_item`` — one tiny LLM call: pass/score only, no issuer universe in the
     prompt, ~20 output tokens.
  2. the full classification — class, tone, impact, direction, issuer links and our own
     summary, and ONLY for items that survive triage.

Both LLM gates are **batched**: many numbered items per call, one shared prompt. Measured on
the 2026-07-25 run, the ~2,200-token constant prefix was re-sent 31 times and accounted for
68% of all input tokens, while the news text itself was 2%. Batching sends it once per batch
instead of once per item; output volume is unchanged, so the saving is pure input.

The expensive constant (the ~93-line issuer universe) sits in the SYSTEM message so it
is an identical prefix on every call and the provider's prompt cache can serve it: on
grok-4.3 cached input is $0.20/M vs $1.25/M, on DeepSeek V4-Flash $0.0028/M vs $0.14/M.

Issuer filings take a separate, compact prompt: their ticker and class come from the filing
itself, so sending them the issuer universe is pure waste.

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
    # The site is served in three languages. These come from the SAME call that writes
    # summary_ru — no second request, no translation provider, no key — because the only
    # free alternative cannot do the job: real Chrome's on-device translator reports
    # ru->uz, uz->ru and en->uz as "unavailable" (checked 2026-07-29), so the Uzbek feed
    # has no browser-side route at all. Empty is tolerated: the reader falls back to
    # Russian rather than to a blank card.
    summary_en: str = Field(default="", description="The same summary in English.")
    summary_uz: str = Field(default="", description="The same summary in Uzbek (Latin script).")
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
    # Added 2026-07-25 from the titles the paid triage gate actually rejected — every one of
    # these cost a call to learn nothing. Sports betting/fights, state awards, municipal
    # works, consular paperwork and party politics.
    r"|букмекер|андердог|\bбо[йя] с\b|нокаут|титульны|наградил|орденом|медал"
    r"|теплотрасс|благоустройств|экопарк|зелены[хе] зон|генеральный план|генплан"
    r"|загранпаспорт|визовы[йм] режим|визовых|оргнабор|омбудсмен"
    r"|оштрафовал|штраф|конфискова|музе[йя]|выставк[аи] картин"
    r"|futbol|chempionat|musobaqa|\bsport|ob-havo|halok|jinoyat|\bkino\b|konsert|festival"
    r"|sayli|bayram"
    # Uzbek: Kun.uz alone accounted for 14 of those 34 paid rejections.
    r"|saylov|partiya|iste'?fo|musodara|jarima|vizasiz|viza rejimi|nomzod"
    r"|xandaq|avtomobil.{0,12}(?:tushib|urib)|jinoiy sud|qoidabuzar|hukm qil"
    r"|football|championship|olympic|weather|accident|crime|concert|festival|movie"
    r"|celebrity|horoscope|boxing|bookmaker",
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

_BATCH_PROTOCOL = """

You will be given SEVERAL numbered items. Judge each one INDEPENDENTLY — never merge them,
never let one item's content influence another's verdict. Reply with ONLY:
{"items": [{"n": <the number the item was given>, ...the fields above...}, ...]}
Return exactly one object per item, echoing the number it was given."""

# Anything at or above this passes to the full classification even if 'pass' came back
# false — the cheap gate should never be the last word on a borderline item.
_TRIAGE_FLOOR = float(os.getenv("NEWS_TRIAGE_FLOOR", "0.35"))
# Items per call. Triage batches larger because both its item text and its answer are tiny.
_BATCH_SIZE = max(1, int(os.getenv("NEWS_BATCH_SIZE", "10")))
_TRIAGE_BATCH_SIZE = max(1, int(os.getenv("NEWS_TRIAGE_BATCH_SIZE", "20")))


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
    return _triage_verdict(raw)


def _triage_verdict(raw: dict[str, Any]) -> tuple[bool, float]:
    score = raw.get("score")
    try:
        score = float(score) if score is not None else 0.0
    except (TypeError, ValueError):
        score = 0.0
    passed = bool(raw.get("pass")) or score >= _TRIAGE_FLOOR
    return passed, score


def _numbered(items: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"### ITEM {i + 1}\n{_format_item(it)}" for i, it in enumerate(items))


def _by_number(raw: Any, expected: int) -> dict[int, dict[str, Any]]:
    """Map a batch reply back onto the items we sent, by the echoed ``n``.

    Tolerates a bare list, a missing ``n`` (falls back to position), and out-of-range
    numbers. Whatever cannot be matched is simply absent — callers retry those individually
    rather than guessing, because a mis-attributed verdict is worse than a second call.
    """
    rows = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        try:
            n = int(row.get("n", position + 1))
        except (TypeError, ValueError):
            n = position + 1
        if 1 <= n <= expected:
            out.setdefault(n, row)
    return out


def screen_items(items: list[dict[str, Any]], *, client: LLMClient | None = None,
                 usage: Usage | None = None) -> list[tuple[bool, float]]:
    """Batched gate 1: ``[(passes, score), ...]`` aligned with ``items``.

    Fails open per item — anything the batch does not come back with is retried on its own,
    and a failure there passes the item through. A cheap gate must never silently swallow
    market news.
    """
    verdicts: list[tuple[bool, float]] = []
    client = client or get_classifier_client()
    for start in range(0, len(items), _TRIAGE_BATCH_SIZE):
        chunk = items[start:start + _TRIAGE_BATCH_SIZE]
        if len(chunk) == 1:
            verdicts.append(triage_item(chunk[0], client=client, usage=usage))
            continue
        rows: dict[int, dict[str, Any]] = {}
        try:
            raw = client.complete_json(_TRIAGE_SYSTEM + _BATCH_PROTOCOL, _numbered(chunk),
                                       usage=usage, max_tokens=60 * len(chunk) + 120)
            rows = _by_number(raw, len(chunk))
        except Exception as exc:  # noqa: BLE001 — fall through to per-item retries
            logger.warning("batched triage failed for %d item(s) (%s); retrying individually",
                           len(chunk), exc)
        missing = 0
        for i, it in enumerate(chunk, start=1):
            if i in rows:
                verdicts.append(_triage_verdict(rows[i]))
            else:
                missing += 1
                verdicts.append(triage_item(it, client=client, usage=usage))
        if missing and rows:
            logger.info("batched triage: %d of %d item(s) missing from the reply, "
                        "retried individually", missing, len(chunk))
    return verdicts


def classify_items(items: list[dict[str, Any]], universe: dict[str, str] | None = None, *,
                   client: LLMClient | None = None, usage: Usage | None = None,
                   ) -> list[NewsClassification]:
    """Batched gate 2, aligned with ``items``. Triage is NOT applied here — call
    :func:`screen_items` first and pass only the survivors.

    Any item the batch fails to return, or whose row does not validate, is re-classified on
    its own; only if that also fails does it get ``classification_failed`` (which the
    collector then declines to store, so the item is retried next run).
    """
    results: list[NewsClassification] = []
    client = client or get_classifier_client()
    system = _system_with_universe(universe) + _BATCH_PROTOCOL
    for start in range(0, len(items), _BATCH_SIZE):
        chunk = items[start:start + _BATCH_SIZE]
        if len(chunk) == 1:
            results.append(classify_item(chunk[0], universe, client=client, usage=usage,
                                         triage=False))
            continue
        rows: dict[int, dict[str, Any]] = {}
        try:
            # 480 -> 620: two more summaries of the same length as summary_ru. Measured
            # 2026-07-29 the reply averaged ~380 tokens an item, so the headroom holds.
            raw = client.complete_json(system, _numbered(chunk), usage=usage,
                                       max_tokens=620 * len(chunk) + 200)
            rows = _by_number(raw, len(chunk))
        except Exception as exc:  # noqa: BLE001
            logger.warning("batched classification failed for %d item(s) (%s); "
                           "retrying individually", len(chunk), exc)
        retried = 0
        for i, it in enumerate(chunk, start=1):
            row = rows.get(i)
            if row is not None:
                try:
                    results.append(NewsClassification.model_validate(row))
                    continue
                except ValidationError as exc:
                    logger.warning("batched row %d did not validate (%s); retrying alone",
                                   i, exc)
            retried += 1
            results.append(classify_item(it, universe, client=client, usage=usage,
                                         triage=False))
        if retried and rows:
            logger.info("batched classification: %d of %d item(s) retried individually",
                        retried, len(chunk))
    return results


_SYSTEM = """You are a financial-news triage engine for a Uzbekistan stock-market platform
covering ~93 issuers on the Tashkent exchange (UZSE / RFB "Toshkent"): banks
(Hamkorbank, Ipoteka, Kapitalbank…), cement/industrials (Qizilqumsement, Kvarts…),
and state issuers heading for IPO.

For each news item decide, as a STATISTICAL/ANALYTICAL SIGNAL (never a diagnosis,
never a claim of manipulation or "attack"):

1. relevant — could this move a listed price or the market? A NAMED listed issuer is NOT
   required. The board's issuers are whoever operates in these sectors, so a state programme,
   law, tariff, licence or large investment that touches one of them is relevant on its own:
   banking and insurance, energy and power generation, oil/gas/chemicals, mining and metals,
   cement and construction, telecom, transport corridors, agriculture — as are monetary
   policy, FX and the sum, taxes, and the exchange itself. A nuclear power programme, a
   mining tax regime, a new rail corridor, crypto-asset or stablecoin rules and a foreign
   credit line to a state bank all qualify even when no issuer is named in the text.
   NOT relevant: sport, culture, celebrities, weather, crime, accidents, health scares,
   human-interest writing, and protocol diplomacy carrying no economic decision.
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
9. summary_en / summary_uz — THE SAME summary in English and in Uzbek (Latin script).
   Same facts, same figures, same length as summary_ru — a translation of your own summary,
   not a second opinion and not a longer one. Uzbek in Latin script only, never Cyrillic.
10. reason — why this class/tone, in AT MOST 12 WORDS. It is an internal note, never shown.

Reply with ONLY a JSON object with keys:
relevant, relevance_score, type, tone, tone_score, impact, direction, tickers, sectors,
summary_ru, summary_en, summary_uz, reason."""


# Filings arrive with their issuer and class already known (openinfo org_id → ticker,
# fact_number → class), so this prompt carries no issuer universe at all — on the measured
# run that was ~2,200 wasted tokens per filing — and asks only for what a model can add.
_FILING_SYSTEM = """You rate disclosures ("существенные факты") filed by issuers on the
Tashkent exchange (UZSE / RFB "Toshkent"). The issuer and the filing class are ALREADY known
and are not your job — do not infer or restate them.

Judge only the following, as a STATISTICAL/ANALYTICAL SIGNAL (never a diagnosis, never a
claim of manipulation or "attack"):
1. tone — positive / neutral / negative FOR INVESTORS IN THAT ISSUER, and tone_score in [-1,1].
2. impact — high / medium / low / none: how strongly this filing could move the issuer's price.
   Routine administrative filings (changes to lists of affiliates, of branches, of governing
   bodies) are usually low or none; dividends, share issuance, large deals, credit above half
   of capital, bankruptcy and delisting are higher.
3. direction — up / down / mixed / unclear (an estimate, not advice).
4. summary_ru — YOUR OWN one-sentence factual summary in Russian, based only on what the
   filing's title states. Never invent amounts, dates or counterparties.
5. summary_en / summary_uz — the same sentence in English and in Uzbek (Latin script).
6. reason — at most 12 words, an internal note.

Reply with ONLY a JSON object with keys: tone, tone_score, impact, direction,
summary_ru, summary_en, summary_uz, reason."""


def classify_filings(items: list[dict[str, Any]], *, client: LLMClient | None = None,
                     usage: Usage | None = None) -> list[NewsClassification]:
    """Batched rating of issuer filings, aligned with ``items``.

    Returns ``relevant=True`` throughout: an issuer's own disclosure is market news because
    the issuer filed it. ``type`` comes from the item's ``type_hint`` (derived from the
    filing's own fact number), and tickers are attached by the caller — so a model can
    neither drop a filing nor mis-attribute one.
    """
    results: list[NewsClassification] = []
    client = client or get_classifier_client()

    def build(row: dict[str, Any], item: dict[str, Any]) -> NewsClassification:
        return NewsClassification.model_validate({
            "relevant": True,
            "relevance_score": 0.9,
            "type": item.get("type_hint") or "corporate_event",
            "tone": row.get("tone"), "tone_score": row.get("tone_score"),
            "impact": row.get("impact"), "direction": row.get("direction"),
            "tickers": item.get("tickers") or [], "sectors": [],
            "summary_ru": row.get("summary_ru") or "",
            "summary_en": row.get("summary_en") or "",
            "summary_uz": row.get("summary_uz") or "",
            "reason": (row.get("reason") or "issuer filing")[:200],
        })

    for start in range(0, len(items), _BATCH_SIZE):
        chunk = items[start:start + _BATCH_SIZE]
        rows: dict[int, dict[str, Any]] = {}
        single = len(chunk) == 1
        try:
            system = _FILING_SYSTEM if single else _FILING_SYSTEM + _BATCH_PROTOCOL
            user = _format_item(chunk[0]) if single else _numbered(chunk)
            raw = client.complete_json(system, user, usage=usage,
                                       max_tokens=(420 if single else 380 * len(chunk) + 200))
            rows = {1: raw} if single else _by_number(raw, len(chunk))
        except Exception as exc:  # noqa: BLE001 — a filing must still be stored
            logger.warning("filing rating failed for %d item(s): %s", len(chunk), exc)
        for i, it in enumerate(chunk, start=1):
            row = rows.get(i)
            if row is None:
                # Store the filing anyway, unrated: losing a disclosure would be worse than
                # showing one with a neutral signal.
                results.append(build({"tone": "neutral", "impact": "low",
                                      "direction": "unclear",
                                      "summary_ru": it.get("snippet") or "",
                                      "reason": "filing stored unrated"}, it))
                continue
            try:
                results.append(build(row, it))
            except ValidationError as exc:
                logger.warning("filing row %d did not validate (%s); storing unrated", i, exc)
                results.append(build({"tone": "neutral", "impact": "low",
                                      "direction": "unclear",
                                      "summary_ru": it.get("snippet") or "",
                                      "reason": "filing stored unrated"}, it))
    return results


# Backfill only. New items get all three summaries from the classification call itself; this
# exists for rows stored before those columns did. No issuer universe, no judgement, no
# re-classification — just the Russian sentence we already wrote, in the other two languages,
# so a backfill can never change an item's tone, impact or issuer links.
_TRANSLATE_SYSTEM = """You translate short financial-news summaries for a Uzbekistan
stock-market platform. You are given a summary in Russian that the platform wrote itself.

Return it in English and in Uzbek (Latin script only, never Cyrillic). Same facts, same
figures, same length — a translation, not a rewrite, not a summary of the summary, and never
an addition. Keep tickers, company names and numbers exactly as they appear.

Reply with ONLY a JSON object: {"summary_en": "...", "summary_uz": "..."}"""


def translate_summaries(items: list[dict[str, Any]], *, client: LLMClient | None = None,
                        usage: Usage | None = None) -> list[dict[str, str]]:
    """``[{"en": ..., "uz": ...}, ...]`` aligned with ``items`` (each needs ``summary_ru``).

    Batched like the other gates. A row that fails comes back as empty strings, which the
    caller stores as "no translation" — the reader then falls back to Russian, exactly as
    they did before this existed.
    """
    out: list[dict[str, str]] = []
    client = client or get_classifier_client()
    for start in range(0, len(items), _BATCH_SIZE):
        chunk = items[start:start + _BATCH_SIZE]
        rows: dict[int, dict[str, Any]] = {}
        single = len(chunk) == 1
        body = "\n\n".join(
            f"### ITEM {i + 1}\n{(it.get('summary_ru') or '').strip()}"
            for i, it in enumerate(chunk))
        try:
            system = _TRANSLATE_SYSTEM if single else _TRANSLATE_SYSTEM + _BATCH_PROTOCOL
            user = (chunk[0].get("summary_ru") or "").strip() if single else body
            raw = client.complete_json(system, user, usage=usage,
                                       max_tokens=(220 if single else 200 * len(chunk) + 150))
            rows = {1: raw} if single else _by_number(raw, len(chunk))
        except Exception as exc:  # noqa: BLE001 — a failed backfill must not abort the run
            logger.warning("summary translation failed for %d item(s): %s", len(chunk), exc)
        for i in range(1, len(chunk) + 1):
            row = rows.get(i) or {}
            out.append({"en": str(row.get("summary_en") or "").strip(),
                        "uz": str(row.get("summary_uz") or "").strip()})
    return out


# The long read on the story page. Two hard rules, and the second is the whole design: the
# article text this call is given is read ONCE, in memory, and is never stored anywhere — what
# comes back is our own account of it, which is the only thing that reaches the database (see
# the legal invariant in NEWS_MODULE.md). A translation of the source's paragraphs would be
# the source's paragraphs.
_DETAIL_SYSTEM = """You write the body text of a story page for a Uzbekistan stock-market
platform. You are given a news article that a source published, and you retell it IN YOUR OWN
WORDS for a reader who will not open the source.

Write 3-5 short paragraphs, separated by a blank line. Cover what happened, who is involved,
the concrete figures, dates and institutions named, and — if the article says so — what
follows next. Facts only: never add, infer or estimate anything the article does not state,
never add market commentary or advice, never mention listed companies the article does not
mention.

Do NOT translate the article and do NOT copy its sentences. Rewrite. If a phrase must be
quoted because it is an official formulation, keep it under ten words.

Write the SAME text in three languages: Russian, English, and Uzbek in Latin script (never
Cyrillic). Same facts, same figures, same length in each.

If the text you are given is not an article — a paywall notice, a cookie banner, a navigation
menu, an error page, or fewer than three sentences of substance — return empty strings rather
than inventing an article.

Reply with ONLY a JSON object: {"detail_ru": "...", "detail_en": "...", "detail_uz": "..."}"""

# Paragraph breaks are the point of this field, so the model's "\n\n" must survive; a JSON
# string carries them literally.
_DETAIL_MAX_CHARS = int(os.getenv("NEWS_DETAIL_MAX_CHARS", "9000"))


# The long read for an item that HAS no article page: an openinfo filing (the portal 404s
# every per-fact URL) or a source that ships nothing but a headline. There is no source text
# to read here, so this call is given only what we already hold — the disclosure's own
# figures, our own summary — and its job is to lay them out, not to research the story.
#
# Hence "expand" and not "write": with no article behind it, the difference between a useful
# page and a fabricated one is whether the model may add a single fact. It may not.
_BRIEF_SYSTEM = """You write the body text of a story page for a Uzbekistan stock-market
platform. You are given everything that is known about one item: its headline, a short
summary, and — for a regulatory filing — the figures the filing itself states. There is no
article to read: this is all there is.

Lay that material out as 2-4 short paragraphs separated by a blank line: what was filed or
reported, which issuer and which securities it concerns, every figure and date given, and who
it affects. Order it so a holder of the security learns the consequence first.

ABSOLUTELY NO NEW FACTS. Every number, name, date and institution in your text must appear in
the material given. Do not infer amounts, do not estimate, do not explain what the issuer
"probably" means, do not add market commentary, background, history or advice, and never
mention a company the material does not mention. You are formatting known facts, not
researching them.

Repetition is better than invention: if the material supports only two short paragraphs,
write two. If it is a bare headline with nothing behind it — fewer than two facts worth
stating — return empty strings.

Write the SAME text in three languages: Russian, English, and Uzbek in Latin script (never
Cyrillic). Same facts, same figures, same length in each.

Reply with ONLY a JSON object: {"detail_ru": "...", "detail_en": "...", "detail_uz": "..."}"""

# Below this there is nothing to lay out — a headline and a half-line teaser expand into
# padding, and padding on a story page is worse than the summary it replaced.
_BRIEF_MIN_MATERIAL = int(os.getenv("NEWS_BRIEF_MIN_CHARS", "180"))


def brief_material(item: dict[str, Any]) -> str:
    """Everything known about an item that has no article page, as one block.

    Deduplicated on the way in: the snippet and the summary are frequently the same sentence,
    and handing the model the same fact twice is how a two-fact filing turns into four
    paragraphs.
    """
    seen: list[str] = []
    for field in ("summary_ru", "snippet"):
        text = str(item.get(field) or "").strip()
        if not text:
            continue
        if any(text in kept or kept in text for kept in seen):
            continue
        seen.append(text)
    return "\n\n".join(seen)


def write_brief_detail(item: dict[str, Any], *, client: LLMClient | None = None,
                       usage: Usage | None = None) -> dict[str, str]:
    """``{"ru":…, "en":…, "uz":…}`` from the stored material alone, or empty strings.

    Used for the items :func:`write_detail` can never serve — openinfo filings and the
    sources that publish no article page. Returns empty strings when there is too little to
    lay out, which is the honest outcome for a bare rating headline.
    """
    material = brief_material(item)
    if len(material) < _BRIEF_MIN_MATERIAL:
        return {"ru": "", "en": "", "uz": ""}
    client = client or get_classifier_client()
    tickers = ", ".join(str(t) for t in (item.get("tickers") or []) if t)
    user = (f"HEADLINE: {(item.get('title') or '').strip()}\n"
            f"SOURCE: {(item.get('source') or item.get('source_id') or '').strip()}\n"
            + (f"SECURITIES: {tickers}\n" if tickers else "")
            + (f"DATE: {item.get('published_at')}\n" if item.get("published_at") else "")
            + f"\nMATERIAL:\n{material[:_DETAIL_MAX_CHARS]}")
    try:
        raw = client.complete_json(_BRIEF_SYSTEM, user, usage=usage, max_tokens=1200)
    except Exception as exc:  # noqa: BLE001 — a story page without a long read is the old page
        logger.warning("brief detail failed for %s: %s", item.get("url"), exc)
        return {"ru": "", "en": "", "uz": ""}
    out = {code: str(raw.get(f"detail_{code}") or "").strip() for code in ("ru", "en", "uz")}
    # All three or none, for the same reason as write_detail.
    if not out["ru"]:
        return {"ru": "", "en": "", "uz": ""}
    return out


def write_detail(item: dict[str, Any], article_text: str, *,
                 client: LLMClient | None = None,
                 usage: Usage | None = None) -> dict[str, str]:
    """``{"ru":…, "en":…, "uz":…}`` — our own long read of one article, or empty strings.

    One call per item rather than a batch: an article is 1-3k tokens on its own, so batching
    would blow past a sane max_tokens and one bad extraction would poison its neighbours.
    Volume is low by construction — the caller only asks for feed-visible items that have no
    long read yet, under a per-run cap.
    """
    text = (article_text or "").strip()
    if len(text) < 200:
        return {"ru": "", "en": "", "uz": ""}
    client = client or get_classifier_client()
    user = (f"HEADLINE: {(item.get('title') or '').strip()}\n"
            f"SOURCE: {(item.get('source') or item.get('source_id') or '').strip()}\n\n"
            f"ARTICLE:\n{text[:_DETAIL_MAX_CHARS]}")
    try:
        raw = client.complete_json(_DETAIL_SYSTEM, user, usage=usage, max_tokens=1600)
    except Exception as exc:  # noqa: BLE001 — a story page without a long read is the old page
        logger.warning("detail write failed for %s: %s", item.get("url"), exc)
        return {"ru": "", "en": "", "uz": ""}
    out = {code: str(raw.get(f"detail_{code}") or "").strip() for code in ("ru", "en", "uz")}
    # All three or none: a page that shows Russian paragraphs to an English reader because the
    # other two came back empty is worse than the summary-only page it replaces.
    if not out["ru"]:
        return {"ru": "", "en": "", "uz": ""}
    return out


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
