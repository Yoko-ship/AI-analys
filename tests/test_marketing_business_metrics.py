"""Specification §7 formulas with comparable scopes and explicit data quality."""
from copy import deepcopy

import pytest

from marketing import analytics
from marketing.errors import MarketingError
from test_marketing_analytics import SETTINGS, event, fixture, report
from test_marketing_core import isolated  # noqa: F401


def config(**changes):
    return {**SETTINGS, "activation_days": 7, "retention_days": 7,
            "activity_events": ["report_open"], "cost_categories": ["advertising", "marketing", "sales"],
            "cost_allocation": "event_channel", "acquisition_channels": ["telegram"], "shared_customer_ids": True,
            "entity_launches": {"ip": "2026-01-01T00:00:00Z", "llc": "2026-01-01T00:00:00Z"},
            "source_status": {**SETTINGS["source_status"], "activity": "complete", "impressions": "complete",
                              "clicks": "complete", "subscriptions": "complete", "margin": "complete"}, **changes}


def monthly(events, **settings):
    return analytics.calculate_report(events, starts_on="2026-11-01", ends_on="2026-12-01",
        cutoff="2026-12-15T00:00:00Z", settings=config(**settings))


def sub(key, subject, amount, months=1, *, at="2026-10-01T00:00:00Z", start="2026-10-01T00:00:00Z", end="2027-10-01T00:00:00Z", **changes):
    return event(key, "subscription", subject, at=at, subscription_id=subject, amount=amount, billing_months=months,
                 service_starts_at=start, service_ends_at=end, legal_entity="ip", **changes)


def payment(key, subject, amount=100000, **changes):
    return event(key, "payment", subject, **{"at": "2026-11-01T00:00:00Z", "amount": amount, "payment_type": "first",
                 "transaction_id": key, "legal_entity": "ip", **changes})


def test_activation_counts_first_use_once_within_its_registered_cohort_window():
    events = fixture() + [event("open", "report_open", "user-0", at="2026-11-24T08:00:00Z", object_id="HMKB:report"),
                          event("open-again", "report_open", "user-0", at="2026-11-25T08:00:00Z", object_id="HMKB:report"),
                          event("late", "report_open", "user-1", at="2026-12-05T08:00:00Z", object_id="HMKB:report")]
    metric = report(events, **config())["metrics"]["activation"]
    assert metric["value"] == pytest.approx(100 / 30)
    assert metric["numerator"] == 1 and metric["denominator"] == 30
    immature = analytics.calculate_report(events, starts_on="2026-11-23", ends_on="2026-11-30", cutoff="2026-11-25T10:00:00Z", settings=config())
    assert immature["metrics"]["activation"]["status"] == "incomplete"
    still_open = analytics.calculate_report([
        event('early-reg', 'registration', 'early', at='2026-11-01T00:00:00Z'),
        event('early-use', 'report_open', 'early', at='2026-11-02T00:00:00Z', object_id='HMKB')],
        starts_on='2026-11-01', ends_on='2026-12-01', cutoff='2026-11-25T10:00:00Z', settings=config())
    assert still_open['metrics']['activation']['status'] == 'incomplete'


def test_ctr_joins_the_same_publication_and_does_not_treat_unmatched_clicks_as_impressions():
    events = [event("shown", "impression", publication_id="post-a", channel="telegram", count=200),
              event("clicked", "click", publication_id="post-a", channel="telegram", count=10),
              event("other", "click", publication_id="post-b", channel="telegram", count=90)]
    result = report(events, **config())
    assert result["metrics"]["ctr"]["value"] == 5
    assert result["content_results"]["telegram:post-b"]["ctr"]["value"] is None
    assert result["content_results"]["telegram:post-b"]["observations"]["impression"] is None


