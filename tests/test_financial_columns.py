"""Source namespaces and date algebra for the corrected financial terminal."""
import json
from pathlib import Path
import pytest

from financial_columns import nsbu, periods


def test_iptb_bank_source_has_all_subrows_and_its_own_namespace():
    source = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_replaced.json').read_text())['current']
    rows = nsbu.rows(source, template='bank')
    by_code = {(r['source_form'], r['source_code']): r for r in rows}
    loan = by_code['BANK_BS', '7а']
    assert loan['metric_id'] == 'loans_gross'
    assert loan['current']['value'] == '37439271287.0'
    assert loan['raw_cells'][0] == 'а. Брутто кредиты'
    assert ('BANK_BS', '31') in by_code
    assert ('BANK_PL', '11') in by_code
    assert by_code['BANK_BS', '26а']['kind'] == 'stock'
    assert by_code['BANK_BS', '26а']['unit'] == 'UZS_thousand'
    assert all(r['source_form'].startswith('BANK_') for r in rows)


def test_bank_category_headers_and_single_period_income_are_not_lost():
    source = json.loads(Path('tests/fixtures/openinfo/iptb_2026q3_complete_rows.json').read_text(encoding='utf-8'))
    rows = nsbu.rows(source, template='bank')
    keyed = {(r['source_form'], r['source_code']): r for r in rows}
    assert len(keyed) == len(rows)
    assert keyed['BANK_BS', '28а.1']['metric_id'] is None
    assert keyed['BANK_PL', '1а']['current']['value'] == '12904109'
    assert keyed['BANK_PL', '1л']['current']['value'] == '9447836814'
    assert keyed['BANK_PL', '1л']['previous']['quality'] == 'missing'
    assert keyed['BANK_PL', '4а']['metric_id'] == 'fee_income'
    assert keyed['BANK_PL', '7з']['metric_id'] == 'operating_expenses'
    assert keyed['BANK_PL', '7з']['current']['value'] == '1732361785'


@pytest.mark.parametrize('ticker,template,form,code,metric', [
    ('alkb', 'bank', 'BANK_BS', '31', 'total_equity_liabilities'),
    ('kfsk', 'insurance', 'INSURANCE_BS', '490', 'total_assets'),
    ('uzal', 'general', 'F1', '400', 'total_assets'),
    ('uztl', 'general', 'F1', '400', 'total_assets'),
])
def test_actual_annual_form_layouts_keep_balance_rows(ticker, template, form, code, metric):
    source = json.loads(Path(f'tests/fixtures/openinfo/{ticker}_2025_complete_rows.json').read_text(encoding='utf-8'))
    result = nsbu.rows(source, template=template)
    found = next(r for r in result if r['source_form'] == form and r['source_code'] == code)
    assert found['metric_id'] == metric
    physical = next(r for sheet in source['sheets'] for r in sheet['source_rows'] if r['row'] == found['row'] and sheet['sheet'] == found['sheet'])
    assert found['raw_cells'] == physical['cells']
    assert found['current']['value'] is not None
    assert len(result) >= 100
    if ticker == 'alkb':
        assert found['previous']['value'] is None
        assert found['current']['value'] == '31527540077'
    if ticker == 'kfsk':
        codes = {r['source_code'] for r in result if r['source_form'] == form}
        assert {'580','670','720','950'} <= codes
    if ticker == 'uztl':
        assert any(r['current']['value'] == '0' for r in result)


def test_general_full_rows_retain_zero_and_do_not_call_construction_cash_capex():
    source = json.loads(Path('tests/fixtures/form1_subtotals.json').read_text(encoding='utf-8'))['MIQE_2026Q2']
    data = {'sheets': [{'sheet': 'Форма №1', 'table_rows': source['rows']}]}
    rows = nsbu.rows(data, template='general', default_form='F1')
    by_code = {r['source_code']: r for r in rows}
    assert by_code['100']['metric_id'] == 'construction_in_progress'
    assert by_code['100']['kind'] == 'stock'
    assert by_code['110']['metric_id'] == 'long_term_receivables'
    assert by_code['020']['current']['value'] == '0.0'
    assert by_code['211']['metric_id'] == 'overdue_receivables'
    assert len(rows) == len(source['rows']) - 1  # Exclude the KFS registration header.


