"""Financials trading operations with explicit dependencies."""
from __future__ import annotations

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.history as collectors_financials_history
import collectors.financials.market as collectors_financials_market
import collectors.financials.retry as collectors_financials_retry
import collectors.financials.settings as collectors_financials_settings
import os
import time
import trade_stats as ts
import uzse_access
from collectors.openinfo import market_fallback as archive_market

# --session-date / MARKET_SESSION_DATE: publish this finished openinfo session
# (YYYY-MM-DD) instead of the newest one.
SESSION_DATE: str | None = os.getenv("MARKET_SESSION_DATE") or None


def _published_session() -> tuple[str | None, str | None]:
    """(session prod's board holds, newest session it holds OFFICIALLY).

    The first is set when BOTH its steps landed it; the second is the newest
    session published from openinfo's daily conclusions rather than provisionally
    from the executions. Read from the deployment's own step stamps
    (/api/coverage), not from openinfo. None when unreadable — nothing is skipped.
    """
    import requests

    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    try:
        steps = (requests.get(f"{base}/api/coverage", timeout=30).json()
                 .get("collector", {}).get("steps", {}))
    except Exception:  # noqa: BLE001 — unknown means "publish"
        collectors_financials_settings.log.warning("published session unknown; running in full", exc_info=True)
        return None, None
    stats = str((steps.get("trade_stats") or {}).get("last_day") or "")
    quotes = str((steps.get("quotes") or {}).get("last_day") or "")
    held = stats if len(stats) == 8 and stats.isdigit() and stats == quotes else None
    # Before provisional sessions existed every published one was official, and
    # such a deployment carries no official_quotes stamp at all.
    official = str((steps.get("official_quotes") or {}).get("last_day") or "") or held
    return held, official


def _session_to_publish() -> str:
    """"published", "not yet" or "go" — decided in one or two openinfo requests.

    A run with nothing to do re-read the whole session and every security's
    quote (~80-320 requests) only to stop or to push the same numbers again:
    01.10's 16:10 run re-pushed an unchanged 30.09. So first ask openinfo for
    its newest session. openinfo posts a day's conclusions only overnight, but
    its executions are whole at the close, so a finished session is published
    provisionally from them (16:10) and again officially once the conclusions
    are there (the next morning). Hence:

      * prod holds it officially, or provisionally with no conclusions yet to
        replace it: stop ("published");
      * no conclusions and the session is still trading: stop ("not yet");
      * otherwise "go". Any doubt: "go".
    """
    published, official = _published_session()
    try:
        newest = archive_market.latest_session()
        posted = archive_market.conclusions_posted(newest)
        if newest == published and (official == newest or not posted):
            collectors_financials_settings.log.info(
                "session %s is already published%s — nothing to do", newest,
                "" if official == newest else " (provisionally; conclusions not posted yet)")
            return "published"
        if not posted and not archive_market._session_finished(
                f"{newest[:4]}-{newest[4:6]}-{newest[6:]}"):
            collectors_financials_settings.log.error(
                "session %s is still trading — nothing published", newest)
            return "not yet"
    except Exception:  # noqa: BLE001
        collectors_financials_settings.log.warning("openinfo's newest session unknown; running in full",
                                                   exc_info=True)
    return "go"


