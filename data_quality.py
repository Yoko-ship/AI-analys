"""Evidence-backed data-quality queue and correction overlay.

The collector-owned catalog remains the record of what a source supplied.  This
module stores a separate, append-only review trail for gaps and corrections;
only an approved correction is allowed to alter a value returned to readers.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

FINANCIAL_FIELDS = frozenset({
    "revenue", "gross_profit", "cash", "total_liabilities", "net_income",
    "operating_income", "total_assets", "total_equity", "current_assets",
    "current_liabilities", "inventories", "noninterest_income",
})
_FORM_RE = re.compile(r"^(NSBU|MSFO|Audition)$")
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,40}$")
_STATUS = {"draft", "approved", "rejected", "reverted"}


class DataQualityError(ValueError):
    """A validation/state error suitable for an admin-facing 4xx response."""


def _conn():
    import reports_catalog
    return reports_catalog.get_catalog_conn()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ensure_schema(conn: Any) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_issues (
            id TEXT PRIMARY KEY,
            source_key TEXT NOT NULL UNIQUE,
            dataset TEXT NOT NULL,
            ticker TEXT NOT NULL,
            form TEXT,
            year INTEGER,
            quarter INTEGER NOT NULL DEFAULT 0,
            field TEXT,
            rule_code TEXT NOT NULL,
            severity TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            original_value REAL,
            details TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dq_issues_status "
                 "ON data_quality_issues(status, severity, updated_at)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_corrections (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            dataset TEXT NOT NULL,
            form TEXT NOT NULL,
            year INTEGER NOT NULL,
            quarter INTEGER NOT NULL DEFAULT 0,
            field TEXT NOT NULL,
            value_thousands_uzs REAL NOT NULL,
            source_url TEXT NOT NULL,
            source_reference TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT,
            supersedes_id TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dq_corrections_lookup "
                 "ON data_corrections(ticker, dataset, form, year, quarter, field, status)")


def _public(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    for key in ("details",):
        if isinstance(row.get(key), str):
            try:
                row[key] = json.loads(row[key])
            except ValueError:
                pass
    return row


def _issue_key(*parts: Any) -> str:
    return ":".join("" if p is None else str(p) for p in parts)


def _upsert_issue(conn: Any, *, source_key: str, dataset: str, ticker: str,
                  form: str | None, year: int | None, quarter: int, field: str | None,
                  rule_code: str, severity: str, original_value: float | None,
                  details: dict[str, Any]) -> bool:
    existing = conn.execute("SELECT id, status FROM data_quality_issues WHERE source_key=?",
                            (source_key,)).fetchone()
    now = _now()
    if existing:
        # A reviewer may have resolved/ignored an issue intentionally. A scan
        # updates the observation but must not silently reopen that decision.
        conn.execute("""UPDATE data_quality_issues
                     SET original_value=?, details=?, severity=?, updated_at=?
                     WHERE source_key=?""",
                     (original_value, json.dumps(details, ensure_ascii=False), severity, now, source_key))
        return False
    conn.execute("""INSERT INTO data_quality_issues
                 (id,source_key,dataset,ticker,form,year,quarter,field,rule_code,
                  severity,status,original_value,details,created_at,updated_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (str(uuid.uuid4()), source_key, dataset, ticker, form, year, quarter,
                  field, rule_code, severity, "open", original_value,
                  json.dumps(details, ensure_ascii=False), now, now))
    return True