def test_confirmed_zero_platform_snapshot_is_distinct_from_absent_click_observations():
    window = {"observation_mode": "snapshot", "observed_starts_at": "2026-11-23T00:00:00+05:00", "observed_ends_at": "2026-11-23T08:00:00Z"}
    observed = event("shown", "impression", publication_id="zero-clicks", count=200, **window)
    zero = event("zero", "click", publication_id="zero-clicks", count=0, **window)
    assert report([observed, zero], **config())["metrics"]["ctr"]["value"] == 0
    assert report([observed], **config())["metrics"]["ctr"]["value"] is None


def test_unallocated_ad_spend_does_not_become_free_acquisition_or_confirmed_roi():
    events = fixture()
    events[0]["channel"] = "unknown"
    result = report(events, **config())
    assert result["metrics"]["advertising_spend"]["value"] == 600000
    assert result["metrics"]["registration_cost"]["value"] is None
    assert result["metrics"]["advertising_cac"]["value"] is None


def test_each_metric_names_its_actual_input_sources_not_unrelated_uploads():
    events = fixture()
    events[0]["source"] = "advertising-ledger"
    events[1].update(kind='publication_visit', publication_id='approved-post', source='published-link-receipts')
    events.extend([
        event('old-reg', 'registration', 'past', at='2026-10-01T00:00:00Z', source='old-registration'),
        event('newer-start', 'registration_started', 'incomplete', at='2026-12-01T00:00:00Z', source='unfinished-form'),
        event('later-reg', 'registration', 'future-period', at='2026-12-01T00:00:00Z', source='next-week'),
        event('other-cost', 'expense', amount=90, category='other', source='unrelated-cost'),
        event('foreign-cost', 'expense', amount=40, currency='USD', category='advertising', source='usd-ledger'),
        event('old-cost', 'expense', amount=10, category='advertising', at='2026-10-01T00:00:00Z', source='old-expense'),
        event('other-channel-cost', 'expense', amount=70, category='advertising', channel='facebook', source='facebook-expense'),
    ])
    result = report(events, **config())
    assert result["metrics"]["registrations"]["source_ids"] == ["acceptance-fixture"]
    assert set(result["metrics"]["registration_cost"]["source_ids"]) == {"acceptance-fixture", "advertising-ledger", "published-link-receipts"}
    assert result['metrics']['registrations']['updated_at'] == '2026-11-23T08:00:00Z'
    assert set(result['metrics']['advertising_spend']['source_ids']) == {'advertising-ledger', 'facebook-expense'}


def test_retention_uses_the_prior_registration_cohort_and_excludes_new_users():
    events = [event("old-a", "registration", "a", at="2026-11-16T08:00:00Z"),
              event("old-b", "registration", "b", at="2026-11-17T08:00:00Z"),
              event("new", "registration", "new"), event("use-a", "report_open", "a", object_id="HMKB"),
              event("use-new", "report_open", "new", object_id="HMKB")]
    metric = report(events, **config())["metrics"]["retention"]
    assert metric["value"] == 50 and metric["denominator"] == 2


def test_full_cac_roi_and_roas_use_actual_agreed_expenses_and_confirmed_margin():
    events = fixture() + [event("sales", "expense", amount=300000, category="sales", channel="telegram", legal_entity="ip")]
    for row in events:
        if row["kind"] == "payment":
            row["gross_profit"] = row["amount"] * 0.6
    result = report(events, **config())
    assert result["metrics"]["full_cac"]["value"] == 300000
    assert result["metrics"]["roas"]["value"] == pytest.approx(400000 / 600000)
    assert result["metrics"]["roi"]["value"] == pytest.approx((240000 - 900000) / 900000 * 100)
    no_margin = deepcopy(events)
    for row in no_margin:
        row.pop("gross_profit", None)
    assert report(no_margin, **config())["metrics"]["roi"]["value"] is None


