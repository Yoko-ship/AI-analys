"""Evidence for acquisition credit, independent of cash and source completeness."""
from collections import Counter
from datetime import timedelta

from .permissions import timestamp

TOUCHES = {'visit', 'click', 'publication_visit'}
METRICS = {'registration_cost', 'advertising_cac', 'full_cac', 'payback', 'roi', 'roas'}
REASONS = {
    'missing_registration': 'Нет связанной подтверждённой регистрации.',
    'no_touch': 'Нет наблюдаемого источника в окне привлечения.',
    'unknown_touch': 'Источник последнего непрямого перехода не определён.',
    'conflicting_touches': 'Одновременные переходы указывают разные источники.',
    'registration_after_payment': 'Регистрация наблюдалась позже относимой оплаты.',
}


def resolve(events, registration, days):
    at = timestamp(registration['at'])
    inputs = [row for row in events if row['kind'] in TOUCHES and at-timedelta(days=days) <= timestamp(row['at']) <= at]
    # An unknown touch is not direct. It can invalidate earlier source credit;
    # an explicitly direct return does not replace a known non-direct source.
    eligible = [row for row in inputs if row['channel'] != 'direct'] or inputs
    if not eligible:
        return {'channel': 'unknown', 'touch': None, 'reason': 'no_touch', 'inputs': inputs}
    latest_at = max(timestamp(row['at']) for row in eligible)
    latest = [row for row in eligible if timestamp(row['at']) == latest_at]
    channels = {row['channel'] or 'unknown' for row in latest}
    if len(channels) != 1 or channels == {'unknown'}:
        return {'channel': 'unknown', 'touch': None, 'inputs': inputs,
                'reason': 'conflicting_touches' if len(channels) != 1 else 'unknown_touch'}
    # Equal timestamps cannot be ordered using a random event ID. The channel
    # can be known while the exact publication remains ambiguous.
    objects = {(row['kind'], row['publication_id'], row['object_id'], row['promotion']) for row in latest}
    return {'channel': next(iter(channels)), 'touch': latest[-1] if len(objects) == 1 else None,
            'reason': None, 'inputs': inputs,
            'publication_uncertain': len(objects) > 1 and any(row['kind'] == 'publication_visit' for row in latest)}


def population(ctx, key):
    if key == 'registration_cost':
        return {subject: [] for subject in ctx.cohort}
    if key == 'channel_first_payers':
        return {subject: [row] for subject, row in ctx.paid_period.items()}
    if key in {'roi', 'roas'}:
        result = {}
        for kind in ('payment', 'refund'):
            for row in ctx.financial_events(kind):
                if row['amount'] > 0:
                    result.setdefault(row['subject_id'], []).append(row)
        return result
    # A receipt without a registration can belong to the cohort. Do not drop
    # it simply because the join failed; bound its possible conversion window.
    result = {subject: [row] for subject, row in ctx.paid_cohort.items()}
    latest = ctx.end + timedelta(days=ctx.settings['conversion_days'])
    for subject, row in ctx.first.items():
        if (subject not in ctx.registrations and row['currency'] == ctx.settings['currency']
                and ctx.start <= timestamp(row['at']) < latest):
            result[subject] = [row]
    return result


def assess(ctx, key):
    subjects = population(ctx, key)
    reasons = Counter()
    originals = {row['transaction_id']: row for row in ctx.financial_events('payment', period=False)}
    for subject, receipts in subjects.items():
        registration = ctx.registrations.get(subject)
        if not registration:
            reason = 'missing_registration'
        elif any(timestamp(registration['at']) > timestamp((originals.get(row['related_transaction_id'], row)
                 if row['kind'] == 'refund' else row)['at']) for row in receipts):
            reason = 'registration_after_payment'
        else:
            reason = ctx.acquisition[subject]['reason']
        if reason:
            reasons[reason] += 1
    return {'status': 'incomplete' if reasons else 'complete', 'customers': len(subjects),
            'unresolved_customers': sum(reasons.values()),
            'reasons': [{'code': code, 'message': REASONS[code], 'customers': count} for code, count in sorted(reasons.items())]}


def touch_inputs(ctx, key):
    return [row for subject in population(ctx, key) for row in ctx.acquisition.get(subject, {}).get('inputs', [])]


def proof_inputs(ctx, key):
    subjects = population(ctx, key)
    receipts = [row for rows in subjects.values() for row in rows]
    originals = {row['related_transaction_id'] for row in receipts if row['kind'] == 'refund'}
    return [*receipts, *(ctx.registrations[subject] for subject in subjects if subject in ctx.registrations),
            *touch_inputs(ctx, key),
            *(row for row in ctx.financial_events('payment', period=False) if row['transaction_id'] in originals)]
