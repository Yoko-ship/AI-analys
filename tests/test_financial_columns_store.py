import json
from pathlib import Path

import pytest

from financial_columns import source_store


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))


def bank_data():
    workbook = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json').read_text(encoding='utf-8'))
    return {'ok': True, 'income': workbook, 'balance': workbook}


def record(data, **changes):
    args = dict(ticker='IPTB', issuer_id='217', year=2026, quarter=3, template='bank',
                data=data, urls={'excel_url': data['income']['source_url'], 'published_at': '2026-10-20'})
    return source_store.record_nsbu(**{**args, **changes})


def test_raw_forms_are_immutable_versioned_and_shared_by_legal_issuer(isolated_store):
    data = bank_data()
    first = record(data)
    assert record(data) == first
    documents = source_store.read('217', standard='NSBU', scope='separate')
    assert len(documents) == 1
    original = documents[0]
    assert len(original['source_forms']) == 1  # income and balance point at the same workbook
    assert original['source_coverage']['complete']
    income = next(r for r in original['rows'] if r['source_form'] == 'BANK_PL' and r['source_code'] == '1л')
    assert income['current']['value'] == '9447836814'
    data['income']['sheets'][0]['source_rows'][105]['cells'][1] += 1
    second = record(data)
    assert second != first
    assert source_store.version(first)['rows'] == original['rows']
    revised = source_store.read('217', standard='NSBU', scope='separate')[0]
    assert revised['source_version'] == second
    assert revised['previous_version'] == first
    assert source_store.read('217', standard='NSBU', scope='consolidated') == []
    assert source_store.read('217', standard='MSFO', scope='separate') == []
    assert source_store.read('218', standard='NSBU', scope='separate') == []


def test_missing_source_unit_is_blocked_not_silently_assumed(isolated_store):
    data = bank_data()
    for sheet in data['income']['sheets']:
        for row in sheet['source_rows']:
            row['cells'] = [None if isinstance(v, str) and ('тыс.' in v or 'тыс.сум' in v) else v for v in row['cells']]
    record(data)
    doc = source_store.read('217', standard='NSBU', scope='separate')[0]
    assert doc['quality'] == 'blocked'
    assert 'UNIT_UNRESOLVED' in doc['source_coverage']['issues']
    from financial_columns.observations import nsbu
    assert all(r['value'] is None for r in nsbu([doc]))
