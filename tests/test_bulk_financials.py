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


def test_old_download_limit_failure_retries_once_after_fetch_policy_upgrade(setup):
    url='https://openinfo.uz/media/int_report/cd722dbe-f284-49c4-a0cc-9c305ca1b61a.pdf'
    registration=dict(org_id='528',ticker='UTYK',url=url,category='MSFO',metadata={},processor='test')
    with store.transaction() as c:
        source=documents.register(c,**registration)
        c.execute("UPDATE ingest_jobs SET state='FAILED',attempts=3,processor='bounded-openinfo-v1',"
                  "error='IFRS PDF exceeds download limit' WHERE source_id=?",(source,))
        documents.register(c,**registration)
        row=c.execute("SELECT * FROM ingest_jobs WHERE source_id=? AND stage='FETCH'",(source,)).fetchone()
        assert row['state']=='QUEUED' and row['attempts']==0
        assert row['processor']==documents.FETCH_VERSION and row['processor']!='bounded-openinfo-v1'
        c.execute("UPDATE ingest_jobs SET state='FAILED',error='IFRS PDF exceeds download limit' WHERE id=?",(row['id'],))
        documents.register(c,**registration)
        assert c.execute('SELECT state FROM ingest_jobs WHERE id=?',(row['id'],)).fetchone()['state']=='FAILED'


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


def test_bulk_receipt_keeps_retained_source_failures_and_confirmed_nsbu_writes(capsys):
    from collection_ops.model import outcome,parse_receipts
    report={'run':{'processing':{'processed':452},'nsbu_history':{'complete':2,'partial':3},
                   'errors':[{'ticker':'INFB','errors':['NSBU annual bank/24: missing fiscal year']}]},
            'issuers':[{'ticker':'UTGA','sources':[{'failures':[{'error':'IFRS PDF exceeds download limit',
                       'url':'https://openinfo.uz/media/audit_conclusion/report.pdf'}]}], 'discovery_errors':[]}],
            'summary':{'failed_jobs':20,'discovery_errors':0}}
    bulk.report_receipts(report)
    receipts=parse_receipts(capsys.readouterr().out.splitlines())
    result=outcome({'invocation':'20261127','result':'exit-code','exit_code':1,'receipts':receipts})
    assert result['status']=='partial' and result['publication']=='acknowledged'
    assert any(r['phase']=='publication' and r['counts'].get('written')==5 for r in receipts)
    assert any(r['ok'] is False and 'INFB' in r['stage'] and 'missing fiscal year' in r['reason'] for r in receipts)
    assert any(r['ok'] is False and 'UTGA' in r['stage'] and 'download limit' in r['reason'] for r in receipts)
    assert not any(r['phase']=='publication' and 452 in r.get('counts',{}).values() for r in receipts)


def test_investor_inventory_in_report_only_mode_is_scoped_and_offline(setup, monkeypatch, tmp_path):
    import pytest
    from financial_ingestion import investor_sweep
    calls = []
    monkeypatch.setattr(investor_sweep, 'coverage', lambda issuers: calls.append([i['ticker'] for i in issuers]) or {'issuers':[]})
    monkeypatch.setattr(investor_sweep, 'collect', lambda *a, **kw: pytest.fail('offline inventory downloaded a source'))
    path = tmp_path / 'report.json'
    assert bulk.main(['--report-only','--investor-metrics','--ticker','BRBN','--report',str(path)]) == 0
    assert calls == [['BRBN']]
    assert json.loads(path.read_text())['investor_metrics']['issuers'] == []

def test_full_scheduled_run_processes_pending_documents_before_catalog_sync(setup, monkeypatch, tmp_path):
    import catalogue.sync as sync

    documents.discover(ticker="BRBN", processor=extract.processor_version())
    worker.run(max_jobs=1, stages=("FETCH",), fetch=lambda _: setup[1])
    assert bulk.queue_state(["23"])["EXTRACT"] == 1
    order = []

    def resume(org_ids, **kwargs):
        assert "23" in org_ids and kwargs["deadline"] <= time.monotonic() + 10
        order.append("queue")
        return {"processed": 1}

    def interrupt_sync(**kwargs):
        order.append("sync")
        raise RuntimeError("Simulated release interruption")

    monkeypatch.setattr(bulk, "drain", resume)
    monkeypatch.setattr(sync, "sync_all", interrupt_sync)
    path = tmp_path / "report.json"
    assert bulk.main(["--nsbu-history", "--max-seconds", "10", "--report", str(path)]) == 1
    assert order == ["queue", "sync"]
