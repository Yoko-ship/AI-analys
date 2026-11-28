"""Prepared inputs authorize bounded future work, without an open browser."""
from datetime import timedelta

import pytest

from marketing import agents, content, delivery, execution, goals, store, worker
from marketing.errors import MarketingError
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, NOW, evidence, isolated  # noqa: F401
from test_marketing_execution import activate, approved_plan, item, model_clock  # noqa: F401
from test_marketing_strategy import approve_goal, proposal, step
from test_postgres_accounts import pg_store  # noqa: F401


@pytest.fixture
def workspace_backend(request, isolated, monkeypatch):
    if request.param == "postgres":
        from psycopg.conninfo import conninfo_to_dict
        native = request.getfixturevalue("pg_store")
        dsn = native.database.database_url
        monkeypatch.setenv("DATABASE_BACKEND", "postgres")
        monkeypatch.setenv("DATABASE_URL", dsn)
        monkeypatch.setenv("DATABASE_SCHEMA", conninfo_to_dict(dsn)["options"].split("search_path=", 1)[1])


def prepare(row, inputs=None, *, now=NOW):
    from marketing import scheduling
    return scheduling.prepare(OWNER, row["id"], row["version"], inputs or {}, now=now)


def test_future_inputs_wait_for_accepted_dependencies_and_start_once_without_a_browser():
    from marketing import scheduling
    run = activate(approved_plan())
    original = evidence(expires_at="2026-12-01T07:00:00Z")
    prepared = prepare(item(run, "research"), {"evidence_ids": [original["id"]]})
    assert prepared["status"] == "prepared"
    assert prepared["preparation"]["basis"]["evidence_versions"] == {original["id"]: original["version"]}
    assert not scheduling.run_one(NOW + timedelta(days=1))
    task = execution.launch(OWNER, item(run, "brief")["id"], item(run, "brief")["version"], {}, now=NOW)
    agents.run_one(Model([output("Actual PR result")]), NOW)
    assert not scheduling.run_one(NOW + timedelta(days=1))
    agents.run_one(Model([output("CMO accepted the actual PR result")]), NOW)
    assert not scheduling.run_one(NOW)
    delivery.set_pause(OWNER, processing=True)
    assert not scheduling.run_one(NOW + timedelta(days=1))
    delivery.set_pause(OWNER, processing=False)
    model = Model([output("Research based on the selected original")])
    result = worker.tick(model=model, now=NOW + timedelta(days=1))
    assert result["plan_work"] and result["model_work"] and len(model.calls) == 1
    assert not scheduling.run_one(NOW + timedelta(days=1))
    with store.connection() as c:
        row = store.get(c, "plan_step", prepared["id"])
        assignment = store.get(c, "task", row["task_id"])
        assert assignment["plan"]["prerequisites"][0]["task_id"] == task["id"]
        assert assignment["evidence_versions"] == {original["id"]: original["version"]}
        assert assignment["requested_by"] == "coordinator"
        assert row["attempts"] == 1 and row["preparation"]["status"] == "launched"
        assert not store.list_items(c, "delivery")


@pytest.mark.parametrize("change", ["version", "expiry", "withdrawal"])
def test_changed_prepared_original_requires_explicit_review_and_does_not_churn_history(change):
    from marketing import scheduling
    run = activate(approved_plan())
    original = evidence()
    prepared = prepare(item(run, "brief"), {"evidence_ids": [original["id"]]})
    now = NOW
    if change == "expiry":
        now += timedelta(days=1)
    else:
        patch = {"excerpt": "Corrected original"} if change == "version" else {"status": "disabled"}
        content.save_evidence(OWNER, original["id"], {key: patch.get(key, value) for key, value in original.items()
                              if key not in {"id", "version", "updated_at"}}, original["version"])
    assert not scheduling.run_one(now)
    with store.connection() as c:
        row = store.get(c, "plan_step", prepared["id"])
        assert row["status"] == "blocked" and row["preparation"]["status"] == "blocked"
        assert row["attempts"] == 0 and row["task_id"] is None
        history = store.history(c, "plan_step", row["id"])
        assert "evidence" in row["reason"].lower()
    assert not scheduling.run_one(now)
    with store.connection() as c:
        assert store.history(c, "plan_step", row["id"]) == history
        assert not store.list_items(c, "task")


