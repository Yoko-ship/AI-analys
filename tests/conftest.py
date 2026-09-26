"""Explicit test adapters for protected HTTP contract checks."""

import server.auth.access as subject_server_auth_access
from types import SimpleNamespace

import pytest


@pytest.fixture
def authenticated_reader(monkeypatch):
    """Opt in only for data-contract tests; authorization tests use real guards."""
    import api

    monkeypatch.setitem(api.app.dependency_overrides, subject_server_auth_access._require_user,
                        lambda: SimpleNamespace(id=1, email="reader@example.test"))
