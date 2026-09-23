"""Bulk orchestration must drain, resume, and keep issuer/publication boundaries."""
import json
import time

from financial_ingestion import bulk, documents, extract, publication, store, worker
from tests.test_financial_ingestion import setup


def test_issuer_aliases_and_unknown_tickers(setup):
    import pytest
    selected, unresolved = bulk.issuers(["BRBNP"])
    assert [r["ticker"] for r in selected] == ["BRBN"]
    assert unresolved == []
    with pytest.raises(ValueError, match="Unknown tickers"):
        bulk.issuers(["TYPO"])


def test_worker_filters_stage_and_issuer(setup):
    processor = extract.processor_version()
    documents.discover(ticker="BRBN", processor=processor)
    with store.transaction() as c:
        documents.register(c, org_id="99", ticker="OCBK", url="https://openinfo.uz/media/other.pdf",
                           category="MSFO", metadata={}, processor=processor)
    assert worker.run(max_jobs=4, stages=("EXTRACT",), org_ids=["23"])["processed"] == 0
    result = worker.run(max_jobs=4, stages=("FETCH",), org_ids=["23"], fetch=lambda _: setup[1])
    assert result["processed"] == 1
    assert bulk.queue_state(["99"])["FETCH"] == 1
    assert bulk.queue_state(["23"])["EXTRACT"] == 1
    assert store.claim(org_ids=[]) is None


def test_discovery_drains_more_than_eight_requests(monkeypatch):
    monkeypatch.setattr(documents, "discover", lambda **_: {"annual_attachments": {
        "requests": 8, "pending": 9, "errors": []}})
    batches = iter([{"requests": 8, "pending": 1, "errors": []},
                    {"requests": 1, "pending": 0, "errors": []}])
    monkeypatch.setattr(bulk.disclosures, "discover", lambda **_: next(batches))
    assert bulk.discover_issuer("BRBN", "test")["requests"] == 17


def test_parse_processes_drain_and_resume_without_publishing(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    worker.run(max_jobs=1, stages=("FETCH",), fetch=lambda _: setup[1])
    result = bulk.drain(["23"], workers=2, deadline=time.monotonic() + 30)
    assert result["processed"] == 1
    assert result["queue"]["pending"] == 0
    assert publication.snapshots("BRBN") == []
    assert bulk.drain(["23"], workers=2)["processed"] == 0


def test_retry_backoff_remains_pending_at_time_budget(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    job = store.claim()
    store.fail(job, "temporarily unavailable")
    result = bulk.drain(["23"], deadline=time.monotonic() + .05)
    assert result["processed"] == 0
    assert result["queue"]["pending"] == 1
    assert result["stopped_by_budget"]


def test_terminal_failure_requires_explicit_retry(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    with store.transaction() as c:
        c.execute("UPDATE ingest_jobs SET state='FAILED',attempts=3")
    assert bulk.prepare_jobs(["23"])["failed_jobs_retried"] == 0
    assert bulk.prepare_jobs(["23"], retry_failed=True)["failed_jobs_retried"] == 1
    assert bulk.queue_state(["23"])["FETCH"] == 1


def test_complete_reviewed_native_source_is_not_scheduled_for_ocr(setup):
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    worker.run(max_jobs=4, fetch=lambda _: setup[1])
    assert bulk.prepare_jobs(["23"], ocr=True)["ocr_sources_scheduled"] == 0


def test_native_gap_gets_only_one_resumable_ocr_upgrade(setup, monkeypatch):
    monkeypatch.setattr(extract, "review_entries", lambda: [])
    documents.discover(ticker="BRBN", processor=extract.processor_version())
    worker.run(max_jobs=4, fetch=lambda _: setup[1])
    assert bulk.prepare_jobs(["23"], ocr=True)["ocr_sources_scheduled"] == 1
    assert bulk.prepare_jobs(["23"], ocr=True)["ocr_sources_scheduled"] == 0
    assert bulk.queue_state(["23"])["EXTRACT"] == 1


def test_report_only_returns_failure_for_existing_discovery_errors(setup, tmp_path):
    with store.transaction() as c:
        c.execute("INSERT INTO ingest_disclosures (id,org_id,ticker,api_path,error) VALUES (?,?,?,?,?)",
                  ("broken", "23", "BRBN", "/reports/bank/annual/7/", "upstream error"))
    assert bulk.main(["--report-only", "--report", str(tmp_path / "report.json")]) == 1


def test_ocr_does_not_reuse_unreviewed_native_duplicate(setup, monkeypatch):
    monkeypatch.setattr(extract, "review_entries", lambda: [])
    processor = extract.processor_version()
    documents.discover(ticker="BRBN", processor=processor)
    worker.run(max_jobs=4, fetch=lambda _: setup[1])
    with store.transaction() as c:
        documents.register(c, org_id="23", ticker="BRBN", url="https://openinfo.uz/media/duplicate.pdf",
                           category="MSFO", metadata={}, processor=processor)
    worker.run(max_jobs=1, stages=("FETCH",), fetch=lambda _: setup[1])
    calls = []
    original = extract.page_texts
    def pages(content, *, ocr=False):
        calls.append(ocr)
        return original(content, ocr=False)
    monkeypatch.setattr(extract, "page_texts", pages)
    worker.run(max_jobs=1, stages=("EXTRACT",), ocr=True)
    assert calls == [True]


def test_report_written_after_discovery_failure(setup, monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError("source unavailable")
    monkeypatch.setattr(bulk, "discover_issuer", fail)
    path = tmp_path / "report.json"
    assert bulk.main(["--skip-sync", "--ticker", "BRBN", "--report", str(path)]) == 1
    report = json.loads(path.read_text())
    assert report["run"]["errors"][0]["reason"] == "source unavailable"
    assert report["publication_performed"] is False
