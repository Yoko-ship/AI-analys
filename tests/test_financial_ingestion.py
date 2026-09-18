"""Restart, evidence and publication invariants for the durable PDF pipeline."""
from copy import deepcopy
import hashlib
import io
import json

import pytest
from reportlab.pdfgen import canvas

import ifrs_financials
import reports_catalog as rc
from financial_ingestion import documents, extract, publication, store, validation, worker


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setenv("FINANCIAL_ARTIFACT_DIR", str(tmp_path / "originals"))
    monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a: None)
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(20, 20, "Synthetic test document, not a real filing")
    pdf.save()
    content = stream.getvalue()
    entry = deepcopy(ifrs_financials.reviews()[0])
    entry.update(page_count=1, sha256=hashlib.sha256(content).hexdigest())
    for figure in entry["figures"].values():
        figure["page"] = 1
    monkeypatch.setattr(ifrs_financials, "reviews", lambda: [entry])
    monkeypatch.setattr(extract, "review_entries", lambda: ifrs_financials.reviews())
    c = rc.get_catalog_conn()
    with c:
        for ticker, org in (("BRBN", "23"), ("BRBNP", "23"), ("OCBK", "99")):
            c.execute("INSERT INTO catalog_companies (ticker,company_name,org_id) VALUES (?,?,?)", (ticker, "Test bank", org))
        rc._upsert_report(c, "BRBN", report_form="MSFO", period_type="annual", year=2024,
                          quarter=0, title="Test", published_at="2025-01-01", pdf_url=entry["pdf_url"],
                          excel_url=None, excel_url_form1=None, openinfo_report_id="test-1", object_id=None)
    c.close()
    return entry, content


