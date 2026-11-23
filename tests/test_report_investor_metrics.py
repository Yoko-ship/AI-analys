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


def test_hmkb_published_ifrs_eps_appears_in_bank_report_only_for_its_scope(report, monkeypatch):
    from financial_analysis import report_investor_metrics as subject
    report.update(standard='ifrs', scope='consolidated', period='2025', financial_as_of='2025-12-31')
    report['issuer'].update(id='8', ticker='HMKB', name='Hamkorbank', organization_type='bank')
    report['verified_facts'] = [dict(metric_code='net_income', value=1786756000, period='2025',
        unit_normalized='thousand UZS', verification_status='verified')]
    base = dict(issuer_id='8', standard='MSFO', scope='consolidated', period_start='2025-01-01',
                period_end='2025-12-31', quality='valid', role='PRIMARY', source_version='published',
                source_url='https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf')
    monkeypatch.setattr(subject, '_load', lambda r: [dict(base, metric_id='net_income', value='1786756000',unit='UZS_thousand'),
        dict(base, metric_id='eps_basic', value='14.22', unit='UZS_per_share')])
    out = metrics(report)
    assert out['eps_basic']['value'] == 14.22
    assert out['book_value_per_share']['missing_inputs'] == ['common_equity','ordinary_shares']
    assert 'operating_margin' not in out and 'ebit' not in out
    report['scope'] = 'separate'
    assert metrics(report).get('eps_basic', {}).get('value') is None


@pytest.mark.parametrize('published,shown,source_unit', [
    ('2026-05-07',True,'UZS_per_share'), ('2027-05-07',False,None), ('',False,None),
    ('2026-05-07',False,'USD_per_share')])
def test_hmkb_separate_report_links_other_published_basis_without_substituting_eps(report, monkeypatch, published, shown, source_unit):
    from financial_ingestion import investor_eps, publication
    from financial_analysis import report_investor_metrics as subject
    import issuer_financials
    report.update(scope='separate',standard='nsbu',period='2026Q3',financial_as_of='2026-09-30')
    report['issuer'].update(id='8',ticker='HMKB',organization_type='bank',name='Hamkorbank')
    report['instrument']={'instrument_type':'ordinary_share','valuation_as_of':'2026-11-20'}
    url='https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf'
    snapshot={'org_id':'8','scope':'consolidated','period_end':'2025-12-31','payload':{
        'classification':{'role':'PRIMARY'}, 'source':{'pdf_url':url,'source_published_at':published},
        'source_rows':[{'metric_id':'eps_basic'}]}}
    monkeypatch.setattr(publication,'snapshots',lambda ticker,scope: [snapshot] if scope=='consolidated' else [])
    monkeypatch.setattr(issuer_financials,'resolve_issuer',lambda ticker: report['issuer'])
    monkeypatch.setattr(subject,'_metrics_at',lambda *a:[{'metric_code':'eps_basic','value':14.22,'unit':'UZS_per_share',
        'verification_status':'verified','components':[{'metric_id':'eps_basic','source_url':url,'page':48}]}])
    direct = {'standard':'ifrs','scope':'consolidated','period':'2025','value':14.22,'unit':source_unit,
              'source_url':url,'page':48} if source_unit else None
    monkeypatch.setattr(investor_eps,'official_eps',lambda *args: direct)
    eps=metrics(report)['eps_basic']
    assert eps['value'] is None and not eps.get('last_verified')
    if shown:
        assert eps['other_filing']=={'standard':'ifrs','scope':'consolidated','period':'2025','value':14.22,
                                     'unit':'UZS_per_share','source_url':url,'page':48}
    else:
        assert not eps.get('other_filing')


def test_verified_older_eps_survives_a_newer_filing_without_usable_eps(report, monkeypatch):
    from financial_ingestion import investor_eps, publication
    from financial_analysis import report_investor_metrics as subject
    import issuer_financials
    report.update(standard='nsbu', scope='separate', period='2027Q3', financial_as_of='2027-09-30')
    report['instrument'] = {'valuation_as_of':'2027-11-20'}
    report['issuer'].update(id='8',ticker='HMKB')
    old = {'standard':'ifrs','scope':'consolidated','period':'2025','value':14.22,'unit':'UZS_per_share',
           'source_url':'https://openinfo.uz/media/msfo/ba173c49-969f-48b2-8657-64d386332c52.pdf','page':48}
    snapshot = {'org_id':'8','period_end':'2026-12-31','payload':{
        'classification':{'role':'PRIMARY'}, 'source':{'source_published_at':'2027-05-07',
        'pdf_url':'https://openinfo.uz/media/msfo/newer-example.pdf'},
        'source_rows':[{'metric_id':'eps_basic'}]}}
    monkeypatch.setattr(publication,'snapshots',lambda ticker,scope: [snapshot] if scope=='consolidated' else [])
    monkeypatch.setattr(investor_eps,'official_eps',lambda *args: old)
    monkeypatch.setattr(issuer_financials,'resolve_issuer',lambda ticker: report['issuer'])
    monkeypatch.setattr(subject,'_metrics_at',lambda *args: [])
    assert subject._published_ifrs_eps(report) == old


@pytest.mark.parametrize('treasury', [0, 100])
def test_abkz_charter_and_filing_verify_september_book_value(report, monkeypatch, treasury):
    report.update(period='2026Q3', financial_as_of='2026-09-30')
    report['issuer'].update(id='78', ticker='ABKZ', name='Andijon biokimyo zavodi')
    report['verified_facts'] = [dict(metric_code=k, value=v, period='2026Q3',
                                     unit_normalized='thousand UZS', verification_status='verified')
                                for k,v in [('total_assets',136766523), ('total_equity',94790492), ('net_income',6317281)]]
    rows = source_rows(report, share_capital=24070520, treasury_shares=treasury)
    inject(monkeypatch, [{**r, 'period_end':'2026-09-30', 'period_start':'2026-09-30'} for r in rows])
    out = metrics(report)
    book = out['book_value_per_share']
    if treasury:
        assert book['value'] is None
        assert 'eps_closing_estimate' not in out
        return
    assert book['value'] == pytest.approx(16051.42049847)
    assert out.get('eps_closing_estimate', {}).get('value') == pytest.approx(6317281 * 1000 / 5905427)
    assert book['denominator_value'] == 5905427
    assert book['share_disclosure_url'].startswith('https://www.uzse.uz/')
    assert out['eps_basic']['value'] is None


