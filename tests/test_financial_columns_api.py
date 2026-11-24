import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from fastapi import FastAPI
from server.company.financial_routes import router
from catalogue.storage import get_catalog_conn
from financial_columns import source_store

app = FastAPI()
app.include_router(router)


def test_table_request_skips_unused_documents_and_ratios_without_losing_evidence(source, monkeypatch):
    from financial_columns import ratios, service
    full = service.load('IPTB', view='template', freq='quarter')
    def unused_calculation(*args, **kwargs):
        pytest.fail('A statement table must not calculate the unopened ratios tab')
    monkeypatch.setattr(ratios, 'calculate', unused_calculation)
    compact = service.load('IPTB', view='template', freq='quarter', include_sources=False, include_ratios=False)
    assert compact['rows'] == full['rows']
    assert compact['overview_rows'] == full['overview_rows']
    assert compact['columns'] == full['columns']
    assert compact['source_forms'] == compact['ratios'] == compact['published_ratios'] == []
    assert len(json.dumps(compact)) < len(json.dumps(full))
    assert any(cell.get('source_url') and cell.get('source_version')
               for row in compact['rows'] for cell in row['cells'].values())


def test_ratio_periods_prepare_derived_history_only_once(source, monkeypatch):
    from financial_columns import service, ratios
    calls = []
    original = service.derived.enrich
    def counted(rows, **options):
        calls.append(len(rows))
        return original(rows, **options)
    expected = service.load('IPTB', freq='quarter', view='template')
    monkeypatch.setattr(service.derived, 'enrich', counted)
    monkeypatch.setattr(ratios, 'enrich', counted)
    actual = service.load('IPTB', freq='quarter', view='template')
    assert actual == expected
    assert len(actual['columns']) > 1
    assert len(calls) == 1


@pytest.mark.parametrize('statement,form', [('balance','BANK_BS'),('income','BANK_PL')])
@pytest.mark.parametrize('view', ['template','overview'])
def test_statement_tabs_and_exports_keep_only_the_requested_statement(source, statement, form, view):
    import csv
    import io
    from openpyxl import load_workbook
    query=f'view={view}&statement={statement}'
    with TestClient(app) as client:
        data=client.get(f'/api/company/IPTB/financials/columns?{query}').json()
        csv_result=client.get(f'/api/company/IPTB/financials/columns.csv?{query}')
        xlsx_result=client.get(f'/api/company/IPTB/financials/columns.xlsx?{query}')
    expected_forms = {form, 'DERIVED'} if statement == 'balance' else {form}
    assert data['rows'] and {r['source_form'] for r in data['rows']} == expected_forms
    if statement == 'balance':
        assert {r['metric_id'] for r in data['rows'] if r['source_form'] == 'DERIVED'} == {'customer_funds'}
    records=list(csv.DictReader(io.StringIO(csv_result.content.decode('utf-8-sig'))))
    assert {r['source_form'] for r in records} == expected_forms
    worksheet=list(load_workbook(io.BytesIO(xlsx_result.content)).active.values)
    assert {r[worksheet[0].index('source_form')] for r in worksheet[1:]} == expected_forms
    assert any(r['value'] not in {'',None} for r in records)


def test_statement_filter_rejects_unknown_names(source):
    with TestClient(app) as client:
        assert client.get('/api/company/IPTB/financials/columns?statement=BAD').status_code == 422


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'catalog.db'))
    c = get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('IPTB','Ipoteka bank','217')")
    c.close()
    data = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json').read_text(encoding='utf-8'))
    source_store.record_nsbu(ticker='IPTB', issuer_id='217', year=2026, quarter=3, template='bank',
                            data={'ok': True, 'income': data, 'balance': data},
                            urls={'excel_url': data['source_url'], 'published_at': '2026-10-20'})
    return data


def test_public_matrix_uses_full_stored_forms_and_keeps_stocks_out_of_ttm(source):
    with TestClient(app) as client:
        response = client.get('/api/company/IPTB/financials/columns?form=NSBU&scope=separate&freq=interim')
    assert response.status_code == 200
    result = response.json()
    assert result['unit'] == 'UZS_thousand'
    income = next(r for r in result['rows'] if r['id'] == 'BANK_PL:1л')
    cell = income['cells']['2026-09-30']
    assert cell['value'] == '9447836814'
    assert cell['source_url'] == source['source_url']
    assert cell['source_code'] == '1л'
    assert cell['scope'] == 'separate'
    assert cell['raw_value'] == 9447836814
    assert result['source_forms']
    assert result['coverage']['notes'] == 'not_applicable'


