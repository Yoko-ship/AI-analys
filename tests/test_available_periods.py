"""The analysis-period selector must retain OpenInfo's full quarterly history."""
from __future__ import annotations

import openinfo_collector as collector
import collectors.openinfo.documents as collectors_openinfo_documents
import collectors.openinfo.issuers as collectors_openinfo_issuers
import collectors.openinfo.transport as collectors_openinfo_transport
import pytest


def test_known_ticker_resolves_through_its_catalogue_name(monkeypatch):
    """The company-page action sends YGSY, while OpenInfo indexes its name."""
    seen = []

    def fake_get(_session, path, params=None):
        seen.append({"path": path, "params": params})
        return [{
            "id": 482,
            "full_name_text": '"Yuggazstroy" aksiyadorlik jamiyati',
            "logo": "https://openinfo.uz/logo.png",
        }]

    monkeypatch.setattr(collectors_openinfo_transport, "_json_get", fake_get)

    resolved = collectors_openinfo_issuers.resolve_company("YGSY", session=object())

    assert seen == [{"path": "/home/autofill/", "params": {"name": '"Yuggazstroy" AJ'}}]
    assert resolved["input"] == "YGSY"
    assert resolved["org_id"] == "482"


def test_available_periods_merges_quarters_older_than_structured_window(monkeypatch):
    """The structured endpoint has only ten records; unified retains 2016."""
    def fake_get(_session, path, params=None):
        if path == "/reports/accounting-report/7/":
            if params["report_type"] == "annual":
                return [{"reporting_year": 2016}, {"reporting_year": 2025}]
            return [
                {"period": "Q2 2023"},
                {"period": "Q3 2023"},
            ]
        assert path == "/reports/unified-financial-reports/"
        assert params["organization"] == "7"
        assert params["page"] == 1
        return {
            "results": [
                {"report_type": "NSBU", "pub_date": "2023-07-20T10:00:00",
                 "properties": {"report_type": "quarter", "report_title": "Q2 2023"}},
                {"report_type": "NSBU", "pub_date": "2016-04-29T10:00:00",
                 "properties": {"report_type": "quarter", "report_title": "Q1 2016"}},
                {"report_type": "NSBU", "pub_date": "2016-07-15T10:00:00",
                 "properties": {"report_type": "quarter", "report_title": "Q2 2016"}},
                {"report_type": "NSBU", "pub_date": "2016-10-24T10:00:00",
                 "properties": {"report_type": "quarter", "report_title": "Q3 2016"}},
                {"report_type": "NSBU", "pub_date": "2017-01-17T10:00:00",
                 "properties": {"report_type": "quarter"}},
                {"report_type": "MSFO", "pub_date": "2016-04-29T10:00:00",
                 "properties": {"report_type": "quarter"}},
            ],
            "next": None,
        }

    monkeypatch.setattr(collectors_openinfo_transport, "_json_get", fake_get)

    periods = collectors_openinfo_documents.fetch_available_periods("7", session=object())

    assert periods["annual_years"] == [2025, 2016]
    assert periods["quarterly"] == [
        {"year": 2023, "quarter": 3},
        {"year": 2023, "quarter": 2},
        {"year": 2016, "quarter": 3},
        {"year": 2016, "quarter": 2},
        {"year": 2016, "quarter": 1},
    ]
    assert periods["latest_quarterly"] == {"year": 2023, "quarter": 3}


def test_available_periods_reads_late_uqeq_statement_and_reports_unresolved(monkeypatch):
    paths = []
    def fetch(session, path, params=None):
        paths.append(path)
        if path.startswith('/reports/accounting-report/'):
            return []
        if path == '/reports/jsc/quarter/11260/':
            return {'id': 11260, 'organization': {'id': 310},
                    'reporting_year': '2021-07-29', 'quarter_no': '5'}
        if path == '/reports/unified-financial-reports/':
            return {'results': [
                {'id': 16009, 'object_id': 11260, 'organization': 310, 'report_type': 'NSBU',
                 'pub_date': '2022-09-14T10:58:39', 'properties': {'report_type': 'quarter', 'org_type': 'jsc'}},
                {'id': 16010, 'organization': 310, 'report_type': 'NSBU',
                 'pub_date': '2025-11-20', 'properties': {'report_type': 'quarter'}},
            ]}
        raise AssertionError(path)
    monkeypatch.setattr(collectors_openinfo_transport, '_json_get', fetch)
    result = collectors_openinfo_documents.fetch_available_periods('310', session=object())
    assert result['quarterly'] == [{'year': 2021, 'quarter': 2}]
    assert paths.count('/reports/jsc/quarter/11260/') == 1
    assert result['unresolved'][0]['id'] == 16010


@pytest.mark.parametrize("kind,quarter", [("quarter", 3), ("annual", 0)])
def test_selector_labels_publication_fallback_when_original_has_no_period(monkeypatch, kind, quarter):
    def fetch(session, path, params=None):
        if path.startswith('/reports/accounting-report/'):
            return []
        if path == f'/reports/jsc/{kind}/11260/':
            return {'id': 11260, 'organization': {'id': 310}, 'reporting_year': None}
        return {'results': [{'id': 16009, 'object_id': 11260, 'report_type': 'NSBU',
            'pub_date': '2022-09-14', 'properties': {'report_type': kind, 'org_type': 'jsc'}}]}
    monkeypatch.setattr(collectors_openinfo_transport, '_json_get', fetch)
    result = collectors_openinfo_documents.fetch_available_periods('310', session=object())
    assert result['quarterly'] == ([{'year': 2022, 'quarter': 3}] if quarter else [])
    assert result['annual_years'] == ([] if quarter else [2022])
    assert result['publication_fallbacks'] == [{'id': 16009, 'year': 2022, 'quarter': quarter,
                                             'period_source': 'publication_date'}]
