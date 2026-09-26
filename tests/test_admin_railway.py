"""Authorization, scoping, recovery safety and honest Railway failure states."""

import web_auth as subject_web_auth
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
import admin_railway as rw

PROJECT = "11111111-1111-4111-8111-111111111111"
ENV = "22222222-2222-4222-8222-222222222222"
SERVICE = "33333333-3333-4333-8333-333333333333"
DEPLOYMENT = "44444444-4444-4444-8444-444444444444"
OTHER = "55555555-5555-4555-8555-555555555555"
ROOT = f"/api/admin/railway/services/{SERVICE}"
AUTH = {"Authorization": "Bearer test-session"}


def deployment(status="CRASHED"):
    return {"id": DEPLOYMENT, "status": status, "createdAt": "2026-08-30T01:00:00Z",
            "statusUpdatedAt": "2026-08-30T01:02:00Z", "canRedeploy": True,
            "projectId": PROJECT, "environmentId": ENV, "serviceId": SERVICE}


def environment(status="CRASHED"):
    return {"environment": {"id": ENV, "projectId": PROJECT, "name": "production",
        "serviceInstances": {"edges": [{"node": {"serviceId": SERVICE, "serviceName": "collector",
            "cronSchedule": "0 3 * * *", "nextCronRunAt": "2026-08-31T03:00:00Z",
            "latestDeployment": deployment(status)}}]}}}


@pytest.fixture
def setup(monkeypatch):
    for key in ("ADMIN_RAILWAY_TOKEN", "ADMIN_RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ADMIN_RAILWAY_TOKEN", "server-only-secret-token")
    monkeypatch.setenv("ADMIN_RAILWAY_PROJECT_ID", PROJECT)
    monkeypatch.setenv("ADMIN_RAILWAY_ENVIRONMENT_ID", ENV)
    monkeypatch.setenv("ADMIN_RAILWAY_RECOVERY_SERVICES", SERVICE)
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setattr(subject_web_auth.web_auth_store, "get_user_by_token", lambda token: SimpleNamespace(id=41, email="admin@example.com"))
    rw._snapshot_cache.clear()
    rw._recovery_times.clear()
    query = AsyncMock(return_value=environment())
    monkeypatch.setattr(rw, "query", query)
    audit = []
    monkeypatch.setattr(rw, "audit_action", lambda actor, service, payload, request_id, outcome: audit.append((actor.id, service["id"], outcome)))
    return TestClient(api.app), query, audit


@pytest.mark.parametrize("path,method", [("/api/admin/railway", "get"), (ROOT + "/deployments", "get"),
    (ROOT + f"/deployments/{DEPLOYMENT}/logs", "get"), (ROOT + "/recover", "post")])
@pytest.mark.parametrize("headers", [{}, {"X-Admin-Secret": "collector-secret"}])
def test_machine_and_anonymous_cannot_access(setup, path, method, headers):
    client, query, _ = setup
    assert getattr(client, method)(path, headers=headers).status_code == 401
    query.assert_not_awaited()


def test_non_admin_cannot_access(setup, monkeypatch):
    client, query, _ = setup
    monkeypatch.setattr(subject_web_auth.web_auth_store, "get_user_by_token", lambda token: SimpleNamespace(id=7, email="reader@example.com"))
    assert client.get("/api/admin/railway", headers=AUTH).status_code == 403
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload()).status_code == 403
    query.assert_not_awaited()


def test_missing_token_is_not_healthy_or_an_error(setup, monkeypatch):
    client, query, _ = setup
    monkeypatch.delenv("ADMIN_RAILWAY_TOKEN")
    res = client.get("/api/admin/railway", headers=AUTH)
    assert res.json() == {"configured": False, "services": []}
    query.assert_not_awaited()


def test_snapshot_status_cache_and_no_credential_leak(setup):
    client, query, _ = setup
    res = client.get("/api/admin/railway", headers=AUTH)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    service = res.json()["services"][0]
    assert service["deployment"]["status"] == "CRASHED"
    assert service["recovery_action"] == "restart"
    assert service["next_run_at"] and service["cron_schedule"]
    assert "server-only-secret-token" not in res.text
    client.get("/api/admin/railway", headers=AUTH)
    assert query.await_count == 1


def test_read_only_allowlist_and_healthy_job(setup, monkeypatch):
    client, query, _ = setup
    monkeypatch.setenv("ADMIN_RAILWAY_RECOVERY_SERVICES", "")
    assert client.get("/api/admin/railway", headers=AUTH).json()["services"][0]["recovery_action"] is None
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload()).status_code == 403
    query.return_value = environment("SUCCESS")
    rw._snapshot_cache.clear()
    service = client.get("/api/admin/railway", headers=AUTH).json()["services"][0]
    assert service["deployment"]["status"] == "SUCCESS" and service["recovery_action"] is None


