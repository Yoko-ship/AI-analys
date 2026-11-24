from decimal import Decimal
import pytest

from financial_columns import matrix, ratios
import json
from pathlib import Path


def test_agmkp_comparative_balance_does_not_claim_an_annual_income_filing():
    rows = json.loads(Path('tests/fixtures/financial_columns/agmkp_comparative_balance.json').read_text(encoding='utf-8'))
    result = matrix.build(rows, mode='annual', recent=True)
    column = next(c for c in result['columns'] if c['key'] == '2025')
    assert column['notice'] == 'ANNUAL_INCOME_NOT_IMPORTED'
    assert column['balance_source'] == 'comparative'
    income = next(r for r in result['rows'] if r['metric_id'] == 'revenue')
    assert income['cells']['2025']['value'] is None
    assert income['cells']['2025']['reason'] == 'ANNUAL_INCOME_NOT_IMPORTED'
    balance = next(r for r in result['rows'] if r['metric_id'] == 'ppe')
    assert balance['cells']['2025']['value'] == '13358866945'
    # A genuinely filed flow, including an explicit zero, removes the notice.
    rows.append(observation('revenue', 0, '2025-12-31', 'flow', source_code='010'))
    complete = matrix.build(rows, mode='annual', recent=True)
    assert 'notice' not in next(c for c in complete['columns'] if c['key'] == '2025')


def observation(metric, value, end, kind='stock', **extra):
    return {'metric_id': metric, 'value': str(value), 'quality': 'valid', 'period_end': end,
            'period_start': end if kind == 'stock' else end[:4] + '-01-01', 'kind': kind,
            'standard': 'NSBU', 'scope': 'separate', 'issuer_id': 'org',
            'source_form': 'F1' if kind == 'stock' else 'F2', 'source_code': metric,
            'raw_label': metric, 'raw_value': str(value), 'unit': 'UZS_thousand',
            'source_version': 'source:' + end, 'source_url': 'https://openinfo.uz/report', **extra}


def data():
    return [observation('net_income', v, d, 'flow') for d, v in [
        ('2024-06-30', 30), ('2024-12-31', 100), ('2025-03-31', 20), ('2025-06-30', 50)]] + [
        observation('total_assets', 500, '2024-06-30'), observation('total_assets', 600, '2024-12-31'),
        observation('total_assets', 700, '2025-06-30')]


def test_recent_annual_view_shows_two_completed_years_and_latest_ytd_together():
    inputs = data() + [observation('total_assets', 400, '2023-12-31'),
                       observation('total_assets', 300, '2022-12-31')]
    result = matrix.build(inputs, mode='annual', recent=True)
    assert [(c['label'], c['basis']) for c in result['columns']] == [
        ('2023', 'annual'), ('2024', 'annual'), ('2025 · 6M', 'ytd')]
    current = result['columns'][-1]['key']
    profit = next(r for r in result['rows'] if r['metric_id'] == 'net_income')
    assets = next(r for r in result['rows'] if r['metric_id'] == 'total_assets')
    assert profit['cells'][current]['value'] == '50'  # Filed YTD, neither Q2 nor TTM.
    assert assets['cells'][current]['value'] == '700'
    assert profit['cells'][current]['source_version'] == 'source:2025-06-30'
    assert profit['cells']['2023']['value'] is None
    assert '2022' not in assets['cells']
    assert any(c['basis'] == 'ttm' for c in matrix.build(inputs, mode='annual')['columns'])
    for mode in ('quarter', 'interim'):
        assert matrix.build(inputs, mode=mode, recent=True) == matrix.build(inputs, mode=mode)


def test_recent_view_does_not_invent_a_current_period_or_duplicate_annual_report():
    annual = [observation('total_assets', 100, f'{year}-12-31') for year in (2022, 2023, 2024)]
    assert [c['label'] for c in matrix.build(annual, mode='annual', recent=True)['columns']] == ['2023', '2024']
    assert matrix.build([], mode='annual', recent=True) == {'columns': [], 'rows': []}
    current = [observation('total_assets', 100, '2026-03-31')]
    assert [c['label'] for c in matrix.build(current, mode='annual', recent=True)['columns']] == ['2026 · 3M']


