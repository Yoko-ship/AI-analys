"""Exact period algebra with explicit coverage and source components."""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

CONTEXT = ('issuer_id', 'standard', 'scope', 'accounting_model')


def calculate(observations, end, mode):
    if mode not in {'quarter', 'ttm'}:
        raise ValueError('Unknown period calculation')
    boundary = date.fromisoformat(end)
    current = [r for r in observations if r['period_end'] == end]
    empty = {'period_end': end, 'value': None, 'quality': 'missing', 'reason': 'PERIOD_COVERAGE_MISSING', 'components': []}
    if not current:
        return empty
    anchor = current[0]
    if boundary.month not in {3, 6, 9, 12} or boundary.day != monthrange(boundary.year, boundary.month)[1]:
        return {**empty, 'quality': 'blocked', 'reason': 'PERIOD_BOUNDARY_UNRESOLVED'}
    same = [r for r in observations if all(r.get(k) == anchor.get(k) for k in CONTEXT)]
    year = boundary.year
    if mode == 'quarter' and anchor['kind'] != 'stock':
        quarter_start = date(year, boundary.month - 2, 1).isoformat()
        direct = [r for r in same if r['period_end'] == end and r.get('period_start') == quarter_start]
        if direct:
            if len({(r.get('value'), r.get('quality')) for r in direct}) > 1:
                return {**empty, 'quality': 'blocked', 'reason': 'CONFLICTING_SOURCE_VERSIONS', 'components': direct}
            if anchor['kind'] == 'flow' and boundary.month > 3:
                # Compare an explicitly reported quarter with independently
                # complete YTD arithmetic, never hide a source disagreement.
                other = [r for r in same if r not in direct]
                derived = calculate(other, end, mode)
                if (derived.get('value') is not None and direct[0].get('value') is not None
                        and Decimal(derived['value']) != Decimal(direct[0]['value'])):
                    return {**empty, 'quality': 'blocked', 'reason': 'REPORTED_DERIVED_PERIOD_CONFLICT',
                            'components': [direct[0], derived]}
            return {**direct[0], 'basis': 'reported_quarter', 'components': [direct[0]], 'formula': 'Reported standalone quarter'}
    if anchor['kind'] != 'flow':
        return {**empty, 'quality': 'not_applicable', 'reason': 'STOCK_IS_AS_OF_DATE' if anchor['kind'] == 'stock' else 'PER_SHARE_IS_NOT_ADDITIVE'}
    terms = [(f'{year}-01-01', end, 1)]
    if mode == 'quarter':
        start = date(year, boundary.month - 2, 1)
        if boundary.month > 3:
            terms.append((f'{year}-01-01', (start - timedelta(days=1)).isoformat(), -1))
    elif boundary.month == 12:
        start = date(year, 1, 1)
    else:
        start = date(year - 1, boundary.month + 1, 1)
        terms += [(f'{year-1}-01-01', f'{year-1}-12-31', 1),
                  (f'{year-1}-01-01', f'{year-1}{end[4:]}', -1)]
    inputs = []
    for period_start, period_end, coefficient in terms:
        candidates = [r for r in same if r.get('period_start') == period_start and r['period_end'] == period_end]
        if not candidates:
            return {**empty, 'components': inputs}
        if len({(r.get('value'), r.get('quality')) for r in candidates}) > 1:
            return {**empty, 'quality': 'blocked', 'reason': 'CONFLICTING_SOURCE_VERSIONS', 'components': candidates}
        item = candidates[0]
        if item.get('quality') not in {'valid', 'warn'} or item.get('value') is None:
            return {**empty, 'quality': item.get('quality', 'missing'), 'components': inputs + [item]}
        inputs.append({**item, 'coefficient': coefficient})
    value = sum(Decimal(r['value']) * r['coefficient'] for r in inputs)
    return {**anchor, 'period_start': start.isoformat(), 'value': str(value),
            'quality': 'warn' if any(r['quality'] == 'warn' for r in inputs) else 'valid',
            'basis': mode, 'formula': ' + '.join(f"({r['coefficient']} × {r['period_start']}…{r['period_end']})" for r in inputs),
            'components': inputs}