@pytest.mark.parametrize('ticker,org,isin,assets,capital,equity,shares,close,end,quote_date,profit', [
    ('JASM','246','UZ7012450001',89023233,1633137,28727827,1633137,29900,'2026-09-30','2026-11-20', 686490.00),
    ('URTS','717','UZ7043200003',11634794983,236119023,655186849,374792100,12800,'2026-09-30','2026-11-20', 341732031.00),
    ('UQEQ','310','UZ7042540003',272964704,12020645,125703243,2404129,75000,'2026-09-30','2026-11-20', 37926448.00),
    ('METQ','733','UZ7035230000',328182245,7348680,73082687,2041300,46000,'2026-09-30','2026-11-20', 18818212.00),
    ('NGQS', '220', 'UZ7042650000', 68735128, 1381950, 26628768, 2763900, 40000.0, '2026-09-30', '2026-11-20', 572969.00),
    ('ORGS', '611', 'UZ7023070004', 6091071, 666680, 4445874, 666680, 15344.0, '2026-09-30', '2026-11-20', -122789.00),
    ('UTYK', '528', 'UZ7051720009', 368765363, 3366271, 259556509, 3366271, 430000.0, '2026-09-30', '2026-11-19', 72466876.00),
    ('UZML', '576', 'UZ7055630006', 1528542.65, 2044500, 1201672.4, 1500000, 36000.0, '2026-09-30', '2026-11-12', -375875.10),
    ('UZPN', '150', 'UZ7005950009', 40248388, 718029, 33317900, 8447400, 20260.82, '2026-09-30', '2026-11-20', 2004655.00),
    ('TMYS', '888', 'UZ7057480012', 336941260.26, 85300000, 137842877.24, 85300000, 1500, '2026-09-30', '2026-11-20', 22900976.18),
    ('BTRL', '540', 'UZ7052610001', 15287949, 4453008, 12482897, 4453008, 10000, '2026-09-30', '2026-11-20', 840680),
    ('CBSK', '633', 'UZ7038380000', 225240792, 87879167, 185183885.97, 87879167190, 4.08, '2026-09-30', '2026-11-20', 33451374),
    ('EQQU', '553', 'UZ7007130006', 514944889, 814485, 135688717, 162897, 313000, '2026-09-30', '2026-10-06', 23388158.38),
    ('TGPG', '650', 'UZ7036730008', 4544259.92, 1362078.73, -644511.21, 541582, 75000, '2026-09-30', '2026-11-20', -7065101.05),
    ('UVGT', '731', 'UZ7051840005', 58029303, 2968227, 6458051, 2968227, 85999, '2026-09-30', '2026-11-20', 903729),
    ('OHDN', '379', 'UZ7023190000', 321754324, 1925938, 72770980, 6419794, 7010, '2026-09-30', '2026-11-20', 2229913),
    ('MXUS', '522', 'UZ7012480008', 14213281, 3148983, 12111110, 6297967, None, '2025-09-30', None, None),
])
def test_september_ordinary_book_value_and_price(report, monkeypatch, ticker, org, isin, assets, capital, equity, shares, close, end, quote_date, profit):
    period = end[:4] + 'Q3'
    report.update(period=period, financial_as_of=end)
    report['issuer'].update(id=org, ticker=ticker)
    report['verified_facts'] = [
        dict(metric_code=key, value=value, period=period, unit_normalized='thousand UZS',
             verification_status='verified')
        for key, value in [('total_assets', assets), ('total_equity', equity), ('net_income', profit)] if value is not None
    ]
    rows = source_rows(report, share_capital=capital, treasury_shares=0)
    inject(monkeypatch, [{**r, 'period_start':end, 'period_end':end} for r in rows])
    report['instrument'] = {'instrument_type':'ordinary_share', 'isin':isin,
                            'ticker':ticker, 'last_price':close, 'market_as_of':quote_date,
                            'valuation_as_of':'2026-11-20', 'freshness':{'status':'fresh'}}
    out = metrics(report)
    book = equity * 1000 / shares
    assert out['book_value_per_share']['value'] == pytest.approx(book)
    assert out['price_to_book']['value'] == (pytest.approx(close / book) if close is not None and book > 0 else None)
    assert out['eps_basic']['value'] is None
    estimate = out.get('eps_closing_estimate', {})
    if end == '2026-09-30':
        assert estimate.get('value') == pytest.approx(profit * 1000 / shares)
        assert estimate['calculation_status'] == 'approximate'
    else:
        assert estimate.get('value') is None


def test_odmp_q3_eps_restates_the_four_for_one_bonus_issue(report, monkeypatch):
    report.update(period='2026Q3', financial_as_of='2026-09-30', scope='separate', standard='nsbu')
    report['issuer'].update(id='538', ticker='ODMP')
    report['verified_facts'] = [
        dict(metric_code=key, value=value, period='2026Q3', unit_normalized='thousand UZS',
             verification_status='verified')
        for key, value in [('total_assets', 15659261.18), ('total_equity', 13088674.11), ('net_income', -288401.40)]
    ]
    rows = source_rows(report, share_capital=3159520, treasury_shares=0)
    inject(monkeypatch, [{**r, 'period_start':'2026-09-30', 'period_end':'2026-09-30'} for r in rows])
    result = metrics(report)
    restated = 1263808 * (1 + 4)
    assert result['eps_basic']['value'] == pytest.approx(-288401400 / restated)
    assert result['book_value_per_share']['value'] == pytest.approx(13088674110 / restated)
    assert 'eps_closing_estimate' not in result


