"""The dispatch lock must also serialize concurrent production PostgreSQL sessions."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import pytest

def test_postgres_dispatch_is_durable_and_claimed_once(monkeypatch):
    dsn = os.getenv("TEST_POSTGRES_URL")
    if not dsn:
        pytest.skip("TEST_POSTGRES_URL is not configured")
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    import dbx
    from collection_ops import store
    from tests.test_collection_operations import observation, JOB
    if conninfo_to_dict(dsn).get("host") not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Use a local disposable PostgreSQL server")
    schema = "qa_collections_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        scoped = make_conninfo(dsn, options=f"-c search_path={schema}")
        monkeypatch.setattr(store, "connect", lambda: dbx.Connection(
            psycopg.connect(scoped, row_factory=psycopg.rows.dict_row), dbx.POSTGRES))
        store.report([observation()])
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = list(pool.map(lambda _: store.enqueue(JOB, actor_id=41), range(2)))
            claims = list(pool.map(lambda _: store.claim(), range(2)))
        assert len({r["id"] for r in requests}) == 1
        assert sum(c is not None for c in claims) == 1
        request = requests[0]
        store.ack(request["id"], "dispatched", "run-2", "Accepted")
        store.report([observation(invocation="run-2")])
        job = next(x for x in store.overview()["items"] if x["id"] == JOB)
        assert job["request"] is None
        assert job["requests"][0]["status"] == "finished"
    finally:
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
