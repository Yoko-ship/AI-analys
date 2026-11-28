"""Reviewable CMO proposals bound to one immutable reporting input."""
from copy import deepcopy
from datetime import date, timedelta
from typing import Literal

from pydantic import Field

from .errors import MarketingError
from .models import Input, PlanRole, PlanText
from .permissions import TASHKENT


class Hypothesis(Input):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    parent_id: str = Field(default="", max_length=80)
    statement: PlanText
    metric_ids: list[str] = Field(min_length=1, max_length=8)
    test_plan: PlanText
    success_metric: str = Field(min_length=1, max_length=100)
    success_criterion: PlanText
    kind: Literal["organic", "measurement", "paid_proposal"]
    priority: Literal["high", "normal", "low"]
    owner: PlanRole
    check_on: date


class Decision(Input):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    action: Literal["continue", "change", "stop"]
    subject: PlanText
    metric_ids: list[str] = Field(min_length=1, max_length=8)
    reason: PlanText
    next_action: PlanText
    owner: PlanRole
    check_on: date
    hypothesis_ids: list[str] = Field(min_length=1, max_length=10)
    strategy_step_ids: list[str] = Field(default_factory=list, max_length=10)


class CMOReview(Input):
    decisions: list[Decision] = Field(min_length=1, max_length=10)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=10)


def _invalid(message):
    raise MarketingError("REPORT_DECISIONS_INVALID", "CMO report: " + message, 422)


def _references(keys, available):
    if len(set(keys)) != len(keys) or not set(keys) <= available:
        _invalid("A proposal references missing or repeated input identifiers")


def bind(task, role, result, now):
    review = result.get("cmo_review")
    eligible = role == "cmo" and task["kind"] == "report" and result["verdict"] == "accept"
    if review is None:
        if eligible:
            _invalid("An accepted result needs decisions and a concrete next test")
        return
    if not eligible or not task.get("report"):
        _invalid("Only an accepted CMO result may supply report decisions")
    report = task["report"]
    metrics = report["metrics"]
    hypotheses = {row["id"]: row for row in review["hypotheses"]}
    decisions = review["decisions"]
    if len(hypotheses) != len(review["hypotheses"]) or len({row["id"] for row in decisions}) != len(decisions):
        _invalid("Proposal identifiers must be unique")
    today = now.astimezone(TASHKENT).date()
    selected = set()
    for row in [*decisions, *hypotheses.values()]:
        _references(row["metric_ids"], metrics.keys())
        selected.update(row["metric_ids"])
        if not today <= date.fromisoformat(row["check_on"]) <= today + timedelta(days=90):
            _invalid("Choose a review date from today through the next 90 days")
    for key, row in hypotheses.items():
        if row["success_metric"] not in metrics:
            _invalid("A hypothesis needs a defined report metric for its test")
        selected.add(row["success_metric"])
        seen = {key}
        parent = row["parent_id"]
        while parent:
            if parent not in hypotheses or parent in seen:
                _invalid("Hypothesis parents must exist and cannot form cycles")
            seen.add(parent)
            parent = hypotheses[parent]["parent_id"]
    steps = {step["id"] for step in (report.get("strategy") or {}).get("steps", [])}
    for row in decisions:
        _references(row["hypothesis_ids"], hypotheses.keys())
        _references(row["strategy_step_ids"], steps)
    review["basis"] = deepcopy({"context_digest": report["context_digest"], "period": report["period"],
        "dataset": report["method"]["dataset"], "goal_version": (report.get("goal") or {}).get("version"),
        "strategy_id": (report.get("strategy") or {}).get("id"), "strategy_version": (report.get("strategy") or {}).get("version"),
        "plan_fact": report["plan_fact"], "metrics": {key: metrics[key] for key in sorted(selected)},
        'experiment_results': report.get('experiment_results', {'items': [], 'total': 0, 'truncated': False})})
