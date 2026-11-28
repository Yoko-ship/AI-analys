"""Paid proposals and exact owner approvals, independent from organic grants."""
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from . import checks, content, founder, goals, permissions, sources, store as s
from .errors import MarketingError, require_owner
from .models import Input


class Experiment(Input):
    title: str = Field(min_length=3, max_length=300)
    goal_version: int = Field(ge=1)
    platform: Literal["telegram", "instagram", "facebook", "linkedin"]
    advertiser_account_id: str = Field(min_length=1, max_length=200)
    campaign_ref: str = Field(min_length=1, max_length=200)
    action: Literal["create", "launch", "extend", "increase_limit", "paid_placement"]
    hypothesis: str = Field(min_length=3, max_length=4000)
    reader_question: str = Field(default="", max_length=2000)
    tested_variable: str = Field(default="", max_length=2000)
    minimum_observations: int | None = Field(default=None, ge=1)
    audience: str = Field(min_length=3, max_length=4000)
    placements: list[str] = Field(min_length=1, max_length=50)
    comparison: str = Field(min_length=3, max_length=4000)
    measurement: str = Field(min_length=3, max_length=4000)
    evaluation_starts_on: date
    evaluation_ends_on: date
    starts_at: datetime
    ends_at: datetime
    budget_limit: float = Field(gt=0)
    currency: Literal["UZS", "USD"]
    stop_condition: str = Field(min_length=3, max_length=4000)
    creative_brief: str = Field(min_length=3, max_length=6000)
    candidate_ids: list[str] = Field(default_factory=list, max_length=24)
    policy_reference: str = Field(default="", max_length=2000)
    policy_review: str = Field(default="", max_length=4000)
    policy_reviewed_on: date | None = None
    policy_review_valid_until: date | None = None

    @model_validator(mode="after")
    def valid_periods(self):
        if not self.starts_at.tzinfo or not self.ends_at.tzinfo or self.ends_at <= self.starts_at:
            raise ValueError("Supply an ordered campaign window with time zones")
        start = self.starts_at.astimezone(ZoneInfo("Asia/Tashkent")).date()
        end = self.ends_at.astimezone(ZoneInfo("Asia/Tashkent")).date()
        if not self.evaluation_starts_on <= start <= end <= self.evaluation_ends_on:
            raise ValueError("The evaluation window must cover the campaign period")
        if len(set(self.candidate_ids)) != len(self.candidate_ids) or any(not value.strip() for value in self.placements):
            raise ValueError("Choose distinct creatives and nonempty placements")
        return self


def _parameters(item):
    return {key: item[key] for key in Experiment.model_fields}


def _version(item, expected):
    if item["version"] != expected:
        raise MarketingError("EXPERIMENT_CHANGED", "The experiment changed. Reload its current version.")


def save(actor, data, experiment_id=None, expected_version=0):
    if actor.get("role") not in {"administrator", "cmo", "targeting"}:
        raise MarketingError("EXPERIMENT_ROLE", "This role cannot propose a paid experiment.", 403)
    value = Experiment.model_validate(data).model_dump(mode="json")
    with s.connection(write=True) as c:
        goal = goals.active_goal(c)
        if not goal or goal["version"] != value["goal_version"]:
            raise MarketingError("STALE_GOAL", "Review the experiment against the current approved goal.")
        prior = s.get(c, "experiment", experiment_id) if experiment_id else None
        if prior and prior["status"] == "approved":
            require_owner(actor)
        if prior and prior["status"] not in {"proposed", "approved", "revoked"}:
            raise MarketingError("PAID_ACTION_ACTIVE", "Reconcile the external action before changing its parameters.")
        return s.put(c, "experiment", {**value, "id": experiment_id or s.uid("experiment"), "status": "proposed", "approval": None},
                     actor=actor, action="paid_experiment_proposed", expected_version=expected_version)


def _creatives(c, item, now):
    if not item["candidate_ids"]:
        raise MarketingError("PAID_CREATIVE_REQUIRED", "Select checked paid creatives before approving an experiment.")
    snapshots = {}
    for key in item["candidate_ids"]:
        candidate = s.get(c, "candidate", key)
        account = s.get(c, "account", candidate["account_id"], required=False)
        proof = candidate.get("check") or {}
        if (candidate["publication_type"] != "paid" or not account or account["platform"] != item["platform"]
                or not proof.get("passed") or proof.get("content_digest") != content.content_digest(candidate)
                or candidate["status"] in {"cancelled", "skipped", "unknown", "sending", "published"}):
            raise MarketingError("PAID_CREATIVE_REQUIRED", "Select current checked paid creatives for this platform.")
        evidence = {key: value for key in candidate["evidence_ids"] if (value := sources.current_evidence(c, key))}
        versions = {key: ev["version"] for key, ev in evidence.items()}
        assets = {ref["id"]: asset for ref in candidate["assets"] if ref.get("id") and (asset := s.get(c, "asset", ref["id"], required=False))}
        failures = checks.check(candidate, evidence, now, assets)
        founder_failures, founder_versions = founder.check(c, candidate, account, now)
        if failures or founder_failures or versions != proof.get("evidence_versions") or founder_versions != proof.get("founder_versions", {}):
            raise MarketingError("PAID_EVIDENCE_CHANGED", "Creative evidence changed or expired. Check the current version again.")
        snapshots[key] = {"candidate_version": candidate["version"], "content_digest": proof["content_digest"],
            "evidence_versions": versions, "founder_versions": founder_versions,
            "account_id": account["id"], "recipient": account["external_id"], "platform": account["platform"]}
    return snapshots