def test_mrr_normalizes_annual_plans_excludes_cancelled_one_off_and_other_currency():
    events = [sub("annual", "a", 1200000, months=12), sub("monthly", "b", 50000),
              sub("cancelled", "c", 200000, subscription_state="cancelled"),
              sub("foreign", "d", 100, currency="USD"), payment("one-off", "e", payment_type="one_off")]
    result = monthly(events)
    assert result["metrics"]["mrr"]["value"] == 150000
    assert result["metrics"]["arr"]["value"] == 1800000


def test_regular_revenue_arpu_and_arppu_use_service_periods_and_actual_active_users():
    start, end = "2026-11-01T00:00:00+05:00", "2026-12-01T00:00:00+05:00"
    events = [payment("regular", "a", 120000, revenue_kind="recurring", service_starts_at=start, service_ends_at=end, gross_profit=72000),
              payment("oneoff", "b", 1000000, payment_type="one_off"),
              event("use-a", "report_open", "a", object_id="HMKB"), event("use-b", "report_open", "b", object_id="HMKB"),
              event("renewal", "payment", "a", transaction_id="future-service", amount=120000, payment_type="renewal", legal_entity="ip",
                    revenue_kind="recurring", service_starts_at=end, service_ends_at="2027-01-01T00:00:00+05:00")]
    result = monthly(events)
    assert result["metrics"]["arpu"]["value"] == 60000
    assert result["metrics"]["arppu"]["value"] == 120000
    refund = event("refund", "refund", "a", transaction_id="refund-regular", related_transaction_id="regular", amount=20000, legal_entity="ip")
    assert monthly(events + [refund])["metrics"]["arppu"]["value"] == 100000


@pytest.mark.parametrize('changes,code', [
    ({'amount': 120001}, 'refund_exceeds_payment'),
    ({'subject_id': 'another-customer'}, 'refund_identity_mismatch'),
    ({'legal_entity': 'llc'}, 'refund_entity_mismatch'),
    ({'currency': 'USD'}, 'refund_currency_mismatch'),
    ({'at': '2026-10-31T18:00:00Z'}, 'refund_before_payment'),
    ({'related_transaction_id': 'missing-payment'}, 'refund_payment_missing'),
])
def test_unreconciled_refunds_cannot_manufacture_revenue_or_service_margin(changes, code):
    original = payment('regular', 'a', 120000, revenue_kind='recurring', gross_profit=72000,
                       service_starts_at='2026-11-01T00:00:00+05:00', service_ends_at='2026-12-01T00:00:00+05:00')
    refund = {**event('refund', 'refund', 'a', transaction_id='refund-regular', related_transaction_id='regular',
                     amount=20000, legal_entity='ip'), **changes}
    result = monthly([original, refund])
    assert any(issue['code'] == code for issue in result['financial_issues'])
    assert result['metrics']['revenue']['value'] is None
    assert result['metrics']['arppu']['value'] is None
    assert result['metrics']['revenue']['status'] == 'unavailable'
    assert result['entities']['ip']['revenue'] is None
    # The confirmed payment still happened; a broken refund does not erase its customer.
    assert result['metrics']['first_paying_customers']['value'] == 1


def test_refund_limit_is_cumulative_decimal_exact_and_a_later_cash_refund_can_be_negative():
    paid = payment('small', 'a', 0.3, currency='USD', gross_profit=0.2)
    refunds = [event(f'refund-{i}', 'refund', 'a', transaction_id=f'r{i}', related_transaction_id='small',
                     amount=amount, currency='USD', legal_entity='ip') for i, amount in enumerate([0.1, 0.2])]
    balanced = monthly([paid, *refunds], currency='USD')
    assert balanced['financial_issues'] == [] and balanced['metrics']['revenue']['value'] == 0
    excess = {**refunds[0], 'id': 'extra', 'transaction_id': 'extra', 'amount': 0.01}
    assert monthly([paid, *refunds, excess], currency='USD')['metrics']['revenue']['value'] is None
    old = {**paid, 'at': '2026-10-01T00:00:00Z'}
    result = monthly([old, *refunds], currency='USD')
    assert result['metrics']['revenue']['value'] == pytest.approx(-0.3)
    assert result['financial_issues'] == []


