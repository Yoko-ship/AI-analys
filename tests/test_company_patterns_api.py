"""/api/company/{ticker}/patterns — the gate and the contract.

The detectors are pinned in test_pattern_engine.py. What matters here is that
a thin security gets no patterns (with the reason), a liquid one gets them
each beside the market-wide outcome table, and that table is never missing.
The upstream fetch is stubbed.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("api")


def _history(flat: bool = False, days: int = 700) -> dict:
    """Waves of ±15 % every few weeks: enough swings for figures to form."""
    start = date.today() - timedelta(days=days)
    points, price = [], 100.0
    for i in range(days):
        day = start + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        price *= 1 + (0.012 if (i // 23) % 2 == 0 else -0.011)
        spread = 0 if flat else price * 0.01
        points.append({"date": day.isoformat(), "open": price - spread / 2, "high": price + spread,
                       "low": price - spread, "close": price, "trading_volume": 10.0,
                       "trading_value": price * 10.0})
    return {"points": points, "adjustments": []}


@pytest.fixture()
def client(monkeypatch):
    def make(flat: bool = False):
        async def fake_resolve(ticker: str):
            return "UZ0000000001" if ticker != "NOPE" else None

        async def fake_history(isin: str, months: int = 60):
            return _history(flat)

        monkeypatch.setattr(api, "_resolve_isin", fake_resolve)
        monkeypatch.setattr(api, "_full_history", fake_history)
        api._PATTERN_CACHE.clear()
        return TestClient(api.app)
    return make


def test_unknown_ticker_is_404(client):
    assert client().get("/api/company/NOPE/patterns").status_code == 404


def test_liquid_security_gets_patterns_with_market_statistics(client):
    body = client().get("/api/company/TEST/patterns").json()
    assert body["ok"] and body["status"] == "AVAILABLE" and body["tier"] == "full"
    assert body["signals"], "the waves must form at least one figure"
    first = body["signals"][0]
    assert {"type", "direction", "signal_date", "lines", "points", "outcome"} <= set(first)
    assert first["direction"] in ("bullish", "bearish")
    # Every type the engine can report has its UZSE record beside it.
    assert "all" in body["market_stats"]
    assert {"hit_rate_pct", "chance_pct", "decided"} <= set(body["market_stats"]["all"])
    assert body["disclaimer"]
    assert body["sensitivity"] == "medium"
    assert {"all", "chart", "candle"} <= set(body["backtest"])
    assert {"trades", "win_rate_pct", "max_drawdown_pct", "sharpe"} <= set(body["backtest"]["all"])
    assert body["cycle"]["status"] in ("AVAILABLE", "NO_DATA")
    assert all("box" in s for s in body["signals"])


def test_sensitivity_selects_its_own_outcome_table(client):
    app = client()
    low = app.get("/api/company/TEST/patterns?sensitivity=low").json()
    high = app.get("/api/company/TEST/patterns?sensitivity=high").json()
    assert low["sensitivity"] == "low" and high["sensitivity"] == "high"
    assert app.get("/api/company/TEST/patterns?sensitivity=nonsense").json()["sensitivity"] == "medium"


def test_thin_security_gets_no_patterns_and_says_why(client):
    body = client(flat=True).get("/api/company/TEST/patterns").json()
    assert body["status"] == "INSUFFICIENT_LIQUIDITY"
    assert body["tier"] != "full"
    assert body["signals"] == []
    assert body["reason"]
