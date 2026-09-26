from __future__ import annotations



from typing import Any
import requests
import server.http as http
import server.settings as settings


def _as_utc_iso(value: Any) -> str | None:
    """Stamp a naive timestamp as UTC so the browser cannot misread it.

    Both clocks behind the board write naive strings. SQLite's `datetime('now')`
    is UTC by definition, and the uzse mirror stamps a UTC container: its
    /health advertises the schedule as `10:00:00+05:00` while the run it fired
    is stamped `05:30` — the same moment, five hours apart. A naive string
    reaches `new Date(...)` in the browser, which reads a zone-less ISO string
    as the READER's local time, so a Tashkent reader was shown 14:00 for data
    that was in fact five hours younger than that.
    """
    if not value:
        return None
    s = str(value).strip().replace(" ", "T")
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        return s[:-1] + "Z"
    # An explicit offset (+05:00 / -0500) already says what it means.
    tail = s[-6:]
    if len(s) > 6 and tail[0] in "+-" and tail[3] == ":" and tail[1:3].isdigit():
        return s
    tail5 = s[-5:]
    if len(s) > 5 and tail5[0] in "+-" and tail5[1:].isdigit():
        return s
    return s + "Z"


def _iso_trade_date(value: Any) -> str | None:
    """Normalise a last-trade date to YYYY-MM-DD.

    The three sources that know when a security last traded each state it
    differently — the RFB registry in ISO, the live UZSE feed as DD.MM.YYYY, the
    trade-stats cache as YYYYMMDD — and they are compared against each other and
    against a date cutoff, so they have to be reduced to one sortable form first.
    """
    s = str(value or "").strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return f"{s[6:]}-{s[3:5]}-{s[:2]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


def _live_last_trade_dates() -> dict[str, str]:
    """ticker → last trade date (ISO) as the live exchange feed reports it.

    The registry's own ``last_trade_date`` is missing for securities that trade
    perfectly normally — it is derived from openinfo's conclusions history, which
    is empty or stale for whole classes of line (ALKB, the microfinance bonds).
    Reading the exchange feed as well is what stops the delisting section from
    accusing a security that traded this morning. Best-effort: on a fetch failure
    the caller simply falls back to the registry, which is the older behaviour.

    Only evidence of an actual trade counts. ``close_date`` is the session the
    closing *quote* belongs to and the exchange carries it forward through days
    with no trading — FRAZP, MXUS, TRSBP and UZML all show yesterday's close_date
    with no volume while their last real trade was in June. So a close date is
    accepted only when the session also reports turnover.
    """
    out: dict[str, str] = {}
    if not settings.UZSE_STOCK_API_BASE:
        return out
    for security_type in (None, "bond"):
        try:
            resp = requests.get(
                f"{settings.UZSE_STOCK_API_BASE}/stocks",
                params={"type": security_type} if security_type else None,
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError):
            http.logger.warning("listings feed: live trade dates unavailable (type=%s)", security_type)
            continue
        rows = payload.get("stocks") if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            ticker = str(row.get("ticker") or "").strip().upper()
            date = _iso_trade_date(row.get("last_trade_date"))
            if not date and any(row.get(k) for k in ("volume", "quantity", "trade_count")):
                date = _iso_trade_date(row.get("close_date"))
            if ticker and date and date > out.get(ticker, ""):
                out[ticker] = date
    return out
