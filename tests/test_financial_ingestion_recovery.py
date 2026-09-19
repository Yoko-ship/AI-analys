"""Interim, component evidence, shared reads and operational recovery checks."""
import json

import pytest

import reports_catalog as rc
from financial_ingestion import documents, extract, maintenance, publication, store, validation
from test_financial_ingestion import setup, stage, candidates


def test_reviewed_release_verifies_and_preserves_existing_publication(setup, monkeypatch, tmp_path):
    from scripts.publish_reviewed_bank_ifrs import release
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    stage(setup)
    publication.publish("BRBN", actor="initial-review")
    before = publication.series("BRBN")
    result = release(fetch=lambda url: setup[1])
    assert result == {"verified_figures": 9, "periods": 1, "preserved_previous_values": True}
    assert publication.series("BRBN") == before


def test_reviewed_release_rejects_source_change_before_writes(setup, monkeypatch, tmp_path):
    from scripts.publish_reviewed_bank_ifrs import release
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    with pytest.raises(ValueError, match="Source changed since visual review"):
        release(fetch=lambda url: setup[1] + b"changed")
    assert not (tmp_path / "backups").exists()
    assert publication.series("BRBN") is None


def test_reviewed_release_refuses_changed_published_values(setup, monkeypatch, tmp_path):
    from scripts.publish_reviewed_bank_ifrs import release
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    stage(setup)
    publication.publish("BRBN", actor="initial-review")
    before = publication.series("BRBN")
    setup[0]["figures"]["net_income"]["raw_value"] = "1"
    with pytest.raises(ValueError, match="Existing published value changed"):
        release(fetch=lambda url: setup[1])
    assert publication.series("BRBN") == before


def test_signed_component_subtraction_preserves_literal_source_expenses(setup):
    payload = validation.from_review(setup[0])
    payload["figures"]["operating_income"] = {
        "raw_value": "140", "raw_label": "Calculated operating income", "page": 1,
        "column_year": 2024, "calculation": "signed_sum", "components": [
            {"raw_value": "100", "raw_label": "Profit before tax", "page": 1,
             "column_year": 2024, "coefficient": 1},
            {"raw_value": "-50", "raw_label": "Operating expenses", "page": 1,
             "column_year": 2024, "coefficient": -1},
            {"raw_value": "10", "raw_label": "Share of associates", "page": 1,
             "column_year": 2024, "coefficient": -1},
        ],
    }
    assert validation.validate(payload, page_count=1)["valid"]
    payload["figures"]["operating_income"]["components"][1]["coefficient"] = 0
    assert "COMPONENT_COEFFICIENT_INVALID:operating_income" in validation.validate(payload, page_count=1)["errors"]


def test_reviewed_correction_requires_exact_previous_source_and_values(setup, monkeypatch, tmp_path):
    from scripts.publish_reviewed_bank_ifrs import release
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    stage(setup)
    publication.publish("BRBN", actor="initial-review")
    old = validation.validate(validation.from_review(setup[0]), page_count=1)["normalized_uzs"]["net_income"]
    setup[0]["figures"]["net_income"]["raw_value"] = "1"
    setup[0]["supersedes"] = {
        "source_sha256": "0" * 64, "reason": "Explicit source correction",
        "normalized_uzs": {"net_income": {"before": old, "after": str(setup[0]["unit_scale"])}}}
    with pytest.raises(ValueError, match="Existing published value changed"):
        release(fetch=lambda url: setup[1], allow_reviewed_corrections=True)
    setup[0]["supersedes"]["source_sha256"] = setup[0]["sha256"]
    result = release(fetch=lambda url: setup[1], allow_reviewed_corrections=True)
    assert len(result["reviewed_corrections"]) == 1
    assert not result["preserved_previous_values"]


def test_reviewed_issuer_website_discovery_is_bound_to_catalog_issuer(setup, monkeypatch):
    monkeypatch.setenv("FINANCIAL_SOURCE_POLICY", "reviewed_issuers")
    setup[0].update(source_kind="issuer_website", source_page_url="https://mkbank.uz/reports/",
                    pdf_url="https://mkbank.uz/upload/reviewed.pdf", document_year=2024)
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    c = store.connect()
    try:
        row = c.execute("SELECT * FROM ingest_sources WHERE url=?", (setup[0]["pdf_url"],)).fetchone()
        assert row["org_id"] == setup[0]["org_id"]
        assert row["category"] == "IssuerIFRS"
    finally:
        c.close()
    setup[0]["org_id"] = "99"
    with pytest.raises(ValueError, match="does not match the catalog issuer"):
        documents.discover(ticker="BRBN", processor=extract.processor_version())


