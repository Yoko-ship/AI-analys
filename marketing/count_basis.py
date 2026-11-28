"""Observed rows retain useful counts while their total's completeness is explicit."""
from . import acquisition


def _basis(ctx, key, sources, *, attribution=None, cohort=False, paid=False):
    coverage = ctx.source_basis(key, sources)
    status = 'complete' if all(row['status'] == 'complete' for row in coverage.values()) else 'incomplete'
    if attribution and attribution['status'] != 'complete':
        status = 'incomplete'
    if cohort and not ctx.mature(ctx.cohort, ctx.settings['conversion_days']):
        status = 'incomplete'
    if paid and ctx.excluded_financial:
        status = 'incomplete'
    if paid and not ctx.live:
        status = 'not_applicable'
    elif paid and not ctx.settings['shared_customer_ids']:
        status = 'not_comparable'
    return {'status': status, 'coverage': coverage, **({'attribution': attribution} if attribution else {})}


def calculate(ctx):
    return {
        'channel_registrations': _basis(ctx, 'registration_cost', ('visits', 'registrations'),
                                       attribution=acquisition.assess(ctx, 'registration_cost')),
        'channel_first_payers': _basis(ctx, 'channel_first_payers', ('visits', 'registrations', 'payments'),
                                      attribution=acquisition.assess(ctx, 'channel_first_payers'), paid=True),
        'cohort_registrations': _basis(ctx, 'registrations', ('registrations',)),
        'cohort_paid_customers': _basis(ctx, 'registration_to_payment', ('registrations', 'payments'), cohort=True, paid=True),
    }
