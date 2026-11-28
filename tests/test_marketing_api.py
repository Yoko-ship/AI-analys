from fastapi.testclient import TestClient
import pytest

import api
from server.auth import access
from test_marketing_core import OWNER, goal_input, isolated  # noqa: F401


@pytest.fixture
def client(monkeypatch):
    def owner(request):
        request.state.control_actor = OWNER
    # Keep FastAPI's Request annotation on the replacement dependency.
    from fastapi import Request
    owner.__annotations__["request"] = Request
    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, owner)
    return TestClient(api.app)


def test_standalone_video_http_handoff_and_private_download(client, monkeypatch, tmp_path):
    from marketing import store, video_studio, video_files
    from test_marketing_video_studio import Director
    from datetime import datetime, timezone
    base = '/api/admin/ai-marketing'
    response = client.post(base + '/videos', json={'brief': 'Show UZStock website and its news section'})
    assert response.status_code == 200
    item = response.json()['item']
    assert client.post(base + '/videos', json={'brief': 'too short', 'account_id': 'tg'}).status_code == 422
    now = datetime.now(timezone.utc)
    video_studio.run_one(Director(), now)
    claimed = video_studio.claim(now)
    workspace = client.get(base + '/workspace').json()
    assert workspace['video_worker']['online']
    assert claimed['lease_token'] not in str(workspace)
    assert client.get(base + f'/videos/{item["id"]}/file').status_code == 404
    monkeypatch.setenv('MARKETING_VIDEO_WORKER_TOKEN', 'synthetic-worker-token-' + 'x' * 40)
    headers = {'Authorization': 'Bearer synthetic-worker-token-' + 'x' * 40,
               'X-Video-Lease': claimed['lease_token'], 'X-Video-Offset': '0'}
    path = f'/api/marketing-video-worker/{item["id"]}'
    monkeypatch.setattr(video_files, 'inspect_video', lambda path: {'duration_seconds': 20})
    assert client.post(path + '/chunk', headers=headers, content=b'fixture MP4').json()['offset'] == 11
    assert client.post(path + '/complete', headers=headers, json={'lease_token': claimed['lease_token'], 'stage': 'uploading'}).status_code == 200
    result = client.get(base + f'/videos/{item["id"]}/file')
    assert result.content == b'fixture MP4' and result.headers['content-type'] == 'video/mp4'
    with store.connection() as c:
        assert not store.list_items(c, 'candidate') and not store.list_items(c, 'delivery')


def test_editorial_rule_http_versions_history_and_authority(client):
    from marketing import automation
    from test_marketing_automation import setup_rule
    rule = setup_rule(enabled=False)
    data = {key: rule[key] for key in automation.Rule.model_fields}
    path = f'/api/admin/ai-marketing/editorial-rules/{rule["id"]}'
    assert client.put(path, json={"expected_version": rule["version"], "data": {**data, "actor": "owner"}}).status_code == 422
    response = client.put(path, json={"expected_version": rule["version"], "data": {**data, "enabled": True}})
    assert response.status_code == 200 and response.json()["item"]["version"] == rule["version"] + 1
    assert client.put(path, json={"expected_version": rule["version"], "data": data}).status_code == 409
    workspace = client.get('/api/admin/ai-marketing/workspace').json()
    assert workspace['editorial_rules'][0]['enabled'] and workspace['editorial_rules'][0]['readiness']['status'] == 'ready'
    history = client.get(f'/api/admin/ai-marketing/history/editorial_rule/{rule["id"]}').json()['items']
    assert len(history) == 2 and all(entry['actor']['role'] == 'administrator' for entry in history)
    assert client.post('/api/admin/ai-marketing/tasks', json={"kind": "content", "message": "Forged priority", "editorial": {"priority": "urgent"}}).status_code == 422


def test_internal_draft_release_http_requires_exact_candidate_and_account(client):
    from datetime import datetime, timedelta, timezone
    from test_marketing_core import account, evidence, candidate
    expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    target = account(mode="manual", valid_until=expires)
    evidence(expires_at=expires)
    item = candidate(mode="draft", expires_at=expires)
    path = f'/api/admin/ai-marketing/candidates/{item["id"]}/release-draft'
    body = {"expected_version": item["version"], "account_version": target["version"]}
    assert client.post(path, json={**body, "mode": "automatic"}).status_code == 422
    assert client.post(path, json={**body, "account_version": 0}).status_code == 422
    assert client.post(path, json={**body, "expected_version": 0}).status_code == 409
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["item"]["status"] == "awaiting_approval"
    assert response.json()["item"]["release_decision"]["actor"] == OWNER["id"]
    assert client.post(path, json=body).status_code == 409