def test_old_refund_problem_does_not_block_an_unrelated_period_or_currency():
    old = payment('old', 'old', 100, at='2026-08-01T00:00:00Z', currency='USD')
    bad = event('old-refund', 'refund', 'old', at='2026-08-02T00:00:00Z', transaction_id='bad',
                related_transaction_id='old', amount=101, legal_entity='ip', currency='USD')
    current = payment('current', 'a', 120000)
    result = monthly([old, bad, current])
    assert result['metrics']['revenue']['value'] == 120000
    assert result['financial_issues'] == []


def test_expenses_are_separate_by_entity_and_unknown_costs_are_not_assigned_to_a_company():
    rows = [event('ip-ad', 'expense', amount=600000, category='advertising', channel='telegram', legal_entity='ip'),
            event('llc-sales', 'expense', amount=300000, category='sales', channel='telegram', legal_entity='llc'),
            event('unknown-ad', 'expense', amount=100000, category='advertising', channel='telegram'),
            event('foreign', 'expense', amount=50, currency='USD', legal_entity='ip')]
    result = monthly(rows, monetization_live=False)
    assert result['entities']['ip']['expense_total'] == 600000
    assert result['entities']['llc']['expense_total'] == 300000
    assert result['unassigned_expenses']['expense_total'] == 100000
    assert result['metrics']['advertising_spend']['value'] == 700000
    assert result['entities']['ip']['revenue'] is None
    incomplete = monthly(rows, source_status={**config()['source_status'], 'expenses': 'incomplete'})
    assert incomplete['entities']['ip']['expense_total'] is None


def test_incomplete_sources_do_not_override_missing_identity_or_calculation_requirements():
    cfg = config(source_status={**config()['source_status'], 'expenses': 'incomplete'})
    rows = fixture()
    rows[0]['channel'] = 'unknown'
    result = report(rows, **cfg)
    assert result['metrics']['registration_cost']['status'] == 'unavailable'
    assert result['metrics']['registration_cost']['numerator'] is None
    cfg = config(shared_customer_ids=False, source_status={**config()['source_status'], 'payments': 'incomplete'})
    assert report(fixture(), **cfg)['metrics']['first_paying_customers']['status'] == 'not_comparable'


def test_zero_value_receipt_is_not_a_new_paying_customer():
    service = {'revenue_kind': 'recurring', 'service_starts_at': '2026-11-01T00:00:00+05:00',
               'service_ends_at': '2026-12-01T00:00:00+05:00'}
    free = payment('free-receipt', 'a', 0, **service)
    result = monthly([free])
    assert result['metrics']['first_paying_customers']['value'] == 0
    assert result['entities']['ip']['first_paying_customers'] == 0
    mixed = monthly([free, payment('paid-service', 'b', 100000, **service)])
    assert mixed['metrics']['arppu']['denominator'] == 1
    assert mixed['metrics']['arppu']['value'] == 100000


def test_churn_uses_opening_paid_base_and_ignores_new_customers_cancelled_same_month():
    events = [sub("old-a", "a", 100000), sub("old-b", "b", 100000), sub('free-plan', 'free', 0),
              sub('cancel-free', 'free', 0, at='2026-11-15T00:00:00Z', subscription_state='cancelled'),
              sub("cancel-a", "a", 100000, at="2026-11-15T00:00:00Z", subscription_state="cancelled"),
              sub("new-c", "c", 100000, at="2026-11-10T00:00:00Z", start="2026-11-10T00:00:00Z"),
              sub("cancel-c", "c", 100000, at="2026-11-20T00:00:00Z", start="2026-11-10T00:00:00Z", subscription_state="cancelled")]
    metric = monthly(events)["metrics"]["churn"]
    assert metric["value"] == 50 and metric["numerator"] == 1 and metric["denominator"] == 2
    downgraded = monthly([*events, sub('paid-to-free', 'b', 0, at='2026-11-20T00:00:00Z')])
    assert downgraded['metrics']['churn']['value'] == 100
    assert downgraded['metrics']['mrr']['value'] == 0


