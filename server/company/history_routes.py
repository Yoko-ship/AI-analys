from __future__ import annotations

import server.market.patterns as market_patterns

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from functools import partial
from typing import Any
import asyncio
import obs
import reports_catalog as catalog_store
import server.http as http
import server.market.history as market_history


router = APIRouter()


@router.get("/api/company/{ticker}/metrics")
async def api_company_metrics(ticker: str, months: int = 12,
                              days: int | None = None,
                              window: str | None = None) -> dict[str, Any]:
    """Window and absolute price metrics for one instrument (ТЗ v1.2 §5).

    The two blocks are the contract: ``window`` follows the period button,
    ``absolute`` never does.

    ``days`` is for the two buttons a month count cannot express — «1Н» is seven
    days, YTD is however many have passed since 1 January — and ``window`` names
    the result (``1w`` / ``ytd``). Without them the card answered «1Н» with a
    month: twenty-one sessions and a range four times too wide, under a label
    that said one week. Both are computed by formulas.py from one full
    history fetch, so the card, the market screen and the export cannot each
    arrive at a different VWAP or a different YTD.
    """
    from datetime import datetime, timezone

    import formulas

    ticker = ticker.upper()
    months = max(1, min(months, 60))
    days = max(1, min(int(days), 3650)) if days else None
    code = str(window).strip().lower()[:12] or None if window else None
    label = market_history._WINDOW_LABELS_RU.get(code) if code else None
    # ТЗ §12: every number on the card can be replayed step by step under one
    # trace_id — input, decision with its reason, output.
    trace = obs.Trace(endpoint="company/metrics", ticker=ticker, months=months, days=days)
    try:
        isin = await market_history._resolve_isin(ticker)
        if not isin:
            trace.reject("resolve_isin", reason="ISIN not found")
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "trace_id": trace.trace_id}, status_code=404)
        trace.step("resolve_isin", out={"isin": isin})
        # Match the company's default chart archive so first paint shares one
        # upstream fetch instead of downloading separate 5- and 20-year series.
        data = await market_history._full_history(isin, months=240)
        points = data.get("points") or []
        trace.step("history_fetch", out={"points": len(points)})
        metrics = formulas.company_metrics(points, months=months, days=days,
                                           code=code, label=label)
        window, absolute, quality = metrics["window"], metrics["absolute"], metrics["quality"]
        trace.step("window_metrics", out={"code": window["code"], "points": window["points"],
                                          "vwap": window["vwap"].get("value"),
                                          "method": window["vwap"].get("method")})
        trace.step("absolute_metrics", decision="no_window_param",
                   out={k: (v or {}).get("value") for k, v in absolute.items()})
        trace.step("quality", decision=quality["data_tier"], reason=quality.get("reason"),
                   out={"candles": quality["candles_enabled"]})
        return {
            "ok": True, "ticker": ticker, "isin": isin,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trace_id": trace.trace_id,
            **metrics,
        }
    except Exception as exc:
        trace.reject("metrics", reason=str(exc))
        http.logger.exception("metrics failed for %s", ticker)
        return JSONResponse({"ok": False, "ticker": ticker, "error": str(exc),
                             "trace_id": trace.trace_id}, status_code=502)
    finally:
        trace.close()


