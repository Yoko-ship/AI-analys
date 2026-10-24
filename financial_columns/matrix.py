"""A date-aware matrix; presentation never manufactures missing observations."""
from collections import defaultdict

from . import periods


def choose(items):
    if not items:
        return {'value': None, 'quality': 'missing', 'reason': 'SOURCE_VALUE_MISSING'}
    # A directly filed period takes precedence over a later comparison column.
    primary = [r for r in items if r.get('role') != 'COMPARATIVE']
    items = primary or items
    signatures = {(r.get('value'), r.get('quality'), *(r.get(k) for k in periods.CONTEXT)) for r in items}
    if len(signatures) > 1:
        return {**items[0], 'value': None, 'quality': 'blocked', 'reason': 'CONFLICTING_SOURCE_VALUES', 'components': items}
    return {**items[0], 'aliases': list(dict.fromkeys(r['raw_label'] for r in items)),
            'sources': [{k: r.get(k) for k in ('source_version', 'source_url', 'page', 'sheet', 'row', 'raw_label')} for r in items]}


def build(observations, *, mode, recent=False):
    if mode not in {'annual', 'quarter', 'interim'}:
        raise ValueError('Unknown frequency')
    ends = sorted({r['period_end'] for r in observations})
    if mode == 'annual':
        columns = [{'key': end[:4], 'label': end[:4], 'end': end, 'basis': 'annual'} for end in ends if end.endswith('-12-31')]
        if recent:
            columns = columns[-2:]
        if ends and not ends[-1].endswith('-12-31'):
            latest = ends[-1]
            if recent:
                # One filed current-period column: stocks at the reporting date,
                # flows from January through that date (not a rolling-year estimate).
                columns.append({'key': latest, 'label': f'{latest[:4]} · {int(latest[5:7])}M',
                                'end': latest, 'basis': 'ytd'})
            else:
                columns += [{'key': 'asof:' + latest, 'label': latest, 'end': latest, 'basis': 'as_of'},
                            {'key': 'ttm:' + latest, 'label': 'TTM · ' + latest, 'end': latest, 'basis': 'ttm'}]
    else:
        columns = [{'key': end, 'label': (end[:4] + ' Q' + str(int(end[5:7]) // 3)) if mode == 'quarter' else end,
                    'end': end, 'basis': 'quarter' if mode == 'quarter' else 'ytd'} for end in ends
                   if mode == 'quarter' or end[5:] in {'06-30', '09-30'}]
    for column in columns:
        if column['basis'] != 'annual':
            continue
        dated = [r for r in observations if r['period_end'] == column['end']]
        stocks = [r for r in dated if r['kind'] == 'stock']
        annual_flows = [r for r in dated if r['kind'] == 'flow' and r.get('period_start') == column['end'][:4] + '-01-01']
        if stocks and not annual_flows:
            column['notice'] = 'ANNUAL_INCOME_NOT_IMPORTED'
            if all(r.get('role') == 'COMPARATIVE' for r in stocks):
                column['balance_source'] = 'comparative'
    grouped = defaultdict(list)
    for row in observations:
        identity = (row['source_form'], row.get('source_code') or row.get('metric_id') or row['raw_label'])
        grouped[identity].append(row)
    rows = []
    for (form, code), items in grouped.items():
        sample = items[-1]
        spans = sorted({(r['period_end'], r.get('period_start') or '') for r in items})
        direct = {(end, start): choose([r for r in items if r['period_end'] == end and (r.get('period_start') or '') == start]) for end, start in spans}
        resolved = [item for item in direct.values() if item.get('period_end')]
        cells = {}
        for column in columns:
            basis, end = column['basis'], column['end']
            stock = sample['kind'] == 'stock'
            if (stock and basis == 'ttm') or (not stock and basis == 'as_of'):
                value = {'value': None, 'quality': 'not_applicable', 'reason': 'STOCK_IS_AS_OF_DATE' if stock else 'FLOW_NEEDS_PERIOD'}
            elif not stock and basis in {'quarter', 'ttm'}:
                value = periods.calculate(resolved, end, basis)
            else:
                candidates = [r for r in items if r['period_end'] == end and
                              (stock or r.get('period_start') == end[:4] + '-01-01')]
                value = choose(candidates)
                if not candidates and not stock and column.get('notice'):
                    value['reason'] = column['notice']
            cells[column['key']] = value
        rows.append({k: sample.get(k) for k in ('metric_id', 'source_form', 'source_code', 'kind', 'unit')} |
                    {'id': form + ':' + str(code), 'label': sample['raw_label'], 'cells': cells})
    return {'columns': columns, 'rows': rows}