def scan_financial_issues() -> dict[str, Any]:
    """Persist financial and catalogue-coverage gaps without changing source rows."""
    conn = _conn()
    try:
        _ensure_schema(conn)
        rows = conn.execute("""SELECT ticker, form, year, quarter, revenue, net_income,
                            total_assets, total_equity, total_liabilities, report_id
                            FROM catalog_financials WHERE form='NSBU'""").fetchall()
        created = 0
        with conn:
            for source in rows:
                row = dict(source)
                ticker, form = str(row["ticker"]).upper(), str(row["form"])
                year, quarter = int(row["year"]), int(row["quarter"] or 0)
                # The bundled correction register is already an approved
                # baseline. It should not flood a new queue with historical
                # gaps that the served read path has already repaired.
                from financial_corrections import corrections_for
                baseline = corrections_for(ticker, f"{year}Q{quarter or 4}")
                for field in ("net_income", "total_assets", "total_equity"):
                    if row.get(field) is None and field not in baseline:
                        created += _upsert_issue(
                            conn, source_key=_issue_key("missing", ticker, form, year, quarter, field),
                            dataset="financials", ticker=ticker, form=form, year=year,
                            quarter=quarter, field=field, rule_code="MISSING_FINANCIAL_FIELD",
                            severity="warning", original_value=None,
                            details={"message": "The parsed filing has no value for this required field.",
                                     "report_id": row.get("report_id")})
                assets, equity, liabilities = (row.get("total_assets"), row.get("total_equity"),
                                                row.get("total_liabilities"))
                if all(v is not None for v in (assets, equity, liabilities)) and assets:
                    variance = abs(float(assets) - float(equity) - float(liabilities)) / abs(float(assets))
                    if variance > 0.001:
                        created += _upsert_issue(
                            conn, source_key=_issue_key("balance", ticker, form, year, quarter),
                            dataset="financials", ticker=ticker, form=form, year=year,
                            quarter=quarter, field=None, rule_code="BALANCE_MISMATCH",
                            severity="blocking", original_value=None,
                            details={"variance": variance, "report_id": row.get("report_id"),
                                     "message": "Assets do not equal equity plus liabilities."})
            # A board instrument can be missing from catalog_companies while it
            # is already present in listings. Include both so the queue sees the
            # exact class of gaps reported by /api/coverage.
            catalog = {
                str(r["ticker"]).upper(): dict(r)
                for r in conn.execute("SELECT ticker, org_id, sync_error FROM catalog_companies").fetchall()
            }
            listed = {str(r["ticker"]).upper() for r in conn.execute(
                "SELECT ticker FROM catalog_listings WHERE ticker IS NOT NULL").fetchall()}
            financial_tickers = {str(r["ticker"]).upper() for r in conn.execute(
                "SELECT DISTINCT ticker FROM catalog_financials WHERE form='NSBU'").fetchall()}
            report_counts = {str(r["ticker"]).upper(): int(r["count"]) for r in conn.execute(
                "SELECT ticker, COUNT(*) AS count FROM catalog_reports GROUP BY ticker").fetchall()}
            for ticker in set(catalog) | listed:
                company = catalog.get(ticker, {})
                if not company.get("org_id"):
                    created += _upsert_issue(
                        conn, source_key=_issue_key("unresolved", ticker), dataset="catalog",
                        ticker=ticker, form=None, year=None, quarter=0, field=None,
                        rule_code="UNRESOLVED_ISSUER", severity="blocking", original_value=None,
                        details={"message": "No issuer mapping is available for this security."})
                if ticker not in financial_tickers:
                    created += _upsert_issue(
                        conn, source_key=_issue_key("coverage", ticker, "financials"), dataset="coverage",
                        ticker=ticker, form="NSBU", year=None, quarter=0, field=None,
                        rule_code="MISSING_FINANCIAL_COVERAGE", severity="warning", original_value=None,
                        details={"message": "No NSBU financial record is available for this security."})
                if not report_counts.get(ticker):
                    created += _upsert_issue(
                        conn, source_key=_issue_key("coverage", ticker, "reports"), dataset="coverage",
                        ticker=ticker, form="NSBU", year=None, quarter=0, field=None,
                        rule_code="MISSING_REPORT_COVERAGE", severity="info", original_value=None,
                        details={"message": "No linked source report is available for this security."})
                if company.get("sync_error"):
                    created += _upsert_issue(
                        conn, source_key=_issue_key("sync", ticker), dataset="catalog", ticker=ticker,
                        form=None, year=None, quarter=0, field=None, rule_code="SOURCE_SYNC_FAILED",
                        severity="warning", original_value=None,
                        details={"message": str(company["sync_error"])[:2000]})
        return {"ok": True, "scanned": len(rows) + len(set(catalog) | listed), "created": created}
    finally:
        conn.close()


def list_issues(status: str | None = None, limit: int = 300) -> dict[str, Any]:
    conn = _conn()
    try:
        _ensure_schema(conn)
        sql = "SELECT * FROM data_quality_issues"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY CASE severity WHEN 'blocking' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        items = [_public(dict(r)) for r in conn.execute(sql, params).fetchall()]
        counts = {r["status"]: r["count"] for r in conn.execute(
            "SELECT status, COUNT(*) AS count FROM data_quality_issues GROUP BY status").fetchall()}
        return {"ok": True, "items": items, "counts": counts}
    finally:
        conn.close()


def list_corrections(ticker: str | None = None, limit: int = 300) -> dict[str, Any]:
    conn = _conn()
    try:
        _ensure_schema(conn)
        sql, params = "SELECT * FROM data_corrections", []
        if ticker:
            sql += " WHERE ticker=?"
            params.append(str(ticker).upper())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        return {"ok": True, "items": [dict(r) for r in conn.execute(sql, params).fetchall()]}
    finally:
        conn.close()


