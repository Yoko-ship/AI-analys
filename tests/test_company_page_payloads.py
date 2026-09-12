"""Company pages should request issuer-sized market payloads."""

from __future__ import annotations

import asyncio
import json

from starlette.requests import Request

import api


def _request(path: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": b"",
    })


def test_market_financials_can_return_one_share_family(monkeypatch) -> None:
    monkeypatch.setattr(api, "get_all_financials", lambda: {
        "ACME": {"year": 2026, "revenue": 2},
        "ACMEP": {"year": 2026, "revenue": 2},
        "OTHER": {"year": 2026, "revenue": 9},
    })
    monkeypatch.setattr(api, "refresh_financials_cache", lambda: None)

    body = asyncio.run(api.api_market_financials(ticker="ACME"))

    assert body["count"] == 2
    assert set(body["financials"]) == {"ACME", "ACMEP"}
    assert body["financials"]["ACME"]["revenue"] == 2000


def test_market_multiples_passes_ticker_scope_and_returns_only_requested_row(monkeypatch) -> None:
    seen: list[str | None] = []

    async def inputs(ticker=None):
        seen.append(ticker)
        return {
            "trade_date": "2026-09-11",
            "board": [],
            "financials": {},
            "ratios": {},
        }

    monkeypatch.setattr(api, "_market_inputs", inputs)
    monkeypatch.setattr(api.public_contract, "market_inputs_version", lambda value: "v1")
    monkeypatch.setattr(api.cache_layer, "cached", lambda key, build: build())
    monkeypatch.setattr(api, "_multiples_payload", lambda value: {
        "ok": True,
        "count": 2,
        "issuers": 1,
        "contract_version": "test",
        "input_snapshot": "v1",
        "items": [
            {"ticker": "ACME", "issuer": "acme", "pe": {"value": 5}},
            {"ticker": "ACMEP", "issuer": "acme", "pe": {"value": 5}},
        ],
        "by_issuer": {"acme": {"tickers": ["ACME", "ACMEP"]}},
    })

    response = asyncio.run(api.api_market_multiples(
        _request("/api/market/multiples"), ticker="acme"
    ))
    body = json.loads(response.body)

    assert seen == ["ACME"]
    assert body["count"] == 1
    assert body["issuers"] == 1
    assert [row["ticker"] for row in body["items"]] == ["ACME"]
    assert set(body["by_issuer"]) == {"acme"}
