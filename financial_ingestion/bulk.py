"""Discover and parse all catalog issuers with a durable, resumable work queue.

Run: python -m financial_ingestion.bulk --workers 2 --ocr
Publication remains a separate, attributed review operation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
import json
import logging
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import time

from . import disclosures, documents, extract, source_policy, store, worker

log = logging.getLogger(__name__)


def write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".bulk-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def issuers(tickers=None):
    import reports_catalog as rc
    import catalogue.filings as catalogue_filings
    import catalogue.sync as catalogue_sync
    c = store.connect()
    try:
        rows = [dict(r) for r in c.execute("SELECT ticker,company_name,org_id FROM catalog_companies ORDER BY ticker")]
    finally:
        c.close()
    requested = set(tickers or [])
    unknown = requested - {r["ticker"] for r in rows}
    if unknown:
        raise ValueError("Unknown tickers: " + ", ".join(sorted(unknown)))
    selected_orgs = {r["org_id"] for r in rows if r["ticker"] in requested and r["org_id"]}
    groups = {}
    unresolved = []
    for row in rows:
        if requested and row["ticker"] not in requested and row["org_id"] not in selected_orgs:
            continue
        if not row["org_id"]:
            unresolved.append(row["ticker"])
            continue
        groups.setdefault(str(row["org_id"]), []).append(row)
    selected = []
    for group in groups.values():
        ticker = catalogue_filings._canonical_ticker(r["ticker"] for r in group)
        selected.append(next(r for r in group if r["ticker"] == ticker))
    return selected, unresolved


def discover_issuer(ticker, processor, deadline=None):
    result = documents.discover(ticker=ticker, processor=processor)
    attachment = result["annual_attachments"]
    errors = list(attachment["errors"])
    requests = attachment["requests"]
    # The timer's eight-request batch is an iteration size, not a bulk limit.
    while attachment["pending"] and (deadline is None or time.monotonic() < deadline):
        attachment = disclosures.discover(ticker=ticker, processor=processor)
        requests += attachment["requests"]
        errors.extend(attachment["errors"])
        if not attachment["requests"]:
            break
    return {"ticker": ticker, "requests": requests, "pending": attachment["pending"], "errors": errors}


def prepare_jobs(org_ids, *, ocr=False, retry_failed=False):
    """Revisit all registered URLs, including PDFs hidden by catalog collisions."""
    processor = extract.processor_version()
    selected = set(str(org) for org in org_ids)
    retried = upgrades = 0
    with store.transaction() as c:
        for source in c.execute("SELECT * FROM ingest_sources").fetchall():
            if source["org_id"] not in selected or not source_policy.allows(source["url"]):
                continue
            documents.register(c, org_id=source["org_id"], ticker=source["ticker"], url=source["url"],
                               category=source["category"], metadata=json.loads(source["metadata_json"]),
                               processor=processor)
            if ocr and source["latest_version"]:
                candidates = c.execute("SELECT payload_json,checks_json FROM ingest_candidates "
                                       "WHERE version_id=? AND processor=?",
                                       (source["latest_version"], processor)).fetchall()
                # One resumable OCR pass per parser/version for native-only gaps.
                def needs_ocr(candidate):
                    from .bulk_report import BANK_FIELDS, COMPANY_FIELDS
                    fields = json.loads(candidate["payload_json"]).get("figures", {})
                    expected = BANK_FIELDS if {"interest_income", "interest_expense"} & fields.keys() else COMPANY_FIELDS
                    missing = any(not isinstance(fields.get(field), dict) or fields[field].get("raw_value") is None
                                  for field in expected)
                    return not json.loads(candidate["checks_json"]).get("valid") or missing

                if candidates and any(needs_ocr(r) for r in candidates):
                    attempted = any("ocr_survey_pages" in json.loads(r["payload_json"]).get("extraction", {})
                                    for r in candidates)
                    if not attempted:
                        key = store.digest([source["id"], "EXTRACT", processor, source["latest_version"], "bulk-ocr-v1"])
                        exists = c.execute("SELECT 1 FROM ingest_jobs WHERE id=?", (key,)).fetchone()
                        store.enqueue(c, source["id"], "EXTRACT", processor,
                                      version_id=source["latest_version"], generation="bulk-ocr-v1")
                        upgrades += not bool(exists)
            if retry_failed:
                jobs = c.execute("SELECT id FROM ingest_jobs WHERE source_id=? AND state='FAILED'",
                                 (source["id"],)).fetchall()
                for job in jobs:
                    c.execute("UPDATE ingest_jobs SET state='QUEUED',attempts=0,available_at=0,error=NULL,updated_at=? WHERE id=?",
                              (store.now(), job["id"]))
                    store.event(c, job["id"], "job.retry_requested", actor="bulk-cli", reason="--retry-failed")
                    retried += 1
    return {"failed_jobs_retried": retried, "ocr_sources_scheduled": upgrades}


def queue_state(org_ids):
    selected = set(str(org) for org in org_ids)
    c = store.connect()
    try:
        rows = c.execute("SELECT j.state,j.stage,j.available_at,j.lease_until,s.org_id,s.url FROM ingest_jobs j "
                         "JOIN ingest_sources s ON s.id=j.source_id WHERE j.state IN ('QUEUED','RETRY','RUNNING','FAILED')").fetchall()
    finally:
        c.close()
    result = {"FETCH": 0, "EXTRACT": 0, "pending": 0, "failed": 0, "next_at": None}
    clock = time.time()
    for row in rows:
        if row["org_id"] not in selected or not source_policy.allows(row["url"]):
            continue
        if row["state"] == "FAILED":
            result["failed"] += 1
            continue
        result["pending"] += 1
        due = (row["lease_until"] or clock) if row["state"] == "RUNNING" else row["available_at"]
        if due <= clock:
            result[row["stage"]] += 1
        result["next_at"] = min(result["next_at"] or due, due)
    return result


def _process_one(stage, org_ids, ocr):
    return worker.run(max_jobs=1, stages=(stage,), org_ids=org_ids, ocr=ocr, include_coverage=False)


def drain(org_ids, *, workers=2, ocr=False, deadline=None, progress=None):
    """Threads share the HTTP pacing gate; isolated processes own PDFium/OCR."""
    outcomes = {"processed": 0, "failed_attempts": 0, "stopped_by_budget": False}
    if not org_ids:
        return {**outcomes, "queue": queue_state(org_ids)}
    # Native PDFium is not thread safe. Spawn also avoids inheriting DB pools.
    with ThreadPoolExecutor(max_workers=workers) as fetch_pool, ProcessPoolExecutor(
        max_workers=workers, mp_context=multiprocessing.get_context("spawn")
    ) as parse_pool:
        pending = {}
        last_log = 0.0
        while True:
            expired = deadline is not None and time.monotonic() >= deadline
            state = queue_state(org_ids)
            if not expired:
                for stage, pool in (("FETCH", fetch_pool), ("EXTRACT", parse_pool)):
                    running = sum(s == stage for s in pending.values())
                    for _ in range(min(workers - running, state[stage])):
                        pending[pool.submit(_process_one, stage, org_ids, ocr)] = stage
            if time.monotonic() - last_log >= 15:
                log.info("Parsed/fetched %d jobs; pending=%d failed=%d", outcomes["processed"], state["pending"], state["failed"])
                if progress:
                    progress({**outcomes, "queue": state})
                last_log = time.monotonic()
            if not pending:
                if expired or not state["pending"]:
                    outcomes["stopped_by_budget"] = bool(expired and state["pending"])
                    break
                delay = min(5, max(.1, (state["next_at"] or time.time()) - time.time()))
                if deadline is not None:
                    delay = min(delay, max(0, deadline - time.monotonic()))
                time.sleep(delay)
                continue
            done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                pending.pop(future)
                result = future.result()
                outcomes["processed"] += result["processed"]
                outcomes["failed_attempts"] += sum(not o["ok"] for o in result["outcomes"])
    return {**outcomes, "queue": queue_state(org_ids)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", action="append", help="Optional issuer subset; repeat for multiple tickers")
    parser.add_argument("--workers", type=int, default=2, help="Concurrent downloads and PDF processes (1..8)")
    parser.add_argument("--ocr", action="store_true", help="Read scanned statements; revisit native-only gaps once")
    parser.add_argument("--nsbu-history", action="store_true", help="Also collect and reparse NSBU annual/quarter history")
    parser.add_argument("--skip-sync", action="store_true", help="Use existing issuer/report catalog")
    parser.add_argument("--force-sync", action="store_true", help="Refresh listings even within catalog TTL")
    parser.add_argument("--retry-failed", action="store_true", help="Explicitly retry terminal failed jobs")
    parser.add_argument("--max-seconds", type=int, default=0, help="Stop scheduling after this budget; 0 drains all work")
    parser.add_argument("--report", default="data/bulk-financial-report.json")
    parser.add_argument("--report-only", action="store_true", help="Inventory current coverage without network or parsing")
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 8 or args.max_seconds < 0:
        parser.error("--workers must be 1..8 and --max-seconds must be nonnegative")
    if args.ocr and not args.report_only and not shutil.which("tesseract"):
        parser.error("--ocr requires tesseract; install it or omit --ocr for native PDF text")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from .bulk_report import build_report
    import reports_catalog as rc
    import catalogue.filings as catalogue_filings
    import catalogue.sync as catalogue_sync
    tickers = sorted({t.upper().strip() for t in args.ticker}) if args.ticker else None
    started = time.monotonic()
    deadline = started + args.max_seconds if args.max_seconds else None
    run = {"started_at": store.now(), "processor": extract.processor_version(), "discovery": [], "errors": []}
    try:
        if not args.report_only and not args.skip_sync:
            log.info("Refreshing issuer and report listings")
            run["catalog_sync"] = catalogue_sync.sync_all(tickers=tickers, force=args.force_sync)
            run["errors"].extend(run["catalog_sync"].get("errors", []))
        targets, unresolved = issuers(tickers)
        if not targets and not args.report_only:
            run["errors"].append({"reason": "No resolved catalog issuers; run without --skip-sync to discover issuers"})
        run["unresolved_tickers"] = unresolved
        run["issuer_count"] = len(targets)
        org_ids = [str(r["org_id"]) for r in targets]
        if not args.report_only:
            if args.nsbu_history:
                from . import nsbu_history
                log.info("Collecting NSBU annual and quarterly history")
                write_report(args.report, {"run": run, "state": "NSBU_HISTORY"})
                run["nsbu_history"] = nsbu_history.run(tickers=tickers)
                run["errors"].extend(run["nsbu_history"].get("errors", []))
            processor = extract.processor_version()
            for index, target in enumerate(targets):
                if deadline is not None and time.monotonic() >= deadline:
                    run["discovery_incomplete"] = True
                    break
                ticker = target["ticker"]
                log.info("Discovering %s (%d/%d)", ticker, index + 1, len(targets))
                try:
                    result = discover_issuer(ticker, processor, deadline)
                    run["discovery"].append(result)
                    run["errors"].extend(result["errors"])
                    if result["pending"]:
                        run["discovery_incomplete"] = True
                except Exception as exc:
                    log.exception("Discovery failed for %s", ticker)
                    run["errors"].append({"ticker": ticker, "reason": str(exc)})
                write_report(args.report, {"run": run, "state": "DISCOVERING"})
            run["preparation"] = prepare_jobs(org_ids, ocr=args.ocr, retry_failed=args.retry_failed)
            run["processing"] = drain(org_ids, workers=args.workers, ocr=args.ocr, deadline=deadline,
                                      progress=lambda state: write_report(args.report, {"run": run, "processing": state}))
    except KeyboardInterrupt:
        run["interrupted"] = True
    except Exception as exc:
        log.exception("Bulk collection failed")
        run["errors"].append({"reason": str(exc)})
    report = build_report(tickers=tickers)
    report["run"] = {**run, "finished_at": store.now(), "elapsed_seconds": round(time.monotonic() - started, 1)}
    write_report(args.report, report)
    log.info("Coverage and missing-data report: %s", args.report)
    # A drained queue means parsed, not reviewed, published, or complete history.
    if run.get("interrupted"):
        return 130
    if (run["errors"] or run.get("unresolved_tickers") or report.get("unknown_tickers")
            or report["summary"].get("discovery_errors") or report["summary"].get("failed_jobs")):
        return 1
    if run.get("discovery_incomplete") or run.get("processing", {}).get("stopped_by_budget"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
