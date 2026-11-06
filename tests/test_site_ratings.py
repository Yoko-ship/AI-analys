"""Explicit ratings are durable feedback with optional verified account attribution."""
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
import api
import analytics_api
from identity.support import Support
from identity import schema
from server.auth import limits


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(limits, '_rate_limiter', limits._SlidingWindowLimiter())
    return TestClient(api.app)


def payload(**changes):
    return dict(response_id=str(uuid4()), rating=3, page_path='/company/HMKB', language='en', **changes)


def test_guest_can_submit_rating_without_account_or_text(client, monkeypatch):
    calls = []
    monkeypatch.setattr(analytics_api.web_auth_store.support, 'create_site_rating',
                        lambda **values: calls.append(values), raising=False)
    body = payload()
    response = client.post('/api/feedback/ratings', json=body)
    assert response.status_code == 200
    assert response.json() == {'ok': True}
    assert calls == [{**body, 'user_id': None}]


def test_signed_in_rating_uses_verified_session_account(client, monkeypatch):
    calls, tokens = [], []
    def resolve(token):
        tokens.append(token)
        return SimpleNamespace(id=17)
    monkeypatch.setattr(analytics_api.web_auth_store.sessions, 'get_user_by_token', resolve)
    monkeypatch.setattr(analytics_api.web_auth_store.support, 'create_site_rating',
                        lambda **values: calls.append(values))
    body = payload()
    response = client.post('/api/feedback/ratings', json=body,
                           headers={'Authorization': 'Bearer rating-session'})
    assert response.status_code == 200
    assert tokens == ['rating-session']
    assert calls == [{**body, 'user_id': 17}]


@pytest.mark.parametrize('authorization', ['Bearer expired', 'Basic invalid', 'Bearer '])
def test_invalid_session_does_not_silently_save_anonymous_rating(client, monkeypatch, authorization):
    calls = []
    monkeypatch.setattr(analytics_api.web_auth_store.sessions, 'get_user_by_token', lambda token: None)
    monkeypatch.setattr(analytics_api.web_auth_store.support, 'create_site_rating',
                        lambda **values: calls.append(values))
    response = client.post('/api/feedback/ratings', json=payload(), headers={'Authorization': authorization})
    assert response.status_code == 401
    assert not calls


def test_session_lookup_failure_does_not_lose_rating_attribution(client, monkeypatch):
    calls = []
    def unavailable(token):
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(analytics_api.web_auth_store.sessions, 'get_user_by_token', unavailable)
    monkeypatch.setattr(analytics_api.web_auth_store.support, 'create_site_rating',
                        lambda **values: calls.append(values))
    response = client.post('/api/feedback/ratings', json=payload(), headers={'Authorization': 'Bearer session'})
    assert response.status_code == 503
    assert not calls


@pytest.mark.parametrize('field,value', [('rating', 0), ('rating', 4), ('rating', True),
    ('rating', '3'), ('rating', 1.5), ('language', 'xx'), ('response_id', 'bad'),
    ('page_path', 'https://example.com/'), ('page_path', '/?token=secret'),
    ('page_path', '/#token=secret'), ('page_path', '//example.com'), ('user_id', 7)])
def test_rating_validation(client, field, value):
    body = payload()
    body[field] = value
    assert client.post('/api/feedback/ratings', json=body).status_code == 422


def test_rating_write_failure_is_visible_and_rate_limit_has_retry_after(client, monkeypatch):
    def unavailable(**values):
        raise RuntimeError('database unavailable')
    monkeypatch.setattr(analytics_api.web_auth_store.support, 'create_site_rating', unavailable, raising=False)
    assert client.post('/api/feedback/ratings', json=payload()).status_code == 503
    monkeypatch.setattr(limits._rate_limiter, 'allow', lambda *args: False)
    response = client.post('/api/feedback/ratings', json=payload())
    assert response.status_code == 429
    assert int(response.headers['retry-after']) > 0


def test_rating_results_are_private(client):
    assert client.get('/api/admin/feedback/ratings').status_code in (401, 403)


def test_existing_ratings_gain_nullable_account_link_without_backfill():
    statements = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            statements.append(' '.join(sql.split()))
    schema.initialize(Connection)
    migration = next((sql for sql in statements if sql.startswith('ALTER TABLE web_site_ratings')), '')
    assert 'ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES web_users(id) ON DELETE SET NULL' in migration
    assert 'NOT NULL' not in migration and 'DEFAULT' not in migration
    assert not any(sql.startswith('UPDATE web_site_ratings') for sql in statements)


@pytest.mark.parametrize('user_id', [None, 17])
def test_rating_persistence_is_idempotent_and_admin_summary_includes_all_scores(user_id):
    calls = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            calls.append((' '.join(sql.split()), params))
            if 'INSERT INTO' in sql:
                return None
            if 'GROUP BY' in sql:
                return SimpleNamespace(fetchall=lambda: [{'rating': 1, 'count': 2}, {'rating': 3, 'count': 4}])
            assert 'LEFT JOIN web_users' in sql
            assert 'u.full_name' in sql and 'u.email' in sql and 'r.user_id' in sql
            return SimpleNamespace(fetchall=lambda: [{'rating': 3, 'page_path': '/market', 'language': 'uz',
                'user_id': user_id, 'full_name': 'Reader' if user_id else None,
                'email': 'reader@example.test' if user_id else None,
                'created_at': datetime(2026, 10, 29, tzinfo=timezone.utc)}])
    support = Support(SimpleNamespace(connect=Connection))
    body = payload()
    support.create_site_rating(**body, user_id=user_id)
    sql, values = calls[0]
    assert 'ON CONFLICT (response_id) DO NOTHING' in sql
    assert values == (body['response_id'], 3, '/company/HMKB', 'en', user_id)
    result = support.list_site_ratings()
    assert result['counts'] == {'1': 2, '2': 0, '3': 4}
    assert result['total'] == 6
    assert result['items'][0]['created_at'] == '2026-10-29T00:00:00+00:00'
    assert result['items'][0]['user_id'] == user_id
    assert result['items'][0]['email'] == ('reader@example.test' if user_id else None)
