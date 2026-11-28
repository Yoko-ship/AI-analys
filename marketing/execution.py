"""Approved-plan work, exact assignments and accepted prerequisite handoffs."""
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import Field

from . import goals, store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT, timestamp
from .production_models import ProductionBrief

COORDINATOR = {"id": "coordinator", "role": "coordinator"}


class WorkInputs(Input):
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    trend_ids: list[str] = Field(default_factory=list, max_length=10)
    planning_snapshot_ids: list[str] = Field(default_factory=list, max_length=10)
    production: ProductionBrief | None = None


class OwnerResult(Input):
    summary: str = Field(min_length=20, max_length=6000)
    reference: str = Field(min_length=10, max_length=2000)


def _require(condition, message):
    if not condition:
        raise MarketingError("PLAN_WORK_BLOCKED", message)


def _plan(c, run, now):
    _require(run["status"] == "active", "This working plan is paused.")
    plan = s.revision(c, "strategy", run["strategy_id"], run["strategy_version"])
    _require(plan and plan["status"] == "approved", "Work needs the exact approved strategy version.")
    checked = goals.current_strategy(c, plan, now)
    _require(checked["readiness"]["status"] == "ready", checked["readiness"]["reason"])
    _require(now.astimezone(TASHKENT).date().isoformat() <= goals.active_goal(c)["deadline"], "The goal period ended. Review its deadline with the owner.")
    return plan


def activate(actor, strategy_id, expected_version, *, now=None):
    require_owner(actor)
    now = now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        plan = s.get(c, "strategy", strategy_id)
        _require(plan["version"] == expected_version and plan["status"] == "approved", "Work needs the exact approved strategy version.")
        key = "plan_" + s.digest([strategy_id, expected_version])
        prior = s.get(c, "plan_run", key, required=False)
        if prior:
            return prior
        run = {"id": key, "strategy_id": strategy_id, "strategy_version": expected_version, "goal_version": plan["goal_version"],
               "title": plan["title"], "status": "active", "activated_at": now.isoformat()}
        _plan(c, run, now)
        for old in s.list_items(c, "plan_run", status="active"):
            if old["strategy_id"] == strategy_id:
                s.put(c, "plan_run", {**old, "status": "paused", "replaced_by": key}, actor=actor,
                      action="plan_replaced", expected_version=old["version"])
        saved = s.put(c, "plan_run", run, actor=actor, action="plan_activated", expected_version=0)
        ids = {step["id"]: "step_" + s.digest([key, step["id"]]) for step in plan["steps"]}
        for step in plan["steps"]:
            s.put(c, "plan_step", {"id": ids[step["id"]], "run_id": key, "step": step,
                  "dependencies": [ids[dep] for dep in step["dependencies"]], "status": "pending", "attempts": 0,
                  "task_id": None, "task_ids": [], "reason": "Waiting for an internal work brief"},
                  actor=COORDINATOR, action="plan_step_created", expected_version=0)
        return saved


def _prerequisites(c, row, now):
    result = []
    for key in row["dependencies"]:
        prerequisite = s.get(c, "plan_step", key)
        _require(prerequisite["status"] == "complete", "A prerequisite has no accepted result yet.")
        if prerequisite.get("owner_result"):
            result.append({"step_id": key, "step": prerequisite["step"], "owner_result": prerequisite["owner_result"]})
            continue
        task = s.get(c, "task", prerequisite["task_id"])
        _require(task["status"] == "complete" and task["outputs"] and task["outputs"][-1]["result"]["verdict"] == "accept",
                 "A prerequisite has no accepted result yet.")
        _inputs_current(c, task, now)
        result.append({"step_id": key, "step": prerequisite["step"], "task_id": task["id"], "task_version": task["version"], "outputs": task["outputs"]})
    return result


def _inputs_current(c, task, now):
    from . import planning, sources
    if (task.get("plan") or {}).get("preparation"):
        from . import scheduling
        scheduling._check_binding(c, task["plan"]["preparation"], now)
    original = {row["id"]: row for row in task["evidence"]}
    for key, version in task["evidence_versions"].items():
        evidence = sources.current_evidence(c, key)
        _require(evidence and evidence["version"] == version and evidence["status"] == original[key]["status"]
                 and timestamp(evidence["expires_at"]) > now, "The work item's selected evidence changed or expired. Prepare a new assignment.")
    for basis in task.get("planning_snapshots", []):
        if basis.get("eligible"):
            current = planning.measured_basis(c, basis["snapshot_id"], task["goal"], now)
            _require(current["basis_digest"] == basis["basis_digest"], "The work item's measured basis changed. Prepare a new assignment.")
    for artifact in (task.get("plan") or {}).get("artifacts", []):
        current = s.get(c, artifact["kind"], artifact["id"])
        _require(current["version"] == artifact["version"], "A prepared artifact changed during CMO review.")


