"""Regressions for optional source-workbook enrichment."""
from __future__ import annotations

import issuer_financials as issuer_sources

from copy import deepcopy

import issuer_analysis_api as api
import reports_catalog
import sector_report_service as service


def _snapshot(*, verified=True):
    return {
        "organization_type": "non_financial",
        "standard": "nsbu",
        "scope": "separate",
        "period": "2025Q1",
        "period_basis": "cumulative_ytd",
        "previous_comparable_period": "2024Q1",
        "current_values": {
            "revenue": 500,
            "net_income": 80,
            "total_assets": 1000,
            "total_equity": 400,
            "total_liabilities": 600,
        },
        "previous_values": {"revenue": 450, "net_income": 70},
        "opening_values": {},
        "source": {"url": "https://example.org/utgap-2025q1.pdf"},
        "quality": {
            "traceable": verified,
            "verification_status": "verified" if verified else "unknown",
            "data_quality": [],
        },
    }


def test_combined_workbook_url_is_downloaded_only_once(monkeypatch):
    url = "https://example.org/combined.xlsx"
    parsed = {"ok": True, "sheets": []}
    calls = []

    monkeypatch.setattr(reports_catalog, "get_report_urls", lambda *args: {
        "excel_url": url,
        "excel_url_form1": url,
        "period_type": "quarter",
    })
    monkeypatch.setattr(reports_catalog, "_make_session", lambda: object())

    def parse(_session, document):
        calls.append(document["excel_url"])
        return parsed

    monkeypatch.setattr(reports_catalog, "parse_excel_report_document", parse)

    result = reports_catalog.fetch_report_excel_data("UTGAP", "NSBU", 2025, 1)

    assert result["ok"] is True
    assert result["income"] is parsed
    assert result["balance"] is parsed
    assert calls == [url]


def _run_report(monkeypatch, snapshot):
    issuer = {"id": "702", "ticker": "UTGAP", "name": "O'ztransgaz", "sector": "transport"}
    document = {
        "period": "2025Q1",
        "excel_url": "https://example.org/combined.xlsx",
        "excel_url_form1": "https://example.org/combined.xlsx",
    }
    monkeypatch.setattr(issuer_sources, 'classify_organization', lambda *_: "non_financial")
    monkeypatch.setattr(issuer_sources, 'financial_snapshot', lambda *_: deepcopy(snapshot))
    monkeypatch.setattr(issuer_sources, 'report_rows', lambda *_: [document])

    def fail_fetch(*_args):
        raise TimeoutError("source timeout")

    monkeypatch.setattr(issuer_sources, 'fetch_report_excel_data', fail_fetch)
    monkeypatch.setattr(issuer_sources, 'quote_and_trade', lambda *_: ({}, {}))
    monkeypatch.setattr(service, "_REPORT_CACHE", {})
    return service.sector_report(issuer, "nsbu", "2025Q1", "separate", "ru", persist=False)


def test_verified_catalog_snapshot_survives_workbook_enrichment_failure(monkeypatch):
    report = _run_report(monkeypatch, _snapshot(verified=True))

    assert report["status"] == "stale"
    assert report["sections"]
    assert any(item["code"] == "SOURCE_ENRICHMENT_UNAVAILABLE" for item in report["data_quality"])
    assert not any(item["code"] == "SOURCE_MAPPING_FAILED" for item in report["data_quality"])


def test_unverified_snapshot_remains_blocked_when_workbook_mapping_fails(monkeypatch):
    report = _run_report(monkeypatch, _snapshot(verified=False))

    assert report["status"] == "mapping_failed"
    assert not report["sections"]
    assert any(item["code"] == "SOURCE_MAPPING_FAILED" for item in report["data_quality"])
