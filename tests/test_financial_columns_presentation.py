import json
from pathlib import Path
import pytest

from financial_columns.presentation import project, template_for


def test_hmkb_overview_matches_html_24_rows_and_preserves_component_values():
    fixture = Path('tests/fixtures/financial_columns')
    source = json.loads((fixture / 'hmkb_2025_matrix.json').read_text(encoding='utf-8'))
    expected = json.loads((fixture / 'hmkb_overview_labels.json').read_text(encoding='utf-8'))
    result = project(source)
    overview = result.get('overview_rows', result['rows'])
    assert [r['label'] for r in overview] == expected
    assert len({r['display_field'] for r in overview}) == 24
    loans = next(r for r in overview if r['display_field'] == 'gross_loans')
    parts = loans['cells']['2025']['display_parts']
    for part in parts:
        original = next(r for r in source['rows'] if r['source_form'] == part['source_form'] and r['source_code'] == part['source_code'])
        assert part == original['cells']['2025']
    assert len(parts) == 2
    deposit = next(r for r in overview if r['display_field'] == 'customer_accounts')
    assert deposit['cells']['2025']['value'] is None
    assert deposit['cells']['2025']['quality'] == 'missing'
    assert len(result['rows']) == 42  # The longer reference list remains available separately.


def test_overview_components_keep_codes_even_when_the_period_is_missing():
    loans = row('BANK_BS', '7а', 'loans_gross')
    leases = row('BANK_BS', '7б', 'leases_gross')
    leases['cells']['2025'] = {'value': None, 'quality': 'blocked', 'reason': 'UNDER_REVIEW'}
    overview = project(payload([loans, leases]))['overview_rows']
    cell = next(r for r in overview if r['display_field'] == 'gross_loans')['cells']['2025']
    assert cell['value'] is None  # Never present a partial total.
    assert [(p['source_code'], p['value'], p['quality']) for p in cell['display_parts']] == [
        ('7а', '0', 'valid'), ('7б', None, 'blocked')]


def row(form, code, metric, value='0'):
    return dict(id=f'{form}:{code or metric}', source_form=form, source_code=code, metric_id=metric,
                label=metric, kind='stock' if form.endswith('BS') else 'flow', unit='UZS_thousand',
                cells={'2025': {'value': value, 'quality': 'valid', 'raw_value': value, 'source_url': 'https://openinfo.uz'}})


def payload(rows, template='bank', standard='NSBU'):
    return dict(template=template, standard=standard, issuer_name='Example', rows=rows, ratios=[],
                columns=[dict(key='2025', label='2025', end='2025-12-31', basis='annual')], source_forms=[])


def test_insurance_and_general_use_distinct_namespaced_lists():
    source=[row('INSURANCE_PL','070','insurance_cost'),row('INSURANCE_PL','100','selling_expense'),
            row('F2','070','other_operating_expense'),row('F2','080','excluded_period_expenses')]
    assert [r['source_code'] for r in project(payload(source,'insurance'))['rows']] == ['070']
    assert [r['source_form'] for r in project(payload(source,'general'))['rows']] == ['F2']


def test_ifrs_lists_do_not_accept_nsbu_codes_or_unlisted_metrics():
    source=[row('PL',None,'interest_eir'),row('PL',None,'revenue'),row('BS',None,'loans_net'),
            row('BS',None,'preferred_share_liability'),row('BANK_PL','1л','interest_income')]
    selected=project(payload(source,standard='MSFO'))['rows']
    assert [r['metric_id'] for r in selected] == ['interest_eir','loans_net']
    assert selected[0]['cells']['2025']['value'] == '0'
    assert selected[0]['cells'] == source[0]['cells']


def test_reference_projection_keeps_source_order_independent_and_missing_rows_empty():
    source=[row('BANK_BS','14','total_assets'),row('BANK_PL','7а','staff_expense'),row('BANK_PL','1л','interest_income')]
    result=project(payload(source))
    assert [r['metric_id'] for r in result['rows']] == ['interest_income','total_assets']
    assert result['rows'][0]['display_group'] != result['rows'][1]['display_group']
    assert project(payload([]))['rows'] == []
    assert len(source) == 3


@pytest.mark.parametrize('standard,form,code,metric,expected', [
    ('NSBU', 'BANK_PL', '1л', 'interest_income', 'Итого процентных доходов'),
    ('MSFO', 'PL', None, 'interest_eir', 'Процентный доход по эффективной ставке (EIR)'),
])
def test_reference_labels_replace_source_labels_without_losing_provenance(standard,form,code,metric,expected):
    source = row(form,code,metric)
    source['label'] = 'Long original filing label'
    result = project(payload([source],standard=standard))['rows'][0]
    assert result['label'] == expected
    assert result['source_label'] == source['label'] == 'Long original filing label'
    assert result['cells'] == source['cells']
    assert result['id'] == source['id']


@pytest.mark.parametrize('name,kind,expected', [
    ('O‘zbektelekom','industry','telecom'),('Regional Telecom Services','industry','telecom'),
    ('O‘zagrolizing','financial','leasing'),('Example Leasing','financial','leasing'),
    ('Aloqabank','bank','bank'),('Telecom Bank','bank','bank'),('Factory','industry','general')])
def test_reference_template_uses_sector_and_name_not_ticker(name,kind,expected):
    assert template_for(kind,name) == expected


@pytest.mark.parametrize('ticker,source_template,display_template,kept,rejected', [
    ('alkb','bank','bank',('BANK_PL','1л'),('BANK_PL','7а')),
    ('kfsk','insurance','insurance',('INSURANCE_PL','060'),('INSURANCE_PL','100')),
    ('uzal','general','leasing',('F2','140'),('F2','060')),
    ('uzal','general','general',('F2','060'),('F2','140')),
    ('uztl','general','telecom',('F1','030'),('F1','330')),
])
def test_real_annual_filings_follow_the_reference_lists(ticker,source_template,display_template,kept,rejected):
    from financial_columns.nsbu import rows
    document=json.loads(Path(f'tests/fixtures/openinfo/{ticker}_2025_complete_rows.json').read_text(encoding='utf-8'))
    original=rows(document,template=source_template)
    source=[{**r,'id':r['source_form']+':'+r['source_code'],'cells':{'2025':r['current']}} for r in original]
    selected=project(payload(source,display_template))['rows']
    codes={(r['source_form'],r['source_code']) for r in selected}
    assert kept in codes and rejected not in codes
    assert rejected in {(r['source_form'],r['source_code']) for r in original}
    assert all(r['cells']==next(s for s in source if s['id']==r['id'])['cells'] for r in selected)


def test_all_twelve_reference_lists_are_explicit():
    from financial_columns.presentation import FIELDS
    counts={'bank':(42,38),'insurance':(25,30),'leasing':(19,19),'general':(35,36),'telecom':(37,20),'fund':(5,18)}
    assert set(FIELDS)==set(counts)
    for sector,expected in counts.items():
        assert tuple(sum(len(g['fields']) for g in FIELDS[sector][standard]) for standard in ['nsbu','ifrs'])==expected
        for standard in ['nsbu','ifrs']:
            fields=[f for g in FIELDS[sector][standard] for f in g['fields']]
            assert len({f['field_id'] for f in fields})==len(fields)
            assert all(f['selectors'] for f in fields)
