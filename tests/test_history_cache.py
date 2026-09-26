"""The shared price-history cache must collapse concurrent upstream work."""
from __future__ import annotations

import server.market.history as subject_server_market_history

import asyncio
import importlib
import time

import openinfo_collector

api = importlib.import_module("api")


def test_concurrent_requests_for_the_same_archive_fetch_once(monkeypatch):
    calls = []
    payload = {"points": [{"date": "2026-09-01", "close": 100}], "adjustments": []}

    def fake_fetch(isin: str, session=None, months: int = 6):
        calls.append((isin, months))
        time.sleep(0.05)
        return payload

    monkeypatch.setattr(openinfo_collector, "fetch_price_history", fake_fetch)
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
