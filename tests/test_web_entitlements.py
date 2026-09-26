from __future__ import annotations

import analysis_service as subject_analysis_service
import web_auth as subject_web_auth

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import api
from web_auth import WebUser


def _user(*, tier: str = "free", until: datetime | None = None) -> WebUser:
    return WebUser(
        id=101,
        email="reader@example.test",
        full_name="Reader",
        avatar_data_url=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_login_at=None,
        is_active=True,
        tier=tier,
        subscription_until=until,
    )


def test_pro_access_respects_active_and_expired_entitlements() -> None:
    assert not _user().has_pro_access
    assert _user(tier="pro", until=datetime.now(timezone.utc) + timedelta(days=1)).has_pro_access
    assert not _user(tier="pro", until=datetime.now(timezone.utc) - timedelta(seconds=1)).has_pro_access


def test_paid_analysis_is_rejected_before_the_engine_runs(monkeypatch) -> None:
    monkeypatch.setattr(subject_web_auth.web_auth_store, "get_user_by_token", lambda _: _user())
    monkeypatch.setattr(subject_analysis_service, 'run_company_analysis', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))
    client = TestClient(api.app)

    response = client.post(
        "/api/analyze",
        headers={"Authorization": "Bearer free-user"},
        json={"company": "UZTL"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PRO_REQUIRED"
