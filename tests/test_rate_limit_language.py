"""A rate-limit refusal is worded in the reader's language and says when to retry."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import server.auth.limits as limits


def _request(headers):
    return SimpleNamespace(headers={k.lower(): v for k, v in headers.items()}, client=SimpleNamespace(host="10.0.0.1"))


@pytest.fixture
def fresh_limiter(monkeypatch):
    limiter = limits._SlidingWindowLimiter()
    monkeypatch.setattr(limits, "_rate_limiter", limiter)
    monkeypatch.setattr(limits, "LLM_RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(limits, "LLM_DAILY_LIMIT", 100)
    monkeypatch.setattr(limits, "LLM_GLOBAL_DAILY_LIMIT", 100)
    return limiter


@pytest.mark.parametrize("language, expected", [
    ("ru", "Превышен лимит запросов. Попробуйте через"),
    ("uz", "So‘rovlar chegarasidan oshildi."),
    ("en", "Request limit exceeded. Try again in"),
    (None, "Request limit exceeded. Try again in"),
])
def test_analysis_limit_is_worded_in_the_interface_language(fresh_limiter, language, expected):
    user = SimpleNamespace(id=7)
    limits._enforce_llm_quota(user, language)
    with pytest.raises(HTTPException) as caught:
        limits._enforce_llm_quota(user, language)
    assert caught.value.status_code == 429
    assert caught.value.detail.startswith(expected)
    seconds = int(caught.value.headers["Retry-After"])
    assert 1 <= seconds <= 60
    if language == "ru":
        assert caught.value.detail.endswith(f"{seconds} {limits._seconds_word(seconds)}.")


def test_auth_limit_reads_the_request_language(fresh_limiter, monkeypatch):
    monkeypatch.setattr(limits, "AUTH_RATE_LIMIT_PER_MINUTE", 1)
    request = _request({"Accept-Language": "uz-UZ,ru;q=0.8"})
    limits._enforce_auth_rate_limit(request, "login")
    with pytest.raises(HTTPException) as caught:
        limits._enforce_auth_rate_limit(request, "login")
    assert caught.value.status_code == 429 and caught.value.detail.startswith("So‘rovlar")
    assert "Retry-After" in caught.value.headers


def test_request_language_prefers_the_interface_header():
    assert limits.request_language(_request({"X-UI-Language": "ru", "Accept-Language": "en-US"})) == "ru"
    assert limits.request_language(_request({"Accept-Language": "de-DE,en;q=0.5"})) == "en"
    assert limits.request_language(_request({"Accept-Language": "de-DE"})) is None
    assert limits.request_language(None) is None


@pytest.mark.parametrize("seconds, word", [(1, "секунду"), (2, "секунды"), (5, "секунд"), (11, "секунд"),
                                           (21, "секунду"), (22, "секунды"), (44, "секунды"), (59, "секунд")])
def test_russian_seconds_agree_with_the_number(seconds, word):
    assert limits._seconds_word(seconds) == word