def test_meta_http_login_selection_is_owner_scoped_and_keeps_tokens_private(client, monkeypatch):
    from urllib.parse import parse_qs, urlsplit
    from test_marketing_meta import MetaPeer, target, PAGE_ID, USER_TOKEN, PAGE_TOKEN, SECRET
    MetaPeer(monkeypatch)
    saved = target()
    client.base_url = "https://testserver"
    base = "/api/admin/ai-marketing"
    started = client.post(base + "/accounts/facebook/meta/start", json={"expected_version": saved["version"]})
    assert started.status_code == 200
    assert "binding" not in started.json()
    cookie = started.headers["set-cookie"]
    assert all(value in cookie for value in ["HttpOnly", "Secure", "SameSite=lax", "Max-Age=600"])
    state = parse_qs(urlsplit(started.json()["authorization_url"]).query)["state"][0]
    response = client.post(base + "/oauth/meta/finish", json={"state": state, "code": "synthetic-code"})
    assert response.status_code == 200 and "Max-Age=0" in response.headers["set-cookie"]
    workspace = client.get(base + "/workspace")
    selection = workspace.json()["channel_setup"]["facebook"]["selection"]
    body = {"expected_version": saved["version"], "selection_id": selection["selection_id"], "target_id": PAGE_ID}
    path = base + "/accounts/facebook/meta/select"
    assert client.post(path, json={**body, "access_token": PAGE_TOKEN}).status_code == 422
    assert client.post(path, json=body).status_code == 200
    workspace = client.get(base + "/workspace")
    assert workspace.json()["accounts"][0]["mode"] == "draft"
    for secret in [USER_TOKEN, PAGE_TOKEN, SECRET]:
        assert secret not in workspace.text and secret not in response.text
    assert client.post(path, json=body).status_code == 409


def test_linkedin_http_uses_http_only_binding_and_server_profile_evidence(client, monkeypatch):
    from urllib.parse import urlsplit, parse_qs
    from test_marketing_linkedin import LinkedInPeer, personal, TOKEN, SECRET, PERSON
    peer = LinkedInPeer(monkeypatch)
    saved = personal()
    client.base_url = "https://testserver"
    base = "/api/admin/ai-marketing"
    start = base + "/accounts/li/linkedin/start"
    assert client.post(start, json={"expected_version": saved["version"], "verified": True}).status_code == 422
    response = client.post(start, json={"expected_version": saved["version"]})
    assert response.status_code == 200
    assert "binding" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie and "Max-Age=600" in cookie
    state = parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]
    finish = base + "/oauth/linkedin/finish"
    payload = {"state": state, "code": "synthetic-code"}
    assert client.post(finish, json={**payload, "external_id": PERSON}).status_code == 422
    result = client.post(finish, json=payload)
    assert result.status_code == 200 and result.json()["item"]["external_id"] == PERSON
    assert "Max-Age=0" in result.headers["set-cookie"]
    workspace = client.get(base + "/workspace")
    assert TOKEN not in workspace.text and SECRET not in workspace.text
    assert workspace.json()["channel_setup"]["li"]["ready"] is True
    assert workspace.json()["accounts"][0]["mode"] == "draft"
    assert client.post(finish, json=payload).status_code == 409
    assert len(peer.calls) == 2
    disconnected = client.post(base + "/accounts/li/linkedin/disconnect", json={"expected_version": result.json()["item"]["version"]})
    assert disconnected.status_code == 200
    assert not client.get(base + "/workspace").json()["channel_setup"]["li"]["ready"]