def test_premature_monetization_missing_sources_and_separate_customer_id_spaces_are_not_facts():
    events = fixture()
    result = report(events, **config(entity_launches={}))
    assert result["metrics"]["revenue"]["value"] is None
    assert result["metrics"]["revenue"]["status"] == "not_applicable"
    result = report(events, **config(shared_customer_ids=False))
    assert result["metrics"]["first_paying_customers"]["value"] is None
    assert result["entities"]["ip"]["first_paying_customers"] == 3
    result = report(events, **config(source_status={"expenses": "complete"}))
    assert result["entities"]["ip"]["revenue"] is None


def test_changed_transaction_date_cannot_silently_move_money_between_periods():
    events = [payment("tx", "a"), {**payment("tx", "a"), "id": "other-copy", "at": "2026-12-01T08:00:00Z"}]
    with pytest.raises(MarketingError, match="Conflicting"):
        monthly(events)


def test_channel_scoped_acquisition_cost_never_borrows_another_channels_expense():
    events = fixture() + [event("facebook-cost", "expense", amount=900000, category="advertising", channel="facebook", legal_entity="ip")]
    result = report(events, **config())
    assert result["metrics"]["advertising_spend"]["value"] == 1500000
    assert result["metrics"]["registration_cost"]["value"] == 20000
    assert result["metrics"]["advertising_cac"]["value"] == 200000


def test_cumulative_platform_snapshots_replace_the_same_window_without_adding_unique_reach():
    window = {"observation_mode": "snapshot", "observed_starts_at": "2026-11-23T00:00:00+05:00", "observed_ends_at": "2026-11-24T00:00:00+05:00"}
    events = [event("old", "impression", at="2026-11-24T00:00:00Z", publication_id="a", channel="telegram", count=200, **window),
              event("new", "impression", at="2026-11-25T00:00:00Z", publication_id="a", channel="telegram", count=220, **window),
              event("click", "click", at="2026-11-25T00:00:00Z", publication_id="a", channel="telegram", count=22, **window),
              event("reach-a", "reach", at="2026-11-25T00:00:00Z", publication_id="a", channel="telegram", count=150, **window),
              event("reach-b", "reach", at="2026-11-25T00:00:00Z", publication_id="b", channel="facebook", count=150, **window)]
    for row in events:
        row['source'] = row['id']
    events.append(event('another-post', 'click', publication_id='unmatched', channel='linkedin', source='unmatched-click', at='2026-11-29T00:00:00Z'))
    events.append(event('another-window', 'click', publication_id='a', channel='telegram', source='unmatched-window', count=1,
                        observation_mode='snapshot', observed_starts_at='2026-11-26T00:00:00Z',
                        observed_ends_at='2026-11-27T00:00:00Z', at='2026-11-28T00:00:00Z'))
    result = report(events, **config())
    assert result["metrics"]["ctr"]["value"] == 10
    assert result["content_results"]["telegram:a"]["observations"]["impression"] == 220
    assert "unique_reach" not in result
    assert result['metrics']['ctr']['source_ids'] == ['click', 'new']
    assert result['content_results']['telegram:a']['ctr']['source_ids'] == ['click', 'new']
    assert result['metrics']['ctr']['updated_at'] == '2026-11-25T00:00:00Z'
    assert result['content_results']['linkedin:unmatched']['ctr']['source_ids'] == ['unmatched-click']


def test_payback_does_not_borrow_old_customers_service_margin_for_a_new_cohort():
    events = fixture()
    for row in events:
        if row["kind"] == "payment":
            row["revenue_kind"] = "one_off"
    events.append(payment("older-client", "old", amount=1000000, revenue_kind="recurring", service_starts_at="2026-11-01T00:00:00+05:00",
                          service_ends_at="2026-12-01T00:00:00+05:00", gross_profit=900000))
    assert monthly(events)["metrics"]["payback"]["value"] is None


