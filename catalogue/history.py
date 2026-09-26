"""Recover historical quarterly filings and parse their original workbooks."""
from __future__ import annotations
from financial_corrections import correction_periods_for
from collectors.openinfo.settings import OPENINFO_WEB_BASE
from collectors.openinfo.settings import REQUEST_TIMEOUT
import catalogue.snapshots as catalogue_snapshots
from typing import Any

from datetime import datetime
from collectors.openinfo.settings import OPENINFO_WEB_BASE
from collectors.openinfo.settings import REQUEST_TIMEOUT
import catalogue.fields as catalogue_fields
import catalogue.filings as catalogue_filings
import catalogue.financial_store as catalogue_financial_store
import catalogue.parsing as catalogue_parsing
import catalogue.periods as catalogue_periods
import catalogue.refresh as catalogue_refresh
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
import os
import re
import time


EXCEL_HARVEST_MAX_BYTES = int(os.getenv("OPENINFO_EXCEL_MAX_BYTES", "3000000"))


def _parse_workbook_uncached(session: Any, excel_url: str) -> dict[str, Any]:
    """Download and parse one NSBU workbook, bypassing the snapshot cache.

    :func:`parse_excel_report_document` memoises into a single JSON file that it
    rewrites whole on every write and trims to 500 entries. At ~60 KB a snapshot
    that file is already 30 MB, so a sweep of two thousand historical filings
    would rewrite 30 MB two thousand times to keep 500 of them — minutes of disk
    for a cache that cannot hold the sweep anyway. A one-pass backfill has no
    second read to serve, so it takes the workbook straight.
    """
    from collectors.openinfo.workbooks import _parse_excel_workbook

    response = session.get(excel_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content = response.content
    if len(content) > EXCEL_HARVEST_MAX_BYTES:
        return {"ok": False, "error": f"Excel file is too large: {len(content)} bytes"}
    return {"ok": True, "source": "openinfo_excel", **_parse_excel_workbook(content)}


EXCEL_HARVEST_MAX_BYTES = int(os.getenv("OPENINFO_EXCEL_MAX_BYTES", "3000000"))


def unified_quarterly_records(session: Any, org_id: Any) -> list[dict[str, Any]]:

    """List NSBU quarters beyond the structured endpoint's ten-report window."""

    return catalogue_snapshots._unified_statement_records(session, org_id, period_type="quarter")


def parse_catalogued_report(ticker: str, form: str, year: int, quarter: int,
                            session: Any | None = None) -> dict[str, Any]:
    """Re-parse one catalogued filing and return its ``source_values``.

    :func:`fetch_report_excel_data` with the snapshot cache taken out of the way
    — see :func:`_parse_workbook_uncached` for why a sweep must not go through it.
    One workbook carries both NSBU forms, so both links point at the same
    document and it is fetched once.
    """
    urls = catalogue_filings.get_report_urls(ticker, form, year, quarter) or {}
    excel = urls.get("excel_url") or urls.get("excel_url_form1")
    if not excel:
        return {}
    parsed = _parse_workbook_uncached(session or catalogue_sources._make_session(), excel)
    if not parsed.get("ok"):
        return {}
    other = urls.get("excel_url_form1")
    second = parsed
    if other and other != excel:
        second = _parse_workbook_uncached(session or catalogue_sources._make_session(), other)
        second = second if second.get("ok") else parsed
    return (catalogue_parsing.compute_financial_ratios(parsed, second) or {}).get("source_values") or {}


def harvest_historical_quarters(ticker: str, *, limit: int = 40,

                                session: Any | None = None,

                                pace: float = 0.2,

                                publish: bool = True) -> dict[str, Any]:

    """Catalogue and parse the quarterly filings older than the source's window.



    Fetch unknown filings and known records that have no workbook link. Merely

    knowing an accounting id is not evidence that the document was collected.

    A second run after a successful repair costs one feed read and no workbooks.

    With publish=False, only discover catalog sources; the caller validates

    parsed values before updating financial caches or provenance.



    Returns ``{"ticker", "rows", "added", "skipped", "errors"}``; ``rows`` are

    admin-push shaped, so a collector can hand them to /api/admin/financials the

    way the other backfills do.

    """

    t = str(ticker or "").strip().upper()

    if not t:

        return {"ticker": t, "rows": [], "added": 0, "skipped": 0, "errors": ["no ticker"]}

    session = session or catalogue_sources._make_session()

    conn = catalogue_storage.get_catalog_conn()

    try:

        org = conn.execute("SELECT org_id FROM catalog_companies WHERE ticker=?", (t,)).fetchone()

        org_id = (org or {})["org_id"] if org else None

        if not org_id:

            return {"ticker": t, "rows": [], "added": 0, "skipped": 0,

                    "errors": ["issuer not catalogued — run the report sync first"]}

        stored = conn.execute(

            "SELECT year, quarter, openinfo_report_id, published_at, excel_url, excel_url_form1 FROM catalog_reports "

            "WHERE ticker=? AND report_form='NSBU' AND period_type='quarter'", (t,)).fetchall()

    finally:

        conn.close()

    linked = [r for r in stored if r["excel_url"] or r["excel_url_form1"]]

    seen = {str(r["openinfo_report_id"]) for r in linked if r["openinfo_report_id"]}

    # When was the filing we already hold for a period published? A record older

    # than that is a superseded revision of a period we have — openinfo lists

    # both (KSCM filed its 2023 half-year on 31 July and again on 8 August) and

    # re-parsing it every sweep buys an identical upsert for a download.

    held: dict[tuple[int, int], str] = {}

    for row in linked:

        if row["year"] and row["quarter"] and row["published_at"]:

            key = (int(row["year"]), int(row["quarter"]))

            held[key] = max(held.get(key, ""), str(row["published_at"]))



    records = unified_quarterly_records(session, org_id)



    def _is_fresh_record(rec: dict[str, Any]) -> bool:

        if rec["accounting_id"] in seen or not rec["excel_url"]:

            return False

        # The period from the publication date alone — the workbook has the

        # authoritative answer, but reading it is the download this skips.

        try:

            pub = datetime.fromisoformat(rec["pub_date"].replace("Z", "+00:00"))

        except ValueError:

            return True

        key = catalogue_periods._quarter_period_from_publication(catalogue_periods._PUB_MONTH_QUARTER[pub.month], pub)

        return held.get(key, "") < rec["pub_date"]



    fresh = [r for r in records if _is_fresh_record(r)]

    errors: list[str] = []

    rows: list[dict[str, Any]] = []

    for rec in fresh[:limit]:

        try:

            pub = datetime.fromisoformat(rec["pub_date"].replace("Z", "+00:00"))

        except ValueError:

            errors.append(f"{rec['accounting_id']}: unreadable pub_date {rec['pub_date']!r}")

            continue

        try:

            parsed = _parse_workbook_uncached(session, rec["excel_url"])

        except Exception as exc:  # noqa: BLE001 — one bad workbook is not the sweep

            errors.append(f"{rec['accounting_id']}: {exc}")

            continue

        if not parsed.get("ok"):

            errors.append(f"{rec['accounting_id']}: {parsed.get('error')}")

            continue

        quarter = catalogue_periods._stated_quarter(parsed) or catalogue_periods._PUB_MONTH_QUARTER[pub.month]

        year, quarter = catalogue_periods._quarter_period_from_publication(quarter, pub)

        if catalogue_periods._is_future_period(year, quarter):

            errors.append(f"{rec['accounting_id']}: derived {year}Q{quarter} has not ended")

            continue

        values = (catalogue_parsing.compute_financial_ratios(parsed, parsed) or {}).get("source_values") or {}

        if not any(values.get(k) is not None for k in catalogue_fields.FIN_MONEY_FIELDS):

            errors.append(f"{rec['accounting_id']}: no indicator read from {year}Q{quarter}")

            continue

        conn = catalogue_storage.get_catalog_conn()

        try:

            with conn:

                catalogue_filings._upsert_report(

                    conn, t,

                    report_form="NSBU",

                    period_type="quarter",

                    year=year,

                    quarter=quarter,

                    title=rec.get("title"),

                    published_at=rec["pub_date"],

                    pdf_url=(f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{rec['pdf_id']}/"

                             if rec.get("pdf_id") else None),

                    excel_url=rec["excel_url"],

                    # One workbook carries BOTH forms — the balance and the

                    # income statement sit in the same sheet — so the two links

                    # are the same document, exactly as the structured path

                    # already stores them for the current quarters.

                    excel_url_form1=rec["excel_url"],

                    openinfo_report_id=rec["accounting_id"],

                    object_id=None,

                )

        finally:

            conn.close()

        if publish:

            report_id = catalogue_refresh._register_parse(t, "NSBU", year, quarter, parsed, values)

            catalogue_financial_store.upsert_financials_cache(t, "NSBU", year, quarter, values, report_id)

        rows.append({"ticker": t, "year": year, "quarter": quarter,

                     **{k: values.get(k) for k in catalogue_fields.FIN_MONEY_FIELDS}})

        if pace:

            time.sleep(pace)

    return {"ticker": t, "rows": rows, "added": len(rows),

            "skipped": len(records) - len(fresh), "errors": errors}


def get_financial_history_coverage(form: str = "NSBU") -> dict[str, dict[str, Any]]:
    """Field/period coverage against discovered filings, grouped by issuer.

    This measures collection, before public consistency filters. It does not
    claim that the source has been fully discovered or that a figure is valid.
    """
    conn = catalogue_storage.get_catalog_conn()
    try:
        companies = list(conn.execute("SELECT ticker, org_id FROM catalog_companies").fetchall())
        reports = list(conn.execute(
            "SELECT ticker, year, quarter, excel_url, pdf_url, period_type FROM catalog_reports "
            "WHERE report_form=? AND year IS NOT NULL AND NOT (period_type='quarter' AND quarter=0)", (form,)).fetchall())
        financials = list(conn.execute(
            f"SELECT ticker, year, quarter, balance_period, {', '.join(catalogue_fields._FIN_FIELDS + catalogue_fields._IFRS_BANK_FIELDS)} "
            "FROM catalog_financials WHERE form=?", (form,)).fetchall())
    finally:
        conn.close()
    issuer = {r["ticker"]: str(r["org_id"] or r["ticker"]) for r in companies}
    expected: dict[str, set[str]] = {}
    values: dict[str, dict[str, dict[str, Any]]] = {}
    banks: set[str] = set()
    tickers = set(issuer)
    reviewed = {}
    labels = {}
    if form == "MSFO":
        from financial_ingestion import publication
        for ticker, org in issuer.items():
            if org not in reviewed:
                annual = publication.series(ticker)
                if annual is not None:
                    reviewed[org] = {**annual, **(publication.series(ticker, quarterly=True) or {})}
                    labels[org] = publication.catalog_labels(ticker)
                else:
                    reviewed[org] = None
    for row in reports:
        org = issuer.get(row["ticker"], row["ticker"])
        row = {**dict(row), **labels.get(org, {}).get(row["pdf_url"], {})}
        if catalogue_periods._is_future_period(row["year"], row["quarter"] or 0):
            continue
        ticker = row["ticker"]
        tickers.add(ticker)
        org = issuer.get(ticker, ticker)
        period = f"{row['year']}Q{row['quarter']}" if row["quarter"] else str(row["year"])
        expected.setdefault(org, set()).add(period)
        if "org_type=bank" in str(row["excel_url"] or ""):
            banks.add(org)
    for row in financials:
        ticker = row["ticker"]
        tickers.add(ticker)
        org = issuer.get(ticker, ticker)
        period = f"{row['year']}Q{row['quarter']}" if row["quarter"] else str(row["year"])
        values.setdefault(org, {}).setdefault(period, {}).update(catalogue_snapshots._fin_row_fields(row))
    for org, periods in reviewed.items():
        if periods is not None:
            values[org] = periods
            expected.setdefault(org, set()).update(periods)
    # A reviewed correction counts as available, but cannot invent IFRS data.
    if form == "NSBU":
        for ticker in tickers:
            org = issuer.get(ticker, ticker)
            for p, corrections in correction_periods_for(ticker).items():
                period = p[:4] if p.endswith("Q4") else p
                values.setdefault(org, {}).setdefault(period, {}).update(
                    {key: correction.value_thousands_uzs for key, correction in corrections.items()})
    out = {}
    for ticker in tickers:
        org = issuer.get(ticker, ticker)
        required = ("revenue", "net_income", "total_assets", "total_equity", "total_liabilities")
        if org in banks:
            required += ("cash", "gross_profit", "operating_income", "operating_expenses")
        periods = expected.get(org, set())
        collected = values.get(org, {})
        if form == "MSFO" and any(v.get("interest_income") is not None for v in collected.values()):
            required = ("interest_income", "interest_expense", "net_income", "total_assets",
                        "total_equity", "total_liabilities", "cash", "operating_income", "operating_expenses")
        missing = {p: [field for field in required if collected.get(p, {}).get(field) is None]
                   for p in sorted(periods, reverse=True)}
        missing = {p: fields for p, fields in missing.items() if fields}
        absent = [p for p in sorted(periods, reverse=True) if not collected.get(p)]
        out[ticker] = {
            "scope": "catalogued_filings", "standard": form,
            "status": "NO_CATALOGUED_REPORTS" if not periods else "PARTIAL" if missing else "COLLECTED",
            "expected_periods": len(periods),
            "parsed_periods": sum(bool(collected.get(p)) for p in periods),
            "complete_periods": len(periods) - len(missing),
            "missing_periods": absent, "missing_fields": missing,
        }
    return out


def repair_statement_links(ticker: str) -> dict[str, Any]:
    """Recover missing annual/quarterly URLs by exact source id, not guessed year.

    The structured feed's limited window can no longer supply an old URL, but
    the unified feed retains it. Reuse the catalog's known period for that exact
    document; an unknown annual without a stated fiscal year needs review.
    """
    ticker = ticker.strip().upper()
    conn = catalogue_storage.get_catalog_conn()
    try:
        org = conn.execute("SELECT org_id FROM catalog_companies WHERE ticker=?", (ticker,)).fetchone()
        missing = conn.execute("SELECT year, quarter, period_type, openinfo_report_id FROM catalog_reports "
                               "WHERE ticker=? AND report_form='NSBU' "
                               "AND COALESCE(excel_url, '')='' AND COALESCE(excel_url_form1, '')=''",
                               (ticker,)).fetchall()
    finally:
        conn.close()
    result: dict[str, Any] = {"repaired": [], "unresolved": []}
    if not missing or not org or not org["org_id"]:
        return result
    source = {(r["period_type"], r["accounting_id"]): r
              for r in catalogue_snapshots._unified_statement_records(catalogue_sources._make_session(), org["org_id"])}
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            for row in missing:
                key = (row["period_type"], str(row["openinfo_report_id"] or ""))
                rec = source.get(key)
                if not rec or not rec.get("excel_url") or row["year"] is None:
                    result["unresolved"].append({"year": row["year"], "quarter": row["quarter"]})
                    continue
                catalogue_filings._upsert_report(conn, ticker, report_form="NSBU", period_type=row["period_type"],
                               year=row["year"], quarter=row["quarter"] or 0,
                               title=rec.get("title"), published_at=rec["pub_date"],
                               pdf_url=(f"{OPENINFO_WEB_BASE}/ru/reports/to_pdf{rec['pdf_id']}/"
                                        if rec.get("pdf_id") else None),
                               excel_url=rec["excel_url"], excel_url_form1=rec["excel_url"],
                               openinfo_report_id=rec["accounting_id"], object_id=None)
                result["repaired"].append({"year": row["year"], "quarter": row["quarter"] or 0})
    finally:
        conn.close()
    return result
