"""Spec §7: real denominators, late events, monetization gates, immutable cuts."""
from copy import deepcopy

import pytest

from marketing import analytics, snapshots, store
from marketing.errors import MarketingError
from test_marketing_core import OWNER, isolated  # noqa: F401

SETTINGS = {"dataset": "test", "currency": "UZS", "monetization_live": True,
            "shared_customer_ids": True, "entity_launches": {"ip": "2026-01-01T00:00:00Z", "llc": "2026-01-01T00:00:00Z"},
            "legal_entities": ["ip", "llc"], "attribution_model": "last_non_direct", "attribution_days": 7,
            "conversion_days": 7, "activation_event": "report_open", "formula_version": "1",
            "source_status": {"visits": "complete", "registrations": "complete", "payments": "complete", "expenses": "complete"}}


def event(key, kind, subject="", at="2026-11-23T08:00:00Z", **kwargs):
    return {"id": key, "kind": kind, "subject_id": subject, "at": at, "dataset": "test",
            "traffic": "external", "source": "acceptance-fixture", "confirmed": True, **kwargs}


def fixture():
    events = [event("expense", "expense", amount=600000, currency="UZS", category="advertising", legal_entity="ip", channel="telegram")]
    for i in range(30):
        events.append(event(f"v{i}", "visit", f"user-{i}", at="2026-11-23T07:00:00Z", channel="telegram"))
        events.append(event(f"r{i}", "registration", f"user-{i}"))
    for i in range(3):
        events.append(event(f"p{i}", "payment", f"user-{i}", at="2026-11-25T08:00:00Z", transaction_id=f"txn-{i}",
                            amount=100000, currency="UZS", legal_entity="ip", payment_type="first"))
    events.append(event("renewal", "payment", "user-0", at="2026-11-26T08:00:00Z", transaction_id="renewal-txn",
                        amount=100000, currency="UZS", legal_entity="ip", payment_type="renewal"))
    events.append({**events[-2], "id": "duplicate-transaction"})
    return events


def report(events, **changes):
    return analytics.calculate_report(events, starts_on="2026-11-23", ends_on="2026-11-30",
                                      cutoff="2026-12-08T00:00:00Z", settings={**SETTINGS, **changes})


def test_registration_cost_cac_and_conversion_use_distinct_confirmed_denominators():
    result = report(fixture())
    assert result["metrics"]["registration_cost"]["value"] == 20000
    assert result["metrics"]["advertising_cac"]["value"] == 200000
    assert result["metrics"]["registration_to_payment"]["value"] == 10
    assert result["metrics"]["first_paying_customers"]["value"] == 3
    assert result["metrics"]["revenue"]["value"] == 400000
    assert result["metrics"]["advertising_cac"]["denominator"] == 3
    assert result["metrics"]["full_cac"]["value"] is None
    assert result["metrics"]["roi"]["value"] is None


def test_publication_arrivals_use_last_non_direct_touch_without_inflating_platform_clicks():
    rows = [
        event('a1', 'publication_visit', 'reader-a', at='2026-11-23T06:00:00Z', publication_id='post-a', channel='telegram'),
        event('b1', 'publication_visit', 'reader-a', at='2026-11-23T07:00:00Z', publication_id='post-b', channel='linkedin', promotion='paid'),
        event('a2', 'publication_visit', 'reader-a', at='2026-11-23T07:30:00Z', publication_id='post-a', channel='telegram'),
        event('direct', 'visit', 'reader-a', at='2026-11-23T07:45:00Z', channel='direct'),
        event('registered', 'registration', 'reader-a'),
        event('a3', 'publication_visit', 'reader-b', at='2026-11-23T06:00:00Z', publication_id='post-a', channel='telegram'),
        event('other', 'visit', 'reader-b', at='2026-11-23T07:00:00Z', channel='linkedin'),
        event('registered-b', 'registration', 'reader-b'),
        event('team', 'publication_visit', 'owner', publication_id='post-a', channel='telegram', traffic='internal'),
        event('impressions', 'impression', publication_id='post-a', channel='telegram', count=100),
        event('clicks', 'click', publication_id='post-a', channel='telegram', count=10),
    ]
    result = report(rows, source_status={**SETTINGS['source_status'], 'visits': 'incomplete', 'clicks': 'complete', 'impressions': 'complete'})
    publications = {row['publication_id']: row for row in result['publication_attribution']['rows']}
    assert publications['post-a']['observed_arrivals'] == 3
    assert publications['post-a']['attributed_registrations'] == 1
    assert publications['post-b']['observed_arrivals'] == 1 and publications['post-b']['attributed_registrations'] == 0
    assert publications['post-b']['promotion'] == 'paid'
    assert result['publication_attribution']['status'] == 'incomplete'
    assert result['publication_attribution']['unattributed_registrations'] == 1
    assert result['channels']['telegram']['registrations'] == result['channels']['linkedin']['registrations'] == 1
    assert list(result['content_results'].values())[0]['observations']['click'] == 10
    assert list(result['content_results'].values())[0]['ctr']['value'] == 10


