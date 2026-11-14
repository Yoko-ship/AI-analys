"""The shared price-history cache must collapse concurrent upstream work."""
from __future__ import annotations

import server.market.history as subject_server_market_history

import asyncio
import importlib
import time

import openinfo_collector
import collectors.openinfo.market as collectors_openinfo_market

api = importlib.import_module("api")


def test_concurrent_requests_for_the_same_archive_fetch_once(monkeypatch):
    calls = []
    payload = {"points": [{"date": "2026-09-01", "close": 100}], "adjustments": []}

    def fake_fetch(isin: str, session=None, months: int = 6):
        calls.append((isin, months))
        time.sleep(0.05)
        return payload

    monkeypatch.setattr(collectors_openinfo_market, "fetch_price_history", fake_fetch)
    subject_server_market_history._HISTORY_CACHE.clear()
    subject_server_market_history._HISTORY_LOCKS.clear()

    async def scenario():
        return await asyncio.gather(
            subject_server_market_history._full_history("UZ0000000001", months=240),
            subject_server_market_history._full_history("UZ0000000001", months=240),
        )

    first, second = asyncio.run(scenario())

    assert calls == [("UZ0000000001", 240)]
    assert first is payload
    assert second is payload


def test_the_chart_archive_reaches_back_whole_calendar_months(monkeypatch):
    """«1Г» on the chart asked openinfo for 360 days; a year is the same date a year ago."""
    from datetime import date

    import formulas

    asked = {}

    def fake_get(client, path, params):
        asked.update(params)
        return {"results": [], "ticker": "KFSKP"}

    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport,
                        "_json_get", fake_get)
    collectors_openinfo_market.fetch_price_history("UZ7011340008", session=object(), months=12)

    assert asked["start_date"] == formulas.months_before(date.today(), 12).isoformat()


def test_the_card_history_carries_the_session_openinfo_has_not_published(monkeypatch):
    """Audit of 12.10.2026 («Период без последней сессии», 64 cards): openinfo's archive
    publishes a session a day late, so on 12.10 KFSKP's card measured «1Г» through 09.10
    beside a header price from 12.10 — and called that price outside the year's range.
    The exchange's own stored sessions newer than the archive complete the series."""
    import catalogue.market_store as catalogue_market_store

    archive = {"points": [{"date": "2026-10-08", "close": 4500.0, "trading_volume": 10.0,
                           "trading_value": 45000.0},
                          {"date": "2026-10-09", "close": 4713.61, "trading_volume": 20.0,
                           "trading_value": 94272.2}],
               "adjustments": []}
    stored = {"UZ7011340008": [
        {"trade_date": "20261009", "close_price": 4713.61, "quantity": 20.0, "turnover": 94272.2},
        # The exchange carries a close forward at zero turnover; that is not a session.
        {"trade_date": "20261010", "close_price": 4713.61, "quantity": 0.0, "turnover": 0.0},
        {"trade_date": "20261012", "close_price": 5656.33, "quantity": 1717.0,
         "turnover": 9683773.54, "open_price": 4900.0, "high_price": 5656.33,
         "low_price": 4900.0, "trade_count": 41},
    ]}
    monkeypatch.setattr(collectors_openinfo_market, "fetch_price_history",
                        lambda isin, session=None, months=6: archive)
    monkeypatch.setattr(catalogue_market_store, "get_quote_history",
                        lambda isins, days=30: stored)
    subject_server_market_history._HISTORY_CACHE.clear()
    subject_server_market_history._HISTORY_LOCKS.clear()

    got = asyncio.run(subject_server_market_history._full_history("UZ7011340008", months=240))

    assert [p["date"] for p in got["points"]] == ["2026-10-08", "2026-10-09", "2026-10-12"]
    last = got["points"][-1]
    assert (last["close"], last["trading_volume"], last["trading_value"]) == (
        5656.33, 1717.0, 9683773.54)
    assert archive["points"][-1]["date"] == "2026-10-09", "the archive itself is not rewritten"