def _ready(c, row, now, *, check_plan=True):
    if check_plan:
        _plan(c, s.get(c, "plan_run", row["run_id"]), now)
    _require(row["step"]["starts_on"] <= now.astimezone(TASHKENT).date().isoformat(), "The step's start date has not arrived.")
    return _prerequisites(c, row, now)


def current(c, run, now):
    from . import scheduling
    try:
        _plan(c, run, now)
        plan_error = None
    except MarketingError as exc:
        plan_error = str(exc)
    values = []
    for row in s.list_items(c, "plan_step"):
        if row["run_id"] != run["id"]:
            continue
        try:
            _require(not plan_error, plan_error)
            _ready(c, row, now, check_plan=False)
            readiness = {"status": "ready", "reason": ""}
        except MarketingError as exc:
            readiness = {"status": "blocked", "reason": str(exc)}
        can_review = readiness["status"] == "ready" and row["step"]["mode"] == "organic" and row["status"] in {"needs_revision", "blocked", "complete"} and row["attempts"] < 3
        if row["status"] == "complete" and row["task_id"] and readiness["status"] == "ready":
            try:
                _inputs_current(c, s.get(c, "task", row["task_id"]), now)
                can_review = False
            except MarketingError as exc:
                readiness = {"status": "blocked", "reason": str(exc)}
        values.append({**row, "readiness": readiness, "can_review": can_review, "automatic_assignment": scheduling.automatic(row),
                       "overdue": row["status"] != "complete" and row["step"]["due"] < now.astimezone(TASHKENT).date().isoformat()})
    order = {step["id"]: index for index, step in enumerate(s.revision(c, "strategy", run["strategy_id"], run["strategy_version"])["steps"])}
    return {**run, "items": sorted(values, key=lambda row: order[row["step"]["id"]])}


def launch(actor, step_id, expected_version, inputs, *, now=None):
    require_owner(actor)
    inputs = WorkInputs.model_validate(inputs).model_dump(mode="json")
    now = now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        row = s.get(c, "plan_step", step_id)
        _require(row["version"] == expected_version, "The work item changed. Reload before starting it.")
        return _launch_in(c, actor, row, inputs, now)


def _launch_in(c, actor, row, inputs, now):
    from . import agents
    _require(row["status"] in {"pending", "prepared", "needs_revision", "blocked", "cancelled"} and row["attempts"] < 3, "This work item cannot start another attempt.")
    prerequisites = _ready(c, row, now)
    run = s.get(c, "plan_run", row["run_id"])
    step = row["step"]
    _require(step["owner"] != "owner", "This step requires the owner's recorded result.")
    kind = {"research": "research", "measurement": "report", "operations": "dialogue", "organic": "draft", "paid_proposal": "experiment"}[step["mode"]]
    roles = [step["owner"]] + ([] if step["owner"] == "cmo" else ["cmo"])
    scope = inputs["production"]
    if step["mode"] == "organic":
        _require(scope and scope["mode"] == "draft" and scope["rubric"] == step["rubric"], "Plan content work requires a draft brief with its approved rubric.")
        _require(all(s.get(c, "account", target["account_id"])["platform"] == step["channel"] for target in scope["targets"]),
                 "Draft recipients must belong to the step's planned platform.")
        roles = None
    else:
        _require(scope is None, "Only an organic plan step can receive a production brief.")
        if step["mode"] == "paid_proposal":
            roles = None
    previous = s.get(c, "task", row["task_id"]) if row["task_id"] else None
    context = {"run_id": run["id"], "step_id": row["id"], "strategy_id": run["strategy_id"], "strategy_version": run["strategy_version"],
               "step": step, "prerequisites": prerequisites, "previous_task_id": row["task_id"],
                   "preparation": row.get("preparation") if actor == COORDINATOR else None,
               "revision_feedback": previous["outputs"][-1]["result"] if previous and previous["outputs"] else None}
    task = agents._start_in(c, actor, kind=kind, message=f'{step["action"]}\nОжидаемый результат: {step["deliverable"]}',
                            evidence_ids=inputs.get("evidence_ids", []), planning_snapshot_ids=inputs.get("planning_snapshot_ids", []),
                            trend_ids=inputs.get("trend_ids", []), production=scope, plan=context, assigned_roles=roles)
    _require((task.get("plan") or {}).get("step_id") == row["id"] and task["id"] not in row["task_ids"],
             "This event already belongs to an existing production task. Review that task instead of duplicating it.")
    _inputs_current(c, task, now)
    preparation = ({**row["preparation"], "status": "launched" if context["preparation"] else "cancelled"}
                   if row.get("preparation") else None)
    s.put(c, "plan_step", {**row, "preparation": preparation, "status": "queued", "task_id": task["id"], "task_ids": [*row["task_ids"], task["id"]],
          "attempts": row["attempts"] + 1, "reason": "Assigned to the responsible role"},
          actor=COORDINATOR, action="plan_step_assigned", expected_version=row["version"])
    return task


