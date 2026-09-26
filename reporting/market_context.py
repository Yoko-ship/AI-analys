"""Prepare reported market prices and technical context for analysis."""

from __future__ import annotations
from reporting.numbers import _safe_float
from reporting.settings import (
    ABSOLUTE_EXCEL_REPORT_LIMIT,
    EXCEL_PROMPT_MAX_REPORTS,
    EXCEL_PROMPT_MAX_ROWS_PER_SHEET,
    EXCEL_PROMPT_MAX_SHEETS_PER_REPORT,
    REPORT_DOCUMENTS_PROMPT_LIMIT,
)


def _build_fibonacci_levels(points: list[dict]) -> dict:
    cleaned = []
    for point in points or []:
        high = _safe_float(point.get("high"))
        low = _safe_float(point.get("low"))
        close = _safe_float(point.get("close"))
        date_value = point.get("date")
        if high is None or low is None:
            continue
        cleaned.append({"date": date_value, "high": high, "low": low, "close": close})

    if len(cleaned) < 2:
        return {"status": "not_enough_price_history"}

    swing_high = max(cleaned, key=lambda item: item["high"])
    swing_low = min(cleaned, key=lambda item: item["low"])
    high = swing_high["high"]
    low = swing_low["low"]
    if high <= low:
        return {"status": "flat_price_range"}

    price_range = high - low
    latest_close = next(
        (item["close"] for item in reversed(cleaned) if item.get("close") is not None),
        None,
    )
    levels = {
        "0.0": round(high, 4),
        "23.6": round(high - price_range * 0.236, 4),
        "38.2": round(high - price_range * 0.382, 4),
        "50.0": round(high - price_range * 0.5, 4),
        "61.8": round(high - price_range * 0.618, 4),
        "78.6": round(high - price_range * 0.786, 4),
        "100.0": round(low, 4),
    }
    return {
        "status": "ok",
        "swing_high": {"date": swing_high.get("date"), "price": round(high, 4)},
        "swing_low": {"date": swing_low.get("date"), "price": round(low, 4)},
        "latest_close": round(latest_close, 4) if latest_close is not None else None,
        "levels": levels,
    }


def _compact_market_context(company_data: dict | None) -> dict:
    if not company_data or not company_data.get("ok"):
        return {
            "status": "not_available",
            "error": (company_data or {}).get("error"),
        }

    security = company_data.get("security") or {}
    market = company_data.get("market") or {}
    price_history = market.get("price_history") or {}
    points = price_history.get("points") or []
    sorted_points = sorted(points, key=lambda item: str(item.get("date") or ""))
    # Keep last 30 for technical indicators computation
    recent_points = [
        {
            "date": point.get("date"),
            "open": _safe_float(point.get("open")),
            "close": _safe_float(point.get("close")),
            "high": _safe_float(point.get("high")),
            "low": _safe_float(point.get("low")),
            "trading_volume": _safe_float(point.get("trading_volume")),
            "trading_value": _safe_float(point.get("trading_value")),
        }
        for point in sorted_points[-30:]
    ]

    reports = (company_data.get("reports") or {}).get("items") or []
    report_documents_limit = max(0, min(REPORT_DOCUMENTS_PROMPT_LIMIT, 300))
    report_documents = [
        {
            "published_at": item.get("published_at"),
            "report_form": item.get("report_form"),
            "period_type": item.get("period_type"),
            "title": item.get("title"),
            "pdf_available": bool(item.get("pdf_url")),
            "excel_available": bool(item.get("excel_url")),
            "pdf_url": item.get("pdf_url"),
            "excel_url": item.get("excel_url"),
        }
        for item in reports[:report_documents_limit]
    ]

    dividends = (company_data.get("dividends") or {}).get("items") or []
    dividend_items = [
        {
            "decision_date": item.get("decision_date"),
            "pub_date": item.get("pub_date"),
            "ticker": item.get("ticker"),
            "common_share_amount": _safe_float(item.get("common_share_amount")),
            "common_share_percent": _safe_float(item.get("common_share_percent")),
            "privileged_share_amount": _safe_float(item.get("priviliged_share_amount")),
            "privileged_share_percent": _safe_float(item.get("priviliged_share_percent")),
            "link": item.get("link"),
        }
        for item in dividends[:5]
    ]
    excel_reports = company_data.get("excel_reports") or {}
    excel_items = []
    excel_prompt_limit = max(0, min(EXCEL_PROMPT_MAX_REPORTS, ABSOLUTE_EXCEL_REPORT_LIMIT))
    sheet_limit = max(1, min(EXCEL_PROMPT_MAX_SHEETS_PER_REPORT, 10))
    row_limit = max(1, min(EXCEL_PROMPT_MAX_ROWS_PER_SHEET, 30))
    for report in (excel_reports.get("items") or [])[:excel_prompt_limit]:
        compact_sheets = []
        for sheet in (report.get("sheets") or [])[:sheet_limit]:
            compact_sheets.append({
                "sheet": sheet.get("sheet"),
                "matched_rows": [
                    {
                        "row": row.get("row"),
                        "label": row.get("label"),
                        "numeric_values": row.get("numeric_values"),
                        "values": (row.get("values") or [])[:8],
                    }
                    for row in (sheet.get("matched_rows") or [])[:row_limit]
                ],
            })
        excel_items.append({
            "report_id": report.get("report_id"),
            "object_id": report.get("object_id"),
            "published_at": report.get("published_at"),
            "period_type": report.get("period_type"),
            "report_form": report.get("report_form"),
            "title": report.get("title"),
            "from_cache": report.get("from_cache", False),
            "content_length": report.get("content_length"),
            "sheet_count": report.get("sheet_count"),
            "facts_count": report.get("facts_count"),
            "sheets": compact_sheets,
        })

    return {
        "status": "ok",
        "company": company_data.get("company") or {},
        "security": {
            "ticker": security.get("ticker"),
            "isin_code": security.get("isin_code"),
            "issuer_short_name": security.get("issuer_short_name"),
            "stock_type": security.get("stock_type"),
            "market_id": security.get("market_id"),
            "board_id": security.get("board_id"),
        },
        "market_summary": market.get("summary") or {},
        "market_availability": market.get("availability") or {},
        "price_history_source": price_history.get("source_url"),
        "recent_price_history": recent_points,
        "fibonacci_levels": _build_fibonacci_levels(sorted_points),
        "dividends": {
            "count": (company_data.get("dividends") or {}).get("count", 0),
            "items": dividend_items,
        },
        "report_documents": {
            "count": (company_data.get("reports") or {}).get("count", 0),
            "items": report_documents,
        },
        "excel_report_snapshots": {
            "enabled": excel_reports.get("enabled", False),
            "count": excel_reports.get("count", 0),
            "selected_count": excel_reports.get("selected_count", 0),
            "included_in_prompt": len(excel_items),
            "items": excel_items,
            "errors": (excel_reports.get("errors") or [])[:5],
        },
        "accounting_api_summary": (company_data.get("accounting") or {}).get("summary") or {},
    }


