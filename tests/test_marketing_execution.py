"""The coordinator tracks approved work and accepts actual saved handoffs."""
from datetime import timedelta

import pytest

from marketing import agents, goals, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, NOW, isolated  # noqa: F401
from test_marketing_strategy import approve_goal, proposal, step
from test_marketing_agents import Model, output


@pytest.fixture(autouse=True)
def model_clock(monkeypatch):
    class Clock:
        @staticmethod
        def now(tz):
            return NOW
    monkeypatch.setattr(agents, "datetime", Clock)


def approved_plan():
    approve_goal()
    value = proposal(steps=[
        step("brief", owner="pr", mode="operations", action="Prepare the editorial brief", deliverable="Dated brand brief", due="2026-11-23"),
        step("research", owner="market", mode="research", action="Research the brief", starts_on="2026-11-24", due="2026-11-25", dependencies=["brief"]),
    ])
    saved = goals.save_strategy(OWNER, value, now=NOW)
    return goals.approve_strategy(OWNER, saved["id"], saved["version"], now=NOW)


def activate(plan):
    from marketing import execution
    return execution.activate(OWNER, plan["id"], plan["version"], now=NOW)


def item(run, key):
    from marketing import execution
    with store.connection() as c:
        return next(row for row in execution.current(c, run, NOW)["items"] if row["step"]["id"] == key)


def launch(row, *, now=NOW):
    from marketing import execution
    return execution.launch(OWNER, row["id"], row["version"], {}, now=now)


def test_activation_pins_approved_plan_and_is_idempotent_without_creating_publications():
    plan = approved_plan()
    run = activate(plan)
    again = activate(plan)
    assert again["id"] == run["id"] and again["version"] == run["version"]
    assert run["strategy_version"] == plan["version"] and run["status"] == "active"
    first, second = item(run, "brief"), item(run, "research")
    assert first["readiness"]["status"] == "ready"
    assert second["readiness"]["status"] == "blocked" and first["id"] in second["dependencies"]
    with store.connection() as c:
        assert len(store.list_items(c, "plan_step")) == 2
        assert not store.list_items(c, "task") and not store.list_items(c, "delivery")


def test_unapproved_plan_and_agent_actor_cannot_activate_work():
    from marketing import execution
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(), now=NOW)
    with pytest.raises(MarketingError):
        activate(plan)
    approved = goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW)
    with pytest.raises(MarketingError):
        execution.activate({"id": "cmo", "role": "cmo"}, approved["id"], approved["version"], now=NOW)


def test_activating_a_revised_strategy_stops_old_assignments_without_erasing_them():
    from marketing import execution
    plan = approved_plan()
    run = activate(plan)
    old_task = launch(item(run, "brief"))
    revised = goals.save_strategy(OWNER, proposal(title="Revised work order"), plan["id"], plan["version"], now=NOW)
    approved = goals.approve_strategy(OWNER, revised["id"], revised["version"], now=NOW)
    replacement = activate(approved)
    assert replacement["id"] != run["id"]
    with store.connection() as c:
        old = store.get(c, "plan_run", run["id"])
        assert old["status"] == "paused"
    with pytest.raises(MarketingError):
        execution.set_paused(OWNER, old["id"], old["version"], False)
    unused = Model([])
    agents.run_one(unused, NOW)
    assert not unused.calls
    with store.connection() as c:
        assert store.get(c, "task", old_task["id"])["status"] == "blocked"


def test_dependency_needs_a_completed_accepted_cmo_handoff_and_start_date():
    from marketing import execution
    run = activate(approved_plan())
    with pytest.raises(MarketingError):
        launch(item(run, "research"))
    task = launch(item(run, "brief"))
    assert task["steps"] == ["pr", "cmo"]
    model = Model([output("Brief with bounded positioning"), output("The brief meets the approved deliverable")])
    agents.run_one(model, NOW)
    assert item(run, "brief")["status"] != "complete"
    agents.run_one(model, NOW)
    execution.reconcile(NOW)
    assert item(run, "brief")["status"] == "complete"
    with pytest.raises(MarketingError):
        launch(item(run, "research"))
    next_task = launch(item(run, "research"), now=NOW + timedelta(days=1))
    assert next_task["steps"][0] == "market"
    assert next_task["plan"]["prerequisites"][0]["task_id"] == task["id"]
    assert "Brief with bounded positioning" in str(next_task["plan"]["prerequisites"])


