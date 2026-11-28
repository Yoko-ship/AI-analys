"""Native observations keep dates, privacy, source revisions and counting basis."""
import base64
from datetime import timedelta

import pytest

from marketing import event_ledger, reports, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_postgres_accounts import pg_store  # noqa: F401
from test_marketing_api import client  # noqa: F401


@pytest.fixture(autouse=True)
def native_settings(monkeypatch, tmp_path):
    monkeypatch.setenv('MARKETING_ANALYTICS_ID_KEY', base64.urlsafe_b64encode(b'a' * 32).decode())
    monkeypatch.setenv('DATABASE_URL', 'postgresql://synthetic:private-password@127.0.0.1:55493/postgres')
    monkeypatch.setenv('DATABASE_SCHEMA', 'public')
    monkeypatch.setenv('ADMIN_CONTROL_DB', str(tmp_path / 'admin.sqlite3'))
    monkeypatch.setenv('ADMIN_ROLES', '{}')


def enabled():
    from marketing import website
    return website.configure(OWNER, {'enabled': True, 'dataset': 'test', 'starts_on': '2026-11-20', 'interval_minutes': 15}, 0, now=NOW)


def event(kind='visit', **changes):
    return {'id': 'website:visit:session-a', 'subject_id': 'ws_s_abc', 'kind': kind,
            'source': 'uzstock_website', 'confirmed': True, 'dataset': 'test',
            'at': (NOW - timedelta(minutes=20)).isoformat(), 'channel': 'telegram', **changes}


def page(events=(), links=(), **changes):
    return {'events': list(events), 'links': list(links), 'cursor': 12, 'done': True,
            'stats': {'observed_rows': 2, 'legacy_undated': 3}, **changes}


def link(user='ws_u_123'):
    return {'dataset': 'test', 'subject_id': 'ws_s_abc', 'user_id': user, 'observed_at': (NOW - timedelta(minutes=5)).isoformat()}


def test_source_is_opt_in_and_worker_collects_bounded_pages_with_explicit_incomplete_coverage(monkeypatch):
    from marketing import website, website_source, worker
    calls = []
    monkeypatch.setattr(website_source, 'read_page', lambda cfg, job: calls.append(job['stage']) or page([event()] if job['stage'] == 'web' else []))
    assert not website.run_one(NOW) and calls == []
    enabled()
    assert worker.tick(now=NOW)['website_work']
    assert website.run_one(NOW + timedelta(seconds=1))
    assert website.run_one(NOW + timedelta(seconds=2))
    assert calls == ['accounts', 'web', 'actions']
    assert not website.run_one(NOW + timedelta(seconds=3))
    with store.connection() as c:
        state = website.status(c)
        assert state['runtime']['status'] == 'waiting'
        assert state['runtime']['next_at'] == (NOW + timedelta(minutes=15, seconds=2)).isoformat()
        assert all(r['coverage']['status'] == 'incomplete' for r in store.list_items(c, 'coverage'))
        assert len(store.list_items(c, 'event')) == 1
    assert 'private-password' not in store.encode(state)


def test_native_revisions_and_ambiguous_identity_preserve_old_cuts_and_owner_corrections():
    from marketing import website_ledger
    first = NOW
    with store.connection(write=True) as c:
        website_ledger.ingest(c, [event()], [], first)
        original = store.list_items(c, 'event')[0]
        website_ledger.ingest(c, [event()], [link()], first + timedelta(seconds=1))
        before, _ = event_ledger.read(c, first)
        linked, _ = event_ledger.read(c, first + timedelta(seconds=1))
        assert before[0]['event']['subject_id'] == 'ws_s_abc'
        assert linked[0]['event']['subject_id'] == 'ws_u_123'
        website_ledger.ingest(c, [event(traffic='internal')], [link(None)], first + timedelta(seconds=2))
        current, _ = event_ledger.read(c, first + timedelta(seconds=2))
        assert current[0]['event']['subject_id'] == 'ws_s_abc'
        assert current[0]['event']['traffic'] == 'internal'
        assert store.get(c, 'event', original['id']) == original
        replacement = {**original['event'], 'subject_id': 'owner_checked_user', 'channel': 'linkedin'}
        event_ledger.amend(c, OWNER, [{'event_id': replacement['id'], 'dataset': 'test', 'replacement': replacement,
                                    'reason': 'Independent owner verification', 'expected_version': 0}], first + timedelta(seconds=3))
        website_ledger.ingest(c, [event(channel='facebook')], [link()], first + timedelta(seconds=4))
        current, basis = event_ledger.read(c, first + timedelta(seconds=4))
        assert current[0]['event'] == replacement
        assert [row['reason'] for row in basis] == ['Independent owner verification']


