"""An owner approves the complete, bounded plan, not an opaque model paragraph."""
from copy import deepcopy
from datetime import timedelta

import pytest

from marketing import goals, reports, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, CMO, NOW, goal_input, isolated  # noqa: F401


def step(key="measure", **changes):
    return {"id": key, "owner": "analytics", "action": "Measure confirmed report opens",
            "deliverable": "Dated baseline with a source", "starts_on": "2026-11-23", "due": "2026-11-25",
            "budget": 0, "dependencies": [], "channel": "internal", "rubric": "", "mode": "measurement", **changes}


def scenario(kind, **changes):
    return {"kind": kind, "assumptions": ["Audience response is unmeasured"],
            "actions": ["Measure first, then compare one format"], "resources": "Analyst and existing channel",
            "budget": 0, "constraints": ["No assumed payment launch"], "risks": ["Small sample"],
            "checkpoint": "2026-11-25", "formula": "Observed reach * measured opening rate",
            "measurement_plan": "Collect comparable observations before a numerical projection", "projection": None, **changes}


def proposal(**changes):
    goal = goal_input()
    return {"title": "Source-backed weekly plan", "goal_version": 2, "segments": ["Investors"],
            "positioning": "Explain the original data", "channels": ["telegram"], "rubrics": ["quarterly"],
            "steps": [step()], "measurement": "Confirmed report opens, one cohort and window",
            "risks": ["No measured baseline"], "allowed_changes": ["Prioritize tasks within this calendar"],
            "assumptions": ["No paid action without a separate decision"],
            "kpis": [{"metric": goal["metric"], "formula": goal["formula"], "unit": goal["unit"],
                      "source": goal["source"], "target": goal["target"], "owner": "analytics", "checkpoint": goal["deadline"]}],
            "scenarios": [scenario(kind) for kind in ("conservative", "base", "target")], **changes}


def approve_goal(**changes):
    goal = goals.save_goal(OWNER, goal_input(**changes), 0)
    return goals.approve_goal(OWNER, goal["version"])


def save(data=None):
    return goals.save_strategy(CMO, data or proposal(), now=NOW)


def test_full_plan_has_three_explicit_scenarios_and_budget_per_target_is_not_actual_cac():
    approve_goal(budget=3000000)
    saved = save()
    assert saved["assessment"]["planned_budget"] == 0
    assert saved["assessment"]["budget_per_target"] == 30000
    assert all(row["projection"] is None for row in saved["assessment"]["scenarios"])
    assert {row["kind"] for row in saved["scenarios"]} == {"conservative", "base", "target"}
    approved = goals.approve_strategy(OWNER, saved["id"], saved["version"], now=NOW)
    assert approved["status"] == "approved"
    with pytest.raises(MarketingError):
        goals.approve_strategy(OWNER, approved["id"], approved["version"], now=NOW)
    with store.connection() as c:
        assert store.revision(c, "strategy", saved["id"], 1)["status"] == "proposed"
        assert store.list_items(c, "delivery") == []


@pytest.mark.parametrize("case", ["negative_budget", "negative_scenario", "missing_dependency", "cycle", "duplicate_id",
                                  "backwards_dates", "outside_goal", "dependency_not_ready", "unknown_role",
                                  "unplanned_channel", "unplanned_rubric", "missing_scenario", "duplicate_scenario", "changed_kpi"])
def test_invalid_plan_cannot_reach_owner_approval(case):
    approve_goal(budget=100)
    value = proposal()
    if case == "negative_budget":
        value["steps"] = [step(budget=200), step("hide-overrun", budget=-100)]
    elif case == "negative_scenario":
        value["scenarios"][0]["budget"] = -100
    elif case == "missing_dependency":
        value["steps"][0]["dependencies"] = ["not-in-plan"]
    elif case == "cycle":
        value["steps"] = [step("a", dependencies=["b"]), step("b", dependencies=["a"])]
    elif case == "duplicate_id":
        value["steps"].append(step())
    elif case == "backwards_dates":
        value["steps"][0]["due"] = "2026-11-22"
    elif case == "outside_goal":
        value["scenarios"][0]["checkpoint"] = "2027-01-01"
    elif case == "dependency_not_ready":
        value["steps"] = [step("data", due="2026-11-29"), step("draft", dependencies=["data"])]
    elif case == "unknown_role":
        value["steps"][0]["owner"] = "someone"
    elif case == "unplanned_channel":
        value["steps"][0].update(channel="instagram", mode="organic", rubric="quarterly")
    elif case == "unplanned_rubric":
        value["steps"][0].update(channel="telegram", mode="organic", rubric="news")
    elif case == "missing_scenario":
        value["scenarios"].pop()
    elif case == "duplicate_scenario":
        value["scenarios"][0]["kind"] = "base"
    else:
        value["kpis"][0]["target"] = 200
    with pytest.raises((MarketingError, ValueError)):
        save(value)


