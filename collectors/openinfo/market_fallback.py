"""Validated UZSE market data from OpenInfo when the exchange is unreachable."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import logging
import math
import statistics
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


def latest_session(*, session: Any = None) -> str:
    """The archive's newest session as YYYYMMDD — one request."""
    return _latest_day(session or _make_session()).replace("-", "")


def conclusions_posted(day: str, *, session: Any = None) -> bool:
    """Whether openinfo holds the day's conclusions yet — one request for all securities.

    ``isu_cd=""`` answers every security's conclusion for the dates asked
    (73 rows for 30.09). end_date is exclusive, so ask one day past.
    """
    iso = date.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 else day)
    payload = _json_get(session or _make_session(), "/iuzse/conclusions/", {
        "isu_cd": "", "start_date": iso.isoformat(), "end_date": (iso + timedelta(days=1)).isoformat()})
    return any(str(p.get("date")) == iso.isoformat() for p in payload.get("results") or [])


def _board_execution(record: dict, day: str) -> dict | None:
    """One archive record as a board execution; None off the board; ValueError if broken.

    The archive carries every market the exchange runs. REPO deals (`RPO`)
    are financing, not board trades, and two of them on 28.09 made the whole
    session look corrupt, so nothing was published. A named market off the
    board is skipped; a missing one is still a broken record.
    """
    item = dict(record, issue_code=str(record["isin_code"]).strip().upper(), trade_date=day)
    market = str(item.get("market_id") or "")
    if market and market not in {"STK", "BND"}:
        return None
    if (not item["issue_code"] or not item.get("board_id")
            or item.get("market_id") not in {"STK", "BND"}
            or ts.trade_moment(item) is None):
        raise ValueError("archive execution has no valid identity/date/market")
    for field in ("trade_price", "trade_quantity", "trading_value"):
        item[field] = _number(item[field])
        if item[field] <= 0:
            raise ValueError("archive execution has a non-positive value")
    return item


class NoSession(ValueError):
    """The archive holds no executions on that day: a holiday or a day off."""


def _read_executions(client: Any, iso_day: str, *, still_newest: bool,
                     max_pages: int = 100) -> list[dict]:
    """Every board execution of one session, or ValueError — never a short read.

    Pin the session before pagination; require the advertised count on every
    page and recheck it afterwards. Preserve identical executions: the archive
    has no execution IDs, and separate auction trades can share every visible
    field. Deduplicating those would understate actual volume. ``still_newest``
    also requires the session to still be the archive's newest when the read
    ends — a pinned older one cannot be the session still being written.
    """
    day = iso_day.replace("-", "")
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
            if expected == 0 and not still_newest:
                raise NoSession(iso_day)
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
            item = _board_execution(record, day)
            if item is None:
                other_markets[str(record.get("market_id"))] += 1
            else:
                trades.append(item)
        if page == pages:
            break
    check = _json_get(client, "/iuzse/trade-results/", {**params, "page": 1})
    if check != first or read != expected or (still_newest and _latest_day(client) != iso_day):
        raise ValueError("archive session changed while being read")
    if not trades:
        raise ValueError("archive session has no board executions")
    if other_markets:
        log.info("OpenInfo fallback: skipped executions off the board: %s",
                 ", ".join(f"{k} {v}" for k, v in sorted(other_markets.items())))
    return trades


