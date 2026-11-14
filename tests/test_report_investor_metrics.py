"""Public investor indicators retain the filing's context and share basis."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

import sector_report_service as service
from financial_columns import source_store


REPORT = json.loads((Path(__file__).parent / 'fixtures/sector_ui_report.json').read_text())
NEW = {'operating_margin', 'book_value', 'interest_debt_to_equity', 'price_to_book', 'eps_basic'}


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [])
    return deepcopy(REPORT)


def metrics(report):
    return {r['metric_code']: r for r in service.public_report(report)['ratios']}


@pytest.mark.parametrize('missing_short_debt', [False, True])
def test_cbsk_q2_short_term_loans_are_debt_and_missing_is_not_zero(monkeypatch, missing_short_debt):
    case = json.loads((Path(__file__).parent / 'fixtures/cbsk_2026q2_investor_inputs.json').read_text())
    if missing_short_debt:
        case['source']['rows'] = [r for r in case['source']['rows'] if r['metric_id'] != 'bank_borrowings_short']
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [deepcopy(case['source'])])
    out = metrics(case['report'])
    debt = out['interest_debt_to_equity']
    if missing_short_debt:
        assert debt['value'] is None
    else:
        assert debt['value'] == pytest.approx(36000000 / 173774432)
        assert debt['numerator_value'] == 36000000
        assert {'570', '580', '730', '740', '750'} <= {c.get('source_code') for c in debt['components']}
    assert out['price_to_book']['value'] is None
    assert out['price_to_book']['missing_inputs'] == ['common_equity', 'ordinary_shares']
    assert out['eps_basic']['value'] is None
    assert out['eps_basic']['missing_inputs'] == ['profit_ordinary', 'weighted_average_shares']


def test_uzmk_primary_ratios_use_operating_profit_and_equity_not_pretax_profit(report):
    original = deepcopy(report)
    public = service.public_report(report)
    rows = {r['metric_code']: r for r in public['ratios']}
    assert NEW <= rows.keys()
    assert not {'P2', 'P7', 'P8', 'current_ratio', 'quick_ratio'} & rows.keys()
    assert {r['metric_code'] for r in public['additional_ratios']} == {'P2', 'P7', 'P8'}
    assert rows['operating_margin']['value'] == pytest.approx(373505355 / 3205904736 * 100)
    assert rows['book_value']['value'] == 6375622697.23
    assert rows['book_value']['unit'] == 'UZS_thousand'
    assert rows['interest_debt_to_equity']['value'] is None  # Only long-term debt is available.
    assert rows['eps_basic']['value'] is None
    assert rows['eps_basic']['reason_code'] == 'EPS_INPUTS_MISSING'
    assert rows['price_to_book']['value'] is None
    assert report == original


def test_cbsk_q3_uses_reviewed_closing_shares_but_keeps_unverified_eps_blank(tmp_path, monkeypatch):
    from financial_columns import share_disclosures

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'share-disclosures.db'))
    fixtures = Path(__file__).parent / 'fixtures'
    case = json.loads((fixtures / 'cbsk_2026q3_investor_inputs.json').read_text())
    report = case['report']
    documents = json.loads((fixtures / case['source_fixture']).read_text())['CBSK']['documents']
    document = next(d for d in documents if d['period_end'] == report['financial_as_of'])
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [deepcopy(document)])

    out = metrics(report)
    assert out['price_to_book']['value'] == pytest.approx(4.06 * 87879167190 / 185183885970)
    assert out['price_to_book']['missing_inputs'] == []
    assert out['eps_basic']['value'] is None
    assert out['eps_basic']['closing_share_count_verified'] is True
    assert out['eps_basic']['missing_inputs'] == ['profit_ordinary', 'weighted_average_shares']
    assert share_disclosures.read('633', 'CBSK', '2026-06-30', 'separate') is None
    assert share_disclosures.read('633', 'CBSK', '2026-09-30', 'consolidated') is None

    reviewed = share_disclosures.read('633', 'CBSK', '2026-09-30', 'separate')
    assert 'weighted_average_shares' not in reviewed
    correction = {key: value for key, value in reviewed.items() if key in share_disclosures.FIELDS}
    share_disclosures.record({**correction, 'source_url': 'https://example.org/reviewed-correction'},
                             actor='test-reviewer', reason='Verify stored source precedence')
    assert metrics(report)['price_to_book']['share_disclosure_url'] == 'https://example.org/reviewed-correction'


@pytest.mark.parametrize('ticker,invalid_metric,reason,expected,debt_total', [
    ('cbsk', 'net_income', 'SOURCE_NET_PROFIT_MISMATCH', 33000000 / 185183885.97, 33000000),
    ('qatt', 'revenue', 'SOURCE_GROSS_PROFIT_MISMATCH', 3388285 / 36211138, 3388285),
    ('kvts', 'total_assets', 'SOURCE_PASSIVE_TOTAL_MISMATCH', None, None),
])
def test_real_q3_debt_is_blocked_by_balance_discrepancies_but_not_unrelated_income(monkeypatch, ticker, invalid_metric, reason, expected, debt_total):
    from financial_columns import nsbu
    from financial_analysis.report_investor_metrics import _load
    case = json.loads((Path(__file__).parent / f'fixtures/{ticker}_2026q3_investor_inputs.json').read_text())
    report = case['report']
    if case.get('source_fixture'):
        sources = json.loads((Path(__file__).parent / 'fixtures' / case['source_fixture']).read_text())
        doc = next(d for d in sources[ticker.upper()]['documents'] if d['period_end'] == report['financial_as_of'])
    else:
        doc = dict(issuer_id=report['issuer']['id'], scope='separate', period_end=report['financial_as_of'],
                   unit_scale='1000', currency='UZS', quality='valid', source_version=case['source']['source_url'],
                   rows=nsbu.rows(case['source'], template='general'))
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [deepcopy(doc)])
    source = {r['metric_id']: r for r in _load(report) if r['role'] == 'PRIMARY'}
    assert source[invalid_metric]['reason'] == reason
    assert source['total_equity']['quality'] == 'valid'
    debt = metrics(report)['interest_debt_to_equity']
    assert debt['value'] == (pytest.approx(expected) if expected is not None else None)
    if expected is not None:
        assert debt['numerator_value'] == debt_total
        assert {'570', '580', '730', '740', '750'} <= {c.get('source_code') for c in debt['components']}


@pytest.mark.parametrize('bad_balance', [False, True])
def test_balance_ratios_use_balance_anchors_while_eps_still_requires_matching_income(report, monkeypatch, bad_balance):
    rows = source_rows(report, net_income=1, common_equity=500, ordinary_shares=100, eps_basic=42)
    if bad_balance:
        rows[0]['value'] = '123'
    inject(monkeypatch, rows)
    report['instrument'] = {'instrument_type': 'ordinary_share', 'last_price': 10000,
                            'market_as_of': '2026-07-01', 'freshness': {'status': 'fresh'}}
    out = metrics(report)
    assert out['price_to_book']['value'] == (None if bad_balance else 2)
    assert out['eps_basic']['value'] is None


def source_rows(report, **values):
    facts = {r['metric_code']: r['value'] for r in report['verified_facts']}
    values = {'total_assets': facts['total_assets'], 'total_equity': facts['total_equity'], **values}
    return [dict(metric_id=key, raw_label=key, value=str(value), unit='UZS_per_share' if key == 'eps_basic' else 'shares' if key in {'ordinary_shares', 'weighted_average_shares'} else 'UZS_thousand',
                 issuer_id=report['issuer']['id'], standard='NSBU', scope='separate', currency='UZS',
                 period_end='2026-06-30', period_start='2026-01-01' if key in {'eps_basic', 'profit_ordinary', 'weighted_average_shares'} else '2026-06-30',
                 kind='flow' if key in {'profit_ordinary', 'weighted_average_shares'} else 'per_share' if key == 'eps_basic' else 'stock',
                 quality='valid', role='PRIMARY', source_version='filing-1', source_url=report['sources'][0]['url'])
            for key, value in values.items()]


def inject(monkeypatch, rows):
    from financial_columns import observations
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [{}])
    monkeypatch.setattr(observations, 'nsbu', lambda _: deepcopy(rows))


def test_verified_debt_and_share_inputs_are_used_with_correct_units(report, monkeypatch):
    rows = source_rows(report, bank_borrowings_long=100, other_borrowings_long=20,
                       bank_borrowings_short=30, other_borrowings_short=40,
                       current_portion_long_term_debt=10, common_equity=500,
                       ordinary_shares=100, profit_ordinary=60, weighted_average_shares=80)
    inject(monkeypatch, rows)
    report['instrument'] = {'instrument_type': 'ordinary_share', 'last_price': 10000,
                            'market_as_of': '2026-07-01', 'freshness': {'status': 'fresh'}}
    out = metrics(report)
    assert out['interest_debt_to_equity']['value'] == pytest.approx(200 / 6375622697.23)
    assert out['eps_basic']['value'] == 750  # thousand UZS × 1000 / weighted shares
    assert out['eps_basic']['unit'] == 'UZS_per_share'
    assert out['price_to_book']['value'] == 2
    assert out['price_to_book']['market_as_of'] == '2026-07-01'
    assert out['price_to_book']['denominator_value'] == 5000
    assert out['eps_basic']['components']
    for row in out.values():
        if row['metric_code'] in NEW:
            assert row['name_ru'] and row['meaning_en'] and row['formula']


@pytest.mark.parametrize('change', [
    {'scope': 'consolidated'}, {'standard': 'MSFO'}, {'issuer_id': 'other'},
    {'period_end': '2025-06-30'}, {'quality': 'blocked'}, {'unit': 'USD_per_share'},
    {'period_start': '2026-04-01'}, {'role': 'COMPARATIVE'},
])
def test_eps_cannot_cross_contexts_or_use_quarterly_or_unverified_cells(report, monkeypatch, change):
    rows = source_rows(report, eps_basic=42)
    rows[-1].update(change)
    inject(monkeypatch, rows)
    assert metrics(report)['eps_basic']['value'] is None


def test_source_revision_must_reconcile_to_the_report_and_conflicts_stay_missing(report, monkeypatch):
    rows = source_rows(report, eps_basic=42)
    rows[0]['value'] = '123'
    inject(monkeypatch, rows)
    assert metrics(report)['eps_basic']['value'] is None
    rows = source_rows(report, eps_basic=42)
    rows.append({**rows[-1], 'value': '43'})
    inject(monkeypatch, rows)
    assert metrics(report)['eps_basic']['value'] is None


@pytest.mark.parametrize('profit,expected', [(0, 0), (-60, -750)])
def test_zero_and_losses_are_valid_eps_without_annualising(report, monkeypatch, profit, expected):
    inject(monkeypatch, source_rows(report, profit_ordinary=profit, weighted_average_shares=80, ordinary_shares=1000))
    assert metrics(report)['eps_basic']['value'] == expected


def test_reported_basic_eps_is_not_recomputed_from_current_shares(report, monkeypatch):
    inject(monkeypatch, source_rows(report, eps_basic=42, ordinary_shares=1000))
    out = metrics(report)['eps_basic']
    assert out['value'] == 42
    assert out['origin'] == 'reported'


@pytest.mark.parametrize('invalid', ['preferred', 'stale', 'undated', 'negative_equity', 'zero_shares'])
def test_price_to_book_requires_ordinary_equity_shares_and_a_usable_dated_price(report, monkeypatch, invalid):
    inject(monkeypatch, source_rows(report, common_equity=-500 if invalid == 'negative_equity' else 500,
                                   ordinary_shares=0 if invalid == 'zero_shares' else 100))
    report['instrument'] = {'instrument_type': 'preferred_share' if invalid == 'preferred' else 'ordinary_share',
                            'last_price': 10000, 'market_as_of': None if invalid == 'undated' else '2026-07-01',
                            'freshness': {'status': 'very_stale' if invalid == 'stale' else 'fresh'}}
    assert metrics(report)['price_to_book']['value'] is None


def test_blocked_filings_and_financial_sectors_do_not_gain_enterprise_metrics(report, monkeypatch):
    for status in ('quality_blocked', 'mapping_failed', 'no_source'):
        report['status'] = status
        out = service.public_report(report)
        assert out['ratios'] == []
        assert out.get('additional_ratios', []) == []
    report['status'] = 'available'
    for org in ('bank', 'insurance', 'investment_fund_ifrs_annual'):
        report['issuer']['organization_type'] = org
        assert not NEW & metrics(report).keys()


def test_ifrs_exact_aliases_keep_ordinary_equity_and_profit_separate():
    from financial_columns.ifrs import metric
    assert metric('Equity attributable to ordinary shareholders', 'BS') == 'common_equity'
    assert metric('Profit attributable to ordinary equity holders of the parent', 'PL') == 'profit_ordinary'
    assert metric('Equity attributable to owners of the parent', 'BS') == 'equity_owners'


@pytest.mark.parametrize('mode', ['revised_income', 'mixed_sources'])
def test_revised_income_and_mixed_source_versions_cannot_fill_eps(report, monkeypatch, mode):
    if mode == 'revised_income':
        rows = source_rows(report, eps_basic=42, net_income=1)
    else:
        rows = source_rows(report, profit_ordinary=60)
        rows += [{**r, 'source_version': 'filing-2'} for r in source_rows(report, weighted_average_shares=80)]
    inject(monkeypatch, rows)
    assert metrics(report)['eps_basic']['value'] is None


@pytest.mark.parametrize('ticker,debt,equity', [
    ('uztl', 5628836416 + 1936822167, 3030753112),
    ('uzal', 379419223.7 + 4386362917.1, 1099340322.3),
])
def test_real_nsbu_source_forms_include_current_debt_without_double_counting(report, monkeypatch, ticker, debt, equity):
    from financial_columns import nsbu
    source = json.loads((Path(__file__).parent / f'fixtures/openinfo/{ticker}_2025_complete_rows.json').read_text())
    rows = nsbu.rows(source, template='general')
    values = {r['metric_id']: r['current']['value'] for r in rows if r['metric_id']}
    report.update(period='2025', financial_as_of='2025-12-31')
    report['issuer']['ticker'] = ticker.upper()
    for fact in report['verified_facts']:
        fact['period'] = '2025'
        if fact['metric_code'] in values:
            fact['value'] = values[fact['metric_code']]
    doc = dict(issuer_id=report['issuer']['id'], scope='separate', period_end='2025-12-31',
               unit_scale='1000', currency='UZS', quality='valid', source_version='real-filing', rows=rows)
    for row in rows:
        row['source_url'] = report['sources'][0]['url']
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [deepcopy(doc)])
    out = metrics(report)['interest_debt_to_equity']
    assert out['value'] == pytest.approx(debt / equity)
    assert out['numerator_value'] == pytest.approx(debt)


def test_ifrs_uses_approved_source_rows_and_includes_leases(report, monkeypatch):
    from financial_ingestion import publication
    from financial_columns import observations
    report.update(standard='ifrs', scope='consolidated')
    rows = source_rows(report, borrowings_short=100, borrowings_long=200, lease_liabilities=50, eps_basic=42)
    for row in rows:
        row.update(standard='MSFO', scope='consolidated')
    monkeypatch.setattr(publication, 'snapshots', lambda ticker, **kw: [{'period_end':'2026-06-30'}])
    monkeypatch.setattr(observations, 'ifrs', lambda docs: deepcopy(rows))
    out = metrics(report)
    assert out['interest_debt_to_equity']['value'] == pytest.approx(350 / 6375622697.23)
    assert out['eps_basic']['value'] == 42
    rows[-2]['value'] = None  # Missing leases are not zero.
    assert metrics(report)['interest_debt_to_equity']['value'] is None


@pytest.fixture
def biok_report(report, monkeypatch, tmp_path):
    # Real BIOK 2024 audited figures (p.4: assets/equity; p.5: net profit).
    # The price is an explicit test input, not a historical quote claim.
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    from financial_ingestion import publication
    monkeypatch.setattr(publication, 'snapshots', lambda *a, **kw: [])
    report.update(standard='ifrs', scope='separate', period='2024', financial_as_of='2024-12-31')
    report['issuer'].update(id='396', ticker='BIOK', name='Biokimyo AJ')
    values = dict(total_assets=174930061, total_equity=143292694, net_income=26037647)
    report['verified_facts'] = [dict(metric_code=k, value=v, period='2024',
        unit_normalized='thousand UZS', verification_status='verified') for k,v in values.items()]
    report['instrument'] = dict(instrument_type='ordinary_share', last_price=10000,
        market_as_of='2025-01-06', freshness={'status':'fresh'})
    return report


def share_basis():
    return json.loads((Path(__file__).parent / 'fixtures/biok_2024_share_basis.json').read_text())


def import_basis(basis):
    from financial_columns import share_disclosures
    return share_disclosures.record(basis, actor='test-reviewer', reason='Checked source lines')


def test_biok_2024_report_uses_dated_share_disclosures_without_financial_form_cells(biok_report):
    import_basis(share_basis())
    out = metrics(biok_report)
    assert out['eps_basic']['value'] == pytest.approx(26037647 * 1000 / 5713280)
    assert out['price_to_book']['value'] == pytest.approx(10000 / (143292694 * 1000 / 5713280))
    assert out['eps_basic']['basis'] == 'verified_share_disclosure'
    assert any(c.get('source_url') == share_basis()['source_url'] for c in out['eps_basic']['components'])


@pytest.mark.parametrize('change', [
    {'issuer_id':'78'}, {'ticker':'ABKZ'}, {'period_end':'2023-12-31', 'period_start':'2023-01-01'},
    {'scope':'consolidated'}, {'ordinary_only':False},
])
def test_different_issuer_period_scope_or_share_rights_cannot_fill_missing_metrics(biok_report, change):
    import_basis({**share_basis(), **change})
    out = metrics(biok_report)
    assert out['eps_basic']['value'] is None
    assert out['price_to_book']['value'] is None


def test_closing_shares_never_replace_missing_weighted_average(biok_report):
    basis = share_basis()
    del basis['weighted_average_shares']
    import_basis(basis)
    out = metrics(biok_report)
    assert out['price_to_book']['value'] is not None
    assert out['eps_basic']['value'] is None
    assert out['eps_basic']['missing_inputs'] == ['weighted_average_shares']


def test_weighted_shares_must_cover_the_whole_income_period(biok_report):
    import_basis({**share_basis(), 'period_start':'2024-04-01'})
    out = metrics(biok_report)
    assert out['price_to_book']['value'] is not None
    assert out['eps_basic']['value'] is None


def test_nsbu_uses_share_counts_but_never_borrows_ifrs_profit_or_equity(biok_report):
    import_basis(share_basis())
    biok_report['standard'] = 'nsbu'
    for fact in biok_report['verified_facts']:
        fact['value'] /= 2
    out = metrics(biok_report)
    assert out['eps_basic']['value'] == pytest.approx(26037647 / 2 * 1000 / 5713280)
    assert out['price_to_book']['value'] == pytest.approx(10000 / (143292694 / 2 * 1000 / 5713280))


def test_share_disclosures_cannot_override_conflicting_filing_inputs(biok_report, monkeypatch):
    import_basis(share_basis())
    from financial_analysis import report_investor_metrics as subject
    # Existing source conflicts/blocks remain binding, even with a supplemental disclosure.
    rows = []
    for key,value in [('total_assets',174930061),('total_equity',143292694),('eps_basic',42)]:
        rows.append(dict(issuer_id='396', standard='MSFO', scope='separate', source_version='filing',
            source_url='https://openinfo.uz/source', metric_id=key, value=str(value),
            period_end='2024-12-31', period_start='2024-01-01' if key=='eps_basic' else '2024-12-31',
            unit='UZS_per_share' if key=='eps_basic' else 'UZS_thousand', quality='valid', role='PRIMARY'))
    rows.append({**rows[-1], 'value':'43'})
    monkeypatch.setattr(subject, '_load', lambda _: rows)
    assert metrics(biok_report)['eps_basic']['value'] is None


@pytest.mark.parametrize('change', [{'unit':'UZS_thousand'}, {'ordinary_shares':-1},
    {'weighted_average_shares':0}, {'ordinary_only':True,'source_lines':{}}, {'source_url':''}])
def test_share_import_requires_evidence_and_valid_units(biok_report, change):
    with pytest.raises(ValueError):
        import_basis({**share_basis(), **change})


def test_conflicting_share_disclosures_are_withheld_until_explicit_replacement(biok_report):
    from financial_columns import share_disclosures
    first = import_basis(share_basis())
    changed = {**share_basis(), 'ordinary_shares':'6000000'}
    with pytest.raises(ValueError, match='replace'):
        import_basis(changed)
    assert share_disclosures.read('396', 'BIOK', '2024-12-31', 'separate')['ordinary_shares'] == '5713280'
    second = share_disclosures.record(changed, actor='reviewer', reason='Explicit correction', replace=True)
    assert first != second

def test_biok_exchange_identity_matches_the_source_issuer():
    from entity_resolver import resolve_security
    assert resolve_security({'ticker': 'BIOK', 'isin': 'UZ7025870005'})['org_id'] == '396'
    assert resolve_security({'ticker': 'ABKZ', 'isin': 'UZ7047650005'})['org_id'] == '78'


@pytest.mark.parametrize('variant', ['ordinary_only', 'preferred', 'wrong_identity', 'wrong_date'])
def test_real_biok_form5_supplies_dated_book_inputs_without_substituting_eps(report, variant):
    from financial_analysis.report_investor_metrics import calculate
    from financial_columns.share_disclosures import form5_basis

    source = json.loads(Path('tests/fixtures/openinfo/biok_2026q3_equity.json').read_text(encoding='utf-8'))
    if variant == 'preferred':
        rows = source['sheets'][0]['source_rows']
        for row in rows:
            if row['row'] in (34, 39):
                row['cells'][8] = 100
            if row['row'] == 37:
                row['cells'][8] = 5713380
    basis = form5_basis(source, ticker='BIOK', issuer_id='396', tin='200240495' if variant == 'wrong_identity' else source['tin'],
                        period_end='2026-06-30' if variant == 'wrong_date' else source['period_end'])
    if variant in {'wrong_identity', 'wrong_date'}:
        assert basis is None
        return
    assert basis['ordinary_shares'] == '5713280'
    assert 'weighted_average_shares' not in basis
    assert basis['ordinary_only_at_end'] == (variant == 'ordinary_only')
    report['issuer'].update(id='396', ticker='BIOK')
    report.update(standard='nsbu', period='2026Q3', financial_as_of='2026-09-30')
    report['instrument'] = {'instrument_type': 'ordinary_share', 'last_price': 14301,
                            'market_as_of': '2026-11-12', 'freshness': {'status': 'fresh'}}
    report['verified_facts'] = [
        {'metric_code': 'total_equity', 'value': 130595895, 'period': '2026Q3',
         'unit_normalized': 'thousand UZS', 'verification_status': 'verified'},
        {'metric_code': 'net_income', 'value': 12628226, 'period': '2026Q3',
         'unit_normalized': 'thousand UZS', 'verification_status': 'verified'},
    ]
    result = {r['metric_code']: r for r in calculate(report, [], {**basis, 'verification_status': 'verified'})}
    expected = pytest.approx(14301 * 5713280 / 130595895000) if variant == 'ordinary_only' else None
    assert result['price_to_book']['value'] == expected
    assert result['price_to_book']['share_disclosure_url'] == source['source_url']
    assert result['eps_basic']['value'] is None
    assert result['eps_basic']['closing_share_count_verified'] is True
    assert result['eps_basic']['missing_inputs'] == ['profit_ordinary', 'weighted_average_shares']

@pytest.mark.parametrize('matching_issuer', [True, False])
def test_openinfo_equity_attachment_is_imported_only_for_its_issuer(tmp_path, monkeypatch, matching_issuer):
    from catalogue import history
    from collectors.openinfo import transport
    from financial_columns import share_disclosures

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'share-disclosures.db'))
    source = json.loads(Path('tests/fixtures/openinfo/biok_2026q3_equity.json').read_text(encoding='utf-8'))
    calls = []
    def detail(session, path):
        assert path == '/reports/jsc/quarter/18938/'
        return {'id': 18938, 'organization': {'id': 396 if matching_issuer else 78},
                'organization_inn': 200468069, 'int_report': source['source_url']}
    def workbook(session, url):
        calls.append(url)
        return source
    monkeypatch.setattr(transport, '_json_get', detail)
    monkeypatch.setattr(history, '_parse_workbook_uncached', workbook)
    query = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=jsc&report_id=18938'
    args = dict(ticker='BIOK', issuer_id='396', period_end='2026-09-30', excel_url=query)
    assert share_disclosures.collect_form5(None, **args) is matching_issuer
    assert share_disclosures.collect_form5(None, **args) is False
    assert calls == ([source['source_url']] if matching_issuer else [])
    basis = share_disclosures.read('396', 'BIOK', '2026-09-30', 'separate')
    assert (basis or {}).get('ordinary_shares') == ('5713280' if matching_issuer else None)
