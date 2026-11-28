"""Reviewable strategy constraints and conditional projections from measured cuts."""
from datetime import date, datetime, time
from decimal import Decimal
import math

from . import report_activity, reports, store as s
from .errors import MarketingError
from .permissions import TASHKENT, timestamp

SCENARIOS = {"conservative", "base", "target"}
BOUNDED_RATES = {"visit_to_registration", "activation", "registration_to_payment", "ctr", "retention", "churn"}


def _require(condition, message):
    if not condition:
        raise MarketingError("INVALID_STRATEGY", message, 422)


def _inside(value, goal):
    return goal["starts_on"] <= value <= goal["deadline"]


def _metric_basis(metric):
    # The comparison cut advances; the measured period and relevant proof must
    # remain the same. Unrelated later ledger events are not forecast inputs.
    value = {key: item for key, item in metric.items() if key != "period"}
    if "coverage" in value:
        value["coverage"] = report_activity.coverage_basis(value["coverage"])
    if "attribution" in value:
        value["attribution"] = report_activity.assessment_basis(value["attribution"])
    return value


def measured_basis(c, snapshot_id, goal, now, allowed=None):
    _require(allowed is None or snapshot_id in allowed, "A projection must use a selected report snapshot.")
    snapshot = s.get(c, "snapshot", snapshot_id)
    report = snapshot["report"]
    period, key = report["period"], goal["metric"]
    metric = report["metrics"].get(key, {})
    _require(snapshot.get("status") == "frozen" and report.get("input_digest"), "Use a measured report snapshot from the reporting ledger.")
    _require(metric.get("status") == "complete" and metric.get("value") is not None and not metric.get("estimate"),
             "A numerical scenario needs a complete measured KPI, not an estimate or missing input.")
    _require(metric["unit"] == goal["unit"] and (metric["unit"] != "currency" or metric.get("currency") == goal["currency"]),
             "The scenario baseline and goal must use the same KPI units and currency.")
    duration = date.fromisoformat(period["ends_on"]) - date.fromisoformat(period["starts_on"])
    _require(duration == date.fromisoformat(goal["deadline"]) - date.fromisoformat(goal["starts_on"]),
             "Use a baseline with the same observation duration as the goal; no automatic extrapolation.")
    end = datetime.combine(date.fromisoformat(period["ends_on"]), time(), TASHKENT)
    _require(end <= timestamp(period["cutoff"]) <= now, "The baseline observation window must be complete and in the past.")
    _require(not s.get(c, "snapshot_correction", snapshot_id, required=False), "Recalculate a corrected snapshot before using it in a strategy.")
    current = reports._calculate(c, {key: period[key] for key in ("starts_on", "ends_on")}, now)
    _require(report["method"] == current["method"] and _metric_basis(metric) == _metric_basis(current["metrics"].get(key, {})),
             "The measured baseline or its definitions changed. Recalculate it and prepare a new proposal.")
    return {"snapshot_id": snapshot_id, "snapshot_version": snapshot["version"], "name": snapshot["name"],
            "baseline": metric["value"], "metric": key, "unit": metric["unit"], "currency": metric.get("currency"),
            "period": period, "sources": metric.get("source_ids", []), "dataset": report["method"]["dataset"],
            "basis_digest": s.digest([report["method"], _metric_basis(metric)])}


def scenarios(c, rows, goal, now, allowed=None):
    _require(len(rows) == 3 and {row["kind"] for row in rows} == SCENARIOS, "Include conservative, base and target scenarios exactly once.")
    evaluated, cache = [], {}
    for row in rows:
        _require(_inside(row["checkpoint"], goal), "Scenario checkpoints must stay inside the goal period.")
        _require(Decimal(str(row["budget"])) <= Decimal(str(goal["budget"])), "A scenario exceeds the approved budget.")
        projection = None
        if row["projection"]:
            selected = row["projection"]
            key = selected["snapshot_id"]
            if key not in cache:
                cache[key] = measured_basis(c, key, goal, now, allowed)
            basis = cache[key]
            value = float(Decimal(str(basis["baseline"])) * Decimal(str(selected["factor"])))
            _require(math.isfinite(value) and (goal["metric"] not in BOUNDED_RATES or 0 <= value <= 100),
                     "The conditional result exceeds the KPI's valid range.")
            projection = {**basis, "value": value, "factor": selected["factor"], "assumption": selected["assumption"],
                          "formula": "measured baseline × assumed factor", "status": "conditional"}
        evaluated.append({"kind": row["kind"], "projection": projection})
    return evaluated


