"""admin_overview.py — what the admin panel's «Обзор» screen reads.

One question, one query pass: *is the data alive, and what is waiting for a
decision*. Everything here is measured, never estimated — if a number cannot be
derived from a table it is not returned at all, and the screen renders a dash.

A note on the freshness block. The five collectors run as separate Railway cron
services and push over HTTP, so this process never sees their exit codes and
there is no run log to read. What it *can* see is the mark each one leaves: the
newest ``updated_at`` in the table that collector writes. That is reported
literally — «последняя запись», not «прогон завершён» — because a service that
died before writing and a service that had nothing to write are the same
silence from here, and the panel must not claim to tell them apart.

Dates are compared as ISO text against a cutoff computed in Python rather than
with ``datetime('now', ?)``: that idiom is SQLite-only and the catalog now runs
on PostgreSQL in production.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Which collector leaves its mark in which table. The panel names the service,
# so the mapping lives here rather than being guessed in the frontend.
STREAMS: tuple[dict[str, str], ...] = (
    {"key": "financials", "service": "collector", "schedule": "08:00 · Пн–Пт",
     "title": "Отчётность", "table": "catalog_financials", "column": "updated_at"},
    {"key": "reports", "service": "reports-watch", "schedule": "ежечасно 09–23 · Пн–Сб",
     "title": "Каталог отчётов", "table": "catalog_reports", "column": "synced_at"},
    {"key": "quotes", "service": "quotes-1610 / quotes-2130", "schedule": "16:10 и 21:30",
     "title": "Котировки", "table": "catalog_quotes", "column": "updated_at"},
    {"key": "trades", "service": "quotes-1610", "schedule": "16:10 · Пн–Сб",
     "title": "Итоги торгов", "table": "catalog_trade_stats", "column": "updated_at"},
    {"key": "news", "service": "news-collector", "schedule": "16:10 · ежедневно",
     "title": "Новости", "table": "news", "column": "collected_at"},
    {"key": "dividends", "service": "collector", "schedule": "08:00 · Пн–Пт",
     "title": "Дивиденды", "table": "catalog_dividends", "column": "updated_at"},
)

# Older than this and the stream is stale enough to say so on screen. Deliberately
# generous: a quiet session is silence, not failure (see cron-red-means-wrong-data).
STALE_AFTER_HOURS = 36


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _scalar(conn: Any, sql: str, params: tuple = ()) -> Any:
    """Run a one-value query, returning None instead of raising on a missing table."""
    try:
        row = conn.execute(sql, params).fetchone()
    except Exception as exc:  # a table that does not exist yet is not an error here
        logger.debug("overview query failed (%s): %s", sql.split()[3:5], exc)
        return None
    if row is None:
        return None
    try:
        return row[0]
    except (KeyError, IndexError, TypeError):
        return None


def _age_hours(stamp: Any, now: datetime) -> float | None:
    if not stamp:
        return None
    text = str(stamp).strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        seen = datetime.fromisoformat(text)
    except ValueError:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return round((now - seen).total_seconds() / 3600, 2)


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

def _catalog_block(conn: Any) -> dict[str, Any]:
    """How much of a market we are carrying, split the way the board splits it."""
    block: dict[str, Any] = {
        "companies": _scalar(conn, "SELECT COUNT(*) FROM catalog_companies"),
        "issuers": _scalar(conn, "SELECT COUNT(*) FROM issuers"),
        "with_financials": _scalar(conn, "SELECT COUNT(DISTINCT ticker) FROM catalog_financials"),
        "with_dividends": _scalar(conn, "SELECT COUNT(DISTINCT ticker) FROM catalog_dividends"),
    }
    # The securities catalog is a separate database with its own accessor.
    try:
        from securities_catalog import get_securities_map

        securities = get_securities_map() or {}
        block["securities"] = len(securities)
        block["stocks"] = sum(1 for s in securities.values() if (s.get("type") or "") != "bond")
        block["bonds"] = sum(1 for s in securities.values() if (s.get("type") or "") == "bond")
        block["preferred"] = sum(1 for s in securities.values() if s.get("is_preferred"))
    except Exception as exc:
        logger.warning("securities map unavailable for overview: %s", exc)
    return block


def _audit_block(conn: Any, *, history: int = 14, decide: int = 8) -> dict[str, Any]:
    """The auditor's own record: last run, the trend behind it, what is open."""
    from audit import find_findings, latest_run, list_runs

    runs = list_runs(max(1, history))
    open_counts: dict[str, int] = {}
    for severity in ("blocking", "warning", "info"):
        rows = find_findings(severity=severity, status="new", limit=2000)
        open_counts[severity] = len(rows)

    # What a person is actually asked to decide: open findings, worst first, and
    # only as many as the screen shows without scrolling.
    queue: list[dict[str, Any]] = []
    for severity in ("blocking", "warning", "info"):
        for row in find_findings(severity=severity, status="new", limit=decide):
            queue.append(row)
            if len(queue) >= decide:
                break
        if len(queue) >= decide:
            break

    return {
        "latest": latest_run(),
        # oldest first, so the chart reads left to right
        "history": list(reversed(runs)),
        "open": open_counts,
        "queue": queue,
    }