def test_insurance_form_codes_cannot_be_interpreted_as_company_balance_codes():
    data = {'sheets': [{'sheet': 'Баланс', 'source_rows': [
        {'row': 1, 'cells': ['Всего по активу баланса', '490', '100', '110']},
        {'row': 2, 'cells': ['Страховые резервы, всего', '580', '50', '60']},
        {'row': 3, 'cells': ['Доля перестраховщиков в страховых резервах', '670', '10', '20']},
        {'row': 4, 'cells': ['Итого по разделу II (стр. 580 - 670)', '720', '40', '40']},
        {'row': 5, 'cells': ['Неизвестная строка', '777', '—', '0']},
    ]}]}
    rows = nsbu.rows(data, template='insurance', default_form='F1')
    by_code = {r['source_code']: r for r in rows}
    assert by_code['490']['metric_id'] == 'total_assets'
    assert by_code['580']['metric_id'] == 'insurance_reserves_gross'
    assert by_code['720']['metric_id'] == 'insurance_reserves_net'
    assert by_code['777']['previous']['quality'] == 'missing'
    assert by_code['777']['previous']['raw_value'] == '—'
    assert by_code['777']['current']['value'] == '0'
    assert by_code['777']['metric_id'] is None


def test_insurance_code_label_conflict_keeps_raw_row_without_wrong_semantics():
    source = {'sheets': [{'sheet': 'Баланс', 'source_rows': [
        {'row': 1, 'cells': ['Долгосрочные обязательства', '490', '100', '110']},
    ]}]}
    row = nsbu.rows(source, template='insurance')[0]
    assert row['source_code'] == '490'
    assert row['metric_id'] is None
    assert row['current']['raw_value'] == '110'
    assert row['mapping_issue'] == 'CODE_LABEL_MISMATCH'


def observations(kind='flow', scope='separate'):
    return [{'period_start': f'{y}-01-01', 'period_end': f'{y}-{end}',
             'value': value, 'standard': 'NSBU', 'scope': scope, 'issuer_id': '123',
             'kind': kind, 'quality': 'valid', 'source_version': f'{y}-{end}'}
            for y, end, value in [(2024, '06-30', '30'), (2024, '12-31', '100'),
                                  (2025, '03-31', '20'), (2025, '06-30', '50')]]


def test_quarter_and_ttm_use_exact_coverage_and_keep_component_passports():
    data = observations()
    q2 = periods.calculate(data, '2025-06-30', 'quarter')
    ttm = periods.calculate(data, '2025-06-30', 'ttm')
    assert q2['value'] == '30'
    assert q2['period_start'] == '2025-04-01'
    assert ttm['value'] == '120'
    assert ttm['period_start'] == '2024-07-01'
    assert len(ttm['components']) == 3
    assert periods.calculate(data[1:], '2025-06-30', 'ttm')['quality'] == 'missing'
    assert periods.calculate([data[1]], '2024-12-31', 'quarter')['quality'] == 'missing'


def test_stock_is_a_date_not_ttm_and_scope_or_blocked_inputs_never_mix():
    assert periods.calculate(observations('stock'), '2025-06-30', 'ttm')['quality'] == 'not_applicable'
    data = observations()
    data[-2]['scope'] = 'consolidated'
    assert periods.calculate(data, '2025-06-30', 'quarter')['quality'] == 'missing'
    data[-2]['scope'] = 'separate'
    data[-2]['quality'] = 'blocked'
    assert periods.calculate(data, '2025-06-30', 'quarter')['quality'] == 'blocked'


def test_duplicate_conflicting_source_versions_do_not_silently_win():
    data = observations()
    data.append({**data[-1], 'value': '60', 'source_version': 'revised'})
    assert periods.calculate(data, '2025-06-30', 'quarter')['quality'] == 'blocked'


def test_a_reported_standalone_quarter_needs_no_ytd_subtraction():
    data = [{**observations()[-1], 'period_start': '2025-04-01', 'value': '37'}]
    result = periods.calculate(data, '2025-06-30', 'quarter')
    assert result['value'] == '37'
    assert result['basis'] == 'reported_quarter'
    assert len(result['components']) == 1


@pytest.mark.parametrize('metric,kind', [('eps_basic','per_share'), ('weighted_average_shares','flow')])
def test_eps_cannot_be_subtracted_like_profit_when_share_counts_may_change(metric,kind):
    data = [{**r, 'kind': kind, 'metric_id': metric} for r in observations()]
    assert periods.calculate(data, '2025-06-30', 'quarter')['quality'] == 'not_applicable'
    assert periods.calculate(data, '2025-06-30', 'ttm')['quality'] == 'not_applicable'
def test_kafolat_2025_subtotals_and_reserve_changes_have_literal_meanings():
    import json
    from pathlib import Path
    from financial_columns.nsbu import rows
    data = json.loads(Path('tests/fixtures/openinfo/kfsk_2025_complete_rows.json').read_text(encoding='utf-8'))
    mapped = {(r['source_form'], r['source_code']): r for r in rows(data, template='insurance')}
    assert mapped['INSURANCE_BS', '1190']['metric_id'] == 'nonreserve_liabilities'
    assert mapped['INSURANCE_BS', '1200']['metric_id'] == 'total_equity_liabilities'
    assert mapped['INSURANCE_PL', '015']['metric_id'] == 'change_reported_claims_net'
    assert mapped['INSURANCE_PL', '130']['metric_id'] == 'excluded_period_expenses'
    assert mapped['INSURANCE_PL', '140']['metric_id'] == 'other_operating_income'


