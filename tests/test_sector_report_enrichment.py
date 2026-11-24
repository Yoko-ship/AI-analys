"""Regressions for optional source-workbook enrichment."""
from __future__ import annotations

import issuer_financials as issuer_sources

from copy import deepcopy
import pytest

import issuer_analysis_api as api
import reports_catalog
import catalogue.filings as catalogue_filings
import catalogue.sources as catalogue_sources
import sector_report_service as service


@pytest.mark.parametrize('invalid',[None,'revision','period','parser'])
def test_cached_workbook_reader_uses_only_the_selected_filing(monkeypatch,invalid):
    from collectors.openinfo import cache, settings
    url='https://example.org/HMKB-2025.xlsx'
    monkeypatch.setattr(catalogue_filings,'get_report_urls',lambda *args:{'excel_url':url})
    monkeypatch.setattr(catalogue_sources,'_financial_revision',lambda *args:'accepted-2025')
    seen=[]
    def cached(source):
        seen.append(source)
        return {'ok':True,'parser_version':-1 if invalid=='parser' else settings.EXCEL_PARSER_VERSION,
                'financial_revision':'old' if invalid=='revision' else 'accepted-2025',
                'reporting_date':'2024-12-31' if invalid=='period' else '2025-12-31','sheets':[]}
    monkeypatch.setattr(cache,'_get_excel_cache',cached)
    result=catalogue_sources.cached_report_excel_data('HMKB','NSBU',2025,0)
    assert result['ok'] is (invalid is None)
    if invalid is None:
        assert result['income']==result['balance']
        assert result['income']['source_url']==url
    assert seen==[url]
    monkeypatch.setattr(cache,'_get_excel_cache',lambda source:None)
    assert catalogue_sources.cached_report_excel_data('HMKB','NSBU',2025,0)['ok'] is False


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

    monkeypatch.setattr(catalogue_filings, "get_report_urls", lambda *args: {
        "excel_url": url,
        "excel_url_form1": url,
        "period_type": "quarter",
    })
    monkeypatch.setattr(catalogue_sources, "_make_session", lambda: object())

    def parse(_session, document):
        calls.append(document["excel_url"])
        return parsed

    monkeypatch.setattr(catalogue_sources, "parse_excel_report_document", parse)

    result = catalogue_sources.fetch_report_excel_data("UTGAP", "NSBU", 2025, 1)

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


def test_agat_credit_structured_q3_can_support_the_report_without_excel(monkeypatch):
    issuer = {"id": "1058", "ticker": "ACMT1B2", "name": "AGAT CREDIT",
              "isin": "UZ6058977AB6", "sector": "other"}
    source = "https://openinfo.uz/ru/reports/to_pdf31772/"
    values = {"revenue": 88917943, "net_income": 5544203, "total_assets": 482682178,
              "total_liabilities": 403411621, "total_equity": 79270557}
    monkeypatch.setattr(issuer_sources, "get_all_financials", lambda form: {"ACMT1B2": {"org_type": "microfinance"}})
    monkeypatch.setattr(issuer_sources, "get_financials_series_quarterly", lambda *args: {"2026Q3": values})
    monkeypatch.setattr(issuer_sources, "get_financials_series", lambda *args: {})
    monkeypatch.setattr(issuer_sources, "report_rows", lambda *args: [{"period": "2026Q3", "pdf_url": source}])
    snapshot = issuer_sources.financial_snapshot(issuer, "nsbu", "2026Q3", "separate")
    assert snapshot["sector_template_code"] == "microfinance"
    assert snapshot["quality"]["balance_check"]["status"] == "passed"
    assert service._verified_catalog_fallback(snapshot)
    snapshot["current_values"]["total_equity"] = None
    assert not service._verified_catalog_fallback(snapshot)


@pytest.mark.parametrize('evicted', [False, True], ids=['expired', 'evicted'])
def test_kasu_annual_reserves_survive_download_cache_turnover(monkeypatch, tmp_path, evicted):
    from collectors.openinfo import cache, settings
    from catalogue.parsing import extract_insurance_balance

    # Openinfo annual insurance filing 312, F1 lines 580 and 670, thousands of UZS.
    url = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=annual&org_type=insurance&report_id=312&lang=ru'
    monkeypatch.setattr(settings, 'EXCEL_CACHE_PATH', tmp_path / 'cache.json')
    monkeypatch.setattr(settings, 'EXCEL_CACHE_TTL_SECONDS', 30 * 86400)
    monkeypatch.setattr(catalogue_filings, 'get_report_urls', lambda *args: {'excel_url': url})
    monkeypatch.setattr(catalogue_sources, '_financial_revision', lambda *args: 'filing-312')
    balance_rows = [
        {'label': 'Страховые резервы, всего (стр. 590 + 600 + 610 + 620 + 630 + 640 + 650 + 660)',
         'numeric_values': [296006195.06, 296360594.09]},
        {'label': 'Доля перестраховщиков в страховых резервах, всего (стр. 680 + 690 + 700 + 710)',
         'numeric_values': [109165810.64, 186159662.71]},
    ]
    parsed = {'ok': True, 'sheets': [{'table_rows': balance_rows}], 'financial_revision': 'filing-312',
              'parser_version': settings.EXCEL_PARSER_VERSION, 'content_sha256': 'a' * 64,
              'reporting_date': '2025-12-31', 'source_coverage': {'complete': True, 'issues': []},
              'sheet_count': 1, 'sheets_read': 1, 'warnings': []}
    cache._set_excel_cache(url, parsed)
    def read():
        return catalogue_sources.cached_report_excel_data('KASU', 'NSBU', 2025, 0)
    assert extract_insurance_balance(read()['balance'])['net_insurance_reserves'] == pytest.approx(110200931.38)
    entries = cache._load_excel_cache()
    entries[url]['cached_at'] = 1
    if evicted:
        entries.update({f'other-{i}': {'cached_at': 2} for i in range(499)})
    cache._save_excel_cache(entries)
    if evicted:
        cache._set_excel_cache('next', {})
        assert url not in cache._shared_excel_cache()
    assert cache._get_excel_cache(url) is None
    assert extract_insurance_balance(read()['balance'])['net_insurance_reserves'] == pytest.approx(110200931.38)
    monkeypatch.setattr(catalogue_sources, '_financial_revision', lambda *args: 'corrected-filing')
    assert not read()['ok']
    # A newer download at the same URL supersedes any retained evidence.
    monkeypatch.setattr(catalogue_sources, '_financial_revision', lambda *args: 'filing-312')
    # Openinfo regenerates docProps/core.xml's modified time on every export.
    # Re-reading the complete, unchanged source must preserve both its fiscal
    # binding and the identity of the latest download.
    refreshed = {**parsed, 'financial_revision': None, 'content_sha256': 'b' * 64}
    cache._set_excel_cache(url, refreshed, existing_only=True)
    assert read()['balance']['content_sha256'] == 'b' * 64
    assert extract_insurance_balance(read()['balance'])['net_insurance_reserves'] == pytest.approx(110200931.38, abs=.005, rel=0)
    corrected = deepcopy(refreshed)
    corrected['content_sha256'] = 'c' * 64
    corrected['sheets'][0]['table_rows'][0]['numeric_values'][-1] += 1
    cache._set_excel_cache(url, corrected, existing_only=True)
    assert not read()['ok']
