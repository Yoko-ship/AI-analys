"""Current-period ratios: HMKB's reported 9M 2026 case and basis guards."""
import csv
import io
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from financial_columns import ratios


@pytest.fixture
def abkz_rows():
    from financial_columns.observations import nsbu
    filings = Path('tests/fixtures/financial_columns/abkz_roce.json')
    return nsbu(json.loads(filings.read_text(encoding='utf-8')))


@pytest.mark.parametrize(('end', 'basis', 'expected'), [
    ('2026-09-30', 'ytd', '9.19'),
    ('2025-12-31', 'annual', '14.43'),
    ('2026-09-30', 'ttm', '11.36'),
    ('2025-12-31', 'ttm', '14.43'),
])
def test_abkz_roce_uses_reported_operating_profit_and_mean_capital(abkz_rows, end, basis, expected):
    result = ratios.calculate(abkz_rows, ticker='ABKZ', template='industry', end=end, basis=basis)
    cell = next(r for r in result if r['metric_id'] == 'roce')
    assert cell['value'] is not None
    assert Decimal(cell['value']).quantize(Decimal('.01')) == Decimal(expected)
    assert cell['annualized'] is False and cell['unit'] == 'percent'
    assert cell['basis'] == basis and cell['balance_basis'] == 'average_opening_closing'
    assert len(cell['components']) == 3
    assert all(part['source_url'] for cap in cell['components'][1:] for part in cap['components'])
    roic = next(r for r in result if r['metric_id'] == 'roic')
    assert roic['value'] is None and roic['reason'] == 'NOPAT_OR_INVESTED_CAPITAL_POLICY_MISSING'


