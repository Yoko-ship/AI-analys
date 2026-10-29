"""Anonymous, explicit ratings are durable feedback, not best-effort analytics."""
from types import SimpleNamespace
from uuid import uuid4
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
import api
import analytics_api
from identity.support import Support
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
    assert calls == [body]


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


def test_rating_persistence_is_idempotent_and_admin_summary_includes_all_scores():
    calls = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            calls.append((' '.join(sql.split()), params))
            if 'GROUP BY' in sql:
                return SimpleNamespace(fetchall=lambda: [{'rating': 1, 'count': 2}, {'rating': 3, 'count': 4}])
            return SimpleNamespace(fetchall=lambda: [{'rating': 3, 'page_path': '/market', 'language': 'uz',
                'created_at': datetime(2026, 10, 29, tzinfo=timezone.utc)}])
    support = Support(SimpleNamespace(connect=Connection))
    body = payload()
    support.create_site_rating(**body)
    sql, values = calls[0]
    assert 'ON CONFLICT (response_id) DO NOTHING' in sql
    assert values == (body['response_id'], 3, '/company/HMKB', 'en')
    result = support.list_site_ratings()
    assert result['counts'] == {'1': 2, '2': 0, '3': 4}
    assert result['total'] == 6
    assert result['items'][0]['created_at'] == '2026-10-29T00:00:00+00:00'
