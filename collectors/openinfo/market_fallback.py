"""Validated UZSE market data from OpenInfo when the exchange is unreachable."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import logging
import math
from typing import Any

from collectors.openinfo.transport import _json_get, _make_session
import trade_stats as ts

log = logging.getLogger(__name__)
TASHKENT = timezone(timedelta(hours=5))


def _number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite market number")
    return number


def _latest_day(client: Any) -> str:
    payload = _json_get(client, "/iuzse/trade-results/", {"page": 1, "page_size": 1})
    stamp = datetime.fromisoformat(payload["results"][0]["trade_datetime"])
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(TASHKENT)
    if stamp.date() > datetime.now(TASHKENT).date():
        raise ValueError("archive latest session is in the future")
    return stamp.date().isoformat()


def fetch_latest_trade_stats(*, min_day: str | None = None, session: Any = None,
                             max_pages: int = 100, session_day: str | None = None) -> dict:
    """Return a complete, stable session or an explicit failure with no rows.

    ``session_day`` (YYYY-MM-DD) publishes that finished session instead of the
    newest one — the newest is often still being written (trading, or openinfo
    not yet holding its daily conclusions), and an operator may need the one
    before it now rather than at 21:30.

    Pin the latest session before pagination; require the advertised count on
    every page and recheck it afterwards. Preserve identical executions: the
    archive has no execution IDs, and separate auction trades can share every
    visible field. Deduplicating those would understate actual volume.
    """
    failure = {"source": "openinfo", "reachable": False, "complete": False,
               "trade_date": None, "count": 0, "stats": {}, "intraday": []}
    client = session or _make_session()
    try:
        latest = _latest_day(client)
        iso_day = latest
        if session_day:
            iso_day = date.fromisoformat(str(session_day)).isoformat()
            if iso_day > latest:
                raise ValueError(f"archive has no session {iso_day} yet (latest {latest})")
        day = iso_day.replace("-", "")
        if min_day and day < str(min_day).replace("-", ""):
            raise ValueError("archive is behind the exchange session")
        params = {"start_date": iso_day, "end_date": iso_day, "page_size": 1000}
        trades: list[dict] = []
        read = 0
        other_markets: dict[str, int] = defaultdict(int)
        expected = pages = page_size = None
        first = None
        for page in range(1, max_pages + 1):
            payload = _json_get(client, "/iuzse/trade-results/", {**params, "page": page})
            batch = payload["results"]
            if first is None:
                first = payload
                expected, pages, page_size = (int(payload[k]) for k in
                                              ("count", "total_pages", "page_size"))
                if expected <= 0 or page_size <= 0 or not 1 <= pages <= max_pages:
                    raise ValueError("invalid archive session pagination")
                if pages != math.ceil(expected / page_size):
                    raise ValueError("archive page count disagrees with record count")
            if (payload["count"] != expected or payload["total_pages"] != pages
                    or payload["page_size"] != page_size or payload["current_page"] != page
                    or payload["has_next"] is not (page < pages)
                    or not isinstance(batch, list)
                    or len(batch) != min(page_size, expected - read)):
                raise ValueError("archive session changed or a page is incomplete")
            read += len(batch)
            for record in batch:
                item = dict(record, issue_code=str(record["isin_code"]).strip().upper(),
                            trade_date=day)
                # The archive carries every market the exchange runs. REPO deals
                # (`RPO`) are financing, not board trades, and two of them on
                # 28.09 made the whole session look corrupt, so nothing was
                # published. A named market off the board is skipped; a missing
                # one is still a broken record.
                market = str(item.get("market_id") or "")
                if market and market not in {"STK", "BND"}:
                    other_markets[market] += 1
                    continue
                if (not item["issue_code"] or not item.get("board_id")
                        or item.get("market_id") not in {"STK", "BND"}
                        or ts.trade_moment(item) is None):
                    raise ValueError("archive execution has no valid identity/date/market")
                for field in ("trade_price", "trade_quantity", "trading_value"):
                    item[field] = _number(item[field])
                    if item[field] <= 0:
                        raise ValueError("archive execution has a non-positive value")
                trades.append(item)
            if page == pages:
                break
        check = _json_get(client, "/iuzse/trade-results/", {**params, "page": 1})
        # A pinned older session cannot be the one still being written, so only
        # the newest has to still be the newest when the read ends.
        if check != first or read != expected or (not session_day and _latest_day(client) != iso_day):
            raise ValueError("archive session changed while being read")
        if not trades:
            raise ValueError("archive session has no board executions")
        if other_markets:
            log.info("OpenInfo fallback: skipped executions off the board: %s",
                     ", ".join(f"{k} {v}" for k, v in sorted(other_markets.items())))
        grouped: dict[str, list] = defaultdict(list)
        for trade in trades:
            grouped[trade["issue_code"]].append(trade)
        stats = {isin: ts._aggregate(isin, rows, day) for isin, rows in grouped.items()}
        quotes = fetch_quotes([(isin, row["market"]) for isin, row in stats.items()],
                              session=client, as_of=iso_day)
        quoted = {row["isin"]: row for row in quotes}
        for isin, row in stats.items():
            if not row["trade_count"]:
                continue  # negotiated trades have no auction close
            quote = quoted.get(isin) or {}
            if quote.get("trade_date") != day:
                raise ValueError(f"archive conclusions lag executions for {isin}")
            for quote_key, stats_key in (("quantity", "total_qty"), ("turnover", "total_value")):
                if not math.isclose(quote[quote_key], row[stats_key], rel_tol=1e-9, abs_tol=.02):
                    raise ValueError(f"archive conclusions disagree with executions for {isin}")
            for field in ("high_price", "low_price"):
                if quote[field] is None or not math.isclose(quote[field], row[field], rel_tol=1e-7, abs_tol=.01):
                    raise ValueError(f"archive price range disagrees with executions for {isin}")
            for field in ("open_price", "close_price"):
                if quote[field] is None or not row["low_price"] - .01 <= quote[field] <= row["high_price"] + .01:
                    raise ValueError(f"archive {field} is outside the execution range for {isin}")
            # Simultaneous auction trades lack IDs in this archive. The official
            # daily conclusion resolves their order; arbitrary row order cannot.
            for field in ("open_price", "close_price", "high_price", "low_price"):
                row[field] = quote[field]
        log.info("OpenInfo fallback: %s complete, %d executions, %d securities",
                 day, len(trades), len(stats))
        return {"source": "openinfo", "reachable": True, "complete": True,
                "trade_date": day, "count": len(stats), "stats": stats,
                # Without execution IDs tied timestamps cannot give reliable
                # hourly opens/closes. Preserve existing bars; daily history is
                # updated from authoritative conclusions instead.
                "intraday": [], "quotes": quotes}
    except Exception:
        log.exception("OpenInfo market session unavailable or incomplete; nothing published")
        return failure


# A year of closes is what the board needs from almost every security; ten years
# is only for one that has not traded in a year. Asking for ten up front sent the
# whole decade for all ~120 board securities on every run.
_QUOTE_LOOKBACK_DAYS = (400, 3650)


def fetch_quotes(targets: list[tuple[str, str]], *, session: Any = None,
                 as_of: str | None = None) -> list[dict]:
    """Official daily closes, ranges and history, retaining actual trading dates.

    This path makes no requests to the unavailable exchange. The endpoint is
    ISIN-filtered and supplies its issuer identity along with daily conclusions.
    ``as_of`` (YYYY-MM-DD) ends the read on that session, so a pinned older
    session is quoted as it closed, not with a later day's close.
    """
    client = session or _make_session()
    today = datetime.now(TASHKENT).date()
    end = min(date.fromisoformat(as_of), today) if as_of else today
    rows = []
    for isin, market in targets:
        try:
            for lookback in _QUOTE_LOOKBACK_DAYS:
                # openinfo's end_date is EXCLUSIVE: end_date=2026-09-28 stops at
                # 25.09. Ask one day past the session; later days are dropped below.
                payload = _json_get(client, "/iuzse/conclusions/", {
                    "isu_cd": isin, "start_date": (end - timedelta(days=lookback)).isoformat(),
                    "end_date": (end + timedelta(days=1)).isoformat(),
                })
                payload["results"] = [p for p in payload.get("results") or []
                                      if str(p.get("date") or "") <= end.isoformat()]
                if any(_number(p.get("trading_volume") or 0) > 0 for p in payload.get("results") or []):
                    break
            points = payload["results"]
            if not isinstance(points, list):
                raise ValueError("invalid archive conclusions")
            history = []
            traded = []
            for index, point in enumerate(sorted(points, key=lambda p: p["date"], reverse=True)):
                day = date.fromisoformat(point["date"])
                close = _number(point["close"])
                if day > end or close <= 0:
                    if index == 0:
                        raise ValueError("invalid archive latest quote date/close")
                    continue  # historical zero placeholders are not prices
                item = {"date": day.strftime("%Y%m%d"), "close": close,
                        "change": _number(point["change"]) if point.get("change") is not None else None,
                        "quantity": _number(point["trading_volume"]),
                        "turnover": _number(point["trading_value"])}
                history.append(item)
                if item["quantity"] > 0:
                    traded.append((item, point))
            if not traded:
                continue
            latest, point = max(traded, key=lambda pair: pair[0]["date"])
            close, change = latest["close"], latest["change"]
            previous = close - change if change is not None else None
            row = {"isin": isin, "market": market, "ticker": payload.get("ticker"),
                   "name": payload.get("name"), "trade_date": latest["date"],
                   "close_price": close, "prev_close": previous, "change_value": change,
                   "change_percent": round(change / abs(previous) * 100, 4)
                   if previous and change is not None else None,
                   "quantity": latest["quantity"], "turnover": latest["turnover"],
                   "history": sorted(history, key=lambda h: h["date"])[-21:]}
            for target, source in (("open_price", "open"), ("high_price", "high"), ("low_price", "low")):
                row[target] = _number(point[source]) if point.get(source) is not None else None
            rows.append(row)
        except Exception:
            log.exception("OpenInfo quote %s unavailable; keeping its stored quote", isin)
    return rows