def test_ltv_is_an_explicit_estimate_and_payback_needs_monthly_confirmed_contribution():
    events = [sub(f"old-{i}", f"old-{i}", 100000) for i in range(10)]
    events += [sub("cancel", "old-0", 100000, at="2026-11-15T00:00:00Z", subscription_state="cancelled"),
               event("ad", "expense", amount=600000, category="advertising", channel="telegram", legal_entity="ip"),
               event("sales", "expense", amount=300000, category="sales", channel="telegram", legal_entity="ip")]
    for user in ["a", "b", "c"]:
        events += [event(f"v-{user}", "visit", user, at="2026-10-31T18:00:00Z", channel="telegram"),
                   event(f"r-{user}", "registration", user, at="2026-11-01T00:00:00+05:00"),
                   payment(f"p-{user}", user, revenue_kind="recurring", service_starts_at="2026-11-01T00:00:00+05:00",
                           service_ends_at="2026-12-01T00:00:00+05:00", gross_profit=60000)]
    stability = {"confirmed": True, "note": "Сверены три закрытых месяца с одинаковой клиентской базой.",
                 'period': '2026-11', 'reviewed_at': '2026-12-02T00:00:00Z', 'currency': 'UZS', 'dataset': 'test',
                 'legal_entities': ['ip', 'llc'], 'opening_customers': 10, 'lost_customers': 1,
                 "monthly_rates": [{"period": f"2026-{month:02}", "rate": 0.1, "source": f"billing:{month}"} for month in [8, 9, 10]]}
    for row in events:
        row['source'] = row['id']
    result = monthly(events, ltv_stability=stability)
    assert result["metrics"]["ltv"]["value"] == 600000
    assert result["metrics"]["ltv"]["estimate"] is True
    from marketing import report_activity
    from marketing.permissions import timestamp
    from test_marketing_core import goal_input
    goal = goal_input(metric="ltv", unit="currency", currency="UZS", target=700000,
                      starts_on="2026-11-01", deadline="2026-12-01")
    progress = report_activity.goal_progress(goal, result, timestamp("2026-12-01T00:00:00+05:00"),
                                            timestamp(result["period"]["cutoff"]))
    assert progress["actual"] is None and progress["difference"] is None
    assert set(result['metrics']['ltv']['source_ids']) == {
        *(f'old-{i}' for i in range(10)), 'cancel', 'p-a', 'p-b', 'p-c', 'billing:8', 'billing:9', 'billing:10'}
    assert result["metrics"]["payback"]["value"] == 5
    assert monthly(events)["metrics"]["ltv"]["value"] is None
    zero_churn = [row for row in events if row["id"] != "cancel"]
    assert monthly(zero_churn, ltv_stability=stability)["metrics"]["ltv"]["value"] is None
    stale = {**stability, 'monthly_rates': [{**row, 'period': row['period'].replace('2026', '2025')} for row in stability['monthly_rates']]}
    assert monthly(events, ltv_stability=stale)['metrics']['ltv']['value'] is None
    for change in [{'currency': 'USD'}, {'dataset': 'production'}, {'legal_entities': ['ip']}, {'period': '2026-10'},
                   {'reviewed_at': '2026-11-20T00:00:00Z'}, {'reviewed_at': '2026-12-16T00:00:00Z'},
                   {'reviewed_at': None}, {'opening_customers': 9}, {'lost_customers': 2}]:
        metric = monthly(events, ltv_stability={**stability, **change})['metrics']['ltv']
        assert metric['value'] is None and metric['status'] == 'unavailable', change
    legacy = {key: stability[key] for key in ('confirmed', 'note', 'monthly_rates')}
    assert monthly(events, ltv_stability=legacy)['metrics']['ltv']['value'] is None