def test_social_connection_endpoints_require_a_human_owner(monkeypatch):
    from fastapi import Request
    def viewer(request: Request):
        request.state.control_actor = {"id": 3, "role": "viewer"}
    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, viewer)
    viewer_client = TestClient(api.app)
    for path in ["/accounts/li/linkedin/start", "/oauth/linkedin/finish", "/accounts/li/linkedin/disconnect", "/deliveries/missing/confirm-visible",
                 "/accounts/facebook/meta/start", "/oauth/meta/finish", "/accounts/facebook/meta/select", "/accounts/facebook/meta/disconnect", "/candidates/missing/release-draft"]:
        assert viewer_client.post("/api/admin/ai-marketing" + path, json={}).status_code == 403
    assert viewer_client.put('/api/admin/ai-marketing/telegram/tg/schedule', json={}).status_code == 403


def test_telegram_schedule_http_preserves_connection_and_checks_versions(client, monkeypatch):
    from test_marketing_telegram_news import connected
    saved = connected(monkeypatch)
    path = '/api/admin/ai-marketing/telegram/tg/schedule'
    data = {'news_daily_limit': 3, 'news_publish_times': ['10:00', '14:00', '18:00'],
            'window_start': '09:00', 'window_end': '21:00', 'min_interval_minutes': 30}
    body = {'expected_version': saved['version'], 'data': data}
    assert client.put(path, json={**body, 'data': {**data, 'news_publish_times': ['10:00']}}).status_code == 422
    response = client.put(path, json=body)
    assert response.status_code == 200, response.text
    updated = response.json()['item']
    assert updated['news_daily_limit'] == 3
    assert updated['news_publish_times'] == ['10:00:00', '14:00:00', '18:00:00']
    for key in ['connection_fingerprint', 'connection_identity', 'mode', 'languages', 'valid_until']:
        assert updated[key] == saved[key]
    assert client.put(path, json=body).status_code == 409
    assert client.put(path, json={**body, 'expected_version': updated['version'],
                                 'data': {**data, 'mode': 'automatic'}}).status_code == 422


def test_linkedin_visibility_confirmation_is_owner_observation_of_a_created_id(client, monkeypatch):
    from test_marketing_linkedin_media import queued_media, TOKEN, UPLOAD_SECRET
    from test_marketing_core import NOW
    from marketing import worker
    _, job, _ = queued_media(monkeypatch)
    worker.tick(now=NOW)
    base = "/api/admin/ai-marketing"
    workspace = client.get(base + "/workspace")
    assert TOKEN not in workspace.text and UPLOAD_SECRET not in workspace.text
    assert workspace.json()["uploads"][0]["status"] == "uploaded"
    review = workspace.json()["visibility_reviews"][0]
    path = base + f"/deliveries/{job['id']}/confirm-visible"
    payload = {"expected_version": review["delivery_version"], "review_digest": review["review_digest"]}
    assert client.post(path, json={**payload, "external_id": "invented"}).status_code == 422
    assert client.post(path, json={**payload, "review_digest": "invented"}).status_code == 409
    response = client.post(path, json=payload)
    assert response.status_code == 200 and response.json()["item"]["status"] == "published"
    assert response.json()["item"]["visibility_confirmation"]["method"] == "owner_visual_review"
    assert client.post(path, json=payload).status_code == 409


def test_workspace_is_empty_truthful_and_durable(client):
    initial = client.get("/api/admin/ai-marketing/workspace")
    assert initial.status_code == 200
    data = initial.json()
    assert data["active_goal"] is None and data["candidates"] == []
    assert len(data["roles"]) == 11
    assert {row['id']: row['formats'] for row in data['platforms']} == {
        'telegram': ['post', 'image', 'carousel', 'video'],
        'instagram': ['image', 'carousel', 'video', 'story'],
        'facebook': ['post', 'image', 'carousel', 'video'],
        'linkedin': ['post', 'image', 'carousel', 'video'],
    }
    assert all(a["connection_status"] == "not_connected" for a in data["accounts"])
    response = client.put("/api/admin/ai-marketing/goal", json={"data": goal_input(), "expected_version": 0})
    assert response.status_code == 200
    approved = client.post("/api/admin/ai-marketing/goal/approve", json={"expected_version": 1})
    assert approved.status_code == 200
    assert client.get("/api/admin/ai-marketing/workspace").json()["active_goal"]["target"] == 100
    assert len(client.get("/api/admin/ai-marketing/history/goal/primary").json()["items"]) == 2
    assert client.post("/api/admin/ai-marketing/goal/approve", json={"expected_version": 1}).status_code == 409


