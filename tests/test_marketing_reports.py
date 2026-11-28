"""Owner reporting uses stored events, measured coverage and immutable cuts."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta

import pytest

from marketing import store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, isolated  # noqa: F401
from test_marketing_analytics import fixture
from test_marketing_business_metrics import config

NOW = datetime(2026, 12, 8, 12, tzinfo=timezone.utc)
PERIOD = {"starts_on": "2026-11-23", "ends_on": "2026-11-30"}


def coverage(**changes):
    return {"dataset": "test", "categories": ["visits", "registrations", "payments", "expenses", "activity", "subscriptions", "margin", "clicks", "impressions"],
            "starts_on": "2026-01-01", "ends_on": "2027-01-01", "through": NOW.isoformat(),
            "history_complete": True, "status": "complete", "reference": "Confirmed billing and event export, checked by owner", **changes}


def configured():
    from marketing import reports
    return reports.save_settings(OWNER, config(), 0)


def test_only_coverage_for_this_period_and_dataset_can_turn_missing_data_into_measured_zero():
    from marketing import reports
    configured()
    reports.import_events(OWNER, fixture(), [], now=NOW)
    unavailable = reports.calculate(PERIOD, now=NOW)
    assert unavailable["metrics"]["registrations"]["value"] is None
    reports.import_events(OWNER, [], [coverage(dataset="production")], now=NOW)
    assert reports.calculate(PERIOD, now=NOW)["metrics"]["registrations"]["value"] is None
    reports.import_events(OWNER, [], [coverage()], now=NOW)
    report = reports.calculate(PERIOD, now=NOW)
    assert report["metrics"]["registration_cost"]["value"] == 20000
    assert report["input_event_ids"] and report["settings_version"] == 1
    later = reports.calculate({"starts_on": "2026-12-14", "ends_on": "2026-12-21"}, now=NOW + timedelta(days=20))
    assert later["metrics"]["registrations"]["value"] is None


def test_snapshot_recalculation_keeps_original_events_values_and_definition_versions():
    from marketing import reports
    settings = configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    frozen = reports.freeze(OWNER, "Week as confirmed", PERIOD, settings["version"], now=NOW)
    added = [{**row, "id": row["id"] + "-late", "subject_id": "late-user"} for row in fixture() if row["id"] in {"v0", "r0"}]
    reports.import_events(OWNER, added, [], now=NOW + timedelta(seconds=1))
    revised = reports.recompute(OWNER, frozen["id"], "Late confirmed registration", now=NOW + timedelta(seconds=2))
    assert revised["recomputed_from"] == frozen["id"]
    assert revised["report"]["metrics"]["registrations"]["value"] == 31
    with store.connection() as c:
        assert store.get(c, "snapshot", frozen["id"])["report"]["metrics"]["registrations"]["value"] == 30
    compared = reports.compare(frozen["id"], revised["id"])
    assert compared["metrics"]["registrations"]["difference"] == 1
    reports.save_settings(OWNER, config(attribution_days=30), settings["version"])
    current = reports.compare(frozen["id"], period=PERIOD, now=NOW + timedelta(seconds=3))
    assert not current["comparable"] and current["metrics"]["registration_cost"]["difference"] is None


def test_late_arrival_is_not_included_in_an_earlier_cutoff():
    from marketing import reports
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    at_cut = {**PERIOD, "cutoff": (NOW - timedelta(seconds=1)).isoformat()}
    assert reports.calculate(at_cut, now=NOW)["event_count"] == 0


def test_automatic_week_cut_is_once_per_closed_tashkent_week_and_survives_retry():
    from marketing import reports
    reports.save_settings(OWNER, config(automatic_weekly=True), 0)
    assert reports.freeze_closed_week(NOW)
    assert not reports.freeze_closed_week(NOW + timedelta(minutes=1))
    with store.connection() as c:
        saved = store.list_items(c, "snapshot")
        assert len(saved) == 1 and saved[0]["report"]["period"]["starts_on"] == "2026-11-30"
        assert saved[0]["report"]["period"]["ends_on"] == "2026-12-07"


def test_coverage_and_settings_do_not_allow_unprivileged_changes_or_future_confirmation():
    from marketing import reports
    with pytest.raises(MarketingError):
        reports.save_settings({"id": "analytics", "role": "analytics"}, config(), 0)
    with pytest.raises(MarketingError):
        reports.import_events(OWNER, [], [coverage(through=(NOW + timedelta(days=1)).isoformat())], now=NOW)
    review = {'confirmed': True, 'note': 'Owner checked a stable comparable base', 'period': '2025-11',
              'reviewed_at': '2099-12-01T00:00:00Z', 'currency': 'UZS', 'dataset': 'test',
              'legal_entities': ['ip', 'llc'], 'opening_customers': 10, 'lost_customers': 1,
              'monthly_rates': [{'period': f'2025-{month:02}', 'rate': .1, 'source': f'billing:{month}'} for month in (8, 9, 10)]}
    with pytest.raises(MarketingError, match='будущ'):
        reports.save_settings(OWNER, config(ltv_stability=review), 0)
    accepted = reports.save_settings(OWNER, config(ltv_stability={**review, 'reviewed_at': '2025-12-01T00:00:00Z'}), 0)
    assert accepted['version'] == 1


@pytest.mark.parametrize("completeness,closed,actual", [("complete", True, 30), ("incomplete", True, None), ("complete", False, None)])
def test_team_activity_and_goal_versions_are_bound_to_the_reporting_cut(monkeypatch, completeness, closed, actual):
    from marketing import reports, goals
    from test_marketing_core import goal_input
    configured()
    cut = NOW if closed else datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    events = [row for row in fixture() if datetime.fromisoformat(row["at"].replace("Z", "+00:00")) <= cut]
    reports.import_events(OWNER, events, [coverage(status=completeness, through=cut.isoformat())], now=cut)
    at = "2026-11-24T10:00:00+00:00"
    monkeypatch.setattr(store, "now", lambda: at)
    goals.save_goal(OWNER, goal_input(metric="registrations", unit="users", starts_on=PERIOD["starts_on"], deadline=PERIOD["ends_on"], target=100), 0)
    goals.approve_goal(OWNER, 1)
    with store.connection(write=True) as c:
        item = store.put(c, "candidate", {"id": "work-1", "status": "draft"}, actor=OWNER, action="candidate_created", expected_version=0)
        store.put(c, "candidate", {**item, "status": "skipped", "check": {"passed": False, "reason": "No source"}}, actor=OWNER, action="final_check", expected_version=1)
    frozen = reports.freeze(OWNER, "With decisions", PERIOD, 1, now=cut)
    report = frozen["report"]
    assert report["metrics"]["registrations"]["numerator"] == 30
    assert report["plan_fact"]["observed"] == (30 if completeness == "complete" else None)
    assert report["plan_fact"]["target"] == 100 and report["plan_fact"]["actual"] == actual
    assert report["plan_fact"]["difference"] == (None if actual is None else -70)
    assert report["team"]["created"] == 1 and report["team"]["skipped"] == 1
    assert report["goal"]["version"] == 2
    at = (cut + timedelta(seconds=1)).isoformat()
    goals.save_goal(OWNER, goal_input(metric="registrations", unit="users", target=200), 2)
    goals.approve_goal(OWNER, 3)
    earlier = reports.calculate({**PERIOD, "cutoff": cut.isoformat()}, now=cut + timedelta(seconds=2))
    assert earlier["goal"]["target"] == 100
    current = reports.calculate(PERIOD, now=cut + timedelta(seconds=2))
    assert current["plan_fact"]["actual"] is None  # No invented weekly share of a longer goal.


def test_report_task_has_aggregate_computed_inputs_and_owner_notes_preserve_versions(monkeypatch):
    import json
    from marketing import reports, agents
    from test_marketing_agents import Model, output
    from test_marketing_report_decisions import review
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    monkeypatch.setattr(store, "now", lambda: NOW.isoformat())
    saved = reports.save_review(OWNER, PERIOD, {"decisions": "Measure the baseline", "next_actions": "Compare the next closed week"}, 0)
    assert saved["version"] == 1
    task = reports.request_analysis(OWNER, PERIOD, now=NOW)
    assert task["report"]["metrics"]["registrations"]["value"] == 30
    assert "input_event_ids" not in task["report"]
    captured = []
    class Analyst(Model):
        def complete_json(self, system, user, **kwargs):
            captured.append(json.loads(user))
            return output("Confirmed registrations are 30")
    agents.run_one(Analyst([]), NOW)
    agents.run_one(Model([output("First measure, then adjust the plan", cmo_review=review())]), NOW)
    assert captured[0]["report"]["metrics"]["registrations"]["value"] == 30
    result = reports.calculate(PERIOD, now=NOW)
    assert result["review"]["decisions"] == "Measure the baseline"
    assert result["analysis"]["cmo"]["summary"] == "First measure, then adjust the plan"


def test_new_incomplete_source_notice_withdraws_old_full_coverage():
    from marketing import reports
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    reports.import_events(OWNER, [], [coverage(status="incomplete", history_complete=False,
        starts_on="2026-11-24", ends_on="2026-11-25", reference="A day was lost in the registration export")], now=NOW + timedelta(seconds=1))
    value = reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))["metrics"]["registrations"]
    assert value["value"] is None and value["status"] == "incomplete"


def test_comparison_refuses_to_compare_closed_week_with_partially_elapsed_different_week():
    from marketing import snapshots
    from test_marketing_analytics import report
    closed = report(fixture(), **config())
    partial = deepcopy(closed)
    partial["period"] = {"starts_on": "2026-12-07", "ends_on": "2026-12-14", "cutoff": NOW.isoformat(), "timezone": "Asia/Tashkent"}
    compared = snapshots.compare({"report": closed}, {"report": partial})
    assert not compared["comparable"] and compared["metrics"]["registrations"]["difference"] is None


def test_owner_source_correction_recomputes_derived_values_without_rewriting_original_cut():
    from marketing import reports
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    before = reports.freeze(OWNER, "Original invoice", PERIOD, 1, now=NOW)
    corrected = {**fixture()[0], "amount": 300000}
    amendment = {"event_id": "expense", "dataset": "test", "replacement": corrected, "reason": "Verified revised invoice", "expected_version": 0}
    reports.import_events(OWNER, [], [], corrections=[amendment], now=NOW + timedelta(seconds=1))
    current = reports.recompute(OWNER, before["id"], "Corrected expense source", now=NOW + timedelta(seconds=2))
    assert current["report"]["metrics"]["registration_cost"]["value"] == 10000
    assert before["report"]["metrics"]["registration_cost"]["value"] == 20000
    assert reports.calculate({**PERIOD, "cutoff": NOW.isoformat()}, now=NOW + timedelta(seconds=2))["metrics"]["registration_cost"]["value"] == 20000
    with pytest.raises(MarketingError, match="changed"):
        reports.import_events(OWNER, [], [], corrections=[amendment], now=NOW + timedelta(seconds=3))
    # Retraction has its own revision and does not delete the stored source event.
    reports.import_events(OWNER, [], [], corrections=[{**amendment, "replacement": None, "expected_version": 1, "reason": "Invoice was voided"}], now=NOW + timedelta(seconds=4))
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=5))["metrics"]["advertising_spend"]["value"] == 0
    with store.connection() as c:
        original = store.get(c, "event", store.digest(["test", "expense"]))
        assert original["event"]["amount"] == 600000
    reports.save_settings(OWNER, {"dataset": "production"}, 1)
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=6))["corrections"] == []


def test_conflicting_transaction_correction_rolls_back_entire_import_and_keeps_evidence():
    from marketing import reports
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    payment = next(row for row in fixture() if row["id"] == "p2")
    changes = [{"event_id": "p2", "dataset": "test", "replacement": {**payment, "amount": 1}, "expected_version": 0, "reason": "Incorrect copy"}]
    with pytest.raises(MarketingError, match="transaction"):
        reports.import_events(OWNER, [], [], corrections=changes, now=NOW + timedelta(seconds=1))
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))["metrics"]["revenue"]["value"] == 400000
    with store.connection() as c:
        assert not store.list_items(c, "event_correction")
