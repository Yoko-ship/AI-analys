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

def test_scoped_bank_workbooks_keep_separate_and_group_values_apart(isolated_store):
    data=bank_data()
    separate=record(data)
    group=record(data,urls={'excel_url':data['income']['source_url'],'title':'Консолидированная финансовая отчетность'})
    assert separate!=group
    assert source_store.read('217',standard='NSBU',scope='separate')[0]['source_version']==separate
    series, sources=source_store.consolidated_series('217')
    assert series['2026Q3']['total_assets']>0
    assert [s['report_id'] for s in sources]==[group]


def test_replaying_iptb_q4_preserves_the_later_annual_balance_and_archives_both(isolated_store):
    filings = json.loads(Path('tests/fixtures/openinfo/iptb_2019_year_end_deposits.json').read_text())
    def ingest(kind, published):
        src = filings[kind]
        book = {'sheets': [{'sheet': src['sheet'], 'source_rows': src['rows']}], 'source_url': src['source_url'],
                'source_coverage': {'complete': True, 'issues': []}}
        return record({'ok': True, 'income': book, 'balance': book}, issuer_id='17', year=2019,
                      quarter=4 if kind == 'quarter' else 0, urls={'excel_url': src['source_url'], 'published_at': published})
    first = ingest('quarter', '2020-01-22T09:51:48')
    annual = ingest('annual', '2020-10-14T12:06:37')
    assert ingest('quarter', '2020-01-22T09:51:48') == first
    head = source_store.read('17', standard='NSBU', scope='separate', period_end='2019-12-31')[0]
    assert head['source_version'] == annual
    assert source_store.read_filing_version('17','separate','2019-12-31',
                                            {'excel_url':filings['quarter']['source_url']})[0]['source_version'] == first
    amounts = {r['metric_id']: r['current']['value'] for r in head['rows']}
    assert amounts['total_assets'] == '23587804019'
    corrected = ingest('quarter', '2020-10-15')
    assert source_store.read('17', standard='NSBU', scope='separate', period_end='2019-12-31')[0]['source_version'] == corrected


def test_inconsistent_gross_loan_components_cannot_produce_a_zero_ratio(isolated_store):
    from financial_columns import bank_history
    filing = json.loads(Path('tests/fixtures/openinfo/iptb_2019_year_end_deposits.json').read_text())['annual']
    book = {'source_url': filing['source_url'], 'sheets': [{'sheet': filing['sheet'], 'source_rows': filing['rows']}],
            'source_coverage': {'complete': True}}
    def current():
        record({'ok': True, 'income': book, 'balance': book}, issuer_id='17', year=2019, quarter=0)
        return bank_history.cells('IPTB', '17', 'bank', ['2019'])['2019']

    selected = current()
    assert selected['customer_funds']['value'] == '7787309795'
    assert 'loans_gross' not in selected and 'loans_to_deposits' not in selected
    # A fully leased portfolio can legitimately disclose zero gross loans.
    next(row for row in filing['rows'] if row['row'] == 50)['cells'][1] = 19792761803
    selected = current()
    assert selected['loans_gross']['value'] == '0'
    assert selected['loans_to_deposits']['value'] == '0'
