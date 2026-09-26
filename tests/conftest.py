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


@pytest.fixture
def authenticated_reader(monkeypatch):
    """Opt in only for data-contract tests; authorization tests use real guards."""
    import api

    monkeypatch.setitem(api.app.dependency_overrides, subject_server_auth_access._require_user,
                        lambda: SimpleNamespace(id=1, email="reader@example.test"))