def fetch_latest_trade_stats(*, min_day: str | None = None, session: Any = None,
                             max_pages: int = 100, session_day: str | None = None) -> dict:
    """Return a complete, stable session or an explicit failure with no rows.

    ``session_day`` (YYYY-MM-DD) publishes that finished session instead of the
    newest one — the newest is often still being written (trading, or openinfo
    not yet holding its daily conclusions), and an operator may need the one
    before it now rather than at 21:30.

    The executions are read by ``_read_executions``; the official daily
    conclusions then have to agree with them before anything is returned.
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
        trades = _read_executions(client, iso_day, still_newest=not session_day,
                                  max_pages=max_pages)
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
                "intraday": session_bars(trades, {
                    (isin, day): (row.get("open_price"), row.get("close_price"))
                    for isin, row in stats.items()}),
                "quotes": quotes}
    except Exception:
        log.exception("OpenInfo market session unavailable or incomplete; nothing published")
        return failure


def _nearest(prices: list[float], anchor: float | None) -> float:
    """The tied price closest to ``anchor``; the lower one on a draw."""
    if anchor is None:
        return statistics.median_low(prices)
    return min(prices, key=lambda p: (abs(p - anchor), p))


def session_bars(trades: list[dict], anchors: dict[tuple[str, str], tuple]) -> list[dict]:
    """Hourly bars for the 1Д/1Н chart from the archive's executions.

    ``trade_stats.hourly_bars`` builds them exactly as it does from uzse.uz's
    feed. The one thing the archive lacks is uzse's trade number: an hour that
    opens or closes with several executions in the same millisecond at
    different prices does not say which came first (7–8 % of bars on 29–30.09;
    the tied prices sit a median 0,2 % apart, 3,6 % at the 90th percentile).
    Such an edge takes one of its own tied prices — a real execution, never an
    average: the day's first open and last close come from the official
    conclusion (``anchors``: (isin, YYYYMMDD) -> (open, close)); an hour in
    between opens nearest the previous hour's close and closes nearest the
    next hour's opening executions. High, low, quantity and turnover are exact.
    """
    bars = ts.hourly_bars(trades)
    edges: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for trade in trades:
        if ts._is_block(trade):
            continue
        day, hour, stamp = ts.trade_moment(trade)
        edges[(trade["issue_code"], day, hour)][stamp[0]].append(trade["trade_price"])
    series: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for bar in bars:
        series[(bar["isin"], bar["date"])].append(bar)
    for key, day_bars in series.items():
        day_bars.sort(key=lambda b: b["hour"])
        day_open, day_close = anchors.get(key) or (None, None)
        for i, bar in enumerate(day_bars):
            stamps = edges[(bar["isin"], bar["date"], bar["hour"])]
            opening, closing = stamps[min(stamps)], stamps[max(stamps)]
            if len(set(opening)) > 1:
                bar["open"] = _nearest(opening, day_open if i == 0 else day_bars[i - 1]["close"])
            if len(set(closing)) > 1:
                if i == len(day_bars) - 1:
                    anchor = day_close
                else:
                    later = edges[(bar["isin"], bar["date"], day_bars[i + 1]["hour"])]
                    anchor = statistics.median(later[min(later)])
                bar["close"] = _nearest(closing, anchor)
    return bars


def fetch_session_bars(iso_day: str, *, session: Any = None) -> list[dict] | None:
    """Hourly bars of one finished session (the intraday backfill), or None.

    One conclusions read per security traded that day supplies the day's open
    and close for the tied edges. None when the day cannot be read completely
    — a partial day would upsert understated volumes over correct bars.
    """
    client = session or _make_session()
    day = iso_day.replace("-", "")
    try:
        trades = _read_executions(client, iso_day, still_newest=False)
    except NoSession:
        return []
    except Exception:
        log.exception("OpenInfo bars: session %s unreadable", iso_day)
        return None
    # Only a security whose day opens or closes on a tie needs its conclusion
    # (a handful a day), not every security that traded.
    edges: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for trade in trades:
        if not ts._is_block(trade):
            edges[trade["issue_code"]][ts.trade_moment(trade)[2][0]].add(trade["trade_price"])
    tied = sorted(isin for isin, stamps in edges.items()
                  if len(stamps[min(stamps)]) > 1 or len(stamps[max(stamps)]) > 1)
    anchors = {}
    for quote in fetch_quotes([(isin, "") for isin in tied], session=client, as_of=iso_day):
        if quote.get("trade_date") == day:
            anchors[(quote["isin"], day)] = (quote.get("open_price"), quote.get("close_price"))
    return session_bars(trades, anchors)


# One request reads the session so far: the archive answers page_size=10000
# for a whole day (8 270 executions on 30.09). A live session read page by page
# would shift under us as trades arrive — newest first, so every page would
# repeat the executions pushed down from the one before.
_LIVE_PAGE = 10000


def fetch_live_bars(*, session: Any = None) -> list[dict] | None:
    """Hourly bars of TODAY's session so far, from one archive request.

    The archive receives executions within seconds of the trade (02.10:
    10:39:33 visible at 10:39:30 + 3 s), while the day's conclusions come only
    after the close — so these bars carry no official day open/close, and a
    tied first open or last close takes the lower-median of its tied prices.
    The evening run rebuilds the whole day with the conclusions over them.
    The hour still in progress is partial and is upserted again next run.
    [] when nothing has traded today; None when the read is not usable.
    """
    client = session or _make_session()
    today = datetime.now(TASHKENT).date().isoformat()
    day = today.replace("-", "")
    try:
        payload = _json_get(client, "/iuzse/trade-results/", {
            "start_date": today, "end_date": today, "page": 1, "page_size": _LIVE_PAGE})
        records = payload["results"]
        if int(payload["count"]) == 0:
            return []
        if int(payload["count"]) != len(records) or payload.get("has_next"):
            raise ValueError(f"live read is not the whole session ({len(records)} of {payload['count']})")
        trades = [t for t in (_board_execution(r, day) for r in records) if t is not None]
    except Exception:
        log.exception("OpenInfo live bars: today's executions unusable; bars left as they are")
        return None
    return session_bars(trades, {})


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
