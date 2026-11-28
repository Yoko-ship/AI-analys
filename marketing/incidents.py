"""Original-preserving source incidents and separately authorized clarifications."""
from datetime import datetime

from pydantic import Field

from . import permissions, sources, store as s
from .errors import MarketingError, require_owner
from .models import Candidate, Claim, Input

MONITOR = {"id": "publication_monitor", "role": "quality_editor"}
FACT_FIELDS = ("entity", "url", "excerpt", "data", "units", "period", "standard", "scope", "currency", "event_at", "published_at", "analysis_version")
NOTICES = {"ru": "Уточнение к предыдущей публикации.", "uz": "Oldingi nashrga aniqlik kiritish.", "en": "Clarification of the previous publication."}


class Correction(Input):
    reason: str = Field(min_length=3, max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=18000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    destination_url: str = Field(min_length=1, max_length=2000)
    expires_at: datetime
    source_replacements: dict[str, str] = Field(default_factory=dict, max_length=100)


def _facts(row, *, live=False):
    if not row:
        return None
    value = {key: row.get(key) for key in FACT_FIELDS}
    value["withdrawn"] = row.get("status") in {"disabled", "unavailable"}
    if row.get("analysis_version"):
        version = row["analysis_version"]
        if live:
            from reporting import store as reports
            report = reports.get_run(version)
            current = reports.latest_publication(report["issuer"]["id"], report["language"], report["standard"]) if report else None
            version = current["version"] if current else None
        value["current_analysis_version"] = version
    return value


def _changes(c, publication):
    changes = []
    for evidence_id, version in (publication.get("check") or {}).get("evidence_versions", {}).items():
        original = s.revision(c, "evidence", evidence_id, version)
        current = sources.current_evidence(c, evidence_id)
        before, after = _facts(original), _facts(current, live=True)
        if before != after:
            changes.append({"evidence_id": evidence_id, "original_version": version,
                "current_version": current["version"] if current else None, "before": before, "after": after,
                "fields": [key for key in dict.fromkeys([*(before or {}), *(after or {})]) if (before or {}).get(key) != (after or {}).get(key)]})
    # Arrival/verification versions do not manufacture another factual change.
    basis = s.digest([{key: change[key] for key in ("evidence_id", "before", "after")} for change in changes])
    return changes, basis


def _publication(job, item, account=None):
    return {"candidate_id": item["id"], "title": item["title"], "body": item["body"], "account_id": item["account_id"],
            "external_id": job["external_id"], "url": job.get("url", ""), "external_account_id": job["external_account_id"],
            "platform": job.get("platform") or (account or {}).get("platform"), "confirmed_at": job["finished_at"]}


def record_publication(c, item, job, account):
    """Only a confirmed transport outcome advances the public correction chain."""
    root = item.get("correction_of") or item["id"]
    old = s.get(c, "publication_watch", root, required=False)
    if old and old.get("incident_id") and old["incident_id"] != item.get("correction_incident"):
        pending = s.get(c, "incident", old["incident_id"])
        if pending["status"] in {"open", "correction_prepared"}:
            s.put(c, "incident", {**pending, "status": "superseded", "superseded_by_publication": item["id"]},
                  actor=MONITOR, action="new_publication_requires_current_comparison", expected_version=pending["version"])
    s.put(c, "publication_watch", {"id": root, "head_id": item["id"], "basis": None, "incident_id": None},
          actor=MONITOR, action="publication_confirmed", expected_version=old["version"] if old else 0)
    if item.get("correction_incident"):
        incident = s.get(c, "incident", item["correction_incident"])
        s.put(c, "incident", {**incident, "status": "corrected", "correction_publication": _publication(job, item, account)},
              actor=MONITOR, action="clarification_confirmed", expected_version=incident["version"])


def scan(now):
    changed = False
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return False
        roots = [row for row in s.list_items(c, "candidate", status="published") if not row.get("correction_of")]
        for root in roots:
            watch = s.get(c, "publication_watch", root["id"], required=False) or {"id": root["id"], "head_id": root["id"], "version": 0}
            head = s.get(c, "candidate", watch["head_id"])
            job = s.get(c, "delivery", head["id"], required=False)
            if not job or job["status"] != "published" or not job.get("external_id"):
                continue
            changes, basis = _changes(c, head)
            if basis == watch.get("basis"):
                continue
            previous = s.get(c, "incident", watch["incident_id"], required=False) if watch.get("incident_id") else None
            key = s.uid("incident") if changes else None
            if previous and previous["status"] not in {"corrected", "not_material", "superseded"}:
                s.put(c, "incident", {**previous, "status": "superseded", "superseded_by": key},
                      actor=MONITOR, action="source_changed_again", expected_version=previous["version"])
                changed = True
            if changes:
                s.put(c, "incident", {"id": key, "root_candidate_id": root["id"], "publication_id": head["id"],
                    "publication": _publication(job, head), "basis": basis, "changes": changes,
                    "status": "open", "detected_at": now.isoformat(), "correction_id": None},
                    actor=MONITOR, action="published_source_changed", expected_version=0)
                changed = True
            s.put(c, "publication_watch", {**watch, "basis": basis, "incident_id": key},
                  actor=MONITOR, action="publication_sources_checked", expected_version=watch["version"])
    return changed


def _current(c, incident):
    watch = s.get(c, "publication_watch", incident["root_candidate_id"])
    _, basis = _changes(c, s.get(c, "candidate", incident["publication_id"]))
    return watch["head_id"] == incident["publication_id"] and watch.get("incident_id") == incident["id"] and basis == incident["basis"]


def _recipient(incident, account):
    publication = incident["publication"]
    return account and account["id"] == publication["account_id"] and account["external_id"] == publication["external_account_id"] and account["platform"] == publication["platform"]


def _sources_bound(incident, evidence_ids, replacements):
    changed = {row["evidence_id"] for row in incident["changes"]}
    return not (set(replacements) - changed) and all(replacements.get(key, key) in evidence_ids for key in changed)


def prepare(actor, incident_id, expected_version, data, now):
    require_owner(actor)
    value = Correction.model_validate(data).model_dump(mode="json")
    from . import checks, content
    with s.connection(write=True) as c:
        incident = s.get(c, "incident", incident_id)
        if incident["version"] != expected_version or incident["status"] != "open" or not _current(c, incident):
            raise MarketingError("INCIDENT_CHANGED", "The incident changed or already has a clarification. Reload its current version.")
        original = s.get(c, "candidate", incident["publication_id"])
        account = s.get(c, "account", original["account_id"])
        if not _recipient(incident, account):
            raise MarketingError("CORRECTION_RECIPIENT", "The original recipient changed; a clarification cannot be sent to another account.")
        if not _sources_bound(incident, value["evidence_ids"], value["source_replacements"]):
            raise MarketingError("CORRECTION_SOURCE", "Retain each changed source or explicitly select its replacement.", 422)
        if any(row.get("correction_of") == incident["root_candidate_id"] and row["status"] in {"sending", "unknown", "submitted"}
               for row in s.list_items(c, "candidate")):
            raise MarketingError("CORRECTION_UNKNOWN", "A prior clarification needs reconciliation before another can be prepared.")
        notice = NOTICES[original["language"]]
        url = incident["publication"]["url"]
        url = url if checks.public_url(url) else ""
        body = notice + "\n\n" + value["body"] + ("\n\n" + url if url else "")
        mode = "manual" if account["mode"] != "draft" and account["correction_policy"] == "manual" else account["mode"]
        inputs = {key: original[key] for key in Candidate.model_fields if key in original}
        inputs.update({key: value[key] for key in ("title", "evidence_ids", "claims", "destination_url", "expires_at")})
        inputs.update(event_id="correction:" + incident_id, body=body, mode=mode, assets=[], not_before=None)
        item = content.create_in(c, Candidate.model_validate(inputs).model_dump(mode="json"), provenance={
            "correction_of": incident["root_candidate_id"], "correction_parent": original["id"], "correction_incident": incident_id,
            "correction_notice": notice, "correction_url": url, "correction_sources": value["source_replacements"]})
        s.put(c, "incident", {**incident, "status": "correction_prepared", "reason": value["reason"], "correction_id": item["id"],
              "prepared_at": now.isoformat()}, actor=actor, action="clarification_prepared", expected_version=expected_version)
        return item


def check(c, item, account):
    if not item.get("correction_incident"):
        return []
    incident = s.get(c, "incident", item["correction_incident"], required=False)
    if (not incident or incident["status"] != "correction_prepared" or incident["correction_id"] != item["id"] or not _current(c, incident)):
        return ["Correction incident changed; review the current source incident"]
    if not _recipient(incident, account):
        return ["Correction recipient no longer matches the original publication"]
    if not _sources_bound(incident, item["evidence_ids"], item.get("correction_sources", {})):
        return ["Retain each changed source or explicitly select its replacement"]
    if not item["body"].startswith(item["correction_notice"]) or (item["correction_url"] and item["correction_url"] not in item["body"]):
        return ["The visible correction notice and original publication link must remain in the text"]
    return []


def dismiss(actor, incident_id, expected_version, reason):
    require_owner(actor)
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise MarketingError("REASON_REQUIRED", "Record why the change does not affect the publication.", 422)
    with s.connection(write=True) as c:
        incident = s.get(c, "incident", incident_id)
        if incident["status"] not in {"open", "correction_prepared"} or not _current(c, incident):
            raise MarketingError("INCIDENT_CHANGED", "Review the current incident before deciding.")
        if incident.get("correction_id"):
            item = s.get(c, "candidate", incident["correction_id"])
            if item["status"] in {"sending", "unknown", "submitted", "published"}:
                raise MarketingError("CORRECTION_DISPATCHED", "Reconcile the dispatched clarification before deciding.")
            from . import content
            content._stop_pending_delivery(c, item, actor, "cancelled")
            if item["status"] not in content.TERMINAL:
                s.put(c, "candidate", {**item, "status": "cancelled"}, actor=actor,
                      action="clarification_not_needed", expected_version=item["version"])
        return s.put(c, "incident", {**incident, "status": "not_material", "reason": reason.strip()}, actor=actor,
                     action="owner_assessed_source_change", expected_version=expected_version)
