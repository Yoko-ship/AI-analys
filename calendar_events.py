"""One dated feed of corporate events — the news «Календарь».

The calendar used to be three separate screens over two snapshots: a month grid
of meetings, a table of meeting notices and a table of dividend filings. A
reader tracking a company had to visit all three and could never see that the
payout window of one issuer opens the week another holds its meeting. This
module folds every source that names a real, dated corporate event into one
list of events with a common shape, so the page can draw them on one grid.

Every event is a date the source states. Nothing is projected or estimated:

* ``meeting``  — a general meeting, on its announced date (catalog_meetings).
* ``notice``   — the notice of that meeting, on the day it was published.
* ``dividend`` — a dividend filing (catalog_dividends): the decision date, and
  the start and the end of the payment window of every security class the
  filing declared an amount for. openinfo states no record date and no
  ex-dividend date, so neither is shown.
* ``report``   — a financial report, on the day the issuer published it
  (catalog_reports).
* ``fact``     — a material fact (существенный факт) from the issuer's own
  disclosure feed, on its publication date (news, openinfo sources only).
* ``listing``  — a security admitted to trading, on its listing date.

Bond coupon dates are left to the bond calendar: many of them are rebuilt from
the coupon cycle rather than stated by the issuer. A «delisting» is not an
event either — the news feed infers it from a security that stopped trading.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TYPES = ("meeting", "notice", "dividend", "report", "fact", "listing")
MAX_SPAN_DAYS = 400
_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_DIV_CLASSES = ("ordinary", "preferred", "bond")


def _day(value: Any) -> str | None:
    """The calendar day of a stored timestamp, or None when it is not a date."""
    match = _ISO_DAY.match(str(value or "").strip())
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def _meeting_time(value: Any) -> str | None:
    """The meeting hour, only when the issuer filed one.

    A real agenda starts on a round minute; a meeting date copied from the
    filing timestamp carries its seconds (16:21:48) and is a date only.
    """
    match = re.search(r"[T ](\d\d):(\d\d):(\d\d)", str(value or ""))
    if not match or match[3] != "00" or (match[1] == "00" and match[2] == "00"):
        return None
    return f"{match[1]}:{match[2]}"


def _today() -> date:
    """Today on the exchange's clock — «upcoming» means upcoming in Tashkent."""
    return datetime.now(ZoneInfo("Asia/Tashkent")).date()


def parse_range(start: str | None, end: str | None) -> tuple[date, date]:
    """[start, end] as dates; both inclusive. Defaults to the current month."""
    today = _today()
    try:
        first = date.fromisoformat(start) if start else today.replace(day=1)
        if end:
            last = date.fromisoformat(end)
        else:
            nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
            last = nxt - timedelta(days=1)
    except ValueError as exc:
        raise ValueError("start and end must be YYYY-MM-DD") from exc
    if last < first:
        raise ValueError("end is before start")
    if (last - first).days > MAX_SPAN_DAYS:
        raise ValueError(f"the range may span at most {MAX_SPAN_DAYS} days")
    return first, last


# ---------------------------------------------------------------------------
# Sources. Each takes [lo, hi) as ISO days and returns events.
# ---------------------------------------------------------------------------

def _meetings(lo: str, hi: str) -> list[dict[str, Any]]:
    import meetings

    meetings.ensure_snapshot()
    out = []
    for row in meetings.read_window(lo, hi):
        day = _day(row.get("meeting_date"))
        if not day:
            continue
        out.append({
            "id": f"meeting:{row.get('announcement_id')}",
            "type": "meeting",
            "date": day,
            "time": _meeting_time(row.get("meeting_date")),
            "organization": row.get("organization"),
            "ticker": row.get("ticker"),
            "title": row.get("title"),
            "announcement_id": row.get("announcement_id"),
            "details": {"pub_date": row.get("pub_date")},
        })
    return out


