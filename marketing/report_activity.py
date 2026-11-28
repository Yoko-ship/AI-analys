"""Point-in-time owner decisions and team output, separate from business results."""
import json

from . import experiment_review, store as s
from .permissions import timestamp


def revisions(c, kind, cut):
    rows = c.execute("SELECT payload,action FROM marketing_revisions WHERE environment=? AND kind=? ORDER BY created_at,version",
                     (s.environment(), kind)).fetchall()
    return [(record, row["action"]) for row in rows if timestamp((record := json.loads(row["payload"]))["updated_at"]) <= cut]


def latest(c, kind, cut):
    values = {}
    for record, _ in revisions(c, kind, cut):
        values[record["id"]] = record
    return list(values.values())


def coverage_basis(coverage):
    return {source: {'status': basis['status'], 'confirmation': (basis.get('confirmation') or {}).get('id')}
            for source, basis in coverage.items()}


def assessment_basis(value):
    return {**{key: item for key, item in value.items() if key != 'coverage'}, 'coverage': coverage_basis(value.get('coverage', {}))}


def goal_progress(goal, report, end, cut):
    observed = actual = None
    reason = "Нет сопоставимого полного периода, единиц или подтверждённого KPI. Недельная доля цели не назначается автоматически."
    if goal and goal["starts_on"] == report["period"]["starts_on"] and goal["deadline"] == report["period"]["ends_on"]:
        measured = report["metrics"].get(goal["metric"])
        if (measured and measured["unit"] == goal["unit"] and measured["status"] == "complete" and not measured.get("estimate")
                and (measured["unit"] != "currency" or goal["currency"] == report["method"]["currency"])):
            observed = measured["value"]
            if cut >= end:
                actual = observed
                if actual is not None:
                    reason = "План и факт сопоставлены по полному периоду и единицам цели."
        if cut < end:
            reason = "Период ещё не завершён; наблюдаемое значение не сравнивается с полной целью."
    return {"target": goal["target"] if goal else None, "actual": actual, "observed": observed,
            "difference": actual - goal["target"] if actual is not None else None, "reason": reason}


def enrich(c, report, start, end, cut):
    goal = next((r for r, action in reversed(revisions(c, "goal", cut)) if action == "goal_approved"), None)
    plans = [r for r in latest(c, "strategy", cut) if r["status"] == "approved" and goal and r["goal_version"] == goal["version"]]
    plan = plans[-1] if plans else None
    report.update(goal=goal, strategy=plan, plan_fact=goal_progress(goal, report, end, cut))
    counts = {key: set() for key in ("created", "checked", "skipped", "published", "failed", "tasks_completed")}
    skipped = {}
    for kind in ("candidate", "delivery", "task"):
        for record, action in revisions(c, kind, cut):
            if not start <= timestamp(record["updated_at"]) < end:
                continue
            key = record["id"]
            if kind == "candidate":
                if action == "candidate_created":
                    counts["created"].add(key)
                if action == "final_check":
                    counts["checked"].add(key)
                if record["status"] == "skipped":
                    counts["skipped"].add(key)
                    skipped[key] = {"id": key, "title": record.get("title", key), "reason": record.get("check", {}).get("reason", ""), "version": record["version"]}
            elif kind == "delivery":
                if action == "dispatch_published" and record.get("external_id"):
                    counts["published"].add(key)
                if record["status"] in {"error", "unknown"}:
                    counts["failed"].add(key)
            elif action == "role_completed" and record["status"] == "complete":
                counts["tasks_completed"].add(key)
    report["team"] = {**{key: len(values) for key, values in counts.items()}, "skipped_items": list(skipped.values())}
    report['experiment_results'] = experiment_review.context(c, report['method']['dataset'], start, end, cut)
    report["context_digest"] = s.digest({"period": [report["period"][key] for key in ("starts_on", "ends_on")],
        "method": report["method"], "input": report["input_digest"], "sources": report["sources"], "goal": goal, "strategy": plan,
        "plan_fact": report["plan_fact"],
        'experiment_results': report['experiment_results'],
        'publication_attribution': assessment_basis(report.get('publication_attribution', {})),
        'count_basis': {key: assessment_basis(value) for key, value in report.get('count_basis', {}).items()},
        'metric_basis': {key: {'value': metric['value'], 'status': metric['status'], 'coverage': coverage_basis(metric.get('coverage', {}))}
                         for key, metric in report['metrics'].items()}})
    review_key = review_id(report["method"]["dataset"], report["period"])
    report["review"] = next((r for r in latest(c, "report_review", cut) if r["id"] == review_key), {"version": 0, "decisions": "", "next_actions": ""})
    analysis = next((r for r in reversed(latest(c, "task", cut)) if r["kind"] == "report" and (r.get("report") or {}).get("context_digest") == report["context_digest"]), None)
    report["analysis"] = {"task_id": analysis["id"], "status": analysis["status"], **{o["role"]: o["result"] for o in analysis["outputs"]}} if analysis else None


def review_id(dataset, period):
    return s.digest([dataset, period["starts_on"], period["ends_on"]])


def aggregate(report):
    result = {key: value for key, value in report.items() if key not in {"input_event_ids", "excluded_financial_events"}}
    if 'financial_issues' in result:
        result['financial_issues'] = [{key: issue[key] for key in ('code', 'message', 'entities', 'metrics')}
                                      for issue in result['financial_issues']]
    return result
