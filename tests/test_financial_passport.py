"""Financial-table evidence passports (v4.2 source traceability)."""
from __future__ import annotations

import reports_catalog as rc
import catalogue.evidence as catalogue_evidence
import catalogue.financial_store as catalogue_financial_store
import catalogue.storage as catalogue_storage
import provenance


def test_direct_financial_value_returns_its_filing_line(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)",
                ("TRACE", "Trace issuer", "org-trace"),
            )
    finally:
        conn.close()

    report_id = provenance.upsert_report(
        "org-trace", "NSBU", "annual", 2025,
        title="Annual report 2025", excel_url="https://example.test/report.xlsx",
        hash_value=provenance.file_hash("report-v1"),
        source_published_at="2026-03-31T10:00:00+05:00",
        extraction_version="test-parser-v1",
    )
    provenance.record_figures(report_id, [{
        "field": "revenue", "value": 1234.0, "unit_scale": 1000,
        "page": 4, "raw_label": "Выручка от реализации",
    }])
    provenance.set_state(report_id, "validated")
    catalogue_financial_store.upsert_financials_cache("TRACE", "NSBU", 2025, 0,
                               {"revenue": 1234.0}, report_id=report_id)

    got = catalogue_evidence.get_financial_value_passport("TRACE", "2025", "net_revenue")

    assert got["status"] == "SOURCED"
    assert got["source_field"] == "revenue"
    assert got["source"]["report_id"] == report_id
    assert got["source"]["raw_label"] == "Выручка от реализации"
    assert got["source"]["page"] == 4
    assert got["source"]["excel_url"] == "https://example.test/report.xlsx"
    assert got["source"]["source_published_at"] == "2026-03-31T10:00:00+05:00"
    assert got["source"]["extraction_version"] == "test-parser-v1"
    assert got["source"]["received_at"]
    assert got["source"]["perimeter"] == "org-trace"
    assert got["source"]["normalized_value"] == 1_234_000.0
    assert got["source"]["normalization_formula"] == "raw_value × unit_scale"


def test_derived_value_is_explicitly_a_formula_not_a_filed_line(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))

    got = catalogue_evidence.get_financial_value_passport("TRACE", "2025", "net_margin")

    assert got == {
        "status": "DERIVED",
        "period": "2025",
        "field": "net_margin",
        "standard": "NSBU",
        "formula": "net_profit / net_revenue * 100",
        "inputs": ["net_profit", "net_revenue"],
        "reason": "This value is calculated by the platform; open its input values for filing sources.",
    }


def test_legacy_value_without_report_link_is_not_given_a_guessed_source(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            conn.execute(
                "INSERT INTO catalog_companies (ticker, company_name, org_id) VALUES (?,?,?)",
                ("LEGACY", "Legacy issuer", "org-legacy"),
            )
    finally:
        conn.close()
    catalogue_financial_store.upsert_financials_cache("LEGACY", "NSBU", 2025, 0, {"revenue": 999.0})

    got = catalogue_evidence.get_financial_value_passport("LEGACY", "2025", "net_revenue")

    assert got["status"] == "NO_SOURCE_PASSPORT"
    assert "cannot be attributed safely" in got["reason"]