def test_workspace_exposes_recovery_lock_that_normal_pause_controls_cannot_remove(client, tmp_path, monkeypatch):
    from marketing import backup
    archive = tmp_path / "empty-backup.zip"
    backup.create(archive)
    monkeypatch.setenv("MARKETING_ENVIRONMENT", "api-recovery")
    backup.restore(archive)
    base = "/api/admin/ai-marketing"
    assert client.put(base + "/pause", json={"publications": False}).status_code == 200
    state = client.get(base + "/workspace").json()
    assert state["recovery"]["status"] == "requires_reconciliation"
    assert client.put(base + "/pause", json={"recovery": None}).status_code == 422


def test_recovery_review_http_binds_current_records_and_retains_owner_history(client, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from marketing import api as marketing_api
    from test_marketing_recovery_review import restored, review_input, REVIEWED
    restored(monkeypatch, tmp_path)
    monkeypatch.setattr(marketing_api, 'datetime', SimpleNamespace(now=lambda zone: REVIEWED))
    base = '/api/admin/ai-marketing'
    body = review_input()
    assert client.post(base + '/recovery/complete', json={**body, 'actor': 'owner'}).status_code == 422
    state = client.get(base + '/workspace').json()['recovery']
    assert state['basis_digest'] == body['basis_digest'] and len(state['quarantine']) == 2
    result = client.post(base + '/recovery/complete', json=body)
    assert result.status_code == 200 and result.json()['item']['status'] == 'reconciled'
    assert client.post(base + '/recovery/complete', json=body).status_code == 409
    history = client.get(base + '/history/settings/recovery').json()['items']
    assert history[-1]['action'] == 'recovery_gap_reviewed' and history[-1]['actor']['role'] == 'administrator'


def test_reconciliation_api_uses_server_observations_and_exact_current_match(client, monkeypatch):
    from types import SimpleNamespace
    from marketing import api as marketing_api
    from test_marketing_reconciliation import uncertain, observation
    from test_marketing_core import NOW
    monkeypatch.setattr(marketing_api, "datetime", SimpleNamespace(now=lambda zone: NOW))
    peer, job, _, copy = uncertain(monkeypatch)
    peer.updates = [observation(copy, forwarded=True)]
    base = "/api/admin/ai-marketing"
    assert client.post(base + "/channels/telegram/reconcile", json={"verified": True}).status_code == 422
    response = client.post(base + "/channels/telegram/reconcile", json={})
    assert response.status_code == 200 and response.json()["received"] == 1
    workspace = client.get(base + "/workspace").json()
    found = workspace["reconciliation"][0]
    assert found["status"] == "matched"
    path = base + f"/deliveries/{job['id']}/confirm-match"
    payload = {"expected_version": job["version"], "match_digest": found["match_digest"]}
    assert client.post(path, json={**payload, "external_id": "invented"}).status_code == 422
    assert client.post(path, json={**payload, "match_digest": "invented"}).status_code == 409
    result = client.post(path, json=payload)
    assert result.status_code == 200 and result.json()["item"]["status"] == "published"
    assert client.post(path, json=payload).status_code == 409


def test_reconciliation_endpoints_require_a_human_owner(monkeypatch):
    from fastapi import Request
    def viewer(request: Request):
        request.state.control_actor = {"id": 3, "role": "viewer"}
    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, viewer)
    viewer_client = TestClient(api.app)
    for path in ["/channels/telegram/reconcile", "/deliveries/missing/confirm-match"]:
        assert viewer_client.post("/api/admin/ai-marketing" + path, json={}).status_code == 403


