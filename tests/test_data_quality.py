"""Data-quality review records must be auditable and non-destructive."""
from __future__ import annotations

import data_quality as dq
import reports_catalog as rc


def _draft(**overrides):
    value = {
        "ticker": "TSTQ", "form": "NSBU", "year": 2024, "quarter": 3,
        "field": "total_assets", "value_thousands_uzs": 321.5,
        "source_url": "https://example.test/report.pdf", "source_reference": "Form 1, line 400",
        "reason": "The published workbook contains a value the parser missed.",
    }
    value.update(overrides)
    return value


def test_scan_persists_missing_field_issue_without_changing_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    rc.upsert_financials_cache("TSTQ", "NSBU", 2024, 3, {
        "revenue": 10, "net_income": None, "total_assets": None, "total_equity": None,
    })

    scan = dq.scan_financial_issues()
    assert scan["scanned"] == 1
    assert scan["created"] == 3
    issues = dq.list_issues()["items"]
    assert {issue["field"] for issue in issues} == {"net_income", "total_assets", "total_equity"}

    conn = rc.get_catalog_conn()
    try:
        row = conn.execute("SELECT total_assets FROM catalog_financials WHERE ticker='TSTQ'").fetchone()
        assert row["total_assets"] is None
    finally:
        conn.close()


def test_approved_correction_overlays_reader_and_revert_restores_source(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    rc.upsert_financials_cache("TSTQ", "NSBU", 2024, 3, {
        "revenue": 10, "net_income": 2, "total_assets": 100, "total_equity": 40,
        "total_liabilities": 60,
    })
    correction = dq.create_correction(_draft(), "author@example.test")
    assert correction["status"] == "draft"
    assert dq.approved_corrections_for("TSTQ", "NSBU", 2024, 3) == {}

    dq.review_correction(correction["id"], "approved", "reviewer@example.test")
    assert dq.approved_corrections_for("TSTQ", "NSBU", 2024, 3) == {"total_assets": 321.5}

    row = {"year": 2024, "quarter": 3, "form": "NSBU", "total_assets": 100,
           "balance": {"assets_end": 100}}
    served = rc._apply_registered_financial_corrections("TSTQ", "2024Q3", row)
    assert served["total_assets"] == 321.5
    assert served["balance"]["assets_end"] == 321.5

    dq.review_correction(correction["id"], "reverted", "reviewer@example.test")
    row = {"year": 2024, "quarter": 3, "form": "NSBU", "total_assets": 100}
    assert rc._apply_registered_financial_corrections("TSTQ", "2024Q3", row)["total_assets"] == 100


def test_correction_requires_evidence_and_supported_field(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    try:
        dq.create_correction(_draft(source_url="not-a-url"), "author@example.test")
    except dq.DataQualityError as exc:
        assert "evidence URL" in str(exc)
    else:
        raise AssertionError("missing source URL validation")
    try:
        dq.create_correction(_draft(field="made_up"), "author@example.test")
    except dq.DataQualityError as exc:
        assert "Unsupported" in str(exc)
    else:
        raise AssertionError("unsupported-field validation")


def test_balance_suggestion_is_editable_proposal_not_a_write(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    rc.upsert_financials_cache("TSTQ", "NSBU", 2024, 3, {
        "revenue": 10, "net_income": 2, "total_assets": 100, "total_equity": 30,
        "total_liabilities": 50,
    })
    conn = rc.get_catalog_conn()
    try:
        with conn:
            rc._upsert_report(conn, "TSTQ", report_form="NSBU", period_type="quarter", year=2024,
                              quarter=3, title="NSBU report", published_at="2024-11-01",
                              pdf_url="https://example.test/report.pdf", excel_url=None,
                              excel_url_form1=None, openinfo_report_id="123", object_id=None)
    finally:
        conn.close()
    dq.scan_financial_issues()
    issue = next(item for item in dq.list_issues()["items"] if item["rule_code"] == "BALANCE_MISMATCH")

    proposal = dq.suggest_correction(issue["id"])

    assert proposal["recommended"]["field"] == "total_assets"
    assert proposal["recommended"]["value_thousands_uzs"] == 80
    assert {item["field"] for item in proposal["alternatives"]} == {
        "total_assets", "total_equity", "total_liabilities"}
    assert proposal["evidence"] == {
        "source_url": "https://example.test/report.pdf",
        "source_reference": "NSBU report; опубликован 2024-11-01",
        "available": True,
    }
    assert proposal["reason"].startswith("Автоматическая подсказка")
    assert dq.list_corrections()["items"] == []


def test_missing_balance_component_can_be_suggested(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    rc.upsert_financials_cache("TSTQ", "NSBU", 2024, 3, {
        "revenue": 10, "net_income": 2, "total_assets": None, "total_equity": 40,
        "total_liabilities": 60,
    })
    dq.scan_financial_issues()
    issue = next(item for item in dq.list_issues()["items"] if item["field"] == "total_assets")

    proposal = dq.suggest_correction(issue["id"])

    assert proposal["recommended"]["field"] == "total_assets"
    assert proposal["recommended"]["value_thousands_uzs"] == 100
    assert proposal["recommended"]["confidence"] == "medium"
