"""Observed arrivals and registration credit; never synthetic platform clicks."""
from . import store as s


def calculate(ctx):
    rows = {}

    def row(event):
        key = s.digest([event['publication_id'], event['channel'], event['promotion']])
        return rows.setdefault(key, {'publication_id': event['publication_id'], 'channel': event['channel'],
            'promotion': event['promotion'], 'observed_arrivals': 0, 'attributed_registrations': 0})

    for event in ctx.by_kind['publication_visit']:
        row(event)['observed_arrivals'] += 1
    unattributed = 0
    for subject in ctx.cohort:
        touch = ctx.touches[subject]
        if touch and touch['kind'] == 'publication_visit':
            row(touch)['attributed_registrations'] += 1
        else:
            unattributed += 1
    coverage = ctx.source_basis('publication_attribution', ('visits', 'registrations'))
    unresolved = sum(bool(ctx.acquisition[subject]['reason'] or ctx.acquisition[subject].get('publication_uncertain')) for subject in ctx.cohort)
    return {'rows': sorted(rows.values(), key=lambda item: (item['publication_id'], item['channel'], item['promotion'])),
            'unattributed_registrations': unattributed, 'coverage': coverage,
            'unresolved_registrations': unresolved,
            'status': 'complete' if not unresolved and all(item['status'] == 'complete' for item in coverage.values()) else 'incomplete'}
