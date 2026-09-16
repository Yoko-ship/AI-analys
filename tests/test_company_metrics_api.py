"""/api/company/{ticker}/metrics — the contract, not the arithmetic.

The formulas themselves are pinned in test_formulas.py. What matters here is
the shape the screen depends on (ТЗ v1.2 §10.4.2): a `window` block that
follows the period, an `absolute` block that does not, a `quality` block, and
a status on every metric — never a bare number.

The upstream fetch is stubbed: this test is about the endpoint, and a test
that needs openinfo to be up is not a test.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("api")


def _history(days: int = 420) -> dict:
    """A daily series with a real turnover per point, ending today."""
    start = date.today() - timedelta(days=days)
    points = []
    price = 100.0
    for i in range(days):
        day = start + timedelta(days=i)
        if day.weekday() >= 5:
            continue
        price *= 1.001
        points.append({
            "date": day.isoformat(),
            "open": price * 0.99, "high": price * 1.02,
            "low": price * 0.97, "close": price,
            "trading_volume": 10.0,
            # Turnover deliberately != close*volume, so a VWAP computed the old
            # way would be a different number and the test would catch it.
            "trading_value": price * 10.0 * 0.9,
        })
    return {"points": points, "adjustments": []}


@pytest.fixture()
def client(monkeypatch):
    requested_months = []

    async def fake_resolve(ticker: str):
        return "UZ0000000001"

    async def fake_history(isin: str, months: int = 60):
        requested_months.append(months)
        return _history()

    monkeypatch.setattr(api, "_resolve_isin", fake_resolve)
    monkeypatch.setattr(api, "_full_history", fake_history)
    app_client = TestClient(api.app)
    app_client.requested_history_months = requested_months
    return app_client


def test_returns_the_three_blocks(client):
    body = client.get("/api/company/UZHM/metrics").json()
    assert body["ok"] is True
    assert set(("window", "absolute", "quality", "ma_windows")) <= set(body)
    assert body["as_of"]
    assert client.requested_history_months == [240]


def test_every_metric_carries_a_status(client):
    body = client.get("/api/company/UZHM/metrics").json()
    for name, metric in body["absolute"].items():
        assert "status" in metric, name
        assert "value" in metric, name
    for name in ("vwap", "min_close", "max_close", "mean_close"):
        assert "status" in body["window"][name], name


def test_absolute_block_is_identical_under_every_period(client):
    """The invariant the endpoint exists to hold (ТЗ §3)."""
    first = None
    for months in (1, 3, 6, 12, 36, 60):
        body = client.get("/api/company/UZHM/metrics", params={"months": months}).json()
        if first is None:
            first = body["absolute"]
        assert body["absolute"] == first, f"absolute block moved at months={months}"
        assert body["quality"] == client.get(
            "/api/company/UZHM/metrics", params={"months": 12}).json()["quality"]


def test_window_block_does_follow_the_period(client):
    short = client.get("/api/company/UZHM/metrics", params={"months": 1}).json()["window"]
    long = client.get("/api/company/UZHM/metrics", params={"months": 12}).json()["window"]
    assert short["points"] < long["points"]
    assert short["code"] == "1m" and long["code"] == "1y"


def test_vwap_is_turnover_over_volume(client):
    body = client.get("/api/company/UZHM/metrics", params={"months": 12}).json()
    vwap = body["window"]["vwap"]
    mean_close = body["window"]["mean_close"]["value"]
    assert vwap["status"] == "ok"
    assert vwap["method"] == "turnover/volume"
    # The fixture prices every trade at 90 % of the close, so a VWAP that had
    # been derived from closes would land ~11 % higher.
    assert vwap["value"] == pytest.approx(mean_close * 0.9, rel=0.02)


def test_volatility_is_annualised_over_a_calendar_window(client):
    vol = client.get("/api/company/UZHM/metrics").json()["absolute"]["volatility"]
    assert vol["window_days"] == 30
    if vol["value"] is not None:
        assert vol["annualized"] is True


def test_unknown_ticker_is_reported_not_guessed(client, monkeypatch):
    async def no_isin(ticker: str):
        return None

    monkeypatch.setattr(api, "_resolve_isin", no_isin)
    body = client.get("/api/company/NOPE/metrics").json()
    assert body["ok"] is False
    assert body["error"] == "ISIN not found"


def test_months_is_clamped(client):
    assert client.get("/api/company/UZHM/metrics",
                      params={"months": 999}).json()["window"]["code"] == "5y"
    assert client.get("/api/company/UZHM/metrics",
                      params={"months": 0}).json()["window"]["code"] == "1m"