def guard(c, task, now):
    if not task.get("plan"):
        return
    row = s.get(c, "plan_step", task["plan"]["step_id"])
    _require(row["task_id"] == task["id"], "A newer task replaced this plan assignment.")
    _ready(c, row, now)
    _inputs_current(c, task, now)


def validate_output(task, result):
    if not task.get("plan"):
        return
    step = task["plan"]["step"]
    for proposal in result["experiments"]:
        _require(step["mode"] == "paid_proposal" and proposal["platform"] == step["channel"]
                 and proposal["currency"] == task["goal"]["currency"]
                 and Decimal(str(proposal["budget_limit"])) <= Decimal(str(step["budget"])),
                 "The paid proposal exceeds this step's platform, currency or budget limits.")
    proposals = [proposal for output in task["outputs"] for proposal in output["result"].get("experiments", [])] + result["experiments"]
    _require(sum((Decimal(str(proposal["budget_limit"])) for proposal in proposals), Decimal(0)) <= Decimal(str(step["budget"])),
             "The paid proposal exceeds this step's platform, currency or budget limits.")


def set_paused(actor, run_id, expected_version, paused):
    require_owner(actor)
    with s.connection(write=True) as c:
        run = s.get(c, "plan_run", run_id)
        _require(paused or not run.get("replaced_by"), "A newer approved strategy replaced this working plan.")
        return s.put(c, "plan_run", {**run, "status": "paused" if paused else "active"}, actor=actor,
                     action="plan_paused" if paused else "plan_resumed", expected_version=expected_version)


def record_owner_result(actor, step_id, expected_version, data, *, now=None):
    require_owner(actor)
    value = OwnerResult.model_validate(data).model_dump(mode="json")
    now = now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        row = s.get(c, "plan_step", step_id)
        _require(row["step"]["owner"] == "owner" and row["status"] == "pending", "Only the owner can record the result of a pending owner step.")
        _ready(c, row, now)
        return s.put(c, "plan_step", {**row, "status": "complete", "owner_result": {**value, "at": now.isoformat(), "recorded_by": actor["id"]},
                     "reason": "Result and reference recorded by the owner"}, actor=actor, action="owner_step_completed", expected_version=expected_version)


def _review_drafts(c, row, task, now, *, refresh_inputs=False):
    from . import agents, checks, content, founder, publishing, sources
    if refresh_inputs:
        _ready(c, row, now)
    else:
        guard(c, task, now)
    candidates = [s.get(c, "candidate", key) for key in task.get("candidate_ids", [])]
    if len(candidates) != len(task["production"]["targets"]):
        return None
    for value in candidates:
        proof = value.get("check") or {}
        if (value.get("origin_task") != task["id"] or value["mode"] != "draft" or not proof.get("passed")
                or proof.get("content_digest") != content.content_digest(value)):
            return None
        evidence = {key: source for key in value["evidence_ids"] if (source := sources.current_evidence(c, key))}
        assets = {ref["id"]: asset for ref in value["assets"] if (asset := s.get(c, "asset", ref["id"], required=False))}
        account = s.get(c, "account", value["account_id"])
        personal_failures, founder_versions = founder.check(c, value, account, now)
        if (proof.get("evidence_versions") != {key: source["version"] for key, source in evidence.items()}
                or proof.get("asset_versions", {}) != {key: {"version": asset["version"], "sha256": asset.get("sha256")} for key, asset in assets.items()}
                or proof.get("founder_versions", {}) != founder_versions or personal_failures
                or checks.check(value, evidence, now, assets) or content.publication_links.check(c, value)
                or publishing.check(account, value, evidence)):
            return None
    artifacts = [{"kind": "candidate", "id": value["id"], "version": value["version"], "record": value} for value in candidates]
    previous = s.get(c, "task", row["task_id"])
    context = {**task["plan"], "phase": "review", "production_task_id": task["id"], "artifacts": artifacts,
               "preparation": None if refresh_inputs else task["plan"].get("preparation"),
               "revision_feedback": previous["outputs"][-1]["result"] if refresh_inputs and previous["outputs"] else None}
    return agents._start_in(c, COORDINATOR, kind="dialogue", message=f'Проверьте сохранённые черновики на соответствие результату плана: {row["step"]["deliverable"]}',
                            evidence_ids=list(task["evidence_versions"]), plan=context, assigned_roles=["cmo"])


