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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

UZSE_TRADE_URL = "https://uzse.uz/trade_results/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")


def _feed_session() -> requests.Session:
    """Retry the feed rather than end the session on one bad page."""
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=3, backoff_factor=1.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET", "HEAD"), respect_retry_after_header=True)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

# Fields carrying the per-trade numbers, and a stable id used to dedupe.
_KEYS = ("total_value", "total_qty", "trade_count", "avg_price",
         "largest_qty", "largest_value", "largest_pct_value", "largest_pct_qty")

# The exchange's own execution classification, measured over the full sessions
# of 12–14.08.2026: every auction execution — stock and bond alike — carries
# board_id "G1"; a negotiated (пакетная) deal carries "T1", and the exchange's
# OWN daily bulletin excludes it. HMKB 14.08 is the proof: 878 G1 executions
# sum to exactly the bulletin's 839 168 papers / 82,9 млн, while the lone T1
# execution moved 2,2 млрд papers at 55,00 — a −44% discount that belongs to
# no session's OHLC. Folding it in made the card contradict itself three ways:
# a day's turnover 2,2× the year's, an average price outside the day's range,
# and a stored low (55,0) the exchange never printed.
NEGO_BOARD_IDS = {"T1"}


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_block(trade: dict) -> bool:
    return str(trade.get("board_id") or "") in NEGO_BOARD_IDS


def _aggregate(isin: str, lst: list[dict], trade_date: str) -> dict[str, Any]:
    """Per-security day statistics from that day's individual executions.

    The session numbers — totals, OHLC, averages, the largest trade — are
    computed from PRICE-ELIGIBLE executions only, which is the set the
    exchange's own bulletin aggregates. Negotiated deals are recorded beside
    them in ``block_*``: real money that changed hands that day, but at a
    bilaterally agreed price that never stood in the order book, so it may not
    move a candle, a turnover column or a "top liquidity" panel.

    openinfo's archive marks every execution with ``board_id``; whether the
    UZSE rolling feed carries the field too is unverified (the feed is empty
    on weekends) — the loud warning below is what answers that question from
    the first weekday run's log.
    """
    eligible = [x for x in lst if not _is_block(x)]
    blocks = [x for x in lst if _is_block(x)]
    unmarked = sum(1 for x in lst if "board_id" not in x)
    if unmarked:
        logger.warning(
            "%s %s: %d of %d executions carry no board_id — negotiated deals "
            "cannot be told apart and are counted into the session",
            isin, trade_date, unmarked, len(lst))

    total_value = sum(_f(x.get("trading_value")) for x in eligible)
    total_qty = sum(_f(x.get("trade_quantity")) for x in eligible)
    prices = [_f(x.get("trade_price")) for x in eligible if _f(x.get("trade_price")) > 0]
    big = max(eligible, key=lambda x: _f(x.get("trading_value")), default=None)
    bv = _f(big.get("trading_value")) if big else None
    bq = _f(big.get("trade_quantity")) if big else None
    # Session OHLC from the executions in time order — the exchange's official
    # closing price is the day's LAST trade, which the averages can't stand in
    # for (the daily bulletin's change is computed close-to-close). openinfo's
    # archive records carry trade_datetime; the UZSE rolling feed does NOT —
    # there the monotonically increasing id/trade_number is the time order
    # (the feed itself lists newest first, so input order must not be trusted).
    timed = sorted((x for x in eligible if _f(x.get("trade_price")) > 0),
                   key=lambda x: (str(x.get("trade_datetime") or ""),
                                  _f(x.get("trade_number")), _f(x.get("id"))))
    open_p = _f(timed[0].get("trade_price")) if timed else None
    close_p = _f(timed[-1].get("trade_price")) if timed else None
    return {
        "open_price": open_p,
        "close_price": close_p,
        "high_price": max(prices) if prices else None,
        "low_price": min(prices) if prices else None,
        "isin": isin,
        # Which board the security trades on (STK / BND). Carried so the quote
        # pass can ask uzse.uz for the right view without a second lookup.
        "market": next((str(x.get("market_id")) for x in lst if x.get("market_id")), None),
        "trade_date": trade_date,
        "total_value": round(total_value, 2),
        "total_qty": total_qty,
        "trade_count": len(eligible),
        "avg_price": round(sum(prices) / len(prices), 2) if prices else None,
        "vwap": round(total_value / total_qty, 2) if total_qty else None,
        "largest_qty": bq,
        "largest_value": round(bv, 2) if bv is not None else None,
        "largest_pct_value": round(bv / total_value * 100, 2) if (bv is not None and total_value) else None,
        "largest_pct_qty": round(bq / total_qty * 100, 2) if (bq is not None and total_qty) else None,
        # The negotiated deals of the day, apart from the session — the flag
        # a bar carries; the deals themselves keep their own numbers.
        "block_count": len(blocks),
        "block_qty": sum(_f(x.get("trade_quantity")) for x in blocks) or None,
        "block_value": round(sum(_f(x.get("trading_value")) for x in blocks), 2) or None,
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

    Returns ``{"trade_date": "YYYYMMDD", "count": n, "reachable": bool,
    "complete": bool, "stats": {isin: {...}}}``.

    ``reachable`` separates the two ways this comes back empty. The feed holds
    only yesterday and today (see DEPLOY.md), so a Monday-morning run reads a
    Saturday+Sunday window and the exchange correctly answers "nothing traded" —
    an empty session, not a fault. A feed that never answered is a fault. Only
    the first page has to land for the exchange to have spoken.

    ``complete`` says the pagination reached the end of the session rather than
    stopping on an error. A page that fails halfway used to end the walk and
    return what had been gathered so far, which is a *smaller* session — real
    ISINs, real executions, turnover short by however many pages were missed,
    and nothing anywhere saying so. Truncated totals are worse than none.
    """
    s = session or _feed_session()
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    seen: set = set()
    trades: list[dict] = []
    latest_day: str | None = None
    reachable = complete = False

    for page in range(1, max_pages + 1):
        try:
            resp = s.get(UZSE_TRADE_URL, headers=headers, params={"page": page}, timeout=30)
            res = resp.json().get("results") or []
            reachable = True
        except Exception:
            logger.exception("trade feed page %d failed", page)
            break
        if not res:
            complete = True
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
            complete = True
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
    return {"trade_date": latest_day, "count": len(stats),
            "reachable": reachable, "complete": complete, "stats": stats}


if __name__ == "__main__":
    import json
    data = fetch_trade_stats()
    print("trade_date:", data["trade_date"], "| securities:", data["count"])
    uz = data["stats"].get("UZ7003040001")
    if uz:
        print("UZMT:", json.dumps(uz, ensure_ascii=False))