def test_repeated_identity_proof_does_not_create_revisions_without_a_changed_link():
    from marketing import website_ledger
    with store.connection(write=True) as c:
        website_ledger.ingest(c, [], [link()], NOW)
        website_ledger.ingest(c, [], [{**link(), 'observed_at': NOW.isoformat()}], NOW + timedelta(seconds=1))
        saved = store.list_items(c, 'website_identity')[0]
        assert saved['version'] == 1


@pytest.mark.parametrize('problem', ['dataset', 'invalid_event', 'missing_stats'])
def test_invalid_source_batch_is_atomic_and_records_a_redacted_error(monkeypatch, problem):
    from marketing import website, website_source
    enabled()
    batch = page([event()])
    if problem == 'dataset': batch['events'][0]['dataset'] = 'production'
    elif problem == 'invalid_event': batch['events'].append(event(id='website:bad', at='not-a-date'))
    else: del batch['stats']
    monkeypatch.setattr(website_source, 'read_page', lambda *args: batch)
    assert website.run_one(NOW)
    with store.connection() as c:
        assert store.list_items(c, 'event') == []
        assert website.status(c)['runtime']['status'] == 'error'


def test_expired_reader_cannot_commit_after_a_replacement_claim(monkeypatch):
    from marketing import website, website_source
    enabled()
    first = website._claim(NOW, False)
    assert website._claim(NOW + timedelta(seconds=89), False) is None
    second = website._claim(NOW + timedelta(seconds=91), False)
    assert second and second[1]['cursor'] == first[1]['cursor']
    assert second[1]['cutoff'] == first[1]['cutoff']
    assert not website._finish(*first, page([event()]), '', NOW + timedelta(seconds=92))
    assert website._finish(*second, page([event()]), '', NOW + timedelta(seconds=93))
    assert len(_events()) == 1


def test_late_identity_evidence_changes_new_report_but_never_frozen_snapshot():
    from marketing import website_ledger
    reports.save_settings(OWNER, {'dataset': 'test'}, 0)
    period = {'starts_on': '2026-11-23', 'ends_on': '2026-11-24'}
    registration = event('registration', id='website:registration:user-a', subject_id='ws_u_123',
                         at=(NOW - timedelta(minutes=10)).isoformat(), channel='unknown')
    with store.connection(write=True) as c:
        website_ledger.ingest(c, [event(), registration], [], NOW)
    old = reports.freeze(OWNER, 'Before identity evidence', period, 1, now=NOW)
    assert old['report']['channels']['unknown']['registrations'] == 1
    with store.connection(write=True) as c:
        website_ledger.ingest(c, [], [link()], NOW + timedelta(seconds=1))
    new = reports.recompute(OWNER, old['id'], 'Dated server identity evidence', now=NOW + timedelta(seconds=2))
    assert new['report']['channels']['telegram']['registrations'] == 1
    assert new['report']['input_digest'] != old['report']['input_digest']
    assert reports.calculate({**period, 'cutoff': NOW.isoformat()}, now=NOW + timedelta(seconds=2))['channels'] == old['report']['channels']
    with store.connection() as c:
        assert store.get(c, 'snapshot', old['id']) == old


