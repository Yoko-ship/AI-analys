"""Upcoming shareholder-meeting announcements, market-wide.

openinfo publishes one *announcement calendar* for the whole market
(``/announcement/calendar/``): each row is an issuer's notice of a general
meeting, carrying the organization, the publication date and — the field the
news-page calendar exists for — the MEETING date, which lies in the future.
This is the one disclosure feed we hold nowhere else: the filings feed shows a
meeting after it happened; this one announces it.

The feed is ordered newest-published-first and reaches years back (~10 000
rows). Only a recent window is worth storing — a calendar of 2019 meetings is
an archive, not a calendar — so the snapshot keeps announcements published in
the last ``HORIZON_DAYS`` and paging stops at the first page that is entirely
older than that.

Ticker mapping reuses dividends.py's issuer universe: ``organization_id`` IS
the openinfo org id ``catalog_companies.org_id`` stores, and the row's own
``ticker`` field is the same free-text candidate it is on the dividend
calendar. Rows that map to no listed security are KEPT with a null ticker —
the market's calendar shows every issuer that filed a notice, and a name
without a link is still an event.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

CALENDAR_PATH = "/announcement/calendar/"
PAGE_SIZE = int(os.getenv("MEETINGS_PAGE_SIZE", "200"))
MAX_PAGES = int(os.getenv("MEETINGS_MAX_PAGES", "12"))
HORIZON_DAYS = int(os.getenv("MEETINGS_HORIZON_DAYS", "200"))
REFRESH_TTL_HOURS = int(os.getenv("MEETINGS_TTL_HOURS", "6"))

_REFRESH_LOCK = threading.Lock()
_REFRESH_RUNNING = threading.Event()
_last_refresh_attempt = 0.0


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

def fetch_calendar(
    session: requests.Session | None = None,
    *,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
    horizon_days: int = HORIZON_DAYS,
) -> list[dict[str, Any]]:
    """Announcements published within the horizon, newest first.

    Unlike the dividend calendar this is deliberately a WINDOW, not the whole
    feed: the endpoint is ordered by publication date, so the crawl stops at
    the first page whose every row is older than the horizon.
    """
    from openinfo_collector import _json_get, _make_session

    cutoff = (datetime.now(timezone.utc) - timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    client = session or _make_session()
    rows: list[dict[str, Any]] = []
    page = 1
    while page <= max_pages:
        payload = _json_get(client, CALENDAR_PATH, {"page": page, "page_size": page_size})
        if not isinstance(payload, dict):
            break
        batch = payload.get("results") or []
        fresh = [r for r in batch if str(r.get("pub_date") or "") >= cutoff]
        rows.extend(fresh)
        if not payload.get("next") or not batch or not fresh:
            break
        page += 1
    return rows


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def _clean_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "announcement_id": str(row.get("id") or "").strip() or None,
        "org_id": str(row.get("organization_id") or "").strip() or None,
        "organization": row.get("organization_name"),
        "title": row.get("title"),
        "meeting_date": _clean_date(row.get("meeting_date")),
        "pub_date": _clean_date(row.get("pub_date")),
    }


def map_rows(rows: list[dict[str, Any]], universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a ticker where the issuer is one we list; keep the row either way.

    One row per announcement — a meeting is an issuer-level event, so the
    ordinary line's ticker represents the issuer (the shortest listed ticker of
    the org, which is the ordinary line on this exchange's naming).
    """
    from dividends import _ticker_tokens

    pool = [e for e in universe if (e.get("type") or "stock") != "bond"]
    listed = {e["ticker"] for e in pool}
    by_org: dict[str, list[str]] = {}
    for entry in pool:
        if entry.get("org_id"):
            by_org.setdefault(str(entry["org_id"]), []).append(entry["ticker"])

    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        item = normalize_row(raw)
        if not item["announcement_id"] or not item["meeting_date"]:
            continue
        ticker = None
        candidates = by_org.get(item["org_id"] or "")
        if candidates:
            ticker = min(candidates, key=lambda t: (len(t), t))
        else:
            tokens = [t for t in _ticker_tokens(raw.get("ticker")) if t in listed]
            if tokens:
                ticker = min(tokens, key=lambda t: (len(t), t))
        item["ticker"] = ticker
        out[item["announcement_id"]] = item
    return sorted(out.values(), key=lambda r: str(r.get("meeting_date") or ""))


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_COLUMNS = ("announcement_id", "org_id", "organization", "ticker", "title",
            "meeting_date", "pub_date")

INSERT_CHUNK = int(os.getenv("MEETINGS_INSERT_CHUNK", "250"))


