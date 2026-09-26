"""AI provider adapter: requests, retries, and output sanitization."""

from __future__ import annotations
import logging
import os
import re
import time
from openai import OpenAI
from reporting.settings import OPENAI_MODEL


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("api_key")


OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "medium").strip().lower() or "medium"


client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def _require_client() -> OpenAI:
    if client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured — AI analysis is unavailable")
    return client


logger = logging.getLogger(__name__)


def _sanitize_reasoning_effort(value: str) -> str:
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    return value if value in allowed else "low"


def api_call_with_retry(fn, max_retries: int = 6):
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status_code", None)
            response = getattr(exc, "response", None)
            if status is None and response is not None:
                status = getattr(response, "status_code", None)

            retriable = status in {429, 500, 502, 503, 504}
            if not retriable or attempt == max_retries - 1:
                raise

            wait = min(120, 10 * (2 ** attempt))
            headers = getattr(response, "headers", None)
            if headers:
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = int(float(retry_after)) + 2
                    except (TypeError, ValueError):
                        pass

            print(f"   ⏳ OpenAI error (attempt {attempt + 1}/{max_retries}), waiting {wait}s...")
            time.sleep(wait)


_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    # Russian — directive recommendations (tolerate up to 2 words in between)
    (r"рекоменду\w*\s+(?:\w+\s+){0,2}?(?:купить|покупать)", "по данным анализа факторы выглядят позитивно"),
    (r"рекоменду\w*\s+(?:\w+\s+){0,2}?(?:продать|продавать)", "по данным анализа факторы выглядят негативно"),
    (r"рекоменду\w*\s+(?:\w+\s+){0,2}?(?:держать|удерживать)", "по данным анализа факторы выглядят нейтрально"),
    (r"(?:советуе\w*|стоит|следует|целесообразно)\s+(?:купить|покупать)", "позитивные факторы преобладают"),
    (r"(?:советуе\w*|стоит|следует|целесообразно)\s+(?:продать|продавать)", "негативные факторы преобладают"),
    (r"рекомендаци\w*\s*[:——-]?\s*(?:покупать|купить)", "аналитический вывод: позитивный"),
    (r"рекомендаци\w*\s*[:——-]?\s*(?:продавать|продать)", "аналитический вывод: негативный"),
    (r"рекомендаци\w*\s*[:——-]?\s*(?:держать|удерживать)", "аналитический вывод: нейтральный"),
    (r"сигнал\s+(?:на\s+)?(?:покупку|продажу)", "аналитический сигнал"),
    # Russian — trade-execution / return-promise constructs (mirror the prompt bans:
    # целевая цена / стоп-лосс / размер позиции / ожидаемая доходность). Valuation
    # labels (недооценена/переоценена) are intentionally NOT neutralized — ТЗ §3.3
    # permits them in the closed contour beside the numbers with a disclaimer.
    (r"целев\w*\s+цен\w*", "оценка стоимости по показателям"),
    (r"стоп[-\s]?лосс\w*", "исторический ценовой уровень"),
    (r"(?:набира\w*|наращ\w*|нараст\w*|сократ\w*|уменьш\w*|открыва\w*|закрыва\w*|размер\w*)\s+позици\w*", "динамику показателей"),
    (r"ожидаем\w*\s+доходность\w*", "историческую доходность"),
    # English — directive recommendations
    (r"\b(?:recommend|advise|suggest)\w*\s+(?:to\s+)?buy\b", "the factors look positive"),
    (r"\b(?:recommend|advise|suggest)\w*\s+(?:to\s+)?sell\b", "the factors look negative"),
    (r"\b(?:recommend|advise|suggest)\w*\s+(?:to\s+)?hold\b", "the factors look neutral"),
    (r"\b(?:buy|sell|hold)\s+(?:rating|recommendation|signal)\b", "analytical assessment"),
    (r"\b(?:strong\s+)?(?:buy|sell|hold)\s+(?:the\s+)?(?:stock|shares)\b", "analytical assessment"),
    (r"\bstop[-\s]?loss\b", "historical price level"),
    (r"\btarget\s+price\b", "valuation estimate"),
    (r"\bposition\s+siz\w*\b", "the metric dynamics"),
    # Uzbek — directive recommendations (tolerate intervening words)
    (r"tavsiya[\w'\s:.,—-]{0,18}?sotib\s+ol\w*", "omillar ijobiy ko'rinadi"),
    (r"tavsiya[\w'\s:.,—-]{0,18}?sotish\w*", "omillar salbiy ko'rinadi"),
    (r"tavsiya[\w'\s:.,—-]{0,18}?ushlab\s+tur\w*", "omillar neytral ko'rinadi"),
]


_FORBIDDEN_COMPILED = [(re.compile(pat, re.IGNORECASE), repl) for pat, repl in _FORBIDDEN_PATTERNS]


def _sanitize_ai_text(text: str) -> str:
    """Neutralize any buy/sell/hold recommendation phrasing in generated output."""
    if not text:
        return text
    hits = 0
    cleaned = text
    for pattern, replacement in _FORBIDDEN_COMPILED:
        cleaned, n = pattern.subn(replacement, cleaned)
        hits += n
    if hits:
        logger.warning("AI output sanitizer neutralized %d forbidden recommendation phrase(s)", hits)
    return cleaned


def _responses_text(prompt: str, instructions: str, max_output_tokens: int) -> tuple[str, object]:
    def _call():
        return _require_client().responses.create(
            model=OPENAI_MODEL,
            reasoning={"effort": _sanitize_reasoning_effort(OPENAI_REASONING_EFFORT)},
            instructions=instructions,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )

    response = api_call_with_retry(_call)
    text = (getattr(response, "output_text", "") or "").strip()
    if not text:
        raise ValueError("OpenAI returned an empty response")
    text = _sanitize_ai_text(text)
    return text, response
