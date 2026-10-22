from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

import api
import web_auth
import securities_catalog
import catalogue.market_store as market
from tests.test_web_entitlements import _user
from tests.test_portfolio_ledger import trade, SECURITIES


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token", lambda token: _user(tier="pro"))
    monkeypatch.setattr(securities_catalog, "get_securities_map", lambda: SECURITIES)
    monkeypatch.setattr(market, "get_all_listings", lambda: {})
    monkeypatch.setattr(market, "get_all_trade_stats", lambda: {})
    monkeypatch.setattr(market, "get_all_quotes", lambda: {
        "UZ7001560000": {"close_price": 589, "trade_date": "20261021"}})
    return TestClient(api.app, headers={"Authorization": "Bearer portfolio-test"})


def test_portfolio_uses_stored_data_and_never_fetches_openinfo_per_view(client, monkeypatch):
    monkeypatch.setattr(web_auth.web_auth_store.portfolio, "list_transactions", lambda user_id: [trade()], raising=False)
    response = client.get("/api/portfolio")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["market_value"] == "5890"
    assert data["transactions"][0]["ticker"] == "AGBA"
    assert data["items"][0]["price_date"] == "2026-10-21"
    assert data["refresh_interval_seconds"] == 30
    assert "no-store" in response.headers["cache-control"]


def test_post_normalizes_input_and_only_uses_authenticated_owner(client, monkeypatch):
    calls = []
    def save(user_id, key, payload):
        calls.append((user_id, key, payload))
        return dict(payload, id=key, version=1)
    monkeypatch.setattr(web_auth.web_auth_store.portfolio, "add_transaction", save, raising=False)
    key = str(uuid4())
    payload = {k: v for k, v in trade(ticker=" agba ").items() if k not in {"id", "sequence"}}
    response = client.post("/api/portfolio/transactions", json=dict(payload, id=key))
    assert response.status_code == 200, response.text
    assert calls[0][0] == 101 and calls[0][1] == key and calls[0][2]["ticker"] == "AGBA"
    assert response.json()["transaction"]["quantity"] == "10"
    assert client.post("/api/portfolio/transactions", json=dict(payload, id=key, user_id=999)).status_code == 422


@pytest.mark.parametrize("patch", [{"quantity": "NaN"}, {"price": "Infinity"}, {"fees": "-1"}, {"trade_date": "2999-01-01"}])
def test_api_rejects_invalid_transactions_before_any_write(client, monkeypatch, patch):
    monkeypatch.setattr(web_auth.web_auth_store.portfolio, "add_transaction",
                        lambda *a, **k: pytest.fail("invalid transaction reached storage"), raising=False)
    payload = {k: v for k, v in trade().items() if k not in {"id", "sequence"}}
    assert client.post("/api/portfolio/transactions", json={**payload, "id": str(uuid4()), **patch}).status_code == 422


def test_portfolio_and_mutations_require_account_and_pro_entitlement(client, monkeypatch):
    for user, status in [(None, 401), (_user(), 403)]:
        monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token", lambda token: user)
        assert client.get("/api/portfolio").status_code == status
        assert client.post("/api/portfolio/transactions", json={}).status_code == status
        assert client.put("/api/portfolio/transactions/example", json={}).status_code == status
        assert client.delete("/api/portfolio/transactions/example?version=1").status_code == status


def test_api_surfaces_edit_conflicts_and_ownership_without_leaking_records(client, monkeypatch):
    def fail(*a, **k):
        raise ValueError("VERSION_CONFLICT")
    monkeypatch.setattr(web_auth.web_auth_store.portfolio, "delete_transaction", fail, raising=False)
    assert client.delete("/api/portfolio/transactions/example?version=1").status_code == 409
    def missing(*a, **k):
        raise ValueError("TRANSACTION_NOT_FOUND")
    monkeypatch.setattr(web_auth.web_auth_store.portfolio, "delete_transaction", missing, raising=False)
    assert client.delete("/api/portfolio/transactions/example?version=1").status_code == 404