def test_matrix_has_distinct_latest_stock_date_and_flow_ttm():
    result = matrix.build(data(), mode='annual')
    assert [(c['key'], c['basis']) for c in result['columns']] == [
        ('2024', 'annual'), ('asof:2025-06-30', 'as_of'), ('ttm:2025-06-30', 'ttm')]
    profit = next(r for r in result['rows'] if r['metric_id'] == 'net_income')
    assets = next(r for r in result['rows'] if r['metric_id'] == 'total_assets')
    assert profit['cells']['ttm:2025-06-30']['value'] == '120'
    assert profit['cells']['asof:2025-06-30']['quality'] == 'not_applicable'
    assert assets['cells']['asof:2025-06-30']['value'] == '700'
    assert assets['cells']['ttm:2025-06-30']['quality'] == 'not_applicable'
    assert next(c for c in matrix.build(data(), mode='interim')['columns'] if c['key'] == '2025-06-30')['basis'] == 'ytd'


def test_bilingual_aliases_do_not_duplicate_or_add_values_and_conflicts_are_visible():
    rows = [observation('total_assets', 500, '2024-12-31', source_form='BS', source_code=None, standard='MSFO', raw_label='Total assets'),
            observation('total_assets', 500, '2024-12-31', source_form='BS', source_code=None, standard='MSFO', raw_label='Итого активы')]
    result = matrix.build(rows, mode='annual')
    assert len(result['rows']) == 1
    cell = result['rows'][0]['cells']['2024']
    assert cell['value'] == '500'
    assert len(cell['aliases']) == 2
    rows[1]['value'] = '600'
    assert matrix.build(rows, mode='annual')['rows'][0]['cells']['2024']['quality'] == 'blocked'


def test_standalone_and_ytd_columns_with_the_same_end_date_stay_distinct():
    rows = data() + [observation('net_income', 30, '2025-06-30', 'flow', period_start='2025-04-01')]
    q = next(r for r in matrix.build(rows, mode='quarter')['rows'] if r['metric_id'] == 'net_income')
    ytd = next(r for r in matrix.build(rows, mode='interim')['rows'] if r['metric_id'] == 'net_income')
    assert q['cells']['2025-06-30']['value'] == '30'
    assert ytd['cells']['2025-06-30']['value'] == '50'


@pytest.mark.parametrize(('ticker', 'end', 'basis', 'values', 'expected', 'reason'), [
    ('ABKZ', '2025-12-31', 'annual', (142434170, -114078960, 28355210, -18645393), '19.91', None),
    ('ABKZ', '2025-12-31', 'ttm', (142434170, -114078960, 28355210, -18645393), '19.91', None),
    ('CBSK', '2026-09-30', 'ytd', (74357988, 0, 74357988, -33420351), None, 'GROSS_MARGIN_NO_COST_OF_SALES'),
])
def test_nsbu_gross_margin_uses_filed_profit_and_revenue(ticker, end, basis, values, expected, reason):
    metrics = ('revenue', 'cost_of_sales', 'gross_profit', 'operating_expenses')
    rows = [observation(m, v, end, 'flow', source_code=f'{i * 10:03d}')
            for i, (m, v) in enumerate(zip(metrics, values), start=1)]
    calculated = ratios.calculate(rows, ticker=ticker, template='industry', end=end, basis=basis)
    margin = next(r for r in calculated if r['metric_id'] == 'gross_margin')
    assert margin['reason'] == reason
    assert margin['annualized'] is False and margin['unit'] == 'percent'
    assert [r['source_code'] for r in margin['components'][:2]] == ['030', '010']
    if expected is None:
        assert margin['value'] is None
    else:
        assert Decimal(margin['value']).quantize(Decimal('.01')) == Decimal(expected)


def test_financial_issuer_with_an_enterprise_form_gets_the_sector_exclusion():
    # DMMT2B submitted Form 2 for 2025 under the financial organization classification.
    rows = [observation('revenue', '139881115.28', '2025-12-31', 'flow'),
            observation('gross_profit', '0', '2025-12-31', 'flow')]
    result = ratios.calculate(rows, ticker='DMMT2B', template='financial', end='2025-12-31', basis='annual')
    margin = next(r for r in result if r['metric_id'] == 'gross_margin')
    assert margin['value'] is None and margin['quality'] == 'not_applicable'


def test_roe_roa_use_matching_average_bases_and_nim_never_uses_total_assets():
    inputs = data() + [observation('total_equity', 200, '2023-12-31'),
                       observation('total_equity', 300, '2024-12-31'),
                       observation('net_interest_before_ecl', 40, '2024-12-31', 'flow')]
    result = ratios.calculate(inputs, ticker='HMKB', template='bank', end='2024-12-31', basis='annual')
    keyed = {r['metric_id']: r for r in result}
    assert keyed['roe']['value'] == '40.0'
    assert len(keyed['roe']['components']) == 3
    assert keyed['nim']['value'] is None
    assert keyed['nim']['reason'] == 'AVERAGE_EARNING_ASSETS_MISSING'
    assert keyed['current_ratio']['quality'] == 'not_applicable'
    assert 'nav_per_share' not in keyed