@pytest.mark.parametrize('view', ['template', 'overview'])
def test_iptb_annual_screen_and_export_include_current_report_amounts(source, view):
    import csv
    import io
    with TestClient(app) as client:
        response = client.get(f'/api/company/IPTB/financials/columns?view={view}')
        exported = client.get(f'/api/company/IPTB/financials/columns.csv?view={view}')
    assert response.status_code == exported.status_code == 200
    result = response.json()
    assert [(c['label'], c['basis']) for c in result['columns']] == [('2025', 'annual'), ('2026 · 9M', 'ytd')]
    current = result['columns'][-1]['key']
    income = next(r for r in result['rows'] if r['source_form'] == 'BANK_PL' and r['source_code'] == '1л')
    assert income['cells'][current]['value'] == '9447836814'
    assert income['cells'][current]['period_start'] == '2026-01-01'
    assert income['cells'][current]['source_url'] == source['source_url']
    rows = list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    assert any(r['source_code'] == '1л' and r['value'] == '9447836814' and r['period_end'] == '2026-09-30' for r in rows)


def test_matrix_rejects_invalid_context_and_never_reads_nsbu_as_consolidated(source):
    with TestClient(app) as client:
        assert client.get('/api/company/IPTB/financials/columns?form=BAD').status_code == 422
        assert client.get('/api/company/IPTB/financials/columns?freq=BAD').status_code == 422
        result = client.get('/api/company/IPTB/financials/columns?scope=consolidated').json()
    assert result['rows'] == []


def test_csv_and_excel_export_include_source_context_and_zero_cells(source):
    import csv
    import io
    from openpyxl import load_workbook
    with TestClient(app) as client:
        csv_response = client.get('/api/company/IPTB/financials/columns.csv?freq=interim')
        excel_response = client.get('/api/company/IPTB/financials/columns.xlsx?freq=interim')
    assert csv_response.status_code == excel_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.content.decode('utf-8-sig'))))
    item = next(r for r in rows if r['source_code'] == '1л' and r['period_end'] == '2026-09-30')
    assert item['standard'] == 'NSBU' and item['scope'] == 'separate'
    assert item['source_url'] == source['source_url']
    assert item['quality'] == 'valid'
    assert item['value'] == '9447836814'
    assert any(r['value'] == '0' for r in rows)
    workbook = load_workbook(io.BytesIO(excel_response.content))
    assert list(workbook.active.values)[0] == tuple(rows[0].keys())
    assert len(list(workbook.active.values)) == len(rows) + 1


def test_openinfo_ratios_are_separate_from_uzstock_calculations(source):
    from catalogue.facts import upsert_facts
    upsert_facts([{'entity_id': '217', 'dataset': 'financial_indicators', 'field': 'roe',
                   'period': '2025', 'value': 12.5, 'unit': '%',
                   'source': 'openinfo_financial_indicators', 'source_url': source['source_url']},
                  {'entity_id': '217', 'dataset': 'financial_indicators', 'field': 'roe',
                   'period': '2025', 'value': 99, 'unit': '%',
                   'source': 'nsbu_derived', 'source_url': source['source_url']}])
    with TestClient(app) as client:
        result = client.get('/api/company/IPTB/financials/columns').json()
    assert len(result['published_ratios']) == 1
    assert result['published_ratios'][0]['value'] == '12.5'
    assert result['published_ratios'][0]['origin'] == 'OpenInfo_published'
    assert all(cell['origin'] == 'UZStock_calculated' for r in result['ratios'] for cell in r['cells'].values())


def test_exports_include_published_ratios_owners_and_literal_spreadsheet_labels():
    import csv
    import io
    from financial_columns.exports import export
    payload = {'ticker':'UZNF', 'issuer_id':'1059', 'standard':'MSFO', 'scope':'separate',
               'rows':[], 'ratios':[], 'columns':[],
               'published_ratios':[{'field':'roe', 'period':'2024', 'value':'-12.5', 'unit':'%',
                                    'source_url':'https://openinfo.uz', 'origin':'OpenInfo_published'}],
               'shareholders':[{'name':'-HYPERLINK("https://example.com")', 'share':'75', 'date':'2024-12-31',
                                'quality':'valid', 'share_class':'ordinary', 'page':6, 'source_url':'https://openinfo.uz'}]}
    content, _ = export(payload, 'csv')
    rows = list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    assert next(r for r in rows if r['metric_id'] == 'roe')['value'] == '-12.5'
    owner = next(r for r in rows if r['source_form'] == 'OWNERS')
    assert owner['label'].startswith("'-HYPERLINK")
    assert owner['share_class'] == 'ordinary'
    assert owner['page'] == '6'