def test_step_budget_uses_decimal_totals_and_scenarios_are_alternative_not_additive():
    approve_goal(budget=0.3)
    value = proposal(steps=[step("a", budget=0.1), step("b", budget=0.2)],
                     scenarios=[scenario(kind, budget=0.3) for kind in ("conservative", "base", "target")])
    assert save(value)["assessment"]["planned_budget"] == 0.3
    value["scenarios"][0]["budget"] = 0.31
    with pytest.raises(MarketingError):
        save(value)


def test_legacy_incomplete_record_cannot_bypass_new_checks_at_approval():
    approve_goal()
    value = proposal()
    value.pop("kpis")
    value["scenarios"] = []
    with store.connection(write=True) as c:
        legacy = store.put(c, "strategy", {**value, "id": "legacy", "status": "proposed"},
                           actor=CMO, action="legacy_fixture", expected_version=0)
    with pytest.raises(MarketingError):
        goals.approve_strategy(OWNER, legacy["id"], legacy["version"], now=NOW)


def measured_snapshot(*, complete=True, count=2):
    settings = reports.save_settings(OWNER, {"dataset": "test"}, 0)
    events = [{"id": str(i), "kind": "registration", "subject_id": f"reader-{i}", "channel": "direct", "dataset": "test",
               "at": "2025-01-07T08:00:00Z", "source": "typed-registration-ledger", "confirmed": True} for i in range(count)]
    coverage = [{"dataset": "test", "categories": ["registrations"], "starts_on": "2025-01-06", "ends_on": "2025-01-13",
                 "through": NOW.isoformat(), "history_complete": True, "status": "complete", "reference": "Reconciled registration inventory"}] if complete else []
    reports.import_events(OWNER, events, coverage, now=NOW)
    return reports.freeze(OWNER, "Measured complete week", {"starts_on": "2025-01-06", "ends_on": "2025-01-13"}, settings["version"], now=NOW)


def measured_plan(snapshot):
    goal = approve_goal(metric="registrations", unit="users", deadline="2026-11-30")
    value = proposal()
    value["kpis"][0].update(metric=goal["metric"], unit=goal["unit"], checkpoint=goal["deadline"])
    for row, factor in zip(value["scenarios"], (0.5, 1, 1.5)):
        row["projection"] = {"snapshot_id": snapshot["id"], "factor": factor,
                             "assumption": "Conditional change in response for the same seven-day horizon"}
    return value


def test_numeric_scenarios_use_comparable_measured_snapshot_and_server_arithmetic():
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    saved = save(value)
    measured = saved["assessment"]["scenarios"]
    assert [row["projection"]["value"] for row in measured] == [1, 2, 3]
    assert all(row["projection"]["baseline"] == 2 and row["projection"]["snapshot_id"] == snapshot["id"] for row in measured)
    assert measured[0]["projection"]["period"]["starts_on"] == "2025-01-06"
    assert measured[0]["projection"]["sources"] == ["typed-registration-ledger"]
    value["scenarios"][0]["projection"]["value"] = 100
    with pytest.raises((MarketingError, ValueError)):
        save(value)


def test_incomplete_baseline_cannot_become_a_numeric_forecast():
    snapshot = measured_snapshot(complete=False)
    with pytest.raises(MarketingError):
        save(measured_plan(snapshot))


def test_changed_measurement_blocks_approval_and_preserves_proposed_numbers():
    snapshot = measured_snapshot()
    saved = save(measured_plan(snapshot))
    reports.import_events(OWNER, [{"id": "late", "kind": "registration", "subject_id": "late-reader", "channel": "direct", "dataset": "test",
                                  "at": "2025-01-08T08:00:00Z", "source": "typed-registration-ledger", "confirmed": True}], [], now=NOW + timedelta(seconds=1))
    with pytest.raises(MarketingError):
        goals.approve_strategy(OWNER, saved["id"], saved["version"], now=NOW + timedelta(seconds=2))
    with store.connection() as c:
        assert store.get(c, "strategy", saved["id"])["assessment"]["scenarios"][1]["projection"]["value"] == 2