def test_nav_restricted_to_uznf_and_nonpositive_denominators_blocked():
    inputs = [observation('total_equity', 100, '2024-12-31'),
              observation('ordinary_shares', 10, '2024-12-31', unit='shares')]
    assert not any(r['metric_id'] == 'nav_per_share' for r in ratios.calculate(inputs, ticker='ODMP', template='fund', end='2024-12-31', basis='annual'))
    nav = next(r for r in ratios.calculate(inputs, ticker='UZNF', template='fund', end='2024-12-31', basis='annual') if r['metric_id'] == 'nav_per_share')
    assert nav['value'] == '10000'
    assert nav['unit'] == 'UZS_per_share'
    inputs[1]['value'] = '0'
    nav = next(r for r in ratios.calculate(inputs, ticker='UZNF', template='fund', end='2024-12-31', basis='annual') if r['metric_id'] == 'nav_per_share')
    assert nav['quality'] == 'blocked'


def test_nonbank_has_no_bank_ratios_and_stock_ratios_never_use_ttm():
    inputs = [observation('total_assets', 100, '2025-06-30'),
              observation('total_liabilities', 60, '2025-06-30')]
    result = ratios.calculate(inputs, ticker='URTS', template='financial', end='2025-06-30', basis='ttm')
    assert not {'nim', 'cir', 'cost_of_risk'} & {r['metric_id'] for r in result}
    debt = next(r for r in result if r['metric_id'] == 'liabilities_to_assets')
    assert debt['quality'] == 'not_applicable'
    assert debt['value'] is None


def test_nsbu_bank_cir_uses_income_before_credit_losses_and_positive_costs():
    inputs = [observation(k, v, '2025-12-31', 'flow', source_form='BANK_PL') for k, v in
              [('net_interest_before_ecl', 100), ('noninterest_income', 40),
               ('noninterest_expense', 10), ('operating_expenses', 65), ('credit_loss_expense', 80)]]
    result = ratios.calculate(inputs, ticker='ALKB', template='bank', end='2025-12-31', basis='annual')
    cir = next(r for r in result if r['metric_id'] == 'cir')
    assert cir['value'] == '50.0'
    assert cir['components'][1]['formula'] == 'net_interest_before_ecl + noninterest_income - noninterest_expense'
    assert len(cir['components'][1]['components']) == 3


def test_nsbu_interest_debt_does_not_include_trade_payables_or_double_count_totals():
    from financial_columns import derived
    inputs = [observation(k, v, '2025-12-31') for k, v in
              [('bank_borrowings_long', 100), ('other_borrowings_long', 20),
               ('bank_borrowings_short', 30), ('other_borrowings_short', 40),
               ('current_portion_long_term_debt', 10), ('total_liabilities', 900), ('trade_payables', 700)]]
    debt = next(r for r in derived.enrich(inputs) if r['metric_id'] == 'interest_bearing_debt')
    assert debt['value'] == '200'
    assert len(debt['components']) == 5
    assert not any(r['metric_id'] == 'interest_bearing_debt' for r in derived.enrich(inputs[1:]))


def test_old_insurance_policy_does_not_block_ratios_using_only_new_policy_inputs():
    inputs = [observation('total_equity', 100, '2022-12-31', accounting_model='legacy'),
              observation('total_equity', 200, '2023-12-31', accounting_model='IFRS17'),
              observation('total_equity', 300, '2024-12-31', accounting_model='IFRS17'),
              observation('net_income', 50, '2024-12-31', 'flow', accounting_model='IFRS17')]
    result = ratios.calculate(inputs, ticker='UZIN', template='insurance', end='2024-12-31', basis='annual')
    assert next(r for r in result if r['metric_id'] == 'roe')['value'] == '20.0'
    assert next(r for r in result if r['metric_id'] == 'loss_ratio')['quality'] == 'not_applicable'


def test_source_subtotals_flag_conflicts_without_replacing_reported_amounts():
    from financial_columns.observations import check
    inputs = [observation(k, v, '2025-12-31') for k, v in
              [('insurance_reserves_gross', '728597206.3'), ('reinsurer_share_reserves', '469160235.8'),
               ('insurance_reserves_net', '259436970.5')]]
    assert check(inputs) == []
    inputs[-1]['value'] = '259436980.5'
    issues = check(inputs)
    assert issues[0]['code'] == 'SOURCE_RESERVE_MISMATCH'
    assert inputs[-1]['value'] == '259436980.5'
    assert inputs[-1]['raw_value'] == '259436970.5'
    assert inputs[-1]['quality'] == 'warn'