@pytest.mark.parametrize('ticker,org,assets,equity,profit,shares,capital', [
    ('UTYK', '528', 320913944, 222803659, 118876555, 3366271, {'share_capital':3366271, 'treasury_shares':0}),
    ('BTRL', '540', 20968863, 12305816, 1311727, 4453008, {'share_capital': 4453008, 'treasury_shares': 0}),
    ('CBSK', '633', 202075369, 184642814, 41719485, 87879167190, {'share_capital': 87879167, 'treasury_shares': 0}),
    ('TGPG', '650', 8312319.05, 6670433.53, 611457.53, 541582, {'share_capital': 1362078.73, 'treasury_shares': 0}),
    ('UVGT', '731', 43923520, 6013212, 1604155.03, 2968227, {'share_capital': 2968227, 'treasury_shares': 0}),
    ('OHDN', '379', 207936734, 65041662, 4306516, 6419794, {'share_capital':1925938, 'treasury_shares':0}),
    ('TGBK', '815', 7100122903, 1358068453, 54856400, 229800000, {}),
])
def test_annual_eps_uses_the_verified_weighted_ordinary_share_count(report, monkeypatch, ticker, org, assets, equity, profit, shares, capital):
    report.update(period='2025', financial_as_of='2025-12-31', scope='separate', standard='nsbu')
    report['issuer'].update(id=org, ticker=ticker)
    report['verified_facts'] = [
        dict(metric_code=key, value=value, period='2025', unit_normalized='thousand UZS',
             verification_status='verified')
        for key, value in [('total_assets', assets), ('total_equity', equity), ('net_income', profit)]
    ]
    rows = source_rows(report, **capital)
    inject(monkeypatch, [{**r, 'period_start':'2025-12-31', 'period_end':'2025-12-31'} for r in rows])
    annual = metrics(report)
    assert annual['eps_basic']['value'] == pytest.approx(profit * 1000 / shares)
    assert 'eps_closing_estimate' not in annual


@pytest.mark.parametrize('ordinary_capital,preferred_capital,expected', [
    (542157347, 21600, True), (602399453, 21600, False), (542157347, 20000, False),
])
def test_ipky_q3_values_ordinary_shares_after_cancellation(report, monkeypatch, ordinary_capital, preferred_capital, expected):
    end = '2026-09-30'
    report.update(period='2026Q3', financial_as_of=end, scope='separate', standard='nsbu')
    report['issuer'].update(id='28', ticker='IPKY', organization_type='bank')
    report['verified_facts'] = [
        dict(metric_code=key, value=value, period='2026Q3', unit_normalized='thousand UZS',
             verification_status='verified')
        for key, value in [('total_assets', 40078085831), ('total_equity', 4758374715), ('net_income', 821796398)]
    ]
    report['instrument'] = dict(instrument_type='ordinary_share', isin='UZ7039920002', last_price=344,
                                market_as_of='2026-11-20', freshness={'status':'fresh'})
    rows = source_rows(report, share_capital=542178947, ordinary_share_capital=ordinary_capital,
                       preferred_share_capital=preferred_capital)
    inject(monkeypatch, [{**row, 'period_start':end, 'period_end':end} for row in rows])
    result = metrics(report)
    book = (4758374715 * 1000 - 2160000 * 10) / 54215734738
    assert result['book_value_per_share']['value'] == (pytest.approx(book) if expected else None)
    assert result['price_to_book']['value'] == (pytest.approx(344 / book) if expected else None)
    assert result['eps_basic']['value'] is None
    assert result.get('eps_closing_estimate', {}).get('value') is None
    if expected:
        parts = result['book_value_per_share']['components']
        assert {'preferred_equity_claim', 'ordinary_share_capital', 'preferred_share_capital'} <= {
            c.get('metric_id') for c in parts}


@pytest.mark.parametrize('profit,treasury,conflicting_claim,has_book,has_eps', [
    (21848903.1, 0, None, True, True),
    (21848903.1, 1, None, False, False),
    (21848903.1, 0, 82000, False, True),
    (21848900, 0, None, True, False),
])
def test_uzas_fy2024_attributes_equity_and_earnings_by_class(
        report, monkeypatch, profit, treasury, conflicting_claim, has_book, has_eps):
    end = '2024-12-31'
    report.update(period='2024', financial_as_of=end, scope='separate', standard='nsbu')
    report['issuer'].update(id='669', ticker='UZAS', organization_type='insurance')
    report['verified_facts'] = [
        dict(metric_code=key, value=value, period='2024', unit_normalized='thousand UZS', verification_status='verified')
        for key, value in [('total_assets', 540773599.3), ('total_equity', 136024256.5), ('net_income', profit)]
    ]
    values = {'share_capital': 108955938.7, 'treasury_shares': treasury}
    if conflicting_claim is not None:
        values['preferred_equity_claim'] = conflicting_claim
    inject(monkeypatch, [{**r, 'period_start':end, 'period_end':end} for r in source_rows(report, **values)])
    out = metrics(report)
    book = (136024256.5 * 1000 - 20000 * 3280) / 33198274
    eps = (21848903.1 * 1000 - 20000 * 820) / 33198274
    assert out['book_value_per_share']['value'] == (pytest.approx(book) if has_book else None)
    assert out['eps_basic']['value'] == (pytest.approx(eps) if has_eps else None)


@pytest.mark.parametrize('change,valid', [
    ({}, True), ({'ordinary_only_at_end': True}, False),
    ({'preferred_liquidation': {'outstanding_shares':'2160000', 'uzs_per_share':'9'}}, False),
])
def test_ipky_stored_share_count_preserves_or_conflicts_with_reviewed_terms(tmp_path, monkeypatch, change, valid):
    from financial_columns import share_disclosures
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'ipky-class.db'))
    key = ('28', 'IPKY', '2026-09-30', 'separate')
    reviewed = share_disclosures.read(*key)
    stored = {k:v for k,v in reviewed.items()
              if k not in {'verification_status', 'source_version', 'preferred_liquidation'}}
    stored.update(change)
    stored['source_lines']['ordinary_only_at_end'] = 'The attachment identifies only ordinary shares.'
    share_disclosures.record(stored, actor='reviewer', reason='Check class count')
    actual = share_disclosures.read(*key)
    if valid:
        assert actual.get('preferred_liquidation') == reviewed['preferred_liquidation']
    else:
        assert actual is None


