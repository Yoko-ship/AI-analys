"""Bounded resumable worker. Shadow staging is the default; no implicit publish."""
import argparse
import json
import logging
from pathlib import Path

from . import documents, extract, publication, store

log = logging.getLogger(__name__)


def run(*, max_jobs=4, ocr=False, fetch=None):
    outcomes = []
    processor = extract.processor_version()
    for _ in range(max_jobs):
        job = store.claim(processor=processor)
        if not job:
            break
        try:
            if job["stage"] == "FETCH":
                documents.fetch_job(job, processor, fetch=fetch)
            elif job["stage"] == "EXTRACT":
                if job["processor"] != processor:
                    with store.transaction() as c:
                        store.assert_lease(c, job)
                        store.enqueue(c, job["source_id"], "EXTRACT", processor, version_id=job["version_id"])
                        store.finish(c, job, "SUPERSEDED", "Extraction implementation/review ledger changed")
                else:
                    extract.extract_job(job, ocr=ocr)
            else:
                raise ValueError("Unknown job stage")
            outcomes.append({"job": job["id"], "ok": True})
        except Exception as exc:
            log.warning("financial ingestion %s failed: %s", job["id"], exc)
            try:
                store.fail(job, exc)
            except ValueError:
                log.warning("Job lease lost; replacement worker owns recovery")
            outcomes.append({"job": job["id"], "ok": False, "reason": str(exc)[:1000]})
    with store.transaction() as c:
        store.event(c, "financial-ingestion", "worker.completed", processed=len(outcomes), errors=sum(not o["ok"] for o in outcomes))
    return {"processed": len(outcomes), "outcomes": outcomes, "coverage": store.status()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register-source", "inspect", "backup", "verify-backup", "monitor", "cycle", "discover", "work", "status", "candidates", "propose", "publish", "approve", "retry", "rollback"))
    parser.add_argument("--ticker")
    parser.add_argument("--max-jobs", type=int, default=4)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--actor")
    parser.add_argument("--reason")
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--file", help="PDF for inspect, reviewed JSON for propose, or backup directory")
    parser.add_argument("--url", help="Issuer PDF URL for register-source")
    parser.add_argument("--source-page", help="Verified issuer source page for register-source")
    args = parser.parse_args()
    if args.command == "register-source":
        if not all((args.ticker, args.url, args.source_page, args.actor, args.reason)):
            parser.error("register-source requires --ticker, --url, --source-page, --actor and --reason")
        result = documents.register_issuer_source(ticker=args.ticker, url=args.url, source_page=args.source_page,
                    actor=args.actor, reason=args.reason, processor=extract.processor_version())
    elif args.command == "inspect":
        if not args.file:
            parser.error("inspect requires --file PDF_PATH")
        from . import statements, validation
        pages, evidence = extract.page_texts(Path(args.file).read_bytes(), ocr=args.ocr)
        proposals = statements.proposals(pages, evidence)
        result = {"parser": statements.VERSION, "evidence": evidence,
                  "candidates": [{"payload": p, "checks": validation.validate(p, page_count=evidence["page_count"])}
                                 for p in proposals], "requires_review": True}
    elif args.command in {"backup", "verify-backup", "monitor"}:
        from . import maintenance
        if args.command == "verify-backup" and not args.file:
            parser.error("verify-backup requires --file BACKUP_DIRECTORY")
        result = (maintenance.backup() if args.command == "backup" else maintenance.verify_backup(args.file)
                  if args.command == "verify-backup" else maintenance.monitor())
    elif args.command == "discover":
        result = documents.discover(ticker=args.ticker, processor=extract.processor_version())
    elif args.command in {"work", "cycle"}:
        if not 1 <= args.max_jobs <= 1000:
            parser.error("--max-jobs must be 1..1000")
        if args.command == "cycle":
            discovery = documents.discover(ticker=args.ticker, processor=extract.processor_version())
        result = run(max_jobs=args.max_jobs, ocr=args.ocr)
        if args.command == "cycle":
            result["discovery"] = discovery
    elif args.command == "status":
        org = None
        if args.ticker:
            from reports_catalog import get_company_index
            org = (get_company_index(args.ticker) or {}).get("org_id")
            if not org:
                parser.error("Unknown issuer")
        result = store.status(org)
    elif args.command == "candidates":
        if not args.ticker:
            parser.error("candidates requires --ticker")
        c = store.connect()
        try:
            rows = c.execute("SELECT x.* FROM ingest_candidates x JOIN ingest_versions v ON v.id=x.version_id "
                             "JOIN ingest_sources s ON s.id=v.source_id WHERE s.org_id="
                             "(SELECT org_id FROM catalog_companies WHERE ticker=?) ORDER BY x.created_at,x.id",
                             (args.ticker.upper(),)).fetchall()
            result = [{**dict(r), "payload": json.loads(r["payload_json"]), "checks": json.loads(r["checks_json"])} for r in rows]
        finally:
            c.close()
    elif args.command == "propose":
        if not args.ids or len(args.ids) != 1 or not args.file or not args.actor or not args.reason:
            parser.error("propose requires one --id, --file, --actor and --reason")
        result = {"candidate": publication.propose(args.ids[0], json.loads(Path(args.file).read_text()),
                                                  actor=args.actor, reason=args.reason)}
    elif args.command == "publish":
        if not args.ticker or not args.actor:
            parser.error("publish requires --ticker and --actor")
        result = publication.publish(args.ticker, actor=args.actor, replace=args.replace, candidate_ids=args.ids)
    elif args.command == "approve":
        if not args.ids or not args.actor or not args.reason:
            parser.error("approve requires --id, --actor and --reason")
        result = {"reviews": [publication.approve(i, actor=args.actor, reason=args.reason) for i in args.ids]}
    elif args.command == "rollback":
        if not args.ids or len(args.ids) != 1 or not args.actor or not args.reason:
            parser.error("rollback requires one snapshot --id, --actor and --reason")
        publication.rollback(args.ids[0], actor=args.actor, reason=args.reason)
        result = {"restored": args.ids[0]}
    else:
        if not args.ids or not args.actor or not args.reason:
            parser.error("retry requires --id, --actor and --reason")
        with store.transaction() as c:
            for job_id in args.ids:
                changed = c.execute("UPDATE ingest_jobs SET state='QUEUED',attempts=0,available_at=0,error=NULL,updated_at=? "
                                    "WHERE id=? AND state='FAILED'", (store.now(), job_id))
                if changed.rowcount != 1:
                    raise ValueError("Only failed jobs can be retried explicitly")
                store.event(c, job_id, "job.retry_requested", actor=args.actor, reason=args.reason)
        result = {"retried": args.ids}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if args.command in {"work", "cycle"} and any(not x["ok"] for x in result["outcomes"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
