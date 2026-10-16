"""Abuse limits and OAuth CSRF protection.

Two regressions pinned here:
  * ``_client_ip`` trusted the LEFTMOST X-Forwarded-For entry, which the client
    controls — so every request could claim a fresh rate-limit bucket and neither
    login brute-force nor mass registration was actually limited.
  * the Google OAuth flow carried no ``state``, leaving login-CSRF and
    code-replay open.
"""
from __future__ import annotations

import server.auth.limits as subject_server_auth_limits
import server.auth.oauth as subject_server_auth_oauth

import importlib

import pytest

api = importlib.import_module("api")


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeURL:
    def __init__(self, scheme: str = "https") -> None:
        self.scheme = scheme


class _FakeRequest:
    """Just the surface _client_ip / _verify_oauth_state actually touch."""

    def __init__(self, *, headers: dict | None = None, peer: str | None = "10.0.0.1",
                 cookies: dict | None = None, scheme: str = "https") -> None:
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.client = _FakeClient(peer) if peer else None
        self.cookies = cookies or {}
        self.url = _FakeURL(scheme)


class TestClientIp:
    def test_the_rightmost_trusted_hop_is_used(self, monkeypatch) -> None:
        # The attack: the client sends a forged left-hand entry; the edge proxy
        # appends the real address. Only the appended one may be trusted.
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 1)
        request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9"})
        assert subject_server_auth_limits._client_ip(request) == "203.0.113.9"

    def test_a_spoofed_chain_cannot_mint_new_buckets(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 1)
        seen = {
            subject_server_auth_limits._client_ip(_FakeRequest(
                headers={"x-forwarded-for": f"10.9.9.{i}, 203.0.113.9"}))
            for i in range(50)
        }
        assert seen == {"203.0.113.9"}, "a client-controlled header still varies the bucket"

    def test_two_proxy_hops(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 2)
        request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4, 203.0.113.9, 198.51.100.7"})
        assert subject_server_auth_limits._client_ip(request) == "203.0.113.9"

    def test_a_short_chain_falls_back_to_the_peer(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 2)
        request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4"}, peer="198.51.100.1")
        assert subject_server_auth_limits._client_ip(request) == "198.51.100.1"

    def test_no_header_falls_back_to_the_peer(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 1)
        assert subject_server_auth_limits._client_ip(_FakeRequest(peer="198.51.100.2")) == "198.51.100.2"

    def test_zero_hops_ignores_the_header_entirely(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 0)
        request = _FakeRequest(headers={"x-forwarded-for": "1.2.3.4"}, peer="198.51.100.3")
        assert subject_server_auth_limits._client_ip(request) == "198.51.100.3"

    def test_unknown_peer_is_a_stable_key(self, monkeypatch) -> None:
        monkeypatch.setattr(subject_server_auth_limits, 'TRUSTED_PROXY_HOPS', 1)
        assert subject_server_auth_limits._client_ip(_FakeRequest(peer=None)) == "unknown"