def test_reported_quarter_disagreement_with_complete_ytd_history_is_visible():
    inputs = data() + [observation('net_income', 40, '2025-06-30', 'flow', period_start='2025-04-01')]
    row = next(r for r in matrix.build(inputs, mode='quarter')['rows'] if r['metric_id'] == 'net_income')
    assert row['cells']['2025-06-30']['quality'] == 'blocked'
    assert row['cells']['2025-06-30']['reason'] == 'REPORTED_DERIVED_PERIOD_CONFLICT'


def test_combined_ratio_requires_explicit_nonoverlapping_expenses_and_legacy_policy():
    inputs = [observation(k, v, '2025-12-31', 'flow', accounting_model='legacy') for k, v in
              [('net_earned_premiums', 100), ('net_incurred_claims', 40), ('insurance_expense_nonoverlap', 20)]]
    result = ratios.calculate(inputs, ticker='UZIN', template='insurance', end='2025-12-31', basis='annual')
    combined = next(r for r in result if r['metric_id'] == 'combined_ratio')
    assert combined['value'] == '60.0'
    for r in inputs:
        r['accounting_model'] = 'IFRS17'
    result = ratios.calculate(inputs, ticker='UZIN', template='insurance', end='2025-12-31', basis='annual')
    assert next(r for r in result if r['metric_id'] == 'combined_ratio')['quality'] == 'not_applicable'


@pytest.mark.parametrize(('cost', 'version', 'expected'), [
    (-35914487, 'filing:6121', '17.73'),
    (-35914470, 'filing:6121', None),
    (-35914487, 'different filing', None),
])
def test_btrl_gross_margin_reconciles_its_inputs_independently_of_operating_income(cost, version, expected):
    end = '2025-12-31'
    def line(metric, code, value, **extra):
        return observation(metric, value, end, 'flow', source_code=code,
                           **({'source_version': 'filing:6121'} | extra))
    issue = {'code': 'SOURCE_OPERATING_PROFIT_MISMATCH', 'metric_id': 'operating_income',
             'severity': 'blocked', 'difference': '6711695', 'source_version': 'filing:6121'}
    gross = line('gross_profit', '030', 7741905, quality='blocked', reason=issue['code'],
                 reconciliation_issues=[issue])
    inputs = [line('revenue', '010', 43656392), line('cost_of_sales', '020', cost, source_version=version), gross]
    results = ratios.calculate(inputs, ticker='BTRL', template='industry', end=end, basis='annual')
    margin = next(r for r in results if r['metric_id'] == 'gross_margin')
    assert gross['quality'] == 'blocked'
    if expected:
        assert Decimal(margin['value']).quantize(Decimal('.01')) == Decimal(expected)
        assert margin['quality'] == 'warn' and margin['reason'] == issue['code']
        assert margin['components'][0]['reconciliation_issues'] == [issue]
    else:
        assert margin['value'] is None and margin['quality'] == 'blocked'


@pytest.mark.parametrize(('metric', 'form', 'prior', 'following'), [
    ('cash_begin', 'CF', '263360459', '530920046'),
    ('equity_open', 'Equity', '277920154', '495249840'),
])
def test_grbk_opening_balances_use_the_statement_year_and_keep_the_source_date(metric, form, prior, following):
    # Openinfo bank annual 25104, pages 3–4. Openings are dated at the prior close.
    rows = [
        observation(metric, value, date, standard='MSFO', scope='consolidated', issuer_id='11',
                    source_form=form, statement_period_end=end, role=role)
        for value, date, end, role in [
            (prior, '2023-12-31', '2024-12-31', 'COMPARATIVE'),
            (following, '2024-12-31', '2025-12-31', 'PRIMARY'),
        ]
    ]
    annual = matrix.build(rows, mode='annual')
    assert [col['key'] for col in annual['columns']] == ['2024', '2025']
    cells = annual['rows'][0]['cells']
    assert [(cells[y]['value'], cells[y]['period_end']) for y in ('2024', '2025')] == [
        (prior, '2023-12-31'), (following, '2024-12-31')]
    quarters = matrix.build(rows, mode='quarter')
    assert all(c.get('value') is None for c in quarters['rows'][0]['cells'].values())
    quarter_open = {**rows[0], 'value': '123', 'period_end': '2024-09-30', 'statement_period_end': '2024-12-31'}
    annual = matrix.build(rows + [quarter_open], mode='annual')
    assert annual['rows'][0]['cells']['2024']['value'] == prior
    quarterly = matrix.build(rows + [quarter_open], mode='quarter')
    assert quarterly['rows'][0]['cells']['2024-12-31']['period_end'] == '2024-09-30'