def _validate(payload: dict[str, Any]) -> dict[str, Any]:
    ticker = str(payload.get("ticker") or "").strip().upper()
    field, form = str(payload.get("field") or "").strip(), str(payload.get("form") or "NSBU").strip()
    if not _TICKER_RE.fullmatch(ticker):
        raise DataQualityError("Ticker must contain 2-40 Latin letters or digits")
    if field not in FINANCIAL_FIELDS:
        raise DataQualityError("Unsupported financial field")
    if not _FORM_RE.fullmatch(form):
        raise DataQualityError("Unsupported report form")
    try:
        year, quarter = int(payload.get("year")), int(payload.get("quarter") or 0)
        value = float(payload.get("value_thousands_uzs"))
    except (TypeError, ValueError):
        raise DataQualityError("Year, quarter and value must be numeric") from None
    if not 2000 <= year <= 2100 or not 0 <= quarter <= 4 or not math.isfinite(value):
        raise DataQualityError("Invalid period or correction value")
    source_url = str(payload.get("source_url") or "").strip()
    parsed = urlparse(source_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise DataQualityError("A valid evidence URL is required")
    source_reference = str(payload.get("source_reference") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if not source_reference or not reason:
        raise DataQualityError("Source reference and reason are required")
    return {"ticker": ticker, "form": form, "year": year, "quarter": quarter,
            "field": field, "value_thousands_uzs": value, "source_url": source_url,
            "source_reference": source_reference[:500], "reason": reason[:2000]}


def create_correction(payload: dict[str, Any], actor: str) -> dict[str, Any]:
    data = _validate(payload)
    conn = _conn()
    try:
        _ensure_schema(conn)
        now, record_id = _now(), str(uuid.uuid4())
        with conn:
            conn.execute("""INSERT INTO data_corrections
                         (id,ticker,dataset,form,year,quarter,field,value_thousands_uzs,
                          source_url,source_reference,reason,status,created_by,created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (record_id, data["ticker"], "financials", data["form"], data["year"],
                          data["quarter"], data["field"], data["value_thousands_uzs"],
                          data["source_url"], data["source_reference"], data["reason"],
                          "draft", actor, now))
        row = conn.execute("SELECT * FROM data_corrections WHERE id=?", (record_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def review_correction(record_id: str, status: str, actor: str, note: str | None = None) -> dict[str, Any]:
    if status not in {"approved", "rejected", "reverted"}:
        raise DataQualityError("Review status must be approved, rejected or reverted")
    conn = _conn()
    try:
        _ensure_schema(conn)
        record = conn.execute("SELECT * FROM data_corrections WHERE id=?", (record_id,)).fetchone()
        if not record:
            raise DataQualityError("Correction not found")
        record = dict(record)
        if record["status"] != "draft" and status != "reverted":
            raise DataQualityError("Only a draft correction can be approved or rejected")
        if status == "reverted" and record["status"] != "approved":
            raise DataQualityError("Only an approved correction can be reverted")
        now = _now()
        with conn:
            if status == "approved":
                # One active answer per exact data point. Earlier approved records
                # remain auditable but cease to be served.
                conn.execute("""UPDATE data_corrections SET status='reverted', reviewed_by=?,
                             reviewed_at=?, review_note='Superseded by a newer approved correction'
                             WHERE ticker=? AND dataset='financials' AND form=? AND year=?
                             AND quarter=? AND field=? AND status='approved'""",
                             (actor, now, record["ticker"], record["form"], record["year"],
                              record["quarter"], record["field"]))
            conn.execute("""UPDATE data_corrections SET status=?, reviewed_by=?, reviewed_at=?,
                         review_note=? WHERE id=?""", (status, actor, now, (note or "")[:2000], record_id))
            if status == "approved":
                conn.execute("""UPDATE data_quality_issues SET status='resolved', resolved_at=?,
                             resolved_by=?, updated_at=? WHERE dataset='financials' AND ticker=?
                             AND form=? AND year=? AND quarter=? AND field=? AND status='open'""",
                             (now, actor, now, record["ticker"], record["form"], record["year"],
                              record["quarter"], record["field"]))
        row = conn.execute("SELECT * FROM data_corrections WHERE id=?", (record_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def approved_corrections_for(ticker: str, form: str, year: int, quarter: int) -> dict[str, float]:
    """Return database-approved values in catalog units (thousands of UZS)."""
    conn = _conn()
    try:
        _ensure_schema(conn)
        rows = conn.execute("""SELECT field, value_thousands_uzs FROM data_corrections
                             WHERE ticker=? AND dataset='financials' AND form=? AND year=?
                             AND quarter=? AND status='approved'""",
                            (str(ticker).upper(), form, year, quarter)).fetchall()
        return {str(r["field"]): float(r["value_thousands_uzs"]) for r in rows}
    finally:
        conn.close()