@pytest.mark.parametrize('change', ['pause', 'disable', 'key', 'database'])
def test_inflight_read_cannot_commit_after_permission_or_source_binding_changes(monkeypatch, change):
    from marketing import delivery, website, website_source
    config = enabled()

    def fetch(cfg, job):
        if change == 'pause': delivery.set_pause(OWNER, processing=True)
        elif change == 'disable': website.configure(OWNER, {**config['data'], 'enabled': False}, config['version'], now=NOW)
        elif change == 'key': monkeypatch.setenv('MARKETING_ANALYTICS_ID_KEY', base64.urlsafe_b64encode(b'b' * 32).decode())
        else: monkeypatch.setenv('DATABASE_URL', 'postgresql://synthetic@127.0.0.1:55493/different')
        return page([event()])

    monkeypatch.setattr(website_source, 'read_page', fetch)
    website.run_one(NOW)
    with store.connection() as c:
        assert store.list_items(c, 'event') == []


def test_failed_database_read_is_redacted_and_retried_only_after_due_time(monkeypatch):
    from marketing import website, website_source
    enabled()
    calls = []
    def fail(*args):
        calls.append(True)
        raise RuntimeError('postgresql://synthetic:private-password@private-host/postgres')
    monkeypatch.setattr(website_source, 'read_page', fail)
    assert website.run_one(NOW)
    assert not website.run_one(NOW + timedelta(minutes=14))
    with store.connection() as c:
        state = website.status(c)
        assert state['runtime']['status'] == 'error'
        assert store.list_items(c, 'event') == []
        assert 'private-password' not in store.encode(store.list_items(c, 'runtime'))
    assert len(calls) == 1


def test_arrival_cut_is_after_the_database_read_not_the_claim_time(monkeypatch):
    from marketing import website, website_source
    enabled()
    moments = iter([NOW, NOW + timedelta(seconds=10)])
    class Clock:
        @staticmethod
        def now(tz):
            return next(moments)
    monkeypatch.setattr(website, 'datetime', Clock)
    monkeypatch.setattr(website_source, 'read_page', lambda *args: page([event()]))
    assert website.run_one()
    with store.connection() as c:
        before, _ = event_ledger.read(c, NOW + timedelta(seconds=5))
        after, _ = event_ledger.read(c, NOW + timedelta(seconds=10))
    assert before == [] and len(after) == 1


def test_database_password_rotation_keeps_source_and_pseudonyms_stable(monkeypatch):
    from marketing import website_source
    before = website_source.binding(), website_source._subject('u', 7)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://replacement:rotated-password@127.0.0.1:55493/postgres')
    assert (website_source.binding(), website_source._subject('u', 7)) == before


def test_database_timezone_change_does_not_revise_the_same_observation():
    from marketing import website_source, website_ledger
    from marketing.permissions import TASHKENT
    cfg = enabled()
    with store.connection(write=True) as c:
        website_ledger.ingest(c, [website_source._event(cfg, 'visit', 'ws_s_timezone', NOW)], [], NOW)
        repeated = website_ledger.ingest(c, [website_source._event(cfg, 'visit', 'ws_s_timezone', NOW.astimezone(TASHKENT))], [], NOW + timedelta(seconds=1))
        assert repeated['revised'] == repeated['imported'] == 0


def test_owner_configuration_pins_dataset_key_and_database_and_hides_secrets(monkeypatch):
    from marketing import website
    with pytest.raises(MarketingError):
        website.configure({'role': 'analytics'}, {'enabled': True, 'starts_on': '2026-11-20'}, 0, now=NOW)
    config = enabled()
    with pytest.raises(MarketingError):
        website.configure(OWNER, {**config['data'], 'dataset': 'production'}, config['version'], now=NOW)
    monkeypatch.setenv('MARKETING_ANALYTICS_ID_KEY', '')
    with pytest.raises(MarketingError):
        website.configure(OWNER, config['data'], config['version'], now=NOW)