@pytest.mark.parametrize('status', ['available','no_source'])
def test_last_verified_book_value_uses_both_inputs_from_same_older_filing(biok_report, monkeypatch, status):
    import issuer_financials
    old = deepcopy(biok_report)
    old['sources'] = [{'publication_date':'2025-01-06','url':old['sources'][0]['url']}]
    import_basis(share_basis())
    monkeypatch.setattr(issuer_financials, 'resolve_issuer', lambda _: old['issuer'])
    monkeypatch.setattr(service, 'sector_report', lambda *args, **kw: deepcopy(old))
    biok_report.update(period='2025', financial_as_of='2025-12-31', status=status)
    biok_report['verified_facts'] = [{**f, 'period':'2025', 'value': f['value'] * 2}
                                     for f in old['verified_facts']]
    result = metrics(biok_report)
    book = result['book_value_per_share']
    assert book['value'] is None
    assert book['last_verified']['period_end'] == '2024-12-31'
    assert book['last_verified']['value'] == pytest.approx(143292694000 / 5713280)
    assert book['last_verified']['share_disclosure_url'] == share_basis()['source_url']
    assert result.get('price_to_book', {}).get('value') is None
    assert result.get('eps_basic', {}).get('value') is None
    eps = result['eps_basic']['last_verified']
    assert eps['value'] == pytest.approx(26037647000 / 5713280)
    assert (eps['period_start'], eps['period_end']) == ('2024-01-01', '2024-12-31')
    pb = result['price_to_book']['last_verified']
    assert pb['value'] == pytest.approx(10000 / book['last_verified']['value'])
    assert pb['market_as_of'] == '2025-01-06'
    biok_report['scope'] = 'consolidated'
    assert not metrics(biok_report).get('book_value_per_share', {}).get('last_verified')
    biok_report.update(scope='separate', period='2023', financial_as_of='2023-12-31')
    assert not metrics(biok_report).get('book_value_per_share', {}).get('last_verified')


@pytest.mark.parametrize('ticker,org,year,profit,shares', [
    ('KVTS','445','2025',1340874.93,96449218), ('ABKZ','78','2023',10157483,5905427)])
def test_parent_profit_uses_audited_weighted_average(report, ticker, org, year, profit, shares):
    from financial_columns import share_disclosures
    from financial_analysis.report_investor_metrics import calculate
    report.update(period=year, financial_as_of=year+'-12-31')
    report['issuer'].update(id=org, ticker=ticker)
    report['verified_facts'] = [dict(metric_code='net_income', value=profit, period=year,
        unit_normalized='thousand UZS', verification_status='verified')]
    basis = share_disclosures.read(org, ticker, report['financial_as_of'], 'separate')
    earnings = next(r for r in calculate(report, [], basis) if r['metric_code'] == 'eps_basic')
    assert earnings['value'] == pytest.approx(profit * 1000 / shares)
    assert earnings['denominator_value'] == shares


def test_biok_2026_ytd_earnings_use_reviewed_share_movements(report):
    from financial_columns import share_disclosures
    from financial_analysis.report_investor_metrics import calculate
    report.update(period='2026Q3', financial_as_of='2026-09-30')
    report['issuer'].update(id='396', ticker='BIOK')
    report['verified_facts'] = [dict(metric_code='net_income', value=12628226, period='2026Q3',
        unit_normalized='thousand UZS', verification_status='verified')]
    basis = share_disclosures.read('396', 'BIOK', '2026-09-30', 'separate')
    earnings = next(r for r in calculate(report, [], basis) if r['metric_code'] == 'eps_basic')
    assert earnings['value'] == pytest.approx(12628226000 / 5713280)
    assert earnings['denominator_value'] == 5713280


def test_abkz_historical_valuation_uses_last_trade_before_next_public_filing(monkeypatch):
    from catalogue import market_store
    from financial_columns import share_disclosures
    from financial_analysis.report_investor_metrics import _historical_instrument
    basis = share_disclosures.read('78', 'ABKZ', '2025-03-31', 'separate')
    assert basis['ordinary_shares'] == '5905427'
    rows = [{'period':'2025Q2','published_at':'2025-07-28T15:12:08'},
            {'period':'2026Q3','published_at':'2026-10-30'}]
    old = {'issuer':{'id':'78','ticker':'ABKZ'}, 'financial_as_of':'2025-03-31',
           'instrument':{'instrument_type':'ordinary_share','ticker':'ABKZ','isin':None},
           'sources':[{'publication_date':'2025-04-29'}]}
    def quote(isin, cap):
        assert isin == 'UZ7047650005'
        assert cap == '2025-07-27'
        return {'isin':isin,'trade_date':'2025-05-20','close_price':6100}
    monkeypatch.setattr(market_store, 'quote_at', quote)
    matched = _historical_instrument(old, basis, rows, '2026-11-22')
    assert (matched['market_as_of'], matched['valuation_as_of'], matched['last_price']) == ('2025-05-20','2025-05-20',6100)
    assert _historical_instrument(old, basis, [{'period':'2025Q1','published_at':'2025-04-29'}],
                                  '2025-07-27')['market_as_of'] == '2025-05-20'
    old['instrument']['isin'] = 'UZ7025770007'
    assert _historical_instrument(old, basis, rows, '2026-11-22').get('last_price') is None


def test_latest_trade_uses_newer_archived_biok_close_and_respects_a_historical_cutoff(monkeypatch):
    from catalogue import market_store
    from datetime import date
    quote = {'isin':'UZ7025870005','trade_date':'20261106','close_price':14450}
    archived = {'isin':quote['isin'],'trade_date':'2026-11-20','close_price':14558.99}
    monkeypatch.setattr(market_store,'quote_at',lambda isin,end: archived if end >= '2026-11-20' else {})
    assert service._report_quote(quote,quote['isin'],date(2026,11,22))['close_price'] == 14558.99
    assert service._report_quote(quote,quote['isin'],date(2026,11,10)) == quote
    assert service._report_quote(quote,quote['isin'],date(2026,10,20)) == {}
    assert service._report_quote({**quote,'trade_date':'20261120','close_price':None},quote['isin'],date(2026,11,20)) == archived


def test_unavailable_optional_history_keeps_current_report(report, monkeypatch):
    from financial_columns import share_disclosures
    def unavailable(*args):
        raise OSError('optional history unavailable')
    monkeypatch.setattr(share_disclosures,'prior_dates',unavailable)
    assert metrics(report)['book_value']['value'] == 6375622697.23