def _news_block(conn: Any, now: datetime, *, days: int = 7) -> dict[str, Any]:
    """Seven days of the feed: what arrived, what survived triage, what is stuck."""
    # `relevant` is the triage verdict and lives in news_nlp, one row per story.
    cutoff = _iso(now - timedelta(days=days))
    collected = _scalar(conn, "SELECT COUNT(*) FROM news WHERE collected_at >= ?", (cutoff,))
    published = _scalar(
        conn,
        "SELECT COUNT(*) FROM news n JOIN news_nlp p ON p.news_id = n.id "
        "WHERE n.collected_at >= ? AND p.relevant = 1",
        (cutoff,),
    )
    no_image = _scalar(
        conn,
        "SELECT COUNT(*) FROM news n JOIN news_nlp p ON p.news_id = n.id "
        "WHERE n.collected_at >= ? AND p.relevant = 1 "
        "AND (n.image_url IS NULL OR n.image_url = '')",
        (cutoff,),
    )
    rejected = None
    if collected is not None and published is not None:
        rejected = collected - published
    usage = None
    try:
        row = conn.execute(
            "SELECT * FROM news_usage_runs ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            usage = dict(row)
    except Exception as exc:
        # Old databases get the table when reports_catalog initialises. Keeping
        # this best-effort also lets the admin overview load during a rolling deploy.
        logger.debug("news usage query unavailable: %s", exc)
    return {
        "days": days,
        "collected": collected,
        "published": published,
        "rejected": rejected,
        "without_image": no_image,
        "usage": usage,
    }


def _streams_block(conn: Any, now: datetime) -> list[dict[str, Any]]:
    """The mark each collector left, reported as a mark and not as a verdict."""
    out: list[dict[str, Any]] = []
    for stream in STREAMS:
        table, column = stream["table"], stream["column"]
        last = _scalar(conn, f"SELECT MAX({column}) FROM {table}")  # noqa: S608 - fixed names
        rows = _scalar(conn, f"SELECT COUNT(*) FROM {table}")  # noqa: S608 - fixed names
        age = _age_hours(last, now)
        out.append({
            **{k: stream[k] for k in ("key", "service", "schedule", "title", "table")},
            "last_write": last,
            "age_hours": age,
            "rows": rows,
            # Three states only, and «unknown» is one of them: an empty table has
            # never been written and that is not the same as a stale one.
            "state": "unknown" if age is None else ("stale" if age > STALE_AFTER_HOURS else "fresh"),
        })
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_overview(*, history: int = 14, decide: int = 8) -> dict[str, Any]:
    """Everything the «Обзор» screen needs, in one connection.

    Each block is guarded on its own: a broken auditor table must not take the
    catalog counters down with it, because a panel that shows nothing is worse
    at diagnosing an outage than a panel that shows four of five blocks.
    """
    from catalogue.storage import get_catalog_conn

    now = _utcnow()
    conn = get_catalog_conn()
    try:
        blocks: dict[str, Any] = {"ok": True, "generated_at": _iso(now)}
        for name, fn in (
            ("catalog", lambda: _catalog_block(conn)),
            ("audit", lambda: _audit_block(conn, history=history, decide=decide)),
            ("news", lambda: _news_block(conn, now)),
            ("streams", lambda: _streams_block(conn, now)),
        ):
            try:
                blocks[name] = fn()
            except Exception as exc:
                logger.exception("overview block %s failed", name)
                blocks[name] = None
                blocks.setdefault("errors", {})[name] = str(exc)
        return blocks
    finally:
        try:
            conn.close()
        except Exception:
            pass