def test_connection_probe_and_outgoing_preview_use_server_evidence_not_browser_verdicts(client, monkeypatch):
    from test_marketing_core import account, candidate, evidence
    from test_marketing_channels import TelegramPeer, TOKEN
    monkeypatch.delenv("MARKETING_TELEGRAM_BOT_TOKEN", raising=False)
    saved = account()
    base = "/api/admin/ai-marketing"
    setup = client.get(base + "/workspace").json()["channel_setup"]["tg"]
    assert setup["configured"] is False and setup["ready"] is False
    path = base + "/accounts/tg/probe"
    assert client.post(path, json={"expected_version": saved["version"], "verified": True}).status_code == 422
    assert client.post(path, json={"expected_version": saved["version"]}).status_code == 409
    peer = TelegramPeer(monkeypatch)
    result = client.post(path, json={"expected_version": saved["version"]})
    assert result.status_code == 200 and result.json()["item"]["connection_status"] == "connected"
    workspace = client.get(base + "/workspace")
    assert workspace.json()["channel_setup"]["tg"]["ready"] is True and TOKEN not in workspace.text
    assert all(method.startswith("get") for method, _, _ in peer.calls)
    evidence()
    item = candidate()
    preview = client.get(base + f"/candidates/{item['id']}/publication-preview")
    assert preview.status_code == 200 and "https://openinfo.uz/facts/123" in preview.json()["text"]
    assert item["destination_url"] in preview.json()["text"]


def test_incident_http_preserves_before_after_and_requires_current_owner_decision(client):
    from test_marketing_incidents import published, amend, draft
    published()
    amend()
    base = "/api/admin/ai-marketing"
    assert client.post(base + "/incidents/scan").status_code == 200
    found = client.get(base + "/workspace").json()["incidents"][0]
    assert found["changes"][0]["before"]["data"]["dividend"] == 120
    assert found["changes"][0]["after"]["data"]["dividend"] == 99
    path = base + f"/incidents/{found['id']}"
    value = {"expected_version": found["version"], "data": draft()}
    assert client.post(path + "/correction", json={**value, "account_id": "injected"}).status_code == 422
    assert client.post(path + "/correction", json={**value, "expected_version": 0}).status_code == 409
    assert client.post(path + "/correction", json={**value, "data": {**draft(), "expires_at": "bad date"}}).status_code == 422
    result = client.post(path + "/correction", json=value)
    assert result.status_code == 200 and result.json()["item"]["correction_incident"] == found["id"]
    assert client.post(path + "/correction", json=value).status_code == 409
    current = client.get(base + "/workspace").json()["incidents"][0]
    dismissed = client.post(path + "/dismiss", json={"expected_version": current["version"], "reason": "В опубликованном тексте нет изменённого факта"})
    assert dismissed.status_code == 200 and dismissed.json()["item"]["status"] == "not_material"
    history = client.get(base + f"/history/incident/{found['id']}").json()["items"]
    assert len(history) == 3 and history[-1]["actor"] == OWNER


def test_incident_endpoints_require_a_human_owner(monkeypatch):
    from fastapi import Request
    def viewer(request: Request):
        request.state.control_actor = {"id": 3, "role": "viewer"}
    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, viewer)
    viewer_client = TestClient(api.app)
    base = "/api/admin/ai-marketing/incidents"
    for path in ["/scan", "/missing/correction", "/missing/dismiss"]:
        assert viewer_client.post(base + path, json={}).status_code == 403


def test_paid_experiment_api_approval_is_versioned_and_does_not_create_delivery(client, monkeypatch):
    from types import SimpleNamespace
    from marketing import api as marketing_api
    from test_marketing_experiments import basis, proposal, NOW
    monkeypatch.setattr(marketing_api, "datetime", SimpleNamespace(now=lambda zone: NOW))
    item = basis()
    base = "/api/admin/ai-marketing"
    value = {"data": proposal(item), "expected_version": 0}
    assert client.post(base + "/experiments", json={**value, "approval": True}).status_code == 422
    result = client.post(base + "/experiments", json=value)
    assert result.status_code == 200
    experiment = result.json()["item"]
    path = base + f"/experiments/{experiment['id']}"
    assert client.post(path + "/action", json={"expected_version": 1}).status_code == 409
    approved = client.post(path + "/approve", json={"expected_version": 1})
    assert approved.status_code == 200
    assert client.post(path + "/approve", json={"expected_version": 1}).status_code == 409
    assert client.post(path + "/action", json={"expected_version": 2}).json()["error"]["code"] == "PAID_CONNECTION_REQUIRED"
    workspace = client.get(base + "/workspace").json()
    assert workspace["experiments"][0]["approval"]["parameters"]["budget_limit"] == 600_000
    assert workspace["deliveries"] == []
    assert client.post(path + "/revoke", json={"expected_version": 2, "reason": "Отложить пилот"}).status_code == 200
    assert len(client.get(base + f"/history/experiment/{experiment['id']}").json()["items"]) == 3