@pytest.fixture
def sqbn_loan_note():
    path = Path('tests/fixtures/financial_columns/sqbn_2025_loan_note.json')
    return json.loads(path.read_text())


def sqbn_risk_ratios(rows, basis='annual'):
    return {r['metric_id']: r for r in ratios.calculate(rows, ticker='SQBN', template='bank',
                                                        end='2025-12-31', basis=basis)}


def test_sqbn_loan_quality_ratios_reconcile_to_signed_stage_and_net_balances(sqbn_loan_note):
    result = sqbn_risk_ratios(sqbn_loan_note)
    for key, amount in [('stage3_to_gross_loans', 5310186), ('ecl_coverage', 4250886)]:
        cell = result[key]
        assert Decimal(cell['value']) == Decimal(amount) / 71008798 * 100
        assert (cell['quality'], cell['unit'], cell['period_start']) == ('valid', 'percent', '2025-12-31')
        assert all(c['source_version'] == sqbn_loan_note[0]['source_version'] for c in cell['components'])
        assert sqbn_risk_ratios(sqbn_loan_note, 'ttm')[key]['value'] is None
    deduction = next(c for c in result['ecl_coverage']['components'] if c['metric_id'] == 'loan_loss_allowance_deduction')
    assert deduction['value'] == '-4250886000'


@pytest.mark.parametrize(('metric', 'change', 'ratio_key'), [
    ('stage2_loans', {'value': '25320439000'}, 'stage3_to_gross_loans'),
    ('stage2_loans', {'quality': 'blocked'}, 'stage3_to_gross_loans'),
    ('stage1_loans', {'scope': 'separate'}, 'stage3_to_gross_loans'),
    ('stage3_loans', {'source_version': 'other-report'}, 'stage3_to_gross_loans'),
    ('stage2_loans', {'currency': 'USD'}, 'stage3_to_gross_loans'),
    ('stage1_loans', {'period_end': '2024-12-31'}, 'stage3_to_gross_loans'),
    ('loans_net', {'value': '66757913000'}, 'ecl_coverage'),
    ('loan_loss_allowance_deduction', {'value': '4250886000'}, 'ecl_coverage'),
    ('loans_net', {'unit': 'UZS_million'}, 'ecl_coverage'),
])
def test_unreconciled_or_mixed_loan_portfolios_have_no_ratio(sqbn_loan_note, metric, change, ratio_key):
    rows = [{**r, **change} if r['metric_id'] == metric else r for r in sqbn_loan_note]
    assert sqbn_risk_ratios(rows)[ratio_key]['value'] is None


def test_anor_stage_ratio_uses_the_total_in_the_staging_table(sqbn_loan_note):
    # Anor's FY2024 risk table and amortised-cost note differ by one thousand UZS.
    source = dict(sqbn_loan_note[0], issuer_id='837', source_version='anor-2025', page=43,
                  source_url='https://openinfo.uz/media/int_report/34cddf83-0a60-436b-be9b-6452431c88bf.pdf',
                  period_start='2024-12-31', period_end='2024-12-31', source_form='Notes')
    values = {'stage1_loans': 6581204690, 'stage2_loans': 257972270, 'stage3_loans': 202964330,
              'staged_loans_gross': 7042141290, 'loans_gross': 7042141291}
    rows = [dict(source, metric_id=key, value=str(value)) for key, value in values.items()]
    result = ratios.calculate(rows, ticker='ANBK3B', template='bank', end='2024-12-31', basis='annual')
    stage = next(r for r in result if r['metric_id'] == 'stage3_to_gross_loans')
    assert Decimal(stage['value']) == Decimal(202964330) / 7042141290 * 100
    assert stage['components'][1]['metric_id'] == 'staged_loans_gross'


def test_a_reported_staging_total_governs_its_table_and_can_reconcile_the_deduction(sqbn_loan_note):
    gross = next(r for r in sqbn_loan_note if r['metric_id'] == 'loans_and_finance_leases_gross')
    staged = dict(gross, metric_id='staged_loans_gross')
    partial = [r for r in sqbn_loan_note if r is not gross]
    assert sqbn_risk_ratios([*partial, staged])['ecl_coverage']['value'] is not None
    bad_total = dict(staged, value=str(Decimal(staged['value']) + 1000))
    assert sqbn_risk_ratios([*sqbn_loan_note, bad_total])['stage3_to_gross_loans']['value'] is None