def push_trade_stats() -> int:
    """Fetch the latest-day per-trade stats and push to prod.

    From uzse.uz when it is switched on, else straight from openinfo's archive.
    openinfo gets ONE attempt: when its session is not there yet it is hours
    behind, not minutes, and re-walking it every five minutes only multiplies
    the requests — the next scheduled run is the retry.
    """
    exchange = uzse_access.enabled() and not SESSION_DATE
    if not exchange and not SESSION_DATE:
        ready = _session_to_publish()
        if ready == "published":
            return collectors_financials_market.audit_board()
        if ready == "not yet":
            return 1
    attempts = collectors_financials_retry.RETRY_ATTEMPTS if exchange else 1
    for attempt in range(1, attempts + 1):
        if exchange:
            collectors_financials_settings.log.info("fetching UZSE trade stats (latest day) ...")
            data = ts.fetch_trade_stats()
        else:
            data = {}
        if not (data.get("reachable") and data.get("complete")):
            if exchange:
                collectors_financials_settings.log.warning("UZSE unavailable/incomplete; trying OpenInfo")
            data = archive_market.fetch_latest_trade_stats(min_day=data.get("trade_date"),
                                                           session_day=SESSION_DATE)
        stats = data.get("stats") or {}
        rows = list(stats.values())
        collectors_financials_settings.log.info("trade stats: %d securities for %s", len(rows), data.get("trade_date"))
        if data.get("reachable") and data.get("complete"):
            break
        # A short read is a session with real ISINs and understated turnover, and
        # the board cannot tell it from a quiet day — so it is retried, not
        # published, exactly like a feed that never answered.
        why = ("the trade feed did not answer" if not data.get("reachable")
               else f"the trade feed stopped mid-session with {len(rows)} securities")
        if attempt >= attempts or not collectors_financials_retry._wait_and_retry(attempt, why):
            collectors_financials_settings.log.error("%s — giving up after %d attempts", why, attempt)
            return 1
    if not rows:
        # The feed is a two-day window, so a Monday-morning run reads Sat+Sun and
        # the exchange truthfully answers "nothing traded". Nothing to push and
        # nothing wrong: the stored session stays the newest one there is, and the
        # audit below still asserts it is coherent.
        collectors_financials_settings.log.info("the exchange published no session in the feed's window — "
                 "keeping the stored session")
        return collectors_financials_market.audit_board()
    # Board rows whose security did not trade today otherwise show dashes in
    # the qty/avg-price/avg-trade/largest columns forever, even though their
    # price/OHLC columns already display the LAST trading day. Backfill that
    # same day's stats from openinfo's trade-results archive so the whole row
    # is coherently "as of the last trade date".
    try:
        board_rows = collectors_financials_market.board_securities()
        targets = []
        seen: set[str] = set()
        no_date: list[str] = []
        for r in board_rows:
            isin = str(r.get("isin") or "").strip().upper()
            if not isin or isin in stats or isin in seen:
                continue
            seen.add(isin)
            day = str(r.get("last_trade_date") or "").strip()
            if day:
                targets.append((isin, day))
            else:
                no_date.append(isin)
        # The live feed reports last_trade_date=null for some securities that
        # DID trade (e.g. FRAZP, UZML) — recover the day from the conclusions
        # archive; securities with genuinely no history are skipped.
        if no_date:
            import listings_collector as lc
            from collectors.openinfo.transport import _make_session
            session = _make_session()
            for isin in no_date:
                last = lc._last_conclusion(session, isin)
                day = str((last or {}).get("date") or "").strip()
                if day:
                    targets.append((isin, day))
        if targets:
            collectors_financials_settings.log.info("backfilling last-day stats for %d untraded securities ...", len(targets))
            back = ts.backfill_last_day_stats(targets)
            collectors_financials_settings.log.info("backfilled %d securities", len(back))
            rows.extend(back)
    except Exception:
        collectors_financials_settings.log.exception("last-day stats backfill failed (pushing today's only)")
    status = collectors_financials_delivery._post("/api/admin/trade-stats", {"trade_date": data.get("trade_date"), "rows": rows})
    if status == 0:
        collectors_financials_delivery._stamp_step("trade_stats", str(data.get("trade_date") or ""))
    # Hourly bars for the 1Д/1Н chart, rolled up from the SAME walked executions
    # (negotiated T1 deals already excluded by trade_stats.hourly_bars). Failure
    # is logged, not fatal: the day statistics are what this step exists for.
    bars = data.get("intraday") or []
    if bars:
        try:
            if collectors_financials_delivery._post("/api/admin/quotes", {"rows": [], "history": [], "intraday": bars}):
                collectors_financials_settings.log.error("intraday bars push failed (%d bars)", len(bars))
            else:
                collectors_financials_settings.log.info("intraday: %d hourly bars pushed for %s", len(bars), data.get("trade_date"))
        except Exception:
            collectors_financials_settings.log.exception("intraday bars push failed")
    if not collectors_financials_market.SKIP_QUOTES:
        try:
            if data.get("source") == "openinfo":
                status = collectors_financials_market.push_quotes(
                    stats, source="openinfo", archive_quotes=data.get("quotes")) or status
            else:
                status = collectors_financials_market.push_quotes(stats) or status
        except Exception:
            collectors_financials_settings.log.exception("quotes step failed")
            status = status or 1
    if status == 0 and not data.get("provisional") and not collectors_financials_market.SKIP_QUOTES:
        # The session now stands on the exchange's own daily figures; a
        # provisional one (from the executions) is published again over itself.
        collectors_financials_delivery._stamp_step("official_quotes", str(data.get("trade_date") or ""))
    return status


def push_live_bars() -> int:
    """Refresh the 1Д/1Н chart's hourly bars from today's session so far.

    One openinfo request per run (the hourly timer during trading). Only the
    bars move: the board's day statistics wait for the close — the 16:10 run
    publishes them provisionally from the executions, the next morning's run
    officially from the conclusions.
    """
    bars = archive_market.fetch_live_bars()
    if bars is None:
        return 1
    if not bars:
        collectors_financials_settings.log.info("live bars: nothing traded today yet")
        return 0
    status = collectors_financials_delivery._post("/api/admin/quotes",
                                                  {"rows": [], "history": [], "intraday": bars})
    if status:
        collectors_financials_settings.log.error("live bars: push of %d hourly bars failed", len(bars))
    else:
        collectors_financials_settings.log.info("live bars: %d hourly bars for %s pushed",
                                                len(bars), bars[0]["date"])
    return status

