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
