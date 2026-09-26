"""Company pages should request issuer-sized market payloads."""

from __future__ import annotations

import cache_layer as subject_cache_layer
import public_contract as subject_public_contract
import reports_catalog as subject_reports_catalog
import server.market.routes as subject_server_market_routes
import server.market.valuations as subject_server_market_valuations

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
    monkeypatch.setattr(subject_reports_catalog, 'get_all_financials', lambda: {
        "ACME": {"year": 2026, "revenue": 2},
        "ACMEP": {"year": 2026, "revenue": 2},
        "OTHER": {"year": 2026, "revenue": 9},
    })
    monkeypatch.setattr(subject_reports_catalog, 'refresh_financials_cache', lambda: None)

    body = asyncio.run(subject_server_market_routes.api_market_financials(ticker="ACME"))

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

    monkeypatch.setattr(subject_server_market_valuations, '_market_inputs', inputs)
    monkeypatch.setattr(subject_public_contract, "market_inputs_version", lambda value: "v1")
    monkeypatch.setattr(subject_cache_layer, "cached", lambda key, build: build())
    monkeypatch.setattr(subject_server_market_valuations, '_multiples_payload', lambda value: {
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

    response = asyncio.run(subject_server_market_routes.api_market_multiples(
        _request("/api/market/multiples"), ticker="acme"
    ))
    body = json.loads(response.body)

    assert seen == ["ACME"]
    assert body["count"] == 1
    assert body["issuers"] == 1
    assert [row["ticker"] for row in body["items"]] == ["ACME"]
    assert set(body["by_issuer"]) == {"acme"}