def stage(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    result = worker.run(max_jobs=4, fetch=lambda _: setup[1])
    assert all(r["ok"] for r in result["outcomes"])
    return result


def candidates():
    c = store.connect()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM ingest_candidates").fetchall()]
    finally:
        c.close()


def test_shadow_never_publishes_and_marks_approved_unpublished(setup):
    result = stage(setup)
    assert result["processed"] == 2
    assert result["coverage"]["approved_unpublished"] == 1
    assert result["coverage"]["status"] == "PARTIAL"
    assert rc.get_financials_series("BRBN", "MSFO") == {}
    assert publication.snapshots("BRBN") == []


def test_atomic_publication_reader_units_passport_and_issuer_binding(setup):
    stage(setup)
    rc.upsert_financials_cache("BRBN", "NSBU", 2024, 0, {"revenue": 99})
    result = publication.publish("brbn", actor="test-reviewer")
    assert result["published"] == 1
    assert rc.get_financials_series("BRBNP", "MSFO")["2024"]["total_assets"] == 31_596_795_000
    assert rc.get_financials_series("BRBN", "NSBU")["2024"]["revenue"] == 99
    passport = rc.get_financial_value_passport("BRBNP", "2024", "net_profit", "MSFO")
    assert passport["source"]["normalized_value"] == -1_367_921_000_000
    assert passport["source"]["file_hash"] == setup[0]["sha256"]
    assert documents.issuer_artifact("BRBNP", setup[0]["sha256"]) == setup[1]
    assert documents.issuer_artifact("OCBK", setup[0]["sha256"]) is None
    assert publication.publish("BRBN", actor="test-reviewer") == result
    assert store.status("23")["status"] == "PROCESSED"


def test_discovery_and_processing_are_idempotent(setup):
    stage(setup)
    for _ in range(3):
        documents.discover(ticker="BRBNP", processor=extract.processor_version())
        assert worker.run(max_jobs=4, fetch=lambda _: setup[1])["processed"] == 0
    assert len(candidates()) == 1
    assert store.status("23")["sources"] == 1


def test_expired_worker_cannot_commit_after_reclaim(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    old = store.claim(lease_seconds=-1)
    replacement = store.claim()
    assert replacement["id"] == old["id"]
    assert replacement["lease_token"] != old["lease_token"]
    with pytest.raises(ValueError, match="no longer owns"):
        documents.fetch_job(old, extract.processor_version(), fetch=lambda _: setup[1])
    assert store.status("23")["jobs"] == {"RUNNING": 1}
    documents.fetch_job(replacement, extract.processor_version(), fetch=lambda _: setup[1])
    assert store.status("23")["jobs"]["SUCCEEDED"] == 1


def test_failures_back_off_and_stop_after_three_attempts(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    for attempt in range(1, 4):
        job = store.claim()
        assert job["attempts"] == attempt
        store.fail(job, RuntimeError("upstream unavailable"))
        assert store.claim() is None
        with store.transaction() as c:
            c.execute("UPDATE ingest_jobs SET available_at=0")
    assert store.claim() is None
    assert store.status("23")["jobs"] == {"FAILED": 1}
    assert store.status("23")["status"] == "PARTIAL"


def test_replacement_retains_original_and_does_not_change_publication(setup):
    stage(setup)
    publication.publish("BRBN", actor="reviewer")
    with store.transaction() as c:
        c.execute("UPDATE ingest_sources SET checked_at=1")
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    changed = setup[1] + b"\n% replacement version\n"
    worker.run(max_jobs=4, fetch=lambda _: changed)
    assert store.status("23")["stale_publications"] == 1
    assert documents.read_artifact(setup[0]["sha256"]) == setup[1]
    assert documents.read_artifact(hashlib.sha256(changed).hexdigest()) == changed
    assert publication.passport("BRBN", "2024", "net_profit")["source"]["file_hash"] == setup[0]["sha256"]
    with pytest.raises(ValueError, match="No current"):
        publication.publish("BRBN", actor="reviewer", replace=True)


def test_ledger_revision_requeues_extraction_without_redownload(setup):
    stage(setup)
    setup[0]["period_evidence"] += " Reviewed again."
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    result = worker.run(max_jobs=4, fetch=lambda _: pytest.fail("must reuse archive"))
    assert result["processed"] == 1
    assert len(candidates()) == 2


def test_unreviewed_document_is_visible_not_successfully_complete(setup, monkeypatch):
    monkeypatch.setattr(ifrs_financials, "reviews", lambda: [])
    stage(setup)
    assert store.status("23")["jobs"]["NEEDS_REVIEW"] == 1
    assert store.status("23")["unreviewed_sources"] == 1
    assert store.status("23")["status"] == "PARTIAL"
    with pytest.raises(ValueError, match="Validation failed"):
        publication.approve(candidates()[0]["id"], actor="reviewer", reason="checked")


def test_review_correction_is_immutable_and_requires_separate_approval(setup, monkeypatch):
    monkeypatch.setattr(ifrs_financials, "reviews", lambda: [])
    stage(setup)
    original = candidates()[0]
    payload = validation.from_review(setup[0])
    corrected = publication.propose(original["id"], payload, actor="reviewer", reason="Read exact statement columns")
    assert len(candidates()) == 2
    assert next(r for r in candidates() if r["id"] == original["id"])["payload_json"] == original["payload_json"]
    with pytest.raises(ValueError, match="No current"):
        publication.publish("BRBN", actor="publisher")
    publication.approve(corrected, actor="reviewer", reason="Checked page and units")
    publication.publish("BRBN", actor="publisher", candidate_ids=[corrected])
    assert store.status("23")["unreviewed_sources"] == 0


def test_first_migration_cannot_hide_existing_ifrs_years(setup):
    stage(setup)
    rc.upsert_financials_cache("BRBN", "MSFO", 2023, 0, {"net_income": 42})
    with pytest.raises(ValueError, match="every legacy"):
        publication.publish("BRBN", actor="reviewer")
    assert publication.snapshots("BRBN") == []
    assert rc.get_financials_series("BRBN", "MSFO")["2023"]["net_income"] == 42


def test_transaction_rolls_back_all_heads_if_second_write_fails(setup, monkeypatch):
    stage(setup)
    original = candidates()[0]
    payload = json.loads(original["payload_json"])
    payload["classification"].update(period_start="2023-01-01", period_end="2023-12-31", document_year=2023)
    for f in payload["figures"].values():
        f["column_year"] = 2023
    other = publication.propose(original["id"], payload, actor="reviewer", reason="test second period")
    publication.approve(other, actor="reviewer", reason="test")
    event = store.event
    calls = []
    def fail_second(c, entity_id, action, **kw):
        calls.append(action)
        if len(calls) == 2:
            raise RuntimeError("simulated storage failure")
        event(c, entity_id, action, **kw)
    monkeypatch.setattr(store, "event", fail_second)
    with pytest.raises(RuntimeError, match="simulated"):
        publication.publish("BRBN", actor="publisher")
    assert publication.snapshots("BRBN") == []
    c = store.connect()
    assert c.execute("SELECT COUNT(*) FROM ingest_snapshots").fetchone()[0] == 0
    c.close()


def test_replacement_is_explicit_and_rollback_restores_prior_snapshot(setup):
    stage(setup)
    first = publication.publish("BRBN", actor="publisher")["snapshots"][0]
    original = candidates()[0]
    payload = json.loads(original["payload_json"])
    payload["figures"]["net_income"]["raw_value"] = "-100"
    other = publication.propose(original["id"], payload, actor="reviewer", reason="test revision")
    publication.approve(other, actor="reviewer", reason="test revision")
    with pytest.raises(ValueError, match="Conflicting"):
        publication.publish("BRBN", actor="publisher", replace=True)
    with pytest.raises(ValueError, match="explicit revision"):
        publication.publish("BRBN", actor="publisher", candidate_ids=[other])
    publication.publish("BRBN", actor="publisher", replace=True, candidate_ids=[other])
    assert publication.series("BRBN")["2024"]["net_income"] == -100000
    publication.rollback(first, actor="publisher", reason="Revert test correction")
    assert publication.series("BRBN")["2024"]["net_income"] == -1_367_921_000


@pytest.mark.parametrize("change,code", [
    ({"unit_scale": None}, "UNIT_UNRESOLVED"),
    ({"scope": None}, "SCOPE_UNRESOLVED"),
    ({"period_end": "2023-12-31"}, "DOCUMENT_PERIOD_MISMATCH"),
    ({"period_end": None}, "PERIOD_UNRESOLVED"),
    ({"issuer_evidence": None}, "ISSUER_EVIDENCE_MISSING"),
])
def test_validator_blocks_ambiguous_metadata(setup, change, code):
    payload = validation.from_review(setup[0])
    payload["classification"].update(change)
    assert code in validation.validate(payload, page_count=1)["errors"]


def test_partial_separate_accounts_and_zero_are_valid_not_fabricated(setup):
    payload = validation.from_review(setup[0])
    payload["classification"]["scope"] = "separate"
    payload["figures"] = {"net_income": {"raw_value": "0", "raw_label": "Profit", "page": 1, "column_year": 2024}}
    check = validation.validate(payload, page_count=1)
    assert check["valid"]
    assert check["normalized_uzs"] == {"net_income": "0"}
    assert "PARTIAL_BALANCE" in check["warnings"]


def test_balance_mismatch_and_expense_sign_are_blocked(setup):
    payload = validation.from_review(setup[0])
    payload["figures"]["total_assets"]["raw_value"] = "1"
    payload["figures"]["interest_expense"]["raw_value"] = "1"
    check = validation.validate(payload, page_count=1)
    assert "BALANCE_MISMATCH" in check["errors"]
    assert "EXPENSE_SIGN_INVALID:interest_expense" in check["errors"]


def test_comparative_column_keeps_its_own_year(setup):
    payload = validation.from_review(setup[0])
    payload["classification"].update(role="COMPARATIVE", document_year=2025)
    assert validation.validate(payload, page_count=1)["valid"]
    payload["classification"]["role"] = "PRIMARY"
    assert not validation.validate(payload, page_count=1)["valid"]


def test_archive_api_and_pipeline_status(setup):
    import api
    from fastapi.testclient import TestClient
    stage(setup)
    client = TestClient(api.app)
    path = "/api/company/BRBN/financials/documents/" + setup[0]["sha256"]
    assert client.get(path).status_code == 404
    publication.publish("BRBN", actor="publisher")
    response = client.get(path)
    assert response.status_code == 200 and response.content == setup[1]
    assert client.get(path.replace("BRBN", "OCBK")).status_code == 404
    result = client.get("/api/company/BRBN/financials?form=MSFO").json()
    assert result["ingestion"]["published_periods"] == 1
    assert result["series"]["interest_income"]["values"]["2024"] == 4_473_647_000_000


def test_pdf_publication_date_is_not_a_financial_year():
    for form in ("MSFO", "Audition"):
        assert rc._extract_year({"report_type": form, "pub_date": "2026-01-30", "properties": {"report_type": "annual"}}) is None
    assert rc._extract_year({"report_type": "NSBU", "pub_date": "2026-01-30", "properties": {"report_type": "annual"}}) == 2025


def test_unknown_period_source_upsert_does_not_duplicate_or_merge_pdfs(setup):
    c = rc.get_catalog_conn()
    with c:
        for url in ("https://openinfo.uz/media/a.pdf", "https://openinfo.uz/media/b.pdf"):
            for _ in range(2):
                rc._upsert_report(c, "BRBN", report_form="Audition", period_type="annual", year=None,
                                  quarter=0, title="Unknown date", published_at="2026-01-30", pdf_url=url,
                                  excel_url=None, excel_url_form1=None, openinfo_report_id=url, object_id=None)
    assert c.execute("SELECT COUNT(*) FROM catalog_reports WHERE report_form='Audition'").fetchone()[0] == 2
    c.close()


def test_changed_processor_never_labels_new_extraction_with_old_version(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    worker.run(max_jobs=1, fetch=lambda _: setup[1])
    setup[0]["period_evidence"] += " Updated review."
    worker.run(max_jobs=4, fetch=lambda _: pytest.fail("No fetch needed"))
    assert candidates()[0]["processor"] == extract.processor_version()
    assert store.status("23")["jobs"]["SUPERSEDED"] == 1


def test_corrupt_archive_blocks_publication_and_download(setup, monkeypatch):
    stage(setup)
    monkeypatch.setattr(documents.Path, "read_bytes", lambda _: b"corrupted")
    with pytest.raises(ValueError, match="corrupt"):
        publication.publish("BRBN", actor="publisher")
    assert publication.snapshots("BRBN") == []


def test_all_checked_in_reviews_validate():
    entries = extract.review_entries()
    assert len(entries) == 9
    for entry in entries:
        check = validation.validate(validation.from_review(entry), page_count=entry["page_count"])
        assert check["valid"], (entry["ticker"], entry["year"], check)
    octobank = next(e for e in entries if e["ticker"] == "OCBK")
    assert len(octobank["figures"]) == 5
    assert "interest_income" not in octobank["figures"]


def test_unknown_dates_remain_distinct_in_public_library(setup):
    base = {"report_form": "MSFO", "period_type": "annual", "year": None, "quarter": 0}
    assert rc._report_key({**base, "pdf_url": "a"}) != rc._report_key({**base, "pdf_url": "b"})


def test_vps_pdf_worker_is_persistent_bounded_and_shadow_only():
    import textwrap
    from pathlib import Path
    workflow = Path(".github/workflows/ci.yml").read_text()
    start = workflow.index("          def worker(")
    end = workflow.index("          for name, content in units.items():", start)
    namespace = {}
    exec(compile(textwrap.dedent(workflow[start:end]), "VPS workers", "exec"), namespace)
    service = namespace["units"]["/etc/systemd/system/uzstock-financial-ingestion.service"]
    for required in ("-v uzstock_data:/app/data", "--memory 768m", "--cpus 0.50", "--pids-limit 128",
                     "cycle --max-jobs 4 --ocr", "ExecStopPost=", "TimeoutStartSec=30min"):
        assert required in service
    assert "worker publish" not in service
    assert workflow.count("uzstock-financial-ingestion.timer uzstock-news-collector.timer") == 2
