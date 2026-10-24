"""Explicit source-form arithmetic, retaining every input and its provenance."""
from collections import defaultdict
from decimal import Decimal

from .matrix import choose
from .periods import CONTEXT


def enrich(observations):
    result = list(observations)
    groups = defaultdict(list)
    for row in observations:
        groups[tuple(row.get(k) for k in (*CONTEXT, 'source_version', 'period_start', 'period_end', 'kind'))].append(row)
    for rows in groups.values():
        standard = rows[0].get('standard')
        forms = {r.get('source_form') for r in rows}

        def add(metric, label, terms, formula, unit='UZS_thousand'):
            if any(r.get('metric_id') == metric for r in rows):
                return
            parts = [choose([r for r in rows if r.get('metric_id') == field]) for field, _ in terms]
            if any(p.get('value') is None or p.get('quality') not in {'valid', 'warn'} for p in parts):
                return
            result.append({**parts[0], 'metric_id': metric, 'raw_label': label,
                           'source_form': 'DERIVED', 'source_code': None, 'raw_value': None,
                           'value': str(sum(Decimal(p['value']) * coefficient for p, (_, coefficient) in zip(parts, terms))),
                           'components': parts, 'formula': formula, 'origin': 'UZStock_calculated',
                           'unit': unit, 'quality': 'warn' if any(p['quality'] == 'warn' for p in parts) else 'valid'})

        if standard == 'NSBU' and 'F1' in forms:
            fields = ['bank_borrowings_long', 'other_borrowings_long', 'bank_borrowings_short',
                      'other_borrowings_short', 'current_portion_long_term_debt']
            add('interest_bearing_debt', 'Interest-bearing debt', [(k, 1) for k in fields],
                'F1:570 + F1:580 + F1:730 + F1:740 + F1:750')
        if standard == 'NSBU' and 'BANK_PL' in forms:
            add('operating_income_before_ecl', 'Operating income before credit losses',
                [('net_interest_before_ecl', 1), ('noninterest_income', 1), ('noninterest_expense', -1)],
                'net_interest_before_ecl + noninterest_income - noninterest_expense')
            add('operating_costs_positive', 'Operating costs', [('operating_expenses', 1)], 'BANK_PL operating expenses')
        if standard == 'NSBU' and 'F2' in forms:
            add('interest_cost_positive', 'Interest costs', [('interest_expense', -1)], '- F2:180 expense column')
        if standard == 'NSBU' and 'INSURANCE_BS' in forms:
            add('total_liabilities', 'Liabilities including net insurance reserves',
                [('nonreserve_liabilities', 1), ('insurance_reserves_net', 1)], 'INSURANCE_BS:1190 + INSURANCE_BS:720')
        if standard == 'NSBU' and 'INSURANCE_PL' in forms:
            add('net_earned_premiums', 'Net earned premiums',
                [('direct_premiums', 1), ('ceded_premiums', 1), ('assumed_premiums', 1), ('change_upr_net', 1)],
                'INSURANCE_PL:011 + signed 012 + 013 + signed 014')
    return result