def _validate(c, item, now):
    goal = goals.active_goal(c)
    if not goal or goal["version"] != item["goal_version"]:
        raise MarketingError("STALE_GOAL", "Review the experiment against the current approved goal.")
    if not item.get("reader_question") or not item.get("tested_variable") or not item.get("minimum_observations"):
        raise MarketingError("EXPERIMENT_DESIGN", "Define the reader question, single tested variable and minimum observations before approval.")
    local_date = now.astimezone(ZoneInfo("Asia/Tashkent")).date().isoformat()
    if permissions.timestamp(item["ends_at"]) <= now:
        raise MarketingError("EXPERIMENT_EXPIRED", "The campaign period ended. Prepare a new version.")
    if item["currency"] != goal["currency"]:
        raise MarketingError("PAID_CURRENCY", "The experiment currency must match the approved goal budget.")
    if (not item["policy_review"] or not checks.public_url(item["policy_reference"])
            or not item["policy_reviewed_on"] or not item["policy_review_valid_until"]
            or not item["policy_reviewed_on"] <= local_date <= item["policy_review_valid_until"]):
        raise MarketingError("PAID_POLICY_REVIEW", "Record a dated, currently valid review of the platform's advertising rules.")
    start = permissions.timestamp(item["starts_at"]).astimezone(ZoneInfo("Asia/Tashkent")).date().isoformat()
    end = permissions.timestamp(item["ends_at"]).astimezone(ZoneInfo("Asia/Tashkent")).date().isoformat()
    if not goal["starts_on"] <= start <= end <= goal["deadline"]:
        raise MarketingError("PAID_GOAL_PERIOD", "The campaign window must fit the approved goal period.")
    reservations = [row for row in s.list_items(c, "experiment", status="approved") if row["id"] != item["id"]]
    if any(row["currency"] != goal["currency"] for row in reservations):
        raise MarketingError("PAID_BUDGET_CURRENCY", "Existing approvals use a different currency. Review or revoke them before reserving another budget.")
    reserved = sum((Decimal(str(row["budget_limit"])) for row in reservations), Decimal(0))
    if reserved + Decimal(str(item["budget_limit"])) > Decimal(str(goal["budget"])):
        raise MarketingError("PAID_BUDGET", "Approved experiments would exceed the goal budget. Revoke unused approvals or review the goal separately.")
    return _creatives(c, item, now)


def approve(actor, experiment_id, expected_version, now):
    require_owner(actor)
    with s.connection(write=True) as c:
        item = s.get(c, "experiment", experiment_id)
        _version(item, expected_version)
        if item["status"] != "proposed":
            raise MarketingError("PAID_PROPOSAL_REQUIRED", "Approve a current proposal before requesting a paid action.")
        creatives = _validate(c, item, now)
        approval = {"actor": actor["id"], "at": now.isoformat(), "parameters": _parameters(item), "creatives": creatives}
        return s.put(c, "experiment", {**item, "status": "approved", "approval": approval}, actor=actor,
                     action="exact_paid_action_approved", expected_version=expected_version)


def revoke(actor, experiment_id, expected_version, reason):
    require_owner(actor)
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 2000:
        raise MarketingError("REASON_REQUIRED", "Record why the paid approval is being revoked.", 422)
    with s.connection(write=True) as c:
        item = s.get(c, "experiment", experiment_id)
        _version(item, expected_version)
        if item["status"] not in {"proposed", "approved"}:
            raise MarketingError("PAID_ACTION_ACTIVE", "Reconcile the external action before changing its parameters.")
        return s.put(c, "experiment", {**item, "status": "revoked", "reason": reason.strip(), "approval": None}, actor=actor,
                     action="paid_action_revoked", expected_version=expected_version)


def request_action(actor, experiment_id, expected_version, now):
    require_owner(actor)
    with s.connection() as c:
        item = s.get(c, "experiment", experiment_id)
        _version(item, expected_version)
        if item["status"] != "approved" or not item.get("approval"):
            raise MarketingError("PAID_APPROVAL_REQUIRED", "Separate owner approval is required for this paid action.")
        creatives = _validate(c, item, now)
        if item["approval"]["parameters"] != _parameters(item) or item["approval"]["creatives"] != creatives:
            raise MarketingError("PAID_APPROVAL_CHANGED", "The approved parameters or creatives changed. Request a new owner decision.")
        # Organic account credentials cannot satisfy this boundary. The paid
        # connector must later verify the advertiser account and action scopes.
        raise MarketingError("PAID_CONNECTION_REQUIRED", "A verified paid advertising connection is required. No external action was performed.")


def creative_context(c):
    accounts = {row["id"]: row for row in s.list_items(c, "account")}
    return [{"id": row["id"], "title": row["title"], "platform": accounts.get(row["account_id"], {}).get("platform"),
             "version": row["version"], "check_passed": bool((row.get("check") or {}).get("passed"))}
            for row in s.list_items(c, "candidate") if row["publication_type"] == "paid"][:100]


def record_proposals(c, task, role, proposals):
    """Commit the role handoff and its proposal IDs in the same transaction."""
    if not proposals:
        return []
    goal = goals.active_goal(c)
    if not goal or any(value["goal_version"] != goal["version"] for value in proposals):
        raise MarketingError("STALE_GOAL", "Paid proposals do not match the current approved goal.")
    keys = []
    for index, value in enumerate(proposals):
        key = "experiment_" + s.digest([task["id"], task["step"], index])
        if not s.get(c, "experiment", key, required=False):
            s.put(c, "experiment", {**value, "id": key, "status": "proposed", "approval": None, "task_id": task["id"]},
                  actor={"id": role, "role": role}, action="paid_experiment_proposed", expected_version=0)
        keys.append(key)
    return keys