def submit_drafts(actor, step_id, expected_version, *, now=None):
    require_owner(actor)
    now = now or datetime.now(timezone.utc)
    with s.connection(write=True) as c:
        row = s.get(c, "plan_step", step_id)
        _require(row["version"] == expected_version, "The work item changed. Reload before starting it.")
        _require(row["step"]["mode"] == "organic" and row["status"] in {"needs_revision", "blocked", "complete"} and row["attempts"] < 3,
                 "This work item cannot start another attempt.")
        if row["status"] == "complete":
            prior = s.get(c, "task", row["task_id"])
            _require(any(s.get(c, artifact["kind"], artifact["id"])["version"] != artifact["version"] for artifact in prior["plan"].get("artifacts", [])),
                     "The accepted draft package has not changed.")
        original = next((task for key in row["task_ids"] if (task := s.get(c, "task", key)).get("production")), None)
        _require(original is not None, "The planned draft package has no complete passing quality check.")
        review = _review_drafts(c, row, original, now, refresh_inputs=True)
        _require(review is not None, "The planned draft package has no complete passing quality check.")
        return s.put(c, "plan_step", {**row, "status": "reviewing", "task_id": review["id"], "task_ids": [*row["task_ids"], review["id"]],
                     "attempts": row["attempts"] + 1, "reason": "CMO is reviewing the checked draft package"},
                     actor=actor, action="plan_drafts_resubmitted", expected_version=expected_version)


def reconcile(now):
    changed = 0
    with s.connection(write=True) as c:
        for row in s.list_items(c, "plan_step"):
            if not row["task_id"] or (row.get("preparation") or {}).get("status") in {"armed", "blocked"}:
                continue
            task = s.get(c, "task", row["task_id"])
            status, reason = task["status"], task["reason"]
            if status == "complete":
                final = task["outputs"][-1] if task["outputs"] else None
                if row["step"]["mode"] == "organic" and task.get("production"):
                    try:
                        review = _review_drafts(c, row, task, now)
                    except MarketingError as exc:
                        if (row["status"], row["reason"]) != ("blocked", str(exc)):
                            s.put(c, "plan_step", {**row, "status": "blocked", "reason": str(exc)}, actor=COORDINATOR,
                                  action="plan_draft_basis_changed", expected_version=row["version"])
                            changed += 1
                        continue
                    if review:
                        s.put(c, "plan_step", {**row, "task_id": review["id"], "task_ids": [*row["task_ids"], review["id"]],
                              "status": "reviewing", "reason": "CMO is reviewing the checked draft package"},
                              actor=COORDINATOR, action="plan_drafts_submitted", expected_version=row["version"])
                        changed += 1
                        continue
                    status, reason = "needs_revision", "The planned draft package has no complete passing quality check."
                elif not final or final["role"] != "cmo" or final["result"]["verdict"] != "accept":
                    status = "needs_revision"
                elif row["step"]["mode"] == "paid_proposal" and not task.get("experiment_ids"):
                    status, reason = "needs_revision", "The planned paid proposal was not produced."
            elif (task.get("plan") or {}).get("phase") == "review" and status in {"queued", "running"}:
                status = "reviewing"
            if (row["status"], row["reason"]) == (status, reason):
                continue
            s.put(c, "plan_step", {**row, "status": status, "reason": reason}, actor=COORDINATOR,
                  action="plan_step_result_recorded", expected_version=row["version"])
            changed += 1
    return changed
