"""Real database contracts: atomic replay, ownership, retries and migration."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from tests.test_postgres_accounts import pg_store  # noqa: F401
from tests.test_portfolio_ledger import trade


def investor(store, name="investor"):
    return store.accounts.register_user(f"{name}@example.test", "example-pass-123")[0]


def add(store, user, **kwargs):
    return store.portfolio.add_transaction(user.id, str(uuid4()), trade(**kwargs))


def test_retries_are_idempotent_and_other_users_cannot_change_transactions(pg_store):
    user, other = investor(pg_store), investor(pg_store, "other")
    key = str(uuid4())
    first = pg_store.portfolio.add_transaction(user.id, key, trade())
    assert pg_store.portfolio.add_transaction(user.id, key, trade()) == first
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        pg_store.portfolio.add_transaction(user.id, key, trade(quantity="11"))
    assert pg_store.portfolio.list_transactions(other.id) == []
    with pytest.raises(ValueError, match="TRANSACTION_NOT_FOUND"):
        pg_store.portfolio.update_transaction(other.id, key, trade(), version=1)
    with pytest.raises(ValueError, match="TRANSACTION_NOT_FOUND"):
        pg_store.portfolio.delete_transaction(other.id, key, version=1)
    assert len(pg_store.portfolio.list_transactions(user.id)) == 1


def test_corrections_replay_the_whole_ledger_and_rollback_invalid_changes(pg_store):
    user = investor(pg_store)
    buy = add(pg_store, user)
    sell = add(pg_store, user, kind="sell", quantity="5", price="120", day="2026-02-01")
    with pytest.raises(ValueError, match="INSUFFICIENT_SHARES"):
        pg_store.portfolio.delete_transaction(user.id, buy["id"], version=1)
    with pytest.raises(ValueError, match="INSUFFICIENT_SHARES"):
        pg_store.portfolio.update_transaction(user.id, buy["id"], trade(quantity="4"), version=1)
    updated = pg_store.portfolio.update_transaction(user.id, buy["id"], trade(price="110"), version=1)
    assert updated["version"] == 2
    with pytest.raises(ValueError, match="VERSION_CONFLICT"):
        pg_store.portfolio.update_transaction(user.id, buy["id"], trade(price="100"), version=1)
    pg_store.portfolio.delete_transaction(user.id, sell["id"], version=1)
    assert pg_store.portfolio.list_portfolio_positions(user.id)[0]["quantity"] == 10


def test_concurrent_sales_serialize_before_checking_the_remaining_quantity(pg_store):
    user = investor(pg_store)
    add(pg_store, user)
    def sell(_):
        try:
            add(pg_store, user, kind="sell", quantity="7", day="2026-02-01")
            return "ok"
        except ValueError as exc:
            return str(exc).split(":")[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(sell, range(2))) == ["INSUFFICIENT_SHARES", "ok"]
    assert pg_store.portfolio.list_portfolio_positions(user.id)[0]["quantity"] == 3


def test_existing_positions_migrate_once_without_invented_dates_or_resurrection(pg_store):
    from identity.schema import initialize
    user = investor(pg_store)
    with pg_store.database.connect() as conn:
        conn.execute("""INSERT INTO web_portfolio_positions (user_id, ticker, quantity, average_cost, note)
                     VALUES (%s, 'AGBA', 100, 589.25, 'Original holding')""", (user.id,))
    initialize(pg_store.database.connect)
    initialize(pg_store.database.connect)
    rows = pg_store.portfolio.list_transactions(user.id)
    assert len(rows) == 1
    assert rows[0]["kind"] == "opening" and rows[0]["trade_date"] is None
    assert rows[0]["note"] == "Original holding"
    assert pg_store.portfolio.list_portfolio_positions(user.id)[0]["cost_value"] == 58925
    pg_store.portfolio.delete_transaction(user.id, rows[0]["id"], version=1)
    initialize(pg_store.database.connect)
    assert pg_store.portfolio.list_transactions(user.id) == []


def test_legacy_position_endpoint_cannot_silently_overwrite_transaction_history(pg_store):
    user = investor(pg_store)
    pg_store.portfolio.upsert_portfolio_position(user.id, "AGBA", quantity=10, average_cost=100)
    assert pg_store.portfolio.list_portfolio_positions(user.id)[0]["quantity"] == 10
    add(pg_store, user, kind="sell", quantity="2")
    with pytest.raises(ValueError, match="USE_TRANSACTION_HISTORY"):
        pg_store.portfolio.upsert_portfolio_position(user.id, "AGBA", quantity=20, average_cost=120)
    with pytest.raises(ValueError, match="USE_TRANSACTION_HISTORY"):
        pg_store.portfolio.delete_portfolio_position(user.id, "AGBA")


def test_deleting_account_cascades_private_investment_records(pg_store):
    user = investor(pg_store)
    add(pg_store, user)
    with pg_store.database.connect() as conn:
        conn.execute("DELETE FROM web_users WHERE id=%s", (user.id,))
        assert conn.execute("SELECT count(*) AS n FROM web_portfolio_transactions").fetchone()["n"] == 0


def test_deleted_submission_cannot_be_replayed_and_legacy_precision_is_preserved(pg_store):
    from identity.schema import initialize
    from decimal import Decimal
    user = investor(pg_store)
    key = str(uuid4())
    pg_store.portfolio.add_transaction(user.id, key, trade())
    pg_store.portfolio.delete_transaction(user.id, key, version=1)
    with pytest.raises(ValueError, match='IDEMPOTENCY_CONFLICT'):
        pg_store.portfolio.add_transaction(user.id, key, trade())
    with pg_store.database.connect() as conn:
        conn.execute("""INSERT INTO web_portfolio_positions (user_id,ticker,quantity,average_cost)
                     VALUES (%s,'AGBA',3,1.123456789)""", (user.id,))
    initialize(pg_store.database.connect)
    assert pg_store.portfolio.list_portfolio_positions(user.id)[0]['cost_value'] == Decimal('3.370370367')


def test_http_records_and_values_transactions_against_real_postgres(pg_store, monkeypatch):
    from fastapi.testclient import TestClient
    import api
    import web_auth
    import securities_catalog
    import catalogue.market_store as market
    from tests.test_portfolio_ledger import SECURITIES
    user, token = pg_store.accounts.register_user('portfolio-http@example.test', 'example-pass-123')
    assert user.tier == 'free' and not user.has_pro_access
    monkeypatch.setattr(web_auth, 'web_auth_store', pg_store)
    monkeypatch.setattr(securities_catalog, 'get_securities_map', lambda: SECURITIES)
    monkeypatch.setattr(market, 'get_all_listings', lambda: {})
    monkeypatch.setattr(market, 'get_all_trade_stats', lambda: {})
    monkeypatch.setattr(market, 'get_all_quotes', lambda: {'UZ7001560000': {'close_price': 589, 'trade_date': '20261021'}})
    client = TestClient(api.app, headers={'Authorization': f'Bearer {token}'})
    body = {k:v for k,v in trade().items() if k not in {'id','sequence'}}
    response = client.post('/api/portfolio/transactions', json={**body, 'id': str(uuid4())})
    assert response.status_code == 200, response.text
    record = response.json()['transaction']
    assert client.get('/api/portfolio').json()['market_value'] == '5890'
    edited = client.put('/api/portfolio/transactions/' + record['id'], json={**body, 'price': '110', 'version': 1})
    assert edited.status_code == 200, edited.text
    assert client.get('/api/portfolio').json()['cost_value'] == '1100'
    response = client.delete('/api/portfolio/transactions/' + record['id'] + '?version=2')
    assert response.status_code == 200, response.text
    assert client.get('/api/portfolio').json()['items'] == []
