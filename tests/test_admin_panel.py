"""The admin panel authenticates as a person; the collectors keep their secret.

Two credentials now open the same doors. That is the risk worth pinning: the
browser must never need ``ADMIN_API_SECRET`` (it would sit in a bundle and in
every developer's devtools), and adding the browser path must not have widened
the machine path by accident. So each test below asks one question — who gets
in, who is turned away, and with which status.

The overview endpoint gets its own tests because the panel renders whatever it
returns: a block that quietly becomes ``None`` on a broken table must not take
the other four down with it, and a missing measurement must arrive as null
rather than as a plausible zero.
"""
from __future__ import annotations

import web_auth as subject_web_auth

import pytest
from fastapi.testclient import TestClient

import api
import admin_overview
import analytics_api


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ADMIN_API_SECRET", "s3cret")
    return TestClient(api.app)


class _User:
    def __init__(self, email: str, user_id: int = 41) -> None:
        self.id = user_id
        self.email = email


def _as_user(monkeypatch, email: str | None) -> None:
    """Make Bearer resolution deterministic: a token maps to this email, or nobody."""
    def _get_user_by_token(token: str):
        return _User(email) if (token and email) else None

    monkeypatch.setattr(subject_web_auth.web_auth_store.sessions, "get_user_by_token", _get_user_by_token)


# ---------------------------------------------------------------------------
# Who gets in
# ---------------------------------------------------------------------------

