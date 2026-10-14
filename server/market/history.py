from __future__ import annotations

import server.settings as settings

from datetime import date
from functools import partial
from typing import Any
import asyncio
import formulas
import logging
import reports_catalog as catalog_store
import catalogue.market_store as catalogue_market_store
import securities_catalog as securities_store
import time


logger = logging.getLogger(__name__)


# The periods the board can measure a change over, back from the last settled
# session. Calendar, not sessions: «за неделю» means the price seven days ago, and
# on a market where a security can go a fortnight without a trade, counting
# sessions would call a three-month-old price a week old. And calendar MONTHS, not
# day counts: «3М» from 12.10 starts on 12.07. Written as 91 days it started on
# 13.07, the base became the first session inside the period, and the audit of
# 12.10.2026 found 104 cells off by up to 64 points (ALSMP 3М: 191.57 % against
# 143.53 %). YTD carries no span — its base is the close of 31 December.
#
# The spans are not spelled here: they are formulas.PERIOD_SPANS, the one table
# the card's window, the chart's presets and the absolute returns read too, so a
# period cannot mean one thing on the board and another a click away.
MARKET_CHANGE_WINDOWS: dict[str, dict[str, int] | None] = {
    code: formulas.PERIOD_SPANS[code] for code in ("1w", "1m", "3m", "6m", "1y", "ytd")
}


# The board's name for the shared rule — see formulas.period_cutoff.
window_cutoff = formulas.period_cutoff


def _window_change(points: list[dict[str, Any]], span_days: dict[str, int] | int | None,
                   as_of: date) -> dict[str, Any] | None:
    """The change from the price one window ago (see :func:`window_cutoff`) to the
    latest close.

    The base is the LAST close at or before the cutoff — the price the security
    was worth then — not the first close after it. On a market where a security
    can go weeks without a trade the two are wildly different things: the first
    close inside a seven-day window is routinely yesterday's, which would print a
    one-session move under a label that says a week.

    A carried-forward close (the store's turnover 0) is a legitimate base: it is
    what the security was last worth, and it is what the exchange itself shows.
    Where the store reaches no further back than the cutoff there is no base and
    no figure — an issuer whose history starts inside the window has not moved
    over it, it simply was not there.

    A security with no session after the cutoff did not move: its base close is
    still its latest, and the change is 0 %. The audit of 12.10.2026 found 49
    cells (30 of them 1Н/1М) printing «—» for that instead.
    """
    if not points:
        return None
    cutoff = window_cutoff(span_days, as_of)
    if cutoff >= as_of:
        return None
    base = formulas.base_point(points, cutoff)
    last = points[-1]
    if base is None or not base["close"]:
        return None
    return {"pct": round((last["close"] - base["close"]) / abs(base["close"]) * 100.0, 2),
            "from": base["date"], "base": base["close"]}


