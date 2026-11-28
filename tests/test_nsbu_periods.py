"""Reviewed fiscal periods must never leak across issuers or source revisions."""
from copy import deepcopy
import json

import pytest

import nsbu_periods as periods


@pytest.mark.parametrize("kind,quarter", [("quarter", 3), ("annual", 0)])
def test_missing_period_uses_publication_calendar_without_shifting(kind, quarter):
    result = periods.resolve_period(None, kind, published_at="2022-09-14T10:58:39")
    assert result == {"year": 2022, "quarter": quarter, "period_source": "publication_date"}


def test_reported_period_wins_and_conflicts_are_not_missing_metadata():
    assert periods.resolve_period("2021-07-29", "quarter", quarter=2,
        published_at="2022-09-14") == {"year": 2021, "quarter": 2, "period_source": "reported"}
    assert periods.resolve_period("2024-12-31", "annual", published_at="2023-05-01") is None
    assert periods.resolve_period(None, "quarter", published_at="bad date") is None


def ledger():
    return json.loads(periods._LEDGER_PATH.read_text(encoding="utf-8"))


def test_reviewed_sources_resolve_by_issuer_and_document():
    assert periods.resolve_annual_year("374", "3109", 2018) == 2017
    assert periods.resolve_annual_year(374, 3110, 2019) == 2018


@pytest.mark.parametrize("identity", [
    ("375", "3109", 2018),
    ("374", "3279", 2018),
    ("UZIR", "3109", 2018),
    ("UZIRP", "3109", 2018),
    ("374", "3109", 2017),
    ("374", "3109", 2019),
    (None, "3109", 2018),
    ("374", "3109", "2018"),
])
def test_unknown_identity_or_changed_source_label_is_not_corrected(identity):
    assert periods.resolve_annual_year(*identity) is None


def test_ledger_rejects_duplicate_sources_even_if_the_year_differs():
    payload = ledger()
    duplicate = deepcopy(payload["annual_periods"][0])
    duplicate.update(labeled_year=2019, fiscal_year=2018)
    payload["annual_periods"].append(duplicate)
    with pytest.raises(ValueError, match="Duplicate"):
        periods._validate_ledger(payload)


@pytest.mark.parametrize("update", [{"page": 0}, {"page": True}, {"sha256": "unknown"}])
def test_document_evidence_requires_a_page_and_content_hash(update):
    payload = ledger()
    payload["annual_periods"][0]["evidence"][1].update(update)
    with pytest.raises(ValueError):
        periods._validate_ledger(payload)


def test_a_source_link_alone_is_not_a_document_review():
    payload = ledger()
    payload["annual_periods"][0]["evidence"] = payload["annual_periods"][0]["evidence"][:1]
    with pytest.raises(ValueError, match="document bytes"):
        periods._validate_ledger(payload)


@pytest.mark.parametrize("update", [
    {"revenue": 324369277},  # The ledger cannot carry financial overrides.
    {"ticker": "UZIR"},
    {"org_id": 374},
    {"record_id": ""},
    {"labeled_year": "2018"},
    {"fiscal_year": True},
    {"fiscal_year": 1999},
    {"fiscal_year": 2018},
    {"fiscal_year": 2019},
    {"reviewed_by": " "},
    {"reviewed_at": "2026-9-19"},
    {"reviewed_at": "2026-02-30"},
    {"evidence": []},
    {"evidence": [{"url": "https://example.com/report.pdf", "description": "An unrelated source"}]},
    {"evidence": [{"url": "http://openinfo.uz/report.pdf", "description": "Insecure source"}]},
    {"evidence": [{"url": "https://openinfo.uz/", "description": "No document"}]},
    {"evidence": [{"url": "https://openinfo.uz/report.pdf", "description": ""}]},
])
def test_ledger_rejects_unreviewable_or_nonperiod_metadata(update):
    payload = ledger()
    payload["annual_periods"][0].update(update)
    with pytest.raises(ValueError):
        periods._validate_ledger(payload)


@pytest.mark.parametrize("payload", [None, [], {}, {"schema_version": True, "annual_periods": []},
                                         {"schema_version": 2, "annual_periods": []}])
def test_ledger_rejects_invalid_schema(payload):
    with pytest.raises(ValueError):
        periods._validate_ledger(payload)


@pytest.mark.parametrize('issuer, record, approval, stated, year, family, published', [
    ('841', '307', 21812, '2024-01-01', 2023, 'bank', '2024-02-15T16:42:08'),
    ('841', '269', 19685, '2023-01-01', 2022, 'bank', '2023-02-10T13:39:21'),
    ('636', '276', 1596, None, 2015, 'jsc', '2016-06-13T04:16:57'),
])
def test_approval_discovers_reviewed_annual_with_missing_or_conflicting_date(
        monkeypatch, issuer, record, approval, stated, year, family, published):
    from catalogue import sources

    properties = {'org_type': family, 'report_type': 'annual'}
    filing = {'id': approval, 'organization': issuer, 'object_id': record, 'pub_date': published,
              'report_type': 'NSBU', 'status': 'approved', 'properties': properties}
    detail = {'id': record, 'parent_id': approval, 'organization': {'id': issuer}, 'status': 'approved',
              'pub_date': filing['pub_date'], 'reporting_year': stated,
              'balance_sheet_report': [{'title': 'Assets'}], 'financial_results_report': [{'title': 'Profit'}]}
    monkeypatch.setattr(sources, '_json_get', lambda *args: detail)
    def discover():
        return sources.additional_annual_forms(None, issuer, [filing], [{'id': record, 'reporting_year': None}], [])
    assert [r['reporting_year'] for r in discover()] == [year]
    detail['reporting_year'] = '2014-10-01'
    assert discover() == []
    detail.update(reporting_year=stated, parent_id=approval + 1)
    filing['id'] = approval + 1
    assert discover() == []
