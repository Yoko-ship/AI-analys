"""Admin-reviewed imports from UZSE and OpenInfo.

The exchange/OpenInfo resolver already discovers securities and maps them to an
OpenInfo organisation.  This module adds the missing product boundary: a new
discovery is a *candidate* until a signed-in administrator reviews it, while an
approved candidate becomes part of the public company registry without a code
change or deploy.

The operational ``catalog_companies`` table is intentionally kept.  Collectors
already depend on it for ticker -> org routing, so approval upserts that table
and stores the richer review/audit record beside it in
``catalog_company_imports``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from delisted import DELISTED_TICKERS


ALLOWED_SECTORS = (
    "finance",
    "manufacturing",
    "mining",
    "transport",
    "logistics",
    "telecom",
    "professional",
    "trade",
    "funds",
    "other",
)
DETERMINISTIC_RESOLVERS = {"override", "ticker", "isin", "base_ticker_index", "base_ticker"}
_TICKER_RE = re.compile(r"^[A-Z0-9]{2,40}$")
_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
_LOGOS_PATH = Path(__file__).with_name("company_logos.json")
_STATIC_TICKERS = {str(t).upper() for t in COMPANY_CATALOG.values()}


class CompanyImportError(ValueError):
    """A validation or state error safe to return as an HTTP 4xx detail."""


def _conn():
    import reports_catalog

    return reports_catalog.get_catalog_conn()


def _static_logos() -> dict[str, str]:
    try:
        payload = json.loads(_LOGOS_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:  # noqa: BLE001 - optional presentation metadata
        return {}


def _clean_ticker(value: Any) -> str:
    ticker = str(value or "").strip().upper()
    if not _TICKER_RE.fullmatch(ticker):
        raise CompanyImportError("Ticker must contain 2-40 Latin letters or digits")
    if ticker in DELISTED_TICKERS:
        raise CompanyImportError(f"{ticker} is explicitly delisted")
    return ticker


def _clean_logo(value: Any) -> str | None:
    logo = str(value or "").strip()
    if not logo:
        return None
    if len(logo) > 1000:
        raise CompanyImportError("Logo URL is too long")
    if logo.startswith("/logos/"):
        return logo
    parsed = urlparse(logo)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CompanyImportError("Logo must be an HTTPS/HTTP URL or a /logos/ path")
    return logo


def _candidate(rec: dict[str, Any]) -> dict[str, Any]:
    ticker = _clean_ticker(rec.get("ticker"))
    name = str(rec.get("org_name") or rec.get("company_name") or rec.get("name") or ticker).strip()
    if not name:
        name = ticker
    isin = str(rec.get("isin") or "").strip().upper() or None
    return {
        "ticker": ticker,
        "company_name": name[:240],
        "org_id": str(rec.get("org_id") or "").strip() or None,
        "isin": isin,
        "security_type": str(rec.get("type") or "stock").strip().lower()[:40] or "stock",
        "share_type": str(rec.get("share_type") or "").strip().lower()[:40] or None,
        "sector": COMPANY_SECTORS.get(ticker, "other"),
        "logo_url": _static_logos().get(ticker) or None,
        "resolved_by": str(rec.get("resolved_by") or "").strip() or None,
        "source_payload": json.dumps(rec, ensure_ascii=False, default=str),
    }


def _event(conn, ticker: str, action: str, actor: str | None, detail: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO catalog_company_import_events (ticker, action, actor, detail) VALUES (?,?,?,?)",
        (ticker, action, actor, json.dumps(detail or {}, ensure_ascii=False, default=str)),
    )


def _upsert_candidate(rec: dict[str, Any], *, actor: str | None = None) -> dict[str, Any]:
    item = _candidate(rec)
    conn = _conn()
    try:
        current = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (item["ticker"],)
        ).fetchone()
        with conn:
            if current:
                # Source refreshes must not undo a reviewed correction. Pending
                # rows, on the other hand, should follow the latest source facts.
                if current["status"] == "approved":
                    conn.execute(
                        """
                        UPDATE catalog_company_imports
                        SET source_payload=?, resolved_by=?, updated_at=datetime('now')
                        WHERE ticker=?
                        """,
                        (item["source_payload"], item["resolved_by"], item["ticker"]),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE catalog_company_imports
                        SET company_name=?, org_id=?, isin=?, security_type=?, share_type=?,
                            sector=?, logo_url=COALESCE(?, logo_url), resolved_by=?,
                            source_payload=?, updated_at=datetime('now')
                        WHERE ticker=?
                        """,
                        (
                            item["company_name"], item["org_id"], item["isin"],
                            item["security_type"], item["share_type"], item["sector"],
                            item["logo_url"], item["resolved_by"], item["source_payload"],
                            item["ticker"],
                        ),
                    )
            else:
                status = "approved" if item["ticker"] in _STATIC_TICKERS else "pending"
                reviewed_by = "code catalog" if status == "approved" else None
                reviewed_at = (
                    datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    if reviewed_by else None
                )
                conn.execute(
                    """
                    INSERT INTO catalog_company_imports
                        (ticker, company_name, org_id, isin, security_type, share_type,
                         sector, logo_url, resolved_by, status, source_payload,
                         reviewed_by, reviewed_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        item["ticker"], item["company_name"], item["org_id"], item["isin"],
                        item["security_type"], item["share_type"], item["sector"],
                        item["logo_url"], item["resolved_by"], status,
                        item["source_payload"], reviewed_by, reviewed_at,
                    ),
                )
                _event(conn, item["ticker"], "discovered", actor, {
                    "resolved_by": item["resolved_by"], "status": status,
                })
        row = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (item["ticker"],)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def refresh_candidates(*, force: bool = False, actor: str | None = None) -> dict[str, Any]:
    """Refresh the review queue from UZSE/OpenInfo and return its new state."""
    import entity_resolver

    if force:
        # ``resolve_all`` immediately reuses this refreshed deterministic index.
        entity_resolver.get_org_index(force=True)
    records = entity_resolver.resolve_all()
    seen = record_discovered_candidates(records, actor=actor)
    result = list_imports()
    result["discovered"] = len(records)
    result["seen"] = len(seen)
    return result


def record_discovered_candidates(
    records: list[dict[str, Any]], *, actor: str | None = None,
) -> set[str]:
    """Land already-resolved records in the queue without another source call.

    The hourly catalog discovery uses this hook, so the queue fills even when
    nobody has the admin page open. The explicit Discover button calls the same
    path after forcing a fresh source read.
    """
    seen: set[str] = set()
    for rec in records:
        try:
            item = _upsert_candidate(rec, actor=actor)
        except CompanyImportError:
            continue
        seen.add(item["ticker"])
    return seen


def _catalog_fallback(ticker: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        row = conn.execute(
            """
            SELECT c.ticker, c.company_name, c.org_id,
                   l.isin, l.share_type
            FROM catalog_companies c
            LEFT JOIN catalog_listings l ON l.ticker = c.ticker
            WHERE c.ticker = ?
            """,
            (ticker,),
        ).fetchone()
        if not row:
            return None
        return {
            "ticker": row["ticker"], "name": row["company_name"],
            "org_name": row["company_name"], "org_id": row["org_id"],
            "isin": row["isin"], "share_type": row["share_type"],
            "type": "stock", "resolved_by": "catalog",
        }
    finally:
        conn.close()


def preview_import(ticker: str, *, refresh: bool = True, actor: str | None = None) -> dict[str, Any]:
    """Resolve one ticker and persist it as a pending review candidate."""
    ticker = _clean_ticker(ticker)
    record: dict[str, Any] | None = None
    if refresh:
        import entity_resolver

        for rec in entity_resolver.resolve_all():
            if str(rec.get("ticker") or "").strip().upper() == ticker:
                record = rec
                break
    if record is None:
        record = _catalog_fallback(ticker)
    if record is None:
        raise LookupError(f"{ticker} was not found in the UZSE/OpenInfo registry")

    row = _upsert_candidate(record, actor=actor)
    # Logo is optional and comes from the same OpenInfo organization. Resolve it
    # only for the one previewed company; doing this for the entire discovery
    # queue would turn one refresh into hundreds of upstream calls.
    if not row.get("logo_url") and row.get("org_id"):
        try:
            from openinfo_collector import resolve_company

            profile = resolve_company(row["company_name"])
            if str(profile.get("org_id") or "") == str(row["org_id"]):
                logo = _clean_logo(profile.get("logo"))
                if logo:
                    conn = _conn()
                    try:
                        with conn:
                            conn.execute(
                                "UPDATE catalog_company_imports SET logo_url=?, updated_at=datetime('now') WHERE ticker=?",
                                (logo, ticker),
                            )
                    finally:
                        conn.close()
                    row["logo_url"] = logo
        except Exception:  # noqa: BLE001 - a logo cannot block identity review
            pass

    warnings: list[str] = []
    if not row.get("org_id"):
        warnings.append("OpenInfo organization was not resolved")
    if not row.get("isin"):
        warnings.append("ISIN is missing from the exchange source")
    if row.get("resolved_by") not in DETERMINISTIC_RESOLVERS and row.get("resolved_by") != "catalog":
        warnings.append("Organization was matched by name; verify it before approval")
    if not row.get("logo_url"):
        warnings.append("OpenInfo did not provide a logo")
    return {**row, "warnings": warnings, "can_approve": bool(row.get("org_id"))}


def list_imports(status: str | None = None) -> dict[str, Any]:
    status = str(status or "").strip().lower() or None
    if status and status not in {"pending", "approved", "rejected"}:
        raise CompanyImportError("status must be pending, approved, or rejected")
    conn = _conn()
    try:
        where = "WHERE i.status = ?" if status else ""
        params = (status,) if status else ()
        rows = conn.execute(
            f"""
            SELECT i.*, c.last_synced_at AS catalog_last_synced_at,
                   c.sync_error AS catalog_sync_error
            FROM catalog_company_imports i
            LEFT JOIN catalog_companies c ON c.ticker = i.ticker
            {where}
            ORDER BY CASE i.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END,
                     i.updated_at DESC, i.ticker
            """,
            params,
        ).fetchall()
        counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM catalog_company_imports GROUP BY status"
        ).fetchall()
    finally:
        conn.close()
    summary = {"pending": 0, "approved": 0, "rejected": 0}
    for row in counts:
        summary[str(row["status"])] = int(row["count"] or 0)
    items = [dict(row) for row in rows]
    return {
        "ok": True,
        "count": len(items),
        "summary": summary,
        "unresolved": sum(1 for item in items if not item.get("org_id")),
        "items": items,
    }


def approve_import(ticker: str, values: dict[str, Any], *, actor: str) -> dict[str, Any]:
    ticker = _clean_ticker(ticker)
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not row:
            raise CompanyImportError("Preview this ticker before approving it")
        current = dict(row)
        company_name = str(values.get("company_name") or current["company_name"] or "").strip()
        org_id = str(values.get("org_id") or current.get("org_id") or "").strip()
        isin = str(values.get("isin") or current.get("isin") or "").strip().upper() or None
        sector = str(values.get("sector") or current.get("sector") or "other").strip().lower()
        security_type = str(values.get("security_type") or current.get("security_type") or "stock").strip().lower()
        share_type = str(values.get("share_type") or current.get("share_type") or "").strip().lower() or None
        logo_url = _clean_logo(values.get("logo_url") if "logo_url" in values else current.get("logo_url"))
        note = str(values.get("review_note") or "").strip()[:2000] or None

        if not company_name:
            raise CompanyImportError("Company name is required")
        if len(company_name) > 240:
            raise CompanyImportError("Company name is too long")
        if not org_id:
            raise CompanyImportError("A verified OpenInfo organization ID is required")
        if len(org_id) > 80:
            raise CompanyImportError("OpenInfo organization ID is too long")
        if isin and not _ISIN_RE.fullmatch(isin):
            raise CompanyImportError("ISIN must contain 12 letters/digits and start with a country code")
        if sector not in ALLOWED_SECTORS:
            raise CompanyImportError(f"Unknown sector: {sector}")
        if security_type not in {"stock", "bond", "fund", "other"}:
            raise CompanyImportError(f"Unknown security type: {security_type}")

        if isin:
            duplicate = conn.execute(
                """
                SELECT ticker FROM catalog_company_imports
                WHERE isin = ? AND ticker <> ? AND status = 'approved'
                """,
                (isin, ticker),
            ).fetchone()
            if duplicate:
                raise CompanyImportError(f"ISIN already belongs to {duplicate['ticker']}")

        detail = {
            "before": {k: current.get(k) for k in
                       ("company_name", "org_id", "isin", "sector", "logo_url", "status")},
            "after": {"company_name": company_name, "org_id": org_id, "isin": isin,
                      "sector": sector, "logo_url": logo_url, "status": "approved"},
        }
        with conn:
            conn.execute(
                """
                UPDATE catalog_company_imports
                SET company_name=?, org_id=?, isin=?, sector=?, logo_url=?,
                    security_type=?, share_type=?, status='approved', review_note=?,
                    reviewed_by=?, reviewed_at=datetime('now'), updated_at=datetime('now'),
                    sync_status='queued', sync_error=NULL
                WHERE ticker=?
                """,
                (company_name, org_id, isin, sector, logo_url, security_type,
                 share_type, note, actor, ticker),
            )
            conn.execute(
                """
                INSERT INTO catalog_companies (ticker, company_name, org_id)
                VALUES (?,?,?)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_name=excluded.company_name,
                    org_id=excluded.org_id,
                    sync_error=NULL
                """,
                (ticker, company_name, org_id),
            )
            _event(conn, ticker, "approved", actor, detail)
        saved = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (ticker,)
        ).fetchone()
        return dict(saved)
    finally:
        conn.close()


def reject_import(ticker: str, *, actor: str, note: str | None = None) -> dict[str, Any]:
    ticker = _clean_ticker(ticker)
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (ticker,)
        ).fetchone()
        if not row:
            raise CompanyImportError("Company candidate was not found")
        with conn:
            conn.execute(
                """
                UPDATE catalog_company_imports
                SET status='rejected', review_note=?, reviewed_by=?,
                    reviewed_at=datetime('now'), updated_at=datetime('now')
                WHERE ticker=?
                """,
                (str(note or "").strip()[:2000] or None, actor, ticker),
            )
            _event(conn, ticker, "rejected", actor, {"note": note})
        saved = conn.execute(
            "SELECT * FROM catalog_company_imports WHERE ticker = ?", (ticker,)
        ).fetchone()
        return dict(saved)
    finally:
        conn.close()


def set_sync_status(ticker: str, status: str, error: str | None = None) -> None:
    ticker = _clean_ticker(ticker)
    if status not in {"queued", "running", "complete", "failed"}:
        raise CompanyImportError(f"Unknown sync status: {status}")
    conn = _conn()
    try:
        with conn:
            conn.execute(
                """
                UPDATE catalog_company_imports
                SET sync_status=?, sync_error=?, updated_at=datetime('now')
                WHERE ticker=?
                """,
                (status, str(error or "")[:2000] or None, ticker),
            )
    finally:
        conn.close()


def approved_metadata_map() -> dict[str, dict[str, Any]]:
    """Ticker metadata approved through the panel, for public read overlays."""
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT ticker, company_name, org_id, isin, security_type, share_type,
                   sector, logo_url, reviewed_at
            FROM catalog_company_imports
            WHERE status='approved'
            """
        ).fetchall()
        return {str(row["ticker"]).upper(): dict(row) for row in rows}
    finally:
        conn.close()


def approved_company_name(ticker: str) -> str | None:
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        return None
    return (approved_metadata_map().get(ticker) or {}).get("company_name")