def test_owner_http_connection_reaches_real_import_without_accepting_credentials_or_counts(client, monkeypatch):
    from marketing import website_source
    base = '/api/admin/ai-marketing'
    data = {'enabled': True, 'dataset': 'test', 'starts_on': '2026-11-20', 'interval_minutes': 15}
    body = {'expected_version': 0, 'data': data}
    assert client.put(base + '/reports/website', json={**body, 'database_url': 'not-accepted'}).status_code == 422
    saved = client.put(base + '/reports/website', json=body)
    assert saved.status_code == 200
    assert 'binding' not in saved.json()['item']
    monkeypatch.setattr(website_source, 'read_page', lambda *args: page([event()]))
    assert client.post(base + '/reports/website/sync', json={'expected_version': 0}).status_code == 409
    response = client.post(base + '/reports/website/sync', json={'expected_version': 1})
    assert response.status_code == 200 and len(_events()) == 1
    workspace = client.get(base + '/workspace')
    assert workspace.json()['website']['settings']['data']['enabled']
    assert 'private-password' not in workspace.text and 'binding' not in workspace.json()['website']['settings']
    assert 'claim' not in workspace.json()['website']['runtime']


@pytest.fixture
def native_database(pg_store, monkeypatch):
    from psycopg.conninfo import conninfo_to_dict
    import web_analytics
    dsn = pg_store.database.database_url
    monkeypatch.setenv('DATABASE_URL', dsn)
    monkeypatch.setenv('DATABASE_SCHEMA', conninfo_to_dict(dsn)['options'].split('search_path=', 1)[1])
    monkeypatch.setenv('ADMIN_EMAILS', 'team@example.test')
    monkeypatch.setattr(web_analytics, 'DATABASE_URL', dsn)
    web_analytics.init_db()
    return pg_store


