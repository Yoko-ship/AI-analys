from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
import api
import web_auth
from collection_ops import store
from tests.test_collection_operations import isolated_store, observation, JOB

@pytest.fixture
def client(monkeypatch, isolated_store):
    monkeypatch.setenv("ADMIN_API_SECRET", "machine-test-secret")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.test")
    monkeypatch.setattr(web_auth.web_auth_store.sessions, "get_user_by_token",
        lambda token: SimpleNamespace(id=41, email="admin@example.test" if token == "admin" else "reader@example.test"))
    return TestClient(api.app)

def test_observations_are_admin_only_and_machine_posts_need_the_secret(client):
    assert client.get("/api/admin/collections").status_code == 401
    assert client.get("/api/admin/collections", headers={"Authorization": "Bearer reader"}).status_code == 403
    assert client.post("/api/admin/collections/report", json={"items": []}).status_code == 401
    assert client.get("/api/admin/collections", headers={"Authorization": "Bearer admin"}).status_code == 200

def test_manual_run_requires_human_admin_step_up_and_records_actor(client, admin_authenticator):
    store.report([observation()])
    path = f"/api/admin/collections/{JOB}/run"
    assert client.post(path, headers={"X-Admin-Secret": "machine-test-secret"}, json={}).status_code == 401
    response = client.post(path, headers={"Authorization": "Bearer admin"}, json={})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "MFA_REQUIRED"
    response = client.post(path, headers={"Authorization": "Bearer admin", **admin_authenticator}, json={})
    assert response.status_code == 200
    assert response.json()["actor_id"] == 41

def test_machine_can_report_claim_and_ack_but_browser_cannot_forge_a_result(client, admin_authenticator):
    auth = {"X-Admin-Secret": "machine-test-secret"}
    assert client.post("/api/admin/collections/report", headers=auth, json={"items": [observation()]}).status_code == 200
    request = store.enqueue(JOB, actor_id=41)
    assert client.post("/api/admin/collections/claim", headers={"Authorization": "Bearer admin", **admin_authenticator}, json={}).status_code == 401
    response = client.post("/api/admin/collections/claim", headers=auth, json={})
    assert response.json()["request"]["id"] == request["id"]
    assert client.post("/api/admin/collections/ack", headers=auth, json={
        "id": request["id"], "status": "failed", "detail": "systemctl refused the start"}).status_code == 200

def test_admin_request_reaches_host_and_completion_reaches_the_panel(client, admin_authenticator, monkeypatch, tmp_path):
    from collection_ops import host
    machine = {"X-Admin-Secret": "machine-test-secret"}
    admin = {"Authorization": "Bearer admin", **admin_authenticator}
    store.report([observation()])
    response = client.post(f"/api/admin/collections/{JOB}/run", headers=admin, json={})
    assert response.status_code == 200
    request_id = response.json()["id"]
    commands = []
    monkeypatch.setattr(host, "collect", lambda: [observation()])
    states = iter([{"ActiveState": "inactive"}, {"ActiveState": "activating", "InactiveExitTimestamp": "Sat 2026-11-07 10:00:00 UTC"}])
    monkeypatch.setattr(host, "properties", lambda unit: next(states))
    monkeypatch.setattr(host, "command", lambda args: commands.append(args) or "")
    def post(path, body):
        result = client.post("/api/admin/collections" + path, headers=machine, json=body)
        assert result.status_code == 200, result.text
        return result.json()
    host.tick(post, tmp_path / "outbox")
    job = next(x for x in client.get("/api/admin/collections", headers=admin).json()["items"] if x["id"] == JOB)
    assert job["request"]["id"] == request_id
    assert job["request"]["status"] == "dispatched"
    current = job["request"]["invocation"]
    monkeypatch.setattr(host, "collect", lambda: [observation(invocation=current, receipts=[
        {"stage": "/api/admin/quotes", "ok": True, "counts": {"upserted": 12}}])])
    host.tick(post, tmp_path / "outbox")
    job = next(x for x in client.get("/api/admin/collections", headers=admin).json()["items"] if x["id"] == JOB)
    assert job["request"] is None
    assert job["latest"]["publication"] == "acknowledged"
    assert job["requests"][0]["status"] == "finished"
    assert commands == [["systemctl", "start", "--no-block", "uzstock-quotes-catchup.service"]]
