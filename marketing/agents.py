"""Durable bounded model jobs. Each confirmed role result is its own checkpoint."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field

from . import competitors, experiments, founder, goals, occasions, planning, production as pipeline, references, report_decisions, trends, store as s
from .errors import MarketingError, require_owner
from .experiments import Experiment
from .models import Input, Scenario, Strategy
from .permissions import timestamp
from .prompts import ROLE_STEPS, system_prompt
from .production_models import DraftReview, PlatformDraft

COORDINATOR = {"id": "coordinator", "role": "coordinator"}
MAX_ATTEMPTS = 3
LEASE_MINUTES = 15


class RoleResult(Input):
    summary: str = Field(min_length=1, max_length=16000)
    questions: list[str] = Field(default_factory=list, max_length=15)
    risks: list[str] = Field(default_factory=list, max_length=30)
    recommendations: list[str] = Field(default_factory=list, max_length=30)
    verdict: Literal["accept", "revise", "blocked"]
    handoff: str = Field(min_length=1, max_length=5000)
    strategy: Strategy | None = None
    feasibility: list[Scenario] = Field(default_factory=list, max_length=3)
    drafts: list[PlatformDraft] = Field(default_factory=list, max_length=24)
    reviews: list[DraftReview] = Field(default_factory=list, max_length=24)
    experiments: list[Experiment] = Field(default_factory=list, max_length=3)
    reference_cards: list[references.ReferenceCard] = Field(default_factory=list, max_length=12)
    competitor_cards: list[competitors.CompetitorCard] = Field(default_factory=list, max_length=12)
    cmo_review: report_decisions.CMOReview | None = None


def start(actor, **values):
    require_owner(actor)
    with s.connection(write=True) as c:
        return _start_in(c, actor, **values)


def _start_in(c, actor, *, kind, message, evidence_ids=None, conversation_id=None, production=None, report_context=None, trend_ids=None, planning_snapshot_ids=None, plan=None, assigned_roles=None, editorial=None):
    if kind not in ROLE_STEPS or not 1 <= len(message.strip()) <= 12000:
        raise MarketingError("INVALID_TASK", "Choose a task type and enter a brief of at most 12,000 characters.", 422)
    if len(evidence_ids or []) > 30:
        raise MarketingError("TOO_MANY_SOURCES", "Choose at most 30 evidence records.", 422)
    if len(trend_ids or []) > 10:
        raise MarketingError("TOO_MANY_TRENDS", "Choose at most 10 theme observations.", 422)
    if len(planning_snapshot_ids or []) > 10:
        raise MarketingError("TOO_MANY_SNAPSHOTS", "Choose at most 10 report snapshots for planning.", 422)
    if kind == "report" and report_context is None:
        from . import reports, report_activity
        report_context = report_activity.aggregate(reports._calculate(c, None, datetime.now(timezone.utc)))
        report_context.pop("analysis", None)
    scope, accounts = pipeline.scope_context(c, production) if production is not None else (None, [])
    founder_facts = founder.context(c, scope["founder_fact_ids"]) if scope else []
    if scope and kind not in {"content", "draft"}:
        raise MarketingError("PRODUCTION_KIND", "Use a content or drafting task for channel production.", 422)
    task_id = pipeline.task_key(scope) if scope else s.uid("task")
    prior = s.get(c, "task", task_id, required=False)
    if prior:
        return prior
    conversation = s.get(c, "conversation", conversation_id) if conversation_id else {"id": s.uid("conversation"), "messages": [], "version": 0}
    if len(conversation["messages"]) >= 100:
        raise MarketingError("CONVERSATION_LIMIT", "Start a new conversation after 100 messages.")
    sources = [s.get(c, "evidence", key) for key in dict.fromkeys(evidence_ids or [])]
    from .chart_series import validate_scope
    validate_scope(c, scope, sources, datetime.now(timezone.utc))
    occasions.validate_scope(c, scope, sources, datetime.now(timezone.utc))
    trend_versions = {key: s.get(c, "trend", key)["version"] for key in dict.fromkeys(trend_ids or [])}
    trend_context = trends.task_context(c, trend_versions, datetime.now(timezone.utc))
    planning_ids = list(dict.fromkeys(planning_snapshot_ids or []))
    selected_goal = goals.active_goal(c) or s.get(c, "goal", "primary", required=False)
    planning_context = planning.context(c, planning_ids, selected_goal, datetime.now(timezone.utc))
    if len(s.encode(sources)) > 80000:
        raise MarketingError("CONTEXT_TOO_LARGE", "Choose shorter source excerpts for this task.", 422)
    steps = ["cmo", "copywriter", "creative", "quality"] if scope and kind == "draft" else ROLE_STEPS[kind]
    steps = assigned_roles or steps
    task = {"id": task_id, "kind": kind, "title": message.strip()[:160], "message": message.strip(),
            "production": scope, "accounts": accounts, "plan": plan, "editorial": editorial, "founder_facts": founder_facts,
            "report": report_context if kind == "report" else None,
            "paid_creatives": experiments.creative_context(c) if kind in {"experiment", "strategy"} else [],
            "conversation_id": conversation["id"], "conversation": conversation["messages"],
            "goal": selected_goal, "planning_snapshot_ids": planning_ids, "planning_snapshots": planning_context,
            "evidence": sources, "evidence_versions": {e["id"]: e["version"] for e in sources},
            "trend_versions": trend_versions, "trend_context": trend_context,
            "steps": steps, "step": 0, "role": steps[0], "outputs": [],
            "status": "queued", "attempts": 0, "reason": "Waiting for the model worker", "requested_by": actor["id"]}
    saved = s.put(c, "task", task, actor=actor, action="task_requested", expected_version=0)
    s.put(c, "conversation", {**conversation, "messages": [*conversation["messages"], {"role": "coordinator" if actor == COORDINATOR else "owner", "text": task["message"], "task_id": task["id"]}]},
          actor=actor, action="coordinator_message" if actor == COORDINATOR else "owner_message", expected_version=conversation["version"])
    return saved


def _claim(now):
    from . import automation, execution, media
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return None
        # Bound concurrent work across workers, not just browser requests.
        if s.list_items(c, "task", status="running"):
            return None
        for task in automation.order_tasks(list(reversed(s.list_items(c, "task")))):
            if task["status"] not in {"queued", "waiting_assets"}:
                continue
            try:
                occasions.guard(c, task, now)
                execution.guard(c, task, now)
                automation.guard(c, task, now)
            except MarketingError as exc:
                s.put(c, "task", {**task, "status": "blocked", "reason": str(exc)}, actor=COORDINATOR,
                      action="plan_assignment_blocked", expected_version=task["version"])
                continue
            if task.get("production") and task["steps"][task["step"]] == "quality" and media.variants_pending(c, task):
                if task["status"] != "waiting_assets":
                    s.put(c, "task", {**task, "status": "waiting_assets", "reason": "Финальная проверка ожидает готовые медиафайлы. Ошибки рендера доступны в задаче."},
                          actor=COORDINATOR, action="waiting_for_media", expected_version=task["version"])
                continue
            return s.put(c, "task", {**task, "status": "running", "claimed_at": now.isoformat(),
                         "claim_token": s.uid("model"), "attempts": task["attempts"] + 1, "reason": "Model is processing this role"},
                         actor=COORDINATOR, action="role_started", expected_version=task["version"])
    return None


def run_one(model, now):
    task = _claim(now)
    if not task:
        return False
    role = task["steps"][task["step"]]
    context = {key: task[key] for key in ("kind", "message", "conversation", "goal", "evidence", "outputs")}
    context["current_time"] = now.isoformat()
    context.update(production=task.get("production"), accounts=task.get("accounts", []))
    context["founder_facts"] = task.get("founder_facts", [])
    context["report"] = task.get("report")
    context["paid_creatives"] = task.get("paid_creatives", [])
    context["plan"] = task.get("plan")
    context["editorial"] = task.get("editorial")
    with s.connection() as c:
        context["drafts"] = pipeline.drafts_for(c, task["id"])
        context["assets"] = [{key: value for key, value in asset.items() if key != "file_name"}
                             for draft in context["drafts"] for ref in draft.get("assets", [])
                             if (asset := s.get(c, "asset", ref["id"], required=False))]
    try:
        with s.connection() as c:
            context["trend_observations"] = trends.task_context(c, task.get("trend_versions", {}), now)
            context["planning_snapshots"] = planning.context(c, task.get("planning_snapshot_ids", []), task["goal"], now)
            context["strategies"] = [{key: value for key, value in item.items() if key not in {"updated_at"}}
                                      for item in s.list_items(c, "strategy")[:10] if task["goal"] and item["goal_version"] == task["goal"]["version"]]
        raw = model.complete_json(system_prompt(role), s.encode(context), response_schema=RoleResult.model_json_schema(), max_tokens=12000 if task.get("production") else 6000)
        result = RoleResult.model_validate(raw).model_dump(mode="json")
        from . import execution
        execution.validate_output(task, result)
        if len(s.encode(result)) > (80000 if task.get("production") else 40000):
            raise ValueError("Role output too large")
        pipeline.validate_output(task, role, result)
        references.bind(task, role, result, now)
        competitors.bind(task, role, result, now)
        report_decisions.bind(task, role, result, now)
    except Exception as exc:
        with s.connection(write=True) as c:
            current = s.get(c, "task", task["id"])
            if current["status"] == "running" and current.get("claim_token") == task["claim_token"]:
                changed_context = isinstance(exc, MarketingError) and exc.code == "TREND_REVIEW_CHANGED"
                known_failure = isinstance(exc, MarketingError) and exc.code == "REPORT_DECISIONS_INVALID"
                reason = str(exc) if changed_context or known_failure else "Model unavailable or invalid response. Saved inputs and completed roles are preserved."
                s.put(c, "task", {**current, "status": "blocked" if changed_context else "error", "reason": reason},
                      actor={"id": role, "role": role}, action="role_failed", expected_version=current["version"])
        return True
    with s.connection(write=True) as c:
        current = s.get(c, "task", task["id"])
        if current["status"] != "running" or current.get("claim_token") != task["claim_token"]:
            return True
        try:
            from . import automation, execution
            occasions.guard(c, task, max(now, datetime.now(timezone.utc)))
            execution.guard(c, task, max(now, datetime.now(timezone.utc)))
            automation.guard(c, task, max(now, datetime.now(timezone.utc)))
            # A material can arrive while the model is running. Reusing its
            # start-time cut would hide that arrival from the acceptance check.
            trends.task_context(c, task.get("trend_versions", {}), max(now, datetime.now(timezone.utc)))
        except MarketingError as exc:
            s.put(c, "task", {**current, "status": "blocked", "reason": str(exc)}, actor=COORDINATOR,
                  action="theme_observations_changed", expected_version=current["version"])
            return True
        strategy = None
        try:
            if result["feasibility"] or result["strategy"]:
                goal = goals.active_goal(c) or s.get(c, "goal", "primary", required=False)
                if not goal or not task["goal"] or goal["version"] != task["goal"]["version"]:
                    raise MarketingError("STALE_GOAL", "Review the strategy against the current goal first.")
                completed_at = max(now, datetime.now(timezone.utc))
                if result["feasibility"]:
                    result["feasibility_assessment"] = planning.scenarios(c, result["feasibility"], goal, completed_at, task.get("planning_snapshot_ids", []))
                if result["strategy"]:
                    strategy = goals.propose_in(c, {"id": role, "role": role}, result["strategy"], now=completed_at,
                                                allowed_snapshots=task.get("planning_snapshot_ids", []))
        except MarketingError as exc:
            s.put(c, "task", {**current, "status": "blocked", "reason": str(exc)}, actor=COORDINATOR,
                  action="planning_inputs_blocked", expected_version=current["version"])
            return True
        if result["drafts"]:
            pipeline.save_drafts(c, task, result["drafts"])
        experiment_error = None
        try:
            experiment_ids = experiments.record_proposals(c, task, role, result["experiments"])
        except MarketingError:
            experiment_ids = []
            experiment_error = "Paid proposals do not match the current approved goal. Review the saved result against the new goal."
        if role == "creative" and task.get("production"):
            from . import media
            media.request_variants(c, task)
        output = {"role": role, "step": task["step"], "result": result, "at": now.isoformat(), "evidence_versions": task["evidence_versions"], "trend_versions": task.get("trend_versions", {})}
        next_step = task["step"] + 1
        steps = list(task["steps"])
        blocked = result["verdict"] == "blocked" or bool(experiment_error)
        if role == "quality" and result["verdict"] == "revise":
            # Only internal/manual drafting can loop. Automatic content review
            # terminates the job; candidate fact-check failure is terminal too.
            internal = task["production"]["mode"] == "draft" if task.get("production") else task["kind"] == "draft"
            if internal and steps.count("quality") < 3:
                steps.extend(["copywriter", "creative", "quality"] if task.get("production") else ["copywriter", "quality"])
            else:
                blocked = True
        finished = next_step >= len(steps) or blocked
        status = "blocked" if blocked else "complete" if finished else "queued"
        s.put(c, "task", {**current, "outputs": [*current["outputs"], output], "status": status, "step": next_step,
              **({"strategy_id": strategy["id"]} if strategy else {}),
              "steps": steps, "role": role if finished else steps[next_step], "attempts": 0,
              "experiment_ids": [*current.get("experiment_ids", []), *experiment_ids],
              "reason": experiment_error or result["handoff"]}, actor={"id": role, "role": role}, action="role_completed", expected_version=current["version"])
        conversation = s.get(c, "conversation", task["conversation_id"])
        s.put(c, "conversation", {**conversation, "messages": [*conversation["messages"],
              {"role": role, "text": result["summary"], "questions": result["questions"], "task_id": task["id"]}]},
              actor={"id": role, "role": role}, action="role_message", expected_version=conversation["version"])
    if finished and role == "quality" and task.get("production"):
        pipeline.finalize(task["id"], now)
    if task.get("plan"):
        execution.reconcile(max(now, datetime.now(timezone.utc)))
    return True


def retry(actor, task_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        task = s.get(c, "task", task_id)
        if task["status"] != "error" or task["attempts"] >= MAX_ATTEMPTS:
            raise MarketingError("RETRY_UNAVAILABLE", "This task is not retryable or has reached the attempt limit.")
        return s.put(c, "task", {**task, "status": "queued", "reason": "Owner requested retry from the last confirmed step"},
                     actor=actor, action="task_retry", expected_version=expected_version)


def cancel(actor, task_id, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        task = s.get(c, "task", task_id)
        if task["status"] in {"complete", "cancelled"}:
            raise MarketingError("TASK_FINISHED", "This task has already finished.")
        return s.put(c, "task", {**task, "status": "cancelled", "reason": "Cancelled by owner; completed outputs remain available"},
                     actor=actor, action="task_cancelled", expected_version=expected_version)


def recover(now):
    count = 0
    with s.connection(write=True) as c:
        for task in s.list_items(c, "task", status="running"):
            if timestamp(task["claimed_at"]) + timedelta(minutes=LEASE_MINUTES) > now:
                continue
            status = "queued" if task["attempts"] < MAX_ATTEMPTS else "error"
            s.put(c, "task", {**task, "status": status, "reason": "Recovered from the last confirmed role checkpoint"},
                  actor=COORDINATOR, action="task_recovered", expected_version=task["version"])
            count += 1
    return count
