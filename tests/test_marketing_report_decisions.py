"""CMO decisions cite the measured report cut and remain proposals."""
from copy import deepcopy
from datetime import timedelta

import pytest

from marketing import agents, goals, reports, store
from test_marketing_agents import Model, output
from test_marketing_core import OWNER, goal_input, isolated  # noqa: F401
from test_marketing_reports import NOW, PERIOD, configured, coverage
from test_marketing_analytics import fixture, event


def review():
    return {"decisions": [{"id": "measure-first", "action": "change", "subject": "Подготовка следующего контент-теста",
        "metric_ids": ["registrations"], "reason": "Наблюдение не объясняет причину отставания. Проверим подачу отдельно.",
        "next_action": "Сравнить два варианта обложки при одинаковом размещении.", "owner": "analytics",
        "check_on": "2026-12-15", "hypothesis_ids": ["cover"], "strategy_step_ids": []}],
        "hypotheses": [{"id": "cover", "parent_id": "", "statement": "Более понятная обложка может улучшить отклик.",
            "metric_ids": ["registrations"], "test_plan": "Одинаковая аудитория и окно; меняется только обложка.",
            "success_metric": "registrations", "success_criterion": "Больше подтверждённых регистраций при сопоставимой экспозиции.",
            "kind": "organic", "priority": "high", "owner": "analytics", "check_on": "2026-12-15"}]}


def prepared_report(monkeypatch, *, completeness="complete", analyst=True):
    configured()
    monkeypatch.setattr(store, "now", lambda: NOW.isoformat())
    goals.save_goal(OWNER, goal_input(metric="registrations", unit="users", starts_on=PERIOD["starts_on"],
                                    deadline=PERIOD["ends_on"], target=100, budget=0), 0)
    goals.approve_goal(OWNER, 1)
    reports.import_events(OWNER, fixture(), [coverage(status=completeness)], now=NOW)
    task = reports.request_analysis(OWNER, PERIOD, now=NOW)
    if analyst:
        assert agents.run_one(Model([output("Подтверждённые наблюдения и полнота доступны в отчёте; причины разницы не измерены.")]), NOW)
    return task


def test_cmo_decisions_bind_actual_metrics_and_a_testable_hypothesis_without_changing_the_goal(monkeypatch):
    task = prepared_report(monkeypatch)
    model = Model([output("Меняем тест, сохраняя цель.", cmo_review=review())])
    assert agents.run_one(model, NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        goal = store.get(c, "goal", "primary")
        assert saved["status"] == "complete", saved["reason"]
        result = saved["outputs"][-1]["result"]["cmo_review"]
        assert result["basis"]["context_digest"] == task["report"]["context_digest"]
        assert result["basis"]["metrics"]["registrations"]["value"] == 30
        assert result["basis"]["plan_fact"]["difference"] == -70
        assert result["decisions"][0]["action"] == "change"
        assert result["hypotheses"][0]["success_metric"] == "registrations"
        assert goal["target"] == 100 and goal["budget"] == 0 and goal["version"] == 2
        assert store.list_items(c, "delivery") == [] and store.list_items(c, "experiment") == []
    assert model.calls[0][1]["report"]["metrics"]["registrations"]["value"] == 30
    assert model.calls[0][1]["current_time"] == NOW.isoformat()
    assert reports.calculate(PERIOD, now=NOW)["analysis"]["cmo"]["cmo_review"] == result


def test_an_accepted_cmo_report_needs_a_decision_and_next_test_not_only_a_generic_summary(monkeypatch):
    task = prepared_report(monkeypatch)
    agents.run_one(Model([output("Продолжайте работу.")]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "error" and len(saved["outputs"]) == 1


def test_late_registration_does_not_rewrite_a_cmo_decisions_original_basis(monkeypatch):
    task = prepared_report(monkeypatch)
    later = NOW + timedelta(seconds=1)
    monkeypatch.setattr(store, "now", lambda: later.isoformat())
    reports.import_events(OWNER, [event("late-r", "registration", "late-user")], [], now=later)
    agents.run_one(Model([output("Сохраняем исходную базу сравнения.", cmo_review=review())]), later)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete", saved["reason"]
        assert saved["outputs"][-1]["result"]["cmo_review"]["basis"]["metrics"]["registrations"]["value"] == 30
    current = reports.calculate(PERIOD, now=later)
    assert current["metrics"]["registrations"]["value"] == 31
    assert current["analysis"] is None


def test_cmo_measurement_proposal_preserves_missing_totals_and_observed_sample(monkeypatch):
    task = prepared_report(monkeypatch, completeness="incomplete")
    value = review()
    value["hypotheses"][0]["kind"] = "measurement"
    agents.run_one(Model([output("Сначала подтвердим полноту регистраций.", cmo_review=value)]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "complete", saved["reason"]
        basis = saved["outputs"][-1]["result"]["cmo_review"]["basis"]
        assert basis["metrics"]["registrations"]["value"] is None
        assert basis["metrics"]["registrations"]["numerator"] == 30
        assert basis["metrics"]["registrations"]["status"] == "incomplete"
        assert basis["plan_fact"]["difference"] is None


def test_the_analyst_cannot_supply_a_cmo_decision(monkeypatch):
    task = prepared_report(monkeypatch, analyst=False)
    agents.run_one(Model([output("Решение от другой роли", cmo_review=review())]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "error" and saved["outputs"] == []


@pytest.mark.parametrize("problem", ["metric", "parent", "cycle", "reference", "step", "date", "duplicate"])
def test_report_decision_references_and_hypothesis_tree_cannot_invent_their_context(monkeypatch, problem):
    task = prepared_report(monkeypatch)
    value = deepcopy(review())
    if problem == "metric":
        value["decisions"][0]["metric_ids"] = ["invented_sales"]
    elif problem == "parent":
        value["hypotheses"][0]["parent_id"] = "missing"
    elif problem == "cycle":
        value["hypotheses"][0]["parent_id"] = "child"
        value["hypotheses"].append({**value["hypotheses"][0], "id": "child", "parent_id": "cover"})
    elif problem == "reference":
        value["decisions"][0]["hypothesis_ids"] = ["not-tested"]
    elif problem == "step":
        value["decisions"][0]["strategy_step_ids"] = ["unapproved-step"]
    elif problem == "date":
        value["decisions"][0]["check_on"] = "2026-12-01"
    else:
        value["hypotheses"].append(dict(value["hypotheses"][0]))
    agents.run_one(Model([output("Неподходящее предложение", cmo_review=value)]), NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "error" and len(saved["outputs"]) == 1
        assert "report" in saved["reason"].casefold() and "invalid response" not in saved["reason"]
