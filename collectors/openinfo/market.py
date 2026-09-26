"""Openinfo market operations with explicit dependencies."""
from __future__ import annotations
from typing import Any
import requests

from corporate_actions import adjust_history
from datetime import date
from datetime import timedelta
from urllib.parse import urlencode
import collectors.openinfo.cells as collectors_openinfo_cells
import collectors.openinfo.issuers as collectors_openinfo_issuers
import collectors.openinfo.settings as collectors_openinfo_settings
import collectors.openinfo.transport as collectors_openinfo_transport


def fetch_stock_screener(
    query: str,
    session: requests.Session | None = None,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    client = session or collectors_openinfo_transport._make_session()
    payload = collectors_openinfo_transport._json_get(
        client,
        "/iuzse/stock-screener/",
        {"mkt_id": "STK", "page_size": page_size, "search": query},
    )
    return list(payload.get("results") or []) if isinstance(payload, dict) else []


def _pick_security(
    query: str,
    securities: list[dict[str, Any]],
    company_name: str | None = None,
) -> dict[str, Any] | None:
    if not securities:
        return None

    query_key = collectors_openinfo_issuers._normalize_key(query)
    company_key = collectors_openinfo_issuers._normalize_key(company_name)
    for security in securities:
        ticker_key = collectors_openinfo_issuers._normalize_key(security.get("ticker"))
        isin_key = collectors_openinfo_issuers._normalize_key(security.get("isin_code"))
        if query_key and query_key in {ticker_key, isin_key}:
            return security

    if company_key:
        for security in securities:
            issuer_key = collectors_openinfo_issuers._normalize_key(security.get("issuer_short_name"))
            if company_key and (company_key in issuer_key or issuer_key in company_key):
                return security

    return securities[0]


def fetch_price_history(
    isin_code: str,
    session: requests.Session | None = None,
    months: int = 6,
) -> dict[str, Any]:
    client = session or collectors_openinfo_transport._make_session()
    end_date = date.today()
    start_date = end_date - timedelta(days=max(1, months) * 30)
    params = {
        "isu_cd": isin_code,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }
    payload = collectors_openinfo_transport._json_get(client, "/iuzse/conclusions/", params)
    ticker = payload.get("ticker")
    # The feed never restates a price after a split or a bonus issue, so a series that
    # spans one is quoted in two different units. Put the older half on today's share
    # before anything reads it — the chart, the period change below, the analyst prompt.
    points, adjustments = adjust_history(payload.get("results") or [], ticker, isin_code)
    return {
        "source_url": f"{collectors_openinfo_settings.OPENINFO_API_BASE}/iuzse/conclusions/?{urlencode(params)}",
        "name": payload.get("name"),
        "ticker": ticker,
        "points": points,
        "adjustments": adjustments,
    }


def _market_summary(
    security: dict[str, Any] | None,
    history_points: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(
        history_points,
        key=lambda item: str(item.get("date") or ""),
    )
    closes = [collectors_openinfo_cells._safe_float(point.get("close")) for point in ordered]
    closes = [value for value in closes if value is not None and value > 0]
    trading_values = [collectors_openinfo_cells._safe_float(point.get("trading_value")) for point in ordered]
    trading_values = [value for value in trading_values if value is not None]
    trading_volumes = [collectors_openinfo_cells._safe_float(point.get("trading_volume")) for point in ordered]
    trading_volumes = [value for value in trading_volumes if value is not None]

    period_change_percent = None
    if len(closes) >= 2 and closes[0]:
        period_change_percent = round((closes[-1] - closes[0]) / closes[0] * 100, 2)

    return {
        "latest_price": collectors_openinfo_cells._safe_float((security or {}).get("trade_price")) or (closes[-1] if closes else None),
        "latest_trade_datetime": (security or {}).get("trade_datetime"),
        "day_change": collectors_openinfo_cells._safe_float((security or {}).get("change")),
        "day_change_percent": collectors_openinfo_cells._safe_float((security or {}).get("change_percent")),
        "history_points": len(history_points),
        "history_start": ordered[0].get("date") if ordered else None,
        "history_end": ordered[-1].get("date") if ordered else None,
        "period_change_percent": period_change_percent,
        "total_trading_value": round(sum(trading_values), 2) if trading_values else None,
        "avg_daily_trading_value": round(sum(trading_values) / len(trading_values), 2) if trading_values else None,
        "total_trading_volume": round(sum(trading_volumes), 2) if trading_volumes else None,
    }


def fetch_dividends(
    query: str,
    session: requests.Session | None = None,
    page_size: int = 20,
) -> dict[str, Any]:
    client = session or collectors_openinfo_transport._make_session()
    params = {
        "stock_type": "simple",
        "page": 1,
        "page_size": page_size,
        "search": query,
        "ordering": "",
    }
    payload = collectors_openinfo_transport._json_get(client, "/disclosure/dividend-calendar/", params)
    return {
        "source_url": f"{collectors_openinfo_settings.OPENINFO_API_BASE}/disclosure/dividend-calendar/?{urlencode(params)}",
        "count": payload.get("count", 0) if isinstance(payload, dict) else 0,
        "items": payload.get("results", []) if isinstance(payload, dict) else [],
    }
