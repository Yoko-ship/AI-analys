"""provenance.py — where every published number came from.

ТЗ Дополнение 1, часть Б. The reporting catalog is a shelf of links today: it
lists companies and opens PDFs on openinfo.uz, and hands nothing to the rest of
the system. Three consequences, all of them visible:

The screen contradicts itself. The header says 85 companies and 2 021 reports;
the list returns 73 rows holding 1 659. Twelve companies and 362 reports exist
in the database and in nobody's view, because the two numbers come from separate
queries that are never compared. **So the counters and the list are now produced
by ONE call** — a disagreement becomes impossible rather than unnoticed.

It is keyed by ticker, not by issuer. 73 rows are 66 organisations: one issuer
has four bond series, another four, another two. Their statements are shared but
either duplicated across rows or shown nowhere — five series display "0 reports"
while their issuer's filings sit under another ticker.

And the part this module exists for: **no published figure names the report it
came from.** "Where did UQEQ's revenue of 31 379 733 363 530 — 131 times its
annual — come from?" is currently unanswerable: nobody can say which filing,
which form, which period, or whether it was parsed at all rather than read off
the wrong field. That gap is the origin of the entire FIN defect group.

A report therefore moves through explicit states and numbers are published only
from `validated`. A rejected report is not deleted: "we have the report and
could not parse it" is information, and an empty space is not.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# ТЗ Б.3. Numbers are published from `validated` and never straight from
# `parsed` — parsing is extraction, validation is the decision to believe it.
STATES = ("discovered", "downloaded", "parsed", "validated", "published",
          "download_failed", "parse_failed", "rejected", "stale")
PUBLISHABLE = ("validated", "published")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or _conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS issuers (
              org_id    TEXT PRIMARY KEY,
              name      TEXT NOT NULL,
              inn       TEXT,
              logo_url  TEXT,
              synced_at TEXT
            );
            CREATE TABLE IF NOT EXISTS source_reports (
              id            INTEGER PRIMARY KEY AUTOINCREMENT,
              org_id        TEXT NOT NULL,
              report_form   TEXT NOT NULL,
              period_type   TEXT NOT NULL,
              period_year   INTEGER NOT NULL,
              period_quarter INTEGER,
              title         TEXT,
              pdf_url       TEXT, excel_url TEXT,
              file_hash     TEXT,
              state         TEXT NOT NULL DEFAULT 'discovered',
              state_reason  TEXT,
              discovered_at TEXT NOT NULL,
              parsed_at     TEXT, published_at TEXT,
              UNIQUE (org_id, report_form, period_type, period_year, period_quarter)
            );
            CREATE INDEX IF NOT EXISTS ix_reports_state
              ON source_reports (state, period_year DESC);
            CREATE TABLE IF NOT EXISTS report_figures (
              report_id  INTEGER NOT NULL REFERENCES source_reports(id),
              field      TEXT NOT NULL,
              value      REAL,
              unit_scale INTEGER NOT NULL DEFAULT 1,
              page       INTEGER,
              raw_label  TEXT,
              PRIMARY KEY (report_id, field)
            );
            CREATE TABLE IF NOT EXISTS bond_reference (
              ticker      TEXT PRIMARY KEY,
              isin        TEXT,
              nominal     REAL,
              currency    TEXT NOT NULL DEFAULT 'UZS',
              coupon_rate REAL,
              coupon_freq INTEGER,
              coupon_type TEXT,
              float_base  TEXT,
              issue_date  TEXT,
              maturity_date TEXT,
              issue_volume REAL,
              amortization INTEGER NOT NULL DEFAULT 0,
              has_put      INTEGER NOT NULL DEFAULT 0,
              has_call     INTEGER NOT NULL DEFAULT 0,
              source_url   TEXT,
              synced_at    TEXT
            );
            CREATE TABLE IF NOT EXISTS bond_coupons (
              ticker      TEXT NOT NULL REFERENCES bond_reference(ticker),
              coupon_no   INTEGER NOT NULL,
              period_from TEXT NOT NULL, period_to TEXT NOT NULL,
              pay_date    TEXT NOT NULL,
              amount      REAL,
              is_paid     INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (ticker, coupon_no)
            );
            """
        )
        conn.commit()
    finally:
        if own:
            conn.close()