def replace_snapshot(records: list[dict[str, Any]]) -> int:
    """Swap the stored window for a fresh one — one transaction, chunked inserts
    (row-at-a-time on PostgreSQL is the round-trip cost model this codebase has
    already paid for once)."""
    from reports_catalog import get_catalog_conn

    row_sql = "(" + ",".join("?" * len(_COLUMNS)) + ", datetime('now'))"
    conn = get_catalog_conn()
    try:
        with conn:
            conn.execute("DELETE FROM catalog_meetings")
            for start in range(0, len(records), INSERT_CHUNK):
                chunk = records[start:start + INSERT_CHUNK]
                params: list[Any] = []
                for record in chunk:
                    params.extend(record.get(col) for col in _COLUMNS)
                conn.execute(
                    f"INSERT INTO catalog_meetings ({', '.join(_COLUMNS)}, updated_at) "
                    f"VALUES {', '.join([row_sql] * len(chunk))}",
                    params,
                )
    finally:
        conn.close()
    return len(records)


def read_window(start: str, end: str) -> list[dict[str, Any]]:
    """Stored announcements whose meeting date falls in [start, end)."""
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)}, updated_at FROM catalog_meetings "
            "WHERE meeting_date >= ? AND meeting_date < ? "
            "ORDER BY meeting_date, organization",
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def snapshot_state() -> dict[str, Any]:
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS announcements, MAX(updated_at) AS updated_at "
            "FROM catalog_meetings"
        ).fetchone()
    finally:
        conn.close()
    state = dict(row or {})
    from dividends import _age_hours

    state["age_hours"] = _age_hours(state.get("updated_at"))
    return state


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def refresh(*, force: bool = False) -> dict[str, Any]:
    """Re-read the announcement window and rewrite the snapshot. Serialised."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": "already running"}
    _REFRESH_RUNNING.set()
    try:
        state = snapshot_state()
        age = state.get("age_hours")
        if not force and state.get("announcements") and age is not None and age < REFRESH_TTL_HOURS:
            return {"ok": True, "skipped": "fresh", **state}

        from dividends import attach_org_ids, build_universe

        rows = fetch_calendar()
        universe = attach_org_ids(build_universe(), use_index=False)
        records = map_rows(rows, universe)
        stored = replace_snapshot(records)
        mapped = sum(1 for r in records if r.get("ticker"))
        logger.info(
            "meetings snapshot: %d announcements from openinfo -> %d stored, %d with a ticker",
            len(rows), stored, mapped,
        )
        return {"ok": True, "read": len(rows), "records": stored, "mapped": mapped}
    finally:
        _REFRESH_RUNNING.clear()
        _REFRESH_LOCK.release()


def refresh_in_background(*, force: bool = False) -> bool:
    """Kick a refresh off a request thread, at most one attempt per minute."""
    global _last_refresh_attempt
    if _REFRESH_RUNNING.is_set():
        return False
    now = time.time()
    if not force and now - _last_refresh_attempt < 60:
        return False
    _last_refresh_attempt = now

    def _run() -> None:
        try:
            refresh(force=force)
        except Exception:  # noqa: BLE001 — a background refresh may not kill the app
            logger.exception("meetings background refresh failed")

    threading.Thread(target=_run, name="meetings-refresh", daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# Read path
# ---------------------------------------------------------------------------

def meetings_for(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """One month of the meetings calendar, warming the snapshot as needed.

    A cold (empty) snapshot is filled synchronously — the crawl is a handful of
    paced pages, and an empty calendar teaches the first visitor the feature is
    broken; a merely stale one refreshes in the background.
    """
    today = datetime.now(timezone.utc)
    y = year or today.year
    m = month or today.month
    if not (1 <= m <= 12) or not (2000 <= y <= 2100):
        raise ValueError(f"not a calendar month: {y}-{m}")
    start = f"{y:04d}-{m:02d}-01"
    end = f"{y + 1:04d}-01-01" if m == 12 else f"{y:04d}-{m + 1:02d}-01"

    state = snapshot_state()
    if not state.get("announcements"):
        try:
            refresh(force=True)
            state = snapshot_state()
        except Exception:  # noqa: BLE001 — openinfo down must not 500 the page
            logger.exception("meetings cold refresh failed")
    else:
        age = state.get("age_hours")
        if age is None or age >= REFRESH_TTL_HOURS:
            refresh_in_background()

    items = read_window(start, end)
    return {
        "ok": True,
        "year": y,
        "month": m,
        "count": len(items),
        "items": items,
        "as_of": state.get("updated_at"),
    }


if __name__ == "__main__":  # pragma: no cover — operational entry point
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Refresh the meetings snapshot")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--month", help="print one month (YYYY-MM) and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.month:
        y, m = args.month.split("-")
        print(json.dumps(meetings_for(int(y), int(m)), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(refresh(force=args.force), ensure_ascii=False, indent=2))
