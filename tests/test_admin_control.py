"""Control-plane acceptance checks against isolated persistence and real handlers."""
from __future__ import annotations

import web_auth as subject_web_auth

import io
import sqlite3
import json
import uuid

import pytest

from admin_control import store as s, service, rules, documents, worker, adapters

ADMIN = {"id": 1, "email": "owner@example.test", "role": "administrator"}
EDITOR = {"id": 2, "email": "reviewer@example.test", "role": "rule_editor"}
VIEWER = {"id": 3, "email": "viewer@example.test", "role": "viewer"}


def test_catalog_refresh_preserves_special_issuer_classification(monkeypatch):
    import reports_catalog

    def source_connection():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE catalog_companies (ticker, company_name, org_id, last_synced_at)")
        conn.execute("INSERT INTO catalog_companies VALUES ('URTS', 'Commodity Exchange', '123', NULL)")
        conn.execute("CREATE TABLE catalog_reports (id INTEGER)")
        return conn

    monkeypatch.setattr(reports_catalog, "get_catalog_conn", source_connection)
    assert adapters.refresh_catalog() == {"documents": 0, "issuers": 1, "verified": False}
    with s.connection() as conn:
        issuer = next(item for item in s.all_items(conn, "issuers") if item["ticker"] == "URTS")
    assert issuer["special_type"] == "commodity_exchange"
    assert issuer["sector_template"] == "commodity_exchange"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("ADMIN_CONTROL_DB", str(tmp_path / "control.db"))
    monkeypatch.setenv("ADMIN_DOCUMENT_DIR", str(tmp_path / "originals"))
    monkeypatch.setenv("ADMIN_ENVIRONMENT", "test")
    monkeypatch.setenv("ADMIN_ROLES", "{}")
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "sector.db"))
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))


def put(kind, value):
    with s.connection(write=True) as c:
        return s.put(c, kind, value)


def get(kind, key):
    with s.connection() as c:
        return s.get(c, kind, key)


def execute(kind, key, action, data=None, person=ADMIN, command_key=None):
    data = {"reason": "Acceptance test", **(data or {})}
    payload = [kind, key, action, data]
    return s.command(person, command_key or str(uuid.uuid4()), payload, "test-request",
                     lambda c: service.execute(c, person, kind, key, action, data, "test-request"))


def formula_config():
    return {"code": "current_ratio", "numerators": ["form1:c390"], "denominators": ["form1:c600"], "percent": False,
            "test_cases": [{"inputs": {"form1:c390": "200", "form1:c600": "100"}, "expected": "2"},
                           {"inputs": {"form1:c390": "200", "form1:c600": "0"}, "expected": None}]}


def test_viewer_cannot_mutate_even_with_direct_command():
    with pytest.raises(s.ControlError, match="role") as error:
        execute("catalog", "catalog", "sync", person=VIEWER)
    assert error.value.status == 403


def test_idempotent_command_and_payload_conflict():
    first = execute("catalog", "catalog", "sync", command_key="repeat-command")
    second = execute("catalog", "catalog", "sync", command_key="repeat-command")
    assert first["job_id"] == second["job_id"]
    with s.connection() as c:
        assert s.query(c, "jobs")["total"] == 1
        assert s.query(c, "audit")["total"] == 1
    with pytest.raises(s.ControlError) as error:
        execute("catalog", "catalog", "sync", {"reason": "Different request"}, command_key="repeat-command")
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_immutable_history_and_environment_isolation(monkeypatch):
    value = put("documents", {"id": "d", "ticker": "T", "status": "DISCOVERED"})
    put("documents", {**value, "status": "VALIDATED"})
    with s.connection() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM control_revisions").fetchone()["n"] == 2
    with pytest.raises(Exception, match="immutable"):
        with s.connection(write=True) as c:
            c.execute("DELETE FROM control_revisions")
    monkeypatch.setenv("ADMIN_ENVIRONMENT", "another-environment")
    with s.connection() as c:
        assert s.query(c, "documents")["total"] == 0
    with pytest.raises(s.ControlError):
        get("documents", "d")