def _notices(lo: str, hi: str) -> list[dict[str, Any]]:
    import meetings

    meetings.ensure_snapshot()
    out = []
    for row in meetings.read_published(lo, hi):
        day = _day(row.get("pub_date"))
        if not day:
            continue
        out.append({
            "id": f"notice:{row.get('announcement_id')}",
            "type": "notice",
            "date": day,
            "time": None,
            "organization": row.get("organization"),
            "ticker": row.get("ticker"),
            "title": row.get("title"),
            "announcement_id": row.get("announcement_id"),
            "details": {
                "meeting_date": _day(row.get("meeting_date")),
                "meeting_time": _meeting_time(row.get("meeting_date")),
            },
        })
    return out


def _dividend_events(filing: dict[str, Any], lo: str, hi: str) -> list[dict[str, Any]]:
    """The dated steps of one filing that fall in [lo, hi)."""
    pub = _day(filing.get("pub_date"))
    classes = []
    for cls in _DIV_CLASSES:
        amount = filing.get(f"{cls}_amount") or 0
        # A class with no amount declared nothing: openinfo still fills its
        # start date with the filing day on some rows, which is not a payout.
        if amount <= 0:
            continue
        classes.append({
            "class": cls,
            "amount": amount,
            "percent": filing.get(f"{cls}_percent") or None,
            "start": _day(filing.get(f"{cls}_start")),
            "end": _day(filing.get(f"{cls}_end")),
        })
    decision = _day(filing.get("decision_date"))
    # Issuer-typed free text: DORI filed a 2018 payout as decided «2108-10-02».
    # A decision cannot postdate the filing that reports it.
    if decision and pub and decision > pub:
        decision = None

    details = {
        "decision_date": decision,
        "pub_date": pub,
        "classes": classes,
        "link": filing.get("link"),
    }
    base = {
        "type": "dividend",
        "time": None,
        "organization": filing.get("organization"),
        "ticker": filing.get("ticker"),
        "tickers": filing.get("tickers") or [],
        "title": None,
        "details": details,
    }
    steps: dict[tuple[str, str], list[str]] = {}
    if decision and classes:
        steps[("decision", decision)] = [c["class"] for c in classes]
    for c in classes:
        for kind, day in (("payment_start", c["start"]), ("payment_end", c["end"])):
            if day:
                steps.setdefault((kind, day), []).append(c["class"])
    out = []
    for (kind, day), in_step in steps.items():
        if lo <= day < hi:
            out.append({**base, "id": f"dividend:{filing.get('filing_id')}:{kind}",
                        "kind": kind, "date": day, "classes": in_step})
    return out


def _dividends(lo: str, hi: str) -> list[dict[str, Any]]:
    import dividends

    state = dividends.snapshot_state()
    age = state.get("age_hours")
    if not state.get("filings") or age is None or age >= dividends.REFRESH_TTL_HOURS:
        dividends.refresh_in_background()
    out = []
    for filing in dividends.read_all(100_000):
        out.extend(_dividend_events(filing, lo, hi))
    return out


def _reports(lo: str, hi: str) -> list[dict[str, Any]]:
    import catalogue.settings as settings
    from catalogue.storage import get_catalog_conn

    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            "SELECT ticker, report_form, period_type, year, quarter, title, "
            "published_at, pdf_url, excel_url FROM catalog_reports "
            "WHERE published_at LIKE '____-__-__%' AND published_at >= ? AND published_at < ? "
            "ORDER BY published_at",
            (lo, hi),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        r = dict(row)
        day = _day(r.get("published_at"))
        if not day:
            continue
        tk = r.get("ticker")
        out.append({
            "id": f"report:{tk}:{r.get('report_form')}:{r.get('year')}:{r.get('quarter')}:{r.get('period_type')}",
            "type": "report",
            "date": day,
            "time": None,
            "organization": settings._TICKER_TO_NAME.get(tk, tk),
            "ticker": tk,
            "title": r.get("title"),
            "details": {
                "report_form": r.get("report_form"),
                "period_type": r.get("period_type"),
                "year": r.get("year"),
                "quarter": r.get("quarter"),
                "pdf_url": r.get("pdf_url"),
                "excel_url": r.get("excel_url"),
            },
        })
    return out


