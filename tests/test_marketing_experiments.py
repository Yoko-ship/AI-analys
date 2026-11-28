"""Paid actions need their own exact owner decision, never an organic grant."""
from datetime import timedelta

import pytest

from marketing import content, goals, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, CMO, NOW, account, candidate, evidence, goal_input, isolated  # noqa: F401


def basis():
    goals.save_goal(OWNER, goal_input(budget=1_000_000), 0)
    goals.approve_goal(OWNER, 1)
    account()
    evidence()
    item = candidate(publication_type="paid", mode="draft")
    return content.check_candidate(item["id"], NOW)


def proposal(item, **changes):
    return {"title": "Дивидендный радар · тест размещения", "goal_version": 2,
            "platform": "telegram", "advertiser_account_id": "paid-cabinet-1", "campaign_ref": "radar-pilot",
            "action": "launch", "hypothesis": "Разбор решения увеличит открытия исходной новости",
            "reader_question": "Как проверить решение эмитента?", "tested_variable": "Подача дивидендного радара вместо общей новости", "minimum_observations": 30,
            "audience": "Начинающие инвесторы Узбекистана", "placements": ["approved-channel-1"],
            "comparison": "Обычная новость по сопоставимой теме", "measurement": "Подтверждённые открытия новости по кампании",
            "evaluation_starts_on": "2026-11-23", "evaluation_ends_on": "2026-12-01",
            "starts_at": "2026-11-23T08:00:00Z", "ends_at": "2026-11-24T06:00:00Z",
            "budget_limit": 600_000, "currency": "UZS", "stop_condition": "Остановить при исчерпании лимита или ошибке источника",
            "creative_brief": "Показать утверждённую сумму и прямую ссылку на решение", "candidate_ids": [item["id"]],
            "policy_reference": "https://ads.telegram.org/guidelines", "policy_review": "Проверить ограничения финансовой рекламы до пилота",
            "policy_reviewed_on": "2026-11-23", "policy_review_valid_until": "2026-12-23", **changes}


def test_paid_proposal_and_organic_permission_cannot_start_a_campaign():
    from marketing import experiments
    item = basis()
    experiment = experiments.save(CMO, proposal(item))
    assert experiment["status"] == "proposed" and experiment["approval"] is None
    with pytest.raises(MarketingError, match="approval"):
        experiments.request_action(OWNER, experiment["id"], experiment["version"], NOW)
    with store.connection() as c:
        assert store.list_items(c, "delivery") == [] and store.list_items(c, "analytics_event") == []


def test_owner_approval_pins_all_parameters_and_edits_need_a_new_decision():
    from marketing import experiments
    item = basis()
    saved = experiments.save(CMO, proposal(item))
    with pytest.raises(MarketingError, match="owner"):
        experiments.approve(CMO, saved["id"], saved["version"], NOW)
    approved = experiments.approve(OWNER, saved["id"], saved["version"], NOW)
    assert approved["approval"]["parameters"]["budget_limit"] == 600_000
    assert approved["approval"]["creatives"][item["id"]]["content_digest"] == item["check"]["content_digest"]
    changed = experiments.save(OWNER, proposal(item, budget_limit=650_000), saved["id"], approved["version"])
    assert changed["status"] == "proposed" and changed["approval"] is None
    with pytest.raises(MarketingError, match="approval"):
        experiments.request_action(OWNER, changed["id"], changed["version"], NOW)
    with store.connection() as c:
        assert store.history(c, "experiment", saved["id"])[1]["record"]["approval"] == approved["approval"]
    with pytest.raises(MarketingError):
        experiments.approve(OWNER, saved["id"], saved["version"], NOW)


@pytest.mark.parametrize("change", ["creative", "evidence", "goal", "expiry"])
def test_action_revalidates_the_exact_approved_inputs(change):
    from marketing import experiments
    item = basis()
    saved = experiments.save(OWNER, proposal(item))
    approved = experiments.approve(OWNER, saved["id"], saved["version"], NOW)
    at = NOW
    if change == "creative":
        content.revise_candidate(OWNER, item["id"], {"title": "Другая подача"}, item["version"])
    elif change == "evidence":
        from test_marketing_incidents import amend
        amend(99)
    elif change == "goal":
        goals.save_goal(OWNER, goal_input(budget=100_000), 2)
        goals.approve_goal(OWNER, 3)
    else:
        at += timedelta(days=2)
    with pytest.raises(MarketingError) as failure:
        experiments.request_action(OWNER, saved["id"], approved["version"], at)
    assert failure.value.code != "PAID_CONNECTION_REQUIRED"