def test_prepared_brief_can_be_replaced_or_cancelled_but_never_by_a_model_role():
    from marketing import scheduling
    run = activate(approved_plan())
    first = evidence("first")
    second = evidence("second")
    prepared = prepare(item(run, "brief"), {"evidence_ids": [first["id"]]})
    with pytest.raises(MarketingError):
        scheduling.prepare({"id": "cmo", "role": "cmo"}, prepared["id"], prepared["version"], {}, now=NOW)
    replacement = prepare(prepared, {"evidence_ids": [second["id"]]})
    with pytest.raises(MarketingError):
        scheduling.cancel(OWNER, prepared["id"], prepared["version"])
    stopped = scheduling.cancel(OWNER, replacement["id"], replacement["version"])
    assert stopped["status"] == "pending" and stopped["preparation"]["status"] == "cancelled"
    assert not scheduling.run_one(NOW)
    rearmed = prepare(stopped, {"evidence_ids": [second["id"]]})
    assert scheduling.run_one(NOW)
    with store.connection() as c:
        row = store.get(c, "plan_step", rearmed["id"])
        task = store.get(c, "task", row["task_id"])
        assert task["evidence_versions"] == {second["id"]: 1}
        history = store.history(c, "plan_step", row["id"])
        assert history[1]["record"]["preparation"]["inputs"]["evidence_ids"] == [first["id"]]


