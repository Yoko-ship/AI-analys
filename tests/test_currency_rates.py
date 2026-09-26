"""/api/currency/rates — the CBU proxy's contract.

The bank's own JSON is stubbed: this is about what the site serves, not about
cbu.uz being up. Three things matter: the curated order (the strip renders the
list as-is), numbers arriving as numbers (CBU ships them as strings), and a
failed refresh serving the last good answer instead of a 502 — yesterday's
official rate stays official until the bank publishes the next one.
"""
from __future__ import annotations

import server.currency.routes as subject_server_currency_routes

import importlib

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("api")

CBU_FEED = [
    {"id": 68, "Code": "840", "Ccy": "USD", "CcyNm_RU": "Доллар США",
     "CcyNm_UZ": "AQSH dollari", "CcyNm_EN": "US Dollar",
     "Nominal": "1", "Rate": "11934.61", "Diff": "-17.49", "Date": "11.08.2026"},
    {"id": 20, "Code": "978", "Ccy": "EUR", "CcyNm_RU": "Евро",
     "CcyNm_UZ": "EVRO", "CcyNm_EN": "Euro",
     "Nominal": "1", "Rate": "13788.05", "Diff": "8.47", "Date": "11.08.2026"},
    # A currency outside the curated list must not leak into the answer.
    {"id": 5, "Code": "051", "Ccy": "AMD", "CcyNm_RU": "Драм",
     "CcyNm_UZ": "Dram", "CcyNm_EN": "Dram",
     "Nominal": "10", "Rate": "31.05", "Diff": "0", "Date": "11.08.2026"},
]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(subject_server_currency_routes, '_fetch_cbu_rates', lambda: list(CBU_FEED))
    monkeypatch.setitem(subject_server_currency_routes._cbu_rates_cache, "payload", None)
    monkeypatch.setitem(subject_server_currency_routes._cbu_rates_cache, "at", 0.0)
    return TestClient(api.app)


def test_serves_curated_currencies_in_order_with_numbers(client):
    data = client.get("/api/currency/rates").json()
    assert data["ok"] is True
    assert data["date"] == "11.08.2026"
    ccys = [r["ccy"] for r in data["rates"]]
    assert ccys == [c for c in subject_server_currency_routes.CBU_RATES_CURRENCIES if c in {"USD", "EUR"}]
    usd = data["rates"][0]
    assert usd["rate"] == pytest.approx(11934.61)
    assert usd["diff"] == pytest.approx(-17.49)
    assert usd["nominal"] == 1


def test_failed_refresh_serves_last_good_answer(client, monkeypatch):
    first = client.get("/api/currency/rates").json()
    assert first["ok"] is True

    def boom():
        raise RuntimeError("cbu unreachable")

    monkeypatch.setattr(subject_server_currency_routes, '_fetch_cbu_rates', boom)
    monkeypatch.setitem(subject_server_currency_routes._cbu_rates_cache, "at", 0.0)  # force a refresh
    again = client.get("/api/currency/rates")
    assert again.status_code == 200
    assert again.json()["rates"] == first["rates"]


def test_nothing_cached_and_bank_down_is_honest(client, monkeypatch):
    def boom():
        raise RuntimeError("cbu unreachable")

    monkeypatch.setattr(subject_server_currency_routes, '_fetch_cbu_rates', boom)
    resp = client.get("/api/currency/rates")
    assert resp.status_code == 200
    assert resp.json() == {"ok": False, "rates": []}