def _window_stats(points: list[dict[str, Any]], span_days: dict[str, int] | int | None,
                  as_of: date) -> dict[str, Any] | None:
    """What the security DID over the window, stated the way a session is stated.

    The board could summarise one day — open, high, low, turnover in сумы and in
    bumagi, the average share price, the average deal, the biggest deal — and for
    any longer period it could only offer a percent, because a period's figures
    were a sum nobody held. They are held now: every settled session is banked
    per security, with its own open/high/low, deal count and largest deal beside
    the close, so «за месяц» is thirty sessions added up rather than one session
    reprinted under a heading that says a month.

    Only sessions the security actually TRADED in are counted. The exchange
    repeats a close at zero quantity when nothing traded, and a carried-forward
    day is not a small session: adding it would change no sum but it would make
    ``sessions`` claim activity that did not happen, and ``sessions`` is what
    tells a reader whether «5,6 млрд за полгода» is eighty sessions or three.

    The window is the same half-open span the change over it uses — everything
    strictly after the cutoff, through the latest session — so a figure and the
    percent beside it describe the same stretch of calendar.

    Every field answers or is absent; nothing is estimated to fill a column.
    Where a banked session carries no high/low (openinfo's archive reaches
    further back than the day statistics do) the session's close stands in for
    it — a real traded price of that session, and a bound the true extreme can
    only be wider than — and ``approx`` says so, so the interface can mark it.
    """
    if not points:
        return None
    cutoff = window_cutoff(span_days, as_of)
    if cutoff >= as_of:
        return None
    inside = formulas.in_period(points, cutoff)
    traded = [p for p in inside if (p.get("turnover") or 0) > 0 or (p.get("quantity") or 0) > 0]
    if not traded:
        return None
    total = sum(p.get("turnover") or 0.0 for p in traded)
    qty = sum(p.get("quantity") or 0.0 for p in traded)
    # Sessions banked with the day statistics beside them — the ones that can say
    # how many deals they were made of and which was the biggest. openinfo's
    # archive reaches further back than those statistics do, so over a year this
    # is routinely a SUBSET, and the average deal must be computed inside it:
    # the whole window's сумы over part of the window's deals would overstate the
    # average by exactly the sessions it could not see.
    counted = [p for p in traded if p.get("trade_count") is not None]
    trades = sum(int(p["trade_count"]) for p in counted) if counted else None
    counted_value = sum(p.get("turnover") or 0.0 for p in counted)
    highs = [p.get("high") if p.get("high") is not None else p.get("close") for p in traded]
    lows = [p.get("low") if p.get("low") is not None else p.get("close") for p in traded]
    highs = [h for h in highs if h is not None]
    lows = [low for low in lows if low is not None]
    first = traded[0]
    last = traded[-1]
    biggest = max((p for p in traded if p.get("largest_value") is not None),
                  key=lambda p: p["largest_value"], default=None)
    out: dict[str, Any] = {
        "value": round(total),
        "sessions": len(traded),
        "from": first["date"],
        "to": last["date"],
        # The period's opening price is the first session INSIDE it that traded —
        # its own open where the session was banked with one, its close where it
        # was not. Not the base the percent is measured from: that close belongs
        # to a session before the window, and a period's open is a price the
        # period itself printed.
        "open": first.get("open") if first.get("open") is not None else first.get("close"),
        "close": last.get("close"),
    }
    if qty > 0:
        out["qty"] = round(qty)
        # Средневзвешенная по объёму цена периода: what the whole window's сумы
        # bought, divided by the bumagi they bought. Over one session this is the
        # session VWAP the column already shows, which is the point.
        if total > 0:
            out["vwap"] = round(total / qty, 2)
    if highs:
        out["high"] = round(max(highs), 2)
    if lows:
        out["low"] = round(min(lows), 2)
    if trades:
        out["trades"] = trades
        if counted_value > 0:
            out["avg_trade"] = round(counted_value / trades)
    if biggest is not None:
        out["largest_value"] = round(biggest["largest_value"])
        if biggest.get("largest_qty") is not None:
            out["largest_qty"] = round(biggest["largest_qty"])
        if total > 0:
            out["largest_pct"] = round(biggest["largest_value"] / total * 100, 2)
        out["largest_from"] = biggest["date"]
    # How much of the window those two figures actually saw. Only when it is less
    # than the whole: the deal count and the largest deal are then a floor and the
    # interface says so, rather than printing a partial answer as a complete one.
    if counted and len(counted) < len(traded):
        out["detail_sessions"] = len(counted)
    # True session extremes are banked only for the sessions the day statistics
    # or openinfo's archive could see. Where some session inside the window stood
    # in with its close, the high and low are bounds and the interface says so.
    if any(p.get("high") is None or p.get("low") is None for p in traded):
        out["approx"] = True
    return out


