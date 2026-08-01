"""Persistence for audit runs and findings (ТЗ v1.3 §12.4).

Three tables. The one that carries the design is ``audit_findings``: findings
are deduplicated by a ``fingerprint`` of rule + ticker + metric, so the same
problem seen on twenty consecutive runs is ONE row whose ``last_seen`` and
counter move — not twenty rows nobody reads. §12.2 is explicit that no finding
disappears silently: each has an author rule, a first-seen time and a status a
person can move to `accepted` (a known exception) or `fixed`.

SQLite, matching the rest of the project. The ТЗ writes PostgreSQL DDL because
that is the target stack; the columns, the unique partial index on open
findings and the semantics are the same.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from audit.rules import ALL_RULES, BLOCKING, WARNING

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("new", "confirmed")


def _conn() -> sqlite3.Connection:
    """The project's catalog database — reached through its own accessor.

    This is storage, not calculation: the isolation rule of §12.1 forbids the
    auditor from sharing the FORMULAS, and resolving the database path a second
    time here would risk auditing a different file than the application writes.
    """
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or _conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_rules (
              code      TEXT PRIMARY KEY,
              title     TEXT NOT NULL,
              group_code TEXT NOT NULL,
              severity  TEXT NOT NULL,
              threshold TEXT,
              is_enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS audit_runs (
              id          TEXT PRIMARY KEY,
              trigger     TEXT NOT NULL,
              started_at  TEXT NOT NULL,
              finished_at TEXT,
              status      TEXT NOT NULL,
              instruments INTEGER, rules_run INTEGER,
              blocking INTEGER, warnings INTEGER, infos INTEGER,
              duration_ms INTEGER, trace_id TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_findings (
              id          INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id      TEXT NOT NULL,
              rule_code   TEXT NOT NULL,
              ticker      TEXT,
              metric      TEXT,
              expected    REAL, actual REAL, deviation REAL,
              severity    TEXT NOT NULL,
              message     TEXT NOT NULL,
              input       TEXT,
              status      TEXT NOT NULL DEFAULT 'new',
              note        TEXT,
              first_seen  TEXT NOT NULL,
              last_seen   TEXT NOT NULL,
              seen_count  INTEGER NOT NULL DEFAULT 1,
              fingerprint TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_finding_open
              ON audit_findings (fingerprint)
              WHERE status IN ('new', 'confirmed');
            CREATE INDEX IF NOT EXISTS ix_findings_run ON audit_findings (run_id, severity);
            CREATE INDEX IF NOT EXISTS ix_findings_ticker ON audit_findings (ticker, status);
            """
        )
        for rule in ALL_RULES:
            conn.execute(
                "INSERT INTO audit_rules (code, title, group_code, severity, threshold) "
                "VALUES (?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET "
                "title=excluded.title, group_code=excluded.group_code, "
                "severity=excluded.severity, threshold=excluded.threshold",
                (rule.code, rule.title, rule.group, rule.severity, rule.threshold),
            )
        conn.commit()
    finally:
        if own:
            conn.close()


def fingerprint(rule_code: str, ticker: str | None, metric: str | None) -> str:
    raw = f"{rule_code}|{(ticker or '').upper()}|{metric or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def start_run(trigger: str, trace_id: str | None = None) -> str:
    init()
    run_id = uuid.uuid4().hex
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO audit_runs (id, trigger, started_at, status, trace_id) "
            "VALUES (?,?,?,?,?)", (run_id, trigger, _now(), "running", trace_id))
        conn.commit()
    finally:
        conn.close()
    return run_id


def record(run_id: str, findings: Sequence[Any]) -> dict[str, int]:
    """Persist a run's findings, folding repeats into their existing row."""
    counts = {BLOCKING: 0, WARNING: 0, "info": 0}
    conn = _conn()
    try:
        for finding in findings:
            severity = finding.severity
            counts[severity] = counts.get(severity, 0) + 1
            fp = fingerprint(finding.rule_code, finding.ticker, finding.metric)
            row = conn.execute(
                "SELECT id, seen_count FROM audit_findings "
                "WHERE fingerprint = ? AND status IN ('new','confirmed')", (fp,)).fetchone()
            payload = json.dumps(finding.input or {}, ensure_ascii=False, default=str)
            if row:
                # The same problem, seen again: one row, a moved timestamp and a
                # counter. Twenty runs must not produce twenty rows.
                conn.execute(
                    "UPDATE audit_findings SET run_id=?, last_seen=?, seen_count=?, "
                    "expected=?, actual=?, deviation=?, message=?, input=? WHERE id=?",
                    (run_id, _now(), row["seen_count"] + 1, finding.expected, finding.actual,
                     finding.deviation, finding.message, payload, row["id"]))
            else:
                conn.execute(
                    "INSERT INTO audit_findings (run_id, rule_code, ticker, metric, expected, "
                    "actual, deviation, severity, message, input, first_seen, last_seen, "
                    "fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, finding.rule_code, (finding.ticker or None), finding.metric,
                     finding.expected, finding.actual, finding.deviation, severity,
                     finding.message, payload, _now(), _now(), fp))
        conn.commit()
    finally:
        conn.close()
    return counts