def test_returns_endpoint_preserves_share_class_units_adjustments_and_market_anchor(monkeypatch):
    """Exercise the real resolver, collector, adjustment and response mapping.

    ALSM's real pre-recapitalisation 1,495 UZS becomes 1,495 / 3 UZS
    per current share. The preferred-class sample deliberately uses different
    prices so an issuer-level lookup or cache collision cannot pass this test.
    """
    from datetime import date
    import pytest
    import server.company.history_routes as routes
    import securities_catalog
    import catalogue.market_store as store

    instruments = {"ALSM": "UZ7045320007", "ALSMP": "UZ704532K019"}
    requests = []
    monkeypatch.setattr(securities_catalog, "get_securities_map",
                        lambda: {t: {"isin": i} for t, i in instruments.items()})
    monkeypatch.setattr(store, "get_quote_history", lambda isins, days=30: {})

    def feed(client, path, params):
        assert path == "/iuzse/conclusions/"
        requests.append(params["isu_cd"])
        ticker = next(t for t, i in instruments.items() if i == params["isu_cd"])
        before, after = (1495.0, 897.0) if ticker == "ALSM" else (3000.0, 1100.0)
        return {"ticker": ticker, "results": [
            {"date": "2025-04-03", "close": before, "trading_volume": 10, "trading_value": before * 10},
            {"date": "2025-10-07", "close": after, "trading_volume": 20, "trading_value": after * 20},
        ]}

    async def anchor():
        return date(2026, 11, 13)  # Market session, not this instrument's last trade.

    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport, "_json_get", feed)
    monkeypatch.setattr(subject_server_market_history, "_market_as_of", anchor)
    subject_server_market_history._HISTORY_CACHE.clear()
    subject_server_market_history._HISTORY_LOCKS.clear()
    for ticker, isin in instruments.items():
        got = asyncio.run(routes.api_price_history(ticker.lower(), months=240))
        before, after = (1495.0, 897.0) if ticker == "ALSM" else (3000.0, 1100.0)
        assert got["ok"] and got["ticker"] == ticker and got["isin"] == isin
        assert got["as_of"] == "2026-11-13"
        assert got["points"][0]["close"] == pytest.approx(before / 3)
        assert got["points"][1]["close"] == after
        assert got["points"][0]["value"] == before * 10  # UZS turnover never rescales.
        assert got["points"][0]["volume"] == 10
        assert {a["kind"] for a in got["adjustments"]} == {"split", "bonus"}
    assert requests == list(instruments.values())

    async def missing_anchor():
        return None

    monkeypatch.setattr(subject_server_market_history, "_market_as_of", missing_anchor)
    assert asyncio.run(routes.api_price_history("ALSM", months=240))["as_of"] is None


def test_returns_endpoint_retains_a_dated_unknown_close(monkeypatch):
    import server.company.history_routes as routes
    from datetime import date

    async def resolve(ticker):
        return "UZ7011340005"

    async def history(isin, months):
        return {"points": [{"date": "2026-01-30", "close": 57.8},
                           {"date": "2026-01-31", "close": None}], "adjustments": []}

    async def anchor():
        return date(2026, 2, 27)

    monkeypatch.setattr(subject_server_market_history, "_resolve_isin", resolve)
    monkeypatch.setattr(subject_server_market_history, "_full_history", history)
    monkeypatch.setattr(subject_server_market_history, "_market_as_of", anchor)
    legacy = asyncio.run(routes.api_price_history("HMKB", months=240))
    assert [(p["date"], p["close"]) for p in legacy["points"]] == [("2026-01-30", 57.8)]
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert [(p["date"], p["close"]) for p in got["points"]] == [
        ("2026-01-30", 57.8), ("2026-01-31", None)]


