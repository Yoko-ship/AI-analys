"""Reviewed fiscal periods must never leak across issuers or source revisions."""
from copy import deepcopy
import json

import pytest

import nsbu_periods as periods


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
