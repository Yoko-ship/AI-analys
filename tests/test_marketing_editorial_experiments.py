"""Measured format tests keep cohorts, cutoffs and owner decisions distinct."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from marketing import content, goals, reports, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, CMO, account, candidate, evidence, goal_input, isolated  # noqa: F401
from test_marketing_reports import configured, coverage

START = datetime(2026, 11, 23, tzinfo=timezone.utc)
CUT = datetime(2026, 11, 27, tzinfo=timezone.utc)


def prepared(*, start=START):
    """Real saved draft IDs and imported observations, also used by browser QA."""
    configured()
    goals.save_goal(OWNER, goal_input(starts_on=(start-timedelta(days=2)).date().isoformat(),
                                    deadline=(start+timedelta(days=30)).date().isoformat()), 0)
    goals.approve_goal(OWNER, 1)
    account(mode="draft")
    evidence()
    drafts = [candidate(event="format-"+arm, mode="draft", track_visits=True,
                        title=label, destination_url="https://uzstock.uz/news/decision-123")
              for arm, label in [("control", "Обычная новость"), ("variant", "Дивидендный радар")]]
    design = {"title": "Проверка подачи новости", "goal_version": 2,
              "hypothesis": "Радар помогает открыть решение", "segment": "Начинающие читатели",
              "reader_question": "Где проверить сумму?", "tested_variable": "Заголовок",
              "comparison": "Одинаковая тема и размещение, меняется только заголовок",
              "control_ids": [drafts[0]["id"]], "variant_ids": [drafts[1]["id"]],
              "kpi": "news_open", "outcome_object_id": "decision-123", "minimum_observations": 3,
              "starts_on": start.date().isoformat(), "ends_on": (start+timedelta(days=2)).date().isoformat(),
              "followup_days": 1, "stop_condition": "Остановить при ошибке первоисточника"}
    events = []
    for arm, draft in zip(("control", "variant"), drafts):
        for i in range(3):
            base = {"dataset": "test", "source": "confirmed-browser-receipts", "confirmed": True,
                    "subject_id": f"{arm}{i}", "at": (start+timedelta(hours=1)).isoformat()}
            events.append({**base, "id": f"{arm}-visit-{i}", "kind": "publication_visit",
                           "channel": "telegram", "publication_id": draft["id"]})
            if i < (1 if arm == "control" else 2):
                events.append({**base, "id": f"{arm}-open-{i}", "kind": "news_open", "object_id": "decision-123",
                               "at": (start+timedelta(hours=2)).isoformat()})
    return design, drafts, events


def measured(design, events, *, at=CUT, status="complete"):
    reports.import_events(OWNER, events, [coverage(starts_on=design["starts_on"], ends_on="2027-01-01",
                                                  through=at.isoformat(), status=status)], now=at)


def test_design_and_evaluation_use_saved_publications_unique_readers_and_exact_outcomes():
    from marketing import editorial_experiments as ex
    design, drafts, events = prepared()
    item = ex.register(OWNER, design, now=START-timedelta(days=1))
    measured(design, events + [
        {**events[0], "id": "repeat-arrival"},
        {**events[1], "id": "repeat-open"},
        {**events[1], "id": "wrong-object", "subject_id": "control1", "object_id": "other-news"},
        {**events[1], "id": "internal", "subject_id": "control1", "traffic": "internal"},
        {**events[1], "id": "unconfirmed", "subject_id": "control2", "confirmed": False},
        {**events[1], "id": "before-arrival", "subject_id": "control1", "at": START.isoformat()},
        {**events[1], "id": "outside-followup", "subject_id": "control2", "at": (START+timedelta(days=2)).isoformat()},
        {**events[0], "id": "paid-arrival", "subject_id": "paid-reader", "promotion": "paid"},
        {**events[0], "id": "other-channel", "subject_id": "other-channel-reader", "channel": "linkedin"},
        {**events[0], "id": "production-arrival", "subject_id": "production-reader", "dataset": "production"},
    ])
    result = ex.evaluate(OWNER, item["id"], 1, now=CUT)
    assert result["result"]["status"] == "observed"
    assert result["result"]["arms"]["control"] == {"readers": 3, "outcomes": 1, "rate": pytest.approx(100/3)}
    assert result["result"]["arms"]["variant"] == {"readers": 3, "outcomes": 2, "rate": pytest.approx(200/3)}
    assert result["result"]["difference_pp"] == pytest.approx(100/3)
    assert result["result"]["dataset"] == "test"
    assert result["design"]["timing"] == "prospective"
    assert result["result"]["inputs_digest"]
    assert "subject_id" not in store.encode(result)
    with store.connection() as c:
        assert store.get(c, "editorial_experiment", item["id"])["design"]["control_ids"] == [drafts[0]["id"]]
        assert store.list_items(c, "delivery") == []
        assert goals.active_goal(c)["budget"] == 0


@pytest.mark.parametrize("case", ["small", "incomplete", "open", "empty"])
def test_insufficient_observations_never_become_a_confirmed_winner(case):
    from marketing import editorial_experiments as ex
    design, _, events = prepared()
    if case == "small":
        design["minimum_observations"] = 4
    item = ex.register(OWNER, design, now=START)
    at = START+timedelta(hours=3) if case == "open" else CUT
    measured(design, [] if case == "empty" else events, at=at, status="incomplete" if case == "incomplete" else "complete")
    result = ex.evaluate(OWNER, item["id"], 1, now=at)["result"]
    assert result["status"] == "preliminary" and result["reasons"]
    assert result["difference_pp"] is None
    if case == "empty":
        assert result["arms"]["control"]["rate"] is None


@pytest.mark.parametrize('second_touch', [START+timedelta(hours=3), START+timedelta(hours=24)])
def test_cross_exposed_readers_are_excluded_from_both_arms(second_touch):
    from marketing import editorial_experiments as ex
    design, drafts, events = prepared()
    design['ends_on'] = (START+timedelta(days=1)).date().isoformat()
    item = ex.register(OWNER, design, now=START)
    measured(design, events + [{**events[0], "id": "cross-exposed", "publication_id": drafts[1]["id"],
                                "at": second_touch.isoformat()}])
    result = ex.evaluate(OWNER, item["id"], 1, now=CUT)["result"]
    assert result["excluded_overlap"] == 1
    assert result["arms"]["control"]["readers"] == 2
    assert result["arms"]["control"]["outcomes"] == 0
    assert result["arms"]["variant"]["readers"] == 3
    assert result["status"] == "preliminary"


def test_late_amendment_creates_a_new_evaluation_without_rewriting_decision_basis():
    from marketing import editorial_experiments as ex
    design, _, events = prepared()
    item = ex.register(OWNER, design, now=CUT)
    measured(design, events)
    first = ex.evaluate(OWNER, item["id"], 1, now=CUT)
    assert first["design"]["timing"] == "retrospective"
    decided = ex.decide(OWNER, item["id"], 1, first["id"], "repeat", "Повторить с новой темой")
    reports.import_events(OWNER, [], [], corrections=[{"event_id": "variant-open-1", "dataset": "test",
        "replacement": None, "reason": "Отозван ошибочный receipt", "expected_version": 0}], now=CUT+timedelta(seconds=1))
    second = ex.evaluate(OWNER, item["id"], decided["version"], now=CUT+timedelta(seconds=2))
    assert second["result"]["arms"]["variant"]["outcomes"] == 1
    assert first["result"]["arms"]["variant"]["outcomes"] == 2
    with store.connection() as c:
        saved = store.get(c, "editorial_experiment", item["id"])
        assert saved["decision"]["evaluation_id"] == first["id"]
        assert store.get(c, "experiment_evaluation", first["id"]) == first
        assert goals.active_goal(c)["target"] == 100
    with pytest.raises(MarketingError):
        ex.decide(OWNER, item["id"], 1, second["id"], "stop", "Устаревшее решение")


def test_changed_creative_is_reported_and_cannot_silently_change_the_design():
    from marketing import editorial_experiments as ex
    design, drafts, events = prepared()
    item = ex.register(OWNER, design, now=START)
    content.revise_candidate(OWNER, drafts[0]["id"], {"body": "Изменённый заголовок"}, drafts[0]["version"])
    measured(design, events)
    result = ex.evaluate(OWNER, item["id"], 1, now=CUT)["result"]
    assert result["status"] == "preliminary"
    assert "creative_changed" in result["reasons"]


def test_registration_outcome_excludes_existing_accounts_and_requires_history():
    from marketing import editorial_experiments as ex
    design, _, events = prepared()
    design.update(kpi="registration", outcome_object_id="")
    events = [{**e, "kind": "registration", "object_id": ""} if e["kind"] == "news_open" else e for e in events]
    events.append({**events[1], "id": "existing-account", "at": (START-timedelta(days=1)).isoformat()})
    item = ex.register(OWNER, design, now=START)
    measured(design, events)
    result = ex.evaluate(OWNER, item["id"], 1, now=CUT)["result"]
    assert result["excluded_existing"] == 1 and result["arms"]["control"]["readers"] == 2
    assert result["arms"]["control"]["outcomes"] == 0
    reports.import_events(OWNER, [], [coverage(through=(CUT+timedelta(seconds=1)).isoformat(), history_complete=False, status="incomplete")], now=CUT+timedelta(seconds=1))
    assert ex.evaluate(OWNER, item["id"], 1, now=CUT+timedelta(seconds=2))["result"]["status"] == "preliminary"


@pytest.mark.parametrize("change", ["overlap", "paid", "no_tracking", "goal", "account"])
def test_design_cannot_merge_arms_paid_creatives_or_unrelated_owner_context(change):
    from marketing import editorial_experiments as ex
    design, drafts, _ = prepared()
    if change == "overlap":
        design["variant_ids"] = design["control_ids"]
    elif change == "goal":
        design["goal_version"] = 999
    else:
        if change == "account":
            account("other")
        other = candidate("invalid-arm", target="other" if change == "account" else "tg", mode="draft",
                          publication_type="paid" if change == "paid" else "organic", track_visits=change != "no_tracking")
        design["variant_ids"] = [other["id"]]
    with pytest.raises((MarketingError, ValidationError)):
        ex.register(OWNER, design, now=START)
    with store.connection() as c:
        assert store.list_items(c, "editorial_experiment") == []


def test_only_owner_registers_or_decides_and_evaluation_cannot_borrow_another_test():
    from marketing import editorial_experiments as ex
    design, _, events = prepared()
    with pytest.raises(MarketingError):
        ex.register(CMO, design, now=START)
    first = ex.register(OWNER, design, now=START)
    second = ex.register(OWNER, design, now=START)
    measured(design, events)
    evaluation = ex.evaluate(OWNER, first["id"], 1, now=CUT)
    for actor, key in [(CMO, first["id"]), (OWNER, second["id"])]:
        with pytest.raises(MarketingError):
            ex.decide(actor, key, 1, evaluation["id"], "stop", "Не продолжать проверку")


def test_a_post_enrollment_touch_outside_the_followup_does_not_contaminate_the_cohort():
    from marketing import editorial_experiments as ex
    design, drafts, events = prepared()
    design['ends_on'] = (START+timedelta(days=1)).date().isoformat()
    item = ex.register(OWNER, design, now=START)
    measured(design, events+[{**events[0], 'id': 'later-unrelated-touch', 'publication_id': drafts[1]['id'],
                              'at': (START+timedelta(days=2)).isoformat()}])
    result = ex.evaluate(OWNER, item['id'], 1, now=CUT)['result']
    assert result['excluded_overlap'] == 0
    assert result['arms']['control']['readers'] == 3
    assert result['status'] == 'observed'


def test_saved_evaluations_reach_cmo_reports_and_late_results_invalidate_old_context(monkeypatch):
    from marketing import editorial_experiments as ex
    monkeypatch.setattr(store, 'now', lambda: (START-timedelta(days=1)).isoformat())
    design, _, events = prepared()
    item = ex.register(OWNER, design, now=START-timedelta(days=1))
    measured(design, events)
    monkeypatch.setattr(store, 'now', lambda: CUT.isoformat())
    evaluation = ex.evaluate(OWNER, item['id'], 1, now=CUT)
    period = {key: design[key] for key in ('starts_on', 'ends_on')}
    report = reports.calculate(period, now=CUT)
    context = report['experiment_results']
    assert context['items'][0]['evaluation_id'] == evaluation['id']
    assert context['items'][0]['result']['arms']['variant']['outcomes'] == 2
    assert context['items'][0]['design']['minimum_observations'] == 3
    task = reports.request_analysis(OWNER, period, now=CUT)
    assert task['report']['experiment_results'] == context
    later = CUT+timedelta(seconds=1)
    monkeypatch.setattr(store, 'now', lambda: later.isoformat())
    reports.import_events(OWNER, [], [], corrections=[{'event_id': 'variant-open-1', 'dataset': 'test',
        'replacement': None, 'reason': 'Ошибка исходного события', 'expected_version': 0}], now=later)
    newer = ex.evaluate(OWNER, item['id'], 1, now=later)
    current = reports.calculate(period, now=later)
    assert current['experiment_results']['items'][0]['evaluation_id'] == newer['id']
    assert current['context_digest'] != report['context_digest']
    assert current['analysis'] is None
    assert reports.calculate({**period, 'cutoff': CUT.isoformat()}, now=later)['experiment_results'] == context