def test_expired_trade_on_latest_balance_is_preserved_as_a_dated_valuation(biok_report,monkeypatch):
    from catalogue import market_store
    from financial_analysis.report_investor_metrics import project
    import_basis(share_basis())
    biok_report['instrument'].update(isin='UZ7025870005',market_as_of='2025-03-12',valuation_as_of='2025-10-01',
                                     freshness={'status':'very_stale'},last_price=10000)
    biok_report['sources']=[{'publication_date':'2025-03-10','url':'https://openinfo.uz/'}]
    monkeypatch.setattr(market_store,'quote_at',lambda isin,day: {'isin':isin,'trade_date':'2025-03-12','close_price':10000})
    item=next(r for r in project(biok_report)['ratios'] if r['metric_code']=='price_to_book')
    assert item['value'] is None
    assert item['last_verified']['value'] == pytest.approx(10000 / (143292694000 / 5713280))
    assert (item['last_verified']['period_end'],item['last_verified']['market_as_of']) == ('2024-12-31','2025-03-12')


def test_kvts_june_charter_and_openinfo_balance(report, monkeypatch):
    report['issuer'].update(id='445', ticker='KVTS', name='Kvarts')
    report['verified_facts'] = [dict(metric_code=k, value=v, period='2026Q2',
        unit_normalized='thousand UZS', verification_status='verified')
        for k,v in [('total_assets',506127021.21), ('total_equity',244032249.94)]]
    inject(monkeypatch, source_rows(report, share_capital=165410409, treasury_shares=0))
    book = metrics(report)['book_value_per_share']
    assert book['value'] == pytest.approx(244032249940 / 96449218)
    assert book['denominator_value'] == 96449218


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


def test_cbsk_q3_withholds_ratios_without_dated_share_counts(tmp_path, monkeypatch):
    from financial_columns import share_disclosures

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'share-disclosures.db'))
    empty = tmp_path / 'no-reviewed-shares.json'
    empty.write_text('[]')
    monkeypatch.setattr(share_disclosures, 'REVIEWED', empty)
    fixtures = Path(__file__).parent / 'fixtures'
    case = json.loads((fixtures / 'cbsk_2026q3_investor_inputs.json').read_text())
    report = case['report']
    documents = json.loads((fixtures / case['source_fixture']).read_text())['CBSK']['documents']
    document = next(d for d in documents if d['period_end'] == report['financial_as_of'])
    monkeypatch.setattr(source_store, 'read', lambda *a, **kw: [deepcopy(document)])

    out = metrics(report)
    assert out['price_to_book']['value'] is None
    assert out['price_to_book']['missing_inputs'] == ['common_equity', 'ordinary_shares']
    assert out['eps_basic']['value'] is None
    assert out['eps_basic']['closing_share_count_verified'] is False
    assert out['eps_basic']['missing_inputs'] == ['profit_ordinary', 'weighted_average_shares']
    assert share_disclosures.read('633', 'CBSK', '2026-06-30', 'separate') is None
    assert share_disclosures.read('633', 'CBSK', '2026-09-30', 'consolidated') is None

    assert share_disclosures.read('633', 'CBSK', '2026-09-30', 'separate') is None


