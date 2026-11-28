"""Observation windows follow the inputs of a metric, not its category alone."""
from datetime import timedelta

from .permissions import timestamp

ACQUISITION = {'registration_cost', 'advertising_cac', 'full_cac', 'payback', 'roi', 'roas'}
CONVERSION = {'registration_to_payment', 'advertising_cac', 'full_cac'}
SERVICE = {'arpu', 'arppu', 'ltv', 'payback'}


def acquisition_dates(ctx, key):
    subjects = ctx.cohort
    if key == 'channel_first_payers':
        subjects = ctx.paid_period
    if key in {'roi', 'roas'}:
        subjects = {e['subject_id'] for kind in ('payment', 'refund') for e in ctx.financial_events(kind)}
    return [timestamp(ctx.registrations[subject]['at']) for subject in subjects if subject in ctx.registrations]


def service_end(ctx, key):
    """A closed service period includes known later adjustments, not future time."""
    end, inclusive = min(ctx.end, ctx.cut), ctx.cut < ctx.end
    subjects = {subject for subject in ctx.paid_cohort if ctx.channel(subject) in ctx.scope} if key == 'payback' else None
    payments = [row for row in ctx.financial_events('payment', period=False)
                if row['amount'] > 0 and row['payment_type'] != 'one_off' and row['revenue_kind'] == 'recurring'
                and (subjects is None or row['subject_id'] in subjects)
                and timestamp(row['service_starts_at']) < min(ctx.end, ctx.cut)
                and timestamp(row['service_ends_at']) > ctx.start]
    transactions = {row['transaction_id'] for row in payments}
    adjustments = [row for row in ctx.financial_events('refund', period=False) if row['amount'] > 0 and row['related_transaction_id'] in transactions]
    latest = max((timestamp(row['at']) for row in [*payments, *adjustments]), default=end)
    return (latest, True) if latest >= end and (payments or adjustments) else (end, inclusive)


def required(ctx, key, source):
    start, end = ctx.start, min(ctx.end, ctx.cut)
    inclusive, history = ctx.cut < ctx.end, False
    if source == 'registrations':
        history = True
        if key == 'retention':
            start, end, inclusive = start - timedelta(days=ctx.settings['retention_days']), start, False
        elif key in {'roi', 'roas', 'channel_first_payers'} and (dates := acquisition_dates(ctx, key)):
            start, end, inclusive = min(dates), max(dates), True
    elif source == 'visits' and key == 'publication_attribution':
        start -= timedelta(days=ctx.settings['attribution_days'])
    elif source == 'visits' and key in ACQUISITION | {'channel_first_payers'}:
        dates = acquisition_dates(ctx, key)
        start = min(dates, default=ctx.start) - timedelta(days=ctx.settings['attribution_days'])
        end, inclusive = (max(dates), True) if dates else (end, inclusive)
    elif source == 'payments':
        history = key in {'first_paying_customers', 'channel_first_payers'} or key in CONVERSION | SERVICE
        if key in SERVICE:
            end, inclusive = service_end(ctx, key)
            if key == 'payback' and ctx.cohort:
                conversion_end = min(ctx.cut, max(timestamp(row['at']) for row in ctx.cohort.values()) + timedelta(days=ctx.settings['conversion_days']))
                if conversion_end >= end:
                    end, inclusive = conversion_end, True
        elif key in CONVERSION and ctx.cohort:
            end = min(ctx.cut, max(timestamp(row['at']) for row in ctx.cohort.values()) + timedelta(days=ctx.settings['conversion_days']))
            inclusive = True
    elif source == 'activity' and key == 'activation' and ctx.cohort:
        end = min(ctx.cut, max(timestamp(row['at']) for row in ctx.cohort.values()) + timedelta(days=ctx.settings['activation_days']))
        inclusive = True
    elif source == 'margin':
        history = True
        if key in SERVICE:
            end, inclusive = service_end(ctx, key)
    elif source == 'subscriptions':
        history = True
    return {'start': start, 'end': end, 'history_required': history, 'end_inclusive': inclusive}
