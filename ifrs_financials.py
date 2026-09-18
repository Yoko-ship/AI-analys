"""Reviewed, source-bound IFRS PDF ingestion (never an NSBU fallback).

PDF text/OCR is not accounting data until its columns, units and reporting
perimeter have been checked. The checked-in review ledger is the input to this
publisher. Each entry is bound to the exact PDF bytes, issuer and source URL;
an upstream replacement requires a new review, not a speculative re-parse.

Run ``python ifrs_financials.py --ticker BRBN`` to verify without publishing;
add ``--apply`` to populate the legacy catalog. New production publication uses
``python -m financial_ingestion.worker``; the bank-history collector only queues
PDF work. This legacy importer is retained for compatibility and migration.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import pdfplumber
import requests
import dbx

LEDGER = Path(__file__).with_name("ifrs_reviewed_financials.json")
VERSION = "ifrs-pdf-reviewed-v1"
FIELDS = ("cash", "total_assets", "total_liabilities", "total_equity",
          "interest_income", "interest_expense", "operating_income",
          "operating_expenses", "net_income")
MAX_BYTES = 25 * 1024 * 1024


def reviews() -> list[dict]:
    data = json.loads(LEDGER.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unknown IFRS review schema")
    entries = data["reports"]
    keys = [(str(e["org_id"]), e["year"]) for e in entries]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate issuer/year in IFRS reviews")
    return entries


def _number(value) -> Decimal:
    # Reviewed ledger stores literal decimal strings, not OCR corrections.
    if not isinstance(value, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        raise ValueError("A reviewed amount must be a plain decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid reviewed amount") from exc
    if not number.is_finite():
        raise ValueError("Non-finite reviewed amount")
    return number


def validate_review(entry: dict, payload: bytes) -> dict[str, float]:
    if entry.get("review_method") != "visual-source-page-check":
        raise ValueError("Unreviewed extraction cannot be published")
    if entry.get("currency") != "UZS" or entry.get("scope") != "consolidated":
        raise ValueError("Unsupported currency or reporting perimeter")
    if entry.get("unit_scale") not in (1000, 1000000):
        raise ValueError("Unknown PDF unit scale")
    year = entry.get("year")
    if type(year) is not int or not 1990 <= year < date.today().year:
        raise ValueError("Invalid or unfinished annual period")
    if not entry.get("period_evidence") or not entry.get("unit_evidence"):
        raise ValueError("Period and unit evidence are required")
    if len(payload) > MAX_BYTES or not payload.startswith(b"%PDF-"):
        raise ValueError("Invalid or oversized PDF")
    if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
        raise ValueError("Source PDF changed; a new review is required")
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        count = len(pdf.pages)
    if count != entry.get("page_count"):
        raise ValueError("PDF page count changed")
    figures = entry.get("figures") or {}
    if set(figures) != set(FIELDS):
        raise ValueError("Incomplete or unknown bank IFRS fields")
    amounts = {}
    for field, figure in figures.items():
        if (type(figure.get("page")) is not int or not 1 <= figure["page"] <= count
                or not str(figure.get("raw_label") or "").strip()
                or figure.get("column_year") != year):
            raise ValueError(f"Missing/invalid page, label or year column: {field}")
        amounts[field] = _number(figure["raw_value"])
    # Allow only the one-unit rounding of independently rounded totals.
    if abs(amounts["total_assets"] - amounts["total_liabilities"] - amounts["total_equity"]) > 1:
        raise ValueError("IFRS balance sheet does not reconcile")
    if amounts["total_assets"] <= 0 or amounts["cash"] < 0 or amounts["total_liabilities"] < 0:
        raise ValueError("Invalid balance-sheet totals")
    if amounts["interest_income"] < 0 or amounts["interest_expense"] > 0 or amounts["operating_expenses"] > 0:
        raise ValueError("Reviewed expense signs must match the statement")
    # Canonical storage is THOUSANDS UZS; passports retain the original units.
    factor = Decimal(entry["unit_scale"]) / 1000
    return {field: float(value * factor) for field, value in amounts.items()}


def download_pdf(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "openinfo.uz" or not parsed.path.startswith("/media/"):
        raise ValueError("IFRS source must be an OpenInfo media document")
    # No redirects to private/internal destinations, no unbounded downloads.
    with requests.get(url, stream=True, timeout=(15, 90), allow_redirects=False) as response:
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Unexpected source redirect/status")
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("IFRS PDF exceeds download limit")
            chunks.append(chunk)
        return b"".join(chunks)


def reviewed_catalog_year(conn, org_id, pdf_url: str | None, fallback: int) -> int:
    """Preserve a verified filing-year correction on future catalog syncs.

    Only an imported, byte-verified review can override source listing metadata.
    Merely adding a draft to the ledger cannot alter the public report catalog.
    """
    for entry in reviews():
        if str(entry["org_id"]) != str(org_id) or entry["pdf_url"] != pdf_url:
            continue
        if "source_reports" not in dbx.tables(conn):
            return fallback
        row = conn.execute(
            "SELECT id FROM source_reports WHERE org_id=? AND report_form='MSFO' "
            "AND period_year=? AND pdf_url=? AND file_hash=? AND extraction_version=? "
            "AND state IN ('validated','published')",
            (str(org_id), entry["year"], pdf_url, entry["sha256"], VERSION)).fetchone()
        return entry["year"] if row else fallback
    return fallback


def import_reviewed(ticker: str, *, apply: bool = False, entries=None, fetch=download_pdf) -> dict:
    import reports_catalog as rc
    import provenance

    ticker = ticker.strip().upper()
    company = rc.get_company_index(ticker) or {}
    org_id = str(company.get("org_id") or "")
    selected = [e for e in (reviews() if entries is None else entries) if str(e["org_id"]) == org_id]
    result = {"ticker": ticker, "verified": [], "published": [], "errors": []}
    for entry in selected:
        year = entry["year"]
        try:
            conn = rc.get_catalog_conn()
            try:
                source = conn.execute(
                    "SELECT r.* FROM catalog_reports r JOIN catalog_companies c ON c.ticker=r.ticker "
                    "WHERE c.org_id=? AND r.report_form='MSFO' AND r.period_type='annual' "
                    "AND r.pdf_url=? ORDER BY r.ticker=? DESC LIMIT 1",
                    (org_id, entry["pdf_url"], ticker)).fetchone()
                if source:
                    conflict = conn.execute(
                        "SELECT id,pdf_url FROM catalog_reports WHERE ticker=? AND report_form='MSFO' "
                        "AND period_type='annual' AND year=? AND quarter=0",
                        (source["ticker"], year)).fetchone()
                    if conflict and conflict["id"] != source["id"]:
                        raise ValueError("A different catalog entry already occupies the reviewed year")
            finally:
                conn.close()
            if not source:
                raise ValueError("Reviewed source URL is not catalogued for this issuer")
            values = validate_review(entry, fetch(entry["pdf_url"]))
            result["verified"].append(year)
            if not apply:
                continue
            report_id = provenance.upsert_report(
                org_id, "MSFO", "annual", year, pdf_url=entry["pdf_url"],
                title=f"{entry['issuer_name']} — consolidated IFRS {year}",
                hash_value=entry["sha256"], source_published_at=source["published_at"],
                extraction_version=VERSION)
            provenance.set_state(report_id, "parsed")
            provenance.record_figures(report_id, [
                {"field": field, "value": float(_number(figure["raw_value"])),
                 "unit_scale": entry["unit_scale"], "page": figure["page"],
                 "raw_label": figure["raw_label"]}
                for field, figure in entry["figures"].items()])
            # Publication is last: failed validation cannot replace live values.
            # This writer never touches NSBU rows or generic indicator facts.
            conn = rc.get_catalog_conn()
            try:
                with conn:
                    conflict = conn.execute(
                        "SELECT id, pdf_url FROM catalog_reports WHERE ticker=? AND report_form='MSFO' "
                        "AND period_type='annual' AND year=? AND quarter=0",
                        (source["ticker"], year)).fetchone()
                    if conflict and conflict["pdf_url"] != entry["pdf_url"]:
                        raise ValueError("A different IFRS document already occupies the reviewed year")
                    if source["year"] != year:
                        if conflict:
                            raise ValueError("Duplicate catalog entries need explicit reconciliation")
                        conn.execute("UPDATE catalog_reports SET year=? WHERE id=?", (year, source["id"]))
                    names = ", ".join(FIELDS)
                    updates = ", ".join(f"{f}=excluded.{f}" for f in FIELDS)
                    marks = ",".join("?" for _ in FIELDS)
                    conn.execute(
                        f"INSERT INTO catalog_financials (ticker,form,year,quarter,{names},report_id,org_type,updated_at) "
                        f"VALUES (?,'MSFO',?,0,{marks},?,'bank',datetime('now')) "
                        f"ON CONFLICT(ticker,form,year,quarter) DO UPDATE SET {updates}, "
                        "report_id=excluded.report_id, org_type='bank', field_periods=NULL, updated_at=datetime('now')",
                        (source["ticker"], year, *(values[f] for f in FIELDS), report_id))
            finally:
                conn.close()
            provenance.set_state(report_id, "validated")
            result["published"].append(year)
        except Exception as exc:
            result["errors"].append({"year": year, "reason": str(exc)})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--apply", action="store_true", help="publish verified ledger entries into the local persistent catalog")
    args = parser.parse_args()
    result = import_reviewed(args.ticker, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["errors"] or not result["verified"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
