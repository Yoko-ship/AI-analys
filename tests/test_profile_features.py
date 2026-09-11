from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

import api
from web_auth import WebUser, _totp_code, _verify_totp


def _user() -> WebUser:
    return WebUser(
        id=7,
        email="person@example.com",
        full_name="Person",
        avatar_data_url=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_login_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        is_active=True,
    )


def _authorize(monkeypatch) -> TestClient:
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: _user() if token == "token" else None)
    return TestClient(api.app)


def test_totp_matches_rfc_6238_sha1_vector() -> None:
    # RFC 6238's ASCII secret "12345678901234567890" in base32. The RFC
    # publishes 94287082 at t=59; this product intentionally uses six digits.
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    at = datetime.fromtimestamp(59, tz=timezone.utc)
    assert _totp_code(secret, at) == "287082"
    assert _verify_totp(secret, "287082", at)
    assert not _verify_totp(secret, "000000", at)


def test_preferences_endpoint_persists_only_supplied_fields(monkeypatch) -> None:
    client = _authorize(monkeypatch)
    captured = {}

    def update(user_id, values):
        captured.update(user_id=user_id, values=values)
        return {"language": "en", "theme": "dark", **values}

    monkeypatch.setattr(api.web_auth_store, "update_preferences", update)
    response = client.patch(
        "/api/profile/preferences",
        headers={"Authorization": "Bearer token"},
        json={"language": "uz", "notify_news": False},
    )
    assert response.status_code == 200
    assert captured == {"user_id": 7, "values": {"language": "uz", "notify_news": False}}
    assert response.json()["preferences"]["language"] == "uz"


def test_password_change_keeps_current_session(monkeypatch) -> None:
    client = _authorize(monkeypatch)
    captured = {}

    def change(user_id, current_password, new_password, token):
        captured.update(
            user_id=user_id,
            current_password=current_password,
            new_password=new_password,
            token=token,
        )
        return 3

    monkeypatch.setattr(api.web_auth_store, "change_password", change)
    response = client.post(
        "/api/profile/password",
        headers={"Authorization": "Bearer token"},
        json={"current_password": "old-password", "new_password": "new-password"},
    )
    assert response.status_code == 200
    assert response.json()["revoked_sessions"] == 3
    assert captured["token"] == "token"


def test_analysis_update_is_scoped_to_current_user(monkeypatch) -> None:
    client = _authorize(monkeypatch)
    captured = {}

    def update(user_id, analysis_id, values):
        captured.update(user_id=user_id, analysis_id=analysis_id, values=values)
        return {"id": analysis_id, **values}

    monkeypatch.setattr(api.web_auth_store, "update_analysis", update)
    response = client.patch(
        "/api/profile/analyses/42",
        headers={"Authorization": "Bearer token"},
        json={"bookmarked": True, "folder": "Banks", "tags": ["q1", "bank"]},
    )
    assert response.status_code == 200
    assert captured == {
        "user_id": 7,
        "analysis_id": 42,
        "values": {"bookmarked": True, "folder": "Banks", "tags": ["q1", "bank"]},
    }


def test_history_clear_requires_explicit_confirmation(monkeypatch) -> None:
    client = _authorize(monkeypatch)
    monkeypatch.setattr(api.web_auth_store, "clear_analysis_history", lambda user_id: 5)
    rejected = client.request(
        "DELETE",
        "/api/profile/history",
        headers={"Authorization": "Bearer token"},
        json={"confirmation": "delete"},
    )
    accepted = client.request(
        "DELETE",
        "/api/profile/history",
        headers={"Authorization": "Bearer token"},
        json={"confirmation": "CLEAR"},
    )
    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()["deleted_analyses"] == 5


def test_support_request_is_attached_to_current_user(monkeypatch) -> None:
    client = _authorize(monkeypatch)
    captured = {}

    def create(user_id, subject, message):
        captured.update(user_id=user_id, subject=subject, message=message)
        return {"id": 12, "subject": subject, "status": "open"}

    monkeypatch.setattr(api.web_auth_store, "create_support_request", create)
    response = client.post(
        "/api/profile/support",
        headers={"Authorization": "Bearer token"},
        json={"subject": "Export issue", "message": "PDF export did not start."},
    )
    assert response.status_code == 200
    assert response.json()["request"]["id"] == 12
    assert captured["user_id"] == 7


def test_admin_receives_open_feedback_in_notification_bell(monkeypatch) -> None:
    admin = _user()
    admin.email = "admin@example.com"
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: admin if token == "token" else None)
    monkeypatch.setattr("admin_control.service.role_for", lambda _email: "administrator")
    monkeypatch.setattr(
        api.web_auth_store,
        "list_support_requests",
        lambda status, limit: {"items": [{
            "id": 32,
            "full_name": "Feedback sender",
            "subject": "Please add an export",
            "created_at": "2026-09-11T10:15:00+00:00",
        }]},
    )
    monkeypatch.setattr(api.web_auth_store, "notification_states", lambda _user_id: {})

    response = TestClient(api.app).get("/api/notifications", headers={"Authorization": "Bearer token"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["kind"] == "feedback"
    assert payload["items"][0]["href"] == "/admin/feedback"


def test_admin_can_mark_feedback_notification_read_without_pro(monkeypatch) -> None:
    admin = _user()
    admin.email = "admin@example.com"
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: admin if token == "token" else None)
    captured = {}

    def mark_read(user_id, ids, *, dismissed=False):
        captured.update(user_id=user_id, ids=ids, dismissed=dismissed)
        return len(ids)

    monkeypatch.setattr(api.web_auth_store, "set_notification_state", mark_read)
    response = TestClient(api.app).post(
        "/api/notifications/read",
        headers={"Authorization": "Bearer token"},
        json={"ids": ["feedback-32"]},
    )

    assert response.status_code == 200
    assert captured == {"user_id": 7, "ids": ["feedback-32"], "dismissed": False}


def test_new_profile_routes_are_available_under_v2() -> None:
    paths = {route.path for route in api.app.routes}
    for path in (
        "/api/profile/preferences",
        "/api/profile/sessions",
        "/api/profile/2fa/setup",
        "/api/profile/notes",
        "/api/profile/support",
        "/api/profile/export",
        "/api/profile/account",
    ):
        assert path in paths
        assert f"/api/v2{path[4:]}" in paths
