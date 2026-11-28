"""Candidate lifecycle. Failed automatic candidates cannot be reopened or resent."""
from . import checks, digest_material, founder, incidents, permissions, publication_links, publishing, sources, store as s
from .errors import MarketingError, require_owner
from .models import Candidate, Evidence

EDITOR = {"id": "quality", "role": "quality_editor"}
COORDINATOR = {"id": "coordinator", "role": "coordinator"}
TERMINAL = {"skipped", "published", "submitted", "cancelled", "unknown"}
EDITABLE = {"title", "body", "claims", "digest_items", "occasion", "evidence_ids", "destination_url", "instagram_link", "track_visits", "assets", "expires_at", "not_before", "calculation", "founder_fact_ids", "language"}


def save_evidence(actor, evidence_id, data, expected_version):
    require_owner(actor)
    value = Evidence.model_validate(data).model_dump(mode="json")
    if not checks.public_url(value["url"]):
        raise MarketingError("INVALID_SOURCE", "Use an HTTPS source URL without credentials.", 422)
    with s.connection(write=True) as c:
        return s.put(c, "evidence", {**value, "id": evidence_id}, actor=actor,
                     action="evidence_recorded", expected_version=expected_version)


def content_digest(item):
    # Previously accepted releases lack this field; preserve their frozen proof.
    value = {key: item.get(key) for key in Candidate.model_fields if key not in {"instagram_link", "track_visits", "digest_items", "occasion"} or key in item}
    if item.get('tracking'):
        value['tracking'] = item['tracking']
    return s.digest(value)


def _stop_pending_delivery(c, item, actor, status):
    job = s.get(c, "delivery", item["id"], required=False)
    if job and job["status"] not in {"sending", "published", "submitted", "unknown", "cancelled"}:
        s.put(c, "delivery", {**job, "status": status, "reason": "Content changed or was cancelled; release is blocked"},
              actor=actor, action="content_" + status, expected_version=job["version"])


def create_candidate(data, *, provenance=None):
    value = Candidate.model_validate(data).model_dump(mode="json")
    with s.connection(write=True) as c:
        return create_in(c, value, provenance=provenance)


def create_in(c, value, *, provenance=None):
    if value["event_id"].startswith("correction:") and value["event_id"] != "correction:" + str((provenance or {}).get("correction_incident", "")):
        raise MarketingError("RESERVED_EVENT", "Correction event IDs are reserved for the incident workflow.", 422)
    key = s.digest([value["event_id"], value["account_id"], value["publication_type"]])
    previous = s.get(c, "candidate", key, required=False)
    if previous:
        return previous
    if s.get(c, 'publication_reservation', key, required=False):
        raise MarketingError('RECOVERED_EVENT_RESERVED', 'Этот выпуск зарезервирован при сверке после восстановления. Повторная публикация закрыта.', 409)
    value = digest_material.prepare(c, value)
    item = {**value, **(provenance or {}), "id": key, "status": "draft", "check": None, "approval": None}
    item['tracking'] = publication_links.issue(c, item)
    return s.put(c, "candidate", item,
                 actor=COORDINATOR, action="candidate_created", expected_version=0)


def revise_candidate(actor, candidate_id, changes, expected_version, *, review_destination=True):
    require_owner(actor)
    if set(changes) - EDITABLE:
        raise MarketingError("INVALID_CHANGE", "The event, account and release mode cannot change on an existing candidate.", 422)
    with s.connection(write=True) as c:
        item = s.get(c, "candidate", candidate_id)
        if item["status"] in TERMINAL or item["status"] == "sending":
            raise MarketingError("TERMINAL_CANDIDATE", "This candidate is terminal or already sending; its history is preserved.")
        inputs = {key: item[key] for key in Candidate.model_fields if key in item}
        value = Candidate.model_validate({**inputs, **changes}).model_dump(mode="json")
        value = digest_material.prepare(c, value)
        _stop_pending_delivery(c, item, actor, "blocked")
        changed = {**item, **value, "status": "draft", "check": None, "approval": None, "editorial_review": None}
        if review_destination and "destination_url" in changes and item.get("origin_task"):
            changed["destination_review"] = {"actor": actor["id"], "url": value["destination_url"],
                "account_id": item["account_id"], "event_id": item["event_id"], "at": s.now()}
        changed['tracking'] = publication_links.issue(c, changed)
        return s.put(c, "candidate", changed,
                     actor=actor, action="content_revised", expected_version=expected_version)