def test_sqlite_revision_retention_keeps_recent_history_but_not_public_deletes():
    value = put("documents", {"id": "retained", "ticker": "T", "status": "V0"})
    for version in range(1, 14):
        value = put("documents", {**value, "status": f"V{version}"})
    with s.connection() as c:
        rows = c.execute(
            "SELECT version FROM control_revisions WHERE id='retained' ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in rows] == list(range(5, 15))
    with pytest.raises(Exception, match="immutable"):
        with s.connection(write=True) as c:
            c.execute("DELETE FROM control_revisions WHERE id='retained'")


def test_filter_full_dataset_cursor_ties_and_invalid_sort():
    for i in range(125):
        put("documents", {"id": f"doc{i:03}", "ticker": "UZNF" if i % 2 else "HMKB", "status": "FOUND", "period": "2026H1"})
    with s.connection() as c:
        a = s.query(c, "documents", {"ticker": "UZNF", "sort": "period"}, limit=50)
        b = s.query(c, "documents", {"ticker": "UZNF", "sort": "period", "cursor": a["next_cursor"]}, limit=50)
        assert a["total"] == 62
        assert len(a["items"]) + len(b["items"]) == 62
        assert len({r["id"] for r in a["items"] + b["items"]}) == 62
        with pytest.raises(s.ControlError):
            s.query(c, "documents", {"sort": "payload; DROP TABLE control_resources"})
        with pytest.raises(s.ControlError):
            s.query(c, "documents", {"ticker": "HMKB", "sort": "period", "cursor": a["next_cursor"]})


def test_unknown_is_not_zero_and_percent_units():
    import sector_analysis as engine
    config = formula_config()
    config.update(percent=True)
    output = engine.enterprise_ratios({"form1:c390": {"raw_current": "4.7"}, "form1:c600": {"raw_current": "100"}}, "non_financial", "nsbu", "2026Q1", methods={"current_ratio": (config["numerators"], config["denominators"], True)})[0]
    assert output["value"] == 4.7 and output["unit"] == "percent"
    assert engine.enterprise_ratios({}, "investment_fund_ifrs_annual", "ifrs", "2026H1") == []
    assert engine.enterprise_ratios({}, "non_financial", "nsbu", "2026Q1")[0]["value"] is None


def test_rule_tests_four_eyes_and_optimistic_lock():
    put("issuers", {"id": "UZNF", "ticker": "UZNF"})
    draft = execute("rules", "new", "draft", {"category": "formula", "config": formula_config()})["item"]
    assert draft["status"] == "DRAFT"
    execute("rules", draft["id"], "test", {"version": draft["version"]})
    assert worker.run_one()
    tested = get("rules", draft["id"])
    assert tested["tests"]["passed"]
    assert tested["impact"]["tickers"] == ["UZNF"]
    with pytest.raises(s.ControlError) as stale:
        execute("rules", draft["id"], "approve", {"version": draft["version"]}, person=EDITOR)
    assert stale.value.code == "VERSION_CONFLICT"
    with pytest.raises(s.ControlError) as self_review:
        execute("rules", draft["id"], "approve", {"version": tested["version"]})
    assert self_review.value.code == "SECOND_REVIEWER_REQUIRED"
    approved = execute("rules", draft["id"], "approve", {"version": tested["version"]}, person=EDITOR)["item"]
    executing = execute("rules", draft["id"], "activate", {"version": approved["version"]}, person=EDITOR)["item"]
    assert executing["status"] == "ROLLING_OUT"
    assert not rules.active()


def test_failed_regression_never_unlocks_activation():
    config = formula_config()
    config["test_cases"][0]["expected"] = "999"
    draft = execute("rules", "new", "draft", {"category": "formula", "config": config})["item"]
    execute("rules", draft["id"], "test", {"version": draft["version"]})
    worker.run_one()
    draft = get("rules", draft["id"])
    assert draft["status"] == "DRAFT" and not draft["tests"]["passed"]
    with pytest.raises(s.ControlError) as error:
        execute("rules", draft["id"], "approve", {"version": draft["version"]}, person=EDITOR)
    assert error.value.code == "TESTS_AND_IMPACT_REQUIRED"


def test_new_data_invalidates_approved_impact():
    draft = execute("rules", "new", "draft", {"category": "formula", "config": formula_config()})["item"]
    execute("rules", draft["id"], "test", {"version": draft["version"]})
    worker.run_one()
    tested = get("rules", draft["id"])
    put("documents", {"id": "new-source", "ticker": "HMKB"})
    with pytest.raises(s.ControlError) as error:
        execute("rules", draft["id"], "approve", {"version": tested["version"]}, person=EDITOR)
    assert error.value.code == "IMPACT_CHANGED"


def test_incident_dedup_and_verified_closure():
    with s.connection(write=True) as c:
        a = service.incident(c, "UNKNOWN_ROW", "doc1", stage="mapping", evidence={"ticker": "UZNF"})
        b = service.incident(c, "UNKNOWN_ROW", "doc2", stage="mapping", evidence={"ticker": "HMKB"})
        again = service.incident(c, "UNKNOWN_ROW", "doc2", stage="mapping", evidence={"ticker": "HMKB"})
    assert a["id"] == b["id"] and b["impact_count"] == 2 and again["occurrences"] == 2
    with pytest.raises(s.ControlError) as error:
        execute("incidents", b["id"], "resolve", {"version": b["version"]})
    assert error.value.code == "IMPACT_NOT_VERIFIED"
    for key in ("doc1", "doc2"):
        put("jobs", {"id": key, "entity_id": key, "status": "COMPLETED", "finished_at": s.now(), "result": {"verified": True, "verification_scope": "financial"}})
    assert execute("incidents", b["id"], "resolve", {"version": b["version"]})["item"]["status"] == "RESOLVED"


def test_retry_keeps_old_attempt_and_cancel_is_checkpoint_safe():
    first = execute("catalog", "catalog", "sync")["item"]
    done = put("jobs", {**first, "status": "FAILED", "errors": [{"code": "SOURCE_UNAVAILABLE"}]})
    new = execute("jobs", done["id"], "retry", {"version": done["version"]})["item"]
    assert new["id"] != first["id"] and new["parent_job_id"] == first["id"]
    assert get("jobs", first["id"])["status"] == "FAILED"
    cancelled = execute("jobs", new["id"], "cancel", {"version": new["version"]})["item"]
    assert cancelled["status"] == "CANCELLED"
    assert worker.run_one() is False


def test_temporal_and_mime_classification():
    annual = documents.classify({"standard": "IFRS", "duration_months": 12, "period_end": "2026-12-31", "published_at": "2026-05-21"})
    assert "ANNUAL_BEFORE_YEAR_END" in annual["blockers"]
    interim = documents.classify({"standard": "IFRS", "declared_format": "PDF", "published_at": "2026-08-01"}, "Six months ended 30 June 2026", "XLSX")
    assert interim["period_end"] == "2026-06-30" and interim["duration_months"] == 6
    assert interim["statement_type"] == "interim" and interim["detected_format"] == "XLSX"
    assert interim["warnings"] == ["FORMAT_MISMATCH"] and not interim["blockers"]


def workbook_bytes():
    import openpyxl
    book = openpyxl.Workbook()
    book.active.title = "Balance"
    book.active.append(["Six months ended 30 June 2026", 100, "=HYPERLINK(\"https://example.invalid\",\"unsafe\")"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_workbook_is_inert_and_checksum_is_checked():
    data = workbook_bytes()
    checksum = documents.save_original(data)
    result = documents.preview({"checksum": checksum})
    assert result["sheets"] == ["Balance"]
    assert result["rows"][0][1] == {"address": "B1", "value": "100"}
    assert result["rows"][0][2]["value"] is None
    documents.original_path(checksum).write_bytes(b"tampered")
    with pytest.raises(s.ControlError) as error:
        documents.preview({"checksum": checksum})
    assert error.value.code == "CHECKSUM_MISMATCH"


def test_pdf_preview_and_image():
    from reportlab.pdfgen import canvas
    data = io.BytesIO()
    page = canvas.Canvas(data)
    page.drawString(50, 700, "Balance 100")
    page.showPage(); page.save()
    document = {"checksum": documents.save_original(data.getvalue())}
    preview = documents.preview(document, query="100")
    assert preview["format"] == "PDF" and preview["matches"]
    assert documents.pdf_page_image(document, 1).startswith(b"\x89PNG")


def test_reprocess_creates_new_runs_and_deduplicates_bytes(monkeypatch):
    monkeypatch.setattr(documents, "fetch_original", lambda url: workbook_bytes())
    for i in (1, 2):
        put("documents", {"id": f"doc{i}", "ticker": "UZNF", "standard": "IFRS", "period": "2026", "period_end": "2026-12-31",
                          "duration_months": 12, "published_at": "2026-08-01", "source_url": f"https://openinfo.uz/{i}", "source": "openinfo.uz"})
    a = worker.process_document("doc1")
    b = worker.process_document("doc2")
    assert a["verified"] and b["duplicate"]
    assert get("documents", "doc1")["period"] == "2026H1"
    assert get("documents", "doc1")["pipeline_stage"] == "RECALCULATING"
    assert get("documents", "doc2")["canonical_document_id"] == "doc1"
    assert get("documents", "doc2")["pipeline_stage"] == "DUPLICATE"
    second = worker.process_document("doc1")
    assert second["parser_run_id"] != a["parser_run_id"]


def test_source_failure_is_persisted_as_a_document_stage(monkeypatch):
    put("documents", {"id": "source-down", "ticker": "UZNF",
                      "source_url": "https://openinfo.uz/down"})
    monkeypatch.setattr(documents, "fetch_original",
                        lambda url: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        worker.process_document("source-down")
    stored = get("documents", "source-down")
    assert stored["pipeline_stage"] == "SOURCE_UNAVAILABLE"
    assert [item["stage"] for item in stored["pipeline_journal"]] == [
        "DOWNLOADING", "SOURCE_UNAVAILABLE"]


def test_api_access_validation_and_export(monkeypatch):
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from admin_control.api import router
    person = dict(VIEWER)
    def gate(request: __import__("fastapi").Request):
        request.state.control_actor = person
    app = FastAPI()
    app.include_router(router, dependencies=[Depends(gate)])
    client = TestClient(app)
    put("documents", {"id": "x", "ticker": "UZNF", "title": "=CMD()"})
    assert client.get("/api/admin/control/session").json()["actor"]["role"] == "viewer"
    assert client.get("/api/admin/control/access").status_code == 403
    denied = client.post("/api/admin/control/catalog/catalog/sync", json={"reason": "test"}, headers={"Idempotency-Key": "test-command"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "PERMISSION_DENIED"
    invalid = client.post("/api/admin/control/catalog/catalog/sync", json={"reason": "x", "unexpected": "field"})
    assert invalid.status_code == 422 and invalid.json()["error"]["field_errors"]
    exported = client.get("/api/admin/control/documents/export?ticker=UZNF&format=csv")
    assert exported.status_code == 200 and "'=CMD()" in exported.text
    assert client.get("/api/admin/control/documents/export?ticker=NOPE").json() == []
    person.update(ADMIN)
    from web_auth import web_auth_store
    monkeypatch.setattr(web_auth_store, "verify_admin_two_factor", lambda *a: False)
    denied = client.post("/api/admin/control/catalog/catalog/sync", json={"reason": "test"}, headers={"Idempotency-Key": "test-command"})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "MFA_REQUIRED"


def test_http_document_job_persists_revisions_and_original(monkeypatch):
    """Actual app gate → API → SQL job → worker → API preview; source IO is a fixture."""
    import api
    from fastapi.testclient import TestClient
    user = type("User", (), {"id": 77, "email": "operator@example.test"})()
    monkeypatch.setenv("ADMIN_ROLES", json.dumps({user.email: "administrator"}))
    monkeypatch.setattr(subject_web_auth.web_auth_store, "get_user_by_token", lambda token: user if token == "session-fixture" else None)
    monkeypatch.setattr(subject_web_auth.web_auth_store, "verify_admin_two_factor", lambda user_id, code: user_id == 77 and code == "123456")
    monkeypatch.setattr(documents, "fetch_original", lambda url: workbook_bytes())
    doc = put("documents", {"id": "http-doc", "ticker": "UZNF", "standard": "IFRS", "period": "2026", "period_end": "2026-12-31",
                          "duration_months": 12, "published_at": "2026-08-01", "source_url": "https://openinfo.uz/test", "source": "openinfo.uz"})
    client = TestClient(api.app)
    base = "/api/admin/control"
    assert client.get(base + "/session").status_code == 401
    assert client.get(base + "/session", headers={"X-Admin-Secret": "machine-only"}).status_code == 401
    headers = {"Authorization": "Bearer session-fixture", "Idempotency-Key": "real-persisted-command"}
    payload = {"version": doc["version"], "reason": "Check the actual source header"}
    assert client.post(base + "/documents/http-doc/reprocess", headers=headers, json=payload).json()["error"]["code"] == "MFA_REQUIRED"
    headers["X-Admin-OTP"] = "123456"
    queued = client.post(base + "/documents/http-doc/reprocess", headers=headers, json=payload)
    assert queued.status_code == 202
    assert client.post(base + "/documents/http-doc/reprocess", headers=headers, json=payload).json()["job_id"] == queued.json()["job_id"]
    assert worker.run_one()
    job = client.get(base + "/jobs/" + queued.json()["job_id"], headers=headers).json()["item"]
    assert job["status"] == "COMPLETED" and job["checkpoint"] == 1
    changed = client.get(base + "/documents/http-doc", headers=headers).json()["item"]
    assert changed["period"] == "2026H1" and changed["metadata_verified"] and not changed["verified"]
    assert client.get(base + "/documents/http-doc/preview?sheet=Balance", headers=headers).json()["rows"][0][1]["value"] == "100"
    history = client.get(base + "/documents/http-doc/history", headers=headers).json()["items"]
    assert len(history) >= 2 and {r["period"] for r in history} == {"2026", "2026H1"}
    assert [item["stage"] for item in changed["pipeline_journal"]] == [
        "DOWNLOADING", "PARSING", "VALIDATING", "READY_IN_LIBRARY", "RECALCULATING"]
    monkeypatch.setenv("ADMIN_ROLES", json.dumps({user.email: "viewer"}))
    assert client.post(base + "/documents/http-doc/reprocess", headers={**headers, "Idempotency-Key": "viewer-denied"}, json={**payload, "version": changed["version"]}).status_code == 403
    assert client.get("/api/admin/overview", headers=headers).status_code == 403


def test_publication_pointer_and_four_eyes_rollback_survive_reindex():
    from reporting import store as report_store
    from reporting import publication, worker as report_worker
    def report(version, period, status="available"):
        return {"version": version, "issuer": {"id": "1", "ticker": "FACT"}, "standard": "nsbu", "language": "en",
                "period": period, "financial_as_of": "2026-06-30" if period == "2026Q2" else "2026-03-31", "status": status,
                "availability": {}, "data_quality": [], "source_snapshot_hash": version, "calculation_version": "v1"}
    publication.publish_report(report("first", "2026Q1"))
    publication.publish_report(report("latest", "2026Q2"))
    publication.publish_report(report("historical", "2026Q1"))
    publication.publish_report(report("failed", "2026Q2", "quality_blocked"))
    adapters.refresh_analyses()
    with s.connection() as c:
        assert [p["id"] for p in s.all_items(c, "publications", {"status": "PUBLISHED"})] == ["latest"]
        issue = service.incident(c, "SOURCE_REVIEW", "latest", stage="analysis")
    original = get("publications", "first")
    pending = execute("publications", "first", "rollback", {"version": original["version"], "incident_id": issue["id"]})["item"]
    with pytest.raises(s.ControlError) as error:
        execute("publications", "first", "rollback", {"version": pending["version"], "incident_id": issue["id"]})
    assert error.value.code == "SECOND_REVIEWER_REQUIRED"
    execute("publications", "first", "rollback", {"version": pending["version"], "incident_id": issue["id"]}, person=EDITOR)
    assert worker.run_one()
    adapters.refresh_analyses()
    with s.connection() as c:
        assert [p["id"] for p in s.all_items(c, "publications", {"status": "PUBLISHED"})] == ["first"]
    domain = report_store.connect()
    try:
        assert domain.execute("SELECT version FROM sector_publications").fetchone()["version"] == "first"
    finally:
        domain.close()


def test_metadata_only_update_retains_old_original_in_history():
    row = {"ticker": "FACT", "report_form": "MSFO", "year": 2026, "quarter": 2, "title": "First title", "excel_url": "https://openinfo.uz/same.xlsx"}
    with s.connection(write=True) as c:
        first = adapters.index_catalog_row(c, row)
        stored = s.put(c, "documents", {**first, "checksum": "previous-original", "parsed": True})
        assert adapters.index_catalog_row(c, row)["version"] == stored["version"]
        revised = adapters.index_catalog_row(c, {**row, "title": "Corrected source title"})
        assert revised["version"] > stored["version"] and revised["previous_checksum"] == "previous-original"
        assert not revised["parsed"] and revised["checksum"] is None


def test_catalog_adapter_does_not_classify_audit_opinion_as_ifrs():
    audit = adapters.catalog_document({
        "ticker": "FACT", "report_form": "Audition", "year": 2025,
        "quarter": 0, "title": "Отчет независимых аудиторов",
        "pdf_url": "https://openinfo.uz/audit.pdf",
    })
    statements = adapters.catalog_document({
        "ticker": "FACT", "report_form": "MSFO", "year": 2025,
        "quarter": 0, "title": "Consolidated financial statements",
        "pdf_url": "https://openinfo.uz/ifrs.pdf",
    })
    assert audit["standard"] == "AUDIT"
    assert statements["standard"] == "IFRS"


@pytest.mark.parametrize("configured", ["[]", '"administrator"', "invalid", '{"owner@example.test":[]}', '{"owner@example.test":null}'])
def test_malformed_role_configuration_fails_closed(monkeypatch, configured):
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN["email"])
    monkeypatch.setenv("ADMIN_ROLES", configured)
    assert service.role_for(ADMIN["email"]) is None


def test_metadata_verification_cannot_close_mapping_incident():
    with s.connection(write=True) as c:
        issue = service.incident(c, "UNKNOWN_ROW", "doc1", stage="mapping")
    put("jobs", {"id": "metadata", "entity_id": "doc1", "status": "COMPLETED", "finished_at": s.now(),
                 "result": {"verified": True, "verification_scope": "classification"}})
    with pytest.raises(s.ControlError) as error:
        execute("incidents", issue["id"], "resolve", {"version": issue["version"]})
    assert error.value.code == "IMPACT_NOT_VERIFIED"


def test_parser_shadow_uses_unchanged_original_bytes():
    data = workbook_bytes()
    checksum = documents.save_original(data)
    doc = put("documents", {"id": "shadow-doc", "ticker": "UZNF", "checksum": checksum, "standard": "IFRS", "period": "2026", "period_end": "2026-12-31",
                           "duration_months": 12, "published_at": "2026-08-01", "detected_format": "XLSX"})
    rule = {"id": "parser-draft", "category": "parser", "config": {"code": "interim", "header_phrase": "Six months ended", "duration_months": 6,
           "test_cases": [{"document": doc, "header": "Six months ended 30 June 2026", "expected": {"period": "2026H1"}}]}}
    result = rules.parser_shadow(rule, "UZNF")
    assert result["verified"] and result["documents"][0]["draft"]["period"] == "2026H1"
    assert get("documents", "shadow-doc")["period"] == "2026"
    assert documents.read_original(doc) == data


def test_rollout_checks_all_targets_and_reverts_failed_production(monkeypatch):
    put("issuers", {"id": "FACT", "ticker": "FACT"})
    draft = execute("rules", "new", "draft", {"category": "formula", "config": formula_config()})["item"]
    execute("rules", draft["id"], "test", {"version": draft["version"]})
    worker.run_one()
    tested = get("rules", draft["id"])
    approved = execute("rules", draft["id"], "approve", {"version": tested["version"]}, person=EDITOR)["item"]
    execute("rules", draft["id"], "activate", {"version": approved["version"]}, person=EDITOR)
    def controlled_recalculation(ticker, *, override=None, persist=True):
        return {"verified": not persist, "verification_scope": "financial", "versions": ["shadow" if not persist else "failed-run"],
                "statuses": ["available" if not persist else "quality_blocked"]}
    monkeypatch.setattr(worker, "recalculate", controlled_recalculation)
    worker.run_one()
    assert get("rules", draft["id"])["status"] == "ACTIVE"
    worker.run_one()
    assert get("rules", draft["id"])["status"] == "ROLLED_BACK" and not rules.active()
    with s.connection() as c:
        assert any(i["blocker_code"] == "PRODUCTION_VERIFICATION_FAILED" for i in s.all_items(c, "incidents"))


def test_real_filing_fixture_projects_every_ratio_input_with_exact_rows():
    from datetime import date
    from pathlib import Path
    import sector_analysis as engine
    filing = json.loads((Path(__file__).parent / "fixtures/sector_v22_filings.json").read_text(encoding="utf8"))["UZMK"]
    for sheet in filing["workbook"].values():
        if isinstance(sheet, dict):
            sheet["source_url"] = "https://openinfo.uz/source-workbook.xlsx"
    snapshot = {"organization_type": "non_financial", "standard": "nsbu", "scope": "separate", "period": "2026Q2",
                "period_basis": "cumulative_ytd", "current_values": {}, "previous_values": {}, "opening_values": {},
                "source": filing["source"], "quality": {"data_quality": []}}
    report = engine.make_report(snapshot, {**filing["issuer"], "oked_code": "24100"}, "en", date(2026, 8, 30), filing["workbook"])
    assert report["status"] == "available"
    adapters.record_analysis(report, current_version=None)
    with s.connection() as c:
        trace = next(r for r in s.all_items(c, "calculations") if r["metric_code"] == "current_ratio")
        assert len(trace["inputs"]) == 5
        assert trace["value"] == next(r["value"] for r in report["ratios"] if r["metric_code"] == "current_ratio")
        for fact in trace["inputs"]:
            assert fact["source_location"]["row"] > 0 and fact["source_location"]["sheet"]
            assert s.get(c, "documents", fact["document_id"])["source_url"] == "https://openinfo.uz/source-workbook.xlsx"
