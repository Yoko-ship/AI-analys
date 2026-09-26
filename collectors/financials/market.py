"""Financials market operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.instruments as collectors_financials_instruments
import collectors.financials.retry as collectors_financials_retry
import collectors.financials.settings as collectors_financials_settings
import os
import requests


def board_securities() -> list[dict]:
    """Every row the deployment is serving on the market board.

    The collector's own database is a scratch copy rebuilt from nothing on each
    run, so asking IT which securities exist answers "none" — which is why the
    quote pass's backfill list, written against the local securities catalog,
    has always come back empty on Railway and nine board rows kept showing no
    price. The deployment is the only place that knows what the site serves.
    """
    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")
    rows: list[dict] = []
    for kind in ("stock", "bond"):
        board = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60).json()
        for row in (board if isinstance(board, list) else board.get("stocks") or []):
            row["_market"] = "BND" if kind == "bond" else "STK"
            rows.append(row)
    return rows


SKIP_QUOTES = False


def quotes_from_archive(targets: list[tuple[str, str]]) -> list[dict]:
    """The exchange's execution record for securities its page cannot date.

    uzse.uz publishes about twenty-one sessions of daily closes, so a security
    whose last trade is older than that falls out of the page entirely — and its
    header field can be wrong where the trade record is not. Kapitalbank is the
    case that found this: the page heads KPBA with "23.02.2024 — 1 030" while its
    own carried-forward close reads 5 284.8, and openinfo's execution archive
    records the trade of 23.02.2024 as 418 shares at 5 284.8. Two sources agree
    against the third, and the board was publishing the third — a market cap 5.13
    times too small.

    Only securities the page could not quote reach here, and the row is dated the
    session it describes, so the forward-only upsert cannot let an archived trade
    displace a live one.
    """
    import listings_collector as lc
    import uzse_quotes as uq
    from collectors.openinfo.transport import _make_session

    def _num(v):
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    session = _make_session()
    exchange = uq._session()
    rows: list[dict] = []
    registry_silent = 0
    for isin, market in targets:
        point = lc._last_conclusion(session, isin)
        day = str((point or {}).get("date") or "").replace("-", "")
        close = _num((point or {}).get("close"))
        if len(day) != 8 or close is None:
            continue
        change = _num(point.get("change"))
        prev = close - change if change is not None else None
        row = {
            "isin": isin, "market": market, "trade_date": day,
            "close_price": close,
            "prev_close": prev,
            "change_value": change,
            "change_percent": round(change / abs(prev) * 100, 4) if (prev and change is not None) else None,
            "open_price": _num(point.get("open")),
            "high_price": _num(point.get("high")),
            "low_price": _num(point.get("low")),
            "quantity": _num(point.get("trading_volume")),
            "turnover": _num(point.get("trading_value")),
        }
        # The name and the share count still come from the exchange's registry —
        # that record answers for a security whose quote page cannot. It is an
        # enrichment, so when uzse.uz stops answering we stop asking rather than
        # spend two minutes of retries per security on it; the board's own share
        # count stands and the price above is what this pass came for.
        detail = {} if registry_silent >= 3 else (uq.fetch_issue_detail(isin, session=exchange) or {})
        registry_silent = 0 if detail else registry_silent + 1
        for key in ("ticker", "name", "share_type", "nominal", "shares_outstanding"):
            if detail.get(key):
                row[key] = detail[key]
        if row.get("shares_outstanding"):
            row["market_cap"] = row["shares_outstanding"] * close
        rows.append(row)
        collectors_financials_settings.log.info("uzse quote %s: page cannot date it — archive says %s at %s",
                 isin, day, close)
    return rows


def push_quotes(stats: dict[str, dict], *, source: str = "uzse",
                archive_quotes: list[dict] | None = None) -> int:
    """Read the exchange's own quote for each security that traded, and push it.

    The board's change % is close-to-close against the exchange's previous close,
    and the exchange CARRIES that close forward through sessions with no trades —
    UQEQ closed at 25 600 on 30.07 without a single execution, so its +20% on
    31.07 exists in no execution feed and in no registry. Only the exchange's own
    security page states it.

    Every security the board serves is read, not only the ones that traded. The
    page answers for a quiet security too — the date it last traded, and that
    session's close, change, quantity and turnover, from its own daily history —
    and reading only the traded ones is what left nine rows priced at an em-dash
    while uzse.uz published a price for each of them. It is also what makes a
    finished session readable the next morning: by 08:00 the page's session table
    has rolled over to a day with no trades yet, and the history row is the only
    surviving statement of what yesterday actually closed at.
    """
    import uzse_quotes as uq

    traded = {
        (isin, str((row or {}).get("market") or "STK"))
        for isin, row in (stats or {}).items() if isin
    }

    listed: set[tuple[str, str]] = set()
    try:
        for row in board_securities():
            isin = str(row.get("isin") or "").strip().upper()
            if isin:
                listed.add((isin, str(row.get("_market") or "STK")))
    except Exception:  # noqa: BLE001 — this must never cost us the session
        collectors_financials_settings.log.warning("board security list unavailable", exc_info=True)

    targets = sorted(traded | listed)
    if not targets:
        collectors_financials_settings.log.warning("no traded securities to quote")
        return 0
    collectors_financials_settings.log.info("reading exchange quotes for %d securities (%d traded today) ...",
             len(targets), len(traded))
    quotes: list[dict] = []
    pending, settled, idle = list(targets), 0, 0
    if source == "openinfo":
        from collectors.openinfo.market_fallback import fetch_quotes
        quotes = list(archive_quotes or [])
        cached = {q["isin"] for q in quotes}
        quotes.extend(fetch_quotes([t for t in targets if t[0] not in cached]))
        # A delayed archive quote must not leave today's statistics beside an
        # older close while claiming the refresh completed successfully.
        dated = {q["isin"]: q["trade_date"] for q in quotes}
        missing = [isin for isin, row in stats.items()
                   if row.get("trade_count", 0) and dated.get(isin) != row.get("trade_date")]
        if missing:
            collectors_financials_settings.log.error("OpenInfo quotes lag executions for %s", ", ".join(missing))
            return 1
        pending = []
    for attempt in range(1, (collectors_financials_retry.RETRY_ATTEMPTS if source == "uzse" else 0) + 1):
        outcome: dict[str, Any] = {}
        answered = uq.fetch_session_quotes(pending, settle=True, outcome=outcome)
        quotes.extend(answered)
        settled += outcome.get("settled", 0)
        idle += outcome.get("idle", 0)
        collectors_financials_settings.log.info("quotes: %d of %d securities answered (%d live session, %d settled from "
                 "the exchange's history, %d silent, %d unreadable)",
                 len(quotes), len(targets), len(quotes) - settled, settled,
                 idle, outcome.get("unreadable", 0))
        # Only the pages that could not be READ are worth asking about again: a
        # page that answered "no session" answered.
        pending = list(outcome.get("unread") or [])
        if not pending or not collectors_financials_retry._wait_and_retry(
                attempt, f"{len(pending)} exchange pages unreadable"):
            break
    if not quotes:
        # Two different empties. Before the first execution of the day every page
        # reads 0/0/0 — the 08:00 run meets that every weekday, and refusing to
        # overwrite a real stored session with an empty one is the correct
        # behaviour, not a failed run. A page that could not be read at all is
        # the failure this return code is for.
        if pending:
            collectors_financials_settings.log.error("quotes: not one of %d pages could be read", len(targets))
            return 1
        collectors_financials_settings.log.info("quotes: the exchange has not opened a session yet "
                 "(%d pages idle) — keeping the stored quotes", idle)
        return audit_board()
    quoted = {str(q.get("isin") or "").upper() for q in quotes}
    unquoted = [t for t in targets if t[0] not in quoted]
    if unquoted and source == "uzse":
        try:
            archived = quotes_from_archive(unquoted)
            collectors_financials_settings.log.info("quotes: %d of %d unquoted securities recovered from the "
                     "execution archive", len(archived), len(unquoted))
            quotes.extend(archived)
        except Exception:  # noqa: BLE001 — a fallback must not cost us the session
            collectors_financials_settings.log.exception("archive quote fallback failed")

    # The exchange's quote page publishes its last ~21 SETTLED sessions in a
    # table below the current one, and every page fetched above already parsed
    # it. It used to be dropped here, so a daily close existed nowhere and a
    # sparkline cost one live openinfo request per ticker. It rides along on the
    # same POST — the history is already in hand, and a second request for data
    # we are holding would be the wasteful part.
    history: list[dict[str, Any]] = []
    for q in quotes:
        isin = str(q.get("isin") or "").upper()
        # Settled quote pages retain only the close. The completed execution
        # feed still has this session's open/high/low; never borrow another day.
        session_stats = (stats or {}).get(isin) or {}
        if q.get("trade_date") and session_stats.get("trade_date") == q["trade_date"]:
            for field in ("open_price", "high_price", "low_price"):
                if q.get(field) is None and session_stats.get(field) is not None:
                    q[field] = session_stats[field]
        for h in (q.pop("history", None) or []):
            day = str(h.get("date") or "").strip()
            if not isin or not day:
                continue
            history.append({"isin": isin, "trade_date": day, "close_price": h.get("close"),
                            "change_value": h.get("change"), "quantity": h.get("quantity"),
                            "turnover": h.get("turnover")})
    collectors_financials_settings.log.info("quotes: %d settled daily closes across %d securities", len(history), len(quotes))
    status = collectors_financials_delivery._post("/api/admin/quotes", {"rows": quotes, "history": history})
    if status == 0:
        # The newest session in the batch, not whichever row happened to be first:
        # a settled row is dated the day its security last traded, which for a
        # quiet one is months ago.
        collectors_financials_delivery._stamp_step("quotes", max((str(q.get("trade_date") or "") for q in quotes), default=""))
        status = audit_board() or status
    return status


def audit_board() -> int:

    """Ask the deployment whether its board agrees with the exchange, and say so.



    Every past mismatch was found by a human comparing our board to the exchange's

    bulletin, because a wrong number is still a number: nothing failed. This runs

    the same comparison in the pipeline, against what the site is serving right

    now, and turns a disagreement into a red run instead of a quiet week.

    """

    # The exchange can throttle or delay individual quote pages.  In that state

    # this cross-check is useful for investigation, but must not block a data

    # refresh that has already successfully written its source data.

    if os.getenv("MARKET_AUDIT_ENABLED", "0").strip().lower() not in {"1", "true", "yes", "on"}:

        collectors_financials_settings.log.info("market audit disabled")

        return 0



    import market_audit



    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")

    try:

        verdict = requests.get(f"{base}/api/market/audit", timeout=120).json()

    except Exception:

        collectors_financials_settings.log.exception("market audit request failed")

        return 1

    collectors_financials_settings.log.info("%s", market_audit.format_verdict(verdict))

    collectors_financials_delivery._stamp_step("market_audit", "ok" if verdict.get("ok") else "MISMATCH")

    if not verdict.get("ok"):

        failed = [c["name"] for c in verdict.get("checks") or [] if not c.get("ok")]

        collectors_financials_settings.log.error("the board disagrees with the exchange: %s", ", ".join(failed))

        return 1

    return 0


def push_listings() -> int:
    """Collect the RFB listing registry (openinfo) and push it to prod.

    Surfaces issuers that are listed on RFB Tashkent but missing from the live
    uzse-stock feed (no recent trades on the main board), so they still appear on
    the market board with their last-known price and market cap.
    """
    import listings_collector as lc

    collectors_financials_settings.log.info("collecting exchange-listing registry (openinfo info_rfb) ...")
    rows = lc.collect_listing_rows()
    collectors_financials_settings.log.info("listings: %d securities", len(rows))
    if not rows:
        collectors_financials_settings.log.warning("no listings collected")
        return 1
    status = collectors_financials_delivery._post("/api/admin/listings", {"rows": rows})
    # The bond issue reference rides on the same walk: the listing rows already
    # name every UZ6… ISIN, so filling the par value costs one request per bond
    # issuer and no second pass over openinfo.
    try:
        status = collectors_financials_instruments.push_bond_reference(rows) or status
    except Exception:  # noqa: BLE001 — a missing par must not fail the listings push
        collectors_financials_settings.log.exception("bond reference step failed")
    return status