def test_zero_missing_and_not_applicable_remain_distinct():
    events = [e for e in fixture() if e["kind"] != "payment"]
    assert report(events)["metrics"]["first_paying_customers"]["value"] == 0
    assert report(events)["metrics"]["advertising_cac"]["value"] is None
    unavailable = report(events, source_status={**SETTINGS["source_status"], "payments": "unavailable"})
    assert unavailable["metrics"]["first_paying_customers"]["value"] is None
    assert unavailable["metrics"]["first_paying_customers"]["status"] == "unavailable"
    before_launch = report(fixture(), monetization_live=False)
    assert before_launch["metrics"]["advertising_cac"]["status"] == "not_applicable"
    assert before_launch["metrics"]["registrations"]["value"] == 30
    assert report([])["metrics"]["visit_to_registration"]["value"] is None


def test_internal_traffic_and_budget_are_excluded_but_traceable():
    events = fixture() + [event("internal", "visit", "staff", traffic="internal"), event("bot", "visit", "bot", traffic="automated"),
                          event("budget", "budget", amount=3000000, currency="UZS")]
    result = report(events)
    assert result["metrics"]["visits"]["value"] == 30
    assert result["metrics"]["advertising_spend"]["value"] == 600000
    assert result["excluded_events"] == 2


def test_late_payment_has_event_week_and_acquisition_cohort_without_rewriting_history():
    events = [event("visit", "visit", "a", channel="telegram"), event("reg", "registration", "a"),
              event("pay", "payment", "a", at="2026-11-30T08:00:00Z", transaction_id="late", amount=100000,
                    currency="UZS", legal_entity="ip", payment_type="first")]
    result = report(events)
    assert result["metrics"]["first_paying_customers"]["value"] == 0
    assert result["metrics"]["registration_to_payment"]["value"] == 100
    assert result["cohorts"]["paid_customers"] == 1
    assert result["channels"]["telegram"]["registrations"] == 1
    second = analytics.calculate_report(events, starts_on="2026-11-30", ends_on="2026-12-07",
                                       cutoff="2026-12-08T00:00:00Z", settings=SETTINGS)
    assert second["metrics"]["first_paying_customers"]["value"] == 1
    assert second["channels"]["telegram"]["first_paying_customers"] == 1


def test_immature_cohort_is_not_presented_as_final_conversion():
    result = analytics.calculate_report(fixture(), starts_on="2026-11-23", ends_on="2026-11-30",
                                       cutoff="2026-11-25T12:00:00Z", settings=SETTINGS)
    assert result["metrics"]["registration_to_payment"]["status"] == "incomplete"


def test_legal_entities_are_separate_and_client_total_is_deduplicated():
    events = fixture() + [event("llc", "payment", "user-0", at="2026-11-27T08:00:00Z", transaction_id="llc-first",
                               amount=200000, currency="UZS", legal_entity="llc", payment_type="first")]
    result = report(events)
    assert result["entities"]["ip"]["first_paying_customers"] == 3
    assert result["entities"]["llc"]["first_paying_customers"] == 1
    assert result["metrics"]["first_paying_customers"]["value"] == 3
    assert result["metrics"]["revenue"]["value"] == 600000


def test_durable_ingestion_deduplicates_and_rejects_conflicting_events():
    value = event("same", "visit", "a")
    analytics.ingest_events(OWNER, [value, value])
    with store.connection() as c:
        assert len(store.list_items(c, "event")) == 1
    with pytest.raises(MarketingError, match="different"):
        analytics.ingest_events(OWNER, [{**value, "subject_id": "another"}])


def test_snapshots_are_immutable_corrections_preserve_original_and_comparison_checks_method():
    first = snapshots.freeze(OWNER, "Неделя 1", report(fixture()))
    empty = report([])
    empty["period"] = {**empty["period"], "starts_on": "2026-11-30", "ends_on": "2026-12-07"}
    second = snapshots.freeze(OWNER, "Неделя 2", empty)
    result = snapshots.compare(first, second)
    assert result["comparable"]
    assert result["metrics"]["registrations"]["difference"] == -30
    assert result["metrics"]["registrations"]["relative_percent"] == -100
    incompatible = deepcopy(second)
    incompatible["report"]["method"]["attribution_days"] = 30
    assert not snapshots.compare(first, incompatible)["comparable"]
    changed = snapshots.correct(OWNER, first["id"], {"registrations": 29}, "Удалён подтверждённый дубль", 0)
    assert changed["original_id"] == first["id"]
    with store.connection() as c:
        assert store.get(c, "snapshot", first["id"])["report"]["metrics"]["registrations"]["value"] == 30
        assert len(store.list_items(c, "snapshot")) == 2
