"""A bounded weekly edition of announced future events, using current originals."""
from datetime import date, datetime, time, timedelta

from . import sources, store as s
from .permissions import TASHKENT, timestamp
from .publication_links import valid_destination

TYPES = {'meeting', 'report', 'placement', 'payment'}


def window(rule, now):
    local = now.astimezone(TASHKENT)
    day = local.date() - timedelta(days=(local.weekday() - rule['calendar_day']) % 7)
    cutoff = datetime.combine(day, time.fromisoformat(rule['calendar_time']), TASHKENT)
    if cutoff > now:
        day -= timedelta(days=7)
        cutoff -= timedelta(days=7)
    start = day + timedelta(days=1) if day.weekday() == 6 else day - timedelta(days=day.weekday())
    end = start + timedelta(days=7)
    if not rule['starts_on'] <= day.isoformat() <= rule['ends_on'] or local.date() >= end:
        return None
    return cutoff, start, end


def select(c, rule, now, inventory, assigned, aliases):
    bounds = window(rule, now)
    if not bounds:
        return []
    cutoff, start, end = bounds
    events = []
    for group in inventory:
        selected = [sources.current_evidence(c, row['id']) for row in group
                    if row.get('source_id') in rule['source_ids'] and row.get('suggested_rubric') == 'calendar']
        selected = [row for row in selected if row['status'] == 'verified' and timestamp(row['expires_at']) > now]
        if not selected or len(selected) > 30:
            continue
        if any(not row.get('event_at') or row['data'].get('event_type') not in TYPES for row in selected):
            continue
        schedules = {(row['entity'], row['data']['event_type'], timestamp(row['event_at']).astimezone(TASHKENT).date()) for row in selected}
        if len(schedules) != 1:
            continue
        event_date = next(iter(schedules))[2]
        at = min(timestamp(row['event_at']) for row in selected)
        if not start <= event_date < end or at <= now or not any(valid_destination(row.get('destination_url', '')) for row in selected):
            continue
        event = {'id': min(row['canonical_event_id'] for row in group), 'at': at,
                 'originals': selected, 'aliases': aliases(group),
                 'inventory_versions': {row['id']: row['version'] for row in group}}
        if not assigned(c, event, rule['target']['account_id']):
            events.append(event)
    chosen, originals = [], []
    for event in sorted(events, key=lambda row: (row['at'], row['id'])):
        if len(originals) + len(event['originals']) <= 30:
            chosen.append(event)
            originals.extend(event['originals'])
        if len(chosen) == 8:
            break
    if not chosen:
        return []
    identity = 'calendar:' + s.digest([rule['id'], start.isoformat()])
    return [{'id': identity, 'at': cutoff, 'entity': '', 'period': start.isoformat(), 'originals': originals,
             'expires_at': min(event['at'] for event in chosen),
             'destination_url': next(row['destination_url'] for row in originals if valid_destination(row.get('destination_url', ''))),
             'aliases': sorted({'event:' + identity, *(alias for event in chosen for alias in event['aliases'])}),
             'inventory_versions': {key: version for event in chosen for key, version in event['inventory_versions'].items()},
             'calendar_cutoff': cutoff.isoformat()}]


def check(item, evidence, now):
    """Structured editions have an explicit Monday and one schedule per event."""
    try:
        start = date.fromisoformat(item['period'])
        if start.weekday() != 0:
            raise ValueError()
    except ValueError:
        return ['A weekly calendar requires its Monday date as the period']
    end = start + timedelta(days=7)
    for entry in item['digest_items']:
        originals = [evidence[key] for key in entry['evidence_ids'] if key in evidence]
        schedules = {(row['entity'], row['data'].get('event_type'), timestamp(row['event_at']).astimezone(TASHKENT).date())
                     for row in originals if row.get('event_at')}
        if not originals or len(schedules) != 1 or any(not row.get('event_at') for row in originals):
            return ['Calendar originals must agree on the announced event, issuer and date']
        _, kind, day = next(iter(schedules))
        if kind not in TYPES or not start <= day < end or any(timestamp(row['event_at']) <= now for row in originals):
            return ['Calendar events must have an announced future date inside the selected week']
    return []