def test_cbsk_openinfo_quarter_has_no_equity_attachment(tmp_path, monkeypatch):
    from collectors.openinfo import transport
    from financial_columns import share_disclosures

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'share-disclosures.db'))
    inspected = []

    def detail(session, path):
        inspected.append(path)
        return {'id': 18989, 'organization': {'id': 633}, 'int_report': None}

    monkeypatch.setattr(transport, '_json_get', detail)
    query = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=jsc&report_id=18989'
    assert not share_disclosures.collect_form5(None, ticker='CBSK', issuer_id='633',
                                              period_end='2026-09-30', excel_url=query)
    assert inspected == ['/reports/jsc/quarter/18989/']


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
    indicators = metrics(report)
    if ticker == 'kvts':
        assert indicators['ebit']['value'] == pytest.approx(50531291.18)
    debt = indicators['interest_debt_to_equity']
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
    return [dict(metric_id=key, raw_label={'profit_before_tax':'Прибыль (убыток) до уплаты налога на прибыль', 'interest_expense':'Расходы в виде процентов'}.get(key,key), value=str(value), unit='UZS_per_share' if key == 'eps_basic' else 'shares' if key in {'ordinary_shares', 'weighted_average_shares'} else 'UZS_thousand',
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
        keys = metrics(report).keys()
        assert not {'operating_margin', 'book_value', 'interest_debt_to_equity', 'ebit'} & keys
        if org in ('bank', 'insurance'):
            assert {'eps_basic', 'price_to_book', 'book_value_per_share'} <= keys


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


@pytest.mark.parametrize('full_period_is_stored', [True, False])
def test_nested_period_rights_conflict_blocks_eps(biok_report, tmp_path, monkeypatch, full_period_is_stored):
    from financial_columns import share_disclosures

    full_period = share_basis()
    short_period = {**full_period, 'period_start': '2024-07-01', 'ordinary_only': False,
                    'source_url': 'https://example.org/test-only-conflicting-rights'}
    stored, reviewed = (full_period, short_period) if full_period_is_stored else (short_period, full_period)
    path = tmp_path / 'reviewed.json'
    path.write_text(json.dumps([reviewed]), encoding='utf-8')
    monkeypatch.setattr(share_disclosures, 'REVIEWED', path)
    import_basis(stored)

    assert share_disclosures.read('396', 'BIOK', '2024-12-31', 'separate') is None
    assert metrics(biok_report)['eps_basic']['value'] is None

    share_disclosures.record(full_period, actor='reviewer', reason='Reconciled nested period rights', replace=True)
    assert metrics(biok_report)['eps_basic']['value'] == pytest.approx(26037647 * 1000 / 5713280)


def test_equivalent_date_formats_cannot_hide_conflicting_averages(biok_report, tmp_path, monkeypatch):
    from financial_columns import share_disclosures

    path = tmp_path / 'reviewed.json'
    reviewed = {**share_basis(), 'period_start': '20240101', 'weighted_average_shares': '5713281'}
    path.write_text(json.dumps([reviewed]), encoding='utf-8')
    monkeypatch.setattr(share_disclosures, 'REVIEWED', path)
    import_basis(share_basis())

    assert share_disclosures.read('396', 'BIOK', '2024-12-31', 'separate') is None
    assert metrics(biok_report)['eps_basic']['value'] is None

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

@pytest.mark.parametrize('variant', [
    'new', 'wrong_issuer', 'corroborates', 'count_conflict', 'rights_conflict', 'different_period_rights',
    'complete_reviewed_basis',
])
def test_openinfo_equity_attachment_is_checked_against_reviewed_basis(tmp_path, monkeypatch, report, variant):
    from catalogue import history
    from collectors.openinfo import transport
    from financial_analysis.report_investor_metrics import calculate
    from financial_columns import share_disclosures

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'share-disclosures.db'))
    source = json.loads(Path('tests/fixtures/openinfo/biok_2026q3_equity.json').read_text(encoding='utf-8'))
    reviewed = share_disclosures.form5_basis(source, ticker='BIOK', issuer_id='396',
                                             tin='200468069', period_end='2026-09-30')
    reviewed['source_url'] = 'https://openinfo.uz/uz/reports/jsc/quarter/18938'
    if variant not in {'new', 'wrong_issuer'}:
        if variant == 'count_conflict':
            reviewed['ordinary_shares'] = '5713281'
        if variant == 'rights_conflict':
            reviewed['ordinary_only_at_end'] = False
        if variant == 'different_period_rights':
            del reviewed['ordinary_only_at_end']
            reviewed['ordinary_only'] = False
        if variant == 'complete_reviewed_basis':
            reviewed.update(weighted_average_shares='5700000', ordinary_only=True)
            reviewed['source_lines'].update(weighted_average_shares='Test-only audited period average',
                                            ordinary_only='Test-only period-wide rights evidence')
    path = tmp_path / 'reviewed.json'
    path.write_text(json.dumps([] if variant in {'new','wrong_issuer'} else [reviewed]), encoding='utf-8')
    monkeypatch.setattr(share_disclosures, 'REVIEWED', path)
    calls = []
    def detail(session, path):
        assert path == '/reports/jsc/quarter/18938/'
        return {'id': 18938, 'organization': {'id': 78 if variant == 'wrong_issuer' else 396},
                'organization_inn': 200468069, 'int_report': source['source_url']}
    def workbook(session, url):
        calls.append(url)
        return source
    monkeypatch.setattr(transport, '_json_get', detail)
    monkeypatch.setattr(history, '_parse_workbook_uncached', workbook)
    query = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=jsc&report_id=18938'
    args = dict(ticker='BIOK', issuer_id='396', period_end='2026-09-30', excel_url=query)
    key = ('396', 'BIOK', '2026-09-30', 'separate')
    if variant == 'complete_reviewed_basis':
        report['issuer'].update(id='396', ticker='BIOK')
        report.update(standard='nsbu', period='2026Q3', financial_as_of=key[2], scope=key[3])
        report['verified_facts'] = [dict(metric_code='net_income', value=12628226, period='2026Q3',
                                         unit_normalized='thousand UZS', verification_status='verified')]

        def eps():
            rows = calculate(report, [], share_disclosures.read(*key))
            return next(row for row in rows if row['metric_code'] == 'eps_basic')

        assert eps()['value'] == pytest.approx(12628226000 / 5700000)
    assert share_disclosures.collect_form5(None, **args) is (
        variant in {'new', 'corroborates', 'different_period_rights', 'complete_reviewed_basis'}
    )
    assert calls == ([] if variant == 'wrong_issuer' else [source['source_url']])
    assert share_disclosures.collect_form5(None, **args) is False
    basis = share_disclosures.read(*key)
    if variant == 'complete_reviewed_basis':
        assert eps()['value'] == pytest.approx(12628226000 / 5700000)
        assert {part['source_url'] for part in eps()['components'] if part.get('unit') == 'shares'} == {
            reviewed['source_url'],
        }
    if variant in {'count_conflict', 'rights_conflict'}:
        assert basis is None
        corrected = share_disclosures.form5_basis(source, ticker='BIOK', issuer_id='396',
                                                   tin='200468069', period_end='2026-09-30')
        share_disclosures.record(corrected, actor='reviewer', reason='Compared the filed share classes', replace=True)
        basis = share_disclosures.read(*key)
        assert basis['source_url'] == source['source_url']
        changed_path = tmp_path / 'updated-reviewed.json'
        changed_path.write_text(json.dumps([{**reviewed, 'ordinary_shares': '5713282'}]), encoding='utf-8')
        monkeypatch.setattr(share_disclosures, 'REVIEWED', changed_path)
        assert share_disclosures.read(*key) is None
    assert (basis or {}).get('ordinary_shares') == (None if variant == 'wrong_issuer' else '5713280')

@pytest.mark.parametrize('pretax,expense,expected', [
    (7603980, -1110029, 8714009), (-200, -50, -150), (-200, 0, -200), (7603980, None, None),
])
def test_abkz_9m_2026_ebit_uses_signed_pretax_and_recognised_interest(report, pretax, expense, expected):
    from financial_analysis.report_investor_metrics import calculate
    report['issuer'].update(id='78', ticker='ABKZ')
    report.update(period='2026Q3', financial_as_of='2026-09-30')
    for f in report['verified_facts']:
        f['period'] = report['period']
    rows = source_rows(report, profit_before_tax=pretax, interest_expense=expense, operating_income=8607795)
    for row in rows:
        row.update(period_end=report['financial_as_of'], source_url='https://openinfo.uz/ru/reports/to_pdf31816/')
        if row['metric_id'] in {'profit_before_tax', 'interest_expense', 'operating_income'}:
            row.update(period_start='2026-01-01', source_form='F2',
                       source_code={'profit_before_tax':'240','interest_expense':'180','operating_income':'100'}[row['metric_id']])
    result = {r['metric_code']: r for r in calculate(report, rows)}
    assert result['ebit']['value'] == expected
    assert {c['source_code'] for c in result['ebit']['components']} == {'240', '180'}