async def _resolve_isin(ticker: str) -> str | None:
    """ISIN for a ticker: local catalog first, listing registry, then the feed.

    The ISIN is known locally (securities catalog / listing registry) — resolve
    there first. The live feed only lists actively traded tickers, so inactive
    listings used to die with "ISIN not found"; it remains the last-resort
    fallback for brand-new tickers.
    """
    import os
    import requests as _req

    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    try:
        smap = await loop.run_in_executor(None, securities_store.get_securities_map)
        isin = str((smap.get(ticker) or {}).get("isin") or "").strip() or None
        if isin:
            return isin
    except Exception:  # noqa: BLE001
        pass
    try:
        listings = await loop.run_in_executor(None, catalogue_market_store.get_all_listings)
        isin = str(((listings or {}).get(ticker) or {}).get("isin") or "").strip() or None
        if isin:
            return isin
    except Exception:  # noqa: BLE001
        pass
    if not settings.UZSE_STOCK_API_BASE:
        return None
    try:
        resp = await loop.run_in_executor(
            None, lambda: _req.get(f"{settings.UZSE_STOCK_API_BASE}/stocks", timeout=15))
        stocks = resp.json().get("stocks", []) if resp.ok else []
        return next((s["isin"] for s in stocks if s.get("ticker", "").upper() == ticker), None)
    except Exception:  # noqa: BLE001
        return None


# Full history per ISIN, kept briefly in-process. The metrics endpoint needs the
# WHOLE series on every call (absolute metrics are computed on it by definition),
# so without this a period switch would refetch five years from openinfo.
_HISTORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


_HISTORY_CACHE_TTL = 600.0


_HISTORY_CACHE_MAX = 256


async def _full_history(isin: str, months: int = 60) -> dict[str, Any]:
    """Full price history for an ISIN, memoised for _HISTORY_CACHE_TTL seconds."""
    from collectors.openinfo.market import fetch_price_history

    # Requests for the same archive can arrive together (the company chart and
    # metrics do this on first paint). Let the first fetch populate the cache
    # while the others wait for and reuse that result.
    key = f"{isin}:{months}"
    now = time.time()
    hit = _HISTORY_CACHE.get(key)
    if hit and now - hit[0] < _HISTORY_CACHE_TTL:
        return hit[1]
    lock = _HISTORY_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _HISTORY_CACHE.get(key)
        if hit and time.time() - hit[0] < _HISTORY_CACHE_TTL:
            return hit[1]
        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                None, partial(fetch_price_history, isin, None, months),
            )
        except Exception:  # noqa: BLE001 — the store alone is still the board's answer
            logger.warning("price archive unreadable for %s; serving the store alone", isin,
                           exc_info=True)
            data = None
        merged = await loop.run_in_executor(
            None, partial(_with_stored_sessions, isin, data or {"points": [], "adjustments": []},
                          months))
        if data is None and not merged.get("points"):
            raise RuntimeError(f"no price history for {isin}: archive unreadable, store empty")
        data = merged
        if len(_HISTORY_CACHE) >= _HISTORY_CACHE_MAX:
            oldest = min(_HISTORY_CACHE, key=lambda k: _HISTORY_CACHE[k][0])
            _HISTORY_CACHE.pop(oldest, None)
        _HISTORY_CACHE[key] = (time.time(), data)
        return data


