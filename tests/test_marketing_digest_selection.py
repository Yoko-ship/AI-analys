"""A closed digest window selects distinct unused events for one account."""
from datetime import timedelta

import pytest

from marketing import agents, automation, content, store
from test_marketing_core import NOW, account, candidate, isolated  # noqa: F401
from test_marketing_execution import model_clock  # noqa: F401
from test_marketing_automation import rows, setup_rule, update_rule
from test_marketing_digest import DigestModel, material, originals


def rule(**changes):
    return setup_rule(initial_material=False, **{"rubric": "digest", "source_ids": ["digest-news"],
                      "digest_time": "13:00", "max_age_hours": 24, **changes})


def test_digest_waits_for_its_tashkent_cut_then_assigns_one_bound_multi_issuer_pack():
    selected = originals(now=NOW - timedelta(hours=1))
    owner_rule = rule(mode="account", max_daily=2)
    assert not automation.run_one(NOW - timedelta(minutes=1))
    assert automation.run_one(NOW)
    task, = rows("task")
    assert task["production"]["rubric"] == "digest" and task["production"]["entity"] == ""
    assert task["production"]["period"] == "2026-11-23"
    assert set(task["evidence_versions"]) == {row["id"] for row in selected}
    assert task["editorial"]["digest_cutoff"] == "2026-11-23T13:00:00+05:00"
    assert not automation.run_one(NOW + timedelta(minutes=1))
    for _ in range(8):
        assert agents.run_one(DigestModel(), NOW)
    item, = rows("candidate")
    assert item["status"] == "ready", item["check"]["reason"]
    update_rule(owner_rule, enabled=False)
    assert content.check_candidate(item["id"], NOW)["status"] == "skipped"
    assert rows("delivery") == []


@pytest.mark.parametrize("count,age_hours", [(1, 1), (2, 30)])
def test_digest_does_not_fill_a_window_with_one_event_or_stale_news(count, age_hours):
    originals(count=count, age_hours=age_hours)
    rule()
    assert not automation.run_one(NOW)
    assert rows("task") == [] and rows("candidate") == []


@pytest.mark.parametrize("recipient,publication_type,expected", [("tg", "organic", 2), ("other", "organic", 3), ("tg", "paid", 3)])
def test_digest_excludes_events_already_assigned_only_to_this_account(recipient, publication_type, expected):
    selected = originals(count=3)
    rule()
    if recipient == "other":
        account("other", external_id="-100999")
    candidate(selected[0]["canonical_event_id"], target=recipient, evidence_ids=[selected[0]["id"]],
              claims=[], body="Ранее созданный внутренний материал.", publication_type=publication_type)
    assert automation.run_one(NOW)
    task, = rows("task")
    assert len(task["evidence_versions"]) == expected
    if recipient == "tg" and publication_type == "organic":
        assert selected[0]["id"] not in task["evidence_versions"]


@pytest.mark.parametrize("publication_type", ["organic", "paid"])
def test_events_in_an_owner_created_digest_are_not_selected_again_as_new_work(publication_type):
    selected = originals(count=3)
    rule()
    material(selected[:2], publication_type=publication_type)
    assert automation.run_one(NOW) == (publication_type == "paid")
    if publication_type == "organic":
        assert rows("task") == []  # Only the third independent event remains.
    else:
        task, = rows("task")
        assert len(task["evidence_versions"]) == 3


def test_an_automatic_digest_cannot_silently_drop_an_assigned_event():
    originals(count=3)
    rule(mode="account")
    assert automation.run_one(NOW)
    for _ in range(8):
        assert agents.run_one(DigestModel(omit_last=True), NOW)
    item, = rows("candidate")
    assert item["status"] == "skipped" and "selected event" in item["check"]["reason"]


@pytest.mark.parametrize("changes", [{"digest_time": ""}, {"digest_time": "24:00"},
    {"rubric": "news"}, {"target": {"account_id": "tg", "languages": ["ru"], "primary_language": "ru", "format": "image"}}])
def test_a_digest_rule_needs_a_valid_cutoff_and_text_format_and_other_rules_have_no_cutoff(changes):
    with pytest.raises(ValueError):
        rule(enabled=False, **changes)
    assert rows("editorial_rule") == []


def test_digest_selection_is_bounded_and_does_not_make_another_edition_after_a_rule_edit():
    selected = originals(count=10)
    saved = rule(max_daily=10)
    assert automation.run_one(NOW)
    task, = rows("task")
    assert len(task["evidence_versions"]) == 8
    assert set(task["evidence_versions"]) < {row["id"] for row in selected}
    update_rule(saved, title="Новая редакционная формулировка")
    assert not automation.run_one(NOW + timedelta(minutes=1))
    assert len(rows("task")) == 1
