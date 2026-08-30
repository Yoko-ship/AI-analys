"""Read existing domain repositories; never re-create financial arithmetic in UI."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import calendar
import logging
from urllib.parse import urlparse

from . import store as s
from .documents import classify
from .service import incident

log = logging.getLogger(__name__)


def catalog_document(row):
    year, quarter = row.get("year"), int(row.get("quarter") or 0)
    annual = not quarter or quarter == 4
    month = quarter * 3 if quarter else 12
    end = f"{year}-{month:02d}-{calendar.monthrange(int(year), month)[1]}" if year else None
    url = row.get("excel_url") or row.get("pdf_url") or row.get("excel_url_form1")
    declared = "XLSX" if row.get("excel_url") or row.get("excel_url_form1") else "PDF" if row.get("pdf_url") else None
    # Extensions are hints, not evidence that MIME sniffing has happened.
    standard = {"MSFO": "IFRS", "Audition": "IFRS"}.get(row.get("report_form"), row.get("report_form"))
    identity = [row.get("ticker"), row.get("report_form"), year, quarter, row.get("period_type")]
    return classify({"id": "doc_" + s.digest(identity)[:24], "ticker": row.get("ticker"), "title": row.get("title"),
              "standard": standard, "period": f"{year}" + (f"Q{quarter}" if not annual else ""),
              "period_start": f"{year}-01-01" if year else None, "period_end": end, "duration_months": month,
              "statement_type": "annual" if annual else "quarterly", "published_at": row.get("published_at"),
              "source_url": url, "source": urlparse(url or "").hostname or "unknown", "declared_format": declared,
              "detected_format": None, "detected_mime": None, "checksum": None,
              "source_discovered_at": row.get("synced_at") or s.now(), "catalog_id": row.get("id"),
              "catalog_available": bool(url), "parsed": False, "verified": False, "used_in_analysis": False,
              "audit_status": "unknown", "scope": "unknown", "status": "DISCOVERED"})


def index_catalog_row(c, row):
    doc = catalog_document(row)
    doc["catalog_metadata_hash"] = s.digest({k: row.get(k) for k in ("title", "year", "quarter", "period_type", "published_at", "report_form", "excel_url", "pdf_url", "excel_url_form1")})
    old = s.get(c, "documents", doc["id"], False)
    if old and old.get("catalog_metadata_hash") == doc["catalog_metadata_hash"]:
        return old
    if old:
        # Preserve the prior original in revision history, and require new evidence
        # after either source metadata or its URL changes.
        doc["previous_checksum"] = old.get("checksum") or old.get("previous_checksum")
        doc["source_discovered_at"] = old.get("source_discovered_at") or doc["source_discovered_at"]
    if doc["blockers"]:
        doc["status"] = "QUALITY_BLOCKED"
        for code in doc["blockers"]:
            incident(c, code, doc["id"], stage="classification", evidence={"ticker": doc["ticker"], "document_id": doc["id"], "period_end": doc["period_end"], "published_at": doc["published_at"]})
    doc = s.put(c, "documents", doc)
    coverage(c, doc)
    return doc


def coverage(c, doc):
    status = "CLASSIFIED_SUSPICIOUS" if doc.get("blockers") else "COMPLETE" if doc.get("used_in_analysis") and doc.get("verified") else "PUBLISHED_NOT_USED" if doc.get("catalog_available") and doc.get("verified") else "VERIFIED_NOT_PUBLISHED" if doc.get("verified") else "INGESTED_NOT_CLASSIFIED" if doc.get("checksum") else "FOUND_NOT_INGESTED"
    if doc.get("status") == "DUPLICATE":
        status = "DUPLICATE"
    item = s.put(c, "coverage", {"id": doc["id"], "document_id": doc["id"], "ticker": doc["ticker"],
             "period": doc["period"], "standard": doc["standard"], "status": status, "source": doc["source"],
             "source_discovered_at": doc.get("source_discovered_at"), "blockers": doc.get("blockers", []),
             "file_available": doc.get("catalog_available", False), "parsed": doc.get("parsed", False),
             "verified": doc.get("verified", False), "used_in_analysis": doc.get("used_in_analysis", False)})
    if status == "FOUND_NOT_INGESTED" and doc.get("source_discovered_at"):
        try:
            stamp = datetime.fromisoformat(doc["source_discovered_at"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - stamp > timedelta(hours=24):
                incident(c, "FOUND_NOT_INGESTED", doc["id"], stage="coverage", evidence={"ticker": doc["ticker"], "document_id": doc["id"]}, severity="P2")
        except ValueError:
            pass
    return item


def refresh_catalog():
    import reports_catalog
    from sector_report_service import special_type
    from sector_analysis import resolve_template
    conn = reports_catalog.get_catalog_conn()
    try:
        companies = [dict(r) for r in conn.execute("SELECT ticker,company_name,org_id,last_synced_at FROM catalog_companies")]
        rows = [dict(r) for r in conn.execute("SELECT * FROM catalog_reports ORDER BY id")]
    finally:
        conn.close()
    with s.connection(write=True) as c:
        for company in companies:
            ticker = company["ticker"]
            special = special_type({"ticker": ticker})
            template = resolve_template({"ticker": ticker}, special)
            s.put(c, "issuers", {"id": ticker, "ticker": ticker, "title": company["company_name"], "inn": None,
                      "org_id": company["org_id"], "special_type": "investment_fund" if ticker == "UZNF" else special,
                      "sector_template": special or template["selected_template"], "template_resolution": template,
                      "status": "INDEXED", "last_source_sync": company["last_synced_at"]})
        for row in rows:
            index_catalog_row(c, row)
        from .rules import index_baseline
        index_baseline(c)
        # Expected NSBU periods follow the project's existing disclosure calendar.
        # IFRS interim expectations must come from source discovery, not guesswork.
        if any(co["ticker"] == "UZNF" for co in companies) and date.today() >= date(2026, 8, 30):
            half = [r for r in s.all_items(c, "documents", {"ticker": "UZNF"}) if r.get("period_end") == "2026-06-30" and r.get("standard") == "IFRS"]
            if not half:
                incident(c, "UZNF_2026H1_SOURCE_UNCONFIRMED", "UZNF:2026H1", stage="coverage",
                         evidence={"ticker": "UZNF", "period": "2026H1", "source": "admin specifications 2026-08-30",
                                   "reason": "The specification requests this filing; the local source catalog does not confirm it. Verify the official source before importing."})
        s.put(c, "sources", {"id": "catalog", "title": "Official reporting catalog", "source": "openinfo.uz",
                 "status": "INDEXED", "documents": len(rows), "issuers": len(companies), "last_success": s.now(),
                 "note": "Indexed local catalog. This is not a live source connectivity check."})
    return {"documents": len(rows), "issuers": len(companies), "verified": False}


def record_analysis(report):
    """Project persisted domain output without upgrading missing lineage to verified."""
    issuer = report.get("issuer") or {}
    ticker = issuer.get("ticker")
    if not ticker or not report.get("version"):
        return
    import analysis_monitor
    domain = analysis_monitor.connect()
    try:
        pointer = domain.execute("SELECT version FROM sector_publications WHERE issuer_id=? AND language=? AND standard=?",
                                 (str(issuer["id"]), report["language"], report["standard"])).fetchone()
        current_version = pointer["version"] if pointer else None
    finally:
        domain.close()
    blockers = [r["code"] for r in report.get("data_quality", []) if r.get("severity") == "blocking"]
    warnings = [r["code"] for r in report.get("data_quality", []) if r.get("severity") != "blocking"]
    with s.connection(write=True) as c:
        catalog_docs = list(s.all_items(c, "documents", {"ticker": ticker}))
        facts = []
        for f in [*report.get("verified_facts", []), *report.get("calculation_inputs", [])]:
            source_url = f.get("source_url") or (f.get("source") or {}).get("url")
            doc = next((d for d in catalog_docs if d.get("source_url") == source_url or source_url in d.get("source_aliases", [])), None)
            if doc is None and source_url:
                period_end = report.get("financial_as_of")
                month = int(period_end[5:7]) if period_end else None
                doc = classify({"id": f.get("source_document_id") or "doc_" + s.digest(source_url)[:24],
                        "ticker": ticker, "source_url": source_url, "source": urlparse(source_url).hostname,
                        "source_discovered_at": report.get("generated_at") or s.now(), "standard": report["standard"].upper(),
                        "period": report.get("period"), "period_end": period_end, "duration_months": month,
                        "published_at": (f.get("source") or {}).get("publication_date"), "status": "DISCOVERED",
                        "parsed": False, "verified": False, "used_in_analysis": True, "catalog_available": False})
                doc = s.put(c, "documents", doc)
                catalog_docs.append(doc)
                coverage(c, doc)
            fact = {**f, "id": str(f.get("id") or s.digest(f)), "ticker": ticker, "status": f.get("verification_status", "unavailable"),
                    "standard": report["standard"].upper(), "document_id": (doc or {}).get("id"),
                    "source_location": f.get("source_location") or {"line": f.get("source_line_id")}, "title": f.get("label") or f.get("metric_code")}
            facts.append(s.put(c, "facts", fact))
        for ratio in report.get("ratios", []):
            code = ratio.get("metric_code") or ratio.get("metric")
            inputs = [f for f in facts if f.get("source_line_id") in ratio.get("component_facts", [])]
            missing = len(inputs) != len(ratio.get("component_facts", [])) or not inputs or any(
                not f.get("document_id") or not (f.get("source_location", {}).get("page") or
                    f.get("source_location", {}).get("sheet") and (f.get("source_location", {}).get("cell") or f.get("source_location", {}).get("row"))) for f in inputs)
            trace_blockers = [*blockers, *(["SOURCE_LOCATION_MISSING"] if missing else [])]
            s.put(c, "calculations", {**ratio, "id": "calc_" + s.digest([report["version"], code])[:24],
                  "ticker": ticker, "title": code, "metric_code": code, "standard": report["standard"].upper(),
                  "period": report.get("period"), "report_period_end": report.get("financial_as_of"),
                  "market_price_at": report.get("market_as_of"), "shares_at": None,
                  "formula_version": ratio.get("method_id") or report.get("calculation_version"), "expression": ratio.get("formula"),
                  "control_rule_versions": report.get("control_rule_versions", []),
                  "inputs": inputs, "sector_template": report.get("sector_template_code"),
                  "sector_eligibility": {"allowed": True, "reason": "Emitted by the domain sector engine"},
                  "status": "blocked" if trace_blockers else ratio.get("calculation_status", "insufficient_data"),
                  "blockers": trace_blockers, "warnings": warnings, "analysis_id": report["version"]})
        validated = report.get("status") == "available" and not blockers
        status = ("PUBLISHED" if current_version == report["version"] else "SUPERSEDED") if validated else "BLOCKED"
        item = {"id": report["version"], "ticker": ticker, "title": report.get("headline"), "status": status,
                "standard": report["standard"].upper(), "period": report.get("period"), "language": report.get("language"),
                "created_at": report.get("generated_at") or s.now(), "eligible_run": report.get("status") in {"available", "quality_blocked", "mapping_failed"},
                "blockers": blockers, "warnings": warnings, "headline": report.get("headline"), "paragraphs": report.get("paragraphs", []),
                "verdict": report.get("verdict"), "issues": report.get("analytical_issues", []), "signals": report.get("analytical_signals", []),
                "facts": facts, "sources": report.get("sources", []), "template_resolution": report.get("template_resolution"),
                "calculation_version": report.get("calculation_version"), "source_snapshot_hash": report.get("source_snapshot_hash"),
                "domain_version": report["version"], "domain_status": report.get("status")}
        s.put(c, "analyses", item)
        if validated:
            for prior in s.all_items(c, "publications", {"ticker": ticker, "standard": item["standard"], "status": "PUBLISHED"}):
                if prior["id"] != current_version and prior.get("language") == item.get("language"):
                    s.put(c, "publications", {**prior, "status": "SUPERSEDED"})
            existing = s.get(c, "publications", item["id"], False)
            # The domain pointer is authoritative; an indexing replay cannot
            # re-promote a historical result or erase a pending approval.
            s.put(c, "publications", {**item, **(existing or {}), "status": status})
        for code in blockers:
            incident(c, code, report["version"], stage="analysis", evidence={"ticker": ticker, "analysis_id": report["version"]})
        instrument = report.get("instrument")
        if instrument:
            s.put(c, "securities", {**instrument, "id": instrument["security_id"], "title": instrument.get("isin") or ticker,
                     "status": (instrument.get("freshness") or {}).get("status", "unavailable"), "category": instrument.get("instrument_type")})


def refresh_analyses():
    import analysis_monitor
    conn = analysis_monitor.connect()
    try:
        import json
        reports = [json.loads(r["payload"]) for r in conn.execute("SELECT payload FROM sector_runs ORDER BY created_at")]
    finally:
        conn.close()
    for report in reports:
        record_analysis(report)
    return len(reports)
