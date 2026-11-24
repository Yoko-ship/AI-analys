"""Investor UI contract, including actual approved Hamkorbank source cells."""
import json
from pathlib import Path
import pytest


def test_reference_fields_map_exact_source_totals_not_narrower_subtotals():
    from financial_columns.ifrs import metric
    from financial_columns.investor import enrich
    for form,label,expected in [
        ('BS','Intangible assets and goodwill','intangibles_goodwill'),
        ('BS','Trade and other receivables','trade_other_receivables'),
        ('PL','Staff costs','staff_costs'),
        ('PL','Investment income','investment_income'),
        ('CF','Other investing cash flows','other_investing_cash_flows'),
        ('Equity','Equity at beginning of period','equity_open'),
    ]:
        assert metric(label,form)==expected
        old=dict(standard='MSFO',source_form=form,raw_label=label,metric_id=None)
        assert enrich([old])[0]['metric_id']==expected
    assert metric('Trade receivables','BS')=='trade_receivables'
    assert metric('Intangible assets','BS')=='intangibles'
    assert metric('Staff costs forecast','PL') is None


def test_cash_and_equity_opening_balances_follow_statement_start_not_column_end(hmkb):
    from financial_columns.investor import project
    rows=[]
    for metric,form in [('cash_begin','CF'),('equity_open','Equity')]:
        for start,end,value in [('2024-12-31','2025-12-31','150'),('2025-12-31','2026-12-31','200')]:
            rows.append(dict(metric_id=metric,source_form=form,kind='stock',raw_label=metric,
                             period_end=start,statement_period_end=end,value=value,quality='valid'))
    result=project(hmkb,rows)
    for statement,field in [('cf','cashStart'),('equity','equityOpen')]:
        row=next(r for g in result['statements'][statement] for r in g['rows'] if r['field']==field)
        assert row['cells']['2025']['value']=='150'
    quarterly={**hmkb,'columns':[{'key':'q4','end':'2025-12-31','basis':'quarter','label':'2025 Q4'}], 'rows':[]}
    result=project(quarterly,rows)
    row=next(r for g in result['statements']['cf'] for r in g['rows'] if r['field']=='cashStart')
    assert row['cells']['q4']['value'] is None


def test_ebitda_requires_positive_addback_not_a_signed_expense():
    from financial_columns.investor import enrich
    base=dict(standard='MSFO',issuer_id='factory',scope='separate',source_version='v1',
              period_start='2025-01-01',period_end='2025-12-31',kind='flow',unit='UZS_thousand',quality='valid')
    rows=[dict(base,metric_id='operating_income',raw_label='Operating profit',value='100'),
          dict(base,metric_id='depreciation_amortization',raw_label='Depreciation',value='-20')]
    assert not any(r['metric_id']=='ebitda' for r in enrich(rows))
    rows[1]['value']='20'
    assert next(r for r in enrich(rows) if r['metric_id']=='ebitda')['value']=='120'


def test_audited_fund_keeps_first_reporting_period_and_scope():
    from financial_columns.investor_sources import audited_fund
    from financial_columns.matrix import build
    rows=audited_fund('UZNF','1059','separate')
    assert rows
    profit=next(r for r in rows if r['metric_id']=='net_income')
    assert profit['period_start']=='2024-12-24'
    assert profit['source_url'].startswith('https://openinfo.uz/')
    table=build(rows,mode='annual',recent=True)
    assert table['columns'][0]['label']=='24.12.2024–31.12.2025'
    assert next(r for r in table['rows'] if r['metric_id']=='net_income')['cells']['2025']['value']==profit['value']
    assert audited_fund('UZNF','1059','consolidated')==[]
    assert audited_fund('UNKNOWN','1059','separate')==[]


@pytest.fixture
def hmkb():
    return json.loads(Path('tests/fixtures/financial_columns/hmkb_ifrs_investor.json').read_text(encoding='utf-8'))


def test_investor_projects_real_bank_statements_without_demo_values(hmkb):
    from financial_columns.investor import project
    result = project(hmkb)
    assert result['presentation'] == 'investor'
    assert set(result['statements']) == {'pl', 'bs', 'cf', 'equity'}
    assert result['statements']['pl'][0]['label'] == 'Процентная деятельность'
    assets = next(r for g in result['statements']['bs'] for r in g['rows'] if r['field'] == 'assets')
    source = next(r for r in hmkb['rows'] if r['metric_id'] == 'total_assets')
    assert assets['cells'] == source['cells']
    assert assets['unit'] == 'UZS_thousand'
    assert all(r['statement'] == 'bs' for g in result['statements']['bs'] for r in g['rows'])
    assert all(r['statement'] == 'pl' for g in result['statements']['pl'] for r in g['rows'])