def evaluate(c, value, goal, now, allowed=None):
    _require(goal and value["goal_version"] == goal["version"], "A strategy must reference the current approved goal.")
    steps = {row["id"]: row for row in value["steps"]}
    _require(len(steps) == len(value["steps"]), "Strategy step identifiers must be unique.")
    for key, row in steps.items():
        _require(_inside(row["starts_on"], goal) and _inside(row["due"], goal) and row["starts_on"] <= row["due"],
                 "Every step must have ordered dates inside the goal period.")
        _require(len(set(row["dependencies"])) == len(row["dependencies"]) and all(dep in steps and dep != key for dep in row["dependencies"]),
                 "Every dependency must name another step in this plan exactly once.")
        _require(row["channel"] == "internal" or row["channel"] in value["channels"], "A step references an unplanned channel.")
        _require(not row["rubric"] or row["rubric"] in value["rubrics"], "A step references an unplanned rubric.")
        _require(row["mode"] not in {"organic", "paid_proposal"} or row["channel"] != "internal", "Channel actions need a planned platform.")
        _require(row["mode"] != "organic" or bool(row["rubric"]), "An organic content step needs a planned rubric.")
    visited, path = set(), set()

    def visit(key):
        _require(key not in path, "Strategy dependencies cannot form a cycle.")
        if key in visited:
            return
        path.add(key)
        for dependency in steps[key]["dependencies"]:
            visit(dependency)
            _require(steps[dependency]["due"] <= steps[key]["starts_on"], "A prerequisite must finish before its dependent step starts.")
        path.remove(key)
        visited.add(key)

    for key in steps:
        visit(key)
    total = sum((Decimal(str(row["budget"])) for row in steps.values()), Decimal(0))
    _require(total <= Decimal(str(goal["budget"])), "The proposed steps exceed the approved budget.")
    metrics = {row["metric"]: row for row in value["kpis"]}
    _require(len(metrics) == len(value["kpis"]) and goal["metric"] in metrics, "List each KPI once and include the owner's KPI.")
    primary = metrics[goal["metric"]]
    _require(all(primary[key] == goal[key] for key in ("formula", "unit", "source", "target")) and primary["checkpoint"] == goal["deadline"],
             "The strategy cannot change the owner's KPI, source, target or deadline.")
    _require(all(_inside(row["checkpoint"], goal) for row in metrics.values()), "KPI checkpoints must stay inside the goal period.")
    budget_per_target = float(Decimal(str(goal["budget"])) / Decimal(str(goal["target"])))
    _require(math.isfinite(budget_per_target), "The budget per target must be a finite planning amount.")
    return {"contract_version": 1, "planned_budget": float(total), "currency": goal["currency"],
            "budget_per_target": budget_per_target,
            "scenarios": scenarios(c, value["scenarios"], goal, now, allowed)}


def context(c, snapshot_ids, goal, now):
    values = []
    for key in snapshot_ids:
        snapshot = s.get(c, "snapshot", key)
        try:
            _require(bool(goal), "Choose a goal before using numerical scenarios.")
            basis = measured_basis(c, key, goal, now)
            values.append({**basis, "eligible": True})
        except MarketingError as exc:
            values.append({"snapshot_id": key, "name": snapshot["name"], "period": snapshot["report"]["period"],
                           "eligible": False, "baseline": None, "reason": str(exc)})
    return values