def file_hash(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# The report state machine (ТЗ Б.3)
# ---------------------------------------------------------------------------

def upsert_report(org_id: str, report_form: str, period_type: str, period_year: int,
                  period_quarter: int | None = None, *, pdf_url: str | None = None,
                  excel_url: str | None = None, title: str | None = None,
                  hash_value: str | None = None) -> int:
    """Register a report, or return it to `discovered` if the source replaced it.

    The source is entitled to re-upload a filing, and that has to be caught
    rather than ignored: a changed file hash sends the report back to the start
    and it is parsed again.
    """
    init()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT id, file_hash, state FROM source_reports WHERE org_id=? AND report_form=? "
            "AND period_type=? AND period_year=? AND IFNULL(period_quarter,-1)=IFNULL(?,-1)",
            (org_id, report_form, period_type, period_year, period_quarter)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO source_reports (org_id, report_form, period_type, period_year, "
                "period_quarter, title, pdf_url, excel_url, file_hash, state, discovered_at) "
                "VALUES (?,?,?,?,?,?,?,?,?, 'discovered', ?)",
                (org_id, report_form, period_type, period_year, period_quarter, title,
                 pdf_url, excel_url, hash_value, _now()))
            conn.commit()
            return int(cur.lastrowid)
        if hash_value and row["file_hash"] and hash_value != row["file_hash"]:
            conn.execute(
                "UPDATE source_reports SET file_hash=?, state='discovered', "
                "state_reason='файл в источнике заменён', parsed_at=NULL, published_at=NULL, "
                "pdf_url=COALESCE(?, pdf_url), excel_url=COALESCE(?, excel_url) WHERE id=?",
                (hash_value, pdf_url, excel_url, row["id"]))
        else:
            conn.execute(
                "UPDATE source_reports SET pdf_url=COALESCE(?, pdf_url), "
                "excel_url=COALESCE(?, excel_url), title=COALESCE(?, title), "
                "file_hash=COALESCE(?, file_hash) WHERE id=?",
                (pdf_url, excel_url, title, hash_value, row["id"]))
        conn.commit()
        return int(row["id"])
    finally:
        conn.close()


def set_state(report_id: int, state: str, reason: str | None = None) -> None:
    if state not in STATES:
        raise ValueError(f"unknown report state: {state}")
    conn = _conn()
    try:
        stamps = ""
        if state == "parsed":
            stamps = ", parsed_at = '%s'" % _now()
        elif state == "published":
            stamps = ", published_at = '%s'" % _now()
        conn.execute(f"UPDATE source_reports SET state=?, state_reason=?{stamps} WHERE id=?",
                     (state, reason, report_id))
        conn.commit()
    finally:
        conn.close()


def record_figures(report_id: int, figures: Iterable[dict[str, Any]]) -> int:
    """Store extracted numbers WITH the page and the label they came from.

    That pair is the traceability: a reader sees not only the figure but the
    line of the report the parser took it from, which is what turns "your
    revenue is wrong" from a day's argument into a minute's check.
    """
    conn = _conn()
    written = 0
    try:
        for figure in figures or []:
            field = str(figure.get("field") or "").strip()
            if not field:
                continue
            conn.execute(
                "INSERT INTO report_figures (report_id, field, value, unit_scale, page, raw_label) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(report_id, field) DO UPDATE SET "
                "value=excluded.value, unit_scale=excluded.unit_scale, page=excluded.page, "
                "raw_label=excluded.raw_label",
                (report_id, field, figure.get("value"), int(figure.get("unit_scale") or 1),
                 figure.get("page"), figure.get("raw_label")))
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def report(report_id: int) -> dict[str, Any] | None:
    init()
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM source_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            return None
        figures = [dict(f) for f in conn.execute(
            "SELECT field, value, unit_scale, page, raw_label FROM report_figures "
            "WHERE report_id=?", (report_id,))]
        out = dict(row)
        out["figures"] = figures
        # ТЗ Б.5: the reverse question. A rejected report with used_by false is
        # normal; a rejected report with used_by true is an incident.
        out["used_by"] = {"financials": row["state"] in PUBLISHABLE and bool(figures)}
        return out
    finally:
        conn.close()


def summary(now: datetime | None = None) -> dict[str, Any]:
    """Counters AND the issuer list from ONE query (ТЗ Б.5).

    The header said 85 companies and the list returned 73 because they were two
    queries nobody compared. Reading both from the same statement makes them
    unable to disagree.
    """
    init()
    conn = _conn()
    try:
        by_state = {r["state"]: r["n"] for r in conn.execute(
            "SELECT state, COUNT(*) AS n FROM source_reports GROUP BY state")}
        by_form = {r["report_form"]: r["n"] for r in conn.execute(
            "SELECT report_form, COUNT(*) AS n FROM source_reports GROUP BY report_form")}
        issuers = [dict(r) for r in conn.execute(
            "SELECT i.org_id, i.name, i.synced_at, COUNT(r.id) AS reports, "
            "SUM(CASE WHEN r.state IN ('validated','published') THEN 1 ELSE 0 END) AS published, "
            "SUM(CASE WHEN r.state IN ('rejected','parse_failed','download_failed') "
            "         THEN 1 ELSE 0 END) AS failed "
            "FROM issuers i LEFT JOIN source_reports r ON r.org_id = i.org_id "
            "GROUP BY i.org_id, i.name, i.synced_at ORDER BY i.name")]
        last_sync = conn.execute("SELECT MAX(synced_at) AS s FROM issuers").fetchone()["s"]
    finally:
        conn.close()

    total = sum(by_state.values())
    reference = now or datetime.now(timezone.utc)
    staleness_hours = None
    if last_sync:
        try:
            stamp = datetime.fromisoformat(last_sync)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            staleness_hours = (reference - stamp).total_seconds() / 3600.0
        except ValueError:
            staleness_hours = None
    limit = 24.0
    try:
        from formulas import thresholds

        limit = float(thresholds()["catalog"].get("staleness_warn_hours", 24))
    except Exception:  # noqa: BLE001 — a missing config must not hide staleness
        pass
    return {
        # These two are computed from the same rows, so they cannot disagree.
        "issuers": len(issuers),
        "reports_total": total,
        "by_state": by_state,
        "by_form": by_form,
        "items": issuers,
        "last_sync": last_sync,
        "staleness_hours": staleness_hours,
        # ТЗ Б.6: age is a sentence in the interface, not a date the reader has
        # to subtract from today. The catalog was ten days behind the market and
        # the screen showed only a date.
        "staleness_warn_hours": limit,
        "is_stale": bool(staleness_hours and staleness_hours > limit),
    }


def queue(limit: int = 200) -> list[dict[str, Any]]:
    """Reports that failed to parse — a work queue, not a shelf (ТЗ Б.5)."""
    init()
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM source_reports WHERE state IN "
            "('discovered','downloaded','parse_failed','download_failed','rejected') "
            "ORDER BY period_year DESC, id DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bond reference (ТЗ А.4)
# ---------------------------------------------------------------------------

def upsert_bond_reference(rows: Sequence[dict[str, Any]]) -> int:
    init()
    conn = _conn()
    fields = ("ticker", "isin", "nominal", "currency", "coupon_rate", "coupon_freq",
              "coupon_type", "float_base", "issue_date", "maturity_date", "issue_volume",
              "amortization", "has_put", "has_call", "source_url")
    written = 0
    try:
        for row in rows or []:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            # Defaults for the columns the schema requires: a partial reference
            # is the normal state of this table, not an error.
            defaults = {"currency": "UZS", "amortization": 0, "has_put": 0, "has_call": 0}
            values = [ticker] + [row.get(f, defaults.get(f)) if row.get(f) is not None
                                 else defaults.get(f) for f in fields[1:]] + [_now()]
            placeholders = ",".join("?" * (len(fields) + 1))
            updates = ",".join(f"{f}=excluded.{f}" for f in fields[1:]) + ", synced_at=excluded.synced_at"
            conn.execute(
                f"INSERT INTO bond_reference ({','.join(fields)}, synced_at) "
                f"VALUES ({placeholders}) ON CONFLICT(ticker) DO UPDATE SET {updates}", values)
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def bond_references() -> dict[str, dict[str, Any]]:
    init()
    conn = _conn()
    try:
        return {r["ticker"]: dict(r) for r in conn.execute("SELECT * FROM bond_reference")}
    finally:
        conn.close()


def bond_coupons() -> dict[str, list[dict[str, Any]]]:
    init()
    conn = _conn()
    try:
        out: dict[str, list[dict[str, Any]]] = {}
        for row in conn.execute("SELECT * FROM bond_coupons ORDER BY ticker, coupon_no"):
            out.setdefault(row["ticker"], []).append(dict(row))
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Bridging the existing catalog into the registry
# ---------------------------------------------------------------------------

def sync_from_catalog() -> dict[str, int]:
    """Register what the catalog already knows as `discovered` reports.

    The project has been collecting `catalog_companies` and `catalog_reports` for
    a long time; what it never had was a state for each report or a link from a
    published figure back to one. So the registry is seeded from those tables
    rather than started empty — the provenance layer describes the filings we
    actually hold, from the first run.

    Idempotent: a report already registered keeps its state, so a nightly sync
    does not reset something that has been parsed.
    """
    init()
    conn = _conn()
    issuers = reports = 0
    try:
        # ТЗ Б.6: the catalog is a list of ISSUERS. 73 ticker rows are 66
        # organisations; keying by ticker is why a bond series showed "0 отчётов"
        # while its issuer's filings sat under another ticker.
        for row in conn.execute(
                "SELECT org_id, MIN(company_name) AS name, MAX(last_synced_at) AS synced "
                "FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != '' "
                "GROUP BY org_id"):
            conn.execute(
                "INSERT INTO issuers (org_id, name, synced_at) VALUES (?,?,?) "
                "ON CONFLICT(org_id) DO UPDATE SET name=excluded.name, "
                "synced_at=COALESCE(excluded.synced_at, issuers.synced_at)",
                (row["org_id"], row["name"], row["synced"]))
            issuers += 1

        for row in conn.execute(
                "SELECT r.ticker, r.report_form, r.period_type, r.year, r.quarter, "
                "       r.title, r.pdf_url, r.excel_url, c.org_id "
                "FROM catalog_reports r LEFT JOIN catalog_companies c ON c.ticker = r.ticker "
                "WHERE r.year IS NOT NULL"):
            org_id = row["org_id"] or f"ticker:{row['ticker']}"
            quarter = row["quarter"] or None
            existing = conn.execute(
                "SELECT id FROM source_reports WHERE org_id=? AND report_form=? AND "
                "period_type=? AND period_year=? AND IFNULL(period_quarter,-1)=IFNULL(?,-1)",
                (org_id, row["report_form"], row["period_type"], row["year"], quarter)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE source_reports SET pdf_url=COALESCE(?, pdf_url), "
                    "excel_url=COALESCE(?, excel_url), title=COALESCE(?, title) WHERE id=?",
                    (row["pdf_url"], row["excel_url"], row["title"], existing["id"]))
            else:
                conn.execute(
                    "INSERT INTO source_reports (org_id, report_form, period_type, "
                    "period_year, period_quarter, title, pdf_url, excel_url, state, "
                    "discovered_at) VALUES (?,?,?,?,?,?,?,?, 'discovered', ?)",
                    (org_id, row["report_form"], row["period_type"], row["year"], quarter,
                     row["title"], row["pdf_url"], row["excel_url"], _now()))
                reports += 1
        conn.commit()
    finally:
        conn.close()
    return {"issuers": issuers, "reports_registered": reports}


def report_id_for(ticker: str, report_form: str, period_type: str, year: int,
                  quarter: int | None = None) -> int | None:
    """The registry id of a report, resolved the way the parser identifies it."""
    init()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT r.id FROM source_reports r "
            "LEFT JOIN catalog_companies c ON c.org_id = r.org_id "
            "WHERE (c.ticker = ? OR r.org_id = ?) AND r.report_form = ? "
            "AND r.period_type = ? AND r.period_year = ? "
            "AND IFNULL(r.period_quarter,-1) = IFNULL(?,-1) LIMIT 1",
            (ticker, f"ticker:{ticker}", report_form, period_type, year,
             quarter or None)).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def ticker_of(report_id: int) -> str | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(c.ticker, REPLACE(r.org_id,'ticker:','')) AS ticker "
            "FROM source_reports r LEFT JOIN catalog_companies c ON c.org_id = r.org_id "
            "WHERE r.id = ? LIMIT 1", (report_id,)).fetchone()
        return row["ticker"] if row else None
    finally:
        conn.close()