@pytest.mark.parametrize('sector', ['bank','insurance','leasing','general','telecom','fund'])
def test_each_sector_keeps_reference_structure_when_sources_are_missing(hmkb, sector):
    from financial_columns.investor import project
    result = project({**hmkb, 'template':sector, 'issuer_name':'Example', 'rows':[], 'ratios':[]})
    assert all(result['statements'][key] for key in ['pl','bs','cf','equity'])
    assert all(c['value'] is None for groups in result['statements'].values()
               for group in groups for row in group['rows'] for c in row['cells'].values())


def test_investor_rejects_nsbu_and_never_uses_assets_as_equity_plus_liabilities(hmkb):
    from financial_columns.investor import project
    with pytest.raises(ValueError):
        project({**hmkb,'standard':'NSBU'})
    hmkb['rows'] = [r for r in hmkb['rows'] if r['metric_id'] == 'total_assets']
    result = project(hmkb)
    total = next(r for g in result['statements']['bs'] for r in g['rows'] if r['field']=='equityLiabilities')
    assert all(c['value'] is None for c in total['cells'].values())


def test_conflicting_metric_sources_stay_blocked_instead_of_picking_one(hmkb):
    from copy import deepcopy
    from financial_columns.investor import project
    original = next(r for r in hmkb['rows'] if r['metric_id']=='total_assets')
    other=deepcopy(original)
    other['id']='BS:conflicting-assets'
    column=next(k for k,c in other['cells'].items() if c.get('value') is not None)
    other['cells'][column]['value']='1'
    result=project({**hmkb,'rows':[original,other]})
    assets=next(r for g in result['statements']['bs'] for r in g['rows'] if r['field']=='assets')
    assert assets['cells'][column]['quality']=='blocked'
    assert assets['cells'][column]['value'] is None


def test_investor_api_preserves_scope_and_adds_ttm_only_for_flow_periods(monkeypatch, tmp_path):
    from financial_columns import service
    from financial_columns.investor import project
    from catalogue.storage import get_catalog_conn
    monkeypatch.setenv('CATALOG_DB_PATH',str(tmp_path/'catalog.db'))
    conn=get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('TEST','Factory','123')")
    conn.close()
    rows=[]
    for end, amount in [('2024-06-30','40'),('2024-12-31','100'),('2025-06-30','60')]:
        for metric,kind,value in [('revenue','flow',amount),('total_assets','stock','1000')]:
            rows.append(dict(metric_id=metric,source_form='PL' if kind=='flow' else 'BS',source_code=None,
                             kind=kind,unit='UZS_thousand',value=value,quality='valid',raw_label=metric,
                             period_start=end[:4]+'-01-01' if kind=='flow' else end,period_end=end,
                             issuer_id='123',standard='MSFO',scope='consolidated',currency='UZS',
                             source_version='reviewed',source_url='https://example.com/report.pdf'))
    monkeypatch.setattr(service.publication,'scopes',lambda ticker:['consolidated'])
    monkeypatch.setattr(service.publication,'snapshots',lambda ticker,scope:[])
    monkeypatch.setattr(service.observations,'ifrs',lambda snapshots, **options:rows)
    result=service.load('TEST',form='MSFO',scope='consolidated',freq='interim',view='investor')
    assert result['presentation']=='investor' and result['scope']=='consolidated'
    ttm=next(c for c in result['columns'] if c['basis']=='ttm')
    income=next(r for g in result['statements']['pl'] for r in g['rows'] if r['field']=='revenue')
    assert income['cells'][ttm['key']]['value']=='120'
    assets=next(r for g in result['statements']['bs'] for r in g['rows'] if r['field']=='assets')
    assert assets['cells'][ttm['key']]['value'] is None
    assert assets['cells'][ttm['key']]['quality']=='not_applicable'


def test_real_hmkb_net_interest_keeps_signed_source_inputs(hmkb):
    from financial_columns.investor import enrich
    observations=[{**row,**cell,'raw_label':row['label']} for row in hmkb['rows']
                  for cell in row['cells'].values() if cell.get('period_end')=='2025-12-31']
    result=enrich(observations)
    interest=next(r for r in result if r['metric_id']=='net_interest_before_ecl')
    assert interest['value']=='2626986000'
    assert [p['metric_id'] for p in interest['components']]==['interest_income','interest_expense']
    assert interest['source_version']==interest['components'][0]['source_version']
    # Incomplete inputs cannot manufacture a zero or a partial net result.
    assert not any(r['metric_id']=='net_interest_before_ecl' for r in enrich(
        [r for r in observations if r['metric_id']!='interest_expense']))


