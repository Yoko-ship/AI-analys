"""Fact collection must not depend on the optional live securities feed.

The feed behind entity_resolver.fetch_uzse_securities was retired; the nightly
collector then failed its facts step every run, although the synced catalog
already lists every issuer it needs.
"""
from __future__ import annotations

import pytest
import requests

import data_sources as ds


class _Conn:
    def __init__(self, org_ids):
        self._rows = [{"org_id": org} for org in org_ids]

    def execute(self, *a, **kw):
        return self

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Recorder:
    def __init__(self):
        self.orgs = None

    def collect(self, orgs, session):
        self.orgs = list(orgs)
        return []


@pytest.fixture()
def recorder(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(ds, "registry", lambda: {"probe": rec})
    monkeypatch.setattr(ds.rc, "purge_premature_annual_facts", lambda: None)
    monkeypatch.setattr(ds.rc, "upsert_facts", lambda facts: 0)
    return rec


def _feed_unavailable(session=None):
    raise requests.ConnectionError("UZSE stock mirror is not configured")


def test_unavailable_feed_collects_the_catalog_issuers(monkeypatch, recorder):
    monkeypatch.setattr(ds, "resolve_all", _feed_unavailable)
    monkeypatch.setattr(ds.rc, "get_catalog_conn", lambda: _Conn(["29", "27"]))

    result = ds.run_all(session=object())

    assert recorder.orgs == ["27", "29"]
    assert result["orgs"] == 2


def test_no_issuers_at_all_is_an_error_not_an_empty_success(monkeypatch, recorder):
    monkeypatch.setattr(ds, "resolve_all", _feed_unavailable)
    monkeypatch.setattr(ds.rc, "get_catalog_conn", lambda: _Conn([]))

    with pytest.raises(RuntimeError, match="no issuers"):
        ds.run_all(session=object())
    assert recorder.orgs is None
