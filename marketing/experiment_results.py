"""Descriptive reader cohorts; exposure is observed, never assumed randomized."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import analytics, content, event_ledger, store as s
from .errors import MarketingError
from .permissions import TASHKENT, timestamp
from .report_coverage import CoverageLedger


def calculate(c, design, now):
    start, end = [datetime.combine(date.fromisoformat(design[key]), datetime.min.time(), TASHKENT)
                  for key in ('starts_on', 'ends_on')]
    if now < start:
        raise MarketingError('EXPERIMENT_NOT_STARTED', 'Период набора ещё не начался.', 422)
    followup = timedelta(days=design['followup_days'])
    mature_at = end+followup
    records, corrections = event_ledger.read(c, now)
    values = [row['event'] for row in records if row['event']['dataset'] == design['dataset']
              and timestamp(row['event']['at']) <= now]
    events = [row for row in analytics._deduplicate(values) if row['traffic'] == 'external' and row['confirmed']]
    cohorts = {arm: {} for arm in ('control', 'variant')}
    exposures = {arm: defaultdict(list) for arm in cohorts}
    outcomes, registrations = defaultdict(list), {}
    for event in events:
        subject, at = event['subject_id'], timestamp(event['at'])
        if not subject:
            continue
        if event['kind'] == 'registration':
            registrations.setdefault(subject, at)
        if event['kind'] == design['kpi'] and (design['kpi'] == 'registration' or event['object_id'] == design['outcome_object_id']):
            outcomes[subject].append(at)
        if (event['kind'] == 'publication_visit' and event['channel'] == design['channel']
                and event['promotion'] == 'organic' and start <= at < mature_at):
            for arm in cohorts:
                if event['publication_id'] in design[arm+'_ids']:
                    exposures[arm][subject].append(at)
                    if at < end:
                        cohorts[arm].setdefault(subject, at)
    overlap = set(cohorts['control']) & set(cohorts['variant'])
    for arm, other in [('control', 'variant'), ('variant', 'control')]:
        overlap.update(key for key, at in cohorts[arm].items()
                       if any(at <= touch <= at+followup for touch in exposures[other][key]))
    existing = set()
    arms = {}
    for arm, members in cohorts.items():
        selected = {key: at for key, at in members.items() if key not in overlap}
        if design['kpi'] == 'registration':
            old = {key for key, at in selected.items() if key in registrations and registrations[key] < at}
            existing |= old
            selected = {key: at for key, at in selected.items() if key not in old}
        count = sum(any(at <= outcome <= at+followup for outcome in outcomes[key]) for key, at in selected.items())
        arms[arm] = {'readers': len(selected), 'outcomes': count, 'rate': 100*count/len(selected) if selected else None}
    ledger = CoverageLedger(s.list_items(c, 'coverage'), design['dataset'], now)
    categories = ['visits', 'registrations' if design['kpi'] == 'registration' else 'activity']
    coverage = {category: ledger.assess(category, start, mature_at,
                                       history_required=category == 'registrations') for category in categories}
    reasons = []
    if now < mature_at:
        reasons.append('open_window')
    if any(row['status'] != 'complete' for row in coverage.values()):
        reasons.append('incomplete_coverage')
    if any(row['readers'] < design['minimum_observations'] for row in arms.values()):
        reasons.append('small_sample')
    for key, original in design['creatives'].items():
        current = s.get(c, 'candidate', key, required=False)
        if not current or content.content_digest(current) != original['content_digest']:
            reasons.append('creative_changed')
            break
    account = s.get(c, 'account', design['account_id'], required=False)
    if not account or (account['platform'], account['external_id']) != (design['channel'], design['recipient']):
        reasons.append('account_changed')
    return {'formula_version': 'organic-reader-cohort-v1', 'dataset': design['dataset'], 'cutoff': now.isoformat(),
            'mature_at': mature_at.isoformat(), 'status': 'preliminary' if reasons else 'observed', 'reasons': reasons,
            'arms': arms, 'difference_pp': None if reasons else arms['variant']['rate']-arms['control']['rate'],
            'excluded_overlap': len(overlap), 'excluded_existing': len(existing), 'coverage': coverage,
            'sources': sorted({row['source'] for row in events if row['kind'] in {'publication_visit', design['kpi']}}),
            'inputs_digest': s.digest(values), 'correction_ids': [row['id'] for row in corrections if row['dataset'] == design['dataset']]}
