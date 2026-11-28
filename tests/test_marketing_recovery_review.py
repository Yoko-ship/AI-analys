"""A reviewed backup gap permits new work without replaying uncertain old releases."""
from datetime import timedelta

import pytest

from marketing import backup, content, delivery, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, CMO, NOW, candidate, isolated  # noqa: F401
from test_marketing_delivery import Platform, prepare
from test_marketing_scheduling import workspace_backend  # noqa: F401
from test_postgres_accounts import pg_store  # noqa: F401

RESTORED = NOW + timedelta(minutes=20)
REVIEWED = RESTORED + timedelta(minutes=5)


def restored(monkeypatch, tmp_path):
    job = prepare()
    draft = candidate('draft-before-backup')
    monkeypatch.setattr(store, 'now', lambda: NOW.isoformat())
    path = tmp_path / 'gap.zip'
    backup.create(path)
    assert delivery.run_one(Platform(), NOW + timedelta(minutes=1))
    monkeypatch.setenv('MARKETING_ENVIRONMENT', 'reviewed-restore')
    monkeypatch.setattr(store, 'now', lambda: RESTORED.isoformat())
    backup.restore(path)
    return job, draft


def review_input():
    from marketing import recovery
    with store.connection() as c:
        state = recovery.inspect(c)
    return {'expected_version': state['version'], 'basis_digest': state['basis_digest'],
            'old_worker_stopped': True, 'reviewed_through': REVIEWED.isoformat(),
            'accounts': [{'account_id': row['account_id'], 'platform': row['platform'], 'external_id': row['external_id'],
                          'reference': 'Проверена история целевого канала за весь промежуток после копии.'} for row in state['accounts']],
            'missing_publications': [{'event_id': 'event-created-after-backup', 'account_id': 'tg', 'publication_type': 'organic',
                                      'platform': 'telegram', 'external_id': '-100123',
                                      'published_at': (NOW + timedelta(minutes=10)).isoformat(),
                                      'url': 'https://t.me/example/124'}],
            'reason': 'Старый обработчик остановлен. История площадок сверена; неподтверждённые старые версии остаются закрытыми.'}


@pytest.mark.parametrize('workspace_backend', ['sqlite', 'postgres'], indirect=True)
def test_owner_finishes_gap_review_but_old_work_and_missing_events_cannot_replay(monkeypatch, tmp_path, workspace_backend):
    from marketing import recovery
    job, draft = restored(monkeypatch, tmp_path)
    request = review_input()
    result = recovery.complete(OWNER, request, now=REVIEWED)
    assert result['status'] == 'reconciled'
    with store.connection() as c:
        assert store.get(c, 'settings', 'pause')['publications'] is True
        assert store.get(c, 'settings', 'pause')['processing'] is True
        assert store.get(c, 'delivery', job['id'])['status'] == 'unknown'
        assert store.get(c, 'candidate', job['candidate_id'])['status'] == 'unknown'
        assert store.get(c, 'candidate', draft['id'])['status'] == 'unknown'
        reservation, = store.list_items(c, 'publication_reservation')
        assert reservation['event_id'] == 'event-created-after-backup'
        assert reservation['url'] == request['missing_publications'][0]['url']
        assert reservation['confirmation'] == 'owner_gap_review'
        assert store.history(c, 'candidate', draft['id'])[0]['record']['status'] == 'draft'
        account = store.get(c, 'account', 'tg')
        assert account['connection_status'] == 'not_connected'
    assert candidate('decision-123')['status'] == 'unknown'
    with pytest.raises(MarketingError) as reserved:
        candidate('event-created-after-backup')
    assert reserved.value.code == 'RECOVERED_EVENT_RESERVED'
    delivery.set_pause(OWNER, publications=False, processing=False)
    transport = Platform()
    assert not delivery.run_one(transport, REVIEWED)
    assert not transport.calls
    # Reconnection and a new checked event are still separate owner steps.
    delivery.record_connection('tg', account['version'], external_id=account['external_id'], verified=True, now=REVIEWED)
    fresh = candidate('new-reviewed-event')
    content.check_candidate(fresh['id'], REVIEWED)
    delivery.schedule(fresh['id'], REVIEWED)
    assert delivery.run_one(transport, REVIEWED)
    assert len(transport.calls) == 1 and transport.calls[0][1] == fresh['id']


@pytest.mark.parametrize('case', ['not_owner', 'stale_basis', 'missing_account', 'changed_recipient', 'worker_not_stopped',
                                 'future_review', 'partial_gap', 'old_publication', 'foreign_publication', 'duplicate_event'])
def test_incomplete_or_changed_gap_review_cannot_unlock_or_partially_quarantine(monkeypatch, tmp_path, case):
    from marketing import recovery
    job, draft = restored(monkeypatch, tmp_path)
    request = review_input()
    actor = OWNER
    if case == 'not_owner': actor = CMO
    elif case == 'stale_basis': candidate('created-during-review')
    elif case == 'missing_account': request['accounts'] = []
    elif case == 'changed_recipient': request['accounts'][0]['external_id'] = '-100999'
    elif case == 'worker_not_stopped': request['old_worker_stopped'] = False
    elif case == 'future_review': request['reviewed_through'] = (REVIEWED + timedelta(minutes=1)).isoformat()
    elif case == 'partial_gap': request['reviewed_through'] = (RESTORED - timedelta(minutes=1)).isoformat()
    elif case == 'old_publication': request['missing_publications'][0]['published_at'] = (NOW - timedelta(minutes=1)).isoformat()
    elif case == 'foreign_publication': request['missing_publications'][0]['account_id'] = 'unreviewed'
    elif case == 'duplicate_event': request['missing_publications'].append(dict(request['missing_publications'][0]))
    with pytest.raises((MarketingError, ValueError)):
        recovery.complete(actor, request, now=REVIEWED)
    with store.connection() as c:
        assert store.get(c, 'settings', 'recovery')['status'] == 'requires_reconciliation'
        assert store.get(c, 'delivery', job['id'])['status'] == 'scheduled'
        assert store.get(c, 'candidate', draft['id'])['status'] == 'draft'
        assert not store.list_items(c, 'publication_reservation')


def test_recovery_completion_is_one_exact_owner_decision_and_requires_normal_pauses(monkeypatch, tmp_path):
    from marketing import recovery
    restored(monkeypatch, tmp_path)
    request = review_input()
    delivery.set_pause(OWNER, publications=False, processing=False)
    with pytest.raises(MarketingError):
        recovery.complete(OWNER, request, now=REVIEWED)
    delivery.set_pause(OWNER, publications=True, processing=True)
    request = review_input()
    recovery.complete(OWNER, request, now=REVIEWED)
    with pytest.raises(MarketingError):
        recovery.complete(OWNER, request, now=REVIEWED)


def test_gap_reservations_exclude_editorial_reprints_without_claiming_provider_confirmation(monkeypatch, tmp_path):
    from marketing import automation, recovery
    restored(monkeypatch, tmp_path)
    recovery.complete(OWNER, review_input(), now=REVIEWED)
    with store.connection() as c:
        assert automation._assigned(c, {'aliases': ['event:event-created-after-backup']}, 'tg')
        assert not automation._assigned(c, {'aliases': ['event:event-created-after-backup']}, 'other-account')
        assert not automation._assigned(c, {'aliases': ['event:a-new-event']}, 'tg')
        assert not store.list_items(c, 'delivery', status='published')