def test_worker_orders_ready_steps_by_deadline_and_skips_a_stale_preparation():
    from marketing import scheduling
    approve_goal()
    plan = goals.save_strategy(OWNER, proposal(steps=[
        step("later", mode="operations", due="2026-11-26"),
        step("stale", mode="research", due="2026-11-23"),
        step("sooner", mode="operations", due="2026-11-24"),
    ]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    prepare(item(run, "later"))
    prepare(item(run, "sooner"))
    original = evidence(expires_at=(NOW + timedelta(minutes=1)).isoformat())
    prepare(item(run, "stale"), {"evidence_ids": [original["id"]]})
    assert scheduling.run_one(NOW + timedelta(minutes=2))
    assert item(run, "stale")["status"] == "blocked"
    assert item(run, "sooner")["status"] == "queued"
    assert item(run, "later")["status"] == "prepared"
    assert scheduling.run_one(NOW + timedelta(minutes=2))
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 2


def test_plan_pause_preserves_preparation_and_a_revised_goal_prevents_new_work():
    from marketing import scheduling
    from test_marketing_core import goal_input
    run = activate(approved_plan())
    prepared = prepare(item(run, "brief"))
    paused = execution.set_paused(OWNER, run["id"], run["version"], True)
    assert not scheduling.run_one(NOW)
    assert item(paused, "brief")["preparation"]["status"] == "armed"
    execution.set_paused(OWNER, run["id"], paused["version"], False)
    changed = goals.save_goal(OWNER, goal_input(target=200), 2)
    goals.approve_goal(OWNER, changed["version"])
    assert not scheduling.run_one(NOW)
    with store.connection() as c:
        assert not store.list_items(c, "task")
        assert store.get(c, "plan_step", prepared["id"])["task_id"] is None


def test_revision_preparation_survives_reconciliation_of_the_old_task():
    from marketing import scheduling
    run = activate(approved_plan())
    row = item(run, "brief")
    old = execution.launch(OWNER, row["id"], row["version"], {}, now=NOW)
    agents.run_one(Model([output("Brief")]), NOW)
    agents.run_one(Model([output("Missing product constraints", verdict="revise")]), NOW)
    prepared = prepare(item(run, "brief"))
    execution.reconcile(NOW)
    assert item(run, "brief")["status"] == "prepared"
    assert scheduling.run_one(NOW)
    with store.connection() as c:
        row = store.get(c, "plan_step", prepared["id"])
        task = store.get(c, "task", row["task_id"])
        assert task["plan"]["previous_task_id"] == old["id"]
        assert task["plan"]["revision_feedback"]["summary"] == "Missing product constraints"
        assert row["attempts"] == 2


@pytest.mark.parametrize("when", ["before_assignment", "before_claim", "during_model"])
def test_prepared_draft_keeps_the_exact_account_binding_until_role_acceptance(when):
    from marketing import scheduling
    from test_marketing_core import account
    from test_marketing_production import brief
    approve_goal()
    account("telegram", mode="draft")
    evidence()
    plan = goals.save_strategy(OWNER, proposal(rubrics=["news"], steps=[
        step("draft", mode="organic", owner="copywriter", channel="telegram", rubric="news")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru"}])
    prepared = prepare(item(run, "draft"), {"evidence_ids": ["decision"], "production": scope})

    def change_recipient():
        with store.connection(write=True) as c:
            value = store.get(c, "account", "telegram")
            store.put(c, "account", {**value, "external_id": "different-recipient"}, actor=OWNER,
                      action="account_saved", expected_version=value["version"])

    if when == "before_assignment":
        change_recipient()
        assert not scheduling.run_one(NOW)
    else:
        assert scheduling.run_one(NOW)
        if when == "before_claim":
            change_recipient()
            model = Model([])
        else:
            class ChangingModel(Model):
                def complete_json(self, *args, **kwargs):
                    change_recipient()
                    return super().complete_json(*args, **kwargs)
            model = ChangingModel([output("Outdated recipient context")])
        agents.run_one(model, NOW)
        execution.reconcile(NOW)
        assert len(model.calls) == (1 if when == "during_model" else 0)
    with store.connection() as c:
        row = store.get(c, "plan_step", prepared["id"])
        assert row["status"] == "blocked"
        assert not store.list_items(c, "candidate") and not store.list_items(c, "delivery")
        if row["task_id"]:
            assert store.get(c, "task", row["task_id"])["outputs"] == []


@pytest.mark.parametrize("workspace_backend", ["sqlite", "postgres"], indirect=True)
def test_two_preparations_for_one_event_never_duplicate_or_restart_rejected_production(workspace_backend):
    from marketing import scheduling
    from test_marketing_production import brief, prepare_accounts, ProductionModel
    approve_goal()
    prepare_accounts()
    plan = goals.save_strategy(OWNER, proposal(rubrics=["news"], steps=[
        step(key, mode="organic", owner="copywriter", channel="telegram", rubric="news") for key in ("a", "b")]), now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    scope = brief(targets=[{"account_id": "telegram", "languages": ["ru"], "primary_language": "ru"}])
    for key in ("a", "b"):
        prepare(item(run, key), {"evidence_ids": ["decision"], "production": scope})
    assert scheduling.run_one(NOW)
    assert not scheduling.run_one(NOW)
    model = ProductionModel(reject="telegram")
    for _ in range(4):
        agents.run_one(model, NOW)
    assert not scheduling.run_one(NOW)
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 1
        assert not store.list_items(c, "delivery")
        blocked = next(row for row in store.list_items(c, "plan_step") if row["status"] == "blocked")
        assert "existing production task" in blocked["reason"]
    with pytest.raises(MarketingError, match="existing production task"):
        prepare(blocked, {"evidence_ids": ["decision"], "production": scope})


def test_changed_selected_measurement_does_not_silently_refresh_a_prepared_assignment():
    from marketing import reports, scheduling
    from test_marketing_strategy import measured_snapshot, measured_plan
    snapshot = measured_snapshot()
    value = measured_plan(snapshot)
    for scenario in value["scenarios"]:
        scenario["projection"] = None
    plan = goals.save_strategy(OWNER, value, now=NOW)
    run = activate(goals.approve_strategy(OWNER, plan["id"], plan["version"], now=NOW))
    prepared = prepare(item(run, "measure"), {"planning_snapshot_ids": [snapshot["id"]]})
    assert prepared["preparation"]["basis"]["planning_snapshots"][0]["baseline"] == 2
    reports.import_events(OWNER, [{"id": "late", "kind": "registration", "subject_id": "late-reader", "channel": "direct", "dataset": "test",
                                  "at": "2025-01-08T08:00:00Z", "source": "typed-registration-ledger", "confirmed": True}], [], now=NOW + timedelta(seconds=1))
    assert not scheduling.run_one(NOW + timedelta(seconds=2))
    row = item(run, "measure")
    assert row["status"] == "blocked" and row["task_id"] is None
    assert row["preparation"]["basis"]["planning_snapshots"][0]["baseline"] == 2


def test_changed_theme_inventory_keeps_prepared_review_frozen_until_reprepared():
    from marketing import scheduling
    from test_marketing_trends import setup_source, import_items, material, save
    run = activate(approved_plan())
    setup_source()
    import_items(material("original", 18))
    observation = save()
    prepare(item(run, "brief"), {"trend_ids": [observation["id"]]})
    import_items(material("late", 19))
    assert not scheduling.run_one(NOW)
    row = item(run, "brief")
    assert row["status"] == "blocked"
    assert row["preparation"]["basis"]["trend_versions"] == {observation["id"]: 1}


@pytest.mark.parametrize("workspace_backend", ["sqlite", "postgres"], indirect=True)
def test_parallel_worker_claims_cannot_create_two_assignments(workspace_backend):
    from concurrent.futures import ThreadPoolExecutor
    from marketing import scheduling
    run = activate(approved_plan())
    prepare(item(run, "brief"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: scheduling.run_one(NOW), range(2)))
    assert sum(results) == 1
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 1
        assert store.list_items(c, "conversation")[0]["messages"][0]["role"] == "coordinator"


def test_prepared_internal_revisions_follow_cmo_feedback_and_stop_after_three_attempts():
    from marketing import scheduling
    run = activate(approved_plan())
    prepare(item(run, "brief"))
    for attempt in range(3):
        assert scheduling.run_one(NOW)
        writer = Model([output(f"Brief attempt {attempt + 1}")])
        agents.run_one(writer, NOW)
        if attempt:
            assert writer.calls[0][1]["plan"]["revision_feedback"]["summary"] == f"Missing original detail {attempt}"
        agents.run_one(Model([output(f"Missing original detail {attempt + 1}", verdict="revise")]), NOW)
        assert item(run, "brief")["status"] == "needs_revision"
    assert not scheduling.run_one(NOW)
    assert item(run, "brief")["attempts"] == 3
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 3 and not store.list_items(c, "delivery")


def test_manual_assignment_does_not_restore_a_cancelled_automatic_binding():
    from marketing import scheduling
    run = activate(approved_plan())
    original = evidence()
    prepared = prepare(item(run, "brief"), {"evidence_ids": [original["id"]]})
    cancelled = scheduling.cancel(OWNER, prepared["id"], prepared["version"])
    manual = execution.launch(OWNER, cancelled["id"], cancelled["version"], {}, now=NOW)
    assert manual["evidence"] == [] and manual["plan"]["preparation"] is None
    agents.run_one(Model([output("New manually scoped brief")]), NOW)
    agents.run_one(Model([output("Needs a different product detail", verdict="revise")]), NOW)
    assert not scheduling.run_one(NOW)
    assert item(run, "brief")["preparation"]["status"] == "cancelled"
    with store.connection() as c:
        assert len(store.list_items(c, "task")) == 1
