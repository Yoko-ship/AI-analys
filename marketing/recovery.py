"""Owner-reviewed backup gaps never authorize replay of uncertain old work."""
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from . import store as s
from .url_policy import public_url
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import timestamp


class AccountReview(Input):
    account_id: str = Field(min_length=1, max_length=200)
    platform: Literal['telegram', 'instagram', 'facebook', 'linkedin']
    external_id: str = Field(max_length=200)
    reference: str = Field(min_length=20, max_length=3000)


class MissingPublication(Input):
    event_id: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    platform: Literal['telegram', 'instagram', 'facebook', 'linkedin']
    external_id: str = Field(max_length=200)
    publication_type: Literal['organic', 'paid'] = 'organic'
    published_at: datetime
    url: str = Field(min_length=1, max_length=2000)


class Review(Input):
    expected_version: int = Field(ge=1)
    basis_digest: str = Field(min_length=1, max_length=100)
    old_worker_stopped: Literal[True]
    reviewed_through: datetime
    accounts: list[AccountReview] = Field(max_length=100)
    missing_publications: list[MissingPublication] = Field(default_factory=list, max_length=500)
    reason: str = Field(min_length=20, max_length=6000)

    @model_validator(mode='after')
    def dated(self):
        if self.reviewed_through.tzinfo is None or any(row.published_at.tzinfo is None for row in self.missing_publications):
            raise ValueError('Recovery review times require a time zone')
        return self


def _scope(row):
    return row['account_id'], row['platform'], row['external_id']


def recipient_scopes(c):
    scopes = {(row['id'], row['platform'], row['external_id']) for row in s.list_items(c, 'account')}
    scopes.update((row['account_id'], row['platform'], row['external_account_id']) for row in s.list_items(c, 'delivery'))
    return [dict(zip(('account_id', 'platform', 'external_id'), value)) for value in sorted(scopes)]


def inspect(c):
    recovery = s.get(c, 'settings', 'recovery', required=False)
    if not recovery:
        return None
    scopes = recovery.get('recipient_scopes') or recipient_scopes(c)
    candidates = s.list_items(c, 'candidate')
    deliveries = s.list_items(c, 'delivery')
    accounts = s.list_items(c, 'account')
    pause = s.get(c, 'settings', 'pause', required=False) or {}
    quarantine = [row for row in candidates if row['status'] not in {'published', 'submitted', 'skipped', 'cancelled', 'unknown'}]
    versions = lambda rows: sorted((row['id'], row['version']) for row in rows)
    basis = [recovery['version'], scopes, versions(accounts), versions(candidates), versions(deliveries),
             versions(s.list_items(c, 'publication_reservation')), pause.get('version', 0)]
    return {**recovery, 'accounts': scopes, 'basis_digest': s.digest(basis),
            'paused': bool(pause.get('publications') and pause.get('processing')),
            'quarantine': [{key: row[key] for key in ('id', 'version', 'title', 'account_id', 'event_id', 'status')} for row in quarantine]}


def _require(condition, message):
    if not condition:
        raise MarketingError('RECOVERY_REVIEW', message, 409)


def complete(actor, data, *, now):
    require_owner(actor)
    review = Review.model_validate(data).model_dump(mode='json')
    with s.connection(write=True) as c:
        state = inspect(c)
        _require(state and state['status'] == 'requires_reconciliation', 'Нет незавершённой сверки восстановления.')
        _require(state['version'] == review['expected_version'] and state['basis_digest'] == review['basis_digest'],
                 'Данные восстановления изменились. Обновите состояние и повторите сверку.')
        _require(state['paused'], 'Перед завершением сверки остановите обработку и публикации.')
        through = timestamp(review['reviewed_through'])
        _require(timestamp(state['restored_at']) <= through <= now, 'Проверенный промежуток должен включать восстановление и не уходить в будущее.')
        supplied = [_scope(row) for row in review['accounts']]
        _require(len(supplied) == len(set(supplied)) and set(supplied) == {_scope(row) for row in state['accounts']},
                 'Подтвердите проверку каждого исходного аккаунта и получателя из копии.')
        keys = set()
        for row in review['missing_publications']:
            key = s.digest([row['event_id'], row['account_id'], row['publication_type']])
            _require(_scope(row) in set(supplied), 'Публикация должна относиться к проверенному получателю.')
            _require(timestamp(state['backup_created_at']) <= timestamp(row['published_at']) <= through,
                     'Дата найденной публикации должна входить в проверенный промежуток после копии.')
            _require(public_url(row['url']), 'Укажите HTTPS-ссылку на найденную публикацию без пароля в адресе.')
            _require(key not in keys and not s.get(c, 'publication_reservation', key, required=False),
                     'Один ключ события, аккаунт и тип публикации можно зарезервировать только один раз.')
            keys.add(key)
        # All validation precedes mutations; the transaction also preserves
        # atomicity if a record changes or a write fails.
        for row in review['missing_publications']:
            key = s.digest([row['event_id'], row['account_id'], row['publication_type']])
            s.put(c, 'publication_reservation', {**row, 'id': key, 'status': 'reserved',
                  'confirmation': 'owner_gap_review', 'recovery_version': state['version'],
                  'reviewed_at': now.isoformat()}, actor=actor, action='recovery_event_reserved', expected_version=0)
        for row in state['quarantine']:
            item = s.get(c, 'candidate', row['id'])
            s.put(c, 'candidate', {**item, 'status': 'unknown', 'approval': None,
                  'recovery_review_version': state['version'],
                  'reason': 'Прежний выпуск из копии закрыт для повторной отправки; его внешний исход не подтверждён.'},
                  actor=actor, action='recovery_candidate_quarantined', expected_version=item['version'])
        for job in s.list_items(c, 'delivery'):
            if job['status'] in {'published', 'submitted', 'cancelled', 'unknown'}:
                continue
            s.put(c, 'delivery', {**job, 'status': 'unknown', 'claim_token': None,
                  'reason': 'Прежний выпуск из копии требует отдельного подтверждения; повторная отправка закрыта.'},
                  actor=actor, action='recovery_delivery_quarantined', expected_version=job['version'])
        record = s.get(c, 'settings', 'recovery')
        return s.put(c, 'settings', {**record, 'status': 'reconciled', 'review': review,
                     'reviewed_at': now.isoformat(), 'reason': review['reason']}, actor=actor,
                     action='recovery_gap_reviewed', expected_version=review['expected_version'])