def test_launch_is_atomic_and_cannot_duplicate_work_on_double_click():
    run = activate(approved_plan())
    row = item(run, "brief")
    first = launch(row)
    with pytest.raises(MarketingError):
        launch(row)
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 1
        assert store.get(c, "plan_step", row["id"])["task_id"] == first["id"]


def test_cmo_revision_does_not_unlock_a_dependent_and_history_is_retained():
    from marketing import execution
    run = activate(approved_plan())
    first = launch(item(run, "brief"))
    model = Model([output("Draft brief"), output("State the product limit clearly", verdict="revise")])
    agents.run_one(model, NOW)
    agents.run_one(model, NOW)
    execution.reconcile(NOW)
    revised = item(run, "brief")
    assert revised["status"] == "needs_revision"
    assert item(run, "research")["readiness"]["status"] == "blocked"
    retry = launch(revised)
    assert retry["id"] != first["id"] and retry["plan"]["previous_task_id"] == first["id"]
    assert "State the product limit clearly" in str(retry["plan"]["revision_feedback"])


def test_goal_change_before_claim_blocks_the_task_without_calling_model():
    from test_marketing_core import goal_input
    run = activate(approved_plan())
    task = launch(item(run, "brief"))
    draft = goals.save_goal(OWNER, goal_input(target=200), 2)
    goals.approve_goal(OWNER, draft["version"])
    unused = Model([])
    agents.run_one(unused, NOW)
    assert unused.calls == []
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "blocked"


