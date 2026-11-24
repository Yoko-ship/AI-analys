"""Match IFRS loan-note totals to the stages or impairment bridge they describe."""
from decimal import Decimal

from .periods import CONTEXT


def reconciled_gross(candidates, terms):
    """Find a filed gross total equal to the signed sum in the same reporting context."""
    parts = [row for row, _ in terms]
    missing = {'value': None, 'quality': 'missing', 'reason': 'LOAN_PORTFOLIO_INPUTS_MISSING'}
    blocked = {'value': None, 'quality': 'blocked', 'reason': 'LOAN_PORTFOLIO_MISMATCH',
               'components': [*parts, *candidates]}
    if any(row.get('quality') == 'blocked' for row in parts):
        return blocked
    if any(row.get('value') is None or row.get('quality') not in {'valid', 'warn'} for row in parts):
        return missing
    keys = (*CONTEXT, 'source_version', 'currency', 'unit', 'period_end')
    def context(row):
        return tuple(row.get(key) for key in keys)
    first = parts[0]
    amounts = [Decimal(row['value']) * sign for row, sign in terms]
    if (first.get('standard') != 'MSFO' or not all(first.get(key) for key in
            ('issuer_id', 'scope', 'source_version', 'currency', 'unit', 'period_end'))
            or any(row.get('kind') != 'stock' or context(row) != context(first) for row in parts)
            or any(value < 0 for value in amounts)):
        return blocked
    gross_total = sum(amounts)
    for gross in candidates:
        if (gross.get('kind') == 'stock' and gross.get('quality') in {'valid', 'warn'}
                and gross.get('value') is not None and context(gross) == context(first)
                and Decimal(gross['value']) == gross_total):
            warning = next((row for row in [gross, *parts] if row['quality'] == 'warn'), None)
            if warning:
                return {**gross, 'quality': 'warn', 'reason': warning.get('reason')}
            return gross
    return blocked if any(row.get('value') is not None or row.get('quality') == 'blocked'
                          for row in candidates) else missing