@pytest.mark.parametrize('team_source', ['allowlist', 'role_env', 'role_record'])
def test_native_reader_uses_real_account_dates_session_visits_and_server_identity_only(native_database, monkeypatch, team_source):
    from identity import clock
    from marketing import website, website_source
    pg_store = native_database
    if team_source != 'allowlist':
        monkeypatch.setenv('ADMIN_EMAILS', '')
    if team_source == 'role_env':
        monkeypatch.setenv('ADMIN_ROLES', '{"team@example.test":"viewer"}')
    elif team_source == 'role_record':
        from admin_control import store as control_store
        with control_store.connection(write=True) as c:
            control_store.put(c, 'access', {'id': 'team@example.test', 'role': 'analyst', 'status': 'ACTIVE'})
    monkeypatch.setattr(clock, '_utcnow', lambda: NOW - timedelta(minutes=10))
    user, _ = pg_store.accounts.register_user('reader-private@example.test', 'example-pass-123')
    admin, _ = pg_store.accounts.register_user('team@example.test', 'example-pass-123')
    with pg_store.database.connect() as c:
        for minute, visitor, session, uid, kind, campaign in [
            (20, 'visitor-private', 'session-private', None, 'pageview', 'telegram'),
            (15, 'visitor-private', 'session-private', None, 'feature_reports', 'telegram'),
            (5, 'visitor-private', 'session-private', user.id, 'pageview', 'telegram'),
            (4, 'visitor-team', 'session-team', admin.id, 'pageview', 'telegram'),
        ]:
            c.execute('INSERT INTO web_events(ts, visitor_id, session_id, user_id, event, path, utm_source, referrer) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                      (NOW - timedelta(minutes=minute), visitor, session, uid, kind, '/?email=private@example.test', campaign, 'https://t.me/post?secret=private'))
    config = enabled()
    job = {'stage': 'accounts', 'cursor': 0, 'cutoff': NOW.isoformat()}
    accounts = website_source.read_page(config, job)
    web = website_source.read_page(config, {**job, 'stage': 'web'})
    assert [e['kind'] for e in accounts['events']].count('registration') == 2
    assert len(web['events']) == 2 and all(e['kind'] == 'visit' for e in web['events'])
    assert sum(e['traffic'] == 'internal' for e in web['events']) == 1
    assert {e['channel'] for e in web['events']} == {'telegram'}
    assert web['links'][0]['user_id'] in {e['subject_id'] for e in accounts['events']}
    serialized = store.encode([accounts, web])
    assert all(secret not in serialized for secret in ['private@example', 'reader-private', 'visitor-private', 'session-private', '?secret=', 'password'])
    assert website.run_one(NOW) and website.run_one(NOW + timedelta(seconds=1))
    reports.save_settings(OWNER, {'dataset': 'test'}, 0)
    result = reports.calculate({'starts_on': '2026-11-23', 'ends_on': '2026-11-24'}, now=NOW + timedelta(seconds=2))
    assert result['metrics']['registrations']['numerator'] == 1
    assert result['metrics']['visits']['numerator'] == 1
    assert result['metrics']['visits']['status'] == 'incomplete'
    assert result['channels']['telegram']['registrations'] == 1
    assert not any(r['event']['kind'] == 'report_open' for r in _events())
    with pg_store.database.connect() as c:
        c.execute('UPDATE web_events SET user_id=NULL WHERE user_id=%s', (user.id,))
    reread = website_source.read_page(config, {**job, 'stage': 'web'})
    reader_session = next(e['subject_id'] for e in web['events'] if e['traffic'] == 'external')
    assert next(row for row in reread['links'] if row['subject_id'] == reader_session)['user_id'] is None


def test_full_resweep_catches_late_lower_ids_and_never_counts_pages_as_visits(native_database, monkeypatch):
    from marketing import website, website_source
    monkeypatch.setattr(website_source, 'BATCH', 1)
    delayed = native_database.database.connect()
    try:
        delayed.execute('INSERT INTO web_events(ts,visitor_id,session_id,event,path) VALUES (%s,%s,%s,%s,%s)',
                        (NOW - timedelta(minutes=10), 'visitor-delayed', 'session-delayed', 'pageview', '/'))
        with native_database.database.connect() as c:
            c.execute('INSERT INTO web_events(ts,visitor_id,session_id,event,path) VALUES (%s,%s,%s,%s,%s)',
                      (NOW - timedelta(minutes=8), 'visitor-first', 'session-first', 'pageview', '/'))
            c.execute('INSERT INTO web_events(ts,visitor_id,session_id,event,path) VALUES (%s,%s,%s,%s,%s)',
                      (NOW - timedelta(minutes=7), 'visitor-first', 'session-first', 'pageview', '/markets'))
        enabled()
        for second in range(5):
            website.run_one(NOW + timedelta(seconds=second))
        assert len(_events()) == 1
        delayed.commit()
        assert website.run_one(NOW + timedelta(minutes=1), force=True)
        for second in range(1, 6):
            website.run_one(NOW + timedelta(minutes=1, seconds=second))
        assert len(_events()) == 2
    finally:
        delayed.close()


def _events():
    with store.connection() as c:
        return store.list_items(c, 'event')


def test_successful_action_receipts_import_exact_objects_and_do_not_guess_ambiguous_identity(native_database, monkeypatch):
    import product_events as pe
    from test_product_events import action
    from marketing import website, website_source
    monkeypatch.setattr(pe, '_now', lambda: NOW-timedelta(seconds=1))
    first, _ = native_database.accounts.register_user('reader-a@example.test', 'example-pass-123')
    second, _ = native_database.accounts.register_user('reader-b@example.test', 'example-pass-123')
    visitor, session = 'visitor_test_123', 'session_test_123'
    with native_database.database.connect() as c:
        c.execute('INSERT INTO web_events(ts,visitor_id,session_id,user_id,event,path,utm_source) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                  (NOW-timedelta(minutes=5), visitor, session, first.id, 'pageview', '/company/UZTL', 'telegram'))
    payload = action(observed_at=(NOW-timedelta(minutes=1)).isoformat())
    pe.record(pe.Action.model_validate(payload), user_id=second.id, internal=False, automated=False)
    cfg = enabled()
    job = {'stage': 'actions', 'cursor': 0, 'cutoff': NOW.isoformat()}
    page = website_source.read_page(cfg, job)
    assert len(page['events']) == 1
    receipt = page['events'][0]
    assert receipt['kind'] == 'report_open' and receipt['object_id'] == 'report:UZTL:nsbu:separate:2025Q4:ru:report-v2'
    assert receipt['subject_id'] == website_source._subject('u', second.id)
    assert page['links'][0]['user_id'] is None  # shared browser, two authenticated identities
    web = website_source.read_page(cfg, {**job, 'stage': 'web'})
    assert web['links'][0]['user_id'] is None
    assert not website_source.read_page(cfg, {**job, 'cutoff': (NOW-timedelta(seconds=2)).isoformat()})['events']
    for second_offset in range(3):
        assert website.run_one(NOW+timedelta(seconds=second_offset))
    assert [r['event'] for r in _events() if r['event']['kind'] == 'report_open'] == [
        __import__('marketing.analytics', fromlist=['Event']).Event.model_validate(receipt).model_dump(mode='json')]
    assert all(secret not in store.encode(_events()) for secret in ['reader-a', 'reader-b', visitor, session])


def test_publication_receipt_waits_for_visibility_without_losing_arrival_or_frozen_cuts(native_database, monkeypatch):
    import uuid
    import product_events as pe
    from marketing import content, publication_links, website_source, website_ledger
    from test_marketing_core import account, candidate
    monkeypatch.setattr(store, 'now', lambda: (NOW-timedelta(minutes=20)).isoformat())
    account()
    cfg = enabled()
    # Dataset is bound when issuing the link, not accepted from the browser.
    reports.save_settings(OWNER, {'dataset': 'test'}, 0)
    item = candidate(track_visits=True)
    with store.connection(write=True) as c:
        store.put(c, 'delivery', {'id': item['id'], 'candidate_id': item['id'], 'status': 'submitted',
            'external_account_id': '-100123',
            'content_digest': content.content_digest(item), 'provider_requested_at': (NOW-timedelta(minutes=10)).isoformat()},
            actor=OWNER, action='test_submitted', expected_version=0)
    raw = {'event_id': str(uuid.uuid4()), 'visitor_id': 'visitor_publication', 'session_id': 'session_publication',
           'language': 'ru', 'kind': 'publication_visit', 'observed_at': (NOW-timedelta(minutes=5)).isoformat(),
           'publication_token': item['tracking']['token'], 'route_fingerprint': publication_links.fingerprint(item['destination_url'])}
    monkeypatch.setattr(pe, '_now', lambda: NOW-timedelta(minutes=5))
    pe.record(pe.Action.model_validate(raw), user_id=None, internal=False, automated=False)
    job = {'stage': 'actions', 'cursor': 0, 'cutoff': NOW.isoformat()}
    assert website_source.read_page(cfg, job)['events'] == []
    monkeypatch.setattr(store, 'now', lambda: NOW.isoformat())
    with store.connection(write=True) as c:
        store.put(c, 'candidate', {**item, 'status': 'published'}, actor=OWNER, action='test_confirmed', expected_version=item['version'])
        delivery = store.get(c, 'delivery', item['id'])
        store.put(c, 'delivery', {**delivery, 'status': 'published'}, actor=OWNER, action='test_confirmed', expected_version=delivery['version'])
    result = website_source.read_page(cfg, job)
    assert len(result['events']) == 1
    arrival = result['events'][0]
    assert arrival['kind'] == 'publication_visit' and arrival['publication_id'] == item['id']
    assert arrival['channel'] == 'telegram' and arrival['promotion'] == 'organic'
    assert arrival['at'] == (NOW-timedelta(minutes=5)).isoformat()
    assert not website_source.read_page(cfg, {**job, 'cutoff': (NOW-timedelta(seconds=1)).isoformat()})['events']
    assert not website_source.read_page({**cfg, 'data': {**cfg['data'], 'dataset': 'production'}}, job)['events']
    with store.connection(write=True) as c:
        website_ledger.ingest(c, result['events'], result['links'], NOW)
        assert event_ledger.read(c, NOW-timedelta(seconds=1))[0] == []
        assert event_ledger.read(c, NOW)[0][0]['event']['publication_id'] == item['id']
    assert all(private not in store.encode(_events()) for private in [raw['visitor_id'], raw['session_id'], raw['publication_token'], raw['route_fingerprint']])
