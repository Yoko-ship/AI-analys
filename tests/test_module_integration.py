"""HTTP composition, local persistence and worker lifetime integration."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import api
import issuer_financials
import reports_catalog
import securities_catalog
from reporting import store as report_store
from server import lifecycle
from server.audit import jobs as audit_jobs
from server.bonds import quality
from server.market import board


def test_refactor_preserves_all_registered_http_contracts():
    expected = json.loads(Path(__file__).with_name("fixtures").joinpath("http_routes.json").read_text())
    actual = [{"path": r.path, "methods": sorted(r.methods), "name": r.name,
               "dependencies": [d.call.__name__ for d in r.dependant.dependencies]}
              for r in api.app.routes if isinstance(r, APIRoute)]
    order = lambda row: (row["path"], row["methods"])
    assert sorted(actual, key=order) == sorted(expected, key=order)


def test_v2_alias_preserves_domain_error_translation(monkeypatch):
    monkeypatch.setattr(issuer_financials, "get_securities_map", lambda: {})
    client = TestClient(api.app)
    for prefix in ("/api/v1", "/api/v2/v1"):
        response = client.get(prefix + "/issuers/UNKNOWN/profile")
        assert response.status_code == 404
        assert response.json() == {"detail": "issuer not found"}
        assert client.get(prefix + "/issuers/UNKNOWN/ai-report?standard=nsbu").status_code == 404
    assert client.get("/api/missing").status_code == 404


def test_shutdown_drains_watchers_and_market_refresh_tasks():
    async def scenario():
        application = SimpleNamespace(state=SimpleNamespace(background_tasks=set()))
        stopped = set()

        async def work(name):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.add(name)

        tasks = [lifecycle._start_task(application, work(name), name)
                 for name in ("market", "catalog", "calendar", "report", "admin")]
        board._MARKET_BOARD_REFRESH_TASKS["stock"] = asyncio.create_task(work("refresh"))
        quality._BOND_QUALITY_TASKS["QA"] = asyncio.create_task(work("quality"))
        await asyncio.sleep(0)
        await lifecycle._stop_sector_analysis_worker(application)
        assert stopped == {"market", "catalog", "calendar", "report", "admin", "refresh", "quality"}
        assert all(task.done() for task in tasks)
        assert not application.state.background_tasks
        assert not board._MARKET_BOARD_REFRESH_TASKS
        assert not quality._BOND_QUALITY_TASKS

    asyncio.run(scenario())


def test_report_queue_claim_and_expired_lease_use_real_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "reports.sqlite3"))
    job = report_store.enqueue("QA", "source-v1")
    assert report_store.enqueue("QA", "source-v1") == job
    assert [row["id"] for row in report_store.due_jobs()] == [job]
    assert report_store.claim_job(job)
    assert not report_store.claim_job(job)
    with report_store.connect() as connection:
        connection.execute("UPDATE sector_jobs SET updated_at='2000-01-01' WHERE id=?", (job,))
    assert [row["id"] for row in report_store.due_jobs()] == [job]
    assert report_store.claim_job(job)
    report_store.finish_job(job, "completed", 1, None)
    assert report_store.due_jobs() == []


def test_ingested_quotes_reach_market_board_and_persist_across_requests(monkeypatch, tmp_path):
    """Real SQLite writes/readers behind HTTP; only the external mirror is fake."""
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.setenv("ADMIN_API_SECRET", "integration-test-secret")
    monkeypatch.setattr(securities_catalog, "DB_PATH", tmp_path / "securities.sqlite3")
    monkeypatch.setattr(audit_jobs, "_schedule_audit", lambda source: None)
    monkeypatch.setattr(board.requests, "get", lambda *a, **kw: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"stocks": []}))
    board._reset_market_board_cache()
    headers = {"X-Admin-Secret": "integration-test-secret"}
    quote = {"ticker": "QA", "isin": "UZTEST000001", "name": "Integration issuer",
             "market": "STK", "trade_date": "20260925", "close_price": 120,
             "prev_close": 100, "prev_close_date": "20260924", "change_percent": 20,
             "quantity": 10, "turnover": 1200}
    client = TestClient(api.app)
    assert client.post("/api/admin/quotes", json={"rows": [quote]}).status_code == 401
    response = client.post("/api/admin/quotes", headers=headers, json={"rows": [quote]})
    assert response.status_code == 200
    assert response.json()["upserted"] == 1
    response = client.get("/api/market/stocks?type=stock&refresh=true")
    assert response.status_code == 200
    row = next(row for row in response.json()["stocks"] if row["ticker"] == "QA")
    assert row["last_price"] == 120
    assert row["close_price"] == 100
    assert row["last_trade_date"] == "2026-09-25"
    assert reports_catalog.get_all_quotes()["UZTEST000001"]["close_price"] == 120
    # A new client and an emptied response cache must still see the persisted quote.
    board._reset_market_board_cache()
    second = TestClient(api.app).get("/api/v2/market/stocks?type=stock&refresh=true")
    assert second.json()["stocks"] == response.json()["stocks"]
    board._reset_market_board_cache()
