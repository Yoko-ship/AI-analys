"""Metric evidence follows actual cohort, service and subscription inputs."""
import pytest

from test_marketing_analytics import event, report
from test_marketing_business_metrics import config, monthly, payment, sub


def tagged(key, kind, subject='', **kwargs):
    return event(key, kind, subject, source=key, **kwargs)


@pytest.mark.parametrize('key,expected', [
    ('visits', {'current-visit'}),
    ('registrations', {'cohort-registration'}),
    ('visit_to_registration', {'current-visit', 'cohort-registration'}),
    ('activation', {'cohort-registration', 'activation-use'}),
    ('retention', {'prior-registration', 'retained-use'}),
])
def test_product_provenance_respects_the_actual_cohort_and_action_window(key, expected):
    rows = [
        tagged('prior-registration', 'registration', 'prior', at='2026-11-18T00:00:00Z'),
        tagged('cohort-registration', 'registration', 'new'),
        tagged('current-visit', 'visit', 'new'),
        tagged('activation-use', 'report_open', 'new', at='2026-11-30T08:00:00Z', object_id='HMKB'),
        tagged('too-late-use', 'report_open', 'new', at='2026-12-01T00:00:00Z', object_id='HMKB'),
        tagged('retained-use', 'report_open', 'prior', at='2026-11-26T00:00:00Z', object_id='HMKB'),
        tagged('unselected-action', 'chart_open', 'new', object_id='HMKB'),
        tagged('unfinished', 'registration_started', 'unfinished'),
        tagged('old-visit', 'visit', 'old', at='2026-10-01T00:00:00Z'),
        tagged('later-visit', 'visit', 'later', at='2026-12-01T00:00:00Z'),
    ]
    metric = report(rows, **config())['metrics'][key]
    assert set(metric['source_ids']) == expected
    assert metric['updated_at'] == max(row['at'] for row in rows if row['source'] in expected)


@pytest.mark.parametrize('key,expected', [
    ('revenue', {'service', 'one-off'}),
    ('first_paying_customers', {'service', 'one-off', 'foreign'}),
    ('arpu', {'service', 'later-refund', 'active-reader'}),
    ('arppu', {'service', 'later-refund'}),
    ('mrr', {'active-plan', 'cancelled-plan'}),
    ('arr', {'active-plan', 'cancelled-plan'}),
    ('churn', {'active-plan', 'opening-plan', 'cancelled-plan'}),
])
def test_financial_provenance_separates_cash_service_and_subscription_bases(key, expected):
    rows = [
        payment('service', 'a', 120000, source='service', revenue_kind='recurring', gross_profit=72000,
                service_starts_at='2026-11-01T00:00:00+05:00', service_ends_at='2026-12-01T00:00:00+05:00'),
        payment('one-off', 'b', 500000, source='one-off', payment_type='first', revenue_kind='one_off'),
        tagged('later-refund', 'refund', 'a', at='2026-12-03T00:00:00Z', amount=20000,
               transaction_id='later-refund', related_transaction_id='service', legal_entity='ip'),
        payment('foreign', 'c', 10, source='foreign', currency='USD'),
        payment('before-launch', 'd', 100, source='before-launch', legal_entity='unknown'),
        payment('old-cash', 'old', 200, source='old-cash', at='2026-10-01T00:00:00Z', revenue_kind='one_off'),
        tagged('active-reader', 'report_open', 'a', object_id='HMKB'),
        tagged('unused-action', 'chart_open', 'b', object_id='HMKB'),
        sub('superseded-plan', 'a', 50000, source='superseded-plan', at='2026-09-01T00:00:00Z'),
        sub('active-plan', 'a', 100000, source='active-plan'),
        sub('opening-plan', 'b', 50000, source='opening-plan'),
        sub('cancelled-plan', 'b', 50000, source='cancelled-plan', at='2026-11-10T00:00:00Z', subscription_state='cancelled'),
        sub('future-plan', 'future', 100000, source='future-plan', at='2026-12-05T00:00:00Z'),
    ]
    metric = monthly(rows)['metrics'][key]
    # An excluded financial row blocks monetized completeness today; it must
    # be identified as a blocking input, not silently omitted from the proof.
    assert set(metric['source_ids']) == expected | {'before-launch'}
    assert metric['updated_at'] == max(row['at'] for row in rows if row['source'] in expected | {'before-launch'})


def test_zero_metric_has_no_unrelated_source_or_freshness_date():
    rows = [tagged('old-visit', 'visit', 'old', at='2026-10-01T00:00:00Z'),
            tagged('unfinished', 'registration_started', 'pending')]
    metrics = report(rows, **config())['metrics']
    for key in ('visits', 'registrations', 'advertising_spend'):
        assert metrics[key]['value'] == 0
        assert metrics[key]['source_ids'] == []
        assert metrics[key]['updated_at'] is None


@pytest.mark.parametrize('key,expected', [
    ('registration_cost', {'ad', 'registered', 'arrival'}),
    ('advertising_cac', {'ad', 'registered', 'arrival', 'first'}),
    ('full_cac', {'ad', 'sales', 'registered', 'arrival', 'first'}),
    ('registration_to_payment', {'registered', 'first'}),
    ('roas', {'ad', 'registered', 'arrival', 'first', 'renewal'}),
    ('roi', {'ad', 'sales', 'registered', 'arrival', 'first', 'renewal'}),
    ('payback', {'ad', 'sales', 'registered', 'arrival', 'first', 'service-refund'}),
])
def test_acquisition_provenance_keeps_cost_cohort_and_income_scopes_distinct(key, expected):
    rows = [tagged('arrival', 'publication_visit', 'a', at='2026-11-01T00:00:00Z', publication_id='post', channel='telegram'),
            tagged('registered', 'registration', 'a', at='2026-11-02T00:00:00Z'),
            payment('first', 'a', source='first', at='2026-11-04T00:00:00Z', gross_profit=60000, revenue_kind='recurring',
                    service_starts_at='2026-11-01T00:00:00+05:00', service_ends_at='2026-12-01T00:00:00+05:00'),
            payment('renewal', 'a', source='renewal', at='2026-11-09T00:00:00Z', gross_profit=60000, payment_type='renewal', revenue_kind='one_off'),
            tagged('ad', 'expense', at='2026-11-06T00:00:00Z', amount=100000, category='advertising', channel='telegram'),
            tagged('sales', 'expense', at='2026-11-07T00:00:00Z', amount=50000, category='sales', channel='telegram'),
            tagged('other-ad', 'expense', at='2026-11-08T00:00:00Z', amount=20000, category='advertising', channel='linkedin'),
            tagged('service-refund', 'refund', 'a', at='2026-12-03T00:00:00Z', amount=10000, legal_entity='ip',
                   transaction_id='refund-first', related_transaction_id='first'),
            tagged('late-arrival', 'visit', 'a', at='2026-12-05T00:00:00Z', channel='telegram'),
            payment('later-receipt', 'b', source='later-receipt', at='2026-12-08T00:00:00Z')]
    metric = monthly(rows)['metrics'][key]
    assert set(metric['source_ids']) == expected
    assert metric['updated_at'] == max(row['at'] for row in rows if row['source'] in expected)