@router.get("/api/price-history/{ticker}")
async def api_price_history(ticker: str, months: int = 12) -> dict[str, Any]:
    """Close price history for a ticker via UZSE ISIN lookup.

    The ceiling is 20 years, not 5: the chart's «Макс» button means the whole
    record, and a 60-month clamp would quietly serve five years under that label
    the moment an issuer's history grew past it. The archive answers with what
    exists, so asking for more than a security has costs nothing.
    """
    ticker = ticker.upper()
    months = max(1, min(months, 240))
    try:
        isin = await market_history._resolve_isin(ticker)
        if not isin:
            # ТЗ §10.4.6: an unknown instrument is a 404. Returning 200 with a
            # failure body is why neither the browser, retries nor monitoring
            # could tell a fault from a normal answer.
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "points": []}, status_code=404)
        data = await market_history._full_history(isin, months=months)
        points = [
            {
                "date": p.get("date"),
                "open": p.get("open"),
                "high": p.get("high"),
                "low": p.get("low"),
                "close": p.get("close"),
                "change": p.get("change"),
                "volume": p.get("trading_volume"),
                "value": p.get("trading_value"),
            }
            for p in (data.get("points") or [])
            if p.get("date") and p.get("close") is not None
        ]
        # Non-empty only when the series spans a split or a bonus issue: the older prices
        # have been restated onto today's share, so the chart says so rather than let a
        # reader reconcile it against uzse.uz and conclude we are wrong.
        return {
            "ok": True, "ticker": ticker, "isin": isin, "points": points,
            "adjustments": data.get("adjustments") or [],
        }
    except Exception as exc:
        http.logger.exception("price-history failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "points": []}


@router.get("/api/intraday/{ticker}")
async def api_intraday(ticker: str, days: int = 8) -> dict[str, Any]:
    """Hourly bars for the 1Д/1Н chart, from ``catalog_intraday_history``.

    The bars are rolled up from the exchange's own trade feed (per-trade moments
    live in each record's header; negotiated T1 deals are excluded — see
    trade_stats.hourly_bars) and banked by the collector: hourly by the
    trade-stats cron, historically by ``--backfill-intraday``, which the feed's
    date-filtered view makes possible months back. Days the bank has nothing
    for honestly have no bars, and the chart mixes in daily closes for them.
    Dates are ISO with an hour ("2026-08-17T14:00") so a series shared with the
    daily feed still sorts as strings.
    """
    ticker = ticker.upper()
    days = max(1, min(days, 60))
    loop = asyncio.get_running_loop()
    try:
        isin = await market_history._resolve_isin(ticker)
        if not isin:
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "points": []}, status_code=404)
        rows = await loop.run_in_executor(None, partial(catalog_store.get_intraday_history, isin, days))
        points = [
            {
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}T{int(r['hour']):02d}:00",
                "open": r.get("open_price"),
                "high": r.get("high_price"),
                "low": r.get("low_price"),
                "close": r.get("close_price"),
                "volume": r.get("quantity"),
                "value": r.get("turnover"),
            }
            for r in rows
            if (d := str(r.get("trade_date") or "")) and r.get("close_price") is not None
        ]
        return {"ok": True, "ticker": ticker, "isin": isin, "points": points}
    except Exception as exc:
        http.logger.exception("intraday failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "points": []}


@router.get("/api/company/{ticker}/patterns")
async def api_company_patterns(ticker: str, sensitivity: str = "medium") -> Any:
    """Chart figures, reversal candles and cycles in a security's daily history.

    Annotation, not advice: every pattern arrives with how that pattern type
    has actually done on liquid UZSE shares, beside the rate an ordinary
    session reaches the same target by chance — and on this market the first
    number is usually the smaller. Securities outside the full liquidity tier
    get no patterns at all: on a day that printed one price a candle has no
    shape, and a triangle drawn through three trades a month is a drawing of
    the gaps. ``sensitivity`` (low / medium / high) is the ZigZag swing size,
    and the outcome table quoted is the one measured at that size.
    """
    import formulas
    import pattern_engine

    ticker = ticker.strip().upper()
    level = sensitivity if sensitivity in pattern_engine.SENSITIVITY else "medium"
    isin = await market_history._resolve_isin(ticker)
    if not isin:
        return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found"}, status_code=404)
    isin = str(isin).upper()
    data = await market_history._full_history(isin, months=240)
    points = data.get("points") or []
    quality = formulas.data_quality(formulas.normalize_points(points))
    stats = market_patterns._pattern_market_stats()
    level_stats = (stats.get("by_sensitivity") or {}).get(level) or {}
    base = {"ok": True, "ticker": ticker, "isin": isin, "tier": quality["data_tier"], "sensitivity": level,
            "model_version": pattern_engine.MODEL_VERSION, "market_stats": level_stats.get("types", {}),
            "stats_meta": {"securities": level_stats.get("securities"),
                           **{k: stats.get(k) for k in ("generated", "universe", "method", "parameters")}},
            "disclaimer": "Historical pattern statistics only; not a trading recommendation."}
    if quality["data_tier"] != "full":
        return {**base, "status": "INSUFFICIENT_LIQUIDITY", "reason": quality.get("reason"), "signals": []}

    result = await market_patterns._pattern_analysis(isin, points, level)
    if result["status"] != "AVAILABLE":
        return {**base, "status": result["status"], "reason": result.get("reason"), "signals": []}
    keep = ("type", "family", "direction", "start_date", "signal_date", "price", "target", "stop",
            "points", "lines", "angles", "box", "outcome", "entry_date", "exit_date", "directional_return_pct")
    return http._json_safe({
        **base, "status": "AVAILABLE", "period": result["period"],
        "signals": [{k: s.get(k) for k in keep} for s in result["signals"]],
        "stock_stats": result["summary"],
        "backtest": {"all": result["backtest"], **result["backtest_by_family"],
                     "fee_bps": result["parameters"]["fee_bps"],
                     "slippage_bps": result["parameters"]["slippage_bps"],
                     "horizon": result["parameters"]["horizon"]},
        "cycle": result["cycle"],
    })
