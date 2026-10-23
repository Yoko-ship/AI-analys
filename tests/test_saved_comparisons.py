"""Authenticated comparison storage contracts, including ownership boundaries."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api
import web_auth

PAYLOAD = {'name': 'Bank coverage', 'tickers': ['HMKB', 'IPKY'], 'period': 'latest',
           'standard': 'NSBU', 'scope': 'separate', 'unit': 'billion'}


class Connection:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), params))
        result = self.results.pop(0)
        return SimpleNamespace(fetchone=lambda: result, fetchall=lambda: result or [], rowcount=int(bool(result)))


def row():
    return {'id': 13, 'name': PAYLOAD['name'], 'selection': {k: v for k, v in PAYLOAD.items() if k != 'name'},
            'created_at': datetime(2026, 10, 23, tzinfo=timezone.utc), 'updated_at': datetime(2026, 10, 23, tzinfo=timezone.utc)}


def test_storage_lists_and_deletes_only_for_the_authenticated_owner():
    from identity.comparisons import Comparisons
    conn = Connection([[row()], None])
    store = Comparisons(SimpleNamespace(connect=lambda: conn))
    saved = store.list(7)
    assert saved[0]['id'] == '13' and saved[0]['selection']['tickers'] == ['HMKB', 'IPKY']
    assert 'user_id' not in saved[0]
    assert store.delete(8, 13) is False
    assert conn.calls[0][1] == (7,)
    assert 'WHERE user_id = %s' in conn.calls[0][0]
    assert 'id = %s AND user_id = %s' in conn.calls[1][0]
    assert conn.calls[1][1] == (13, 8)


@pytest.mark.parametrize('patch', [
    {'name': ' '}, {'name': 'x' * 81}, {'tickers': ['HMKB']}, {'tickers': ['HMKB', 'HMKB']},
    {'tickers': ['HMKB', '../secret']}, {'tickers': ['HMKB', 'IPKY', 'SQBN', 'UZTL', 'UZMK']},
    {'period': '2025Q9'}, {'standard': 'GAAP'}, {'scope': 'mixed'}, {'unit': 'dollar'},
])
def test_invalid_selections_are_rejected_before_database_access(patch):
    from identity.comparisons import Comparisons
    def unexpected(): raise AssertionError('Invalid input reached database')
    with pytest.raises(ValueError):
        Comparisons(SimpleNamespace(connect=unexpected)).save(7, {**PAYLOAD, **patch})


def test_api_requires_authentication_and_never_caches_account_data(monkeypatch):
    monkeypatch.setattr(web_auth.web_auth_store.sessions, 'get_user_by_token', lambda t: SimpleNamespace(id=7) if t == 'alice' else None)
    from identity.comparisons import public
    repository = SimpleNamespace(list=lambda uid: [public(row())])
    monkeypatch.setattr(web_auth.web_auth_store, 'comparisons', repository, raising=False)
    client = TestClient(api.app)
    for prefix in ['/api', '/api/v2']:
        path = prefix + '/saved-comparisons'
        assert client.get(path).status_code == 401
        assert client.post(path, json=PAYLOAD).status_code == 401
        assert client.delete(path + '/13').status_code == 401
        result = client.get(path, headers={'Authorization': 'Bearer alice'})
        assert result.status_code == 200
        assert result.headers['cache-control'] == 'no-store'


def test_http_writes_derive_owner_from_session_and_reject_spoofing(monkeypatch):
    from server.comparison import service
    monkeypatch.setattr(service, 'compare', lambda *args, **kw: {'companies': [], 'currency': 'UZS'})
    calls = []
    monkeypatch.setattr(web_auth.web_auth_store.sessions, 'get_user_by_token', lambda t: SimpleNamespace(id=7) if t == 'alice' else SimpleNamespace(id=8))
    def save(uid, data, snapshot=None):
        calls.append((uid, data))
        return {'id': '13', 'name': data['name'], 'selection': {k: v for k, v in data.items() if k != 'name'}}
    repository = SimpleNamespace(save=save, delete=lambda uid, identifier: uid == 7)
    monkeypatch.setattr(web_auth.web_auth_store, 'comparisons', repository, raising=False)
    client = TestClient(api.app)
    headers = {'Authorization': 'Bearer alice'}
    response = client.post('/api/saved-comparisons', headers=headers, json=PAYLOAD)
    assert response.status_code == 200
    assert calls[0][0] == 7
    assert response.json()['comparison']['selection']['period'] == 'latest'
    assert response.headers['cache-control'] == 'no-store'
    assert client.post('/api/saved-comparisons', headers=headers, json={**PAYLOAD, 'user_id': 8}).status_code == 422
    assert client.post('/api/saved-comparisons', headers=headers, json={**PAYLOAD, 'tickers': ['HMKB']}).status_code == 422
    assert client.delete('/api/saved-comparisons/13', headers={'Authorization': 'Bearer bob'}).status_code == 404
    assert client.delete('/api/saved-comparisons/13', headers=headers).status_code == 200


def test_storage_failure_never_looks_like_an_empty_list(monkeypatch):
    monkeypatch.setattr(web_auth.web_auth_store.sessions, 'get_user_by_token', lambda t: SimpleNamespace(id=7))
    def unavailable(uid): raise RuntimeError('database unavailable')
    monkeypatch.setattr(web_auth.web_auth_store, 'comparisons', SimpleNamespace(list=unavailable), raising=False)
    response = TestClient(api.app).get('/api/saved-comparisons', headers={'Authorization': 'Bearer alice'})
    assert response.status_code == 503
    assert response.headers['cache-control'] == 'no-store'