def test_positive_expense_is_not_assumed_signed_and_conflicting_contexts_do_not_mix(hmkb):
    from financial_columns.investor import enrich
    rows=[{**row,**cell,'raw_label':row['label']} for row in hmkb['rows']
          for cell in row['cells'].values() if cell.get('period_end')=='2025-12-31']
    for row in rows:
        if row['metric_id']=='interest_expense':
            row['value']='100'
    assert not any(r['metric_id']=='net_interest_before_ecl' for r in enrich(rows))

    for row in rows:
        if row['metric_id']=='interest_expense':
            row.update(value='-100',scope='separate')
    assert not any(r['metric_id']=='net_interest_before_ecl' for r in enrich(rows))


def test_investor_ratio_sets_are_sector_specific_and_missing_is_not_zero():
    from financial_columns.investor_ratios import calculate
    columns=[{'key':'2025','label':'2025','end':'2025-12-31','basis':'annual'}]
    def row(metric,value,kind='flow',end='2025-12-31'):
        return dict(metric_id=metric,value=str(value),quality='valid',kind=kind,period_end=end,
                    period_start=end if kind=='stock' else end[:4]+'-01-01',standard='MSFO',
                    scope='consolidated',issuer_id='test',unit='UZS_thousand',raw_label=metric)
    source=[row('revenue',100),row('operating_income',20),row('total_assets',1000,'stock'),
            row('total_equity',300,'stock'),row('gross_profit',40),row('net_income',10)]
    ratios=calculate(source,[],columns,'general')
    keyed={r['metric_id']:r['cells']['2025'] for r in ratios}
    assert keyed['operating_margin']['value']=='20.0'
    assert keyed['gross_margin']['value']=='40.0'
    assert keyed['equity_to_assets']['value']=='30.0'
    assert keyed['net_debt_to_ebitda']['value'] is None
    assert 'nim' not in keyed and 'loans_to_deposits' not in keyed
    bank={r['metric_id'] for r in calculate(source,[],columns,'bank')}
    assert {'roe','roa','nim','cir','cost_of_risk','loans_to_deposits','ecl_coverage'}<=bank
    assert 'gross_margin' not in bank
    # Duplicate values from different scopes cannot be combined in one ratio.
    source[-1]['scope']='separate'
    source[0]['scope']='separate'
    conflict={r['metric_id']:r['cells']['2025'] for r in calculate(source,[],columns,'general')}
    assert conflict['operating_margin']['value'] is None


def test_partial_import_preserves_unrelated_audited_fund_metrics(monkeypatch, tmp_path):
    from financial_columns import service
    from financial_columns.investor_sources import audited_fund

    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    with service.get_catalog_conn() as db:
        db.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)",
                   ('UZNF', 'National Investment Fund of the Republic of Uzbekistan', '1059'))
    cash = next(r for r in audited_fund('UZNF', '1059', 'separate') if r['metric_id'] == 'cash')
    imported = dict(cash, source_version='reviewed-import', source_code=None)
    opening = dict(cash, metric_id='cash_begin', source_form='CF', source_code=None,
                   statement_period_end='2026-06-30', source_version='interim-opening')
    monkeypatch.setattr(service.publication, 'snapshots', lambda *args, **kwargs: [])
    monkeypatch.setattr(service.publication, 'scopes', lambda ticker: ['separate'])
    audited_profit = next(r for r in audited_fund('UZNF', '1059', 'separate') if r['metric_id'] == 'net_income')
    interim_profit = dict(audited_profit, period_start='2026-01-01', period_end='2026-09-30',
                          value='1936551000', raw_label='Profit for the period', source_code=None,
                          source_version='interim-profit', reported_annual=False)
    monkeypatch.setattr(service.observations, 'ifrs', lambda *args, **kwargs: [opening, imported, interim_profit])
    result = service.load('UZNF', form='MSFO', view='investor', scope='separate', include_ratios=False)
    annual = next(c for c in result['columns'] if c['basis'] == 'annual')
    assert annual['label'] == '24.12.2024–31.12.2025'
    relevant = {r['metric_id']: r['cells']['2025'] for r in result['rows']
                if r['metric_id'] in {'net_income', 'cash'}}
    assert relevant['net_income']['value'] == '1403150000'
    assert relevant['net_income']['page'] == 8
    assert relevant['cash']['source_version'] == 'reviewed-import'
    assert sum(r['metric_id'] == 'cash' for r in result['rows']) == 1
    profit = next(r for group in result['statements']['pl'] for r in group['rows'] if r['field'] == 'profit')
    assert profit['cells']['2025']['value'] == '1403150000'
    assert profit['cells']['2025']['page'] == 8
    assert profit['cells']['2026-09-30']['value'] == '1936551000'

    for view in ('full', 'template', 'overview'):
        report = service.load('UZNF', form='MSFO', view=view, scope='separate', include_ratios=False)
        annual = next(c for c in report['columns'] if c['basis'] == 'annual')
        assert annual['start'] == '2024-12-24'
        for metric, value, page in (
            ('unrealized_investment_gain', '1662300000', 8),
            ('dividend_income', '171535000', 8), ('operating_income', '1833835000', 8),
            ('operating_expenses', '-203250000', 8), ('profit_before_tax', '1630585000', 8),
            ('net_income', '1403150000', 8), ('cfo', '32730000', 11),
        ):
            cell = next(r['cells']['2025'] for r in report['rows'] if r['metric_id'] == metric)
            assert (cell['value'], cell['page'], cell['period_start']) == (value, page, '2024-12-24')

        portfolio = next(r['cells']['2025'] for r in report['rows'] if r['metric_id'] == 'financial_assets_fvtpl')
        assert (portfolio['value'], portfolio['page']) == ('30120689000', 9)


