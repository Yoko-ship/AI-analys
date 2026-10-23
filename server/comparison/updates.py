"""Deterministic changes from account-owned, previously viewed snapshots."""
from datetime import date

from identity.comparisons import ComparisonChanged, snapshot_key, clean
from . import service

TRACKED = ['net_profit', 'interest_income', 'revenue', 'assets', 'equity', 'loan_book',
           'customer_funds', 'roe', 'roa', 'cost_income', 'price', 'market_cap', 'pe', 'pb']
MARKET = {'price', 'market_cap', 'pe', 'pb'}


def source(value):
    return {k: value[k] for k in ['document_id', 'snapshot_id', 'url'] if value.get(k)} if value else {}


def snapshot(data, selection):
    companies = []
    for company in data['companies']:
        cells = {}
        for key in TRACKED:
            cell = company.get('metrics', {}).get(key) or {}
            value = service.number(cell.get('value'))
            if key in {'price', 'market_cap'} and value is not None and value <= 0:
                value = None
            cells[key] = {'value': value, 'unit': cell.get('unit'),
                          'period': cell.get('period'), 'base_period': cell.get('base_period'),
                          'as_of': cell.get('as_of') or (company.get('market_as_of') if key in MARKET else None),
                          'source': source(cell.get('source'))}
        companies.append({'ticker': company['ticker'], 'period': company.get('period') or data.get('period'),
                          'source': source(company.get('source')), 'metrics': cells})
    return {'version': 1, 'context': {k: selection.get(k) for k in ['tickers', 'period', 'standard', 'scope']},
            'currency': data.get('currency', 'UZS'), 'companies': companies}


def valid_day(day):
    try: return date.fromisoformat(day)
    except (TypeError, ValueError): return None


def difference(before, after):
    if not before or before.get('version') != after.get('version') or before.get('context') != after.get('context') or before.get('currency') != after.get('currency'):
        return []
    previous = {c['ticker']: c for c in before['companies']}
    changes = []
    for company in after['companies']:
        old = previous.get(company['ticker'])
        if not old: continue
        same_period = old['period'] == company['period']
        shared = {'ticker': company['ticker'], 'before_period': old['period'], 'after_period': company['period']}
        if not same_period:
            advanced = bool(old['period'] and company['period'] and service.period_order(company['period']) > service.period_order(old['period']))
            changes.append({**shared, 'kind': 'new_period' if advanced else 'period_changed', 'source': company['source']})
        elif old['source'] != company['source'] and company['source']:
            changes.append({**shared, 'kind': 'filing_updated', 'source': company['source']})
        for key in TRACKED:
            left, right = old['metrics'][key], company['metrics'][key]
            if not same_period and key != 'price': continue
            if left['unit'] != right['unit'] or left['period'] != right['period'] and key != 'price': continue
            a, b = left['value'], right['value']
            item = {**shared, 'metric': key, 'before': a, 'after': b,
                    'before_date': left['as_of'], 'after_date': right['as_of'],
                    'source': right['source'] or company['source']}
            if key in MARKET:
                prior_day, current_day = valid_day(left['as_of']), valid_day(right['as_of'])
                if not prior_day or not current_day or current_day < prior_day: continue
            if left['base_period'] != right['base_period'] and key in {'pe', 'pb'}:
                changes.append({**item, 'kind': 'basis_changed', 'before_basis': left['base_period'], 'after_basis': right['base_period']})
            elif a != b:
                if a is None or b is None:
                    changes.append({**item, 'kind': 'data_available' if a is None else 'data_unavailable'})
                else:
                    changes.append({**item, 'kind': 'market_change' if key in MARKET else 'revised_figure',
                                    'delta': b - a, 'percent_change': (b - a) / a * 100 if a > 0 else None})
    return changes


def current(selection):
    return service.compare(selection['tickers'], selection['period'], selection['standard'], selection['scope'])


def save(repository, user_id, payload):
    # Capture a server-produced baseline. Renaming an existing selection keeps
    # its last-viewed snapshot intact in the repository's conflict handler.
    name, selection = clean(payload)
    data = current(selection)
    return repository.save(user_id, {'name': name, **selection}, snapshot(data, selection))


def inspect(repository, user_id, comparison_id):
    record = repository.get(user_id, comparison_id)
    if not record: return None
    data = current(record['selection'])
    now = snapshot(data, record['selection'])
    baseline = record.get('seen_snapshot')
    changes = difference(baseline, now)
    return {'ok': True, 'comparison_id': str(comparison_id), 'comparison': data,
            'changes': changes, 'updated': bool(changes), 'tracking_started': not bool(baseline),
            'last_seen_at': record['seen_at'].isoformat() if record.get('seen_at') else None,
            'snapshot_key': snapshot_key(now), 'baseline_key': snapshot_key(baseline)}


def seen(repository, user_id, comparison_id, expected_snapshot, expected_baseline):
    record = repository.get(user_id, comparison_id)
    if not record: return None
    now = snapshot(current(record['selection']), record['selection'])
    if snapshot_key(now) != expected_snapshot:
        raise ComparisonChanged('Data changed while opening this comparison; refresh the updates')
    return repository.mark_seen(user_id, comparison_id, now, expected_baseline)