def _slim_market_context_for_prompt(market_context: dict) -> dict:
    """Create a slimmed version of market context for the AI prompt to reduce input tokens."""
    if not market_context or market_context.get("status") != "ok":
        return market_context

    # Only include last 10 price points instead of 30 for prompt
    recent_prices = market_context.get("recent_price_history") or []
    slim_prices = [
        {"date": p.get("date"), "close": p.get("close"), "volume": p.get("trading_volume")}
        for p in recent_prices[-10:]
    ]

    # Only include last 3 reports instead of all
    reports = market_context.get("report_documents") or {}
    slim_reports = {
        "count": reports.get("count", 0),
        "items": (reports.get("items") or [])[:3],
    }

    # Only include last 2 dividends
    dividends = market_context.get("dividends") or {}
    slim_dividends = {
        "count": dividends.get("count", 0),
        "items": (dividends.get("items") or [])[:2],
    }

    excel_reports = market_context.get("excel_report_snapshots") or {}
    slim_excel_reports = {
        "enabled": excel_reports.get("enabled", False),
        "count": excel_reports.get("count", 0),
        "selected_count": excel_reports.get("selected_count", 0),
        "included_in_prompt": excel_reports.get("included_in_prompt", 0),
        "items": excel_reports.get("items") or [],
        "errors": excel_reports.get("errors") or [],
    }

    return {
        "status": "ok",
        "security": market_context.get("security"),
        "market_summary": market_context.get("market_summary"),
        "market_availability": market_context.get("market_availability") or {},
        "fibonacci_levels": market_context.get("fibonacci_levels"),
        "recent_price_history": slim_prices,
        "dividends": slim_dividends,
        "report_documents": slim_reports,
        "excel_report_snapshots": slim_excel_reports,
    }


def _slim_technical_indicators_for_prompt(indicators: dict) -> dict:
    """Create a slimmed version of technical indicators for the AI prompt."""
    if not indicators or indicators.get("status") != "ok":
        return indicators

    slim = {"status": "ok"}

    # RSI - keep essential
    if "rsi" in indicators:
        rsi = indicators["rsi"]
        slim["rsi"] = {
            "value": rsi.get("value"),
            "signal": rsi.get("signal"),
        }

    # Fibonacci - keep key levels only
    if "fibonacci_price" in indicators:
        fib = indicators["fibonacci_price"]
        slim["fibonacci"] = {
            "current_price": fib.get("current_price"),
            "current_zone": fib.get("current_zone"),
            "nearest_support": fib.get("nearest_support"),
            "nearest_resistance": fib.get("nearest_resistance"),
        }

    # Price momentum - keep summary
    if "price_momentum" in indicators:
        mom = indicators["price_momentum"]
        slim["momentum"] = {
            "trend": mom.get("trend"),
            "total_change_pct": mom.get("changes", {}).get("total"),
        }

    # Volume - keep signal
    if "volume_analysis" in indicators:
        vol = indicators["volume_analysis"]
        slim["volume"] = {
            "signal": vol.get("signal"),
            "divergence": vol.get("divergence"),
        }

    # Volatility - keep level
    if "volatility" in indicators:
        slim["volatility"] = {
            "annual_pct": indicators["volatility"].get("annual_pct"),
            "level": indicators["volatility"].get("level"),
        }

    # Overall summary
    if "summary" in indicators:
        slim["summary"] = indicators["summary"].get("overall")

    return slim