def test_component_arithmetic_and_evidence(setup):
    payload = validation.from_review(setup[0])
    item = payload["figures"]["interest_income"]
    item.update(raw_value="30", calculation="sum", components=[
        {"raw_value": "10", "page": 1, "column_year": 2024, "raw_label": "Effective interest"},
        {"raw_value": "20", "page": 1, "column_year": 2024, "raw_label": "Other interest"},
    ])
    assert validation.validate(payload, page_count=1)["valid"]
    item["components"][1]["raw_value"] = "21"
    assert "COMPONENT_SUM_MISMATCH:interest_income" in validation.validate(payload, page_count=1)["errors"]
    item["components"][1].update(raw_value="20", column_year=2023)
    assert "COMPONENT_EVIDENCE_INVALID:interest_income" in validation.validate(payload, page_count=1)["errors"]


def test_interim_snapshot_never_becomes_an_annual_or_standalone_quarter(setup):
    setup[0].update(period_start="2024-01-01", period_end="2024-06-30")
    stage(setup)
    publication.publish("BRBN", actor="reviewer")
    assert publication.series("BRBN") == {}
    interim = publication.series("BRBNP", quarterly=True)
    assert set(interim) == {"2024Q2"}
    latest = rc.get_all_financials("MSFO")["BRBNP"]
    assert latest["period_months"] == 6 and latest["is_ytd"]
    assert latest["balance"]["assets_end"] == interim["2024Q2"]["total_assets"]
    assert "annual" not in latest
    passport = publication.passport("BRBN", "2024Q2", "net_profit")
    assert passport["source"]["period_basis"] == "cumulative_ytd"
    assert publication.catalog_labels("BRBN")[setup[0]["pdf_url"]]["quarter"] == 2
    index = rc.get_company_index("BRBN")
    assert index["availability"]["MSFO"]["annual"] == []
    assert index["availability"]["MSFO"]["quarter"][0]["quarter"] == 2
    coverage = rc.get_financial_history_coverage("MSFO")["BRBN"]
    assert coverage["complete_periods"] == 1
    assert coverage["missing_periods"] == []
    import api
    from fastapi.testclient import TestClient
    response = TestClient(api.app).get("/api/company/BRBN/financials?form=MSFO&freq=quarterly").json()
    assert response["period_basis"] == "cumulative_ytd"
    assert response["periods"] == ["2024Q2"]
    assert response["series"]["total_assets"]["values"]["2024Q2"] == interim["2024Q2"]["total_assets"] * 1000


def test_partial_interim_reports_field_gap(setup):
    setup[0].update(period_start="2024-01-01", period_end="2024-06-30")
    setup[0]["figures"].pop("interest_income")
    stage(setup)
    publication.publish("BRBN", actor="reviewer")
    import api
    from fastapi.testclient import TestClient
    response = TestClient(api.app).get("/api/company/BRBN/financials?form=MSFO&freq=quarterly").json()
    assert response["availability"] == "PARTIAL"
    assert response["data_gaps"][0]["fields"] == ["interest_income"]


def test_replaced_source_cannot_certify_live_catalog_label(setup):
    stage(setup)
    publication.publish("BRBN", actor="reviewer")
    assert publication.catalog_labels("BRBN")
    with store.transaction() as c:
        c.execute("UPDATE ingest_sources SET latest_version='replacement'")
    assert publication.catalog_labels("BRBN") == {}
    assert publication.series("BRBN")["2024"]  # Archived evidence is retained.


def test_latest_annual_and_prior_are_snapshot_only(setup):
    stage(setup)
    base = candidates()[0]
    payload = json.loads(base["payload_json"])
    payload["classification"].update(period_start="2023-01-01", period_end="2023-12-31", document_year=2023)
    for f in payload["figures"].values():
        f["column_year"] = 2023
    prior = publication.propose(base["id"], payload, actor="reviewer", reason="test")
    publication.approve(prior, actor="reviewer", reason="test")
    publication.publish("BRBN", actor="publisher", candidate_ids=[base["id"], prior])
    result = rc.get_all_financials("MSFO")["BRBN"]
    assert result["year"] == 2024 and result["prior"]["year"] == 2023
    assert result["prior"]["snapshot_id"]
    assert result["balance"]["equity_end"] == publication.series("BRBN")["2024"]["total_equity"]


def test_verified_backup_restore_and_corruption_detection(setup, monkeypatch, tmp_path):
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    stage(setup)
    publication.publish("BRBN", actor="reviewer")
    result = maintenance.backup()
    assert result["verified"] and result["published_periods"] == 1 and result["artifacts"] == 1
    assert maintenance.verify_backup(result["path"]) == result
    obj = tmp_path / "backups" / "objects" / (setup[0]["sha256"] + ".pdf")
    original = next((tmp_path / "originals").rglob("*.pdf"))
    assert obj.stat().st_ino != original.stat().st_ino
    obj.write_bytes(b"corrupt test fixture")
    with pytest.raises(ValueError, match="artifact mismatch"):
        maintenance.verify_backup(result["path"])
    assert publication.series("BRBN")["2024"]


