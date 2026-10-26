"""Independent ratios, with named bases, applicability and complete passports."""
from datetime import date, timedelta
from decimal import Decimal

from .matrix import choose
from .periods import calculate as period_value, CONTEXT
from .derived import enrich


def calculate(observations, *, ticker, template, end, basis):
    if basis not in {'annual', 'quarter', 'ttm', 'as_of', 'ytd'}:
        raise ValueError('Unknown ratio basis')
    observations = enrich(observations)
    year = int(end[:4])
    start = (f'{year-1}-12-31' if basis in {'annual', 'ytd'} else
             (date(year, int(end[5:7])-2, 1) - timedelta(days=1)).isoformat() if basis == 'quarter' else
             f'{year-1}{end[4:]}')
    months = int(end[5:7])
    annualization = Decimal(4) if basis == 'quarter' else Decimal(12)/months if basis == 'ytd' else Decimal(1)
    annualization_formula = ' × 4' if basis == 'quarter' else f' × 12 / {months}' if basis == 'ytd' else ''
    current_models = {r.get('accounting_model') for r in observations if r['period_end'] == end}
    result = []

    def point(field, at):
        return choose([r for r in observations if r['metric_id'] == field and r['period_end'] == at])

    def flow(field):
        data = [r for r in observations if r['metric_id'] == field]
        if basis in {'ttm', 'quarter'}:
            return period_value(data, end, basis)
        return choose([r for r in data if r['period_end'] == end and r.get('period_start') == f'{year}-01-01'])

    def ratio(metric_id, label, numerator, denominators, *, factor=Decimal(1), formula,
              applicable=True, reason='INPUTS_MISSING', unit='ratio', flow_ratio=False, annualize=False):
        # Flow/stock rates use a yearly rate; flow/flow ratios (e.g. CIR)
        # already compare the same period and must never be multiplied.
        if annualize:
            factor *= annualization
            formula += annualization_formula
        items = [numerator, *denominators]
        contexts = {tuple(r.get(k) for k in CONTEXT) for r in items if r.get('issuer_id')}
        context_ok = len(contexts) <= 1
        quality, why, value = 'valid', None, None
        if not applicable:
            quality, why = 'not_applicable', 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'
        elif not flow_ratio and basis == 'ttm':
            quality, why = 'not_applicable', 'STOCK_REQUIRES_REPORTING_DATE'
        elif flow_ratio and basis == 'as_of':
            quality, why = 'not_applicable', 'REQUIRES_FY_TTM_OR_ANNUALIZED_QUARTER'
        elif not context_ok or any(r.get('quality') == 'blocked' for r in items):
            quality, why = 'blocked', 'INCOMPATIBLE_OR_BLOCKED_INPUTS'
        elif any(r.get('value') is None or r.get('quality') not in {'valid', 'warn'} for r in items):
            quality, why = 'missing', reason
        else:
            denominator = sum(Decimal(r['value']) for r in denominators) / len(denominators)
            if denominator <= 0:
                quality, why = 'blocked', 'NONPOSITIVE_DENOMINATOR'
            else:
                value = str(Decimal(numerator['value']) / denominator * factor)
                if any(r['quality'] == 'warn' for r in items):
                    quality = 'warn'
        result.append({'metric_id': metric_id, 'label': label, 'value': value, 'quality': quality,
                       'reason': why, 'formula': formula, 'components': items, 'period_end': end,
                       'period_start': (date.fromisoformat(start) + timedelta(days=1)).isoformat() if flow_ratio else end,
                       'basis': basis, 'annualized': annualize and annualization != 1, 'unit': unit,
                       'origin': 'UZStock_calculated'})

    # Parent earnings pair only with parent equity; otherwise use total group
    # earnings and total group equity. Never mix one numerator with the other base.
    parent = flow('profit_owners').get('value') is not None and point('equity_owners', end).get('value') is not None
    profit_key, equity_key = ('profit_owners', 'equity_owners') if parent else ('net_income', 'total_equity')
    ratio('roe', 'ROE', flow(profit_key), [point(equity_key, start), point(equity_key, end)],
          factor=Decimal(100), formula=f'{profit_key} / average({equity_key}) × 100', unit='percent', flow_ratio=True, annualize=True)
    ratio('roa', 'ROA', flow('net_income'), [point('total_assets', start), point('total_assets', end)],
          factor=Decimal(100), formula='net_income / average(total_assets) × 100', unit='percent', flow_ratio=True, annualize=True)
    corporate = template not in {'bank', 'insurance', 'fund', 'financial', 'microfinance', 'leasing'}
    ratio('current_ratio', 'Current ratio', point('current_assets', end), [point('current_liabilities', end)],
          formula='current_assets / current_liabilities', applicable=corporate)
    quick = point('current_assets', end)
    deductions = [point(k, end) for k in ('inventory', 'prepaid_expenses')]
    quick_parts = [quick, *deductions]
    quick = {**quick, 'components': quick_parts, 'value': str(Decimal(quick['value']) - sum(Decimal(r['value']) for r in deductions))
             if all(r.get('value') is not None and r.get('quality') in {'valid', 'warn'} for r in quick_parts) else None}
    ratio('quick_ratio', 'Quick ratio', quick, [point('current_liabilities', end)],
          formula='(current_assets − inventory − prepaid_expenses) / current_liabilities', applicable=corporate)
    ratio('liabilities_to_assets', 'Liabilities / assets', point('total_liabilities', end), [point('total_assets', end)], formula='total_liabilities / total_assets')
    ratio('liabilities_to_equity', 'Liabilities / equity', point('total_liabilities', end), [point('total_equity', end)], formula='total_liabilities / total_equity')
    ratio('asset_turnover', 'Asset turnover', flow('revenue'), [point('total_assets', start), point('total_assets', end)],
          formula='revenue / average(total_assets)', applicable=corporate, flow_ratio=True, annualize=True)
    ratio('roce', 'ROCE', flow('nopat'), [point('invested_capital', start), point('invested_capital', end)],
          factor=Decimal(100), formula='NOPAT / average(invested capital) × 100',
          applicable=corporate, unit='percent', flow_ratio=True, annualize=True, reason='NOPAT_OR_INVESTED_CAPITAL_POLICY_MISSING')
    ratio('nim', 'NIM', flow('net_interest_before_ecl'), [point('earning_assets', start), point('earning_assets', end)],
          factor=Decimal(100), formula='net_interest_before_ecl / average(earning_assets) × 100',
          applicable=template == 'bank', unit='percent', flow_ratio=True, annualize=True, reason='AVERAGE_EARNING_ASSETS_MISSING')
    ratio('cir', 'CIR', flow('operating_costs_positive'), [flow('operating_income_before_ecl')], factor=Decimal(100),
          formula='operating costs / operating income before credit losses × 100', applicable=template == 'bank', unit='percent', flow_ratio=True)
    ratio('cost_of_risk', 'Cost of risk', flow('loan_credit_loss_cost'), [point('loans_gross', start), point('loans_gross', end)],
          factor=Decimal(100), formula='loan credit loss cost / average(gross loans) × 100', applicable=template == 'bank', unit='percent', flow_ratio=True, annualize=True)
    model = next(iter(current_models)) if len(current_models) == 1 else None
    ratio('loss_ratio', 'Loss ratio (legacy)', flow('net_incurred_claims'), [flow('net_earned_premiums')],
          factor=Decimal(100), formula='net incurred claims / net earned premiums × 100',
          applicable=template == 'insurance' and model == 'legacy', unit='percent', flow_ratio=True)
    claims, expenses = flow('net_incurred_claims'), flow('insurance_expense_nonoverlap')
    combined = {**claims, 'components': [claims, expenses], 'value': None}
    if all(p.get('value') is not None and p.get('quality') in {'valid', 'warn'} for p in (claims, expenses)):
        combined['value'] = str(Decimal(claims['value']) + Decimal(expenses['value']))
        combined['quality'] = 'warn' if any(p['quality'] == 'warn' for p in (claims, expenses)) else 'valid'
    ratio('combined_ratio', 'Combined ratio (legacy)', combined, [flow('net_earned_premiums')],
          factor=Decimal(100), formula='(net incurred claims + expenses explicitly excluding claims) / net earned premiums × 100',
          applicable=template == 'insurance' and model == 'legacy', unit='percent', flow_ratio=True,
          reason='NONOVERLAPPING_INSURANCE_EXPENSES_MISSING')
    ratio('funding_cost', 'Funding cost', flow('interest_cost_positive'), [point('interest_bearing_debt', start), point('interest_bearing_debt', end)],
          factor=Decimal(100), formula='interest expense / average(interest-bearing debt) × 100',
          applicable=template == 'leasing', unit='percent', flow_ratio=True, annualize=True)
    ratio('ecl_coverage', 'ECL coverage', point('loan_ecl_allowance', end), [point('loans_gross', end)], factor=Decimal(100),
          formula='loan ECL allowance / gross loans of the same perimeter × 100', applicable=template in {'bank', 'leasing'}, unit='percent')
    if ticker.upper() == 'UZNF':
        ratio('nav_per_share', 'NAV / share', point('total_equity', end), [point('ordinary_shares', end)],
              factor=Decimal(1000), formula='net assets in thousands UZS × 1000 / verified ordinary shares outstanding', unit='UZS_per_share')
    bank_only = {'nim', 'cir', 'cost_of_risk'}
    return [r for r in result if template == 'bank' or r['metric_id'] not in bank_only]