def test_real_leasing_form_exposes_calculated_debt_and_the_leasing_ratio(source):
    c = get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('UZAL','O‘zagrolizing','638')")
    c.close()
    data = json.loads(Path('tests/fixtures/openinfo/uzal_2025_complete_rows.json').read_text(encoding='utf-8'))
    source_store.record_nsbu(ticker='UZAL', issuer_id='638', year=2025, quarter=0, template='financial',
                            data={'ok':True, 'balance':data, 'income':data}, urls={'excel_url':data.get('source_url', data.get('url'))})
    with TestClient(app) as client:
        result = client.get('/api/company/UZAL/financials/columns').json()
        template = client.get('/api/company/UZAL/financials/columns?view=template').json()
        balance = client.get('/api/company/UZAL/financials/columns?view=template&statement=balance').json()
    assert 'income_flow_rows' not in balance
    finance_cost = next(r for r in result['rows'] if r['id'] == 'F2:170')
    chart_cost = next(r for r in template['income_flow_rows'] if r['id'] == 'F2:170')
    assert chart_cost['cells']['2025'] == {
        key: finance_cost['cells']['2025'][key] for key in ('value', 'quality')
    }
    assert all(r['id'] != 'F2:170' for r in template['rows'])
    assert result['template'] == 'leasing'
    debt = next(r for r in result['rows'] if r['metric_id'] == 'interest_bearing_debt')
    assert debt['cells']['2025']['value'] is not None
    assert len(debt['cells']['2025']['components']) == 5
    cost = next(r for r in result['ratios'] if r['metric_id'] == 'funding_cost')
    assert cost['cells']['2025']['quality'] == 'valid'
    assert float(cost['cells']['2025']['value']) > 0