def test_backup_before_first_job(setup, monkeypatch, tmp_path):
    monkeypatch.setenv("FINANCIAL_BACKUP_DIR", str(tmp_path / "backups"))
    assert maintenance.backup()["artifacts"] == 0


def test_dashboard_incidents_deduplicate_resolve_and_reopen(setup, monkeypatch):
    monkeypatch.setattr(store, "now", lambda: "2026-09-18T00:00:00+00:00")
    monkeypatch.setattr(maintenance.time, "time", lambda: 1789689600)
    first = maintenance.monitor()
    assert {"WORKER_STALE", "BACKUP_STALE"} <= first["incidents"].keys()
    maintenance.monitor()
    assert len(maintenance.incidents()) == 2
    with store.transaction() as c:
        store.event(c, "test", "worker.completed")
        store.event(c, "test", "backup.verified")
    assert maintenance.monitor()["ok"]
    assert maintenance.incidents() == []
    assert not maintenance.dashboard()["monitor_stale"]
    monkeypatch.setattr(store, "now", lambda: "2026-09-20T00:00:00+00:00")
    monkeypatch.setattr(maintenance.time, "time", lambda: 1789862400)
    assert maintenance.dashboard()["monitor_stale"]
    maintenance.monitor()
    assert {i["first_seen"] for i in maintenance.incidents()} == {"2026-09-20T00:00:00+00:00"}


def test_dashboard_unavailable_is_not_healthy(monkeypatch):
    def unavailable():
        raise RuntimeError("test outage")
    monkeypatch.setattr(store, "status", unavailable)
    assert maintenance.dashboard()["available"] is False
    assert maintenance.dashboard()["monitor_stale"] is True


def test_income_only_page_is_extracted_but_requires_review():
    draft = extract.draft({1: "2024 IFRS consolidated thousands of soums", 8: "Statement of profit or loss\nInterest income 100,000 90,000"}, {"page_count": 8})
    assert draft["figures"]["interest_income"]["raw_value"] == "100000"
    assert not validation.validate(draft, page_count=8)["valid"]


def test_unified_discovery_reads_later_pages(monkeypatch):
    first = [{"id": n, "organization": 23} for n in range(200)]
    second = [{"id": 201, "organization": 23, "properties": {"org_type": "bank"}}, {"id": 202, "organization": 99}]
    calls = []
    def fetch(session, url, params):
        calls.append(params["page"])
        return {"results": first if params["page"] == 1 else second, "next": params["page"] == 1}
    monkeypatch.setattr(rc, "_json_get", fetch)
    rows, kind = rc._fetch_main_results(None, "Bank", 23)
    assert calls == [1, 2] and len(rows) == 201 and kind == "bank"


def test_repeated_discovery_page_is_an_explicit_failure(monkeypatch):
    monkeypatch.setattr(rc, "_json_get", lambda *a: {"results": [{"id": n, "organization": 23} for n in range(200)], "next": True})
    with pytest.raises(RuntimeError, match="repeated"):
        rc._fetch_main_results(None, "Bank", 23)


def test_next_link_takes_precedence_over_requested_page_size(monkeypatch):
    calls = []
    def fetch(session, url, params):
        calls.append(params["page"])
        return {"results": [{"id": params["page"], "organization": 23}], "next": params["page"] == 1}
    monkeypatch.setattr(rc, "_json_get", fetch)
    assert len(rc._fetch_main_results(None, "Bank", 23)[0]) == 2
    assert calls == [1, 2]


def test_admin_dashboard_and_bell_access(setup, monkeypatch, tmp_path):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setenv("ADMIN_CONTROL_DB", str(tmp_path / "control.db"))
    monkeypatch.setenv("ADMIN_ENVIRONMENT", "test")
    user = type("User", (), {"id": 77, "email": "operator@example.test", "has_pro_access": False})()
    monkeypatch.setenv("ADMIN_ROLES", json.dumps({user.email: "administrator"}))
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: user if token == "session-fixture" else None)
    monkeypatch.setattr(api.web_auth_store, "list_support_requests", lambda **kw: {"items": []})
    monkeypatch.setattr(api.web_auth_store, "notification_states", lambda *a: {})
    maintenance.monitor()
    client = TestClient(api.app)
    assert client.get("/api/admin/control/overview").status_code == 401
    headers = {"Authorization": "Bearer session-fixture"}
    result = client.get("/api/admin/control/overview", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["financial_ingestion"]["incidents"]
    alerts = client.get("/api/notifications", headers=headers)
    assert alerts.status_code == 200, alerts.text
    assert any(i["kind"] == "data_pipeline" for i in alerts.json()["items"])
    monkeypatch.setenv("ADMIN_ROLES", "{}")
    assert client.get("/api/admin/control/overview", headers=headers).status_code == 403
    assert client.get("/api/notifications", headers=headers).json().get("items", []) == []