def test_report_http_uses_server_ledger_freezes_exports_and_compares(client):
    base = "/api/admin/ai-marketing/reports"
    settings = client.put(base + "/settings", json={"data": {"dataset": "test", "monetization_live": True,
        "legal_entities": ["ip"], "entity_launches": {"ip": "2024-01-01T00:00:00Z"}}, "expected_version": 0})
    assert settings.status_code == 200
    period = {"starts_on": "2025-01-06", "ends_on": "2025-01-13"}
    rows = [{"id": "registration", "kind": "registration", "at": "2025-01-07T00:00:00Z", "subject_id": "pseudonymous-customer",
             "dataset": "test", "source": "confirmed-export", "confirmed": True}]
    rows.append({**rows[0], 'id': 'private-refund-event', 'kind': 'refund', 'transaction_id': 'private-refund-transaction',
                 'related_transaction_id': 'private-missing-payment', 'amount': 50000, 'legal_entity': 'ip'})
    coverage = [{"dataset": "test", "categories": ["registrations"], "starts_on": "2024-01-01", "ends_on": "2025-02-01",
                 "through": "2025-01-31T00:00:00Z", "history_complete": True, "status": "complete", "reference": "Verified export"}]
    assert client.post(base + "/import", json={"events": rows, "coverage": coverage}).status_code == 200
    report = client.post(base + "/calculate", json=period).json()["report"]
    assert report["metrics"]["registrations"]["value"] == 1
    frozen = client.post(base + "/snapshots", json={"name": "Week one", "period": period, "expected_settings_version": 1}).json()["item"]
    assert frozen['report']['financial_issues'][0]['transaction_id'] == 'private-missing-payment'
    exported = client.get(base + f"/snapshots/{frozen['id']}/export")
    assert exported.status_code == 200 and "pseudonymous-customer" not in exported.text
    assert "input_event_ids" not in exported.json()
    assert 'private-refund-event' not in exported.text and 'private-missing-payment' not in exported.text
    assert exported.json()['financial_issues'][0]['code'] == 'refund_payment_missing'
    csv = client.get(base + f"/snapshots/{frozen['id']}/export?format=csv")
    assert "registrations" in csv.text and "text/csv" in csv.headers["content-type"]
    # A browser cannot supply manufactured report values.
    fabricated = client.post(base + "/snapshots", json={"name": "Fake", "period": period, "expected_settings_version": 1, "report": report})
    assert fabricated.status_code == 422
    stale = client.post(base + "/snapshots", json={"name": "Stale", "period": period, "expected_settings_version": 0})
    assert stale.status_code == 409
    recalculated = client.post(base + f"/snapshots/{frozen['id']}/recompute", json={"reason": "Updated source"}).json()["item"]
    compared = client.post(base + "/compare", json={"first_id": frozen["id"], "second_id": recalculated["id"]}).json()
    assert compared["metrics"]["registrations"]["difference"] == 0
    review = client.put(base + "/review", json={"period": period, "data": {"decisions": "Measure", "next_actions": "Compare"}, "expected_version": 0})
    assert review.status_code == 200
    task = client.post(base + "/analysis", json=period).json()["item"]
    assert task["report"]["metrics"]["registrations"]["value"] == 1
    assert set(task['report']['financial_issues'][0]) == {'code', 'message', 'entities', 'metrics'}
    assert task["kind"] == "report" and task["status"] == "queued"
    assert client.post(base + "/analysis", json={**period, "report": report}).status_code == 422


def test_invalid_fields_and_pauses(client):
    assert client.put("/api/admin/ai-marketing/goal", json={"data": goal_input(target=-1), "expected_version": 0}).status_code == 422
    paused = client.put("/api/admin/ai-marketing/pause", json={"publications": True, "processing": False})
    assert paused.status_code == 200
    assert client.get("/api/admin/ai-marketing/workspace").json()["pause"]["publications"]


def test_no_machine_secret_or_unprivileged_session_can_read_marketing():
    client = TestClient(api.app)
    assert client.get("/api/admin/ai-marketing/workspace", headers={"X-Admin-Secret": "not-a-human"}).status_code == 401


