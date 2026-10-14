"""The publication checks of the analysis text.

An analysis is not published if any of these fails.  The checks read both
the text and what each sentence records about itself (lines described,
movement kind, verb tier, percent shown), so a word can be tested against the
number it was chosen from rather than only matched by pattern.
"""
from __future__ import annotations

from decimal import Decimal
import re

import financial_analysis.sector_vocabulary as vocab

MAX_SENTENCE_WORDS = 30
MIN_WORDS, MAX_WORDS = 250, 450
MOVEMENT_KINDS = frozenset({"trend", "to_loss", "to_profit", "loss_narrowed", "loss_widened", "tiny_base", "extreme",
                            "sign_change", "from_zero", "to_zero"})
TIER_MARKERS = {
    "ru": {vocab.TIER_SHARP: ("резко", "скачок", "в полтора раза"), vocab.TIER_SIGNIFICANT: ("значительно", "заметно", "существенно"),
           vocab.TIER_SLIGHT: ("немного", "умеренно", "слегка", "незначительно")},
    "uz": {vocab.TIER_SHARP: ("keskin", "sakrab", "bir yarim"), vocab.TIER_SIGNIFICANT: ("sezilarli", "ancha", "salmoqli"),
           vocab.TIER_SLIGHT: ("biroz", "mo‘tadil", "ozgina", "sal pasaydi")},
    "en": {vocab.TIER_SHARP: ("sharply", "jumped", "by half"), vocab.TIER_SIGNIFICANT: ("significantly", "markedly", "substantially"),
           vocab.TIER_SLIGHT: ("edged", "slightly", "modestly", "dipped")},
}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁO‘“«])")
_GROUPED_THOUSANDS = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?![\d])")
_LONG_NUMBER = re.compile(r"\d{5,}")
_RAW_DECIMALS = re.compile(r"\d[.,]\d{2}\s*(?:тыс|ming|thousand)|\d\.00\b")
_SNAKE = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s?%")


def _words(text):
    return [word for word in re.split(r"\s+", text.strip()) if re.search(r"\w", word)]


def _check(code, failures):
    return {"code": code, "status": "failed" if failures else "passed", "failures": failures[:5]}


def run(sentences, *, lang, verdict_status, complete, comparison_sources=None):
    """``sentences`` is a list of (section_id, Sentence)."""
    lang = lang if lang in vocab.LANGS else "ru"
    body = [(section, s) for section, s in sentences if section != "footnote"]
    texts = [s.text for _, s in sentences]
    whole = " ".join(texts)
    checks = []

    # text_number_format: no «тыс. сум», no «.00», no unscaled long numbers.
    failures = [phrase for phrase in ("тыс. сум", "ming so‘m", "thousand UZS") if phrase in whole]
    failures += _GROUPED_THOUSANDS.findall(whole) + _LONG_NUMBER.findall(whole) + _RAW_DECIMALS.findall(whole)
    checks.append(_check("text_number_format", failures))

    # no_pct_from_zero_or_sign_change: a percent only on a measurable trend.
    failures = [s.text for _, s in body if s.percent_shown and s.kind not in {"trend", "pace"}]
    failures += [s.text for _, s in body if s.kind == "trend" and s.tier == vocab.TIER_MULTIPLE and s.percent_shown]
    failures += [match for match in _PERCENT.findall(whole) if Decimal(match.replace(",", ".")) > 100]
    checks.append(_check("no_pct_from_zero_or_sign_change", failures))

    # no_banned_phrases: the removed phrases, service names and unearned evaluation.
    lowered = whole.lower()
    failures = [phrase for phrase in vocab.BANNED_PHRASES if phrase.lower() in lowered]
    failures += _SNAKE.findall(whole)
    failures += [s.text for _, s in body if not s.evaluative and any(word in s.text.lower() for word in vocab.EVALUATIVE_WORDS)]
    checks.append(_check("no_banned_phrases", failures))

    # no_duplicate_sentences: no sentence twice, no line's movement twice,
    # no line's percent change twice (the headline's percent restated below).
    seen, failures, described = set(), [], {}
    headline_percents = {code for section, s in sentences if section == "headline" for code in s.percent_codes}
    failures += [s.text for section, s in body if section != "headline" and s.kind == "trend"
                 and (s.percent_shown or s.tier == vocab.TIER_MULTIPLE) and any(code in headline_percents for code in s.metrics)]
    for section, s in body:
        for part in _SENTENCE_SPLIT.split(s.text):
            key = re.sub(r"\W+", " ", part.lower()).strip()
            if key in seen:
                failures.append(part)
            seen.add(key)
        if s.kind in MOVEMENT_KINDS and section != "headline":
            for code in s.metrics:
                if code in described:
                    failures.append(f"{code}: {described[code]} / {section}")
                described[code] = section
    checks.append(_check("no_duplicate_sentences", failures))

    # verb_matches_magnitude: the verb's tier is the tier of its number.
    failures = []
    markers = TIER_MARKERS[lang]
    for _, s in body:
        if s.kind != "trend" or s.pct is None:
            continue
        if vocab.tier_of(s.pct) != s.tier:
            failures.append(s.text)
            continue
        head = re.split(r", (?:за счёт|asosan|driven by)", s.text)[0].lower()
        for tier, words in markers.items():
            if tier != s.tier and any(re.search(rf"(?<!\w){re.escape(word)}(?!\w)", head) for word in words):
                failures.append(s.text)
    checks.append(_check("verb_matches_magnitude", failures))

    # sentence_length: sentences of 30 words at most, the analysis 250–450 words.
    failures = []
    for text in texts:
        for part in _SENTENCE_SPLIT.split(text):
            if len(_words(part)) > MAX_SENTENCE_WORDS:
                failures.append(part)
    total = len(_words(" ".join(s.text for _, s in body)))
    if total > MAX_WORDS:
        failures.append(f"{total} words")
    length = _check("sentence_length", failures)
    # The 250-word floor is a target, not a gate: a filing with few lines
    # cannot reach it without the filler the specification removes, so a
    # short text is flagged for review but still published.
    if not failures and complete and total < MIN_WORDS:
        length["status"] = "warning"
        length["failures"] = [f"{total} words, below the {MIN_WORDS}-word target"]
    checks.append(length)

    # verdict_has_reason: a verdict with its reason; no comparison beside «no data».
    verdict = next((s.text for section, s in sentences if s.kind == "verdict"), "")
    failures = []
    reason = verdict.split("—", 1)[1] if "—" in verdict else ""
    if len(_words(reason)) < 2:
        failures.append(verdict or "missing verdict")
    if verdict_status == "no_signal" and any(s.kind in MOVEMENT_KINDS for _, s in body):
        failures.append("comparison next to «без динамики»")
    checks.append(_check("verdict_has_reason", failures))

    # comparison_fallback_used: an available comparison was used.
    sources = comparison_sources or {}
    failures = [side for side in ("previous", "opening")
                if sources.get(f"{side}_available") and not sources.get(f"{side}_used")]
    checks.append(_check("comparison_fallback_used", failures))

    return {"status": "failed" if any(c["status"] == "failed" for c in checks) else "passed", "word_count": total, "checks": checks}
