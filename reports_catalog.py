from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from db import APP_DATA_DIR, sqlite_connect
from openinfo_collector import (
    OPENINFO_API_BASE,
    OPENINFO_WEB_BASE,
    _build_report_document,
    _json_get,
    _make_session,
    parse_excel_report_document,
    resolve_company,
)

logger = logging.getLogger(__name__)

CATALOG_SYNC_TTL_HOURS = int(os.getenv("CATALOG_SYNC_TTL_HOURS", "6"))
_SYNC_LOCK = threading.Lock()
# Serialize the lazy financials-cache filler so overlapping market loads don't
# parse the same reports concurrently.
_FIN_LOCK = threading.Lock()
FINANCIALS_TTL_DAYS = int(os.getenv("FINANCIALS_TTL_DAYS", "14"))
FINANCIALS_BATCH = int(os.getenv("FINANCIALS_BATCH", "12"))

# Inverted catalog: ticker → company_name (take first match if duplicates)
_TICKER_TO_NAME: dict[str, str] = {}
for _name, _ticker in COMPANY_CATALOG.items():
    if _ticker not in _TICKER_TO_NAME:
        _TICKER_TO_NAME[_ticker] = _name


# ---------------------------------------------------------------------------
# DB bootstrap
# ---------------------------------------------------------------------------