def test_anor_gross_loans_use_the_filed_note_and_preserve_conflicts():
    from financial_columns import investor, matrix, observations

    fixture = Path('tests/fixtures/financial_columns/anbk_customer_loans_2025.json')
    snapshot = json.loads(fixture.read_text())
    rows = observations.ifrs([snapshot])

    def loans(source):
        table = matrix.build(source, mode='annual')
        return investor.field_cells(table, 'loans', 'bs')['2025']

    cell = loans(rows)
    assert (cell['value'], cell['source_form'], cell['page']) == ('10596145884', 'Notes', 23)
    note = next(row for row in rows if row['metric_id'] == 'loans_gross')
    assert loans([dict(note, metric_id='loans_and_finance_leases_gross')])['value'] is None
    assert loans([row for row in rows if row['source_form'] == 'BS'])['value'] is None
    conflict = loans([*rows, dict(note, source_form='BS', value='10596145885')])
    assert conflict['value'] is None and conflict['reason'] == 'CONFLICTING_SOURCE_VALUES'


def test_urts_calculated_ebitda_and_margin_use_cash_flow_addback():
    from decimal import Decimal
    from financial_columns import derived, ratios

    filed = json.loads(Path('tests/fixtures/financial_columns/urts_2025_ebitda.json').read_text())
    actual = derived.enrich(filed, template='industry')
    ebitda = next(r for r in actual if r['metric_id'] == 'ebitda')
    assert ebitda['value'] == '213279768'
    assert [(p['source_form'], p['page']) for p in ebitda['components']] == [('PL', 2), ('CF', 4)]
    margin = next(r for r in ratios.calculate(actual, ticker='URTS', template='industry',
                  end='2025-12-31', basis='annual', enriched=True) if r['metric_id'] == 'ebitda_margin')
    assert Decimal(margin['value']) == Decimal('213279768') / 446493601 * 100
    assert margin['components'][0]['formula'] == ebitda['formula']


@pytest.mark.parametrize('change', [
    {'scope': 'separate'}, {'period_end': '2024-12-31'}, {'source_version': 'another-report'},
    {'currency': 'USD'}, {'unit': 'shares'}, {'kind': 'stock'}, {'quality': 'blocked'},
    {'metric_id': 'depreciation_impairment'}, {'value': '-8897879'},
])
def test_ebitda_from_cash_flow_requires_matching_report_and_complete_addback(change):
    from financial_columns.derived import enrich

    rows = json.loads(Path('tests/fixtures/financial_columns/urts_2025_ebitda.json').read_text())
    for row in rows:
        if row['source_form'] == 'CF':
            row.update(change)
    assert not any(r['metric_id'] == 'ebitda' for r in enrich(rows, template='industry'))


def test_cash_flow_depreciation_annotation_links_to_the_filed_adjustment():
    from financial_columns import investor, matrix
    rows = json.loads(Path('tests/fixtures/financial_columns/urts_2025_ebitda.json').read_text())
    cell = investor.field_cells(matrix.build(rows, mode='annual'), 'depreciation', 'cf')['2025']
    assert (cell['value'], cell['source_form'], cell['page']) == ('8897879', 'CF', 4)


@pytest.mark.parametrize('metric,amount', [('discontinued_operations_profit', '1200'), ('depreciation_amortization', '-500')])
def test_ebitda_does_not_override_a_different_profit_perimeter_or_disagreeing_charge(metric, amount):
    from financial_columns.derived import enrich
    rows = json.loads(Path('tests/fixtures/financial_columns/urts_2025_ebitda.json').read_text())
    rows.append({**rows[0], 'metric_id': metric, 'value': amount})
    assert not any(r['metric_id'] == 'ebitda' for r in enrich(rows, template='industry'))
