"""Pre-tax return on average capital employed for one reporting horizon."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from .matrix import choose
from .periods import CONTEXT, calculate as period_value


LINES = {'operating_income': ('F2', '100'), 'total_assets': ('F1', '400'),
         'current_liabilities': ('F1', '600')}
FINANCIAL = {'bank', 'insurance', 'fund', 'financial', 'microfinance', 'leasing', 'microfinance_bank'}


def _filed_line(row):
    # This ratio explicitly uses the three published lines. A discrepancy
    # against a subtotal is evidence to show alongside the filed amount.
    # Holds, source conflicts and unresolved amounts keep their original block.
    if (row.get('standard') == 'NSBU' and row.get('quality') == 'blocked'
            and row.get('value') is not None and row.get('source_version') and row.get('source_url')
            and any(issue['code'] == row.get('reason') and issue.get('source_version') == row['source_version']
                    for issue in row.get('reconciliation_issues', []))):
        return {**row, 'quality': 'warn', 'source_quality': 'blocked'}
    return row


def _capital(rows, at, preferred_version=None):
    # Pair the two balances from the same statement, including when the opening
    # balance was restated in the current filing.
    groups = defaultdict(list)
    for row in rows:
        if row['period_end'] == at and row['metric_id'] != 'operating_income':
            groups[tuple(row.get(k) for k in (*CONTEXT, 'source_version', 'role'))].append(row)
    pairs = []
    for group in groups.values():
        assets, current = (choose([r for r in group if r['metric_id'] == metric])
                           for metric in ('total_assets', 'current_liabilities'))
        base = group[0]
        parts = [assets, current]
        usable = all(r.get('value') is not None and r['quality'] in {'valid', 'warn'} for r in parts)
        quality = next((q for q in ('blocked', 'missing', 'not_applicable', 'warn')
                        if any(r['quality'] == q for r in parts)), 'valid')
        pairs.append({**base, 'metric_id': 'capital_employed', 'raw_label': 'Capital employed',
                      'source_code': None, 'source_form': 'DERIVED', 'raw_value': None,
                      'formula': 'total_assets − current_liabilities', 'components': parts,
                      'quality': quality, 'reason': next((r.get('reason') for r in parts if r.get('reason')), None),
                      'value': str(Decimal(assets['value']) - Decimal(current['value'])) if usable else None})
    preferred = [r for r in pairs if preferred_version and r.get('source_version') == preferred_version]
    return choose(preferred or pairs)


def roce(rows, *, template, end, basis):
    year = int(end[:4])
    boundary = date.fromisoformat(end)
    if basis == 'quarter':
        opening = (boundary.replace(month=boundary.month - 2, day=1) - timedelta(days=1)).isoformat()
    elif basis == 'ttm':
        opening = f'{year-1}{end[4:]}'
    else:
        opening = f'{year-1}-12-31'
    selected = [_filed_line(r) for r in rows if r.get('metric_id') in LINES and r.get('unit') == 'UZS_thousand'
                and (r.get('standard') != 'NSBU' or
                     (r.get('source_form'), r.get('source_code')) == LINES[r['metric_id']])]
    flows = defaultdict(list)
    for row in selected:
        if row['metric_id'] == 'operating_income':
            flows[(row['period_start'], row['period_end'])].append(row)
    filed = choose(flows.get((f'{year}-01-01', end), []))
    if basis in {'quarter', 'ttm'}:
        profit = period_value([choose(items) for items in flows.values()], end, basis)
    else:
        profit = filed
    opening_version = filed.get('source_version') if opening.endswith('-12-31') and opening[:4] == str(year-1) else None
    capitals = [_capital(selected, opening, opening_version), _capital(selected, end, filed.get('source_version'))]
    operands = [profit, *capitals]
    contexts = {tuple(r.get(k) for k in CONTEXT) for r in operands if r.get('issuer_id')}
    value, reason, quality = None, None, 'valid'
    if template in FINANCIAL:
        quality, reason = 'not_applicable', 'SECTOR_OR_ACCOUNTING_MODEL_NOT_APPLICABLE'
    elif basis == 'as_of':
        quality, reason = 'not_applicable', 'FLOW_NEEDS_PERIOD'
    elif len(contexts) > 1 or any(r.get('quality') == 'blocked' for r in operands):
        quality, reason = 'blocked', 'INCOMPATIBLE_OR_BLOCKED_INPUTS'
    elif any(r.get('value') is None or r.get('quality') not in {'valid', 'warn'} for r in operands):
        quality, reason = 'missing', 'ROCE_INPUTS_MISSING'
    elif any(Decimal(r['value']) <= 0 for r in capitals):
        quality, reason = 'blocked', 'NON_POSITIVE_CAPITAL_EMPLOYED'
    else:
        average = sum(Decimal(r['value']) for r in capitals) / 2
        value = str(Decimal(profit['value']) / average * 100)
        if warning := next((r for r in operands if r['quality'] == 'warn'), None):
            quality, reason = 'warn', warning.get('reason')
    return {'metric_id': 'roce', 'label': 'ROCE', 'unit': 'percent', 'value': value,
            'formula': 'operating_income / average(opening and closing total_assets − current_liabilities) × 100',
            'components': operands, 'period_start': (date.fromisoformat(opening) + timedelta(days=1)).isoformat(),
            'period_end': end, 'basis': basis, 'balance_basis': 'average_opening_closing',
            'annualized': False, 'quality': quality, 'reason': reason, 'origin': 'UZStock_calculated'}