def _catalog_db_path() -> str:
    path = APP_DATA_DIR / "reports_catalog.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS catalog_companies (
            ticker          TEXT PRIMARY KEY,
            company_name    TEXT NOT NULL,
            org_id          TEXT,
            last_synced_at  TEXT,
            sync_error      TEXT
        );

        CREATE TABLE IF NOT EXISTS catalog_reports (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker              TEXT NOT NULL,
            report_form         TEXT NOT NULL,
            period_type         TEXT NOT NULL,
            year                INTEGER,
            quarter             INTEGER NOT NULL DEFAULT 0,
            title               TEXT,
            published_at        TEXT,
            pdf_url             TEXT,
            excel_url           TEXT,
            excel_url_form1     TEXT,
            openinfo_report_id  TEXT,
            object_id           TEXT,
            synced_at           TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(ticker, report_form, period_type, year, quarter)
        );

        CREATE INDEX IF NOT EXISTS idx_cat_ticker ON catalog_reports(ticker);
        CREATE INDEX IF NOT EXISTS idx_cat_year   ON catalog_reports(year);

        CREATE TABLE IF NOT EXISTS catalog_new_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            report_form TEXT NOT NULL,
            period_type TEXT NOT NULL,
            year        INTEGER,
            quarter     INTEGER NOT NULL DEFAULT 0,
            title       TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cnr_ticker   ON catalog_new_reports(ticker);
        CREATE INDEX IF NOT EXISTS idx_cnr_detected ON catalog_new_reports(detected_at);

        CREATE TABLE IF NOT EXISTS catalog_ratios (
            ticker         TEXT NOT NULL,
            form           TEXT NOT NULL,
            year           INTEGER NOT NULL,
            quarter        INTEGER NOT NULL DEFAULT 0,
            roa            REAL,
            roe            REAL,
            net_margin     REAL,
            debt_ratio     REAL,
            debt_to_equity REAL,
            updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, form, year, quarter)
        );

        CREATE TABLE IF NOT EXISTS catalog_financials (
            ticker            TEXT NOT NULL,
            form              TEXT NOT NULL DEFAULT 'NSBU',
            year              INTEGER NOT NULL,
            quarter           INTEGER NOT NULL DEFAULT 0,
            revenue           REAL,
            gross_profit      REAL,
            cash              REAL,
            total_liabilities REAL,
            net_income        REAL,
            operating_income  REAL,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, form, year, quarter)
        );
        CREATE INDEX IF NOT EXISTS idx_cat_fin_ticker ON catalog_financials(ticker);
    """)
    conn.commit()


def get_catalog_conn() -> sqlite3.Connection:
    conn = sqlite_connect(_catalog_db_path())
    _init_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_year(report: dict[str, Any]) -> int | None:
    props = report.get("properties") or {}
    for field in ("reporting_year", "year"):
        v = props.get(field)
        if v is not None:
            try:
                yr = int(v)
                if 2000 <= yr <= 2100:
                    return yr
            except (TypeError, ValueError):
                pass
    title = str(props.get("report_title") or "")
    m = re.search(r"\b(20[12]\d)\b", title)
    if m:
        return int(m.group(1))
    pub = str(report.get("pub_date") or "")
    if len(pub) >= 4:
        try:
            yr = int(pub[:4])
            pt = str(props.get("report_type") or "annual").lower()
            return yr - 1 if pt == "annual" else yr
        except (TypeError, ValueError):
            pass
    return None


def _extract_quarter(period_str: str) -> int | None:
    """Parse quarter number from strings like 'Q1 2024' or 'I квартал 2024'."""
    m = re.search(r"Q([1-3])", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r"([1-3])\s*квартал", period_str, re.IGNORECASE)
    if m:
        return int(m.group(1))
    roman = {"I": 1, "II": 2, "III": 3}
    m = re.search(r"\b(III|II|I)\b\s*квартал", period_str, re.IGNORECASE)
    if m:
        return roman.get(m.group(1).upper())
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(last_synced_at: str | None) -> bool:
    if not last_synced_at:
        return False
    try:
        ts = datetime.fromisoformat(last_synced_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - ts < timedelta(hours=CATALOG_SYNC_TTL_HOURS)
    except (ValueError, TypeError):
        return False


def _upsert_report(
    conn: sqlite3.Connection,
    ticker: str,
    *,
    report_form: str,
    period_type: str,
    year: int | None,
    quarter: int,
    title: str | None,
    published_at: str | None,
    pdf_url: str | None,
    excel_url: str | None,
    excel_url_form1: str | None,
    openinfo_report_id: str | None,
    object_id: str | None,
) -> bool:
    """Insert or update a report row. Returns True if a new row was inserted."""
    # Check existence first — SQLite upsert always returns rowcount=1 so we
    # can't distinguish insert vs update from the cursor alone.
    existing = conn.execute(
        "SELECT id FROM catalog_reports WHERE ticker=? AND report_form=? AND period_type=? AND year IS ? AND quarter=?",
        (ticker, report_form, period_type, year, quarter),
    ).fetchone()
    is_new = existing is None

    conn.execute(
        """
        INSERT INTO catalog_reports
            (ticker, report_form, period_type, year, quarter, title,
             published_at, pdf_url, excel_url, excel_url_form1,
             openinfo_report_id, object_id, synced_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(ticker, report_form, period_type, year, quarter) DO UPDATE SET
            title               = excluded.title,
            published_at        = excluded.published_at,
            pdf_url             = COALESCE(excluded.pdf_url, pdf_url),
            excel_url           = COALESCE(excluded.excel_url, excel_url),
            excel_url_form1     = COALESCE(excluded.excel_url_form1, excel_url_form1),
            openinfo_report_id  = COALESCE(excluded.openinfo_report_id, openinfo_report_id),
            object_id           = COALESCE(excluded.object_id, object_id),
            synced_at           = datetime('now')
        """,
        (
            ticker, report_form, period_type, year, quarter, title,
            published_at, pdf_url, excel_url, excel_url_form1,
            openinfo_report_id, object_id,
        ),
    )
    if is_new:
        try:
            conn.execute(
                "INSERT INTO catalog_new_reports (ticker, report_form, period_type, year, quarter, title) VALUES (?,?,?,?,?,?)",
                (ticker, report_form, period_type, year, quarter, title),
            )
        except Exception:
            pass
    return is_new


def _cleanup_old_notifications(conn: sqlite3.Connection, days: int = 30) -> None:
    conn.execute(
        "DELETE FROM catalog_new_reports WHERE detected_at < datetime('now', ?)",
        (f"-{days} days",),
    )


# ---------------------------------------------------------------------------
# Sync — one company
# ---------------------------------------------------------------------------

# Legal-form tokens that openinfo's /reports/main/ search does NOT match well
# when appended to the brand name (e.g. '"Aloqabank" ATB' → 0 hits, but
# 'Aloqabank' → 54 hits). Stripping them is what lets org_type (and therefore
# the NSBU Excel export URL) resolve for banks/insurers/JSCs.
_LEGAL_FORM_TOKENS = {
    "atb", "aj", "ak", "ato", "mchj", "qmj", "xk", "uk", "ooo", "aytb",
    "ао", "оао", "зао", "акб", "хк", "ук", "чп", "ип", "atb.", "aj.",
}


def _org_search_terms(company_name: str) -> list[str]:
    """Best-first candidate queries for openinfo's /reports/main/ search.

    openinfo's search engine fails on the full legal name (quotes + legal-form
    suffix), so we also try the de-quoted name and the bare brand token(s).
    """
    name = (company_name or "").strip()
    terms: list[str] = []
    if name:
        terms.append(name)
    cleaned = re.sub(r"""["«»“”'`]""", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned not in terms:
        terms.append(cleaned)
    tokens = [t for t in cleaned.split(" ") if t]
    brand = [t for t in tokens if t.lower().strip(".") not in _LEGAL_FORM_TOKENS]
    phrase = " ".join(brand).strip()
    if phrase and phrase not in terms:
        terms.append(phrase)
    if brand and brand[0] not in terms:
        terms.append(brand[0])
    return terms


def _fetch_main_results(session: Any, company_name: str, org_id: Any) -> tuple[list[dict], str | None]:
    """Return (org-filtered /reports/main/ records, org_type) for a company.

    Tries progressively cleaner search terms until one returns records for this
    org_id — openinfo's search misses the full legal name for many issuers.
    """
    for query in _org_search_terms(company_name):
        try:
            payload = _json_get(session, "/reports/main/", {"page": 1, "page_size": 200, "search": query})
        except Exception:
            continue
        results = list(payload.get("results") or []) if isinstance(payload, dict) else []
        filtered = [r for r in results if str(r.get("organization")) == str(org_id)]
        if filtered:
            org_type = next(
                ((r.get("properties") or {}).get("org_type") for r in filtered if (r.get("properties") or {}).get("org_type")),
                None,
            )
            return filtered, org_type
    return [], None


def _nsbu_export_urls(report_id: Any, period_type: str, org_type: str | None) -> tuple[str | None, str | None]:
    """Build (pdf_url, excel_url) for an NSBU accounting-report from its id.

    NSBU records come from the ``/reports/accounting-report/`` endpoint, whose
    shape carries the financial line-items but no document URLs — so
    ``_build_report_document`` (written for the ``/reports/main/`` shape) returns
    nothing and the download buttons never appear. openinfo serves the PDF at
    ``/ru/reports/to_pdf<id>/`` and the Excel via the export-excel API, which also
    needs the period type and the issuer's ``org_type`` (e.g. "bank", "jsc").
    Without a correct org_type the Excel export returns HTTP 400, so excel_url is
    omitted when org_type is unknown (the PDF link still works).
    """
    if not report_id:
        return None, None
    pdf_url = f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{report_id}/"
    excel_url = None
    if org_type:
        excel_url = f"{OPENINFO_API_BASE}/reports/export-excel/?" + urlencode(
            {"report_type": period_type, "org_type": org_type, "report_id": report_id, "lang": "ru"}
        )
    return pdf_url, excel_url


def sync_company(ticker: str, company_name: str, *, force: bool = False) -> dict[str, Any]:
    conn = get_catalog_conn()

    # Check freshness unless forced
    if not force:
        row = conn.execute(
            "SELECT last_synced_at FROM catalog_companies WHERE ticker = ?", (ticker,)
        ).fetchone()
        if row and _is_fresh(row["last_synced_at"]):
            conn.close()
            return {"ticker": ticker, "skipped": True}

    session = _make_session()
    errors: list[str] = []
    added = 0

    try:
        company = resolve_company(company_name, session=session)
        org_id = company.get("org_id")
        # Preferred share tickers (e.g. AGBAP) share the same org as the base ticker (AGBA).
        # If resolution failed, retry with the base ticker's company name.
        if not org_id and ticker.endswith("P"):
            base_name = _TICKER_TO_NAME.get(ticker[:-1])
            if base_name and base_name != company_name:
                company = resolve_company(base_name, session=session)
                org_id = company.get("org_id")
        if not org_id:
            raise LookupError(f"No org_id for {company_name!r}")
    except Exception as exc:
        err = str(exc)
        errors.append(err)
        with conn:
            conn.execute(
                """
                INSERT INTO catalog_companies (ticker, company_name, last_synced_at, sync_error)
                VALUES (?,?,datetime('now'),?)
                ON CONFLICT(ticker) DO UPDATE SET sync_error=excluded.sync_error, last_synced_at=datetime('now')
                """,
                (ticker, company_name, err),
            )
        conn.close()
        return {"ticker": ticker, "org_id": None, "added": 0, "errors": errors}

    base = f"/reports/accounting-report/{org_id}/"

    # Fetch the /reports/main/ listing up front: it supplies the issuer's
    # org_type (needed to build NSBU Excel export URLs) and the MSFO/Audition
    # records consumed further below. openinfo's search misses the full legal
    # name for many issuers, so _fetch_main_results retries with cleaner terms.
    try:
        main_results, org_type = _fetch_main_results(session, company_name, org_id)
    except Exception as exc:
        main_results, org_type = [], None
        errors.append(f"reports/main: {exc}")

    # ---- NSBU annual -------------------------------------------------------
    try:
        form2_annual = _json_get(session, base, {"accounting_type": "form2", "report_type": "annual"})
        if not isinstance(form2_annual, list):
            form2_annual = []
    except Exception as exc:
        form2_annual = []
        errors.append(f"NSBU annual form2: {exc}")

    try:
        form1_annual = _json_get(session, base, {"accounting_type": "form1", "report_type": "annual"})
        if not isinstance(form1_annual, list):
            form1_annual = []
    except Exception as exc:
        form1_annual = []
        errors.append(f"NSBU annual form1: {exc}")

    # Index form1 by reporting_year for quick lookup
    form1_annual_by_year: dict[int, dict] = {}
    for rec in form1_annual:
        yr = rec.get("reporting_year")
        if isinstance(yr, int):
            doc = _build_report_document(rec)
            form1_annual_by_year[yr] = doc

    with conn:
        for rec in form2_annual:
            yr = rec.get("reporting_year")
            if not isinstance(yr, int):
                continue
            doc2 = _build_report_document(rec)
            doc1 = form1_annual_by_year.get(yr)
            pdf_url, excel_url = _nsbu_export_urls(doc2.get("id"), "annual", org_type)
            excel_url_form1 = _nsbu_export_urls(doc1.get("id"), "annual", org_type)[1] if doc1 else None
            new = _upsert_report(
                conn, ticker,
                report_form="NSBU",
                period_type="annual",
                year=yr,
                quarter=0,
                title=doc2.get("title"),
                published_at=doc2.get("published_at"),
                pdf_url=pdf_url,
                excel_url=excel_url,
                excel_url_form1=excel_url_form1,
                openinfo_report_id=str(doc2.get("id") or ""),
                object_id=str(doc2.get("object_id") or ""),
            )
            if new:
                added += 1

    # ---- NSBU quarterly ----------------------------------------------------
    try:
        form2_quarter = _json_get(session, base, {"accounting_type": "form2", "report_type": "quarter"})
        if not isinstance(form2_quarter, list):
            form2_quarter = []
    except Exception as exc:
        form2_quarter = []
        errors.append(f"NSBU quarter form2: {exc}")

    try:
        form1_quarter = _json_get(session, base, {"accounting_type": "form1", "report_type": "quarter"})
        if not isinstance(form1_quarter, list):
            form1_quarter = []
    except Exception as exc:
        form1_quarter = []
        errors.append(f"NSBU quarter form1: {exc}")

    # Index form1 quarterly by (year, quarter)
    form1_quarter_by_yq: dict[tuple[int, int], dict] = {}
    for rec in form1_quarter:
        period_str = str(rec.get("period") or "")
        yr = rec.get("reporting_year")
        q = _extract_quarter(period_str)
        if isinstance(yr, int) and q:
            doc = _build_report_document(rec)
            form1_quarter_by_yq[(yr, q)] = doc

    with conn:
        for rec in form2_quarter:
            period_str = str(rec.get("period") or "")
            yr = rec.get("reporting_year")
            q = _extract_quarter(period_str)
            if not isinstance(yr, int) or not q:
                continue
            doc2 = _build_report_document(rec)
            doc1 = form1_quarter_by_yq.get((yr, q))
            pdf_url, excel_url = _nsbu_export_urls(doc2.get("id"), "quarter", org_type)
            excel_url_form1 = _nsbu_export_urls(doc1.get("id"), "quarter", org_type)[1] if doc1 else None
            new = _upsert_report(
                conn, ticker,
                report_form="NSBU",
                period_type="quarter",
                year=yr,
                quarter=q,
                title=doc2.get("title"),
                published_at=doc2.get("published_at"),
                pdf_url=pdf_url,
                excel_url=excel_url,
                excel_url_form1=excel_url_form1,
                openinfo_report_id=str(doc2.get("id") or ""),
                object_id=str(doc2.get("object_id") or ""),
            )
            if new:
                added += 1

    # ---- MSFO + Audition from the /reports/main/ listing fetched above -------
    msfo_results = [r for r in main_results if r.get("report_type") in {"MSFO", "Audition"}]
    with conn:
        for rec in msfo_results:
            doc = _build_report_document(rec)
            form = doc.get("report_form") or rec.get("report_type")
            if form not in ("MSFO", "Audition"):
                continue
            pt = str(doc.get("period_type") or "annual").lower()
            yr = _extract_year(rec)
            q = 0
            if pt == "quarter":
                props = rec.get("properties") or {}
                period_str = str(props.get("report_title") or "")
                q = _extract_quarter(period_str) or 0
            new = _upsert_report(
                conn, ticker,
                report_form=form,
                period_type=pt if pt in ("annual", "quarter") else "annual",
                year=yr,
                quarter=q,
                title=doc.get("title"),
                published_at=doc.get("published_at"),
                pdf_url=doc.get("pdf_url"),
                excel_url=doc.get("excel_url"),
                excel_url_form1=None,
                openinfo_report_id=str(doc.get("id") or ""),
                object_id=str(doc.get("object_id") or ""),
            )
            if new:
                added += 1

    # ---- Update company row -------------------------------------------------
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_companies (ticker, company_name, org_id, last_synced_at, sync_error)
            VALUES (?,?,?,datetime('now'),NULL)
            ON CONFLICT(ticker) DO UPDATE SET
                company_name   = excluded.company_name,
                org_id         = excluded.org_id,
                last_synced_at = datetime('now'),
                sync_error     = NULL
            """,
            (ticker, company_name, org_id),
        )

    conn.close()
    return {"ticker": ticker, "org_id": org_id, "added": added, "errors": errors}


# ---------------------------------------------------------------------------
# Sync — audition reports (separate endpoint, no org_id filter supported)
# ---------------------------------------------------------------------------

def _sync_auditions(conn: sqlite3.Connection, session: Any) -> int:
    """Fetch all /reports/audition/ records and upsert for known org_ids."""
    from openinfo_collector import OPENINFO_WEB_BASE

    # Build reverse map: org_id (str) → ticker from already-synced companies
    org_to_ticker: dict[str, str] = {
        str(row["org_id"]): row["ticker"]
        for row in conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL"
        ).fetchall()
    }
    if not org_to_ticker:
        return 0

    added = 0
    page = 1
    while True:
        try:
            payload = _json_get(session, "/reports/audition/", {"page": page, "page_size": 200})
        except Exception as exc:
            logger.warning("audition page %d failed: %s", page, exc)
            break
        results = payload.get("results") or []
        if not results:
            break
        with conn:
            for rec in results:
                org_id_str = str(rec.get("organization") or "")
                ticker = org_to_ticker.get(org_id_str)
                if not ticker:
                    continue
                pdf_file = rec.get("pdf_file") or ""
                pdf_url = f"{OPENINFO_WEB_BASE}/media/{pdf_file}" if pdf_file else None
                title_raw = rec.get("title") or ""
                yr = None
                m = re.search(r"\b(20[12]\d)\b", title_raw)
                if m:
                    yr = int(m.group(1))
                elif rec.get("pub_date"):
                    try:
                        yr = int(str(rec["pub_date"])[:4]) - 1
                    except (TypeError, ValueError):
                        pass
                new = _upsert_report(
                    conn, ticker,
                    report_form="Audition",
                    period_type="annual",
                    year=yr,
                    quarter=0,
                    title=title_raw,
                    published_at=rec.get("pub_date"),
                    pdf_url=pdf_url,
                    excel_url=None,
                    excel_url_form1=None,
                    openinfo_report_id=str(rec.get("id") or ""),
                    object_id=None,
                )
                if new:
                    added += 1
        if len(results) < 200:
            break
        page += 1

    return added


# ---------------------------------------------------------------------------
# Sync — all companies
# ---------------------------------------------------------------------------

def sync_all(tickers: list[str] | None = None, *, force: bool = False) -> dict[str, Any]:
    with _SYNC_LOCK:
        targets = tickers if tickers else list(_TICKER_TO_NAME.keys())
        total = len(targets)
        synced = 0
        skipped = 0
        all_errors: list[dict] = []

        try:
            _conn = get_catalog_conn()
            _cleanup_old_notifications(_conn)
            _conn.commit()
            _conn.close()
        except Exception:
            pass

        for ticker in targets:
            # Skip preferred share tickers (e.g. AGBAP) — they map to the same
            # org on openinfo as their base ticker (AGBA) and would duplicate reports.
            if ticker.endswith("P") and ticker[:-1] in _TICKER_TO_NAME:
                skipped += 1
                continue
            name = _TICKER_TO_NAME.get(ticker, ticker)
            try:
                result = sync_company(ticker, name, force=force)
                if result.get("skipped"):
                    skipped += 1
                else:
                    synced += 1
                    if result.get("errors"):
                        all_errors.append({"ticker": ticker, "errors": result["errors"]})
            except Exception as exc:
                all_errors.append({"ticker": ticker, "errors": [str(exc)]})

        # Sync audit reports globally (endpoint has no org_id filter)
        try:
            conn = get_catalog_conn()
            session = _make_session()
            audit_added = _sync_auditions(conn, session)
            conn.close()
            logger.info("Audition sync added %d records", audit_added)
        except Exception as exc:
            all_errors.append({"ticker": "_audition", "errors": [str(exc)]})

        return {
            "total": total,
            "synced": synced,
            "skipped": skipped,
            "errors": all_errors,
        }


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def get_company_index(ticker: str) -> dict[str, Any]:
    conn = get_catalog_conn()
    company_row = conn.execute(
        "SELECT company_name, org_id, last_synced_at FROM catalog_companies WHERE ticker = ?",
        (ticker,),
    ).fetchone()

    reports = conn.execute(
        """
        SELECT report_form, period_type, year, quarter, pdf_url, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ?
        ORDER BY year DESC, quarter DESC
        """,
        (ticker,),
    ).fetchall()
    conn.close()

    availability: dict[str, dict[str, list]] = {
        "NSBU": {"annual": [], "quarter": []},
        "MSFO": {"annual": [], "quarter": []},
        "Audition": {"annual": [], "quarter": []},
    }
    years_seen: set[int] = set()

    for r in reports:
        form = r["report_form"]
        pt = r["period_type"]
        yr = r["year"]
        if yr:
            years_seen.add(yr)
        entry = {
            "year": yr,
            "quarter": r["quarter"],
            "has_pdf": bool(r["pdf_url"]),
            "has_excel": bool(r["excel_url"]),
            "has_excel_form1": bool(r["excel_url_form1"]),
            "pdf_url": r["pdf_url"],
            "excel_url": r["excel_url"],
            "excel_url_form1": r["excel_url_form1"],
        }
        bucket = availability.setdefault(form, {"annual": [], "quarter": []})
        bucket.setdefault(pt, []).append(entry)

    return {
        "ticker": ticker,
        "company_name": company_row["company_name"] if company_row else _TICKER_TO_NAME.get(ticker, ticker),
        "sector": COMPANY_SECTORS.get(ticker),
        "org_id": company_row["org_id"] if company_row else None,
        "last_synced_at": company_row["last_synced_at"] if company_row else None,
        "availability": availability,
        "years": sorted(years_seen, reverse=True),
        "report_count": len(reports),
    }


def get_report_urls(ticker: str, form: str, year: int, quarter: int) -> dict[str, Any] | None:
    conn = get_catalog_conn()
    row = conn.execute(
        """
        SELECT pdf_url, excel_url, excel_url_form1, title, published_at, period_type
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND year = ? AND quarter = ?
        """,
        (ticker, form, year, quarter),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "pdf_url": row["pdf_url"],
        "excel_url": row["excel_url"],
        "excel_url_form1": row["excel_url_form1"],
        "title": row["title"],
        "published_at": row["published_at"],
        "period_type": row["period_type"],
    }


def list_companies_with_stats() -> list[dict[str, Any]]:
    conn = get_catalog_conn()
    rows = conn.execute(
        """
        SELECT
            c.ticker,
            c.company_name,
            c.org_id,
            c.last_synced_at,
            SUM(CASE WHEN r.report_form = 'NSBU'      THEN 1 ELSE 0 END) AS nsbu_count,
            SUM(CASE WHEN r.report_form = 'MSFO'      THEN 1 ELSE 0 END) AS msfo_count,
            SUM(CASE WHEN r.report_form = 'Audition'  THEN 1 ELSE 0 END) AS audit_count,
            COUNT(r.id) AS total_count
        FROM catalog_companies c
        LEFT JOIN catalog_reports r ON r.ticker = c.ticker
        GROUP BY c.ticker
        ORDER BY c.ticker
        """
    ).fetchall()
    conn.close()
    # Exclude preferred share tickers that duplicate their base ticker's data
    base_tickers = {r["ticker"] for r in rows}
    return [
        dict(r) for r in rows
        if not (r["ticker"].endswith("P") and r["ticker"][:-1] in base_tickers)
    ]


def get_catalog_stats() -> dict[str, Any]:
    conn = get_catalog_conn()
    totals = conn.execute(
        """
        SELECT
            COUNT(DISTINCT ticker) AS companies_synced,
            COUNT(*) AS total_reports,
            SUM(CASE WHEN report_form = 'NSBU'     THEN 1 ELSE 0 END) AS nsbu,
            SUM(CASE WHEN report_form = 'MSFO'     THEN 1 ELSE 0 END) AS msfo,
            SUM(CASE WHEN report_form = 'Audition' THEN 1 ELSE 0 END) AS audit
        FROM catalog_reports
        """
    ).fetchone()
    last_sync = conn.execute(
        "SELECT MAX(last_synced_at) AS ls FROM catalog_companies"
    ).fetchone()
    conn.close()
    return {
        "companies_synced": totals["companies_synced"] or 0,
        "total_reports": totals["total_reports"] or 0,
        "nsbu": totals["nsbu"] or 0,
        "msfo": totals["msfo"] or 0,
        "audit": totals["audit"] or 0,
        "last_sync": last_sync["ls"] if last_sync else None,
    }


def upsert_ratio_cache(ticker: str, form: str, year: int, quarter: int, metrics: dict[str, Any]) -> None:
    conn = get_catalog_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_ratios
                (ticker, form, year, quarter, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                roa=excluded.roa, roe=excluded.roe, net_margin=excluded.net_margin,
                debt_ratio=excluded.debt_ratio, debt_to_equity=excluded.debt_to_equity,
                updated_at=datetime('now')
            """,
            (ticker, form, year, quarter,
             metrics.get("ROA"), metrics.get("ROE"), metrics.get("net_margin"),
             metrics.get("debt_ratio"), metrics.get("debt_to_equity")),
        )
    conn.close()


