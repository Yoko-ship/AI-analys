"""The OpenInfo Excel parse cache is read from memory until the file changes.

The file is ~14 MB of JSON and every company report reads it; parsing it on
each read cost ~0.8 s per request.
"""
from __future__ import annotations

import json

import pytest

import openinfo_collector as oc
import collectors.openinfo.cache as collectors_openinfo_cache
import collectors.openinfo.settings as collectors_openinfo_settings


@pytest.fixture()
def cache_file(tmp_path, monkeypatch):
    path = tmp_path / "excel_cache.json"
    monkeypatch.setattr(collectors_openinfo_settings, "EXCEL_CACHE_PATH", path)
    monkeypatch.setattr(collectors_openinfo_cache, "_EXCEL_CACHE_MEMO", None)
    return path


def _count_parses(monkeypatch):
    calls = []
    real = json.loads

    def counting(text, *a, **kw):
        calls.append(1)
        return real(text, *a, **kw)

    monkeypatch.setattr(collectors_openinfo_cache.json, "loads", counting)
    return calls


def test_repeated_reads_parse_the_file_once(cache_file, monkeypatch):
    collectors_openinfo_cache._set_excel_cache("https://openinfo.uz/a.xlsx", {"sheets": [{"rows": [1, 2]}]})
    parses = _count_parses(monkeypatch)

    first = collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")
    second = collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")

    assert first == second == {"sheets": [{"rows": [1, 2]}], "from_cache": True}
    assert len(parses) == 1


def test_a_write_is_seen_by_the_next_read(cache_file):
    collectors_openinfo_cache._set_excel_cache("https://openinfo.uz/a.xlsx", {"v": 1})
    assert collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")["v"] == 1

    collectors_openinfo_cache._set_excel_cache("https://openinfo.uz/b.xlsx", {"v": 2})

    assert collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")["v"] == 1
    assert collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/b.xlsx")["v"] == 2


def test_a_caller_changing_its_payload_does_not_change_the_cache(cache_file):
    collectors_openinfo_cache._set_excel_cache("https://openinfo.uz/a.xlsx", {"sheets": [{"rows": [1, 2]}]})

    got = collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")
    got["sheets"][0]["rows"].append(99)

    again = collectors_openinfo_cache._get_excel_cache("https://openinfo.uz/a.xlsx")
    assert again["sheets"][0]["rows"] == [1, 2]
