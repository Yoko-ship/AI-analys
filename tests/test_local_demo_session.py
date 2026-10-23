from fastapi.testclient import TestClient
import pytest

import api
import web_auth
from tests.test_postgres_accounts import pg_store  # noqa: F401


@pytest.fixture
def local_account(pg_store, monkeypatch):
    user, _ = pg_store.accounts.register_user('local-demo@localhost.test', 'example-pass-123')
    monkeypatch.setattr(web_auth, 'web_auth_store', pg_store)
    monkeypatch.setenv('APP_ENV', 'local')
    monkeypatch.setenv('LOCAL_DEMO_USER_ID', str(user.id))
    return pg_store, user


def test_local_demo_issues_normal_sessions_for_the_same_free_account(local_account):
    store, user = local_account
    client = TestClient(api.app, base_url='http://localhost:8000', client=('127.0.0.1', 12345))
    first = client.post('/api/auth/local-session')
    assert first.status_code == 200, first.text
    assert first.json()['user']['id'] == user.id
    assert first.json()['user']['tier'] == 'free'
    assert first.json()['user']['is_admin'] is False
    assert first.headers['cache-control'] == 'no-store'
    token = first.json()['token']
    assert store.sessions.get_user_by_token(token).id == user.id
    store.sessions.revoke_token(token)
    second = client.post('/api/auth/local-session').json()
    assert second['token'] != token
    assert store.sessions.get_user_by_token(second['token']).id == user.id


@pytest.mark.parametrize('case', ['production', 'disabled', 'remote_peer', 'remote_host', 'foreign_origin', 'remote_database'])
def test_local_demo_is_unavailable_outside_explicit_local_use(local_account, monkeypatch, case):
    store, _ = local_account
    host, peer, headers = 'http://localhost:8000', '127.0.0.1', {}
    if case == 'production': monkeypatch.setenv('APP_ENV', 'production')
    if case == 'disabled': monkeypatch.delenv('LOCAL_DEMO_USER_ID')
    if case == 'remote_peer': peer = '192.0.2.10'
    if case == 'remote_host': host = 'http://uzstock.uz'
    if case == 'foreign_origin': headers['Origin'] = 'https://example.org'
    if case == 'remote_database': monkeypatch.setattr(store.database, 'database_url', 'postgresql://example.org/app')
    client = TestClient(api.app, base_url=host, client=(peer, 12345))
    assert client.post('/api/auth/local-session', headers=headers).status_code == 404


def test_local_demo_cannot_open_an_administrative_account(local_account, monkeypatch):
    _, user = local_account
    monkeypatch.setenv('ADMIN_EMAILS', user.email)
    client = TestClient(api.app, base_url='http://localhost:8000', client=('127.0.0.1', 12345))
    assert client.post('/api/auth/local-session').status_code == 404
