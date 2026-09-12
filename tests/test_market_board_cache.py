"""The public market board should not rebuild its remote snapshot per visitor."""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

import api


def test_startup_warms_both_reader_boards(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    async def cached(kind: str, *, refresh: bool = False):
        calls.append((kind, refresh))
        return {"ok": True, "type": kind, "count": 1, "stocks": []}

    monkeypatch.setattr(api, "_cached_market_board", cached)
    asyncio.run(api._populate_securities_on_startup())

    assert calls == [("stock", True), ("bond", True)]


def test_recent_board_is_reused_and_manual_refresh_bypasses_it(monkeypatch) -> None:
    calls: list[str] = []

    async def build(kind: str):
        calls.append(kind)
        return {"ok": True, "type": kind, "count": len(calls), "stocks": []}

    monkeypatch.setattr(api, "_build_board", build)
    api._reset_market_board_cache()

    async def scenario():
        first = await api._cached_market_board("stock")
        second = await api._cached_market_board("stock")
        refreshed = await api._cached_market_board("stock", refresh=True)
        return first, second, refreshed

    first, second, refreshed = asyncio.run(scenario())

    assert first is second
    assert first["count"] == 1
    assert refreshed["count"] == 2
    assert calls == ["stock", "stock"]


def test_concurrent_cold_requests_share_one_board_build(monkeypatch) -> None:
    calls = 0

    async def build(kind: str):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"ok": True, "type": kind, "stocks": []}

    monkeypatch.setattr(api, "_build_board", build)
    api._reset_market_board_cache()

    async def scenario():
        return await asyncio.gather(*(
            api._cached_market_board("stock") for _ in range(4)
        ))

    results = asyncio.run(scenario())

    assert calls == 1
    assert all(result is results[0] for result in results)


def test_market_response_is_browser_cacheable_but_refresh_is_not(monkeypatch) -> None:
    async def cached(kind: str, *, refresh: bool = False):
        return {"ok": True, "type": kind, "refresh": refresh, "stocks": []}

    monkeypatch.setattr(api, "_cached_market_board", cached)

    async def call(refresh: bool):
        request = Request({
            "type": "http",
            "method": "GET",
            "path": "/api/market/stocks",
            "headers": [],
            "query_string": b"",
        })
        return await api.api_market_stocks(request, type="stock", refresh=refresh)

    normal = asyncio.run(call(False))
    forced = asyncio.run(call(True))

    assert normal.headers["cache-control"] == f"public, max-age={api.MARKET_BOARD_BROWSER_TTL_SEC}"
    assert forced.headers["cache-control"] == "public, max-age=0"
    assert json.loads(normal.body)["refresh"] is False
    assert json.loads(forced.body)["refresh"] is True