@pytest.mark.parametrize('attribution', ['direct', 'minority', 'missing', 'conflict'])
def test_consolidated_eps_and_book_use_only_parent_common_amounts(report, attribution):
    from financial_analysis.report_investor_metrics import calculate
    report['scope'] = 'consolidated'
    for fact in report['verified_facts']:
        if fact['metric_code'] in {'total_equity', 'net_income'}:
            fact['value'] = {'total_equity':120000000, 'net_income':350000}[fact['metric_code']]
    values = {}
    if attribution in {'direct','conflict'}:
        values.update(equity_owners=100000000, profit_owners=300000)
    if attribution in {'minority','conflict'}:
        values.update(nci=20000000 if attribution=='minority' else 10000000,
                      profit_nci=50000 if attribution=='minority' else 10000)
    rows = source_rows(report, **values)
    for row in rows:
        row['scope'] = report['scope']
        if row['metric_id'] in {'profit_owners','profit_nci'}:
            row['period_start'] = '2026-01-01'
    basis = dict(verification_status='verified', issuer_id=report['issuer']['id'], ticker=report['issuer']['ticker'],
                 scope='consolidated', period_start='2026-01-01', period_end='2026-06-30', ordinary_only=True,
                 ordinary_shares=10000000, weighted_average_shares=1500000)
    report['instrument'] = dict(instrument_type='ordinary_share', market_as_of='2026-08-01', last_price=8000,
                                freshness={'status':'fresh'})
    out = {r['metric_code']:r for r in calculate(report, rows, basis)}
    valid = attribution in {'direct','minority'}
    assert out['eps_basic']['value'] == (200 if valid else None)
    assert out['book_value_per_share']['value'] == (10000 if valid else None)
    assert out['price_to_book']['value'] == (0.8 if valid else None)


def test_reviewed_240_day_share_history_weights_outstanding_shares_and_splits():
    from financial_columns.share_disclosures import _validate
    start, change, end = '2026-01-01', '2026-05-01', '2026-08-28'
    base = dict(issuer_id='1', ticker='TEST', period_start=start, period_end=end, scope='separate',
                source_url='https://example.org/share-register', unit='shares', source_standard='NSBU',
                source_lines={'share_intervals':'Reviewed register and corporate actions, cross-checked to closing count'},
                share_intervals=[{'from':start, 'issued':1100000, 'treasury':100000},
                                 {'from':change, 'issued':2100000, 'treasury':100000}])
    out = _validate(base)
    assert out['weighted_average_shares'] == '1500000'
    assert out['ordinary_shares'] == '2000000'
    split = deepcopy(base)
    split['share_intervals'][1]['restatement_factor'] = 2
    assert _validate(split)['weighted_average_shares'] == '2000000'
    for bad in [[], [base['share_intervals'][1]], [base['share_intervals'][0]] * 2]:
        with pytest.raises(ValueError):
            _validate({**base, 'share_intervals':bad})


def test_nsbu_consolidated_supplement_reads_parent_and_preference_allocations_by_exact_label():
    from financial_columns.nsbu import rows
    source = {'sheets':[{'sheet':'Форма 2','source_rows':[
        {'row':1, 'cells':['Прибыль, приходящаяся на собственников материнской компании', 271, 0, 0, 300000, 0]},
        {'row':2, 'cells':['Права привилегированных акционеров на прибыль за период', 272, 0, 0, 10000, 0]},
        {'row':3, 'cells':['Проценты к получению', 240, 0, 0, 50, 0]}]}]}
    assert [r['metric_id'] for r in rows(source, template='general')] == ['profit_owners','preferred_profit_allocation',None]


def test_legacy_abkz_annual_and_quarterly_do_not_label_operating_profit_ebit():
    from financial_analysis.frames import df_to_annual, df_to_quarterly
    import pandas as pd
    rows = [('Прибыль (убыток) от основной деятельности (стр.0З0-040+090)',8607795),
            ('Прибыль (убыток) до уплаты налога на доходы прибыль) (стр.220+/-230)',7603980),
            ('Расходы в виде процентов',1110029)]
    frame = pd.DataFrame([dict(reporting_year=2026,quarter=3,title=k,value=v) for k,v in rows])
    for convert in (df_to_annual, df_to_quarterly):
        out = convert(frame)[0]
        assert (out['operating_income'],out['ebit']) == (8607795,8714009)
        assert convert(frame.iloc[:2])[0].get('ebit') is None
        assert convert(frame.iloc[1:])[0].get('ebit') == 8714009


def test_quote_basis_split_and_recent_trade_without_using_unpublished_balance(report, monkeypatch):
    from corporate_actions import ShareAction
    import corporate_actions
    inject(monkeypatch, source_rows(report, common_equity=500, ordinary_shares=100))
    monkeypatch.setattr(corporate_actions, 'actions_for', lambda t:[ShareAction('2026-07-15', 2, 'split', 'https://example.org/split')])
    report['instrument'] = dict(instrument_type='ordinary_share', market_as_of='2026-08-01', last_price=2000,
                                valuation_as_of='2026-09-01', freshness={'status':'stale','days_since_trade':31})
    out = metrics(report)
    assert out['price_to_book']['value'] == 0.8
    assert out['book_value_per_share']['value'] == 5000
    report['sources'][0]['publication_date']='2026-09-02'
    assert metrics(report)['price_to_book']['value'] is None


def test_consolidated_income_requires_physical_scoped_source_and_never_borrows_separate_snapshot(report,monkeypatch):
    import issuer_financials as fin
    from financial_columns import source_store
    issuer=dict(id='383',ticker='UZMK',name='Uzmetkombinat',sector='metallurgy',isin='UZ7012040003',index={})
    monkeypatch.setattr(fin,'get_financials_series',lambda *a:{'2025':{'net_income':999,'total_assets':500}})
    monkeypatch.setattr(fin,'get_financials_series_quarterly',lambda *a:{})
    monkeypatch.setattr(fin,'report_rows',lambda *a:[])
    monkeypatch.setattr(fin,'get_all_ratios',lambda:{})
    snapshot=fin.financial_snapshot(issuer,'nsbu','2025','consolidated')
    assert snapshot['current_values'].get('net_income') is None


