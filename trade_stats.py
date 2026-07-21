"""Per-trade market statistics from UZSE (uzse.uz/trade_results).

The exchange exposes individual executions (not just daily aggregates), which
lets us compute, per security for the latest trading day: total turnover (sums),
total quantity, average trade price (simple mean of trade prices), and the
single largest trade with its share of the day's total. The feed is a recent-
first, 50-per-page rolling list, so we paginate until we pass the latest day.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

import requests

logger = logging.getLogger(__name__)

UZSE_TRADE_URL = "https://uzse.uz/trade_results/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Fields carrying the per-trade numbers, and a stable id used to dedupe.
_KEYS = ("total_value", "total_qty", "trade_count", "avg_price",
         "largest_qty", "largest_value", "largest_pct_value", "largest_pct_qty")


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _aggregate(isin: str, lst: list[dict], trade_date: str) -> dict[str, Any]:
    """Per-security day statistics from that day's individual executions."""
    total_value = sum(_f(x.get("trading_value")) for x in lst)
    total_qty = sum(_f(x.get("trade_quantity")) for x in lst)
    prices = [_f(x.get("trade_price")) for x in lst if _f(x.get("trade_price")) > 0]
    big = max(lst, key=lambda x: _f(x.get("trading_value")))
    bv, bq = _f(big.get("trading_value")), _f(big.get("trade_quantity"))
    return {
        "isin": isin,
        "trade_date": trade_date,
        "total_value": round(total_value, 2),
        "total_qty": total_qty,
        "trade_count": len(lst),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "vwap": round(total_value / total_qty, 2) if total_qty else None,
        "largest_qty": bq,
        "largest_value": round(bv, 2),
        "largest_pct_value": round(bv / total_value * 100, 2) if total_value else None,
        "largest_pct_qty": round(bq / total_qty * 100, 2) if total_qty else None,
    }


def backfill_last_day_stats(targets: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Day statistics for securities that did NOT trade today: their last
    trading day's executions from openinfo's ``/iuzse/trade-results/`` (the
    UZSE rolling feed retains only the current day, but openinfo serves the
    same execution records for any past date, filtered by ISIN).

    ``targets``: [(isin, last_trade_date)] with the date as YYYY-MM-DD or
    YYYYMMDD. openinfo duplicates execution records — identical
    (datetime, price, qty) triples are the same trade and are deduped.
    """
    from openinfo_collector import _json_get, _make_session
    session = _make_session()
    out: list[dict[str, Any]] = []
    for isin, day in targets:
        d = str(day or "").replace("-", "")
        if len(d) != 8 or not d.isdigit():
            continue
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        rows: list[dict] = []
        page = 1
        while True:
            try:
                payload = _json_get(session, "/iuzse/trade-results/",
                                    {"isu_cd": isin, "start_date": iso,
                                     "end_date": iso, "page_size": 200, "page": page})
            except Exception:  # noqa: BLE001
                payload = None
            results = (payload.get("results") or []) if isinstance(payload, dict) else []
            rows.extend(results)
            if not (isinstance(payload, dict) and payload.get("has_next")):
                break
            page += 1
        seen: set = set()
        lst = []
        for x in rows:
            key = (x.get("trade_datetime"), x.get("trade_price"), x.get("trade_quantity"))
            if key in seen:
                continue
            seen.add(key)
            lst.append(x)
        if lst:
            out.append(_aggregate(isin, lst, d))
    return out


def fetch_trade_stats(max_pages: int = 400, session: requests.Session | None = None) -> dict[str, Any]:
    """Paginate the trade feed for the latest trading day and aggregate per ISIN.

    Returns ``{"trade_date": "YYYYMMDD", "count": n, "stats": {isin: {...}}}``.
    """
    s = session or requests.Session()
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    seen: set = set()
    trades: list[dict] = []
    latest_day: str | None = None

    for page in range(1, max_pages + 1):
        try:
            resp = s.get(UZSE_TRADE_URL, headers=headers, params={"page": page}, timeout=30)
            res = resp.json().get("results") or []
        except Exception:
            logger.exception("trade feed page %d failed", page)
            break
        if not res:
            break
        if latest_day is None:
            latest_day = max(str(x.get("trade_date")) for x in res)
        reached_older = False
        added = 0
        for x in res:
            day = str(x.get("trade_date"))
            if day < latest_day:
                reached_older = True
                continue
            tid = x.get("id")
            if tid in seen:
                continue
            seen.add(tid)
            trades.append(x)
            added += 1
        if reached_older or added == 0:
            break

    by: dict[str, list] = defaultdict(list)
    for x in trades:
        if str(x.get("trade_date")) == latest_day:
            by[x.get("issue_code")].append(x)

    stats: dict[str, dict[str, Any]] = {}
    for isin, lst in by.items():
        if not isin:
            continue
        stats[isin] = _aggregate(isin, lst, latest_day)
    return {"trade_date": latest_day, "count": len(stats), "stats": stats}


if __name__ == "__main__":
    import json
    data = fetch_trade_stats()
    print("trade_date:", data["trade_date"], "| securities:", data["count"])
    uz = data["stats"].get("UZ7003040001")
    if uz:
        print("UZMT:", json.dumps(uz, ensure_ascii=False))