def test_reference_view_keeps_only_named_bank_fields_and_exports_the_same_rows(source):
    import csv
    import io
    with TestClient(app) as client:
        raw = client.get('/api/company/IPTB/financials/columns?freq=interim').json()
        selected = client.get('/api/company/IPTB/financials/columns?freq=interim&view=template').json()
        exported = client.get('/api/company/IPTB/financials/columns.csv?freq=interim&view=template')
    assert selected['presentation'] == 'template'
    codes = {(r['source_form'], r['source_code']) for r in selected['rows']}
    assert ('BANK_PL', '1л') in codes
    assert ('BANK_PL', '1а') in codes
    assert ('BANK_PL', '7з') in codes
    assert ('BANK_BS', '14') in codes
    assert ('BANK_PL', '7а') not in codes  # staff expense is not a reference field
    assert ('BANK_PL', '7в') not in codes  # travel expense
    assert ('BANK_PL', '1') not in codes   # heading must not duplicate the total
    assert ('BANK_BS', '31') not in codes # unlisted balance check total
    assert len(selected['rows']) < len(raw['rows'])
    for row in selected['rows']:
        assert row['cells'] == next(r for r in raw['rows'] if r['id'] == row['id'])['cells']
    income = next(r for r in selected['rows'] if r['id'] == 'BANK_PL:1л')
    raw_income = next(r for r in raw['rows'] if r['id'] == income['id'])
    assert income['label'] == 'Итого процентных доходов'
    assert income['source_label'] == raw_income['label']
    assert income['cells']['2026-09-30']['raw_label'] == raw_income['label']
    rows = list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    assert next(r for r in rows if r['source_code'] == '1л')['label'] == income['label']
    assert not any((r['source_form'], r['source_code']) in {('BANK_PL','7а'), ('BANK_PL','7в'), ('BANK_BS','31')} for r in rows)
    assert any(r['source_code'] == '1л' and r['value'] == '9447836814' for r in rows)
    assert all(r['metric_id'] in {'roe','roa','roce','nim','cir','cost_of_risk','loans_to_deposits'} for r in selected['ratios'])
    roce = next(r for r in selected['ratios'] if r['metric_id'] == 'roce')
    assert all(cell['reason'] == 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE' for cell in roce['cells'].values())


def test_reference_view_rejects_unknown_view(source):
    with TestClient(app) as client:
        assert client.get('/api/company/IPTB/financials/columns?view=bad').status_code == 422
        assert client.get('/api/company/IPTB/financials/columns.csv?view=bad').status_code == 422


def test_overview_export_matches_the_compact_html_list(source):
    import csv
    import io
    with TestClient(app) as client:
        response = client.get('/api/company/IPTB/financials/columns?freq=interim&view=overview')
        exported = client.get('/api/company/IPTB/financials/columns.csv?freq=interim&view=overview')
    assert response.status_code == exported.status_code == 200
    data = response.json()
    assert len(data['rows']) == 24
    rows = list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
    assert {r['label'] for r in rows} == {r['label'] for r in data['rows']}
    assert not any(r['source_code'] == '7з' and r['source_form'] == 'BANK_PL' for r in rows)
    assert any(r['source_code'] == '7а' and r['source_form'] == 'BANK_BS' and r['value'] for r in rows)


@pytest.mark.parametrize('issuer_kind', ['industry', 'insurance'])
def test_filed_inventory_reaches_both_balance_views_and_retains_original_source_row(source, monkeypatch, issuer_kind):
    from financial_columns import ifrs, service
    snapshot = json.loads(Path('tests/fixtures/financial_columns/uzngp_inventory_2025.json').read_text())
    monkeypatch.setattr(service.publication, 'snapshots', lambda *args, **kwargs: [snapshot])
    monkeypatch.setattr(service.publication, 'scopes', lambda ticker: ['separate'])
    monkeypatch.setattr(service, 'organization_kind', lambda *args, **kwargs: issuer_kind)
    def load(view):
        return service.load('UZNGP', form='MSFO', scope='separate', view=view)
    full = next(r for r in load('full')['rows'] if r['id'] == 'BS:inventories')
    assert full['cells']['2025']['value'] == '452000000'
    shown = next(r for r in load('template')['rows'] if r['display_field'] == 'inventories')
    investor = next(r for g in load('investor')['statements']['bs'] for r in g['rows'] if r['field'] == 'inventory')
    for row in [shown, investor]:
        cell = row['cells']['2025']
        assert cell['value'] == full['cells']['2025']['value']
        assert cell['raw_value'] == '452' and cell['page'] == 5 and cell['source_url'] == snapshot['payload']['source']['pdf_url']
    if issuer_kind == 'insurance':
        from collectors.financials.coverage_columns import statement_cells
        snapshot['payload']['source_rows'] = []
        empty = load('template')
        assert not any(r.get('display_field') == 'inventories' for r in empty['overview_rows'])
        assert not any('inventor' in key for key in statement_cells(empty))
        assert not any(r['field'] == 'inventory' for g in load('investor')['statements']['bs'] for r in g['rows'])
    for caption in ('Товарно-материальные запасы', 'Оборотные запасы'):
        assert ifrs.metric(caption, 'BS') == 'inventory'
    assert ifrs.metric('Изменение в товарно-материальных запасах', 'CF') != 'inventory'


def test_iptb_deposits_and_loan_ratio_use_the_same_filed_balance(source):
    from decimal import Decimal
    from financial_columns import service

    data = service.load('IPTB', freq='interim', view='template')
    period = '2026-09-30'
    deposits = next(r for r in data['overview_rows'] if r['display_field'] == 'customer_accounts')['cells'][period]
    assert deposits['value'] == '29321578637'
    assert deposits['origin'] == 'UZStock_calculated'
    assert [(c['source_code'], c['value']) for c in deposits['components']] == [
        ('15', '9468914184'), ('16', '0'), ('17', '19852664453')]
    assert all(c['source_url'] == source['source_url'] and c['period_end'] == period for c in deposits['components'])
    loan_ratio = next(r for r in data['ratios'] if r['metric_id'] == 'loans_to_deposits')
    cell = loan_ratio['cells'][period]
    assert Decimal(cell['value']) == Decimal('37439271287') / Decimal('29321578637')
    assert cell['unit'] == 'ratio' and not cell['annualized']
    assert [c['metric_id'] for c in cell['components']] == ['loans_gross', 'customer_funds']


def test_deposit_total_requires_three_compatible_balance_lines(source):
    from financial_columns import derived, ratios, service

    data = service.load('IPTB', freq='interim', view='full')
    end = '2026-09-30'
    cells = {r['source_code']: r['cells'][end] for r in data['rows'] if r['source_form'] == 'BANK_BS'}
    demand, savings, term = [cells[code] for code in ('15','16','17')]

    def totals(rows):
        return [r for r in derived.enrich(rows) if r['metric_id'] == 'customer_funds']

    for unusable in ({'value': None, 'quality': 'missing'}, {'quality': 'blocked'},
                     {'source_version': 'different'}, {'period_end': '2025-12-31'},
                     {'source_form': 'F1'}, {'source_code': '18'}, {'unit': 'USD'}):
        assert totals([demand, {**savings, **unusable}, term]) == []
    zero = totals([{**item, 'value': '0'} for item in (demand, savings, term)])[0]
    assert zero['value'] == '0'
    filed = {**demand, 'metric_id': 'customer_funds', 'source_code': None}
    assert totals([demand, savings, term, filed]) == [filed]
    for deposit, reason in [(zero, 'NONPOSITIVE_DENOMINATOR'),
                            ({**zero, 'value': '1000', 'source_version': 'other'}, 'INCOMPATIBLE_OR_BLOCKED_INPUTS')]:
        result = ratios.calculate([cells['7а'], deposit], ticker='IPTB', template='bank', end=end, basis='as_of')
        cell = next(r for r in result if r['metric_id'] == 'loans_to_deposits')
        assert cell['value'] is None and cell['reason'] == reason


def test_public_iptb_balance_history_and_passports_match_the_filed_deposits(source):
    import asyncio
    from server.company.financials import _sector_presentation, financial_passport
    period = '2026Q3'
    data = {'standard': 'NSBU', 'freq': 'quarterly', 'periods': [period], 'series': {}}
    series = _sector_presentation(data, 'IPTB')['series']
    assert series['customer_funds']['values'][period] == 29321578637000
    assert series['savings_deposits']['values'][period] == 0
    assert series['loans_to_deposits']['values'][period] == pytest.approx(37439271287 / 29321578637)
    assert series['customer_funds']['unit'] == 'UZS' and series['loans_to_deposits']['money'] is False
    for field, status in [('demand_deposits', 'SOURCED'), ('customer_funds', 'DERIVED'), ('loans_to_deposits', 'DERIVED')]:
        passport = asyncio.run(financial_passport('IPTB', period, field))
        assert passport['status'] == status and passport['source']['excel_url'] == source['source_url']
        if field == 'demand_deposits':
            assert passport['source']['raw_value'] == 9468914184
            assert passport['source']['period_quarter'] == 3 and passport['source']['period_year'] == 2026
    held = {**data, 'series': {}, 'data_gaps': [{'period':period,'code':'VALUE_QUARANTINE'}]}
    assert 'customer_funds' not in _sector_presentation(held, 'IPTB')['series']


def test_empty_bank_balance_column_cannot_establish_zero_deposits():
    from financial_columns import observations, derived
    # Asia Alliance Bank's 2020 Q1 workbook 476 carries amounts in the first
    # balance column and a zero for every balance line in the second.
    url = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_type=quarter&org_type=bank&report_id=476&lang=ru'
    rows = []
    for code, field, raw in [('14','total_assets','2395659440'),('15','demand_deposits','574005074'),
                             ('16','savings_deposits','0'),('17','term_deposits','986968131')]:
        rows.append(dict(metric_id=field, source_form='BANK_BS', source_code=code, kind='stock',
                         raw_label=field, unit='UZS_thousand', source_url=url,
                         current={'value':'0','quality':'valid','raw_value':0},
                         previous={'value':raw,'quality':'valid','raw_value':raw}))
    doc = dict(issuer_id='31', scope='separate', period_end='2020-03-31', quality='valid', currency='UZS',
               unit_scale='1000', template='bank', source_version='476', rows=rows)
    parsed = observations.nsbu([doc])
    current = [r for r in parsed if r['role'] == 'PRIMARY']
    assert all(r['value'] is None and r['raw_value'] == 0 and r['reason'] == 'EMPTY_BANK_BALANCE_COLUMN' for r in current)
    assert not any(r['metric_id'] == 'customer_funds' for r in derived.enrich(current))
    raw_zero = next(r for r in parsed if r['role'] == 'COMPARATIVE' and r['metric_id'] == 'savings_deposits')
    assert raw_zero['raw_value'] == '0' and raw_zero['reason'] == 'BANK_BALANCE_DATE_UNRESOLVED'
    from financial_columns.matrix import choose
    closing = next(r for r in current if r['metric_id'] == 'term_deposits')
    corroborated = {**closing, 'value': '900', 'quality': 'valid', 'reason': None,
                    'source_version': 'independent-annual', 'role': 'COMPARATIVE'}
    assert choose([closing, corroborated])['value'] == '900'
    assert choose([closing])['value'] is None
    # A genuine zero in a populated balance remains available.
    rows[0]['current']['value'] = '2395659440'
    verified = observations.nsbu([doc])
    assert next(r for r in verified if r['role'] == 'PRIMARY' and r['metric_id'] == 'savings_deposits')['value'] == '0'
