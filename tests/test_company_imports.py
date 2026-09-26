"""Admin-reviewed UZSE/OpenInfo company imports."""
from __future__ import annotations

import web_auth as subject_web_auth

import dbx
import pytest
from fastapi.testclient import TestClient

import api
import company_imports
import entity_resolver
import openinfo_collector
import reports_catalog


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "company-imports.db"))
    dbx.reset_pools()
    yield
    dbx.reset_pools()


def _record(**overrides):
    return {
        "ticker": "ZZCO",
        "name": "ZZ Company AJ",
        "org_name": "ZZ Company aksiyadorlik jamiyati",
        "org_id": "777",
        "isin": "UZ0000000001",
        "type": "stock",
        "share_type": "ordinary",
        "resolved_by": "ticker",
        **overrides,
    }


class _User:
    id = 91

    def __init__(self, email: str):
        self.email = email


class _OneRow:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class _PostgresStrictCandidateConnection:
    """Small adapter that rejects the untyped CASE parameter PostgreSQL rejects."""

    def __init__(self):
        self.row = None
        self.insert_sql = ""
        self.insert_params = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None

    def execute(self, sql, params=()):
        compact = " ".join(str(sql).split())
        if compact.startswith("SELECT * FROM catalog_company_imports"):
            return _OneRow(self.row)
        if compact.startswith("INSERT INTO catalog_company_imports"):
            if "CASE WHEN ?" in compact:
                raise RuntimeError("PostgreSQL cannot infer the CASE parameter type")
            self.insert_sql = compact
            self.insert_params = tuple(params)
            self.row = {
                "ticker": params[0],
                "company_name": params[1],
                "org_id": params[2],
                "status": params[9],
                "reviewed_at": params[12],
            }
            return _OneRow()
        if compact.startswith("INSERT INTO catalog_company_import_events"):
            return _OneRow()
        raise AssertionError(f"Unexpected SQL: {compact}")


def _as_user(monkeypatch, email: str | None) -> None:
    monkeypatch.setattr(
        subject_web_auth.web_auth_store,
        "get_user_by_token",
        lambda token: _User(email) if token and email else None,
    )


def test_discovery_creates_a_pending_candidate_and_approval_publishes_it(monkeypatch):
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda: [_record()])

    discovered = company_imports.refresh_candidates(actor="admin@example.com")
    assert discovered["summary"]["pending"] == 1
    assert discovered["items"][0]["ticker"] == "ZZCO"
    assert discovered["items"][0]["status"] == "pending"

    approved = company_imports.approve_import(
        "ZZCO",
        {"sector": "manufacturing", "review_note": "Verified against issuer card"},
        actor="admin@example.com",
    )
    assert approved["status"] == "approved"
    assert approved["sector"] == "manufacturing"
    assert approved["reviewed_by"] == "admin@example.com"

    conn = reports_catalog.get_catalog_conn()
    try:
        company = conn.execute(
            "SELECT company_name, org_id FROM catalog_companies WHERE ticker='ZZCO'"
        ).fetchone()
        event_actions = [row["action"] for row in conn.execute(
            "SELECT action FROM catalog_company_import_events WHERE ticker='ZZCO' ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    assert company["company_name"] == "ZZ Company aksiyadorlik jamiyati"
    assert company["org_id"] == "777"
    assert event_actions == ["discovered", "approved"]

    body = TestClient(api.app).get("/api/companies").json()
    imported = next(item for item in body["companies"] if item["ticker"] == "ZZCO")
    assert imported == {
        "company_name": "ZZ Company aksiyadorlik jamiyati",
        "ticker": "ZZCO",
        "sector": "manufacturing",
        "logo": "",
    }


def test_candidate_insert_is_postgres_safe(monkeypatch):
    conn = _PostgresStrictCandidateConnection()
    monkeypatch.setattr(company_imports, "_conn", lambda: conn)

    candidate = company_imports._upsert_candidate(_record())

    assert candidate["ticker"] == "ZZCO"
    assert candidate["status"] == "pending"
    assert candidate["reviewed_at"] is None
    assert len(conn.insert_params) == 13
    assert "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)" in conn.insert_sql


def test_regular_catalog_discovery_also_fills_the_admin_review_queue(monkeypatch):
    monkeypatch.setattr(reports_catalog, "_make_session", object)
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda session=None: [_record()])

    result = reports_catalog.discover_and_upsert_securities()

    assert result["queued"] == 1
    queued = company_imports.list_imports("pending")
    assert [item["ticker"] for item in queued["items"]] == ["ZZCO"]


def test_preview_reads_source_logo_and_allows_an_explicit_mapping_correction(monkeypatch):
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda: [_record(org_id="wrong")])
    monkeypatch.setattr(
        openinfo_collector,
        "resolve_company",
        lambda _name: {"org_id": "wrong", "logo": "https://openinfo.uz/media/zz.png"},
    )

    preview = company_imports.preview_import("zzco", actor="admin@example.com")
    assert preview["logo_url"] == "https://openinfo.uz/media/zz.png"
    assert preview["can_approve"] is True

    approved = company_imports.approve_import(
        "ZZCO",
        {"org_id": "777", "isin": "UZ0000000001", "review_note": "OpenInfo source correction"},
        actor="admin@example.com",
    )
    assert approved["org_id"] == "777"
    assert approved["review_note"] == "OpenInfo source correction"


