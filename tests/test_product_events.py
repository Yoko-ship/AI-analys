"""Durable, bounded observations of successful UI actions, never arbitrary text."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from test_postgres_accounts import pg_store  # noqa: F401

NOW = datetime(2026, 11, 23, 10, tzinfo=timezone.utc)


def action(**changes):
    return {'event_id': str(uuid.uuid4()), 'observed_at': NOW.isoformat(),
            'visitor_id': 'visitor_test_123', 'session_id': 'session_test_123',
            'kind': 'report_open', 'ticker': 'UZTL', 'language': 'ru',
            'standard': 'nsbu', 'scope': 'separate', 'period': '2025Q4', 'version': 'report-v2', **changes}


@pytest.fixture
def receipts(pg_store, monkeypatch):
    import web_analytics
    import product_events
    monkeypatch.setattr(web_analytics, 'DATABASE_URL', pg_store.database.database_url)
    monkeypatch.setattr(product_events, '_now', lambda: NOW)
    assert web_analytics.init_db() and web_analytics.init_db()
    return pg_store


def test_durable_receipt_has_server_arrival_identity_and_exact_object(receipts):
    import product_events as pe
    payload = pe.Action.model_validate(action(observed_at=(NOW-timedelta(seconds=4)).isoformat()))
    assert pe.record(payload, user_id=17, internal=True, automated=False)
    assert not pe.record(payload, user_id=17, internal=True, automated=False)
    with receipts.database.connect() as c:
        rows = c.execute('SELECT * FROM web_product_events').fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row['user_id'] == 17 and row['traffic'] == 'internal'
    assert row['received_at'] == NOW and row['observed_at'] == NOW-timedelta(seconds=4)
    assert row['object_id'] == 'report:UZTL:nsbu:separate:2025Q4:ru:report-v2'
    with pytest.raises(pe.ReceiptConflict):
        pe.record(payload.model_copy(update={'ticker': 'HMKB'}), user_id=17, internal=True, automated=False)
    with pytest.raises(pe.ReceiptConflict):
        pe.record(payload, user_id=18, internal=True, automated=False)
    with receipts.database.connect() as c:
        assert c.execute('SELECT count(*) AS n FROM web_product_events').fetchone()['n'] == 1


def test_publication_arrival_uses_server_clock_and_no_browser_channel_claim(receipts):
    import product_events as pe
    raw = {key: value for key, value in action().items() if key in {'event_id', 'visitor_id', 'session_id', 'language'}}
    raw.update(kind='publication_visit', observed_at=(NOW-timedelta(minutes=3)).isoformat(),
               publication_token='a'*32, route_fingerprint='b'*64)
    arrival = pe.Action.model_validate(raw)
    assert pe.record(arrival, user_id=None, internal=False, automated=False)
    assert not pe.record(arrival, user_id=None, internal=False, automated=False)
    with receipts.database.connect() as c:
        row = c.execute('SELECT * FROM web_product_events').fetchone()
    assert row['observed_at'] == row['received_at'] == NOW
    assert row['object_id'] == 'publication:' + 'a'*32
    for changes in [{'channel': 'telegram'}, {'destination_url': 'https://uzstock.uz/news/1'}, {'publication_token': 'bad'}, {'route_fingerprint': None}, {'ticker': 'HMKB'}]:
        with pytest.raises(ValueError):
            pe.Action.model_validate({**raw, **changes})


@pytest.mark.parametrize('changes', [
    {'uid': 88}, {'query': 'private@example.test'}, {'ticker': 'private@example.test'},
    {'version': ''}, {'period': ''}, {'scope': None}, {'news_id': 45}, {'kind': 'payment'},
    {'observed_at': '2026-11-23T10:00:00'},
])
def test_receipt_rejects_unbound_or_private_fields(changes):
    import product_events as pe
    with pytest.raises(ValueError):
        pe.Action.model_validate(action(**changes))


def test_search_representation_and_clock_bounds(receipts):
    import product_events as pe
    raw = {key: value for key, value in action().items() if key in {'event_id', 'observed_at', 'visitor_id', 'session_id', 'language'}}
    search = pe.Action.model_validate({**raw, 'kind': 'search_empty', 'query_type': 'other', 'result_count': 0, 'search_scope': 'complete', 'search_area': 'news_feed'})
    assert pe.record(search, user_id=None, internal=False, automated=True)
    for change in [{'result_count': 2}, {'ticker': 'UZTL'}, {'search_scope': 'partial'}]:
        with pytest.raises(ValueError):
            pe.Action.model_validate({**search.model_dump(), **change})
    for clock in [NOW + timedelta(minutes=3), NOW-timedelta(days=2)]:
        with pytest.raises(pe.ReceiptClockError):
            pe.record(search.model_copy(update={'observed_at': clock, 'event_id': uuid.uuid4()}), user_id=None, internal=False, automated=False)


def test_report_version_supports_the_existing_link_contract_without_losing_object_identity():
    import product_events as pe
    first = pe.Action.model_validate(action(version='a'*200))
    second = pe.Action.model_validate(action(version='b'*200))
    assert len(first.object_id()) <= 200
    assert first.object_id() != second.object_id()
    assert first.model_dump()['version'] == 'a'*200


@pytest.fixture
def client(monkeypatch):
    import analytics_api
    app = FastAPI()
    app.include_router(analytics_api.public_router)
    monkeypatch.setattr(analytics_api.auth_limits._rate_limiter, 'allow', lambda *args: True)
    with TestClient(app) as client:
        yield client


def test_http_receipt_requires_commit_and_never_trusts_body_identity(client, receipts, monkeypatch):
    import product_events_api as api
    monkeypatch.setattr(api, '_require_user', lambda token: SimpleNamespace(id=23, email='reader@example.test'))
    payload = action()
    response = client.post('/api/track/actions', json=payload, headers={'Authorization': 'Bearer synthetic'})
    assert response.status_code == 200 and response.json() == {'ok': True}
    assert client.post('/api/track/actions', json={**payload, 'uid': 999}).status_code == 422
    with receipts.database.connect() as c:
        assert c.execute('SELECT user_id FROM web_product_events').fetchone()['user_id'] == 23
    def unavailable(*args, **kwargs):
        raise RuntimeError('private-db-password')
    monkeypatch.setattr(api.events, 'record', unavailable)
    result = client.post('/api/track/actions', json=action())
    assert result.status_code == 503 and 'private-db' not in result.text
    def expired(_token):
        raise HTTPException(401, 'Expired')
    monkeypatch.setattr(api, '_require_user', expired)
    assert client.post('/api/track/actions', json=action(), headers={'Authorization': 'Bearer expired'}).status_code == 401
    assert client.post('/api/track/actions', content='x'*5000).status_code == 413
