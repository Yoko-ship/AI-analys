from __future__ import annotations

from functools import partial
from server.settings import PROJECT_ROOT
from typing import Any
import asyncio
import json
import server.http as http
import server.market.history as market_history


_PATTERN_CACHE: dict[str, dict[str, Any]] = {}


_PATTERN_STATS: dict[str, Any] = {}


def _pattern_market_stats() -> dict[str, Any]:
    """The liquid-tier outcome table scripts/pattern_research.py wrote.

    Read once: it changes only when the research is re-run and redeployed.
    """
    if not _PATTERN_STATS:
        path = (PROJECT_ROOT / "config") / "pattern_stats.json"
        try:
            _PATTERN_STATS.update(json.loads(path.read_text()))
        except (OSError, ValueError):
            http.logger.warning("pattern stats unavailable at %s", path)
    return _PATTERN_STATS


async def _pattern_analysis(isin: str, points: list[dict[str, Any]], level: str = "medium") -> dict[str, Any]:
    """pattern_engine.analyse on the chart's own history, re-run only when a new
    session has arrived (the history cache already dedupes the fetch)."""
    import pattern_engine

    key = f"{len(points)}:{points[-1].get('date') if points else ''}"
    cache_key = f"{isin}:{level}"
    hit = _PATTERN_CACHE.get(cache_key)
    if not hit or hit["key"] != key:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(pattern_engine.analyse, points, sensitivity=level))
        if len(_PATTERN_CACHE) >= market_history._HISTORY_CACHE_MAX:
            _PATTERN_CACHE.pop(next(iter(_PATTERN_CACHE)), None)
        hit = _PATTERN_CACHE[cache_key] = {"key": key, "result": result}
    return hit["result"]


PATTERN_ALERT_DAYS = 5


async def _pattern_alerts(favorites: list[dict[str, Any]], types: list[str]) -> list[dict[str, Any]]:
    """Bell items for figures completed lately on watchlist companies.

    Only liquid securities (the chart draws nothing on the rest), at the
    default sensitivity, and only the chosen types — every chart figure when
    none were chosen. The fields are the stable facts of the event (ticker,
    pattern, session), so the item keeps its read state between polls.
    """
    import formulas
    import pattern_engine
    from datetime import date, timedelta

    wanted = set(types) if types else set(pattern_engine.CHART_TYPES)
    since = (date.today() - timedelta(days=PATTERN_ALERT_DAYS)).isoformat()
    items: list[dict[str, Any]] = []
    for favorite in favorites:
        ticker = str(favorite.get("ticker") or "").upper()
        if not ticker or not favorite.get("pattern_alert_enabled"):
            continue
        isin = await market_history._resolve_isin(ticker)
        if not isin:
            continue
        points = (await market_history._full_history(str(isin).upper(), months=240)).get("points") or []
        if formulas.data_quality(formulas.normalize_points(points))["data_tier"] != "full":
            continue
        result = await _pattern_analysis(str(isin).upper(), points, "medium")
        for sig in result.get("signals") or []:
            if sig["signal_date"] < since or sig["type"] not in wanted:
                continue
            # Only the event's own facts: the item id is a hash of its fields,
            # and a market-wide figure here would re-open every read alert the
            # day the statistics are regenerated.
            items.append({"ticker": ticker, "report_form": "PATTERN", "year": None, "quarter": 0,
                          "kind": "pattern", "pattern": sig["type"], "direction": sig["direction"],
                          "signal_date": sig["signal_date"], "detected_at": sig["signal_date"],
                          "title": f"{sig['type']} {sig['direction']}", "href": f"/company/{ticker}"})
    return items