def test_an_unresolved_candidate_cannot_be_approved(monkeypatch):
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda: [_record(org_id=None, resolved_by=None)])
    company_imports.refresh_candidates()

    with pytest.raises(company_imports.CompanyImportError, match="organization ID"):
        company_imports.approve_import("ZZCO", {}, actor="admin@example.com")


def test_admin_can_hide_and_restore_an_approved_company_in_public_catalog(monkeypatch):
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda: [_record()])
    company_imports.refresh_candidates(actor="admin@example.com")
    company_imports.approve_import("ZZCO", {}, actor="admin@example.com")

    hidden = company_imports.set_catalog_visibility(
        "ZZCO", False, actor="admin@example.com",
    )
    assert hidden["catalog_visible"] == 0
    assert all(item["ticker"] != "ZZCO" for item in TestClient(api.app).get(
        "/api/catalog/companies"
    ).json()["companies"])

    restored = company_imports.set_catalog_visibility(
        "ZZCO", True, actor="admin@example.com",
    )
    assert restored["catalog_visible"] == 1
    assert any(item["ticker"] == "ZZCO" for item in TestClient(api.app).get(
        "/api/catalog/companies"
    ).json()["companies"])

    conn = reports_catalog.get_catalog_conn()
    try:
        events = [row["action"] for row in conn.execute(
            "SELECT action FROM catalog_company_import_events WHERE ticker='ZZCO' ORDER BY id"
        ).fetchall()]
    finally:
        conn.close()
    assert events[-2:] == ["catalog_visibility", "catalog_visibility"]


def test_company_import_endpoints_are_human_admin_only(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    client = TestClient(api.app)

    _as_user(monkeypatch, "reader@example.com")
    assert client.get(
        "/api/admin/companies", headers={"Authorization": "Bearer token"}
    ).status_code == 403

    _as_user(monkeypatch, "admin@example.com")
    response = client.get(
        "/api/admin/companies", headers={"Authorization": "Bearer token"}
    )
    assert response.status_code == 200
    assert response.json()["summary"] == {"pending": 0, "approved": 0, "rejected": 0}


def test_admin_can_preview_and_approve_without_starting_external_sync(monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    _as_user(monkeypatch, "admin@example.com")
    monkeypatch.setattr(entity_resolver, "resolve_all", lambda: [_record()])
    monkeypatch.setattr(
        openinfo_collector,
        "resolve_company",
        lambda _name: {"org_id": "777", "logo": None},
    )
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer token"}

    preview = client.get("/api/admin/companies/ZZCO/preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["company"]["ticker"] == "ZZCO"

    approved = client.post(
        "/api/admin/companies/ZZCO/approve",
        headers=headers,
        json={"sector": "trade", "sync": False},
    )
    assert approved.status_code == 200
    assert approved.json()["sync_requested"] is False
    assert approved.json()["company"]["status"] == "approved"

    hidden = client.patch(
        "/api/admin/companies/ZZCO/visibility",
        headers=headers,
        json={"visible": False},
    )
    assert hidden.status_code == 200
    assert hidden.json()["visible"] is False
    assert hidden.json()["company"]["catalog_visible"] == 0