def test_approval_reserves_budget_without_inventing_spend_and_revocation_releases_it():
    from marketing import experiments
    item = basis()
    first = experiments.save(OWNER, proposal(item))
    approved = experiments.approve(OWNER, first["id"], first["version"], NOW)
    second = experiments.save(CMO, proposal(item, budget_limit=500_000, campaign_ref="second-pilot"))
    with pytest.raises(MarketingError, match="budget"):
        experiments.approve(OWNER, second["id"], second["version"], NOW)
    experiments.revoke(OWNER, first["id"], approved["version"], "Выбран другой пилот")
    assert experiments.approve(OWNER, second["id"], second["version"], NOW)["status"] == "approved"
    with store.connection() as c:
        assert store.list_items(c, "analytics_event") == []


def test_approval_requires_paid_creatives_same_platform_and_current_policy_review():
    from marketing import experiments
    item = basis()
    organic = candidate(event="organic-comparison")
    content.check_candidate(organic["id"], NOW)
    for changes in [{"candidate_ids": [organic["id"]]}, {"platform": "facebook"}, {"policy_reviewed_on": None}, {"currency": "USD"}, {"minimum_observations": None}]:
        saved = experiments.save(OWNER, proposal(item, **changes))
        with pytest.raises(MarketingError):
            experiments.approve(OWNER, saved["id"], saved["version"], NOW)


def test_approved_action_stops_at_the_separate_paid_login_boundary():
    from marketing import experiments
    item = basis()
    saved = experiments.save(OWNER, proposal(item))
    approved = experiments.approve(OWNER, saved["id"], saved["version"], NOW)
    with pytest.raises(MarketingError) as failure:
        experiments.request_action(OWNER, saved["id"], approved["version"], NOW)
    assert failure.value.code == "PAID_CONNECTION_REQUIRED"
    with store.connection() as c:
        assert store.get(c, "experiment", saved["id"])["status"] == "approved"
        assert store.list_items(c, "delivery") == []


def test_agent_cannot_replace_an_owner_approved_experiment_or_release_its_budget():
    from marketing import experiments
    item = basis()
    saved = experiments.save(CMO, proposal(item))
    approved = experiments.approve(OWNER, saved["id"], saved["version"], NOW)
    with pytest.raises(MarketingError, match="owner"):
        experiments.save(CMO, proposal(item, budget_limit=100), approved["id"], approved["version"])
    with store.connection() as c:
        assert store.get(c, "experiment", approved["id"])["approval"] == approved["approval"]


def test_goal_currency_change_never_adds_reservations_in_incompatible_units():
    from marketing import experiments
    item = basis()
    saved = experiments.save(OWNER, proposal(item))
    experiments.approve(OWNER, saved["id"], saved["version"], NOW)
    goals.save_goal(OWNER, goal_input(budget=1_000_000, currency="USD"), 2)
    goals.approve_goal(OWNER, 3)
    fresh = experiments.save(OWNER, proposal(item, goal_version=4, currency="USD", budget_limit=1))
    with pytest.raises(MarketingError, match="currenc"):
        experiments.approve(OWNER, fresh["id"], fresh["version"], NOW)


def test_targeting_model_output_becomes_a_durable_proposal_without_owner_authority():
    from marketing import agents
    from test_marketing_agents import Model, output
    item = basis()
    task = agents.start(OWNER, kind="experiment", message="Предложи платный пилот; ничего не запускай")
    model = Model([{**output("Гипотеза для проверки"), "experiments": [proposal(item)]}])
    assert agents.run_one(model, NOW)
    with store.connection() as c:
        saved = store.get(c, "task", task["id"])
        assert saved["status"] == "queued" and saved["role"] == "pr"
        proposals = store.list_items(c, "experiment")
        assert len(proposals) == 1 and proposals[0]["status"] == "proposed"
        assert proposals[0]["approval"] is None and saved["experiment_ids"] == [proposals[0]["id"]]
        assert store.list_items(c, "delivery") == []
    assert model.calls[0][1]["paid_creatives"][0]["id"] == item["id"]