def test_class_claims_weighted_eps_and_distinct_closing_estimate(report):
    from financial_analysis.report_investor_metrics import calculate
    amounts={'net_income':350000, 'total_equity':120000000}
    for fact in report['verified_facts']:
        if fact['metric_code'] in amounts:
            fact['value']=amounts[fact['metric_code']]
    rows=source_rows(report, preferred_profit_allocation=50000, preferred_equity_claim=20000000,
                     weighted_average_shares=1500000, ordinary_shares=2000000)
    next(r for r in rows if r['metric_id']=='preferred_profit_allocation')['period_start']='2026-01-01'
    result={r['metric_code']:r for r in calculate(report,rows)}
    assert result['eps_basic']['value']==200
    assert result['eps_closing_estimate']['value']==150
    assert result['eps_closing_estimate']['calculation_status']=='approximate'
    assert result['book_value_per_share']['value']==50000


def test_latest_publication_isolated_by_scope_including_rollbacks(report, tmp_path, monkeypatch):
    from reporting import store
    monkeypatch.setenv('SECTOR_ANALYSIS_DB',str(tmp_path/'sectors.db'))
    for scope in ('separate','consolidated'):
        filing={**deepcopy(report), 'scope':scope,'version':scope,'status':'available'}
        store.record_report(filing)
    issuer=report['issuer']['id']
    assert store.latest_publication(issuer,report['language'],'nsbu')['scope']=='separate'
    assert store.latest_publication(issuer,report['language'],'nsbu','consolidated')['scope']=='consolidated'
    assert store.rollback('consolidated','test','verified consolidated report')
    assert store.publication_version({**report,'scope':'separate'})=='separate'


def test_historical_quote_is_only_taken_from_same_issue_on_or_before_publication(monkeypatch, tmp_path):
    from catalogue import market_store
    from catalogue.storage import get_catalog_conn
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'history.db'))
    c=get_catalog_conn()
    with c:
        for isin, day, price in [('UZ7047650005','20250701',8000),('UZ7047650005','2025-07-11',9000),
                                ('UZ7025870005','2025-07-04',7000)]:
            c.execute('INSERT INTO catalog_quote_history(isin,trade_date,close_price,quantity) VALUES(?,?,?,?)',(isin,day,price,1))
    c.close()
    assert market_store.quote_at('UZ7047650005','2025-07-05')['close_price']==8000
    assert market_store.quote_at('UZ7047650005','2025-06-01')=={}


def test_ebit_trace_adds_the_positive_interest_charge(report):
    from financial_analysis.report_investor_metrics import calculate
    rows = source_rows(report, profit_before_tax=-200, interest_expense=-50)
    for row in rows[-2:]:
        row.update(period_start='2026-01-01',source_form='F2',
                   source_code='180' if row['metric_id']=='interest_expense' else '240')
    result = next(r for r in calculate(report,rows) if r['metric_code']=='ebit')
    assert result['denominator_value'] is None
    assert result['addends'] == [-200,50]


def test_nsbu_statement_matrix_calculates_quarterly_and_trailing_ebit_from_comparable_flows(report):
    from financial_columns.derived import enrich
    from financial_columns.periods import calculate
    rows=[]
    for end, pretax, expense in [('2025-09-30',100,-20),('2025-12-31',160,-30),
                                  ('2026-06-30',80,-10),('2026-09-30',140,-15)]:
        for key, code, value in [('profit_before_tax','240',pretax),('interest_expense','180',expense)]:
            rows.append(dict(metric_id=key,value=str(value), quality='valid', issuer_id='78', scope='separate',
                             standard='NSBU', unit='UZS_thousand',currency='UZS', period_start=end[:4]+'-01-01',
                             period_end=end,kind='flow',source_version=end,source_form='F2',source_code=code,
                             role='PRIMARY',raw_label='Прибыль до уплаты налога' if code=='240' else 'Расходы в виде процентов'))
    financials=[r for r in enrich(rows,template='industry') if r['metric_id']=='ebit']
    assert calculate(financials,'2026-09-30','quarter')['value']=='65'
    assert calculate(financials,'2026-09-30','ttm')['value']=='225'
    assert not any(r['metric_id']=='ebit' for r in enrich(rows,template='leasing'))


def test_ebit_rechecks_label_and_source_code_on_previously_imported_cells(report):
    from financial_analysis.report_investor_metrics import calculate
    rows=source_rows(report,profit_before_tax=200,interest_expense=-50)
    for row,code,label in zip(rows[-2:],('240','180'),('Доход от инвестиций','Расходы в виде процентов')):
        row.update(source_form='F2',source_code=code,raw_label=label,period_start='2026-01-01')
    assert next(r for r in calculate(report,rows) if r['metric_code']=='ebit')['value'] is None


@pytest.mark.parametrize('liabilities,expected', [(1645196, 2.3009059456), (1645000, None)])
def test_orgs_equity_valuation_survives_only_an_unrelated_asset_subtotal(report, monkeypatch, liabilities, expected):
    # Openinfo quarterly JSC 19145, Form 1 lines 130, 390, 400, 410, 440, 480, 770 and 780.
    end = '2026-09-30'
    report.update(period='2026Q3', financial_as_of=end)
    report['issuer'].update(id='611', ticker='ORGS')
    report['verified_facts'] = [dict(metric_code=k, value=v, period='2026Q3', unit_normalized='thousand UZS',
                                     verification_status='verified') for k, v in
                                [('total_assets', 6091071), ('total_equity', 4445874), ('total_liabilities', 1645196)]]
    rows = source_rows(report, share_capital=666680, treasury_shares=0, noncurrent_assets=3053240,
                       current_assets=2880124, total_liabilities=liabilities, total_equity_liabilities=6091071)
    for row in rows:
        row.update(source_form='F1', period_start=end, period_end=end)
    inject(monkeypatch, rows)
    report['instrument'] = {'instrument_type':'ordinary_share', 'isin':'UZ7023070004', 'ticker':'ORGS',
                            'last_price':15344, 'market_as_of':'2026-11-20', 'valuation_as_of':'2026-11-20',
                            'freshness':{'status':'fresh'}}
    result = metrics(report)
    assert result['price_to_book']['value'] == (pytest.approx(expected) if expected else None)
    assert result['book_value_per_share']['value'] == (pytest.approx(6668.6776264) if expected else None)