def test_returns_unknown_traded_prices_survive_the_real_archive_and_store_merger(monkeypatch):
    from datetime import date
    import server.company.history_routes as routes
    import securities_catalog
    import catalogue.market_store as store

    isin = "UZ7011340005"
    monkeypatch.setattr(securities_catalog, "get_securities_map", lambda: {"HMKB": {"isin": isin}})
    monkeypatch.setattr(store, "get_quote_history", lambda isins, days=30: {isin: [
        {"trade_date": "20260130", "close_price": 57.8, "quantity": 10, "turnover": 578},
        {"trade_date": "20260131", "close_price": None, "quantity": 5, "turnover": 290},
    ]})

    def feed(client, path, params):
        assert params["isu_cd"] == isin
        return {"ticker": "HMKB", "results": [
            {"date": "2025-12-31", "close": 40, "trading_volume": 0, "trading_value": 0},
            {"date": "2026-01-29", "close": 55, "trading_volume": 0, "trading_value": 0},
            {"date": "2026-02-27", "close": None, "trading_volume": 5, "trading_value": 300},
            {"date": "2026-02-28", "close": None, "trading_volume": 0, "trading_value": 0},
        ]}

    async def anchor():
        return date(2026, 2, 27)

    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport, "_json_get", feed)
    monkeypatch.setattr(subject_server_market_history, "_market_as_of", anchor)
    subject_server_market_history._HISTORY_CACHE.clear()
    subject_server_market_history._HISTORY_LOCKS.clear()
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert sorted((p["date"], p["close"]) for p in got["points"]) == [
        ("2026-01-30", 57.8), ("2026-01-31", None), ("2026-02-27", None)]
    legacy = asyncio.run(routes.api_price_history("HMKB", months=240))
    assert [(p["date"], p["close"]) for p in legacy["points"]] == [
        ("2025-12-31", 40), ("2026-01-29", 55), ("2026-01-30", 57.8)]

    # The archive may know an actual trade missing between two stored dates.
    # An unknown price in that gap must not disappear with source precedence.
    monkeypatch.setattr(store, "get_quote_history", lambda isins, days=30: {isin: [
        {"trade_date": "20260130", "close_price": 57.8, "quantity": 10, "turnover": 578},
        {"trade_date": "20260302", "close_price": 60, "quantity": 10, "turnover": 600},
    ]})
    subject_server_market_history._HISTORY_CACHE.clear()
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert ("2026-02-27", None) in [(p["date"], p["close"]) for p in got["points"]]

    # A stored carry-forward is not evidence that the archive's trade did not
    # happen. A conflicting no-trade row must preserve the same uncertainty.
    monkeypatch.setattr(store, "get_quote_history", lambda isins, days=30: {isin: [
        {"trade_date": "20260130", "close_price": 57.8, "quantity": 10, "turnover": 578},
        {"trade_date": "20260227", "close_price": 57.8, "quantity": 0, "turnover": 0},
        {"trade_date": "20260302", "close_price": 60, "quantity": 10, "turnover": 600},
    ]})
    subject_server_market_history._HISTORY_CACHE.clear()
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert ("2026-02-27", None) in [(p["date"], p["close"]) for p in got["points"]]

    # Store-only fallback remains useful to legacy charts, but cannot establish
    # complete return endpoints when the archive is unavailable. Recovery must
    # retry the source rather than cache a partial series as a successful one.
    def unavailable(*args, **kwargs):
        raise RuntimeError("archive unavailable")

    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport, "_json_get", unavailable)
    subject_server_market_history._HISTORY_CACHE.clear()
    legacy = asyncio.run(routes.api_price_history("HMKB", months=240))
    assert legacy["ok"] and legacy["points"]
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert got["ok"] is False and got["points"] == []
    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport, "_json_get", feed)
    recovered = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert recovered["ok"] is True

    def lagging_archive(client, path, params):
        return {"ticker": "HMKB", "results": [
            {"date": "2026-01-30", "close": 57.8, "trading_volume": 10, "trading_value": 578},
            {"date": "2026-02-26", "close": 58, "trading_volume": 10, "trading_value": 580},
        ]}

    monkeypatch.setattr(collectors_openinfo_market.collectors_openinfo_transport, "_json_get", lagging_archive)
    monkeypatch.setattr(store, "get_quote_history", unavailable)
    subject_server_market_history._HISTORY_CACHE.clear()
    legacy = asyncio.run(routes.api_price_history("HMKB", months=240))
    assert legacy["ok"] and legacy["points"][-1]["date"] == "2026-02-26"
    got = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert got["ok"] is False and got["points"] == []
    monkeypatch.setattr(store, "get_quote_history", lambda isins, days=30: {isin: [
        {"trade_date": "20260130", "close_price": 57.8, "quantity": 10, "turnover": 578},
        {"trade_date": "20260227", "close_price": 60, "quantity": 10, "turnover": 600},
    ]})
    recovered = asyncio.run(routes.api_price_history("HMKB", months=240, include_unknown=True))
    assert recovered["ok"] and recovered["points"][-1]["date"] == "2026-02-27"
    assert recovered["points"][-1]["close"] == 60