def _facts(lo: str, hi: str) -> list[dict[str, Any]]:
    import news_store
    from catalogue.storage import get_catalog_conn

    sources = sorted(news_store.disclosure_source_ids())
    if not sources:
        return []
    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            "SELECT n.id, n.url, n.title, n.published_at, "
            "       (SELECT COUNT(*) FROM news_nlp p WHERE p.news_id = n.id) AS classified, "
            "       (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e WHERE e.news_id = n.id) AS tickers_csv "
            "FROM news n "
            f"WHERE n.source_id IN ({','.join('?' * len(sources))}) "
            "AND n.published_at >= ? AND n.published_at < ? "
            "ORDER BY n.published_at",
            (*sources, lo, hi),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        r = dict(row)
        day = _day(r.get("published_at"))
        if not day:
            continue
        tickers = sorted({t for t in str(r.get("tickers_csv") or "").split(",") if t},
                         key=lambda t: (len(t), t))
        # Filed as «Issuer: fact» — the issuer is a column of its own here.
        org, _, fact = str(r.get("title") or "").partition(": ")
        if not fact:
            org, fact = "", org
        out.append({
            "id": f"fact:{r.get('id')}",
            "type": "fact",
            "date": day,
            "time": None,
            "organization": org.strip() or None,
            "ticker": tickers[0] if tickers else None,
            "tickers": tickers,
            "title": fact.strip(),
            # Our article page reads the classifier's row; an item it has not
            # reached yet opens on openinfo instead.
            "news_id": r.get("id") if r.get("classified") else None,
            "details": {"link": r.get("url")},
        })
    return out


def _listings(lo: str, hi: str) -> list[dict[str, Any]]:
    import catalogue.market_store as market_store
    import server.market.board as market_board

    bond_isins = market_board._registered_bond_isins()
    out = []
    for tk, row in (market_store.get_all_listings() or {}).items():
        day = _day(row.get("listing_date"))
        if not day or not (lo <= day < hi):
            continue
        is_bond = str(row.get("isin") or "").upper() in bond_isins
        out.append({
            "id": f"listing:{tk}",
            "type": "listing",
            "date": day,
            "time": None,
            "organization": row.get("name") or tk,
            "ticker": tk,
            "title": None,
            "details": {
                "share_type": "bond" if is_bond else row.get("share_type"),
                "isin": row.get("isin"),
                "nominal": row.get("nominal"),
            },
        })
    return out


SOURCES: dict[str, Callable[[str, str], list[dict[str, Any]]]] = {
    "meeting": _meetings,
    "notice": _notices,
    "dividend": _dividends,
    "report": _reports,
    "fact": _facts,
    "listing": _listings,
}


def events_between(start: str | None, end: str | None,
                   types: list[str] | None = None) -> dict[str, Any]:
    """Every event dated in [start, end], both days inclusive, oldest first.

    One failing source is reported in ``sources`` and leaves the rest of the
    calendar standing — openinfo down must not empty the reports.
    """
    first, last = parse_range(start, end)
    lo, hi = first.isoformat(), (last + timedelta(days=1)).isoformat()
    wanted = [t for t in (types or TYPES) if t in SOURCES]
    items: list[dict[str, Any]] = []
    status: dict[str, Any] = {}
    for name in wanted:
        try:
            found = SOURCES[name](lo, hi)
            items.extend(found)
            status[name] = {"ok": True, "count": len(found)}
        except Exception as exc:  # noqa: BLE001 — one source must not fail the page
            logger.exception("calendar source %s failed", name)
            status[name] = {"ok": False, "error": str(exc)}
    order = {name: i for i, name in enumerate(TYPES)}
    items.sort(key=lambda e: (e["date"], e.get("time") or "", order.get(e["type"], 99),
                              str(e.get("organization") or "")))
    return {
        "ok": any(s["ok"] for s in status.values()) if status else True,
        "start": first.isoformat(),
        "end": last.isoformat(),
        "today": _today().isoformat(),
        "count": len(items),
        "items": items,
        "sources": status,
    }