def test_non_owner_cannot_mutate_even_with_an_admin_console_role(monkeypatch):
    from fastapi import Request
    def viewer(request: Request):
        request.state.control_actor = {"id": 3, "role": "viewer"}
    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, viewer)
    client = TestClient(api.app)
    assert client.put("/api/admin/ai-marketing/goal", json={"data": goal_input(), "expected_version": 0}).status_code == 403


def test_cmo_task_roundtrip_exposes_saved_context_and_can_be_cancelled(client):
    created = client.post("/api/admin/ai-marketing/tasks", json={"kind": "dialogue", "message": "Что нужно замерить до стратегии?"})
    assert created.status_code == 200
    task = created.json()["item"]
    assert task["status"] == "queued"
    workspace = client.get("/api/admin/ai-marketing/workspace").json()
    assert workspace["model"]["note"]
    assert workspace["tasks"][0]["message"] == "Что нужно замерить до стратегии?"
    cancelled = client.post(f"/api/admin/ai-marketing/tasks/{task['id']}/cancel", json={"expected_version": task["version"]})
    assert cancelled.status_code == 200 and cancelled.json()["item"]["status"] == "cancelled"


def test_owner_registers_imports_verifies_and_revokes_a_source(client):
    from test_marketing_sources import source_input, article
    saved = client.put("/api/admin/ai-marketing/sources/issuer", json={"data": source_input(method="manual"), "expected_version": 0})
    assert saved.status_code == 200
    assert saved.json()["item"]["status"] == "candidate"
    imported = client.post("/api/admin/ai-marketing/sources/issuer/import", json={"materials": [article()]})
    assert imported.status_code == 200
    data = client.get("/api/admin/ai-marketing/workspace").json()
    assert len(data["sources"]) == 1 and len(data["topics"]) == 1
    evidence = data["evidence"][0]
    assert evidence["status"] == "candidate"
    verified = client.post(f"/api/admin/ai-marketing/evidence/{evidence['id']}/verify", json={"expected_version": evidence["version"], "reason": "Compared original decision and unit"})
    assert verified.status_code == 200 and verified.json()["item"]["status"] == "verified"
    disabled = client.post("/api/admin/ai-marketing/sources/issuer/permission", json={"expected_version": data["sources"][0]["version"], "enabled": False})
    assert disabled.status_code == 200
    assert client.get("/api/admin/ai-marketing/workspace").json()["evidence"][0]["status"] == "disabled"
    assert len(client.get("/api/admin/ai-marketing/history/source/issuer").json()["items"]) == 3


def test_source_import_cannot_assert_internal_verification_authority(client):
    from test_marketing_sources import source_input, article
    saved = client.put("/api/admin/ai-marketing/sources/issuer", json={"data": source_input(method="manual"), "expected_version": 0})
    assert saved.status_code == 200
    injected = client.post("/api/admin/ai-marketing/sources/issuer/import", json={"materials": [{**article(), "status": "verified"}], "verified_ids": ["original"]})
    assert injected.status_code == 422


def test_production_api_exposes_reviewed_variants_and_selects_language_without_new_post(client):
    from marketing import agents
    from test_marketing_core import NOW
    from test_marketing_production import brief, prepare_accounts, ProductionModel
    prepare_accounts(mode="manual")
    response = client.post("/api/admin/ai-marketing/tasks", json={"kind": "content", "message": "Четыре площадки", "evidence_ids": ["decision"], "production": brief(mode="account")})
    assert response.status_code == 200
    model = ProductionModel()
    for _ in range(8):
        agents.run_one(model, NOW)
    data = client.get("/api/admin/ai-marketing/workspace").json()
    assert len(data["variants"]) == 8
    candidate = next(item for item in data["candidates"] if item["account_id"] == "telegram")
    variant = next(item for item in data["variants"] if item["account_id"] == "telegram" and item["language"] == "uz")
    selected = client.post(f"/api/admin/ai-marketing/drafts/{variant['id']}/select", json={"expected_version": candidate["version"]})
    assert selected.status_code == 200
    assert selected.json()["item"]["language"] == "uz"
    assert selected.json()["item"]["id"] == candidate["id"]