@pytest.mark.parametrize(('opening_assets', 'operating_profit', 'template', 'value', 'reason'), [
    ('31454274', '100', 'industry', None, 'NON_POSITIVE_CAPITAL_EMPLOYED'),
    ('1', '100', 'industry', None, 'NON_POSITIVE_CAPITAL_EMPLOYED'),
    ('122461662', '-8607795', 'industry', '-9.19', None),
    ('122461662', '0', 'industry', '0.00', None),
    ('122461662', '100', 'bank', None, 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'),
    ('122461662', '100', 'insurance', None, 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'),
])
def test_roce_requires_applicable_sector_and_two_positive_capital_balances(
        abkz_rows, opening_assets, operating_profit, template, value, reason):
    for row in abkz_rows:
        if row['metric_id'] == 'total_assets' and row['period_end'] == '2025-12-31':
            row['value'] = opening_assets
        if row['metric_id'] == 'operating_income' and row['period_end'] == '2026-09-30':
            row['value'] = operating_profit
    result = ratios.calculate(abkz_rows, ticker='ABKZ', template=template, end='2026-09-30', basis='ytd')
    cell = next(r for r in result if r['metric_id'] == 'roce')
    assert cell['reason'] == reason
    assert (None if cell['value'] is None else str(Decimal(cell['value']).quantize(Decimal('.01')))) == value


def test_abkz_filing_ratios_and_csv_include_both_ytd_and_trailing_year(abkz_rows, monkeypatch, tmp_path):
    from financial_columns import service, exports
    from catalogue.storage import get_catalog_conn
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    conn = get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('ABKZ','ABKZ','78')")
    conn.close()
    monkeypatch.setattr(service.source_store, 'read', lambda *args, **kw: [])
    monkeypatch.setattr(service.observations, 'nsbu', lambda docs: deepcopy(abkz_rows))
    payload = service.load('ABKZ', view='template', include_sources=False)
    row = next(r for r in payload['ratios'] if r['metric_id'] == 'roce')
    full = list(exports.records(payload))
    for key, expected in [('2025', '14.43'), ('2026-09-30', '9.19'), ('ttm:2026-09-30', '11.36')]:
        cell = row['cells'][key]
        assert Decimal(cell['value']).quantize(Decimal('.01')) == Decimal(expected)
        exported = next(r for r in full if r['metric_id'] == 'roce' and r['basis'] == cell['basis']
                        and r['period_end'] == cell['period_end'])
        assert exported['value'] == cell['value'] and exported['formula'] == cell['formula']


def test_kscm_roce_uses_the_filed_operating_line_and_discloses_reconciliation():
    from financial_columns import capital_returns, observations
    path = Path('tests/fixtures/financial_columns/kscm_roce.json')
    rows = observations.nsbu([json.loads(path.read_text(encoding='utf-8'))])
    observations.check(rows)
    end = '2026-09-30'
    reported = next(r for r in rows if r['metric_id'] == 'operating_income' and r['period_end'] == end)
    assert reported['reason'] == 'SOURCE_OPERATING_PROFIT_MISMATCH'
    cell = capital_returns.roce(rows, template='industry', end=end, basis='ytd')
    assert cell['quality'] == 'warn'
    assert Decimal(cell['value']).quantize(Decimal('.01')) == Decimal('1.73')
    assert cell['components'][0]['reconciliation_issues'] == reported['reconciliation_issues']
    assert reported['quality'] == 'blocked'
    reported.update(quality='blocked', reason='UNDER_REVIEW')
    assert capital_returns.roce(rows, template='industry', end=end, basis='ytd')['value'] is None


def test_filing_screener_can_show_roce_from_the_filing_without_an_analysis_card(monkeypatch):
    from server.terminal import service
    from financial_columns import source_store
    import issuer_financials
    docs = json.loads(Path('tests/fixtures/financial_columns/abkz_roce.json').read_text(encoding='utf8'))
    company = {'ticker': 'ABKZ', 'tickers': ['ABKZ'], 'name': 'ABKZ', 'org_id': '78'}
    monkeypatch.setattr(service, 'universe', lambda *, all_filings: [company] if all_filings else [])
    monkeypatch.setattr(source_store, 'read', lambda issuer_id, **kw: [docs[-1]] if kw['scope'] == 'separate' else [])
    monkeypatch.setattr('financial_columns.service.organization_kind', lambda *a, **kw: 'industry')
    monkeypatch.setattr('data_quality.held_public_periods', lambda *args: set())
    def unavailable(identifier):
        raise LookupError('analysis card unavailable')
    monkeypatch.setattr(issuer_financials, 'resolve_issuer', unavailable)
    row = service.filing_metrics('separate', None, 'ABKZ', 0, 1)['rows'][0]
    assert row['period'] == '2026Q3' and row['metrics']['roce']['value'] == pytest.approx(9.19, abs=.005)
    group = service.filing_metrics('consolidated', '2026Q3', 'ABKZ', 0, 1)['rows'][0]
    assert group['metrics']['roce']['value'] is None


def test_agmkp_latest_filed_annual_stays_visible_beyond_newer_comparative_balances():
    from financial_columns.matrix import build
    def row(end, kind, role='PRIMARY'):
        return {'metric_id': 'operating_income' if kind == 'flow' else 'total_assets', 'period_end': end,
                'period_start': end[:4] + '-01-01' if kind == 'flow' else end, 'kind': kind,
                'raw_label': kind, 'source_form': 'F2' if kind == 'flow' else 'F1', 'role': role,
                'quality': 'valid', 'value': '1'}
    rows = [row('2023-12-31', 'flow'), row('2024-12-31', 'stock', 'COMPARATIVE'),
            row('2025-12-31', 'stock', 'COMPARATIVE'), row('2026-09-30','flow')]
    table = build(rows, mode='annual', recent=True, recent_ttm=True)
    assert [c['key'] for c in table['columns']] == ['2023','2026-09-30','ttm:2026-09-30']


def test_tgmq_missing_comparable_filing_takes_precedence_for_ttm():
    from financial_columns.capital_returns import LINES, roce
    # OpenInfo quarterly filing 19198 for issuer 737.
    current = []
    for metric, value in [('total_assets', '159716360'), ('current_liabilities', '186769961'),
                          ('operating_income', '-12510376')]:
        form, code = LINES[metric]
        current.append({'metric_id': metric, 'value': value, 'raw_label': metric, 'quality': 'valid',
                        'source_form': form, 'source_code': code, 'unit': 'UZS_thousand', 'standard': 'NSBU',
                        'kind': 'flow' if form == 'F2' else 'stock', 'period_end': '2026-09-30',
                        'period_start': '2026-01-01' if form == 'F2' else '2026-09-30'})
    cell = roce(current, template='industry', end='2026-09-30', basis='ttm')
    assert cell['value'] is None and cell['reason'] == 'ROCE_INPUTS_MISSING'


def test_acmt_latest_ratio_period_uses_filed_date_even_before_cells_are_imported(monkeypatch, tmp_path):
    from catalogue import filings
    from catalogue.storage import get_catalog_conn
    from financial_columns import service
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    conn = get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('ACMT1B2','AGAT CREDIT mikromoliya','1058')")
    conn.close()
    quarterly = {'report_form':'NSBU', 'year':2026, 'quarter':3, 'period_type':'quarter',
                 'excel_url':'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=microfinance&report_id=66&lang=ru'}
    monkeypatch.setattr(filings, 'get_company_reports', lambda ticker: [quarterly])
    monkeypatch.setattr(service.source_store, 'read', lambda *args, **kw: [])
    company = {'ticker':'ACMT1B2', 'name':'AGAT CREDIT mikromoliya', 'org_id':'1058'}
    period, item = service.filing_roce(company, None, 'separate')
    assert period == '2026Q3' and item['reason_code'] == 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'
    table = service.load(company['ticker'], view='template', include_sources=False)
    roce = next(r for r in table['ratios'] if r['metric_id'] == 'roce')['cells']['2026-09-30']
    assert roce['value'] is None and roce['reason'] == item['reason_code']
    assert service.filing_roce(company, None, 'consolidated')[0] is None


@pytest.fixture
def hmkb_rows():
    # Captured source cells include the exact filing, row and original amount.
    payload=json.loads(Path('e2e/fixtures/hmkb-recent-reports.json').read_text())
    return [{'standard':payload['standard'],'scope':payload['scope'],
             'issuer_id':payload['issuer_id'],'unit':row.get('unit',payload['unit']),**cell}
            for row in payload['rows'] for cell in row['cells'].values()]


def calculate(rows, end='2026-09-30', basis='ytd', template='bank'):
    return {r['metric_id']:r for r in ratios.calculate(
        rows,ticker='HMKB',template=template,end=end,basis=basis)}


def test_hmkb_9m_current_ratios_use_year_opening_balances_and_reported_ytd(hmkb_rows):
    original=deepcopy(hmkb_rows)
    result=calculate(hmkb_rows)
    for metric,expected in {'roe':26.5133295211,'roa':4.9162481672,
                            'cir':1819867178/4249412165*100}.items():
        cell=result[metric]
        assert cell['quality']=='valid'
        assert float(cell['value'])==pytest.approx(expected)
        assert cell['period_start']=='2026-01-01'
        assert cell['period_end']=='2026-09-30'
        assert cell['basis']=='ytd'
        assert cell['annualized']==(metric!='cir')
        assert ('× 12 / 9' in cell['formula'])==(metric!='cir')
    assert [p['period_end'] for p in result['roe']['components']]==[
        '2026-09-30','2025-12-31','2026-09-30']
    assert result['roe']['components'][0]['raw_value']==1480422343
    assert 'report_id=1306' in result['roe']['components'][0]['source_url']
    # A published loan-loss charge is not a verified loan-only cost of risk;
    # total assets cannot stand in for the missing earning-assets base.
    assert result['nim']['value'] is None
    assert result['nim']['reason']=='AVERAGE_EARNING_ASSETS_MISSING'
    assert result['cost_of_risk']['value'] is None
    assert result['cost_of_risk']['reason']=='INPUTS_MISSING'
    assert hmkb_rows==original


def test_rv_uses_verified_earning_assets_and_loan_only_costs(hmkb_rows, monkeypatch):
    from server.terminal import bank_ratios

    # Model a filing with the additional lines the real HMKB fixture lacks.
    for metric, kind, when, value in [
        ('earning_assets', 'stock', '2025-12-31', 28_000_000_000),
        ('earning_assets', 'stock', '2026-09-30', 33_000_000_000),
        ('loan_credit_loss_cost', 'flow', '2026-09-30', 150_000_000),
    ]:
        anchor = next(row for row in hmkb_rows if row['metric_id'] == 'total_equity' and row['period_end'] == when)
        hmkb_rows.append({**anchor, 'kind': kind, 'metric_id': metric, 'value': str(value),
                          'period_start': when if kind == 'stock' else '2026-01-01'})
    monkeypatch.setattr('financial_columns.source_store.read', lambda *args, **kwargs: [])
    monkeypatch.setattr('financial_columns.observations.nsbu', lambda docs: deepcopy(hmkb_rows))
    row = {'standard': 'NSBU', 'scope': 'separate', 'nim': None, 'cost_of_risk': None}
    bank_ratios.enrich_interim({'ticker': 'HMKB'}, row, [], set(), '2026-09-30')
    assert row['nim'] == pytest.approx(2_323_944_970 / 30_500_000_000 * 100 * 12 / 9)
    assert row['cost_of_risk'] == pytest.approx(150_000_000 / ((23_274_799_997 + 30_361_825_389) / 2) * 100 * 12 / 9)
    row.update(nim=None, cost_of_risk=None)
    bank_ratios.enrich_interim({'ticker': 'HMKB'}, row, [], {'2025'}, '2026-09-30')
    assert row['nim'] is None and row['cost_of_risk'] is None


@pytest.mark.parametrize('end,months',[('2026-03-31',3),('2026-06-30',6),('2026-09-30',9)])
def test_ytd_rate_annualization_depends_on_elapsed_months_only(hmkb_rows,end,months):
    # Synthetic period variants isolate the annualization policy.
    for row in hmkb_rows:
        if row['period_end']=='2026-09-30':
            row['period_end']=end
            if row['kind']=='stock':row['period_start']=end
    result=calculate(hmkb_rows,end=end)
    assert float(result['roe']['value'])==pytest.approx(
        1480422343/((6704709904+8185132247)/2)*100*12/months)
    assert f'× 12 / {months}' in result['roe']['formula']
    assert float(result['cir']['value'])==pytest.approx(1819867178/4249412165*100)
    assert not result['cir']['annualized']
    debt=result['liabilities_to_assets']
    assert float(debt['value'])==pytest.approx(36204146303/44389278550)
    assert not debt['annualized']
    assert debt['period_start']==end


@pytest.mark.parametrize('problem',['missing_opening','incompatible_scope','blocked_profit'])
def test_ytd_does_not_bypass_required_inputs_or_quality(hmkb_rows,problem):
    if problem=='missing_opening':
        hmkb_rows=[r for r in hmkb_rows if not (
            r['metric_id']=='total_equity' and r['period_end']=='2025-12-31')]
    else:
        profit=next(r for r in hmkb_rows if r['metric_id']=='net_income' and r['period_end']=='2026-09-30')
        profit.update({'scope':'consolidated'} if problem=='incompatible_scope' else {'quality':'blocked'})
    cell=calculate(hmkb_rows)['roe']
    assert cell['value'] is None
    assert cell['quality']==('missing' if problem=='missing_opening' else 'blocked')


def test_asof_stays_stock_only_and_quarter_cir_is_not_annualized(hmkb_rows):
    assert calculate(hmkb_rows,basis='as_of')['roe']['quality']=='not_applicable'
    # Explicit standalone flows, distinct from the captured YTD statements.
    for row in hmkb_rows:
        if row['period_end']=='2026-09-30' and row['kind']=='flow':
            row['period_start']='2026-07-01'
    cir=calculate(hmkb_rows,basis='quarter')['cir']
    assert float(cir['value'])==pytest.approx(1819867178/4249412165*100)
    assert cir['annualized'] is False


@pytest.mark.parametrize('freq',['annual','interim'])
def test_current_hmkb_ratios_reach_api_and_exports(hmkb_rows,monkeypatch,tmp_path,freq):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.company.financial_routes import router
    from catalogue.storage import get_catalog_conn
    from financial_columns import service
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'catalog.db'))
    c=get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('HMKB','Hamkorbank','8')")
    c.close()
    monkeypatch.setattr(service.source_store,'read',lambda *a,**kw:[])
    monkeypatch.setattr(service.observations,'nsbu',lambda docs:deepcopy(hmkb_rows))
    app=FastAPI()
    app.include_router(router)
    query=f'view=template&freq={freq}'
    with TestClient(app) as client:
        response=client.get(f'/api/company/HMKB/financials/columns?{query}')
        exported=client.get(f'/api/company/HMKB/financials/columns.csv?{query}')
    assert response.status_code==exported.status_code==200
    assert 'no-store' in exported.headers.get('cache-control', '')
    payload=response.json()
    roe=next(r for r in payload['ratios'] if r['metric_id']=='roe')['cells']['2026-09-30']
    assert Decimal(roe['value']).quantize(Decimal('.01'))==Decimal('26.51')
    records=list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    exported_roe=next(r for r in records if r['metric_id']=='roe' and r['period_end']=='2026-09-30')
    assert exported_roe['value']==roe['value']
    assert exported_roe['period_start']=='2026-01-01'
    assert '× 12 / 9' in exported_roe['formula']