def finish_run(run_id: str, *, status: str, instruments: int, rules_run: int,
               counts: dict[str, int], duration_ms: int, error: str | None = None) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE audit_runs SET finished_at=?, status=?, instruments=?, rules_run=?, "
            "blocking=?, warnings=?, infos=?, duration_ms=?, error=? WHERE id=?",
            (_now(), status, instruments, rules_run, counts.get(BLOCKING, 0),
             counts.get(WARNING, 0), counts.get("info", 0), duration_ms, error, run_id))
        conn.commit()
    finally:
        conn.close()


def resolve_missing(run_id: str, seen_fingerprints: Iterable[str]) -> int:
    """Findings not seen in this run are fixed — recorded, not deleted."""
    keep = set(seen_fingerprints)
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, fingerprint FROM audit_findings WHERE status IN ('new','confirmed')"
        ).fetchall()
        gone = [r["id"] for r in rows if r["fingerprint"] not in keep]
        for fid in gone:
            conn.execute("UPDATE audit_findings SET status='fixed', last_seen=? WHERE id=?",
                         (_now(), fid))
        conn.commit()
        return len(gone)
    finally:
        conn.close()


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    init()
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_runs ORDER BY started_at DESC LIMIT ?", (limit,))]
    finally:
        conn.close()


def get_run(run_id: str) -> dict[str, Any] | None:
    init()
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM audit_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def latest_run(status: str | None = None) -> dict[str, Any] | None:
    init()
    conn = _conn()
    try:
        sql = "SELECT * FROM audit_runs WHERE finished_at IS NOT NULL"
        args: list[Any] = []
        if status:
            sql += " AND status = ?"
            args.append(status)
        row = conn.execute(sql + " ORDER BY started_at DESC LIMIT 1", args).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def find_findings(*, run_id: str | None = None, severity: str | None = None,
                  group: str | None = None, status: str | None = None,
                  ticker: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    init()
    sql = ["SELECT * FROM audit_findings WHERE 1=1"]
    args: list[Any] = []
    if run_id:
        sql.append("AND run_id = ?"); args.append(run_id)
    if severity:
        sql.append("AND severity = ?"); args.append(severity)
    if group:
        sql.append("AND rule_code LIKE ?"); args.append(f"{group}-%")
    if status:
        sql.append("AND status = ?"); args.append(status)
    else:
        sql.append("AND status IN ('new','confirmed')")
    if ticker:
        sql.append("AND ticker = ?"); args.append(ticker.upper())
    sql.append("ORDER BY CASE severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,"
               " rule_code LIMIT ?")
    args.append(limit)
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute(" ".join(sql), args)]
    finally:
        conn.close()
    for row in rows:
        try:
            row["input"] = json.loads(row["input"]) if row.get("input") else {}
        except (TypeError, ValueError):
            row["input"] = {}
    return rows


def update_finding(finding_id: int, *, status: str, note: str | None = None) -> dict[str, Any] | None:
    if status not in ("new", "confirmed", "accepted", "fixed"):
        raise ValueError("unknown status")
    conn = _conn()
    try:
        conn.execute("UPDATE audit_findings SET status = ?, note = COALESCE(?, note) WHERE id = ?",
                     (status, note, finding_id))
        conn.commit()
        row = conn.execute("SELECT * FROM audit_findings WHERE id = ?", (finding_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def blocking_index() -> dict[str, set[str]]:
    """{TICKER: {metric, ...}} for open blocking findings.

    This is what makes the auditor more than a report: §12.2 says a blocking
    finding means the metric is NOT published. The serving layer reads this and
    replaces the number with a dash and the reason.
    """
    out: dict[str, set[str]] = {}
    try:
        for row in find_findings(severity=BLOCKING, limit=5000):
            ticker = str(row.get("ticker") or "").upper()
            metric = row.get("metric")
            if not ticker or not metric:
                continue
            out.setdefault(ticker, set()).add(metric)
    except Exception:  # noqa: BLE001 — publication must survive an audit outage
        logger.exception("blocking index unavailable")
    return out


def ticker_badge(ticker: str) -> dict[str, Any]:
    """Summary quality badge for one security (ТЗ §12.5 /audit/badge)."""
    rows = find_findings(ticker=ticker, limit=200)
    blocking = [r for r in rows if r["severity"] == BLOCKING]
    warnings = [r for r in rows if r["severity"] == WARNING]
    run = latest_run()
    return {
        "ticker": ticker.upper(),
        "status": "blocking" if blocking else ("warning" if warnings else "ok"),
        "blocking": len(blocking),
        "warnings": len(warnings),
        "metrics_withheld": sorted({r["metric"] for r in blocking if r["metric"]}),
        "reasons": [r["message"] for r in blocking[:5]],
        "last_run_at": (run or {}).get("finished_at"),
    }
