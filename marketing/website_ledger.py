"""Dated native observations and session links; owner amendments retain priority."""
from datetime import datetime
from typing import Literal

from pydantic import Field
from product_events import KINDS as PRODUCT_KINDS

from . import analytics, store as s
from .errors import MarketingError
from .models import Input
from .permissions import timestamp

ACTOR = {'id': 'website', 'role': 'analytics'}


class IdentityLink(Input):
    dataset: Literal['production', 'test']
    subject_id: str = Field(pattern=r'^ws_s_[a-zA-Z0-9]+$', max_length=100)
    user_id: str | None = Field(default=None, pattern=r'^ws_u_[a-zA-Z0-9]+$', max_length=100)
    observed_at: datetime


def _save_changed(c, kind, key, data, now):
    old = s.get(c, kind, key, required=False)
    if old and old['data'] == data:
        return False
    s.put(c, kind, {'id': key, 'data': data, 'received_at': now.isoformat()}, actor=ACTOR,
          action='website_observed', expected_version=old['version'] if old else 0)
    return True


def ingest(c, events, links, now):
    result = {'imported': 0, 'revised': 0, 'identity_updates': 0}
    for raw in events:
        event = analytics.Event.model_validate(raw).model_dump(mode='json')
        if (event['source'] != 'uzstock_website' or not event['id'].startswith('website:')
                or event['kind'] not in {'visit', 'registration_started', 'registration'} | PRODUCT_KINDS or timestamp(event['at']) > now):
            raise MarketingError('INVALID_WEBSITE_EVENT', 'Invalid native website observation.', 422)
        key = s.digest([event['dataset'], event['id']])
        old = s.get(c, 'event', key, required=False)
        if old and old.get('origin') != 'website':
            raise MarketingError('EVENT_CONFLICT', 'This event ID already belongs to another import.')
        if not old:
            s.put(c, 'event', {'id': key, 'origin': 'website', 'event': event, 'received_at': now.isoformat()},
                  actor=ACTOR, action='website_event_imported', expected_version=0)
            result['imported'] += 1
        changed = _save_changed(c, 'website_observation', key, event, now)
        result['revised'] += bool(old and changed)
    for raw in links:
        value = IdentityLink.model_validate(raw).model_dump(mode='json')
        observed = timestamp(value['observed_at'])
        if observed.tzinfo is None or observed > now:
            raise MarketingError('INVALID_WEBSITE_IDENTITY', 'Identity evidence requires an observed timestamp.', 422)
        key = s.digest([value['dataset'], value['subject_id']])
        old = s.get(c, 'website_identity', key, required=False)
        if (not old and value['user_id'] is None) or (old and old['data']['user_id'] == value['user_id']):
            continue
        result['identity_updates'] += _save_changed(c, 'website_identity', key, value, now)
    return result


def _at_cut(c, kind, cut):
    for latest in s.list_items(c, kind):
        available = [row['record'] for row in s.history(c, kind, latest['id'])
                     if timestamp(row['record']['received_at']) <= cut]
        if available:
            yield available[-1]


def apply(c, records, cut, *, protected=()):
    changes = []
    for observed in _at_cut(c, 'website_observation', cut):
        key = observed['id']
        if key in protected or key not in records or records[key].get('origin') != 'website':
            continue
        records[key] = {**records[key], 'event': observed['data']}
        if observed['version'] > 1:
            changes.append({'id': key, 'dataset': observed['data']['dataset'], 'version': observed['version'],
                            'received_at': observed['received_at'], 'reason': 'Обновлённое наблюдение базы сайта'})
    identities = {(row['data']['dataset'], row['data']['subject_id']): row
                  for row in _at_cut(c, 'website_identity', cut) if timestamp(row['data']['observed_at']) <= cut}
    used = set()
    for key, row in list(records.items()):
        if key in protected:
            continue
        event = row['event']
        identity = identities.get((event['dataset'], event['subject_id'])) if row.get('origin') == 'website' else None
        if not identity:
            continue
        if identity['data']['user_id']:
            records[key] = {**row, 'event': {**event, 'subject_id': identity['data']['user_id']}}
        if identity['id'] not in used:
            used.add(identity['id'])
            changes.append({'id': identity['id'], 'dataset': identity['data']['dataset'], 'version': identity['version'],
                            'received_at': identity['received_at'], 'reason': 'Связь с аккаунтом подтверждена в журнале сайта' if identity['data']['user_id'] else 'Сессия не имеет однозначной связи с аккаунтом'})
    return changes