def test_the_client_address_is_derived_in_one_place() -> None:
    # Analytics and the admin audit trail each parsed X-Forwarded-For themselves,
    # taking its client-written leftmost entry. Every reader of the header must go
    # through _client_ip, so one rule decides which entry is trusted.
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(["git", "ls-files", "*.py"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.split()
    readers = [
        path for path in tracked
        if not path.startswith(("tests/", "scripts/nginx_edge.py", "server/auth/limits.py"))
        and "x-forwarded-for" in (root / path).read_text(encoding="utf-8", errors="replace").lower()
    ]
    assert readers == [], f"read X-Forwarded-For outside server/auth/limits._client_ip: {readers}"


class TestSlidingWindowLimiter:
    def test_it_blocks_past_the_limit(self) -> None:
        limiter = subject_server_auth_limits._SlidingWindowLimiter()
        assert [limiter.allow("k", 3, 60.0) for _ in range(5)] == [True, True, True, False, False]

    def test_buckets_are_independent(self) -> None:
        limiter = subject_server_auth_limits._SlidingWindowLimiter()
        assert all(limiter.allow(f"k{i}", 1, 60.0) for i in range(10))

    def test_a_zero_limit_means_unlimited(self) -> None:
        limiter = subject_server_auth_limits._SlidingWindowLimiter()
        assert all(limiter.allow("k", 0, 60.0) for _ in range(100))

    def test_expired_buckets_are_evicted(self, monkeypatch) -> None:
        # Unbounded growth here is a memory leak driven by untrusted input.
        monkeypatch.setattr(subject_server_auth_limits, '_LIMITER_MAX_KEYS', 10)
        limiter = subject_server_auth_limits._SlidingWindowLimiter()
        for i in range(50):
            limiter.allow(f"k{i}", 5, 0.0)  # window 0 -> everything is instantly stale
        assert len(limiter._events) <= 11

    def test_eviction_keeps_buckets_whose_own_window_is_still_open(self, monkeypatch) -> None:
        # A short-window auth call used to trigger a sweep that judged every bucket by
        # its own 60 s window, wiping the 24 h LLM caps (the global one included).
        monkeypatch.setattr(subject_server_auth_limits, '_LIMITER_MAX_KEYS', 10)
        clock = [1000.0]
        monkeypatch.setattr(subject_server_auth_limits.time, 'monotonic', lambda: clock[0])
        limiter = subject_server_auth_limits._SlidingWindowLimiter()
        assert limiter.allow("llm-day:__global__", 1, 86400.0)
        clock[0] += 120.0
        for i in range(50):
            limiter.allow(f"login:{i}", 5, 60.0)
        assert "llm-day:__global__" in limiter._events
        assert limiter.allow("llm-day:__global__", 1, 86400.0) is False


class TestOauthState:
    def test_a_matching_state_verifies(self) -> None:
        request = _FakeRequest(cookies={subject_server_auth_oauth._OAUTH_STATE_COOKIE: "nonce-abc"})
        assert subject_server_auth_oauth._verify_oauth_state(request, "nonce-abc") is True

    def test_a_mismatched_state_is_rejected(self) -> None:
        request = _FakeRequest(cookies={subject_server_auth_oauth._OAUTH_STATE_COOKIE: "nonce-abc"})
        assert subject_server_auth_oauth._verify_oauth_state(request, "nonce-xyz") is False

    def test_a_missing_cookie_is_rejected(self) -> None:
        # Login CSRF: the victim's browser never started a flow, so it has no cookie.
        assert subject_server_auth_oauth._verify_oauth_state(_FakeRequest(), "attacker-supplied") is False

    def test_a_missing_state_param_is_rejected(self) -> None:
        request = _FakeRequest(cookies={subject_server_auth_oauth._OAUTH_STATE_COOKIE: "nonce-abc"})
        assert subject_server_auth_oauth._verify_oauth_state(request, None) is False
        assert subject_server_auth_oauth._verify_oauth_state(request, "") is False

    def test_the_authorize_url_carries_the_state(self, monkeypatch) -> None:
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
        monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://example.test/cb")
        url = subject_server_auth_oauth._build_google_auth_url(_FakeRequest(), "nonce-abc")
        assert "state=nonce-abc" in url
        assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")

    @pytest.mark.parametrize(("base", "scheme", "expected"), [
        ("https://prod.example", "http", True),
        ("http://plain.example", "https", False),
        ("", "https", True),
        ("", "http", False),
    ])
    def test_secure_flag_follows_the_real_scheme(self, monkeypatch, base, scheme, expected) -> None:
        monkeypatch.setenv("PUBLIC_BASE_URL", base)
        assert subject_server_auth_oauth._cookies_are_secure(_FakeRequest(scheme=scheme)) is expected


class TestMachineSecret:
    """A secret published in this public repository opens nothing."""

    def test_the_example_files_value_counts_as_unconfigured(self) -> None:
        from pathlib import Path
        import server.auth.access as access
        example = Path(__file__).resolve().parent.parent / ".env.example"
        value = next(line.split("=", 1)[1].strip() for line in example.read_text().splitlines()
                     if line.startswith("ADMIN_API_SECRET="))
        assert value.lower() in access.PUBLISHED_PLACEHOLDER_SECRETS

    @pytest.mark.parametrize("value", ["your_admin_push_secret", "ChangeMe", " secret "])
    def test_a_placeholder_is_refused_even_when_presented(self, monkeypatch, value) -> None:
        from fastapi.testclient import TestClient
        monkeypatch.setenv("ADMIN_API_SECRET", value)
        response = TestClient(api.app).post("/api/admin/news", headers={"X-Admin-Secret": value.strip()}, json={"items": []})
        assert response.status_code == 503

    def test_a_real_secret_still_opens_the_push(self, monkeypatch) -> None:
        from fastapi.testclient import TestClient
        import news_store
        monkeypatch.setenv("ADMIN_API_SECRET", "3f6c0a9e1d7b4c2a8e5f9d1b7c3a6e0f")
        monkeypatch.setattr(news_store, "upsert_news", lambda items: 0)
        response = TestClient(api.app).post("/api/admin/news", headers={"X-Admin-Secret": "3f6c0a9e1d7b4c2a8e5f9d1b7c3a6e0f"},
                                            json={"items": []})
        assert response.status_code == 200