@pytest.mark.parametrize("changes", [{"deadline": "2026-12-23"}, {"unit": "visits"}])
def test_scenario_cannot_extrapolate_incomparable_goal_period_or_unit(changes):
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    current = goals.active_goal()
    changed = goals.save_goal(OWNER, {key: current[key] for key in goal_input()} | changes, current["version"])
    current = goals.approve_goal(OWNER, changed["version"])
    value["goal_version"] = current["version"]
    value["kpis"][0].update(unit=current["unit"], checkpoint=current["deadline"])
    with pytest.raises(MarketingError):
        save(value)


def test_complete_zero_is_a_measured_baseline_and_does_not_invent_growth():
    snapshot = measured_snapshot(count=0)
    saved = save(measured_plan(snapshot))
    assert all(row["projection"]["value"] == 0 for row in saved["assessment"]["scenarios"])


def test_percentage_scenario_stops_at_the_kpi_boundary():
    from test_marketing_analytics import event
    settings = reports.save_settings(OWNER, {"dataset": "test"}, 0)
    rows = [event("shown", "impression", at="2025-01-07T08:00:00Z", publication_id="post-a", channel="telegram", count=20),
            event("clicked", "click", at="2025-01-07T08:00:00Z", publication_id="post-a", channel="telegram", count=10)]
    reports.import_events(OWNER, rows, [{"dataset": "test", "categories": ["impressions", "clicks"], "starts_on": "2025-01-06",
        "ends_on": "2025-01-13", "through": NOW.isoformat(), "history_complete": True, "status": "complete", "reference": "Matched full platform window"}], now=NOW)
    snapshot = reports.freeze(OWNER, "Measured click rate", {"starts_on": "2025-01-06", "ends_on": "2025-01-13"}, settings["version"], now=NOW)
    assert snapshot["report"]["metrics"]["ctr"]["value"] == 50
    goal = approve_goal(metric="ctr", unit="percent", deadline="2026-11-30")
    value = proposal()
    value["kpis"][0].update(metric=goal["metric"], unit=goal["unit"], checkpoint=goal["deadline"])
    value["scenarios"][2]["projection"] = {"snapshot_id": snapshot["id"], "factor": 2, "assumption": "Conditional doubled rate"}
    assert save(value)["assessment"]["scenarios"][2]["projection"]["value"] == 100
    value["scenarios"][2]["projection"]["factor"] = 3
    with pytest.raises(MarketingError, match="valid range"):
        save(value)


def test_unrelated_later_registrations_do_not_invalidate_a_closed_baseline():
    saved = save(measured_plan(measured_snapshot()))
    reports.import_events(OWNER, [{"id": "later", "kind": "registration", "subject_id": "later-reader", "channel": "direct", "dataset": "test",
                                  "at": "2025-01-20T08:00:00Z", "source": "typed-registration-ledger", "confirmed": True}], [], now=NOW + timedelta(seconds=1))
    approved = goals.approve_strategy(OWNER, saved["id"], saved["version"], now=NOW + timedelta(seconds=2))
    assert approved["assessment"] == saved["assessment"] and approved["status"] == "approved"


def test_approval_history_survives_when_current_measurement_settings_invalidate_the_basis():
    saved = save(measured_plan(measured_snapshot()))
    approved = goals.approve_strategy(OWNER, saved["id"], saved["version"], now=NOW)
    reports.save_settings(OWNER, {"dataset": "production"}, 1)
    with store.connection() as c:
        current = goals.current_strategy(c, approved, NOW + timedelta(seconds=1))
        assert current["status"] == "approved" and current["readiness"]["status"] == "blocked"
        assert store.revision(c, "strategy", saved["id"], 2)["assessment"] == saved["assessment"]


def test_finite_inputs_cannot_produce_nonfinite_budget_per_target():
    approve_goal(budget=1e308, target=1e-308)
    value = proposal()
    value["kpis"][0]["target"] = 1e-308
    with pytest.raises(MarketingError):
        save(value)


