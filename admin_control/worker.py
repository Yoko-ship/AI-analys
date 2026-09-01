"""Durable jobs with leases and checkpoints. Run: python -m admin_control.worker.

--once processes a bounded batch; --sync first indexes existing domain records.
Jobs are the transactional outbox and PostgreSQL remains their source of truth.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import random
import time

from . import store as s
from . import adapters, documents, rules
from .service import SYSTEM, TERMINAL, incident

log = logging.getLogger(__name__)


def _stage_document(entity_id, stage, **changes):
    """Persist one observable document transition and its bounded journal."""
    with s.connection(write=True) as c:
        current = s.get(c, "documents", entity_id)
        stamp = s.now()
        journal = [*current.get("pipeline_journal", []), {"stage": stage, "at": stamp}]
        return s.put(c, "documents", {
            **current, **changes, "pipeline_stage": stage,
            "pipeline_stage_at": stamp, "pipeline_journal": journal[-100:],
        })


def process_document(entity_id):
    old = _stage_document(entity_id, "DOWNLOADING")
    if not old.get("source_url"):
        _stage_document(entity_id, "SOURCE_UNAVAILABLE")
        raise s.ControlError("SOURCE_URL_MISSING", "No official source URL is available.", 422)
    try:
        data = documents.fetch_original(old["source_url"])
    except Exception:
        _stage_document(entity_id, "SOURCE_UNAVAILABLE")
        raise
    checksum = documents.save_original(data)
    doc = _stage_document(entity_id, "PARSING", checksum=checksum,
                          detected_format=documents.detect_format(data))
    try:
        first = documents.preview(doc)
        header = first.get("text") or "\n".join(
            " ".join(str(cell["value"] or "") for cell in row)
            for row in first.get("rows", []))
        doc = rules.apply_parser(doc, header[:20000])
    except Exception:
        _stage_document(entity_id, "PARSER_ERROR")
        raise
    doc = _stage_document(entity_id, "VALIDATING", **doc)
    doc.update(parsed=True, metadata_verified=not doc["blockers"], verified=False,
               status="QUALITY_BLOCKED" if doc["blockers"] else "CLASSIFIED",
               pipeline_stage="NEEDS_REVIEW" if doc["blockers"] else "READY_IN_LIBRARY",
               pipeline_stage_at=s.now())
    with s.connection(write=True) as c:
        # One checksum can be disclosed at multiple URLs; preserve source aliases.
        duplicate = next((d for d in s.all_items(c, "documents") if d.get("checksum") == checksum and d["id"] != entity_id and d.get("status") != "DUPLICATE"), None)
        if duplicate and duplicate.get("ticker") != doc.get("ticker"):
            doc.update(status="QUALITY_BLOCKED", metadata_verified=False, verified=False,
                       pipeline_stage="NEEDS_REVIEW", pipeline_stage_at=s.now(),
                       blockers=sorted(set(doc["blockers"] + ["SOURCE_IDENTITY_CONFLICT"])))
            duplicate = None
        if duplicate:
            stamp = s.now()
            alias = s.put(c, "documents", {
                **doc, "status": "DUPLICATE", "pipeline_stage": "DUPLICATE",
                "pipeline_stage_at": stamp,
                "pipeline_journal": [*doc.get("pipeline_journal", []),
                                     {"stage": "DUPLICATE", "at": stamp}][-100:],
                "canonical_document_id": duplicate["id"], "checksum": checksum,
            })
            aliases = sorted(set(duplicate.get("source_aliases", []) + [doc["source_url"], duplicate["source_url"]]))
            s.put(c, "documents", {**duplicate, "source_aliases": aliases})
            adapters.coverage(c, alias)
            return {"verified": bool(duplicate.get("metadata_verified")), "verification_scope": "classification", "canonical_document_id": duplicate["id"], "duplicate": True}
        stamp = doc["pipeline_stage_at"]
        doc["pipeline_journal"] = [*doc.get("pipeline_journal", []),
                                   {"stage": doc["pipeline_stage"], "at": stamp}][-100:]
        doc = s.put(c, "documents", doc)
        run_id = s.uid("parser")
        parser = {"id": run_id, "document_id": entity_id, "ticker": doc["ticker"], "status": doc["status"],
                 "standard": doc["standard"], "period": doc["period"], "source": doc["source"],
                 "parser_version": doc.get("parser_rule_version", "control-classifier-1"), "checksum": checksum,
                 "detected_mime": doc.get("detected_mime"), "classification": {k: doc.get(k) for k in ("period_start", "period_end", "duration_months", "statement_type", "classification_evidence")},
                 "blockers": doc["blockers"], "warnings": doc["warnings"], "rows_found": len(first.get("rows", [])),
                 "rows_mapped": None, "mapping_status": "domain_pipeline_pending", "created_at": s.now()}
        s.put(c, "parsers", parser)
        adapters.coverage(c, doc)
        for code in doc["blockers"]:
            incident(c, code, entity_id, stage="classification", evidence={"ticker": doc["ticker"], "document_id": entity_id, "run_id": run_id})
        s.audit(c, SYSTEM, "document.processed", entity_id, "Worker classification completed", run_id, old=old, new=doc)
    # A verified header is not proof that the financial series was mapped.
    # The existing domain worker owns mapping and publication and receives the event.
    if not doc["blockers"]:
        import analysis_monitor
        analysis_monitor.enqueue(doc["ticker"], "document:" + checksum)
        doc = _stage_document(entity_id, "RECALCULATING")
    return {"verified": not doc["blockers"], "verification_scope": "classification", "document_id": entity_id, "parser_run_id": run_id, "blockers": doc["blockers"]}


def recalculate(ticker, *, override=None, persist=True):
    from issuer_analysis_api import _resolve_issuer
    from sector_report_service import sector_report
    issuer = _resolve_issuer(ticker)
    outputs = [sector_report(issuer, "nsbu", None, "separate", lang, persist=persist, rule_override=override) for lang in ("ru", "uz", "en")]
    return {"verified": all(r["status"] == "available" for r in outputs), "verification_scope": "financial", "reports": outputs,
            "versions": [r["version"] for r in outputs], "statuses": [r["status"] for r in outputs]}


def process_target(job, target):
    kind = job["category"]
    if kind == "catalog-sync":
        result = adapters.refresh_catalog()
        result["analyses"] = adapters.refresh_analyses()
        return result
    if kind == "document-reprocess":
        return process_document(target)
    if kind in {"rule-test", "rule-impact-analysis", "rule-shadow-run"}:
        with s.connection() as c:
            rule = s.get(c, "rules", target)
        tests = rules.test_rule(rule)
        with s.connection(write=True) as c:
            current = s.get(c, "rules", target)
            if current["version"] != job["payload"]["rule_version"] or current["status"] not in {"DRAFT", "TESTED"}:
                raise s.ControlError("VERSION_CONFLICT", "The draft changed while tests were running.")
            current.update(tests=tests, impact=rules.impact(c, rule), status="TESTED" if tests["passed"] else "DRAFT")
            s.put(c, "rules", current)
            s.audit(c, SYSTEM, "rule.tested", target, job["reason"], job["request_id"], old=rule, new=current)
        return {"verified": tests["passed"], "tests": tests, "impact": current["impact"]}
    if kind == "recalculate":
        out = recalculate(target)
        return {k: v for k, v in out.items() if k != "reports"}
    if kind == "rule-rollout":
        with s.connection() as c:
            rule = s.get(c, "rules", job["entity_id"])
        if rule["status"] != "ROLLING_OUT":
            raise s.ControlError("ROLLOUT_STOPPED", "This rule is no longer awaiting rollout.")
        if rule["category"] == "parser":
            return rules.parser_shadow(rule, target)
        current = recalculate(target, persist=False)
        draft = recalculate(target, persist=False, override=rule)
        regression = current["verified"] and not draft["verified"]
        if regression:
            raise s.ControlError("SHADOW_REGRESSION", "The draft introduces blockers; activation was stopped.")
        return {"verified": True, "ticker": target, "current": current["versions"], "draft": draft["versions"],
                "before": current["statuses"], "after": draft["statuses"]}
    if kind == "publication-rollback":
        import analysis_monitor
        with s.connection() as c:
            publication = s.get(c, "publications", target)
        if publication["version"] != job["payload"]["publication_version"]:
            raise s.ControlError("VERSION_CONFLICT", "Publication changed before rollback.")
        if not analysis_monitor.rollback(publication["domain_version"], job["requested_by"], job["reason"]):
            raise s.ControlError("ROLLBACK_REJECTED", "The domain rejected this publication rollback.")
        with s.connection(write=True) as c:
            for previous in s.all_items(c, "publications", {"ticker": publication["ticker"], "standard": publication["standard"], "status": "PUBLISHED"}):
                if previous.get("language") == publication.get("language") and previous["id"] != target:
                    s.put(c, "publications", {**previous, "status": "ROLLED_BACK"})
            s.put(c, "publications", {**publication, "status": "PUBLISHED", "rollback_request": None, "restored_at": s.now()})
            s.audit(c, SYSTEM, "publication.restored", target, job["reason"], job["request_id"], new={"version": publication["domain_version"]})
        return {"verified": True, "publication_id": target}
    raise s.ControlError("UNKNOWN_JOB", "No worker handles this job category.", 422)


def claim():
    with s.connection(write=True) as c:
        jobs = list(s.all_items(c, "jobs", {"status": "QUEUED,RETRYING,RUNNING", "direction": "asc"}))
        for job in jobs:
            if job["status"] == "RUNNING" and job.get("lease_until", "") > s.now():
                continue
            if job.get("next_attempt", "") > s.now():
                continue
            if job.get("cancel_requested"):
                s.put(c, "jobs", {**job, "status": "CANCELLED"})
                continue
            return s.put(c, "jobs", {**job, "status": "RUNNING", "lease_token": s.uid("lease"),
                   "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(), "started_at": job.get("started_at") or s.now()})
    return None


def run_one():
    job = claim()
    if not job:
        return False
    try:
        results = list(job.get("results", []))
        for index in range(job["checkpoint"], len(job["targets"])):
            with s.connection() as c:
                current = s.get(c, "jobs", job["id"])
            if current.get("lease_token") != job["lease_token"]:
                return True
            if current.get("cancel_requested"):
                break
            result = process_target(job, job["targets"][index])
            results.append(result)
            with s.connection(write=True) as c:
                current = s.get(c, "jobs", job["id"])
                if current.get("lease_token") != job["lease_token"]:
                    return True
                s.put(c, "jobs", {**current, "checkpoint": index + 1, "processed": index + 1, "results": results,
                      "lease_until": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()})
        with s.connection(write=True) as c:
            current = s.get(c, "jobs", job["id"])
            if current.get("lease_token") != job["lease_token"]:
                return True
            cancelled = current.get("cancel_requested")
            verified = bool(results) and all(r.get("verified") for r in results)
            if job["category"] == "rule-rollout":
                rule = s.get(c, "rules", job["entity_id"])
                if cancelled:
                    s.put(c, "rules", {**rule, "status": "APPROVED"})
                else:
                    # No production rule changes before the complete shadow set passes.
                    if rules.impact_fingerprint(c, rule) != rule["impact"]["fingerprint"]:
                        raise s.ControlError("IMPACT_CHANGED", "The impact set changed during shadow testing.")
                    previous_rules = []
                    for old in s.all_items(c, "rules", {"category": rule["category"], "status": "ACTIVE"}):
                        if old["config"]["code"] == rule["config"]["code"]:
                            previous_rules.append(old["id"])
                            s.put(c, "rules", {**old, "status": "SUPERSEDED"})
                    s.put(c, "rules", {**rule, "status": "ACTIVE", "activated_at": s.now(), "previous_rule_ids": previous_rules})
                    from .service import enqueue
                    if rule["category"] == "parser":
                        document_ids = [document["id"] for document in s.all_items(c, "documents") if document.get("status") != "DUPLICATE"]
                        enqueue(c, "document-reprocess", rule["id"], SYSTEM, "Approved parser rollout", job["request_id"], targets=document_ids)
                    else:
                        enqueue(c, "recalculate", rule["id"], SYSTEM, "Approved shadow rollout", job["request_id"], targets=job["targets"],
                                payload={"activation_rule_id": rule["id"], "previous_rule_ids": previous_rules})
            activation_id = job.get("payload", {}).get("activation_rule_id")
            if activation_id and not cancelled and not verified:
                rule = s.get(c, "rules", activation_id)
                if rule["status"] == "ACTIVE":
                    s.put(c, "rules", {**rule, "status": "ROLLED_BACK", "rollout_error": "PRODUCTION_VERIFICATION_FAILED"})
                    for previous_id in job["payload"].get("previous_rule_ids", []):
                        previous = s.get(c, "rules", previous_id)
                        s.put(c, "rules", {**previous, "status": "ACTIVE"})
                    from .service import enqueue
                    enqueue(c, "recalculate", activation_id, SYSTEM, "Restore prior rules after failed production verification", job["request_id"], targets=job["targets"])
                    incident(c, "PRODUCTION_VERIFICATION_FAILED", activation_id, stage="rollout", evidence={"job_id": job["id"], "restored_rule_ids": job["payload"].get("previous_rule_ids", [])})
                    s.audit(c, SYSTEM, "rule.automatically_reverted", activation_id, "Production verification did not pass", job["request_id"], old=rule, new={"status": "ROLLED_BACK"})
            status = "CANCELLED" if cancelled else "COMPLETED" if verified or job["category"] == "catalog-sync" else "BLOCKED"
            scopes = {r.get("verification_scope") for r in results}
            scope = next(iter(scopes)) if len(scopes) == 1 else None
            s.put(c, "jobs", {**current, "status": status, "finished_at": s.now(), "result": {"verified": verified, "verification_scope": scope, "items": results}})
            s.audit(c, SYSTEM, "job.finished", job["id"], job["reason"], job["request_id"], new={"status": status})
    except Exception as exc:
        log.exception("Admin job %s failed", job["id"])
        retryable = not isinstance(exc, s.ControlError) or exc.status >= 500
        code = exc.code if isinstance(exc, s.ControlError) else "WORKER_OPERATION_FAILED"
        with s.connection(write=True) as c:
            current = s.get(c, "jobs", job["id"])
            if current.get("lease_token") != job["lease_token"]:
                return True
            retrying = retryable and current["attempt"] < 4
            s.put(c, "jobs", {**current, "status": "RETRYING" if retrying else "FAILED", "attempt": current["attempt"] + int(retrying),
                  "errors": [*current.get("errors", []), {"code": code, "at": s.now()}],
                  "next_attempt": (datetime.now(timezone.utc) + timedelta(seconds=30 * 2 ** current["attempt"] + random.randint(0, 15))).isoformat()})
            if not retrying:
                incident(c, code, job["entity_id"], stage="worker", evidence={"job_id": job["id"]})
                if job["category"] == "rule-rollout":
                    rule = s.get(c, "rules", job["entity_id"])
                    s.put(c, "rules", {**rule, "status": "TESTED", "rollout_error": code, "approved_by": None})
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.sync:
        print(json.dumps(adapters.refresh_catalog()))
        adapters.refresh_analyses()
    while True:
        progressed = run_one()
        if args.once:
            break
        if not progressed:
            time.sleep(2)


if __name__ == "__main__":
    main()
