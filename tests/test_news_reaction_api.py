"""/api/news/item/{id}/reaction — the contract the story page reads.

The arithmetic is pinned in test_formulas.py::TestPriceReaction. What matters here
is that the endpoint finds the story's issuers, survives an issuer it cannot price,
and never turns "has not traded since" into a number.

The upstream fetch is stubbed: a test that needs openinfo to be up is not a test.
"""
from __future__ import annotations

import news_store as subject_news_store
import server.market.history as subject_server_market_history

import importlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

api = importlib.import_module("api")

PUBLISHED = (date.today() - timedelta(days=10)).isoformat() + " 09:00:00"


def _series(days: int = 40, *, stop_before_story: bool = False) -> dict:
    """A close per calendar day ending today, or ending before the story."""
    last = date.today() - timedelta(days=20 if stop_before_story else 0)
    start = last - timedelta(days=days)
    points, price = [], 100.0
    day = start
    while day <= last:
        price *= 1.01
        points.append({"date": day.isoformat(), "open": price, "high": price * 1.01,
                       "low": price * 0.99, "close": price,
                       "trading_volume": 10.0, "trading_value": price * 10.0})
        day += timedelta(days=1)
    return {"points": points, "adjustments": []}


@pytest.fixture()
def client(monkeypatch):
    item = {"id": 7, "title": "Дивиденды", "published_at": PUBLISHED,
            "tickers": ["AGBA", "KVTS"], "url": "https://example.test/a"}
    monkeypatch.setattr(subject_news_store, "get_news_item",
                        lambda news_id: dict(item) if int(news_id) == 7 else None)

    async def fake_resolve(ticker: str):
        return None if ticker == "KVTS" else f"UZ000{ticker}"

    async def fake_history(isin: str, months: int = 60):
        return _series()

    monkeypatch.setattr(subject_server_market_history, '_resolve_isin', fake_resolve)
    monkeypatch.setattr(subject_server_market_history, '_full_history', fake_history)
    return TestClient(api.app)


def test_it_prices_every_issuer_the_story_names(client):
    body = client.get("/api/news/item/7/reaction").json()
    assert body["ok"] is True and body["published_at"] == PUBLISHED
    assert [r["ticker"] for r in body["items"]] == ["AGBA", "KVTS"]
    hit = body["items"][0]
    assert hit["status"] == "ok"
    assert hit["before"]["date"] < hit["after"]["date"]
    assert hit["change"]["value"] > 0
    assert hit["volume_vs_normal"]["value"] == pytest.approx(1.0, abs=0.01)


def test_an_issuer_we_cannot_price_does_not_break_the_block(client):
    """One unresolvable ISIN must not cost the reader the other issuer's numbers."""
    body = client.get("/api/news/item/7/reaction").json()
    assert body["items"][1] == {"ticker": "KVTS", "status": "no_isin"}


def test_an_unreachable_series_is_reported_not_raised(client, monkeypatch):
    async def boom(isin: str, months: int = 60):
        raise RuntimeError("openinfo down")

    monkeypatch.setattr(subject_server_market_history, '_full_history', boom)
    body = client.get("/api/news/item/7/reaction").json()
    assert body["ok"] is True
    assert {r["status"] for r in body["items"]} == {"unavailable", "no_isin"}


def test_no_session_since_the_story_is_not_a_zero(client, monkeypatch):
    async def stale(isin: str, months: int = 60):
        return _series(stop_before_story=True)

    monkeypatch.setattr(subject_server_market_history, '_full_history', stale)
    reaction = client.get("/api/news/item/7/reaction").json()["items"][0]
    assert reaction["status"] == "no_session_yet"
    assert reaction["change"]["value"] is None


def test_an_unknown_story_is_a_404(client):
    assert client.get("/api/news/item/999/reaction").status_code == 404
