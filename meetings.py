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
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CALENDAR_PATH = "/announcement/calendar/"
PAGE_SIZE = int(os.getenv("MEETINGS_PAGE_SIZE", "200"))
MAX_PAGES = int(os.getenv("MEETINGS_MAX_PAGES", "12"))
HORIZON_DAYS = int(os.getenv("MEETINGS_HORIZON_DAYS", "200"))
REFRESH_TTL_HOURS = int(os.getenv("MEETINGS_TTL_HOURS", "6"))
DETAIL_TTL_SECONDS = int(os.getenv("MEETINGS_DETAIL_TTL_SECONDS", "600"))
OPENINFO_ORIGIN = "https://openinfo.uz"

_REFRESH_LOCK = threading.Lock()
_REFRESH_RUNNING = threading.Event()
_last_refresh_attempt = 0.0
_detail_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_DETAIL_CACHE_LOCK = threading.Lock()


class AnnouncementNotFound(LookupError):
    """The requested announcement does not exist on openinfo."""


class AnnouncementSourceError(RuntimeError):
    """openinfo returned a page that cannot be used as an announcement."""


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

def _node_text(node: Any) -> str:
    joined = " ".join(str(part).strip() for part in node.stripped_strings if str(part).strip())
    return re.sub(r"\s+", " ", joined).strip()


def _announcement_page(html: str, announcement_id: str, language: str) -> dict[str, Any]:
    """Turn openinfo's public, server-rendered announcement page into safe data.

    We deliberately return text and URLs, not the source HTML.  That keeps the
    page in our own design and avoids placing third-party markup in the DOM.
    """
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find("main")
    title_node = main.find("h1") if main else None
    title = _node_text(title_node) if title_node else ""
    if not main or not title:
        raise AnnouncementSourceError("openinfo announcement content is missing")

    organization = ""
    title_wrap = title_node.parent
    if title_wrap:
        company_node = title_wrap.find("span")
        organization = _node_text(company_node) if company_node else ""

    prose = main.find("div", class_=lambda value: value and "prose" in value.split())
    # The organization heading is localized by openinfo, but its position is
    # stable: it is the first heading after the announcement body.
    organization_heading = prose.find_next(["h2", "h3"]) if prose else None
    organization_box = organization_heading.parent if organization_heading else None

    metadata: list[dict[str, str]] = []
    for label_node in main.find_all(class_=lambda value: value and "font-medium" in value.split()):
        if organization_box and organization_box in label_node.parents:
            continue
        parent = label_node.parent
        parts = [str(part).strip() for part in parent.stripped_strings if str(part).strip()]
        if len(parts) < 2:
            continue
        label = parts[0].rstrip(":").strip()
        value = " ".join(parts[1:]).strip()
        if label and value:
            metadata.append({"label": label, "value": value})

    content: list[dict[str, str]] = []
    if prose:
        for node in prose.find_all(["h2", "h3", "p", "li"]):
            if node.name == "li" and node.find_parent("li"):
                continue
            text = _node_text(node)
            if not text:
                continue
            is_heading = node.name in {"h2", "h3"}
            if node.name == "p":
                strong = node.find("strong")
                is_heading = bool(strong and _node_text(strong) == text)
            content.append({
                "kind": "heading" if is_heading else "list_item" if node.name == "li" else "paragraph",
                "text": text,
            })

    organization_details: list[dict[str, str]] = []
    if organization_box:
        grid = organization_heading.find_next_sibling("div")
        for cell in grid.find_all("div", recursive=False) if grid else []:
            parts = [_node_text(node) for node in cell.find_all("p", recursive=False)]
            parts = [part for part in parts if part]
            if len(parts) >= 2:
                organization_details.append({
                    "label": parts[0].rstrip(":").strip(),
                    "value": " ".join(parts[1:]).strip(),
                })

    pdf_node = main.find("a", href=lambda value: bool(value and "/announce/to_pdf/" in value))
    pdf_url = str(pdf_node.get("href") or "") if pdf_node else ""
    source_url = f"{OPENINFO_ORIGIN}/{language}/announce/{announcement_id}"
    return {
        "announcement_id": announcement_id,
        "language": language,
        "title": title,
        "organization": organization,
        "metadata": metadata,
        "content": content,
        "organization_details": organization_details,
        "pdf_url": pdf_url,
        "source_url": source_url,
    }


def announcement_detail(
    announcement_id: int | str,
    language: str = "ru",
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Fetch one announcement from openinfo, with a short in-process cache."""
    item_id = str(announcement_id).strip()
    lang = str(language or "ru").strip().lower()
    if not item_id.isdigit():
        raise ValueError("announcement id must be numeric")
    if lang not in {"ru", "uz", "en"}:
        raise ValueError("language must be ru, uz or en")

    cache_key = (item_id, lang)
    now = time.time()
    if session is None:
        with _DETAIL_CACHE_LOCK:
            cached = _detail_cache.get(cache_key)
        if cached and now - cached[0] < DETAIL_TTL_SECONDS:
            return cached[1]

    url = f"{OPENINFO_ORIGIN}/{lang}/announce/{item_id}"
    client = session or requests.Session()
    try:
        response = client.get(
            url,
            timeout=20,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "UzInvest/1.0 (+https://uzinvest.uz)",
            },
        )
    except requests.RequestException as exc:
        raise AnnouncementSourceError("openinfo is unavailable") from exc
    if response.status_code == 404:
        raise AnnouncementNotFound(f"announcement {item_id} not found")
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AnnouncementSourceError(f"openinfo returned HTTP {response.status_code}") from exc

    payload = _announcement_page(response.text, item_id, lang)
    if session is None:
        with _DETAIL_CACHE_LOCK:
            _detail_cache[cache_key] = (now, payload)
    return payload

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


def read_recent(limit: int = 1000) -> list[dict[str, Any]]:
    """The stored window as a publication feed, newest notice first — the shape
    of the source's «Объявления» table, where the pub date is the row's identity
    and the meeting date is what the reader came for."""
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)}, updated_at FROM catalog_meetings "
            "ORDER BY pub_date DESC, announcement_id DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def announcements(limit: int = 1000) -> dict[str, Any]:
    """The announcement feed, warming the snapshot the same way a month read does."""
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

    items = read_recent(limit)
    return {"ok": True, "count": len(items), "items": items, "as_of": state.get("updated_at")}


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
    """One month — or, with a year and no month, one year — of the calendar,
    warming the snapshot as needed.

    A cold (empty) snapshot is filled synchronously — the crawl is a handful of
    paced pages, and an empty calendar teaches the first visitor the feature is
    broken; a merely stale one refreshes in the background.
    """
    today = datetime.now(timezone.utc)
    whole_year = year is not None and month is None
    y = year or today.year
    m = month or today.month
    if not (1 <= m <= 12) or not (2000 <= y <= 2100):
        raise ValueError(f"not a calendar month: {y}-{m}")
    if whole_year:
        start, end = f"{y:04d}-01-01", f"{y + 1:04d}-01-01"
    else:
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