def check_candidate(candidate_id, now):
    with s.connection(write=True) as c:
        return _check_in(c, s.get(c, "candidate", candidate_id), now)


def release_failures(c, item):
    decision = item.get("release_decision")
    if decision:
        account = s.get(c, "account", item["account_id"], required=False)
        if not permissions.release_recipient_matches(account, item):
            return ["The recipient differs from the owner's draft release decision"]
    return []


def release_draft(actor, candidate_id, expected_version, account_version, now):
    """An explicit owner decision leaves internal mode; all final checks still run."""
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "candidate", candidate_id)
        account = s.get(c, "account", item["account_id"])
        if item["version"] != expected_version or account["version"] != account_version:
            raise MarketingError("VERSION_CONFLICT", "This record changed. Reload before saving.")
        if item["mode"] != "draft" or item["status"] not in {"draft", "needs_revision"}:
            raise MarketingError("DRAFT_REQUIRED", "Only an internal draft can enter the release workflow.")
        allowed, reason = permissions.can_release(account, item, now)
        if not allowed:
            raise MarketingError("NOT_AUTHORIZED", reason)
        decision = {"actor": actor["id"], "at": now.isoformat(), "candidate_version": item["version"],
                    "account_id": account["id"], "account_version": account["version"],
                    "platform": account["platform"], "external_id": account["external_id"]}
        changed = {**item, "mode": account["mode"], "check": None, "approval": None, "release_decision": decision}
        changed["tracking"] = publication_links.issue(c, changed)
        changed = s.put(c, "candidate", changed, actor=actor, action="draft_release_requested", expected_version=expected_version)
        return _check_in(c, changed, now)


def _check_in(c, item, now):
    from . import automation
    if item["status"] in TERMINAL or item["status"] == "sending":
        return item
    evidence = {key: source for key in item["evidence_ids"] if (source := sources.current_evidence(c, key))}
    assets = {key: asset for ref in item["assets"] if (key := ref.get("id")) and (asset := s.get(c, "asset", key, required=False))}
    failures = checks.check(item, evidence, now, assets)
    failures.extend(release_failures(c, item))
    failures.extend(automation.candidate_failures(c, item, now))
    failures.extend(publication_links.check(c, item))
    if item.get("editorial_review") and item["editorial_review"]["verdict"] != "accept":
        failures.append("Quality review rejected this exact version: " + item["editorial_review"]["reason"])
    account = s.get(c, "account", item["account_id"], required=False)
    failures.extend(publishing.check(account, item, evidence))
    failures.extend(incidents.check(c, item, account))
    personal_failures, founder_versions = founder.check(c, item, account, now)
    failures.extend(personal_failures)
    allowed, reason = permissions.can_release(account, item, now)
    if failures:
        status = "skipped" if item["mode"] == "automatic" else "needs_revision"
    elif not allowed or item["mode"] == "draft":
        status = "draft"
    elif permissions.requires_approval(account, item):
        status = "awaiting_approval"
    else:
        status = "ready"
    result = {"passed": not failures, "reason": "; ".join(failures) if failures else reason,
              "failures": failures, "checked_at": now.isoformat(), "content_digest": content_digest(item),
              "asset_versions": {key: {"version": asset["version"], "sha256": asset.get("sha256")} for key, asset in assets.items()},
              "evidence_versions": {key: source["version"] for key, source in evidence.items()}, "founder_versions": founder_versions}
    return s.put(c, "candidate", {**item, "status": status, "check": result, "approval": None},
                 actor=EDITOR, action="final_check", expected_version=item["version"])


def approve_candidate(actor, candidate_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "candidate", candidate_id)
        if item["status"] != "awaiting_approval" or not item["check"] or not item["check"]["passed"]:
            raise MarketingError("CHECK_REQUIRED", "Only a checked manual version can be approved.")
        approval = {"actor": actor["id"], "account_id": item["account_id"], "content_digest": content_digest(item), "at": s.now()}
        return s.put(c, "candidate", {**item, "status": "ready", "approval": approval},
                     actor=actor, action="manual_release_approved", expected_version=expected_version)


def cancel_candidate(actor, candidate_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "candidate", candidate_id)
        if item["status"] in TERMINAL or item["status"] == "sending":
            raise MarketingError("ALREADY_DISPATCHED", "The action cannot be recalled; inspect its recorded outcome.")
        _stop_pending_delivery(c, item, actor, "cancelled")
        return s.put(c, "candidate", {**item, "status": "cancelled"}, actor=actor,
                     action="candidate_cancelled", expected_version=expected_version)