class TestAdminGate:
    def test_the_machine_secret_still_opens_the_door(self, client, monkeypatch):
        """The collectors push with this header and must not have been disturbed."""
        monkeypatch.setattr(admin_overview, "build_overview", lambda **kw: {"ok": True})
        res = client.get("/api/admin/overview", headers={"X-Admin-Secret": "s3cret"})
        assert res.status_code == 200

    def test_a_wrong_secret_is_still_refused(self, client):
        res = client.get("/api/admin/overview", headers={"X-Admin-Secret": "nope"})
        assert res.status_code == 401

    def test_a_wrong_secret_is_not_rescued_by_a_valid_session(self, client, monkeypatch):
        """Presenting the header means claiming to be a machine — the claim is judged
        on its own. Falling back to the user would let a leaked-but-stale secret
        look like it still works."""
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        res = client.get("/api/admin/overview", headers={
            "X-Admin-Secret": "nope", "Authorization": "Bearer tok"})
        assert res.status_code == 401

    def test_a_signed_in_admin_gets_in_without_the_secret(self, client, monkeypatch):
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        monkeypatch.setattr(admin_overview, "build_overview", lambda **kw: {"ok": True})
        res = client.get("/api/admin/overview", headers={"Authorization": "Bearer tok"})
        assert res.status_code == 200

    def test_a_signed_in_ordinary_user_is_refused(self, client, monkeypatch):
        _as_user(monkeypatch, "reader@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        res = client.get("/api/admin/overview", headers={"Authorization": "Bearer tok"})
        assert res.status_code == 403

    def test_nobody_at_all_is_refused(self, client, monkeypatch):
        _as_user(monkeypatch, None)
        res = client.get("/api/admin/overview")
        assert res.status_code == 401

    def test_an_empty_admin_allowlist_admits_no_one(self, client, monkeypatch):
        """`ADMIN_EMAILS` unset must mean *nobody*, never *everybody*."""
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.delenv("ADMIN_EMAILS", raising=False)
        res = client.get("/api/admin/overview", headers={"Authorization": "Bearer tok"})
        assert res.status_code == 403

    @pytest.mark.parametrize("path", [
        "/api/audit/runs",
        "/api/audit/findings",
    ])
    def test_the_audit_screens_accept_a_signed_in_admin(self, client, monkeypatch, path):
        """These used to demand the machine secret, which is why the old screen
        asked the operator to paste it into a field."""
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        res = client.get(path, headers={"Authorization": "Bearer tok"})
        assert res.status_code == 200

    def test_the_rule_book_stays_public(self, client):
        """The rules explain what is checked and why; reading them needs no key."""
        assert client.get("/api/audit/rules").status_code == 200


class TestProductAdminGate:
    def test_collector_secret_cannot_read_human_admin_data(self, client):
        """An ingestion credential is not a user-management credential."""
        res = client.get("/api/admin/users", headers={"X-Admin-Secret": "s3cret"})
        assert res.status_code == 401

    def test_user_action_gets_server_resolved_actor(self, client, monkeypatch):
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        captured = {}

        def _action(user_id, action, **context):
            captured.update(user_id=user_id, action=action, **context)
            return {"ok": True, "action": action, "user_id": user_id}

        monkeypatch.setattr(analytics_api.web_analytics, "user_action", _action)
        res = client.post(
            "/api/admin/users/77/action",
            headers={"Authorization": "Bearer tok"},
            json={"action": "revoke_sessions"},
        )
        assert res.status_code == 200
        assert captured["actor_user_id"] == 41
        assert captured["actor_email"] == "admin@example.com"
        assert captured["user_id"] == 77
        assert len(captured["request_id"]) == 32
        assert captured["source_ip_hash"]

    def test_protected_admin_conflict_is_explicit(self, client, monkeypatch):
        _as_user(monkeypatch, "admin@example.com")
        monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
        monkeypatch.setattr(
            analytics_api.web_analytics, "user_action",
            lambda *a, **kw: {"ok": False, "reason": "protected admin"},
        )
        res = client.post(
            "/api/admin/users/41/action",
            headers={"Authorization": "Bearer tok"},
            json={"action": "deactivate"},
        )
        assert res.status_code == 409


class TestVisitIdentity:
    @staticmethod
    def _payload(uid=999):
        return {
            "vid": "a" * 16, "sid": "b" * 16, "uid": uid,
            "path": "/company/UZTL", "view": "company", "ticker": "UZTL",
        }

    def test_public_beacon_cannot_claim_a_user_id(self, client, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            analytics_api.web_analytics, "record_pageview",
            lambda data, **context: captured.update(data=data, **context),
        )
        res = client.post(
            "/api/track", json=self._payload(),
            headers={"User-Agent": "Mozilla/5.0 Chrome/126.0"},
        )
        assert res.status_code == 204
        assert captured["data"]["uid"] is None

    def test_bearer_session_supplies_the_trusted_user_id(self, client, monkeypatch):
        _as_user(monkeypatch, "reader@example.com")
        captured = {}
        monkeypatch.setattr(
            analytics_api.web_analytics, "record_pageview",
            lambda data, **context: captured.update(data=data, **context),
        )
        res = client.post(
            "/api/track", json=self._payload(uid=999),
            headers={"Authorization": "Bearer tok", "User-Agent": "Mozilla/5.0 Chrome/126.0"},
        )
        assert res.status_code == 204
        assert captured["data"]["uid"] == 41


# ---------------------------------------------------------------------------
# What the overview reports
# ---------------------------------------------------------------------------

class TestOverview:
    def test_every_block_is_present(self):
        data = admin_overview.build_overview()
        assert data["ok"] is True
        for block in ("catalog", "audit", "news", "streams"):
            assert block in data

    def test_one_broken_block_does_not_blank_the_others(self, monkeypatch):
        """A panel that shows nothing diagnoses an outage worse than one that
        shows four of five blocks."""
        monkeypatch.setattr(admin_overview, "_audit_block",
                            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        data = admin_overview.build_overview()
        assert data["audit"] is None
        assert data["catalog"] is not None
        assert "boom" in data["errors"]["audit"]

    def test_a_stream_that_was_never_written_is_not_called_stale(self):
        """Never-written and long-unwritten are different facts, and only one of
        them is a reason to look at a service."""
        streams = admin_overview.build_overview()["streams"]
        for stream in streams:
            if stream["last_write"] is None:
                assert stream["state"] == "unknown"
                assert stream["age_hours"] is None

    def test_a_missing_measurement_is_null_and_not_zero(self, monkeypatch):
        """A dash on the screen must come from an absent number, never from a
        zero we invented for it."""
        monkeypatch.setattr(admin_overview, "_scalar", lambda *a, **kw: None)
        news = admin_overview.build_overview()["news"]
        assert news["collected"] is None
        assert news["rejected"] is None

    def test_the_freshness_cutoff_is_measured_in_hours(self):
        now = admin_overview._utcnow()
        assert admin_overview._age_hours(None, now) is None
        assert admin_overview._age_hours("not a date", now) is None
        # A naive stamp is read as UTC rather than rejected: that is how the
        # catalog writes them.
        aged = admin_overview._age_hours(
            (now - __import__("datetime").timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S"), now)
        assert 4.9 < aged < 5.1

    def test_every_stream_names_the_service_that_writes_it(self):
        """The panel names a Railway service, so the mapping must be complete —
        a stream with no service leaves the reader nothing to go and check."""
        for stream in admin_overview.STREAMS:
            assert stream["service"] and stream["schedule"] and stream["title"]
