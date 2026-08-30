"""Administrative commands. Permission, concurrency and evidence gates live here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os

from . import store as s

CAPABILITIES = {
    "viewer": {"read", "export"},
    "analyst": {"read", "export", "retry", "comment"},
    "rule_editor": {"read", "export", "retry", "comment", "draft", "test", "approve", "activate", "rollback"},
    "administrator": {"read", "export", "retry", "comment", "draft", "test", "approve", "activate", "rollback", "access"},
}
SYSTEM = {"email": "pipeline", "role": "system"}
TERMINAL = {"COMPLETED", "CANCELLED", "FAILED", "BLOCKED"}


def role_for(email):
    from web_auth import is_admin_email
    email = str(email or "").strip().lower()
    if not email:
        return None
    try:
        configured = json.loads(os.getenv("ADMIN_ROLES", "{}"))
    except ValueError:
        return None
    if not isinstance(configured, dict):
        return None
    # An explicit lower role wins over the legacy administrator allowlist.
    role = configured.get(email)
    with s.connection() as c:
        assignment = s.get(c, "access", email, False)
    if assignment:
        role = assignment["role"] if assignment.get("status") == "ACTIVE" else "disabled"
    if role is not None or email in configured:
        return role if isinstance(role, str) and role in CAPABILITIES else None
    return "administrator" if is_admin_email(email) else None


def require(actor, capability):
    if capability not in CAPABILITIES.get(actor.get("role"), set()):
        raise s.ControlError("PERMISSION_DENIED", f"Your role does not allow {capability}.", 403)


def enqueue(c, kind, entity_id, actor, reason, request_id, *, targets=None, parent=None, payload=None):
    targets = [entity_id] if targets is None else targets
    job = s.put(c, "jobs", {"id": s.uid("job"), "category": kind, "entity_id": entity_id,
                "ticker": (payload or {}).get("ticker", ""), "status": "QUEUED", "attempt": 1,
                "parent_job_id": parent, "checkpoint": 0, "processed": 0, "total": len(targets),
                "targets": targets, "errors": [], "result": None, "cancel_requested": False,
                "requested_by": actor["email"], "reason": reason, "request_id": request_id,
                "payload": payload or {}, "created_at": s.now(), "next_attempt": s.now()})
    s.audit(c, actor, kind, job["id"], reason, request_id, new=job)
    return {"ok": True, "job_id": job["id"], "status": job["status"], "item": job}


def incident(c, code, entity, *, stage, evidence=None, severity="P1"):
    root = f"{stage}:{code}"
    key = "incident_" + s.digest(root)[:24]
    old = s.get(c, "incidents", key, False)
    entities = sorted(set((old or {}).get("affected_ids", []) + [str(entity)]))
    # Polling unchanged evidence does not inflate the number of occurrences.
    evidence = evidence or {}
    fingerprint = s.digest([entity, evidence])
    if old and old.get("last_evidence_hash") == fingerprint:
        return old
    due = (datetime.now(timezone.utc) + timedelta(minutes={"P0": 15, "P1": 60, "P2": 1440, "P3": 4320}[severity])).isoformat()
    return s.put(c, "incidents", {**(old or {}), "id": key, "title": code, "blocker_code": code,
            "root_cause_key": root, "stage": stage, "severity": severity, "status": "OPEN" if not old or old["status"] == "RESOLVED" else old["status"],
            "first_seen_at": (old or {}).get("first_seen_at", s.now()), "last_seen_at": s.now(),
            "sla_due_at": (old or {}).get("sla_due_at", due), "affected_ids": entities, "impact_count": len(entities),
            "occurrences": (old or {}).get("occurrences", 0) + 1, "evidence": evidence,
            "last_evidence_hash": fingerprint, "ticker": evidence.get("ticker", ""),
            "comments": (old or {}).get("comments", []), "resolution_rule_id": (old or {}).get("resolution_rule_id")})


def overview(c):
    counts = {}
    for row in c.execute("SELECT collection,status,COUNT(*) AS n FROM control_resources WHERE environment=? AND status<>'DUPLICATE' GROUP BY collection,status", (s.environment(),)):
        counts.setdefault(row["collection"], {})[row["status"]] = row["n"]
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent = [p for p in s.all_items(c, "analyses") if p.get("created_at", "") >= since]
    eligible = [r for r in recent if r.get("eligible_run")]
    clean = sum(1 for r in recent if not r.get("blockers") and not r.get("warnings"))
    coverage = counts.get("coverage", {})
    active = [i for i in s.all_items(c, "incidents") if i["status"] != "RESOLVED"]
    return {"environment": s.environment(), "updated_at": s.now(), "counts": counts,
            "kpis": {"auto_publication": sum(r.get("status") == "PUBLISHED" for r in eligible) / len(eligible) if eligible else None,
                     "active_blockers": sum(i["severity"] in {"P0", "P1"} for i in active),
                     "coverage_complete": coverage.get("COMPLETE", 0), "coverage_total": sum(coverage.values()),
                     "quality_rate": clean / len(recent) if recent else None,
                     "queued": sum(v for k, v in counts.get("jobs", {}).items() if k in {"QUEUED", "RUNNING", "RETRYING"})},
            "attention": sorted(active, key=lambda x: (x["severity"], x["sla_due_at"]))[:8],
            "publications": s.query(c, "publications", {"status": "PUBLISHED"}, limit=5)["items"],
            "jobs": s.query(c, "jobs", limit=5)["items"]}


def execute(c, actor, collection, entity_id, action, data, request_id):
    reason = str(data.get("reason") or "").strip()
    if len(reason) < 3:
        raise s.ControlError("REASON_REQUIRED", "Explain the reason for this action.", 422)
    permissions = {"reprocess": "retry", "recalculate": "retry", "sync": "retry", "retry": "retry", "cancel": "retry",
                   "comment": "comment", "investigate": "comment", "resolve": "comment", "draft": "draft",
                   "test": "test", "impact-analysis": "test", "shadow-run": "test", "approve": "approve", "activate": "activate",
                   "rollback": "rollback", "grant": "access"}
    if action not in permissions:
        raise s.ControlError("UNSUPPORTED_ACTION", "This action is not supported.", 422)
    require(actor, permissions[action])
    if action == "sync" and collection == "catalog":
        return enqueue(c, "catalog-sync", "catalog", actor, reason, request_id)
    if action == "recalculate" and collection == "calculations":
        # Capture the exact full filtered set, never the browser's current page.
        filters = {k: v for k, v in (data.get("filters") or {}).items() if k in s.FILTERS | {"q"}}
        # Calculation-specific status/period filters must resolve calculations,
        # not be mistakenly applied to the issuer registry.
        source = "calculations" if any(k in filters for k in ("status", "standard", "period")) else "issuers"
        targets = sorted({r["ticker"] for r in s.all_items(c, source, filters)})
        if not targets:
            raise s.ControlError("EMPTY_IMPACT_SET", "No issuers match the requested filters.", 422)
        return enqueue(c, "recalculate", "issuers", actor, reason, request_id, targets=targets)
    if action == "draft" and collection == "rules":
        from .rules import validate
        config = data.get("config") or {}
        category = data.get("category")
        validate(category, config)
        old = s.get(c, "rules", entity_id, False) if entity_id != "new" else None
        item = s.put(c, "rules", {"id": s.uid("rule"), "title": data.get("title") or config["code"],
                     "category": category, "status": "DRAFT", "config": config, "created_by": actor["email"],
                     "base_id": (old or {}).get("id"), "base_version": (old or {}).get("version"),
                     "previous_config": (old or {}).get("config"), "tests": None, "impact": None, "approved_by": None})
        s.audit(c, actor, "rule.draft", item["id"], reason, request_id, old=old, new=item)
        return {"ok": True, "item": item}
    if action == "grant" and collection == "access":
        role = data.get("role")
        if role not in CAPABILITIES and role != "disabled":
            raise s.ControlError("INVALID_ROLE", "Choose a supported role.", 422)
        email = entity_id.strip().lower()
        if email == actor["email"] or "@" not in email:
            raise s.ControlError("SELF_ROLE_CHANGE", "You cannot change your own access or use an invalid email.", 422)
        old = s.get(c, "access", email, False)
        if old and data.get("version") != old["version"]:
            raise s.ControlError("VERSION_CONFLICT", "The role assignment changed. Refresh first.")
        item = s.put(c, "access", {"id": email, "email": email, "role": role, "status": "DISABLED" if role == "disabled" else "ACTIVE"})
        s.audit(c, actor, "access.grant", email, reason, request_id, old=old, new=item)
        return {"ok": True, "item": item}
    old = s.get(c, collection, entity_id)
    if data.get("version") != old["version"]:
        raise s.ControlError("VERSION_CONFLICT", "This object changed. Refresh and compare before trying again.")
    item = dict(old)
    if collection == "documents" and action == "reprocess":
        return enqueue(c, "document-reprocess", entity_id, actor, reason, request_id, payload={"ticker": old.get("ticker")})
    if collection == "jobs" and action == "retry":
        if old["status"] not in TERMINAL:
            raise s.ControlError("JOB_ACTIVE", "Wait for the current attempt to finish.")
        return enqueue(c, old["category"], old["entity_id"], actor, reason, request_id,
                       targets=old["targets"], parent=old["id"], payload=old.get("payload"))
    if collection == "jobs" and action == "cancel":
        if old["status"] in TERMINAL:
            raise s.ControlError("JOB_FINISHED", "The job has already finished.")
        item.update(cancel_requested=True, status="CANCELLED" if old["status"] in {"QUEUED", "RETRYING"} else old["status"])
    elif collection == "incidents" and action in {"comment", "investigate", "resolve"}:
        if action == "resolve":
            # Every impacted document must have a successful attempt AFTER last_seen;
            # an operator cannot dismiss a data blocker with a checkbox.
            jobs = list(s.all_items(c, "jobs", {"status": "COMPLETED"}))
            allowed_scopes = {"financial", "classification"} if old["stage"] == "classification" else {"financial"}
            verified = {j["entity_id"] for j in jobs if j.get("finished_at", "") >= old["last_seen_at"] and j.get("result", {}).get("verified")
                        and j.get("result", {}).get("verification_scope") in allowed_scopes}
            if not set(old["affected_ids"]).issubset(verified):
                raise s.ControlError("IMPACT_NOT_VERIFIED", "The original case and every impacted object must pass verification before closure.")
            item.update(status="RESOLVED", closed_at=s.now())
        elif action == "investigate":
            item.update(status="INVESTIGATING", owner=actor["email"])
        item["comments"] = [*old.get("comments", []), {"actor": actor["email"], "text": reason, "at": s.now()}]
    elif collection == "rules":
        if action in {"test", "impact-analysis", "shadow-run"}:
            if old["status"] not in {"DRAFT", "TESTED"}:
                raise s.ControlError("RULE_IMMUTABLE", "Create a new draft to change an approved or active rule.")
            return enqueue(c, "rule-" + action, entity_id, actor, reason, request_id, payload={"rule_version": old["version"]})
        if action in {"approve", "activate"}:
            if old["created_by"] == actor["email"]:
                raise s.ControlError("SECOND_REVIEWER_REQUIRED", "A different rule editor must approve and activate this change.", 403)
            if not (old.get("tests") or {}).get("passed") or not old.get("impact"):
                raise s.ControlError("TESTS_AND_IMPACT_REQUIRED", "Run the regression tests and impact analysis first.")
            from .rules import impact_fingerprint
            if impact_fingerprint(c, old) != old["impact"]["fingerprint"]:
                raise s.ControlError("IMPACT_CHANGED", "New data arrived. Repeat impact analysis and tests.")
        if action == "approve":
            if old["status"] != "TESTED":
                raise s.ControlError("INVALID_RULE_STATE", "Only a tested draft can be approved.")
            item.update(status="APPROVED", approved_by=actor["email"], approved_at=s.now())
        elif action == "activate":
            if old["status"] != "APPROVED" or not old.get("approved_by"):
                raise s.ControlError("APPROVAL_REQUIRED", "A second reviewer must approve this draft first.")
            if not old["impact"]["tickers"]:
                raise s.ControlError("IMPACT_SET_EMPTY", "Index the source catalog before activating a rule.")
            item.update(status="ROLLING_OUT", rollout_requested_at=s.now())
            enqueue(c, "rule-rollout", entity_id, actor, reason, request_id, targets=old["impact"]["tickers"], payload={"rule_id": entity_id})
        else:
            raise s.ControlError("UNSUPPORTED_ACTION", "This rule action is not supported.", 422)
    elif collection == "publications" and action == "rollback":
        if old.get("status") not in {"PUBLISHED", "SUPERSEDED"} or old.get("blockers"):
            raise s.ControlError("PUBLICATION_NOT_VERIFIED", "Only a previously validated publication can be restored.")
        if not data.get("incident_id"):
            raise s.ControlError("INCIDENT_REQUIRED", "Link the rollback to an incident.", 422)
        s.get(c, "incidents", data["incident_id"])
        pending = old.get("rollback_request")
        if not pending:
            item["rollback_request"] = {"requested_by": actor["email"], "incident_id": data["incident_id"], "reason": reason}
        else:
            if pending["requested_by"] == actor["email"]:
                raise s.ControlError("SECOND_REVIEWER_REQUIRED", "Another reviewer must confirm this rollback.", 403)
            return enqueue(c, "publication-rollback", entity_id, actor, reason, request_id, payload={"incident_id": pending["incident_id"], "publication_version": old["version"]})
    else:
        raise s.ControlError("UNSUPPORTED_ACTION", "This object does not support that action.", 422)
    item = s.put(c, collection, item, expected=old["version"])
    s.audit(c, actor, collection + "." + action, entity_id, reason, request_id, old=old, new=item)
    return {"ok": True, "item": item}