def backfill_intraday(days: int = 30) -> int:
    """One-off: bank hourly bars for the last ``days`` calendar days.

    The exchange's trade feed honours begin/end months back when date-filtered
    (the two-day window is only what the unfiltered view shows), so the hourly
    series does not have to start the day the collector first ran. Idempotent:
    every bar upserts on (isin, day, hour), and a day that cannot be walked
    COMPLETELY is skipped rather than pushed short — understated volumes over
    correct ones would be the worse outcome.
    """
    from datetime import date, timedelta

    session = None
    status = 0
    total = 0
    for offset in range(days, -1, -1):
        when = date.today() - timedelta(days=offset)
        day = when.strftime("%Y%m%d")
        if not uzse_access.enabled():
            # openinfo's archive instead of uzse.uz's feed; a Sunday is known
            # to be empty without asking.
            if when.weekday() == 6:
                continue
            bars = archive_market.fetch_session_bars(when.isoformat())
            if bars is None:
                collectors_financials_settings.log.error("intraday backfill: %s could not be read completely — skipped", day)
                status = 1
                continue
        else:
            trades = ts.fetch_day_trades(day, session=session)
            if trades is None:
                collectors_financials_settings.log.error("intraday backfill: %s could not be walked completely — skipped", day)
                status = 1
                continue
            if not trades:
                continue  # a weekend or holiday, not a failure
            bars = ts.hourly_bars(trades)
        collectors_financials_settings.log.info("intraday backfill %s: %d hourly bars", day, len(bars))
        if bars:
            status = collectors_financials_delivery._post("/api/admin/quotes",
                           {"rows": [], "history": [], "intraday": bars}) or status
            total += len(bars)
    collectors_financials_settings.log.info("intraday backfill: %d bars pushed across %d days", total, days + 1)
    return status


def backfill_day_stats(days: int = 365) -> int:
    """One-off: bank per-session day STATISTICS for the last ``days`` days.

    The quote history has always carried closes; what it could not carry was the
    rest of a session — how many deals it was made of and the largest of them —
    because ``catalog_trade_stats`` keeps only the latest session and nothing
    banked the others. Without them a period can report a turnover and a percent
    and nothing else, which is exactly what the board did.

    Sourced per SECURITY from openinfo's execution archive, not from the
    exchange's own feed: date-filtered, that feed answers for the whole market at
    fifty records a page — one past session is 217 requests, ~18 minutes, so a
    year of history would take a year of walking. The archive filtered by ISIN
    serves a thousand records a page, and a year of even the busiest line is four
    requests. It is the same execution record, and it is the one that carries
    ``board_id`` for certain, which is what keeps negotiated deals out of a
    session's numbers.

    Aggregated by the same ``trade_stats._aggregate`` the live pass uses, so a
    banked session and a live one are the same numbers computed the same way.
    Idempotent: every session upserts on (isin, day) and NULLs never overwrite,
    so re-running only fills gaps.
    """
    from datetime import date, timedelta

    from collectors.openinfo.transport import _make_session

    end_day = date.today()
    start_day = end_day - timedelta(days=max(1, days))
    codes = sorted(collectors_financials_history._history_universe())
    session = _make_session()
    collectors_financials_settings.log.info("day-stats backfill: %d securities, %s..%s", len(codes), start_day, end_day)
    rows: list[dict] = []
    failed = 0
    for index, isin in enumerate(codes, 1):
        try:
            trades = ts.archive_executions(isin, start_day.isoformat(), end_day.isoformat(),
                                           session=session)
        except Exception:  # noqa: BLE001 — one unreadable code is not the run
            collectors_financials_settings.log.exception("day-stats backfill: %s unreadable", isin)
            failed += 1
            continue
        # Days made only of off-session deals (board T1/NC) are not sessions.
        sessions = [r for r in ts.aggregate_by_day(isin, trades)
                    if r.get("trade_count") or r.get("total_qty")]
        rows.extend(sessions)
        if index % 20 == 0:
            collectors_financials_settings.log.info("day-stats backfill: %d/%d codes, %d sessions so far",
                     index, len(codes), len(rows))
        time.sleep(0.25)
    collectors_financials_settings.log.info("day-stats backfill: %d sessions from %d codes (%d unreadable)",
             len(rows), len(codes) - failed, failed)
    if not rows:
        return 1
    # Pushed as quote HISTORY, not as the statistics cache: the cache holds the
    # latest session only and a past day must never replace it.
    # bulk_upsert_quote_history reads total_value/total_qty as the session's
    # turnover and quantity, so the aggregate goes over as it is.
    status = 0
    for start in range(0, len(rows), 5000):
        status = collectors_financials_delivery._post("/api/admin/quotes",
                       {"rows": [], "history": rows[start:start + 5000]}) or status
    return status