def test_fully_crossed_income_and_expense_cells_remain_not_applicable():
    from financial_columns.nsbu import rows
    workbook = {'sheets': [{'sheet': 'Форма 2', 'source_rows': [
        {'row': 1, 'cells': ['Валовая прибыль', '030', 0, 'X', 'X', 'Х']}]}]}
    row = rows(workbook, template='industry', default_form='F2')[0]
    assert row['previous']['value'] == '0'
    assert row['current']['value'] is None
    assert row['current']['quality'] == 'not_applicable'


@pytest.mark.parametrize('reader', ['headline', 'statement', 'sector'])
def test_becm_h1_2026_preserves_income_and_loss_columns(reader):
    # Openinfo attachment 3141, filed 31 July 2026, Form 2 rows 030, 100 and 270.
    from catalogue.parsing import compute_financial_ratios
    from collectors.openinfo.workbooks import _parse_excel_workbook

    book = _parse_excel_workbook(Path('tests/fixtures/openinfo/becm_2026h1_income.xlsx').read_bytes())
    expected = {'gross_profit': 19_172_256.7, 'operating_income': -18_792_285.3,
                'net_income': -14_732_265.8, 'operating_expenses': -39_643_960.2}
    if reader == 'headline':
        values = compute_financial_ratios(book, None)['source_values']
    elif reader == 'sector':
        from financial_analysis.sector_inputs import prepare_inputs
        values, _, _, _ = prepare_inputs({'organization_type': 'non_financial'}, {'income': book})
        expected['period_expenses'] = -expected.pop('operating_expenses')
    else:
        rows = nsbu.rows(book, template='general', default_form='F2')
        values = {r['metric_id']: r['current']['value'] for r in rows}
    assert {k: float(values[k]) if values[k] is not None else None for k in expected} == expected


@pytest.mark.parametrize('variant', ['split', 'different_dates', 'mixed_values', 'unbalanced', 'wrong_period', 'one_column'])
def test_universal_bank_single_period_balance_uses_both_sides(variant):
    from financial_columns import observations
    # Openinfo bank quarterly filing 1309, original Excel rows 33–91.
    url = 'https://new-api.openinfo.uz/api/v2/reports/export-excel/?org_type=bank&report_type=quarter&report_id=1309'
    end = '2026-09-30'
    lines = [
        [4, ['Дата отчетности:', end]],
        [33, ['Бухгалтерский баланс - форма № 1']],
        [34, ['Категории', '(тыс.сум.)', None]],
        [36, ['1. Кассовая наличность и другие платежные документы', 459344736, 0]],
        [65, ['14. Итого активов', 5416243300, 0]],
        [78, ['25. Итого обязательств', 0, 4481271663]],
        [80, ['26. Уставный капитал', 0, 500000000]],
        [81, ['а. Акции - Обыкновенные', 0, 500000000]],
        [82, ['б. Акции - Привилегированные', 0, 0]],
        [90, ['30. Итого собственного капитала', 0, 934971637]],
        [91, ['31. Итого обязательств и собственного капитала', 0, 5416243300]],
    ]
    if variant == 'different_dates':
        lines[2][1][1:] = ['На начало года', 'На конец периода']
    if variant == 'mixed_values':
        lines[3][1][2] = 123
    if variant == 'unbalanced':
        lines[-1][1][2] += 100
    if variant == 'wrong_period':
        lines[0][1][1] = '2025-12-31'
    if variant == 'one_column':
        for _, cells in lines[5:]:
            cells[1], cells[2] = cells[2], 0
    form = dict(source_url=url, source_coverage={'complete': True}, sheets=[dict(sheet='bank',
                source_rows=[dict(row=i, cells=cells) for i, cells in lines])])
    doc = dict(template='bank', quality='valid', scope='separate', issuer_id='9', period_end=end,
               source_version='1309', source_forms=[form], rows=nsbu.rows(form, template='bank'))
    data = observations.nsbu([doc])
    assets = {r['role']: r for r in data if r['metric_id'] == 'total_assets'}
    if variant == 'split':
        assert assets['PRIMARY']['value'] == '5416243300'
        assert assets['PRIMARY']['raw_cells'][1:] == [5416243300, 0]
        assert all(r['value'] is None for r in data if r['role'] == 'COMPARATIVE')
        assert next(r['value'] for r in data if r['metric_id'] == 'preferred_share_capital' and r['role'] == 'PRIMARY') == '0'
    else:
        assert assets['PRIMARY']['value'] in ('0', None)