_FINANCIAL_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",
                   "net_income", "operating_income")


def upsert_financials_cache(ticker: str, form: str, year: int, quarter: int,
                            values: dict[str, Any]) -> None:
    """Store the six NSBU headline indicators for a ticker/period."""
    conn = get_catalog_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_financials
                (ticker, form, year, quarter, revenue, gross_profit, cash,
                 total_liabilities, net_income, operating_income, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                revenue=excluded.revenue, gross_profit=excluded.gross_profit,
                cash=excluded.cash, total_liabilities=excluded.total_liabilities,
                net_income=excluded.net_income, operating_income=excluded.operating_income,
                updated_at=datetime('now')
            """,
            (ticker, form, year, quarter,
             values.get("revenue"), values.get("gross_profit"), values.get("cash"),
             values.get("total_liabilities"), values.get("net_income"),
             values.get("operating_income")),
        )
    conn.close()


def get_all_financials(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Return the most recent cached indicators per ticker: {ticker: {...}}.

    Picks the latest period (year, then quarter) available for each ticker.
    """
    conn = get_catalog_conn()
    rows = conn.execute(
        """
        SELECT f.ticker, f.year, f.quarter, f.revenue, f.gross_profit, f.cash,
               f.total_liabilities, f.net_income, f.operating_income, f.updated_at
        FROM catalog_financials f
        JOIN (
            SELECT ticker, MAX(year * 10 + quarter) AS rank
            FROM catalog_financials
            WHERE form = ?
            GROUP BY ticker
        ) latest
          ON latest.ticker = f.ticker AND (f.year * 10 + f.quarter) = latest.rank
        WHERE f.form = ?
        """,
        (form, form),
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        out[r["ticker"]] = {
            "year": r["year"],
            "quarter": r["quarter"],
            "revenue": r["revenue"],
            "gross_profit": r["gross_profit"],
            "cash": r["cash"],
            "total_liabilities": r["total_liabilities"],
            "net_income": r["net_income"],
            "operating_income": r["operating_income"],
            "updated_at": r["updated_at"],
        }
    return out


def _fin_candidates(conn: sqlite3.Connection, form: str, ttl_days: int,
                    tickers: list[str] | None) -> list[dict[str, Any]]:
    """Tickers with an annual report but no fresh financials cache, newest report first."""
    ticker_filter = ""
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND r.ticker IN ({placeholders})"
    # Bind order follows the placeholders top-to-bottom: the TTL cutoff in the
    # JOIN's datetime(), then report_form, then any ticker filter.
    params = [f"-{ttl_days} days", form, *(tickers or [])]
    rows = conn.execute(
        f"""
        SELECT r.ticker, MAX(r.year) AS year
        FROM catalog_reports r
        LEFT JOIN catalog_financials f
          ON f.ticker = r.ticker AND f.form = r.report_form
         AND f.updated_at >= datetime('now', ?)
        WHERE r.report_form = ? AND r.period_type = 'annual'
          AND r.year IS NOT NULL {ticker_filter}
          AND f.ticker IS NULL
        GROUP BY r.ticker
        ORDER BY year DESC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def refresh_financials_cache(tickers: list[str] | None = None, *,
                             form: str = "NSBU",
                             limit: int | None = None,
                             ttl_days: int | None = None) -> dict[str, Any]:
    """Lazily fill the financials cache for stale/missing tickers, in batches.

    Parses the latest annual NSBU report (form 1 + form 2) for each candidate and
    stores the six headline indicators. Non-blocking: if another refresh is
    already running, returns immediately. Safe to call fire-and-forget on every
    market load — it only processes up to ``limit`` companies per call.
    """
    limit = limit or FINANCIALS_BATCH
    ttl_days = ttl_days if ttl_days is not None else FINANCIALS_TTL_DAYS
    if not _FIN_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": "already running", "processed": 0}
    processed = 0
    filled = 0
    try:
        conn = get_catalog_conn()
        candidates = _fin_candidates(conn, form, ttl_days, tickers)
        conn.close()
        for cand in candidates[:limit]:
            ticker, year = cand["ticker"], cand["year"]
            processed += 1
            try:
                data = fetch_report_excel_data(ticker, form, year, 0)
                if not data.get("ok"):
                    continue
                vals = (compute_financial_ratios(data.get("income"),
                                                 data.get("balance")).get("source_values") or {})
                if any(vals.get(k) is not None for k in _FINANCIAL_KEYS):
                    upsert_financials_cache(ticker, form, year, 0, vals)
                    filled += 1
            except Exception:
                logger.exception("financials refresh failed for %s", ticker)
        return {"ok": True, "candidates": len(candidates), "processed": processed, "filled": filled}
    finally:
        _FIN_LOCK.release()


def get_sector_averages(sector_tickers: list[str], form: str, year: int) -> dict[str, Any]:
    if not sector_tickers:
        return {}
    conn = get_catalog_conn()
    placeholders = ",".join("?" * len(sector_tickers))
    row = conn.execute(
        f"""
        SELECT AVG(roa) as roa, AVG(roe) as roe, AVG(net_margin) as net_margin,
               AVG(debt_ratio) as debt_ratio, AVG(debt_to_equity) as debt_to_equity,
               COUNT(*) as n
        FROM catalog_ratios
        WHERE ticker IN ({placeholders}) AND form=? AND year=? AND quarter=0
        """,
        (*sector_tickers, form, year),
    ).fetchone()
    conn.close()
    if not row or not row["n"]:
        return {}
    return {
        "ROA": round(row["roa"], 2) if row["roa"] is not None else None,
        "ROE": round(row["roe"], 2) if row["roe"] is not None else None,
        "net_margin": round(row["net_margin"], 2) if row["net_margin"] is not None else None,
        "debt_ratio": round(row["debt_ratio"], 2) if row["debt_ratio"] is not None else None,
        "debt_to_equity": round(row["debt_to_equity"], 2) if row["debt_to_equity"] is not None else None,
        "n": row["n"],
    }


def get_new_reports_for_tickers(tickers: list[str], since_days: int = 7) -> list[dict[str, Any]]:
    """Return recently detected new reports for the given tickers (used for notifications)."""
    if not tickers:
        return []
    conn = get_catalog_conn()
    placeholders = ",".join("?" * len(tickers))
    rows = conn.execute(
        f"""
        SELECT ticker, report_form, period_type, year, quarter, title, detected_at
        FROM catalog_new_reports
        WHERE ticker IN ({placeholders})
          AND detected_at >= datetime('now', ?)
        ORDER BY detected_at DESC
        """,
        (*tickers, f"-{since_days} days"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Excel data access
# ---------------------------------------------------------------------------

def fetch_report_excel_data(ticker: str, form: str, year: int, quarter: int) -> dict[str, Any]:
    urls = get_report_urls(ticker, form, year, quarter)
    if not urls:
        return {"ok": False, "income": None, "balance": None, "error": "Report not found in catalog"}

    session = _make_session()
    income: dict | None = None
    balance: dict | None = None
    errors: list[str] = []

    if urls.get("excel_url"):
        doc = {"excel_url": urls["excel_url"], "id": None, "object_id": None,
               "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),
               "report_form": form, "title": urls.get("title")}
        try:
            parsed = parse_excel_report_document(session, doc)
            if parsed.get("ok"):
                income = parsed
            else:
                errors.append(f"income/main: {parsed.get('error')}")
        except Exception as exc:
            errors.append(f"income/main: {exc}")

    if urls.get("excel_url_form1"):
        doc1 = {"excel_url": urls["excel_url_form1"], "id": None, "object_id": None,
                "published_at": urls.get("published_at"), "period_type": urls.get("period_type"),
                "report_form": form, "title": urls.get("title")}
        try:
            parsed1 = parse_excel_report_document(session, doc1)
            if parsed1.get("ok"):
                balance = parsed1
            else:
                errors.append(f"balance: {parsed1.get('error')}")
        except Exception as exc:
            errors.append(f"balance: {exc}")

    ok = income is not None or balance is not None
    return {
        "ok": ok,
        "income": income,
        "balance": balance,
        "error": "; ".join(errors) if errors and not ok else None,
        "warnings": errors if ok and errors else [],
    }


# ---------------------------------------------------------------------------
# Financial ratio computation
# ---------------------------------------------------------------------------

_LABEL_PATTERNS: dict[str, list[str]] = {
    "revenue": ["выруч", "реализац", "revenue", "sales", "daromad", "tushum"],
    "net_income": ["чистая прибыл", "чистый доход", "чистый убыт",
                   "net income", "net profit", "net loss", "sof foyda"],
    "total_assets": ["итого актив", "total asset", "всего актив", "jami aktiv"],
    "equity": ["собственный капитал", "итого капитал", "капитал и резерв",
               "total equity", "equity", "o'z kapitali", "kapital"],
    "total_liabilities": ["итого обязательств", "всего обязательств",
                          "total liabilit", "majburiyat"],
    # Commercial NSBU balance has no single "итого обязательств" line — liabilities
    # split into long-term (стр.490) + current (стр.600); summed as a fallback.
    "lt_liabilities": ["долгосрочные обязательства"],
    "cur_liabilities": ["текущие обязательства", "краткосрочные обязательства"],
    # Валовая прибыль (форма №2): "Валовая прибыль (убыток) от реализации ..."
    "gross_profit": ["валовая прибыл", "валовой доход", "валовая выручка",
                     "gross profit", "yalpi foyda"],
    # Наличность в кассе / денежные средства (форма №1, баланс)
    "cash": ["денежные средства", "денежных средств", "наличность", "касса",
             "cash and cash", "cash equivalent", "pul mablag", "kassa"],
    # Операционный доход = прибыль (убыток) от основной деятельности (форма №2,
    # стр. 100). Паттерны требуют "прибыль/убыток", чтобы не поймать стр. 090
    # "Прочие доходы от основной деятельности".
    "operating_income": ["прибыль (убыток) от основной деятельности",
                         "прибыль от основной деятельности",
                         "убыток от основной деятельности",
                         "операционная прибыл", "операционный доход",
                         "operating income", "operating profit"],
}


def _row_value(nums: list) -> float | None:
    """Pick the reporting-period amount from a parsed row's numeric cells.

    Two NSBU Excel layouts occur in the wild:
      * bank/vertical forms → ``[amount]`` (the line number lives in the label);
      * standard commercial forms → ``[line_code, cur_income, cur_expense,
        prev_income, prev_expense]`` where the first cell is the NSBU line code
        (010, 030, 090 …), NOT money.

    A naive "first numeric" grab returns the line code (010 → 10) for the second
    layout, so we drop a leading cell that is clearly a code — a small integer
    dwarfed (>100×) by a real value that follows — then return the first non-zero
    amount (handles the income/expense column pair, where one side is 0).
    """
    vals: list[float] = []
    for n in nums:
        try:
            vals.append(float(n))
        except (TypeError, ValueError):
            continue
    if not vals:
        return None
    if len(vals) > 1 and float(vals[0]).is_integer() and 0 < vals[0] < 100000:
        rest_max = max((abs(v) for v in vals[1:]), default=0.0)
        if rest_max > vals[0] * 100:
            vals = vals[1:]
    for v in vals:
        if abs(v) > 0.0001:
            return v
    return None


def _extract_metric(rows: list[dict], key: str) -> float | None:
    patterns = _LABEL_PATTERNS.get(key, [])
    for row in rows:
        label = str(row.get("label") or "").lower()
        if any(p in label for p in patterns):
            v = _row_value(row.get("numeric_values") or [])
            if v is not None:
                return v
    return None


def _gather_rows(excel_data: dict | None) -> list[dict]:
    if not excel_data:
        return []
    rows: list[dict] = []
    for sheet in (excel_data.get("sheets") or []):
        rows.extend(sheet.get("table_rows") or [])
    return rows


def compute_financial_ratios(income_data: dict | None, balance_data: dict | None) -> dict[str, Any]:
    income_rows = _gather_rows(income_data)
    balance_rows = _gather_rows(balance_data)
    all_rows = income_rows + balance_rows

    revenue = _extract_metric(income_rows or all_rows, "revenue")
    net_income = _extract_metric(income_rows or all_rows, "net_income")
    gross_profit = _extract_metric(income_rows or all_rows, "gross_profit")
    operating_income = _extract_metric(income_rows or all_rows, "operating_income")
    total_assets = _extract_metric(balance_rows or all_rows, "total_assets")
    equity = _extract_metric(balance_rows or all_rows, "equity")
    total_liabilities = _extract_metric(balance_rows or all_rows, "total_liabilities")
    if total_liabilities is None:
        lt = _extract_metric(balance_rows or all_rows, "lt_liabilities")
        cur = _extract_metric(balance_rows or all_rows, "cur_liabilities")
        if lt is not None or cur is not None:
            total_liabilities = (lt or 0.0) + (cur or 0.0)
    cash = _extract_metric(balance_rows or all_rows, "cash")

    def _safe_ratio(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return round(num / den * 100, 2)

    def _safe_div(num: float | None, den: float | None) -> float | None:
        if num is None or den is None or den == 0:
            return None
        return round(num / den, 4)

    metrics: dict[str, Any] = {
        "ROA": _safe_ratio(net_income, total_assets),
        "ROE": _safe_ratio(net_income, equity),
        "net_margin": _safe_ratio(net_income, revenue),
        "debt_ratio": _safe_ratio(total_liabilities, total_assets),
        "debt_to_equity": _safe_div(total_liabilities, equity),
    }

    source_rows: dict[str, Any] = {
        "revenue": revenue,
        "net_income": net_income,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "cash": cash,
        "total_assets": total_assets,
        "equity": equity,
        "total_liabilities": total_liabilities,
    }

    return {"metrics": metrics, "source_values": source_rows}


def get_company_reports(ticker: str) -> list[dict[str, Any]]:
    """Return all catalog reports for a ticker, newest first."""
    conn = get_catalog_conn()
    rows = conn.execute("""
        SELECT report_form, period_type, year, quarter, title, pdf_url, excel_url, excel_url_form1, synced_at
        FROM catalog_reports
        WHERE ticker = ?
        ORDER BY year DESC, quarter DESC, synced_at DESC
    """, (ticker,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_company_ratios_cached(ticker: str) -> dict[str, Any]:
    """Return most recent cached ratios for a ticker."""
    conn = get_catalog_conn()
    row = conn.execute("""
        SELECT year, quarter, form, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at
        FROM catalog_ratios
        WHERE ticker = ?
        ORDER BY year DESC, quarter DESC, updated_at DESC
        LIMIT 1
    """, (ticker,)).fetchone()
    conn.close()
    if not row:
        return {}
    metrics = {}
    if row["roa"] is not None:
        metrics["ROA"] = row["roa"]
    if row["roe"] is not None:
        metrics["ROE"] = row["roe"]
    if row["net_margin"] is not None:
        metrics["net_margin"] = row["net_margin"]
    if row["debt_ratio"] is not None:
        metrics["debt_ratio"] = row["debt_ratio"]
    if row["debt_to_equity"] is not None:
        metrics["debt_to_equity"] = row["debt_to_equity"]
    return {"year": row["year"], "quarter": row["quarter"], "form": row["form"], "metrics": metrics}


# ---------------------------------------------------------------------------
# Dynamics time series
# ---------------------------------------------------------------------------

def build_dynamics_data(ticker: str, form: str = "NSBU") -> dict[str, Any]:
    conn = get_catalog_conn()
    annual_rows = conn.execute(
        """
        SELECT year, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'annual' AND year IS NOT NULL
        ORDER BY year ASC
        """,
        (ticker, form),
    ).fetchall()
    conn.close()

    if not annual_rows:
        return {"ticker": ticker, "form": form, "years": [], "series": {}}

    session = _make_session()
    years: list[int] = []
    series: dict[str, list[float | None]] = {
        "revenue": [],
        "net_income": [],
        "total_assets": [],
        "equity": [],
        "total_liabilities": [],
    }

    for row in annual_rows:
        yr = row["year"]
        years.append(yr)

        income_data: dict | None = None
        balance_data: dict | None = None

        if row["excel_url"]:
            doc = {"excel_url": row["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p = parse_excel_report_document(session, doc)
                if p.get("ok"):
                    income_data = p
            except Exception:
                pass

        if row["excel_url_form1"]:
            doc1 = {"excel_url": row["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "annual", "report_form": form, "title": None}
            try:
                p1 = parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    balance_data = p1
            except Exception:
                pass

        ratios = compute_financial_ratios(income_data, balance_data)
        vals = ratios.get("source_values") or {}
        for key in series:
            series[key].append(vals.get(key))

    # --- Quarterly series (last 8 quarters) ----------------------------------
    conn2 = get_catalog_conn()
    quarter_rows = conn2.execute(
        """
        SELECT year, quarter, excel_url, excel_url_form1
        FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND period_type = 'quarter'
          AND year IS NOT NULL AND quarter > 0
        ORDER BY year DESC, quarter DESC
        LIMIT 8
        """,
        (ticker, form),
    ).fetchall()
    conn2.close()

    quarterly: list[dict[str, Any]] = []
    metric_keys = ["revenue", "net_income", "total_assets", "equity", "total_liabilities"]
    for qrow in reversed(quarter_rows):
        yr, q = qrow["year"], qrow["quarter"]
        inc, bal = None, None
        if qrow["excel_url"]:
            doc = {"excel_url": qrow["excel_url"], "id": None, "object_id": None,
                   "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p = parse_excel_report_document(session, doc)
                if p.get("ok"):
                    inc = p
            except Exception:
                pass
        if qrow["excel_url_form1"]:
            doc1 = {"excel_url": qrow["excel_url_form1"], "id": None, "object_id": None,
                    "published_at": None, "period_type": "quarter", "report_form": form, "title": None}
            try:
                p1 = parse_excel_report_document(session, doc1)
                if p1.get("ok"):
                    bal = p1
            except Exception:
                pass
        vals_q = (compute_financial_ratios(inc, bal).get("source_values") or {})
        entry: dict[str, Any] = {"label": f"Q{q} {yr}", "year": yr, "quarter": q}
        for k in metric_keys:
            entry[k] = vals_q.get(k)
        quarterly.append(entry)

    return {"ticker": ticker, "form": form, "years": years, "series": series, "quarterly": quarterly}
