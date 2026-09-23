"""The OpenInfo Excel parse cache is read from memory until the file changes.

The file is ~14 MB of JSON and every company report reads it; parsing it on
each read cost ~0.8 s per request.
"""
from __future__ import annotations

import json

import pytest

import openinfo_collector as oc


@pytest.fixture()
def cache_file(tmp_path, monkeypatch):
    path = tmp_path / "excel_cache.json"
    monkeypatch.setattr(oc, "EXCEL_CACHE_PATH", path)
    monkeypatch.setattr(oc, "_EXCEL_CACHE_MEMO", None)
    return path


def _count_parses(monkeypatch):
    calls = []
    real = json.loads

    def counting(text, *a, **kw):
        calls.append(1)
        return real(text, *a, **kw)

    monkeypatch.setattr(oc.json, "loads", counting)
    return calls


def test_repeated_reads_parse_the_file_once(cache_file, monkeypatch):
    oc._set_excel_cache("https://openinfo.uz/a.xlsx", {"sheets": [{"rows": [1, 2]}]})
    parses = _count_parses(monkeypatch)

    first = oc._get_excel_cache("https://openinfo.uz/a.xlsx")
    second = oc._get_excel_cache("https://openinfo.uz/a.xlsx")

    assert first == second == {"sheets": [{"rows": [1, 2]}], "from_cache": True}
    assert len(parses) == 1


def test_a_write_is_seen_by_the_next_read(cache_file):
    oc._set_excel_cache("https://openinfo.uz/a.xlsx", {"v": 1})
    assert oc._get_excel_cache("https://openinfo.uz/a.xlsx")["v"] == 1

    oc._set_excel_cache("https://openinfo.uz/b.xlsx", {"v": 2})

    assert oc._get_excel_cache("https://openinfo.uz/a.xlsx")["v"] == 1
    assert oc._get_excel_cache("https://openinfo.uz/b.xlsx")["v"] == 2


def test_a_caller_changing_its_payload_does_not_change_the_cache(cache_file):
    oc._set_excel_cache("https://openinfo.uz/a.xlsx", {"sheets": [{"rows": [1, 2]}]})

    got = oc._get_excel_cache("https://openinfo.uz/a.xlsx")
    got["sheets"][0]["rows"].append(99)

    again = oc._get_excel_cache("https://openinfo.uz/a.xlsx")
    assert again["sheets"][0]["rows"] == [1, 2]
