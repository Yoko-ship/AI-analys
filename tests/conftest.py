"""Explicit test adapters for protected HTTP contract checks."""

import server.auth.access as subject_server_auth_access
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    """A moved test adapter must fail instead of silently contacting a live source."""
    import requests

    def unexpected_request(*args, **kwargs):
        raise AssertionError("Live HTTP is disabled in unit tests; inject the source adapter")

    monkeypatch.setattr(requests.sessions.Session, "send", unexpected_request)


@pytest.fixture(autouse=True)
def no_openinfo_cache(monkeypatch):
    """Tests never read or write the data directory's openinfo cache, nor share a run's report lists."""
    import sys
    monkeypatch.setenv("OPENINFO_CACHE", "0")
    reconcile = sys.modules.get("openinfo_reconcile")
    if reconcile is not None:
        reconcile._listings.clear()


@pytest.fixture(autouse=True)
def no_geoip_download(monkeypatch):
    """An app started in a test must not fetch the visitor-geography database."""
    monkeypatch.setenv("GEOIP_REFRESH", "0")


@pytest.fixture(autouse=True)
def isolated_terminal_journal(monkeypatch, tmp_path):
    """Requests made in a test write their journal events to a throwaway file,
    never into the real data directory's journal."""
    from server.terminal import journal

    monkeypatch.setenv("TERMINAL_JOURNAL_DB", str(tmp_path / "terminal_journal.sqlite3"))
    with journal._lock:
        journal._buffer.clear()
    yield
    journal.flush()
    with journal._lock:
        journal._buffer.clear()


@pytest.fixture(autouse=True)
def no_admin_step_up_carryover():
    """An admin step-up lives in process memory, keyed by session token. One
    test's proof (or its failed attempts) must not open or close another's gate."""
    import server.auth.limits as auth_limits

    def clear():
        subject_server_auth_access._step_ups.clear()
        for key in [k for k in auth_limits._rate_limiter._events if k.startswith("step-up:")]:
            auth_limits._rate_limiter._events.pop(key, None)

    clear()
    yield
    clear()


ADMIN_OTP = "123456"


@pytest.fixture
def admin_authenticator(monkeypatch):
    """The signed-in admin's authenticator: accepts ADMIN_OTP. Returns the header
    an admin change carries to prove it (server/auth/access.py, step-up)."""
    import web_auth

    monkeypatch.setattr(web_auth.web_auth_store.security, "verify_admin_two_factor",
                        lambda user_id, code: code == ADMIN_OTP)
    return {"X-Admin-OTP": ADMIN_OTP}


@pytest.fixture
def authenticated_reader(monkeypatch):
    """Opt in only for data-contract tests; authorization tests use real guards."""
    import api

    monkeypatch.setitem(api.app.dependency_overrides, subject_server_auth_access._require_user,
                        lambda: SimpleNamespace(id=1, email="reader@example.test"))


@pytest.fixture(autouse=True)
def no_market_anchor_from_the_real_store(monkeypatch):
    """Periods end on the market's latest stored session; a test must not read the
    developer's catalogue for it. Tests about the anchor set their own."""
    import server.market.history as market_history

    async def no_anchor():
        return None

    monkeypatch.setattr(market_history, "_market_as_of", no_anchor)