def _with_stored_sessions(isin: str, data: dict[str, Any],
                          months: int | None = None) -> dict[str, Any]:
    """The card's daily history: the board's store, and the archive only where the
    store does not reach.

    The board measures every period from ``catalog_quote_history``; the card, its
    chart and its «За период» block read openinfo's archive. Two histories of one
    security disagreed — on 13.10.2026 in 541 sessions of 60 securities (AGMKP on
    13.10.2025: 8 701,01 on the card, 8 800 on the board, one turnover), and the
    archive's 21.04.2026 printed a close of 0 for 25 securities, which the card
    dropped as no session at all: every «1Г» on those cards was one session short
    of the board's. There is one history now. From the store's first session on,
    every session is the store's — the same row the board, the sparklines and the
    session counts read — and the archive answers only for the years before it
    (the chart's «Макс»). A session the archive has inside that span and the store
    lacks is a gap in the STORE, which the collector's reconcile pass fills from
    the same archive (``--backfill-history``); showing it here alone is what made
    the card and the board describe different years.

    This is also why a session reaches the card the hour it settles: openinfo
    publishes a day late, the store does not (64 cards ended on 09.10 on 12.10).

    Only traded sessions are drawn: the exchange carries a close forward at zero
    turnover, and that is not a session. Prices are restated onto today's share
    exactly as the archive's are (corporate_actions.adjust_history), so the two
    halves of a series meet in one unit.
    """
    import corporate_actions

    points = list(data.get("points") or [])
    try:
        stored = catalogue_market_store.get_quote_history([isin], 3650).get(str(isin).upper()) or []
    except Exception:  # noqa: BLE001 — the archive alone is still an answer
        return data
    start = (formulas.months_before(date.today(), max(1, int(months))).strftime("%Y%m%d")
             if months else "")
    rows = [r for r in stored
            if len(str(r.get("trade_date") or "")) == 8 and str(r["trade_date"]).isdigit()
            and str(r["trade_date"]) >= start]
    if not rows:
        return data
    covered_from = min(str(r["trade_date"]) for r in rows)
    covered_from = f"{covered_from[:4]}-{covered_from[4:6]}-{covered_from[6:]}"
    sessions = []
    for r in rows:
        close = formulas.to_number(r.get("close_price"))
        traded = (r.get("turnover") or 0) > 0 or (r.get("quantity") or 0) > 0
        if close is None or close <= 0 or not traded:
            continue
        stamp = str(r["trade_date"])
        sessions.append({"date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}",
                         "open": r.get("open_price"), "high": r.get("high_price"),
                         "low": r.get("low_price"), "close": close,
                         "change": r.get("change_value"), "trading_volume": r.get("quantity"),
                         "trading_value": r.get("turnover"), "trade_count": r.get("trade_count")})
    sessions, applied = corporate_actions.adjust_history(sessions, data.get("ticker"), isin)
    older = [p for p in points if str(p.get("date") or "")[:10] < covered_from]
    merged = sorted([*older, *sessions], key=lambda p: str(p.get("date") or ""))
    adjustments = list(data.get("adjustments") or [])
    known = {a.get("ex_date") for a in adjustments}
    adjustments.extend(a for a in applied if a.get("ex_date") not in known)
    return {**data, "points": merged, "adjustments": adjustments,
            "store_from": covered_from}


_MARKET_AS_OF: dict[str, Any] = {"at": 0.0, "value": None}


_MARKET_AS_OF_TTL = 60.0


async def _market_as_of() -> date | None:
    """The market's latest stored session — every period's end (see formulas.period_cutoff).

    The board ends its windows here (server/market/routes.py); the card and the
    chart must end theirs on the same day, or a weekend moves one of them a
    session. Kept a minute in-process: it changes once a session, and the card
    asks on every period button. ``None`` when the store cannot say, and the
    caller falls back to the calendar.
    """
    now = time.time()
    if _MARKET_AS_OF["value"] is not None and now - _MARKET_AS_OF["at"] < _MARKET_AS_OF_TTL:
        return _MARKET_AS_OF["value"]
    try:
        value = await asyncio.get_running_loop().run_in_executor(
            None, catalogue_market_store.latest_session_date)
    except Exception:  # noqa: BLE001 — the calendar is the documented fallback
        logger.warning("market as-of unreadable; periods fall back to today", exc_info=True)
        return None
    _MARKET_AS_OF.update(at=now, value=value)
    return value


# Names for the day-based windows. formulas.WINDOW_LABELS_RU is keyed by month
# count and has no entry for a week or for a year-to-date span, which is exactly
# why those two used to arrive labelled as a month.
_WINDOW_LABELS_RU = {"1d": "за сессию", "1w": "за неделю", "ytd": "с начала года"}


_HISTORY_LOCKS: dict[str, asyncio.Lock] = {}