def test_goal_change_during_model_work_cannot_complete_the_plan_step():
    from marketing import execution
    from test_marketing_core import goal_input
    run = activate(approved_plan())
    task = launch(item(run, "brief"))

    class ChangedGoal(Model):
        def complete_json(self, *args, **kwargs):
            draft = goals.save_goal(OWNER, goal_input(target=200), 2)
            goals.approve_goal(OWNER, draft["version"])
            return super().complete_json(*args, **kwargs)

    agents.run_one(ChangedGoal([output("Old brief is no longer current")]), NOW)
    execution.reconcile(NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "blocked" and not saved["outputs"]
    assert item(run, "brief")["status"] == "blocked"


def test_calendar_exposes_overdue_work_without_claiming_it_completed():
    from marketing import execution
    run = activate(approved_plan())
    with store.connection() as c:
        current = execution.current(c, run, NOW + timedelta(days=2))
    first = next(row for row in current["items"] if row["step"]["id"] == "brief")
    assert first["overdue"] and first["status"] == "pending" and first["step"]["owner"] == "pr"


def test_expired_goal_period_blocks_new_work_instead_of_silently_extending_it():
    from marketing import execution
    run = activate(approved_plan())
    with pytest.raises(MarketingError):
        launch(item(run, "brief"), now=NOW + timedelta(days=40))
    with store.connection() as c:
        assert execution.current(c, run, NOW + timedelta(days=40))["items"][0]["readiness"]["status"] == "blocked"


def test_changed_selected_source_blocks_a_saved_assignment_before_model_work():
    from marketing import content, execution
    from marketing.models import Evidence
    from test_marketing_core import evidence
    run = activate(approved_plan())
    selected = evidence(expires_at="2027-01-01T00:00:00Z")
    row = item(run, "brief")
    task = execution.launch(OWNER, row["id"], row["version"], {"evidence_ids": [selected["id"]]}, now=NOW)
    content.save_evidence(OWNER, selected["id"], {key: selected[key] for key in Evidence.model_fields} | {"excerpt": "A corrected original"}, selected["version"])
    model = Model([])
    agents.run_one(model, NOW)
    assert not model.calls
    with store.connection() as c:
        assert store.get(c, "task", task["id"])["status"] == "blocked"


def test_plan_pause_does_not_delete_outputs_and_resume_requires_a_current_assignment():
    from marketing import execution
    run = activate(approved_plan())
    task = launch(item(run, "brief"))
    paused = execution.set_paused(OWNER, run["id"], run["version"], True)
    model = Model([])
    agents.run_one(model, NOW)
    execution.reconcile(NOW)
    assert not model.calls and item(run, "brief")["status"] == "blocked"
    execution.set_paused(OWNER, run["id"], paused["version"], False)
    restarted = launch(item(run, "brief"))
    assert restarted["id"] != task["id"]
    with store.connection() as c:
        assert len(store.history(c, "plan_run", run["id"])) == 3


def test_owner_step_needs_owner_evidence_and_unlocks_the_actual_dependency():
    from marketing import execution
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(steps=[step("access", owner="owner", due="2026-11-23"),
        step("brief", owner="pr", mode="operations", dependencies=["access"], due="2026-11-24")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    row = item(run, "access")
    with pytest.raises(MarketingError):
        launch(row)
    proof = {"summary": "The owner reconciled the complete original export", "reference": "Original export for the selected reporting week"}
    with pytest.raises(MarketingError):
        execution.record_owner_result({"id": "cmo", "role": "cmo"}, row["id"], row["version"], proof, now=NOW)
    execution.record_owner_result(OWNER, row["id"], row["version"], proof, now=NOW)
    assert item(run, "access")["status"] == "complete"
    followup = launch(item(run, "brief"))
    assert followup["plan"]["prerequisites"][0]["owner_result"]["reference"] == proof["reference"]
    with store.connection() as c:
        assert not store.list_items(c, "delivery")


def test_paid_step_must_deliver_real_bounded_proposals_without_creating_a_campaign():
    from marketing import content, execution
    from test_marketing_core import account, candidate, evidence
    from test_marketing_experiments import proposal as paid_proposal
    approve_goal(budget=3000000)
    account()
    evidence()
    creative = content.check_candidate(candidate(publication_type="paid", mode="draft")["id"], NOW)
    plan = goals.save_strategy(OWNER, proposal(steps=[step("paid", owner="targeting", mode="paid_proposal", channel="telegram", budget=600000)]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    task = launch(item(run, "paid"))
    model = Model([output("A bounded proposal", experiments=[paid_proposal(creative)]), output("Reviewed brand implications"), output("Accept this proposal for the owner's separate decision")])
    for _ in range(3):
        agents.run_one(model, NOW)
    execution.reconcile(NOW)
    assert item(run, "paid")["status"] == "complete"
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["experiment_ids"]
        assert store.get(c, "experiment", saved["experiment_ids"][0])["status"] == "proposed"
        assert not store.list_items(c, "delivery")


def test_empty_paid_handoff_cannot_claim_the_planned_proposal_exists():
    from marketing import execution
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(steps=[step("paid", owner="targeting", mode="paid_proposal", channel="telegram")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    launch(item(run, "paid"))
    model = Model([output("Only a narrative") for _ in range(3)])
    for _ in range(3):
        agents.run_one(model, NOW)
    execution.reconcile(NOW)
    assert item(run, "paid")["status"] == "needs_revision"


def test_organic_step_requires_scoped_drafts_and_quality_before_cmo_acceptance():
    from marketing import execution
    from test_marketing_production import ProductionModel, brief, prepare_accounts
    prepare_accounts()
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(rubrics=["news"], steps=[step("draft", owner="copywriter", mode="organic", channel="telegram", rubric="news")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    row = item(run, "draft")
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    with pytest.raises(MarketingError):
        execution.launch(OWNER, row["id"], row["version"], {"production": {**scope, "mode": "account"}}, now=NOW)
    task = execution.launch(OWNER, row["id"], row["version"], {"production": scope, "evidence_ids": ["decision"]}, now=NOW)
    model = ProductionModel()
    for _ in range(4):
        agents.run_one(model, NOW)
    execution.reconcile(NOW)
    pending = item(run, "draft")
    assert pending["status"] == "reviewing" and pending["task_id"] != task["id"]
    review = Model([output("The checked draft meets the plan; publishing remains separate")])
    agents.run_one(review, NOW)
    execution.reconcile(NOW)
    assert review.calls[0][1]["plan"]["artifacts"][0]["kind"] == "candidate"
    assert item(run, "draft")["status"] == "complete"
    with store.connection() as c:
        assert not store.list_items(c, "delivery")
        assert all(row["mode"] == "draft" for row in store.list_items(c, "candidate"))


def test_recovery_cannot_submit_a_draft_whose_checked_original_changed(monkeypatch):
    from marketing import content, execution
    from marketing.models import Evidence
    from test_marketing_production import ProductionModel, brief, prepare_accounts
    prepare_accounts()
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(rubrics=["news"], steps=[step("draft", owner="copywriter", mode="organic", channel="telegram", rubric="news")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    row = item(run, "draft")
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    task = execution.launch(OWNER, row["id"], row["version"], {"production": scope, "evidence_ids": ["decision"]}, now=NOW)
    reconcile = execution.reconcile
    monkeypatch.setattr(execution, "reconcile", lambda now: 0)
    model = ProductionModel()
    for _ in range(4):
        agents.run_one(model, NOW)
    with store.connection() as c:
        original = store.get(c, "evidence", "decision")
    content.save_evidence(OWNER, original["id"], {key: original[key] for key in Evidence.model_fields} | {"excerpt": "Corrected original"}, original["version"])
    reconcile(NOW)
    assert item(run, "draft")["status"] == "blocked"
    assert reconcile(NOW) == 0
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 1 and store.get(c, "plan_step", row["id"])["task_id"] == task["id"]


def test_paid_role_handoffs_cannot_accumulate_proposals_above_the_step_budget():
    from marketing import content, execution
    from test_marketing_core import account, candidate, evidence
    from test_marketing_experiments import proposal as paid_proposal
    approve_goal(budget=3000000)
    account()
    evidence()
    creative = content.check_candidate(candidate(publication_type="paid", mode="draft")["id"], NOW)
    plan = goals.save_strategy(OWNER, proposal(steps=[step("paid", owner="targeting", mode="paid_proposal", channel="telegram", budget=600000)]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    task = launch(item(run, "paid"))
    model = Model([output("First placement", experiments=[paid_proposal(creative, budget_limit=300000)]), output("Brand review"),
                   output("Another placement", experiments=[paid_proposal(creative, budget_limit=400000)])])
    for _ in range(3):
        agents.run_one(model, NOW)
    execution.reconcile(NOW)
    assert item(run, "paid")["status"] != "complete"
    with store.connection() as c:
        assert len(store.list_items(c, "experiment")) == 1
        assert store.get(c, "task", task["id"])["status"] == "error"


@pytest.mark.parametrize("initial_verdict,prepared", [("revise", False), ("accept", False), ("accept", True)])
def test_manual_draft_correction_gets_a_new_cmo_review_without_another_publication(initial_verdict, prepared):
    from marketing import content, execution
    from test_marketing_production import ProductionModel, brief, prepare_accounts
    prepare_accounts()
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(rubrics=["news"], steps=[step("draft", owner="copywriter", mode="organic", channel="telegram", rubric="news")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    row = item(run, "draft")
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru", "format": "post"}])
    if prepared:
        from marketing import scheduling
        scheduling.prepare(OWNER, row["id"], row["version"], {"production": scope, "evidence_ids": ["decision"]}, now=NOW)
        assert scheduling.run_one(NOW)
    else:
        execution.launch(OWNER, row["id"], row["version"], {"production": scope, "evidence_ids": ["decision"]}, now=NOW)
    model = ProductionModel()
    for _ in range(4):
        agents.run_one(model, NOW)
    feedback = "Add a reminder to read the original" if initial_verdict == "revise" else "The original draft is accepted"
    agents.run_one(Model([output(feedback, verdict=initial_verdict)]), NOW)
    row = item(run, "draft")
    assert row["status"] == ("needs_revision" if initial_verdict == "revise" else "complete")
    with store.connection() as c:
        candidate = store.list_items(c, "candidate")[0]
        original = store.get(c, "evidence", "decision")
    if prepared:
        from marketing.models import Evidence
        value = {key: original[key] for key in Evidence.model_fields}
        content.save_evidence(OWNER, original["id"], {**value, "excerpt": original["excerpt"] + ". Original statement reconfirmed."}, original["version"])
    content.revise_candidate(OWNER, candidate["id"], {"body": candidate["body"] + " Read the original decision."}, candidate["version"])
    content.check_candidate(candidate["id"], NOW)
    if initial_verdict == "accept":
        assert item(run, "draft")["readiness"]["status"] == "blocked"
    reviewed = execution.submit_drafts(OWNER, row["id"], row["version"], now=NOW)
    assert reviewed["status"] == "reviewing" and reviewed["attempts"] == 2
    cmo = Model([output("The corrected current draft meets the plan")])
    agents.run_one(cmo, NOW)
    assert feedback in str(cmo.calls[0][1]["plan"]["revision_feedback"])
    assert item(run, "draft")["status"] == "complete"
    with store.connection() as c:
        assert len(store.list_items(c, "candidate")) == 1 and not store.list_items(c, "delivery")
