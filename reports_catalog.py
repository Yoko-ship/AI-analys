from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from entity_resolver import ORG_OVERRIDES, UNRELIABLE_FINANCIALS
from db import APP_DATA_DIR, sqlite_connect
from openinfo_collector import (
    OPENINFO_API_BASE,
    OPENINFO_WEB_BASE,
    REQUEST_TIMEOUT,
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
# How many not-yet-catalogued companies the financials warmup syncs per call, so a
# fresh backend self-populates progressively without a manual full catalog sync.
FINANCIALS_SYNC_BATCH = int(os.getenv("FINANCIALS_SYNC_BATCH", "8"))

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

        CREATE TABLE IF NOT EXISTS catalog_trade_stats (
            isin              TEXT PRIMARY KEY,
            trade_date        TEXT,
            total_value       REAL,
            total_qty         REAL,
            trade_count       INTEGER,
            avg_price         REAL,
            largest_qty       REAL,
            largest_value     REAL,
            largest_pct_value REAL,
            largest_pct_qty   REAL,
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Exchange-listing registry for issuers that are listed on RFB Tashkent
        -- (openinfo info_rfb.isin_codes) but absent from the live uzse-stock feed
        -- because they have not traded recently. Carries the last-known trade
        -- (from /iuzse/conclusions/) plus shares outstanding so these securities
        -- can still appear on the market board / company page, tagged inactive.
        CREATE TABLE IF NOT EXISTS catalog_listings (
            ticker             TEXT PRIMARY KEY,
            isin               TEXT,
            name               TEXT,
            share_type         TEXT,
            listing_date       TEXT,
            shares_outstanding REAL,
            reference_price    REAL,
            last_price         REAL,
            last_trade_date    TEXT,
            open_price         REAL,
            high_price         REAL,
            low_price          REAL,
            volume             REAL,
            market_cap         REAL,
            updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Generic, forward-compatible fact store (scalable-pipeline design).
        -- Any source (adapter) can land any (entity, dataset, field, period) value
        -- without a schema change, so new datasets/fields published in the future
        -- flow in automatically. entity_id is the openinfo org_id (issuer).
        CREATE TABLE IF NOT EXISTS facts (
            entity_id   TEXT NOT NULL,
            dataset     TEXT NOT NULL,
            field       TEXT NOT NULL,
            period      TEXT NOT NULL DEFAULT '',
            value_num   REAL,
            value_text  TEXT,
            unit        TEXT,
            source      TEXT NOT NULL,
            source_url  TEXT,
            fetched_at  TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (entity_id, dataset, field, period, source)
        );
        CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity_id, dataset);
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


_ORG_TYPE_CANDIDATES = ("jsc", "bank", "insurance", "microfinance")


def _probe_org_type(session: Any, form2_records: list[dict], period_type: str) -> str | None:
    """Discover an issuer's org_type by probing the Excel export endpoint.

    openinfo's /reports/main/ search misses some issuers outright — names that
    tokenize to a single useless letter (e.g. "O'zqishloqelektrqurilish" → "O")
    return no org-matched records, so _fetch_main_results yields org_type=None and
    no NSBU Excel URL can be built (financials then stay empty). The export itself
    works once the right org_type label is supplied, so we try each candidate
    against a real report id and keep the first that returns a genuine .xlsx
    (HTTP 200 + spreadsheet content-type; a wrong org_type returns HTTP 400).
    """
    report_id = next(
        (doc.get("id") for rec in form2_records if (doc := _build_report_document(rec)).get("id")),
        None,
    )
    if not report_id:
        return None
    for org_type in _ORG_TYPE_CANDIDATES:
        url = _nsbu_export_urls(report_id, period_type, org_type)[1]
        try:
            resp = session.get(url, stream=True, timeout=REQUEST_TIMEOUT)
            ctype = (resp.headers.get("content-type") or "").lower()
            resp.close()
        except Exception:  # noqa: BLE001 — any transport error just means "try next"
            continue
        if resp.status_code == 200 and ("spreadsheet" in ctype or "officedocument" in ctype):
            return org_type
    return None


def sync_company(
    ticker: str,
    company_name: str,
    *,
    force: bool = False,
    org_id: str | None = None,
) -> dict[str, Any]:
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

    # Resolution precedence: explicit caller org (already override-aware) →
    # ORG_OVERRIDES → deterministic ticker/ISIN index → name matching (last
    # resort, confidence-floored). A below-confidence resolution returns
    # nothing and is recorded as sync_error — wrong data is never landed.
    try:
        from entity_resolver import ORG_OVERRIDES, resolve_by_index

        resolved_name = company_name
        if not org_id:
            org_id = ORG_OVERRIDES.get(ticker.upper())
        if not org_id:
            try:
                hit = resolve_by_index(ticker, session=session)
            except Exception:  # noqa: BLE001 — index needs network; fall through
                hit = None
            if hit:
                org_id = hit["org_id"]
                resolved_name = hit.get("org_name") or company_name
        if not org_id:
            company = resolve_company(company_name, session=session)
            org_id = company.get("org_id")
            resolved_name = company.get("company_name") or company_name
        # Preferred share tickers (e.g. AGBAP) share the same org as the base ticker (AGBA).
        # If resolution failed, retry with the base ticker's company name.
        if not org_id and ticker.endswith("P"):
            base_name = _TICKER_TO_NAME.get(ticker[:-1])
            if base_name and base_name != company_name:
                company = resolve_company(base_name, session=session)
                org_id = company.get("org_id")
                resolved_name = company.get("company_name") or resolved_name
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
    org_id = str(org_id)
    company_name = resolved_name

    # Self-healing: if this ticker previously pointed at a different org, its
    # stored reports/financials/ratios belong to that other company — purge
    # them so only the correct issuer's data is (re-)landed below.
    prev = conn.execute(
        "SELECT org_id FROM catalog_companies WHERE ticker = ?", (ticker,)
    ).fetchone()
    if prev and prev["org_id"] and str(prev["org_id"]) != org_id:
        logger.warning(
            "%s: issuer org changed %s -> %s; purging previously stored data",
            ticker, prev["org_id"], org_id,
        )
        with conn:
            _purge_ticker_data(conn, ticker)

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

    # The /reports/main/ search couldn't resolve org_type for this issuer, so the
    # NSBU Excel URLs below would all come out empty (→ no financials). Recover it
    # by probing the export endpoint against a real report id.
    if org_type is None and form2_annual:
        org_type = _probe_org_type(session, form2_annual, "annual")

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

    # Fall back to a quarterly report id if the issuer files no annuals but the
    # org_type still hasn't been resolved.
    if org_type is None and form2_quarter:
        org_type = _probe_org_type(session, form2_quarter, "quarter")

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

    # ---- NSBU fallback from /reports/main/ ---------------------------------
    # Some issuers (microfinance MCHJ, some LLCs) file NSBU but the structured
    # /reports/accounting-report/{org}/ endpoint returns 400 for them. Their NSBU
    # documents still appear in /reports/main/ with a usable Excel export, so when
    # the structured path yielded nothing we harvest NSBU straight from the listing.
    if not form2_annual and not form2_quarter:
        nsbu_main = [r for r in main_results if r.get("report_type") == "NSBU"]
        with conn:
            for rec in nsbu_main:
                doc = _build_report_document(rec)
                yr = _extract_year(rec)
                if not isinstance(yr, int):
                    continue
                pt = str(doc.get("period_type") or "annual").lower()
                if pt not in ("annual", "quarter"):
                    pt = "annual"
                q = 0
                if pt == "quarter":
                    props = rec.get("properties") or {}
                    q = _extract_quarter(str(props.get("report_title") or "")) or 0
                new = _upsert_report(
                    conn, ticker,
                    report_form="NSBU",
                    period_type=pt,
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
    # Partial failures are recorded, not masked: a run where every report fetch
    # errored used to be stamped as a clean sync and stayed invisible for the
    # whole freshness window.
    sync_error = ("; ".join(errors))[:1000] if errors else None
    with conn:
        conn.execute(
            """
            INSERT INTO catalog_companies (ticker, company_name, org_id, last_synced_at, sync_error)
            VALUES (?,?,?,datetime('now'),?)
            ON CONFLICT(ticker) DO UPDATE SET
                company_name   = excluded.company_name,
                org_id         = excluded.org_id,
                last_synced_at = datetime('now'),
                sync_error     = excluded.sync_error
            """,
            (ticker, company_name, org_id, sync_error),
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

# Resolution sources that identify the issuer exactly (override table or the
# ticker/ISIN→INN→org join). Only these may CORRECT a stored org_id; name-based
# matches remain fill-only so a fuzzy result can never displace a good mapping.
_DETERMINISTIC_RESOLVERS = {"override", "ticker", "isin", "base_ticker_index"}


def _purge_ticker_data(conn: sqlite3.Connection, ticker: str) -> None:
    """Remove a ticker's landed data (used when its issuer org mapping changes)."""
    for table in ("catalog_reports", "catalog_new_reports", "catalog_financials", "catalog_ratios"):
        conn.execute(f"DELETE FROM {table} WHERE ticker = ?", (ticker,))


def discover_and_upsert_securities() -> dict[str, Any]:
    """Discover every UZSE-listed security and record its resolved issuer org.

    This is the self-discovering replacement for iterating the hardcoded
    COMPANY_CATALOG: it upserts a catalog_companies row (ticker -> org_id) for
    *every* listed security — ordinary, preferred and bond — so downstream
    financials inheritance can reach all of them. Deterministic resolutions
    (ticker/ISIN/override) may correct a previously stored org — purging the
    old org's landed data — while name-based matches only fill blanks.
    """
    import entity_resolver as er

    session = _make_session()
    recs = er.resolve_all(session=session)
    conn = get_catalog_conn()
    upserted = 0
    corrected = 0
    with conn:
        for rec in recs:
            org_id = rec.get("org_id")
            name = rec.get("org_name") or rec.get("name") or rec["ticker"]
            deterministic = org_id and rec.get("resolved_by") in _DETERMINISTIC_RESOLVERS
            if deterministic:
                prev = conn.execute(
                    "SELECT org_id FROM catalog_companies WHERE ticker = ?", (rec["ticker"],)
                ).fetchone()
                if prev and prev["org_id"] and str(prev["org_id"]) != str(org_id):
                    logger.warning(
                        "%s: issuer org corrected %s -> %s (%s); purging stored data",
                        rec["ticker"], prev["org_id"], org_id, rec.get("resolved_by"),
                    )
                    _purge_ticker_data(conn, rec["ticker"])
                    corrected += 1
                conn.execute(
                    """
                    INSERT INTO catalog_companies (ticker, company_name, org_id)
                    VALUES (?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        org_id = excluded.org_id,
                        company_name = COALESCE(NULLIF(catalog_companies.company_name, ''), excluded.company_name)
                    """,
                    (rec["ticker"], name, org_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO catalog_companies (ticker, company_name, org_id)
                    VALUES (?,?,?)
                    ON CONFLICT(ticker) DO UPDATE SET
                        org_id = COALESCE(catalog_companies.org_id, excluded.org_id),
                        company_name = COALESCE(NULLIF(catalog_companies.company_name, ''), excluded.company_name)
                    """,
                    (rec["ticker"], name, org_id),
                )
            upserted += 1
    conn.close()
    resolved = sum(1 for r in recs if r.get("org_id"))
    orgs = {r["org_id"] for r in recs if r.get("org_id")}
    return {"discovered": len(recs), "resolved": resolved, "distinct_orgs": len(orgs),
            "upserted": upserted, "corrected": corrected, "records": recs}


def sync_all(tickers: list[str] | None = None, *, force: bool = False) -> dict[str, Any]:
    with _SYNC_LOCK:
        discovered_recs: list[dict[str, Any]] = []
        if tickers:
            targets = tickers
        else:
            # Self-discovering path: resolve every listed security, then sync one
            # representative ticker per distinct issuer org (prefs/bonds inherit via
            # get_all_financials, so we don't re-fetch the same issuer per ticker).
            try:
                disc = discover_and_upsert_securities()
                discovered_recs = disc.get("records") or []
                logger.info("Discovery: %s", {k: disc[k] for k in ("discovered", "resolved", "distinct_orgs")})
            except Exception:
                logger.exception("Security discovery failed; falling back to COMPANY_CATALOG")
            if discovered_recs:
                seen_orgs: set[str] = set()
                reps: list[str] = []
                # Prefer the name-resolved (ordinary) ticker as the org representative.
                for rec in sorted(discovered_recs, key=lambda r: r.get("resolved_by") == "base_ticker"):
                    org = rec.get("org_id")
                    if not org or org in seen_orgs:
                        continue
                    seen_orgs.add(org)
                    reps.append(rec["ticker"])
                targets = reps or list(_TICKER_TO_NAME.keys())
            else:
                targets = list(_TICKER_TO_NAME.keys())

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

        # ticker -> name/org from discovery (falls back to the curated catalog name).
        disc_name = {r["ticker"]: (r.get("org_name") or r.get("name")) for r in discovered_recs}
        disc_org = {
            r["ticker"]: str(r["org_id"])
            for r in discovered_recs
            if r.get("org_id") and r.get("resolved_by") in _DETERMINISTIC_RESOLVERS
        }

        for ticker in targets:
            # Skip preferred share tickers (e.g. AGBAP) — they map to the same
            # org on openinfo as their base ticker (AGBA) and would duplicate reports.
            if ticker.endswith("P") and ticker[:-1] in _TICKER_TO_NAME:
                skipped += 1
                continue
            name = disc_name.get(ticker) or _TICKER_TO_NAME.get(ticker, ticker)
            try:
                result = sync_company(ticker, name, force=force, org_id=disc_org.get(ticker))
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


# Snapshot committed to the repo, generated where openinfo.uz is reachable. Lets
# environments that can't reach openinfo (e.g. a datacenter IP openinfo blocks)
# still serve financials instead of empty "—" columns.
_FINANCIALS_SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "financials_seed.json")
_seed_lock = threading.Lock()
_seeded = False


def _maybe_seed_financials(conn: sqlite3.Connection, form: str = "NSBU") -> None:
    """Bootstrap catalog_financials from the bundled snapshot when it's empty.

    Only fills when no rows exist for the form — never overwrites values produced
    by a live sync. Guarded so it runs at most once per process.
    """
    global _seeded
    if _seeded:
        return
    with _seed_lock:
        if _seeded:
            return
        try:
            n = conn.execute("SELECT COUNT(*) FROM catalog_financials WHERE form=?", (form,)).fetchone()[0]
            if not n and os.path.exists(_FINANCIALS_SEED_PATH):
                with open(_FINANCIALS_SEED_PATH, encoding="utf-8") as f:
                    rows = (json.load(f) or {}).get("rows") or []
                with conn:
                    for r in rows:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO catalog_financials
                                (ticker, form, year, quarter, revenue, gross_profit, cash,
                                 total_liabilities, net_income, operating_income, updated_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
                            """,
                            (r.get("ticker"), r.get("form") or form, r.get("year") or 0,
                             r.get("quarter") or 0, r.get("revenue"), r.get("gross_profit"),
                             r.get("cash"), r.get("total_liabilities"), r.get("net_income"),
                             r.get("operating_income")),
                        )
                logger.info("Seeded catalog_financials from snapshot: %d rows", len(rows))
        except Exception:
            logger.exception("financials seed failed")
        finally:
            _seeded = True


def bulk_upsert_financials(rows: list[dict], form: str = "NSBU") -> int:
    """Overwrite the financials cache from an externally-computed batch.

    Used by the admin push endpoint so a collector running where openinfo IS
    reachable can refresh prod (whose datacenter IP openinfo blocks). Unlike the
    seed loader, this overwrites existing values (ON CONFLICT DO UPDATE).
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                try:
                    year = int(r.get("year") or 0)
                    quarter = int(r.get("quarter") or 0)
                except (TypeError, ValueError):
                    continue
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
                    (ticker, str(r.get("form") or form), year, quarter,
                     _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("cash")),
                     _num(r.get("total_liabilities")), _num(r.get("net_income")),
                     _num(r.get("operating_income"))),
                )
                n += 1
    finally:
        conn.close()
    return n


_TRADE_STAT_KEYS = ("total_value", "total_qty", "trade_count", "avg_price",
                    "largest_qty", "largest_value", "largest_pct_value", "largest_pct_qty")


def bulk_upsert_trade_stats(rows: list[dict], trade_date: str | None = None) -> int:
    """Overwrite the latest-day per-ISIN trade statistics cache."""
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                isin = str(r.get("isin") or "").strip().upper()
                if not isin:
                    continue
                conn.execute(
                    """
                    INSERT INTO catalog_trade_stats
                        (isin, trade_date, total_value, total_qty, trade_count, avg_price,
                         largest_qty, largest_value, largest_pct_value, largest_pct_qty, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(isin) DO UPDATE SET
                        trade_date=excluded.trade_date, total_value=excluded.total_value,
                        total_qty=excluded.total_qty, trade_count=excluded.trade_count,
                        avg_price=excluded.avg_price, largest_qty=excluded.largest_qty,
                        largest_value=excluded.largest_value,
                        largest_pct_value=excluded.largest_pct_value,
                        largest_pct_qty=excluded.largest_pct_qty, updated_at=datetime('now')
                    """,
                    (isin, str(r.get("trade_date") or trade_date or ""),
                     _num(r.get("total_value")), _num(r.get("total_qty")),
                     int(_num(r.get("trade_count")) or 0), _num(r.get("avg_price")),
                     _num(r.get("largest_qty")), _num(r.get("largest_value")),
                     _num(r.get("largest_pct_value")), _num(r.get("largest_pct_qty"))),
                )
                n += 1
    finally:
        conn.close()
    return n


def get_all_trade_stats() -> dict[str, dict[str, Any]]:
    """Return the cached latest-day trade statistics per ISIN: {isin: {...}}."""
    conn = get_catalog_conn()
    rows = conn.execute(
        """SELECT isin, trade_date, total_value, total_qty, trade_count, avg_price,
                  largest_qty, largest_value, largest_pct_value, largest_pct_qty, updated_at
           FROM catalog_trade_stats"""
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        # VWAP on read (ТЗ §3.4/§3.8): volume-weighted price = turnover / quantity.
        tv, tq = d.get("total_value"), d.get("total_qty")
        d["vwap"] = round(tv / tq, 2) if (tv and tq) else None
        out[r["isin"]] = d
    return out


_LISTING_COLS = (
    "ticker", "isin", "name", "share_type", "listing_date", "shares_outstanding",
    "reference_price", "last_price", "last_trade_date", "open_price", "high_price",
    "low_price", "volume", "market_cap",
)


def bulk_upsert_listings(rows: list[dict]) -> int:
    """Overwrite the exchange-listing registry from an externally-computed batch.

    Pushed by the collector (where openinfo is reachable) so prod can show
    listed-but-inactive issuers on the market board even though they are missing
    from the live uzse-stock feed. Keyed by security ticker (ordinary + preferred
    lines are distinct rows, e.g. KSCM / KSCMP).
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    conn = get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker:
                    continue
                conn.execute(
                    """
                    INSERT INTO catalog_listings
                        (ticker, isin, name, share_type, listing_date, shares_outstanding,
                         reference_price, last_price, last_trade_date, open_price, high_price,
                         low_price, volume, market_cap, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(ticker) DO UPDATE SET
                        isin=excluded.isin, name=excluded.name, share_type=excluded.share_type,
                        listing_date=excluded.listing_date,
                        shares_outstanding=excluded.shares_outstanding,
                        reference_price=excluded.reference_price, last_price=excluded.last_price,
                        last_trade_date=excluded.last_trade_date, open_price=excluded.open_price,
                        high_price=excluded.high_price, low_price=excluded.low_price,
                        volume=excluded.volume, market_cap=excluded.market_cap,
                        updated_at=datetime('now')
                    """,
                    (ticker, str(r.get("isin") or "") or None, str(r.get("name") or "") or None,
                     str(r.get("share_type") or "") or None, str(r.get("listing_date") or "") or None,
                     _num(r.get("shares_outstanding")), _num(r.get("reference_price")),
                     _num(r.get("last_price")), str(r.get("last_trade_date") or "") or None,
                     _num(r.get("open_price")), _num(r.get("high_price")), _num(r.get("low_price")),
                     _num(r.get("volume")), _num(r.get("market_cap"))),
                )
                n += 1
    finally:
        conn.close()
    return n


def get_all_listings() -> dict[str, dict[str, Any]]:
    """Return the cached exchange-listing registry per ticker: {ticker: {...}}."""
    conn = get_catalog_conn()
    rows = conn.execute(
        f"SELECT {', '.join(_LISTING_COLS)}, updated_at FROM catalog_listings"
    ).fetchall()
    conn.close()
    return {r["ticker"]: dict(r) for r in rows}


def _financials_enrich_enabled() -> bool:
    """Whether to apply org/fact enrichment when reading financials.

    Enrichment (fact-store corrections, cross-ticker inheritance) must run in the
    collector — where openinfo is reachable and the org mapping is fresh — before
    it pushes the final values. It must NOT run when serving on the deployment:
    prod's catalog_companies/org map is stale (openinfo is blocked there, so it
    never re-syncs), and re-enriching would re-inject a *different* entity's
    numbers over the clean pushed values (the org-1001 → OCBK/MNGM bug). Default
    off; the collector sets FINANCIALS_ENRICH_ON_READ=1.
    """
    return os.getenv("FINANCIALS_ENRICH_ON_READ", "0").strip().lower() in {"1", "true", "yes", "on"}


def get_all_financials(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Return the most recent cached indicators per ticker: {ticker: {...}}.

    Picks the latest period (year, then quarter) available for each ticker. Org/
    fact enrichment runs only when ``_financials_enrich_enabled()`` (collector),
    so the deployment serves exactly what the collector pushed.
    """
    conn = get_catalog_conn()
    _maybe_seed_financials(conn, form)
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
    if _financials_enrich_enabled():
        _inherit_financials_by_org(conn, out)
        _enrich_financials_from_facts(conn, out)
    conn.close()
    return out


# Below this a value is a parse error even for a micro-cap (e.g. O'zbekneftgaz's
# revenue=10). Genuinely tiny issuers (UzMED-lizing ~186k) sit well above it and
# are kept — a magnitude floor, not a size judgement.
_MIN_PLAUSIBLE = 10_000
_FIN_FIELDS = ("revenue", "gross_profit", "cash", "total_liabilities", "net_income", "operating_income")
_RATIO_FIELDS = ("roe", "roa", "net_profit_margin", "debt_to_equity", "current_ratio", "total_equity", "total_assets")


def get_all_ratios() -> dict[str, dict[str, Any]]:
    """Latest per-ticker financial ratios and equity from the fact store
    (openinfo ``financial_indicators``), keyed by ticker.

    Feeds the market-wide multiplier columns (P/E, P/B) and ratio coefficients
    (ТЗ §3.8). Ratios are served exactly as openinfo reports them; equity/assets
    are absolute sums used to derive P/B (= market_cap / equity). Unreliable
    ticker→org matches are skipped, mirroring the financials enrichment.
    """
    conn = get_catalog_conn()
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(_RATIO_FIELDS))})",
            _RATIO_FIELDS,
        ).fetchall()
    except Exception:
        conn.close()
        return {}
    ticker_org = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    best: dict[tuple[str, str], tuple[str, float]] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if best.get(key) is None or period > best[key][0]:
            best[key] = (period, r["value_num"])
    out: dict[str, dict[str, Any]] = {}
    for ticker, org in ticker_org.items():
        if ticker in UNRELIABLE_FINANCIALS:
            continue
        entry: dict[str, Any] = {}
        latest_period = None
        for field in _RATIO_FIELDS:
            hit = best.get((org, field))
            if hit is not None:
                entry[field] = hit[1]
                if latest_period is None or hit[0] > latest_period:
                    latest_period = hit[0]
        if entry:
            entry["period"] = latest_period
            out[ticker] = entry
    conn.close()
    return out


def _enrich_financials_from_facts(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Conservatively correct NSBU headline figures from the fact store.

    openinfo's financial_indicators are cleaner than the NSBU form-2 parse, but the
    ticker→org resolution is ambiguous for some issuers (openinfo carries duplicate
    org records and UZSE names fuzzy-match unrelated entities), so a fact could be
    for the *wrong* company. We therefore only apply changes we can trust:
      - banks (null NSBU revenue): fill revenue and take net_profit;
      - sign flips: NSBU net_income of the same magnitude but opposite sign to the
        fact — unambiguously the same company, a parser sign error;
      - fill genuinely-null revenue / total_liabilities;
      - blank implausibly small NSBU values (clear parse errors).
    Large magnitude disagreements are left as flags (see audit_financials_consistency)
    rather than "corrected" with possibly-wrong-org data.
    """
    srcs = ("net_revenue", "net_profit", "total_liabilities")
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
        rows = conn.execute(
            "SELECT entity_id, field, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND value_num IS NOT NULL "
            f"AND field IN ({','.join('?' * len(srcs))})",
            srcs,
        ).fetchall()
    except Exception:
        return
    ticker_org = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    best: dict[tuple[str, str], tuple[str, float]] = {}
    # net_profit indexed by annual year, so a sign-flip check compares against the
    # SAME year the board displays — not merely the newest indicator on file (which
    # can be a later annual than the parsed NSBU set, defeating the magnitude test).
    npf_by_year: dict[tuple[str, int], float] = {}
    for r in rows:
        key = (str(r["entity_id"]), r["field"])
        period = str(r["period"] or "")
        if best.get(key) is None or period > best[key][0]:
            best[key] = (period, r["value_num"])
        if r["field"] == "net_profit" and period.isdigit() and len(period) == 4:
            npf_by_year[(str(r["entity_id"]), int(period))] = r["value_num"]
    for ticker, fin in out.items():
        # Tickers whose only openinfo match is a different company: blank rather
        # than show another entity's figures.
        if ticker in UNRELIABLE_FINANCIALS:
            for key in _FIN_FIELDS:
                fin[key] = None
            continue
        # is_bank is judged on the issuer's sector — a stable signal. (Using
        # "revenue is None" would misfire after blanking or on a re-read of already
        # enriched-and-pushed data, making a blanked value look like a bank.)
        is_bank = COMPANY_SECTORS.get(ticker) == "finance"
        for key in _FIN_FIELDS:
            val = fin.get(key)
            if val is not None and 0 < abs(val) < _MIN_PLAUSIBLE:
                fin[key] = None
        org = ticker_org.get(ticker)
        if not org:
            continue
        rev = best.get((org, "net_revenue"))
        npf = best.get((org, "net_profit"))
        tl = best.get((org, "total_liabilities"))
        rev_v = rev[1] if rev and rev[1] not in (None, 0) else None
        npf_v = npf[1] if npf and npf[1] is not None else None
        tl_v = tl[1] if tl and tl[1] not in (None, 0) else None

        if ticker in ORG_OVERRIDES:
            # Org is human-verified, so openinfo's clean figures are authoritative.
            if npf_v is not None:
                fin["net_income"] = npf_v
            if rev_v is not None:
                fin["revenue"] = rev_v
            if tl_v is not None:
                fin["total_liabilities"] = tl_v
            continue

        # Finance issuers (banks and insurers): openinfo's net_revenue is the
        # authoritative top line. Banks have no NSBU revenue line at all; insurers
        # do (gross written premiums), but we show the net-of-reinsurance indicator
        # to stay consistent with how bank revenue is sourced. Non-finance keep the
        # NSBU figure and only fall back to the indicator when it is blank.
        if rev_v is not None and (is_bank or fin.get("revenue") is None):
            fin["revenue"] = rev_v
        if npf_v is not None:
            stored = fin.get("net_income")
            if is_bank and npf_v != 0:
                fin["net_income"] = npf_v
            elif stored is not None:
                year = fin.get("year")
                cmp_v = npf_by_year.get((org, year)) if year else None
                if cmp_v is None:
                    cmp_v = npf_v
                same_magnitude = abs(abs(stored) - abs(cmp_v)) / max(abs(cmp_v), 1.0) < 0.05
                if same_magnitude and (stored < 0) != (cmp_v < 0):
                    fin["net_income"] = cmp_v  # sign flip — same company, fix sign
        if fin.get("total_liabilities") is None and tl_v is not None:
            fin["total_liabilities"] = tl_v


def upsert_facts(rows: list[dict[str, Any]]) -> int:
    """Upsert generic facts from any source adapter (forward-compatible storage).

    Each row: ``entity_id, dataset, field, value`` (+ optional ``period, unit,
    source, source_url``). Numeric values land in ``value_num``, others in
    ``value_text``. New datasets/fields require no schema change.
    """
    if not rows:
        return 0
    conn = get_catalog_conn()
    written = 0
    with conn:
        for r in rows:
            value = r.get("value")
            vnum = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            vtext = None if vnum is not None else (str(value) if value is not None else None)
            conn.execute(
                """
                INSERT INTO facts (entity_id, dataset, field, period, value_num, value_text, unit, source, source_url, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(entity_id, dataset, field, period, source) DO UPDATE SET
                    value_num  = excluded.value_num,
                    value_text = excluded.value_text,
                    unit       = excluded.unit,
                    source_url = excluded.source_url,
                    fetched_at = datetime('now')
                """,
                (str(r["entity_id"]), r["dataset"], r["field"], str(r.get("period", "")),
                 vnum, vtext, r.get("unit"), r.get("source", "unknown"), r.get("source_url")),
            )
            written += 1
    conn.close()
    return written


def get_facts(entity_id: Any = None, dataset: str | None = None) -> list[dict[str, Any]]:
    """Query the fact store, optionally filtered by entity (org_id) and dataset."""
    conn = get_catalog_conn()
    query = "SELECT * FROM facts WHERE 1=1"
    params: list[Any] = []
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(str(entity_id))
    if dataset:
        query += " AND dataset = ?"
        params.append(dataset)
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def audit_financials_consistency(form: str = "NSBU", tol: float = 0.05) -> list[dict[str, Any]]:
    """Reconcile served net_income against the authoritative fact-store net_profit.

    Flags any issuer whose stored/served net income differs by more than ``tol``
    from openinfo's own net_profit for the same entity — catching mislabels
    (revenue booked as profit) or stale NSBU parses before they mislead a user.
    """
    served = get_all_financials(form)
    conn = get_catalog_conn()
    try:
        comp = {
            r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"]))
            for r in conn.execute(
                "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT entity_id, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND field='net_profit' AND value_num IS NOT NULL"
        ).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        key = str(r["entity_id"])
        period = str(r["period"] or "")
        if key not in best or period > best[key][0]:
            best[key] = (period, r["value_num"])
    flags: list[dict[str, Any]] = []
    for ticker, fin in served.items():
        ni = fin.get("net_income")
        org = comp.get(ticker)
        if ni is None or not org:
            continue
        hit = best.get(org)
        if not hit or not hit[1]:
            continue
        if abs(ni - hit[1]) / max(abs(hit[1]), 1.0) > tol:
            flags.append({"ticker": ticker, "stored_net_income": ni, "authoritative_net_profit": hit[1]})
    return flags


def get_catalog_coverage(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Per-ticker data coverage from the catalog DB (for /api/coverage).

    Returns {ticker: {org_id, reports, has_financials, sync_error, last_synced_at}}
    so the API can show, for every listed security, whether each dataset is
    filled / empty / failed — no openinfo access required (reads the local cache).
    """
    conn = get_catalog_conn()
    comp = {
        r["ticker"]: {
            "org_id": r["org_id"],
            "sync_error": r["sync_error"],
            "last_synced_at": r["last_synced_at"],
        }
        for r in conn.execute(
            "SELECT ticker, org_id, sync_error, last_synced_at FROM catalog_companies"
        ).fetchall()
    }
    rep_counts = {
        r["ticker"]: r["c"]
        for r in conn.execute(
            "SELECT ticker, COUNT(*) AS c FROM catalog_reports GROUP BY ticker"
        ).fetchall()
    }
    conn.close()
    fin = get_all_financials(form)
    out: dict[str, dict[str, Any]] = {}
    tickers = set(comp) | set(rep_counts) | set(fin)
    for tk in tickers:
        info = comp.get(tk, {})
        out[tk] = {
            "org_id": info.get("org_id"),
            "sync_error": info.get("sync_error"),
            "last_synced_at": info.get("last_synced_at"),
            "reports": rep_counts.get(tk, 0),
            "has_financials": tk in fin,
        }
    return out


def _inherit_financials_by_org(conn: sqlite3.Connection, out: dict[str, dict[str, Any]]) -> None:
    """Let every listed ticker inherit its issuer's financials (ТЗ data pipeline).

    Preferred shares (HMKBP) share the issuer org of the ordinary share (HMKB);
    bonds share the issuer that files the statements. Financials are computed per
    issuer (org_id) but stored under whatever ticker was synced, so a pref/bond
    ends up with an org resolved but no financials row. This maps every ticker in
    catalog_companies to its org's financials when it has none of its own — the
    values are identical because it is the same legal entity.
    """
    try:
        comp = conn.execute(
            "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
        ).fetchall()
    except Exception:
        return
    ticker_org: dict[str, str] = {r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"])) for r in comp}
    # One financials payload per org (any ticker of that org that already has one).
    org_fin: dict[str, dict[str, Any]] = {}
    for ticker, fin in out.items():
        org = ticker_org.get(ticker)
        if org and org not in org_fin:
            org_fin[org] = fin
    # Assign to sibling tickers that have an org but no financials of their own.
    for ticker, org in ticker_org.items():
        if ticker in out:
            continue
        source = org_fin.get(org)
        if source:
            out[ticker] = {**source, "inherited_from_org": org}

    # Preferred shares also inherit directly from their ordinary ticker, even when
    # openinfo indexes them under a different org record (duplicate org entries for
    # the same issuer, e.g. UZMK/UZMKP). Same legal entity → same financials.
    for ticker in list(ticker_org.keys()):
        if ticker in out or not ticker.endswith("P"):
            continue
        base = ticker[:-1]
        if base in out:
            out[ticker] = {**out[base], "inherited_from_ticker": base}


def _fin_candidates(conn: sqlite3.Connection, form: str, ttl_days: int,
                    tickers: list[str] | None) -> list[dict[str, Any]]:
    """Best parseable report per ticker lacking a fresh cache.

    Considers only reports that have an Excel export (PDF-only issuers can't be
    parsed). An annual report is preferred; if a ticker has none with Excel, its
    latest quarter with Excel is used (e.g. GRBK files only quarterly Excel).
    Returns ``[{ticker, year, quarter}]``, newest first.
    """
    ticker_filter = ""
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND r.ticker IN ({placeholders})"
    # Bind order follows the placeholders top-to-bottom: the TTL cutoff in the
    # JOIN's datetime(), then report_form, then any ticker filter.
    params = [f"-{ttl_days} days", form, *(tickers or [])]
    rows = conn.execute(
        f"""
        SELECT r.ticker, r.period_type, r.year, r.quarter
        FROM catalog_reports r
        LEFT JOIN catalog_financials f
          ON f.ticker = r.ticker AND f.form = r.report_form
         AND f.updated_at >= datetime('now', ?)
        WHERE r.report_form = ? AND r.excel_url IS NOT NULL
          AND r.year IS NOT NULL {ticker_filter}
          AND f.ticker IS NULL
        """,
        params,
    ).fetchall()
    best: dict[str, tuple] = {}
    for r in rows:
        t = r["ticker"]
        key = (1 if r["period_type"] == "annual" else 0, r["year"], r["quarter"] or 0)
        if t not in best or key > best[t][0]:
            best[t] = (key, {"ticker": t, "year": r["year"], "quarter": r["quarter"] or 0})
    return [v[1] for v in sorted(best.values(), key=lambda x: x[0], reverse=True)]


def _sync_missing_companies(form: str, sync_limit: int) -> int:
    """Sync a bounded batch of companies that have no catalog reports yet.

    Lets a fresh backend bootstrap its catalog (and therefore financials)
    progressively over successive market loads, so the columns fill in without a
    manual ``sync_all``. Returns the number of companies synced this call.
    """
    if sync_limit <= 0:
        return 0
    conn = get_catalog_conn()
    have = {r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM catalog_reports").fetchall()}
    conn.close()
    pending = [
        t for t in _TICKER_TO_NAME
        if t not in have and not (t.endswith("P") and t[:-1] in _TICKER_TO_NAME)
    ]
    synced = 0
    for ticker in pending[:sync_limit]:
        try:
            sync_company(ticker, _TICKER_TO_NAME.get(ticker, ticker))
            synced += 1
        except Exception:
            logger.exception("warmup catalog sync failed for %s", ticker)
    return synced


def _latest_excel_report(ticker: str, form: str,
                         exclude: tuple[int, int] | None = None) -> dict[str, int] | None:
    """Newest report (any period type) with an Excel export, for a fallback.

    ``_fin_candidates`` prefers the latest *annual* report, but some issuers only
    have an old annual (sometimes an empty filing) plus recent quarterly data
    (e.g. KSCM: newest annual is 2021, but 2026 Q1 has real figures). When the
    preferred report yields nothing, we retry with the most recent report that
    exists so those companies still populate.
    """
    conn = get_catalog_conn()
    rows = conn.execute(
        """
        SELECT year, quarter FROM catalog_reports
        WHERE ticker = ? AND report_form = ? AND excel_url IS NOT NULL AND year IS NOT NULL
        ORDER BY year DESC, quarter DESC
        """,
        (ticker, form),
    ).fetchall()
    conn.close()
    for r in rows:
        yq = (r["year"], r["quarter"] or 0)
        if exclude and yq == exclude:
            continue
        return {"year": yq[0], "quarter": yq[1]}
    return None


def refresh_financials_from_pdf(tickers: list[str] | None = None, limit: int = 80) -> dict[str, Any]:
    """Fill financials from the NSBU report PDF for issuers whose Excel export is
    broken on openinfo (microfinance MCHJ and similar).

    Targets tickers that have an NSBU pdf_url but no cached financials, parsing the
    latest report (annual preferred). This is the last-resort source after the
    structured accounting-report and Excel paths.
    """
    from openinfo_collector import fetch_report_documents, parse_nsbu_pdf_financials

    conn = get_catalog_conn()
    ticker_filter = ""
    params: list[Any] = []
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        ticker_filter = f"AND r.ticker IN ({placeholders})"
        params = list(tickers)
    rows = conn.execute(
        f"""
        SELECT r.ticker, c.company_name, r.period_type, r.year, r.quarter
        FROM catalog_reports r
        JOIN catalog_companies c ON c.ticker = r.ticker
        LEFT JOIN catalog_financials f ON f.ticker = r.ticker AND f.form = 'NSBU'
        WHERE r.report_form = 'NSBU' AND r.year IS NOT NULL AND f.ticker IS NULL {ticker_filter}
        """,
        params,
    ).fetchall()
    conn.close()

    best: dict[str, tuple] = {}  # newest report per ticker (annual beats quarter)
    for r in rows:
        rank = (1 if r["period_type"] == "annual" else 0, r["year"], r["quarter"] or 0)
        if r["ticker"] not in best or rank > best[r["ticker"]][0]:
            best[r["ticker"]] = (rank, r)

    session = _make_session()
    updated = 0
    errors: list[dict] = []
    for ticker, (_, r) in list(best.items())[:limit]:
        try:
            # The stored pdf_url can carry a wrong report id for microfinance, so
            # fetch the live report list to get the current, correct PDF link.
            docs = fetch_report_documents(r["company_name"] or ticker, session=session)
            nsbu = [d for d in docs["items"] if d.get("report_form") == "NSBU" and d.get("pdf_url")]
            if not nsbu:
                continue
            nsbu.sort(key=lambda d: (d.get("period_type") == "annual", str(d.get("published_at") or "")), reverse=True)
            fin = parse_nsbu_pdf_financials(session, nsbu[0]["pdf_url"])
        except Exception as exc:  # noqa: BLE001
            errors.append({"ticker": ticker, "error": str(exc)})
            continue
        if fin.get("net_income") is None and fin.get("revenue") is None:
            continue
        c = get_catalog_conn()
        with c:
            c.execute(
                """
                INSERT INTO catalog_financials
                    (ticker, form, year, quarter, revenue, gross_profit, cash,
                     total_liabilities, net_income, operating_income)
                VALUES (?, 'NSBU', ?, ?, ?, NULL, ?, ?, ?, NULL)
                ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET
                    revenue = excluded.revenue, cash = excluded.cash,
                    total_liabilities = excluded.total_liabilities,
                    net_income = excluded.net_income, updated_at = datetime('now')
                """,
                (ticker, r["year"], r["quarter"] or 0, fin.get("revenue"),
                 fin.get("cash"), fin.get("total_liabilities"), fin.get("net_income")),
            )
        c.close()
        updated += 1
    return {"ok": True, "candidates": len(best), "updated": updated, "errors": errors[:10]}


def refresh_financials_cache(tickers: list[str] | None = None, *,
                             form: str = "NSBU",
                             limit: int | None = None,
                             ttl_days: int | None = None,
                             sync_missing: bool = True,
                             sync_limit: int | None = None) -> dict[str, Any]:
    """Lazily fill the financials cache for stale/missing tickers, in batches.

    Parses the latest annual NSBU report (form 1 + form 2) for each candidate and
    stores the six headline indicators. When ``sync_missing`` is set and no ticker
    filter is given, first syncs a small batch of not-yet-catalogued companies so a
    fresh backend self-populates over successive calls. Non-blocking: if another
    refresh is already running, returns immediately. Safe to call fire-and-forget
    on every market load — it only processes up to ``limit`` companies per call.
    """
    limit = limit or FINANCIALS_BATCH
    ttl_days = ttl_days if ttl_days is not None else FINANCIALS_TTL_DAYS
    sync_limit = FINANCIALS_SYNC_BATCH if sync_limit is None else sync_limit
    if not _FIN_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": "already running", "processed": 0}
    processed = 0
    filled = 0
    synced = 0
    try:
        # Bootstrap the catalog on a fresh backend (only when scanning all tickers).
        if sync_missing and not tickers:
            synced = _sync_missing_companies(form, sync_limit)
        conn = get_catalog_conn()
        candidates = _fin_candidates(conn, form, ttl_days, tickers)
        conn.close()
        for cand in candidates[:limit]:
            ticker, year, quarter = cand["ticker"], cand["year"], cand["quarter"]
            processed += 1
            try:
                data = fetch_report_excel_data(ticker, form, year, quarter)
                vals = (compute_financial_ratios(data.get("income"),
                                                 data.get("balance")).get("source_values") or {}) if data.get("ok") else {}
                if not any(vals.get(k) is not None for k in _FINANCIAL_KEYS):
                    # Preferred (annual) report had no usable data — e.g. an old
                    # empty filing. Fall back to the ticker's most recent report.
                    alt = _latest_excel_report(ticker, form, exclude=(year, quarter or 0))
                    if alt:
                        alt_data = fetch_report_excel_data(ticker, form, alt["year"], alt["quarter"])
                        if alt_data.get("ok"):
                            alt_vals = (compute_financial_ratios(alt_data.get("income"),
                                                                 alt_data.get("balance")).get("source_values") or {})
                            if any(alt_vals.get(k) is not None for k in _FINANCIAL_KEYS):
                                year, quarter, vals = alt["year"], alt["quarter"], alt_vals
                if any(vals.get(k) is not None for k in _FINANCIAL_KEYS):
                    upsert_financials_cache(ticker, form, year, quarter, vals)
                    filled += 1
            except Exception:
                logger.exception("financials refresh failed for %s", ticker)
        return {"ok": True, "synced": synced, "candidates": len(candidates),
                "processed": processed, "filled": filled}
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


def get_recent_new_reports(since_days: int = 120, limit: int = 80) -> list[dict[str, Any]]:
    """Recently detected new report filings across every ticker — the source for
    the public market-news feed (ТЗ §3.2 item 6)."""
    conn = get_catalog_conn()
    rows = conn.execute(
        """
        SELECT ticker, report_form, period_type, year, quarter, title, detected_at
        FROM catalog_new_reports
        WHERE detected_at >= datetime('now', ?)
        ORDER BY detected_at DESC
        LIMIT ?
        """,
        (f"-{max(1, since_days)} days", max(1, limit)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

    Several NSBU Excel layouts occur in the wild, but they all lay their period
    columns out OLDEST → NEWEST left-to-right, exactly as openinfo exports them:
      * bank/vertical forms → ``[amount]`` (single period; the line number lives
        in the label) or ``[prior, current]`` (begin-of-year | end-of-period);
      * commercial form №1 (balance) → ``[line_code, begin, end]``
        (header: «На начало отчётного периода» | «На конец отчётного периода»);
      * commercial form №2 (fin. results) → ``[line_code, prev_income,
        prev_expense, cur_income, cur_expense]``
        (header: «За соответствующий период прошлого года» | «За отчётный период»).

    The reporting-period figure is therefore the LATER column-group, never the
    first. A naive "first numeric after the code" grab returns last year's / the
    opening balance — the exact off-by-one-period bug this guards against.

    We drop a leading cell that is clearly a line code (a small integer, either
    dwarfed >100× by the value after it or sitting ahead of ≥2 more cells), then,
    when the remaining cells split into two equal period halves, read the first
    non-zero amount from the SECOND (reporting) half. We fall back to the first
    half only when the reporting half is entirely zero (e.g. a period that has
    not been reported yet).
    """
    vals: list[float] = []
    for n in nums:
        try:
            f = float(n)
        except (TypeError, ValueError):
            continue
        if f != f:  # NaN (blank cell captured as NaN) — skip so it can't shift the split
            continue
        vals.append(f)
    if not vals:
        return None
    # Detect a leading NSBU line-code cell (010, 030, 320 …): a small integer.
    # In the multi-column commercial layout (code + period pairs) the first cell
    # is ALWAYS the code, so drop it even when the amounts are zero (e.g. a fund
    # with no revenue → [10,0,0,0,0], must not return "10"). In a 2-cell layout
    # it's ambiguous, so only drop when the code is dwarfed by the value after it.
    first_is_code = (
        len(vals) >= 2
        and vals[0].is_integer()
        and 0 < vals[0] < 10000
        and (len(vals) >= 3 or abs(vals[1]) > abs(vals[0]) * 100)
    )
    rest = vals[1:] if first_is_code else vals

    def _first_nonzero(seq: list[float]) -> float | None:
        for v in seq:
            if abs(v) > 0.0001:
                return v
        return None

    # Period columns run oldest → newest, so the reporting period is the second
    # half of the value cells (form №2 prior|current income/expense pairs; form №1
    # and bank forms begin|end / prior|current). Prefer it; fall back if it's zero.
    if len(rest) >= 2 and len(rest) % 2 == 0:
        reporting = _first_nonzero(rest[len(rest) // 2:])
        if reporting is not None:
            return reporting
    return _first_nonzero(rest)


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
        LIMIT 16
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

    # --- Seasonality (ТЗ §3.5): average a headline metric by quarter across years.
    # Needs ≥3 years of history; otherwise flagged insufficient rather than shown.
    season_metric = "revenue"
    by_q: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    years_seen: set[int] = set()
    for e in quarterly:
        v = e.get(season_metric)
        q = e.get("quarter")
        if isinstance(v, (int, float)) and q in by_q:
            by_q[q].append(float(v))
            years_seen.add(e.get("year"))
    seasonality = {
        "metric": season_metric,
        "years_covered": len(years_seen),
        "insufficient": len(years_seen) < 3,
        "quarter_avg": {q: (round(sum(vals) / len(vals), 2) if vals else None) for q, vals in by_q.items()},
    }

    return {"ticker": ticker, "form": form, "years": years, "series": series,
            "quarterly": quarterly, "seasonality": seasonality}