def test_cmo_receives_selected_measurement_and_saves_an_atomic_reviewable_proposal():
    from marketing import agents
    from test_marketing_agents import Model, output
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    task = agents.start(OWNER, kind="strategy", message="Prepare the full plan", planning_snapshot_ids=[snapshot["id"]])
    model = Model([output("Hand off the measured context") for _ in range(4)] + [output("Complete strategy", strategy=value)])
    for _ in range(5):
        agents.run_one(model, NOW)
    basis = model.calls[-1][1]["planning_snapshots"][0]
    assert basis["eligible"] and basis["baseline"] == 2 and basis["snapshot_id"] == snapshot["id"]
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete"
        plan = store.get(c, "strategy", saved["strategy_id"])
        assert plan["status"] == "proposed" and plan["assessment"]["scenarios"][2]["projection"]["value"] == 3


def test_unselected_snapshot_cannot_enter_model_proposal():
    from marketing import agents
    from test_marketing_agents import Model, output
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    task = agents.start(OWNER, kind="dialogue", message="Discuss the plan")
    agents.run_one(Model([output("Unselected baseline", strategy=value)]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
        assert store.list_items(c, "strategy") == []


@pytest.mark.parametrize("case", ["missing_full_strategy", "non_cmo", "unaccepted_strategy"])
def test_role_contract_cannot_claim_a_completed_strategy_without_accepted_cmo_plan(case):
    from marketing import agents
    from test_marketing_agents import Model, output
    approve_goal()
    task = agents.start(OWNER, kind="strategy" if case != "unaccepted_strategy" else "dialogue", message="Prepare the full strategy")
    if case == "missing_full_strategy":
        model = Model([output("Planning handoff") for _ in range(5)])
        for _ in range(5):
            agents.run_one(model, NOW)
    else:
        agents.run_one(Model([output("Unaccepted plan", strategy=proposal(), verdict="blocked" if case == "unaccepted_strategy" else "accept")]), NOW)
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "error"
        assert store.list_items(c, "strategy") == []


def test_pre_strategy_dialogue_can_show_three_formula_scenarios_without_approving_goal():
    from marketing import agents
    from test_marketing_agents import Model, output
    draft = goals.save_goal(OWNER, goal_input(), 0)
    task = agents.start(OWNER, kind="dialogue", message="Assess feasibility before I commit")
    agents.run_one(Model([output("Measure before forecasting", feasibility=proposal()["scenarios"])]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete"
        assert len(saved["outputs"][0]["result"]["feasibility_assessment"]) == 3
        assert store.get(c, "goal", "primary") == draft
        assert store.list_items(c, "strategy") == []


def test_changed_goal_during_cmo_call_does_not_leave_a_false_completed_handoff():
    from marketing import agents
    from test_marketing_agents import Model, output
    approve_goal()
    task = agents.start(OWNER, kind="dialogue", message="Propose a plan for this goal")

    class ChangingGoal(Model):
        def complete_json(self, *args, **kwargs):
            changed = goals.save_goal(OWNER, goal_input(target=200), 2)
            goals.approve_goal(OWNER, changed["version"])
            return super().complete_json(*args, **kwargs)

    agents.run_one(ChangingGoal([output("Obsolete plan", strategy=proposal())]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
        assert store.list_items(c, "strategy") == []


def test_measurement_arriving_during_reasoning_is_checked_at_completion(monkeypatch):
    from marketing import agents
    from test_marketing_agents import Model, output
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    task = agents.start(OWNER, kind="dialogue", message="Use the selected measured baseline", planning_snapshot_ids=[snapshot["id"]])
    finished = NOW + timedelta(minutes=1)

    class Clock:
        @staticmethod
        def now(tz):
            return finished

    class ModelWithArrival(Model):
        def complete_json(self, *args, **kwargs):
            reports.import_events(OWNER, [{"id": "late", "kind": "registration", "subject_id": "late-reader", "channel": "direct", "dataset": "test",
                                          "at": "2025-01-08T08:00:00Z", "source": "typed-registration-ledger", "confirmed": True}], [], now=finished)
            return super().complete_json(*args, **kwargs)

    monkeypatch.setattr(agents, "datetime", Clock)
    model = ModelWithArrival([output("The old projection is obsolete", strategy=value)])
    agents.run_one(model, NOW)
    assert model.calls[0][1]["planning_snapshots"][0]["eligible"]
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
        assert store.list_items(c, "strategy") == []
