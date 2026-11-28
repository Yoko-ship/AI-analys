"""Versioned inputs for future plan work; the worker launches each binding once."""
from datetime import datetime, timezone

from . import execution, founder, goals, planning, production, sources, store as s, trends
from .errors import MarketingError, require_owner
from .permissions import timestamp


def _basis(c, inputs, now):
    evidence_versions = {}
    for key in dict.fromkeys(inputs["evidence_ids"]):
        record = sources.current_evidence(c, key)
        execution._require(record and record["status"] == "verified" and timestamp(record["expires_at"]) > now,
                           "Prepared evidence is unavailable, unverified or expired. Review the inputs.")
        evidence_versions[key] = record["version"]
    trend_versions = {key: s.get(c, "trend", key)["version"] for key in dict.fromkeys(inputs["trend_ids"])}
    trends.task_context(c, trend_versions, now)
    snapshots = planning.context(c, list(dict.fromkeys(inputs["planning_snapshot_ids"])), goals.active_goal(c), now)
    accounts, facts = {}, {}
    if inputs["production"]:
        scope, _ = production.scope_context(c, inputs["production"])
        execution._require(timestamp(scope["expires_at"]) > now, "The prepared draft brief expired. Review the inputs.")
        accounts = {target["account_id"]: s.get(c, "account", target["account_id"])["version"] for target in scope["targets"]}
        for key in scope["founder_fact_ids"]:
            fact = s.get(c, "founder_fact", key)
            execution._require(founder.usable(fact, now), "Prepared founder facts changed or expired. Review the inputs.")
            facts[key] = fact["version"]
    return {"evidence_versions": evidence_versions, "trend_versions": trend_versions,
            "planning_snapshots": snapshots, "account_versions": accounts, "founder_versions": facts}


def _validate_scope(c, row, inputs):
    step, scope = row["step"], inputs["production"]
    execution._require(step["owner"] != "owner", "This step requires the owner's recorded result.")
    if step["mode"] == "organic":
        execution._require(scope and scope["mode"] == "draft" and scope["rubric"] == step["rubric"],
                           "Plan content work requires a draft brief with its approved rubric.")
        execution._require(bool(inputs["evidence_ids"]), "Select verified originals before preparing a draft step.")
        execution._require(all(s.get(c, "account", target["account_id"])["platform"] == step["channel"] for target in scope["targets"]),
                           "Draft recipients must belong to the step's planned platform.")
        execution._require(not s.get(c, "task", production.task_key(scope), required=False),
                           "This event already belongs to an existing production task. Review that task instead of duplicating it.")
    else:
        execution._require(scope is None, "Only an organic plan step can receive a production brief.")


def prepare(actor, step_id, expected_version, inputs, *, now=None):
    require_owner(actor)
    inputs = execution.WorkInputs.model_validate(inputs).model_dump(mode="json")
    now = now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        row = s.get(c, "plan_step", step_id)
        execution._require(row["status"] in {"pending", "prepared", "needs_revision", "blocked", "cancelled"}
                           and row["attempts"] < 3, "This work item cannot start another attempt.")
        execution._plan(c, s.get(c, "plan_run", row["run_id"]), now)
        _validate_scope(c, row, inputs)
        binding = {"inputs": inputs, "basis": _basis(c, inputs, now), "prepared_at": now.isoformat(),
                   "prepared_by": actor["id"], "status": "armed"}
        return s.put(c, "plan_step", {**row, "preparation": binding, "status": "prepared",
                     "reason": "Prepared inputs wait for the start date and accepted prerequisites"}, actor=actor,
                     action="plan_inputs_prepared", expected_version=expected_version)


def cancel(actor, step_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        row = s.get(c, "plan_step", step_id)
        execution._require(automatic(row), "This work item has no pending preparation.")
        return s.put(c, "plan_step", {**row, "status": "pending" if not row["task_id"] else "needs_revision",
                     "preparation": {**row["preparation"], "status": "cancelled"},
                     "reason": "Automatic assignment cancelled; saved inputs remain in history"}, actor=actor,
                     action="plan_preparation_cancelled", expected_version=expected_version)


def _check_binding(c, binding, now):
    current = _basis(c, binding["inputs"], now)
    for key, message in (
        ("evidence_versions", "Prepared evidence changed. Review the inputs."),
        ("trend_versions", "Prepared theme observations changed. Review the inputs."),
        ("planning_snapshots", "The prepared measurement basis changed. Review the inputs."),
        ("account_versions", "A prepared account changed. Review the draft recipients."),
        ("founder_versions", "Prepared founder facts changed or expired. Review the inputs."),
    ):
        execution._require(current[key] == binding["basis"][key], message)


def automatic(row):
    state = (row.get("preparation") or {}).get("status")
    return (row["status"] == "prepared" and state == "armed") or (
        row["status"] == "needs_revision" and state == "launched" and row["attempts"] < 3
        and row["step"]["mode"] in {"operations", "research", "measurement"})


def run_one(now):
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return False
        rows = [row for row in s.list_items(c, "plan_step") if automatic(row)]
        for row in sorted(rows, key=lambda value: (value["step"]["due"], value["step"]["starts_on"], value["preparation"]["prepared_at"], value["id"])):
            run = s.get(c, "plan_run", row["run_id"])
            if run["status"] != "active":
                continue
            try:
                execution._ready(c, row, now)
            except MarketingError:
                # Readiness is shown live on the board. A future date or an
                # incomplete prerequisite must not consume the preparation.
                continue
            try:
                _check_binding(c, row["preparation"], now)
                # A savepoint prevents a rejected duplicate or changed scope
                # from leaving a partial task while we record its blocker.
                c.execute("SAVEPOINT prepared_assignment")
                try:
                    execution._launch_in(c, execution.COORDINATOR, row, row["preparation"]["inputs"], now)
                except Exception:
                    c.execute("ROLLBACK TO SAVEPOINT prepared_assignment")
                    raise
                finally:
                    c.execute("RELEASE SAVEPOINT prepared_assignment")
            except MarketingError as exc:
                s.put(c, "plan_step", {**row, "status": "blocked", "reason": str(exc),
                      "preparation": {**row["preparation"], "status": "blocked"}}, actor=execution.COORDINATOR,
                      action="plan_preparation_blocked", expected_version=row["version"])
                continue
            return True
    return False