def test_owner_renders_previews_and_exports_real_media_and_receives_corruption_error(client):
    from marketing import media
    from test_marketing_media import media_candidate
    from test_marketing_core import NOW
    import io
    import json
    import zipfile
    item = media_candidate(track_visits=True)
    path = f"/api/admin/ai-marketing/candidates/{item['id']}"
    response = client.post(path + "/render", json={"expected_version": item["version"]})
    assert response.status_code == 200
    assert media.run_one(NOW)
    data = client.get("/api/admin/ai-marketing/workspace").json()
    asset = data["assets"][0]
    assert data["renders"][0]["status"] == "complete"
    file = client.get(f"/api/admin/ai-marketing/assets/{asset['id']}/file")
    assert file.status_code == 200 and file.headers["content-type"] == "image/jpeg"
    assert file.content.startswith(b'\xff\xd8')
    export = client.get(path + "/export")
    assert export.status_code == 200
    preview = client.get(path + '/publication-preview').json()
    preview = {key: value for key, value in preview.items() if key not in {'ok', 'request_id'}}
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        assert "material.json" in archive.namelist() and "draft.txt" in archive.namelist()
        assert any(name.endswith(".jpg") for name in archive.namelist())
        assert "120" in archive.read("draft.txt").decode("utf-8")
        assert archive.read('draft.txt').decode('utf-8') == preview['text']
        assert json.loads(archive.read('material.json'))['publication'] == preview
    media.asset_path(asset).write_bytes(b"corrupted")
    assert client.get(f"/api/admin/ai-marketing/assets/{asset['id']}/file").status_code == 409
    assert client.get(path + "/export").status_code == 409


def test_approved_plan_http_links_exact_tasks_and_rejects_injected_authority(client):
    from test_marketing_execution import approved_plan
    plan = approved_plan()
    base = "/api/admin/ai-marketing"
    activated = client.post(f"{base}/strategies/{plan['id']}/work", json={"expected_version": plan["version"]})
    assert activated.status_code == 200
    run = activated.json()["item"]
    workspace = client.get(base + "/workspace").json()
    row = next(value for value in workspace["plans"][0]["items"] if value["step"]["id"] == "brief")
    path = f"{base}/plan-steps/{row['id']}/start"
    assert client.post(path, json={"expected_version": row["version"], "data": {"assigned_roles": ["cmo"]}}).status_code == 422
    task = client.post(path, json={"expected_version": row["version"], "data": {}})
    assert task.status_code == 200 and task.json()["item"]["steps"] == ["pr", "cmo"]
    assert client.post(path, json={"expected_version": row["version"], "data": {}}).status_code == 409
    history = client.get(f"{base}/history/plan_step/{row['id']}").json()["items"]
    assert len(history) == 2 and history[-1]["record"]["task_id"] == task.json()["item"]["id"]
    paused = client.post(f"{base}/plans/{run['id']}/pause", json={"expected_version": run["version"], "paused": True})
    assert paused.status_code == 200 and paused.json()["item"]["status"] == "paused"
    assert not client.get(base + "/workspace").json()["deliveries"]


def test_prepared_step_http_pins_inputs_and_can_be_cancelled_before_its_start(client):
    from test_marketing_execution import approved_plan, activate
    run = activate(approved_plan())
    base = "/api/admin/ai-marketing"
    data = client.get(base + "/workspace").json()
    row = next(item for item in data["plans"][0]["items"] if item["step"]["id"] == "research")
    path = f"{base}/plan-steps/{row['id']}/prepare"
    assert client.post(path, json={"expected_version": row["version"], "data": {"authority": "publish"}}).status_code == 422
    saved = client.post(path, json={"expected_version": row["version"], "data": {}})
    assert saved.status_code == 200 and saved.json()["item"]["status"] == "prepared"
    assert client.post(path, json={"expected_version": row["version"], "data": {}}).status_code == 409
    assert client.get(base + "/workspace").json()["tasks"] == []
    cancelled = client.post(f"{base}/plan-steps/{row['id']}/cancel-preparation", json={"expected_version": saved.json()["item"]["version"]})
    assert cancelled.status_code == 200 and cancelled.json()["item"]["status"] == "pending"
    assert cancelled.json()["item"]["run_id"] == run["id"]