def test_wrong_project_rejected(setup):
    client, query, _ = setup
    data = environment()
    data["environment"]["projectId"] = OTHER
    query.return_value = data
    assert client.get("/api/admin/railway", headers=AUTH).status_code == 502


def test_logs_scoped_and_secrets_redacted(setup):
    client, query, _ = setup
    query.side_effect = [{"deployment": deployment()}, {"deploymentLogs": [
        {"message": "ModuleNotFoundError: No module named 'main'", "severity": "error"},
        {"message": "token=remote-secret password='hidden pass' postgres://me:secret@host/db Bearer abcdefghi server-only-secret-token"}]}]
    res = client.get(ROOT + f"/deployments/{DEPLOYMENT}/logs", headers=AUTH)
    assert res.status_code == 200
    assert "ModuleNotFoundError" in res.json()["error_excerpt"]
    for secret in ("remote-secret", "hidden pass", "me:secret", "abcdefghi", "server-only-secret-token"):
        assert secret not in res.text
    assert "[REDACTED]" in res.text


def test_foreign_deployment_cannot_read_logs(setup):
    client, query, _ = setup
    dep = deployment()
    dep["environmentId"] = OTHER
    query.return_value = {"deployment": dep}
    assert client.get(ROOT + f"/deployments/{DEPLOYMENT}/logs", headers=AUTH).status_code == 404
    assert query.await_count == 1


def test_history_is_bounded_to_configured_service(setup):
    client, query, _ = setup
    query.side_effect = [environment(), {"deployments": {"edges": [{"node": deployment()}]}}]
    res = client.get(ROOT + "/deployments", headers=AUTH)
    assert res.status_code == 200 and res.json()["deployments"][0]["id"] == DEPLOYMENT
    assert query.await_args.args[2]["input"] == {"projectId": PROJECT, "environmentId": ENV, "serviceId": SERVICE}


def payload(**extra):
    return {"deployment_id": DEPLOYMENT, "action": "restart", "confirm": True, **extra}


@pytest.mark.parametrize("change,code", [({"confirm": False}, 400), ({"confirm": "true"}, 422), ({"action": "delete"}, 422)])
def test_recovery_requires_explicit_valid_confirmation(setup, change, code):
    client, query, _ = setup
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload(**change)).status_code == code
    query.assert_not_awaited()


@pytest.mark.parametrize("status,action,field,result", [("CRASHED", "restart", "deploymentRestart", True),
    ("FAILED", "redeploy", "deploymentRedeploy", {"id": OTHER, "status": "QUEUED"})])
def test_recovery_accepted_not_claimed_success_and_audited(setup, status, action, field, result):
    client, query, audit = setup
    query.side_effect = [environment(status), {field: result}]
    res = client.post(ROOT + "/recover", headers=AUTH, json=payload(action=action))
    assert res.status_code == 202 and res.json()["accepted"]
    assert "status" not in res.json()
    assert audit == [(41, SERVICE, "requested"), (41, SERVICE, "accepted")]
    assert query.await_args.args[2] == {"id": DEPLOYMENT}
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload(action=action)).status_code == 429
    assert query.await_count == 2


@pytest.mark.parametrize("change", [{"status": "SUCCESS"}, {"id": OTHER}, {"status": "BUILDING"}])
def test_no_recovery_of_healthy_or_superseded_deployment(setup, change):
    client, query, audit = setup
    data = environment()
    data["environment"]["serviceInstances"]["edges"][0]["node"]["latestDeployment"].update(change)
    query.return_value = data
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload()).status_code == 409
    assert query.await_count == 1 and not audit


def test_no_mutation_if_audit_unavailable(setup, monkeypatch):
    client, query, _ = setup
    def unavailable(*args):
        raise RuntimeError("database offline")
    monkeypatch.setattr(rw, "audit_action", unavailable)
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload()).status_code == 503
    assert query.await_count == 1


def test_uncertain_mutation_never_retried(setup):
    client, query, audit = setup
    query.side_effect = [environment(), HTTPException(502, "Railway unavailable")]
    assert client.post(ROOT + "/recover", headers=AUTH, json=payload()).status_code == 502
    assert audit[-1][2] == "unconfirmed"
    assert query.await_count == 2


def test_transport_checks_graphql_errors_and_uses_project_header(monkeypatch):
    captured = []
    async def handle(request):
        captured.append(request)
        return httpx.Response(200, json={"errors": [{"message": "secret upstream detail"}], "data": None})
    original = httpx.AsyncClient
    monkeypatch.setattr(rw.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    cfg = rw.Config(PROJECT, ENV, "sensitive-token", False, frozenset())
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rw.query(cfg, "query { environment { id } }", {}))
    assert exc.value.status_code == 502 and "secret upstream detail" not in exc.value.detail
    assert captured[0].headers["Project-Access-Token"] == "sensitive-token"
    assert "Authorization" not in captured[0].headers
