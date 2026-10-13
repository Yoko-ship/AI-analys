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
