"""Each metric requires completeness for the dates and history it actually uses."""
from datetime import timedelta

import pytest

from marketing import reports, store
from test_marketing_core import OWNER, isolated  # noqa: F401
from test_marketing_analytics import event, fixture
from test_marketing_business_metrics import config, payment
from test_marketing_reports import NOW, PERIOD, configured, coverage


def period_coverage(**changes):
    return coverage(starts_on=PERIOD['starts_on'], ends_on=PERIOD['ends_on'], **changes)


def test_closed_period_counts_do_not_require_attribution_or_followup_windows():
    configured()
    reports.import_events(OWNER, fixture(), [period_coverage()], now=NOW)
    report = reports.calculate(PERIOD, now=NOW)
    for key, expected in [('visits', 30), ('registrations', 30), ('revenue', 400000), ('first_paying_customers', 3)]:
        assert report['metrics'][key]['value'] == expected, key
    assert report['entities']['ip']['revenue'] == 400000
    assert report['entities']['ip']['first_paying_customers'] == 3
    for key in ('activation', 'registration_to_payment', 'registration_cost', 'retention'):
        assert report['metrics'][key]['value'] is None, key
    cash = report['metrics']['revenue']['coverage']['payments']
    assert cash['starts_at'] == '2026-11-23T00:00:00+05:00'
    assert cash['ends_at'] == '2026-11-30T00:00:00+05:00'
    assert cash['history_required'] is False and cash['end_inclusive'] is False


def test_cash_can_be_complete_while_first_payer_history_is_unknown():
    configured()
    reports.import_events(OWNER, fixture(), [period_coverage(history_complete=False)], now=NOW)
    report = reports.calculate(PERIOD, now=NOW)
    assert report['metrics']['revenue']['value'] == 400000
    assert report['metrics']['first_paying_customers']['value'] is None
    assert report['entities']['ip']['revenue'] == 400000
    assert report['entities']['ip']['first_paying_customers'] is None


def test_retention_requires_prior_registrations_but_only_current_period_activity():
    reports.save_settings(OWNER, config(activation_days=30), 0)
    rows = fixture() + [event('prior', 'registration', 'prior', at='2026-11-17T00:00:00Z'),
                        event('return', 'report_open', 'prior', object_id='HMKB')]
    reports.import_events(OWNER, rows, [coverage(categories=['registrations'], starts_on='2026-11-16', ends_on='2026-11-30'),
        period_coverage(categories=['activity'])], now=NOW)
    report = reports.calculate(PERIOD, now=NOW)
    assert report['metrics']['retention']['value'] == 100
    assert report['metrics']['activation']['value'] is None
    assert report['metrics']['retention']['coverage']['activity']['starts_at'] == '2026-11-23T00:00:00+05:00'


def test_followup_ends_at_the_last_actual_cohort_window_and_ignores_later_gaps():
    configured()
    rows = fixture() + [event('boundary-open', 'report_open', 'user-0', at='2026-11-30T08:00:00Z', object_id='HMKB')]
    reports.import_events(OWNER, rows, [period_coverage(categories=['registrations']), coverage(categories=['activity', 'payments'],
        starts_on='2026-11-23', ends_on='2026-12-01', through='2026-11-30T08:00:00Z')], now=NOW)
    before = reports.calculate(PERIOD, now=NOW)
    assert before['metrics']['activation']['value'] == pytest.approx(100 / 30)
    assert before['metrics']['registration_to_payment']['value'] == 10
    required = before['metrics']['activation']['coverage']['activity']
    assert required['ends_at'] == '2026-11-30T08:00:00+00:00' and required['end_inclusive']
    assert before['metrics']['payback']['coverage']['payments']['ends_at'] == required['ends_at']
    reports.import_events(OWNER, [], [coverage(categories=['activity'], status='incomplete',
        starts_on='2026-12-04', ends_on='2026-12-05')], now=NOW + timedelta(seconds=1))
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))['metrics']['activation']['value'] == pytest.approx(100 / 30)


def test_inclusive_activation_deadline_cannot_use_coverage_ending_at_that_midnight():
    configured()
    rows = [event('registered', 'registration', 'a', at='2026-11-23T00:00:00+05:00'),
            event('open', 'report_open', 'a', at='2026-11-30T00:00:00+05:00', object_id='HMKB')]
    reports.import_events(OWNER, rows, [period_coverage()], now=NOW)
    assert reports.calculate(PERIOD, now=NOW)['metrics']['activation']['value'] is None
    reports.import_events(OWNER, [], [coverage(categories=['activity'], starts_on='2026-11-23', ends_on='2026-12-01',
        through='2026-11-30T00:00:00+05:00')], now=NOW + timedelta(seconds=1))
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))['metrics']['activation']['value'] == 100


def test_cash_attribution_requires_the_paying_customers_actual_acquisition_window():
    configured()
    rows = [event('old-visit', 'visit', 'a', at='2026-08-31T00:00:00Z', channel='telegram'),
            event('old-registration', 'registration', 'a', at='2026-09-01T00:00:00Z'),
            payment('current-payment', 'a', at='2026-11-25T00:00:00Z'), fixture()[0]]
    reports.import_events(OWNER, rows, [coverage(categories=['payments', 'expenses', 'registrations']),
        coverage(categories=['visits'], starts_on='2026-11-16', ends_on='2026-11-30')], now=NOW)
    assert reports.calculate(PERIOD, now=NOW)['metrics']['roas']['value'] is None
    reports.import_events(OWNER, [], [coverage(categories=['visits'], starts_on='2026-08-25', ends_on='2026-09-02')], now=NOW + timedelta(seconds=1))
    assert reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))['metrics']['roas']['value'] == pytest.approx(1 / 6)


def test_historical_gap_withdraws_unique_customer_history_but_not_current_cash():
    configured()
    reports.import_events(OWNER, fixture(), [coverage()], now=NOW)
    reports.import_events(OWNER, [], [coverage(categories=['registrations', 'payments'], status='incomplete', history_complete=False,
        starts_on='2026-09-01', ends_on='2026-09-02', reference='Historical first-event history was lost')], now=NOW + timedelta(seconds=1))
    report = reports.calculate(PERIOD, now=NOW + timedelta(seconds=2))
    assert report['metrics']['registrations']['status'] == 'incomplete'
    assert report['metrics']['first_paying_customers']['status'] == 'incomplete'
    assert report['metrics']['revenue']['value'] == 400000
    assert reports.calculate({**PERIOD, 'cutoff': NOW.isoformat()}, now=NOW + timedelta(seconds=2))['metrics']['registrations']['value'] == 30


def test_service_income_needs_coverage_of_later_adjustments_and_invalidates_stale_analysis(monkeypatch):
    from marketing import agents
    from test_marketing_agents import Model, output
    from test_marketing_report_decisions import review
    configured()
    period = {'starts_on': '2026-11-01', 'ends_on': '2026-12-01'}
    rows = [payment('regular', 'a', 120000, revenue_kind='recurring', service_starts_at='2026-11-01T00:00:00+05:00',
                    service_ends_at='2026-12-01T00:00:00+05:00'),
            event('later-refund', 'refund', 'a', at='2026-12-03T00:00:00Z', transaction_id='refund-regular',
                  related_transaction_id='regular', amount=20000, legal_entity='ip')]
    reports.import_events(OWNER, rows, [coverage(ends_on='2026-12-01')], now=NOW)
    monkeypatch.setattr(store, 'now', lambda: NOW.isoformat())
    frozen = reports.freeze(OWNER, 'Incomplete service cut', period, 1, now=NOW)
    before = frozen['report']
    assert before['metrics']['revenue']['value'] == 120000
    assert before['metrics']['arppu']['value'] is None
    reports.request_analysis(OWNER, period, now=NOW)
    agents.run_one(Model([output('Refund coverage is incomplete')]), NOW)
    proposal = review()
    proposal['decisions'][0].update(metric_ids=['arppu'], subject='Полнота возвратов', next_action='Сверить выгрузку возвратов после окончания месяца.')
    proposal['hypotheses'][0].update(metric_ids=['arppu'], success_metric='arppu', kind='measurement',
        statement='Неполное окно может скрывать корректировки дохода.', test_plan='Сверить оригинальные транзакции и дату последнего возврата.',
        success_criterion='Полнота окна подтверждена оригинальной выгрузкой.')
    agents.run_one(Model([output('Confirm the missing refund window', cmo_review=proposal)]), NOW)
    assert reports.calculate(period, now=NOW)['analysis']['cmo']['cmo_review']['basis']['metrics']['arppu']['value'] is None
    reports.import_events(OWNER, [], [coverage(ends_on='2026-12-04', through='2026-12-03T00:00:00Z')], now=NOW + timedelta(seconds=1))
    after = reports.calculate(period, now=NOW + timedelta(seconds=2))
    assert after['sources'] == before['sources']
    assert after['metrics']['arppu']['value'] == 100000
    assert after['metrics']['arppu']['coverage']['payments']['ends_at'] == '2026-12-03T00:00:00+00:00'
    assert after['context_digest'] != before['context_digest']
    assert after['analysis'] is None
    with store.connection() as c:
        assert store.get(c, 'snapshot', frozen['id'])['report']['metrics']['arppu']['value'] is None


def test_publication_only_coverage_gap_invalidates_analysis_context_without_changing_kpis():
    configured()
    period = {'starts_on': '2026-11-23', 'ends_on': '2026-11-30'}
    rows = [event('tagged', 'publication_visit', 'a', at='2026-11-26T06:00:00Z', publication_id='post-a', channel='telegram'),
            event('registered', 'registration', 'a', at='2026-11-26T08:00:00Z'),
            payment('first', 'a', 100000, at='2026-11-27T08:00:00Z')]
    reports.import_events(OWNER, rows, [coverage(starts_on='2026-11-01', ends_on='2026-12-10')], now=NOW)
    before = reports.calculate(period, now=NOW)
    assert before['publication_attribution']['status'] == 'complete'
    reports.import_events(OWNER, [], [coverage(categories=['visits'], starts_on='2026-11-16', ends_on='2026-11-17',
        status='incomplete', history_complete=False, reference='Earlier publication arrivals were lost')], now=NOW+timedelta(seconds=1))
    after = reports.calculate(period, now=NOW+timedelta(seconds=2))
    def measured(report):
        return {key: {field: value[field] for field in ('value', 'status', 'coverage')} for key, value in report['metrics'].items()}
    assert measured(after) == measured(before)
    assert after['publication_attribution']['status'] == 'incomplete'
    assert after['context_digest'] != before['context_digest']


def test_first_payer_channel_counts_require_the_earlier_acquisition_window():
    configured()
    rows = [event('old-visit', 'visit', 'a', at='2026-08-31T00:00:00Z', channel='telegram'),
            event('old-registration', 'registration', 'a', at='2026-09-01T00:00:00Z'),
            payment('current-first', 'a', 100000, at='2026-11-25T00:00:00Z')]
    reports.import_events(OWNER, rows, [period_coverage()], now=NOW)
    before = reports.calculate(PERIOD, now=NOW)
    assert before['metrics']['first_paying_customers']['value'] == 1
    assert before['channels']['telegram']['first_paying_customers'] == 1
    basis = before['count_basis']['channel_first_payers']
    assert basis['status'] == 'incomplete'
    assert basis['coverage']['visits']['starts_at'] == '2026-08-25T00:00:00+00:00'
    reports.import_events(OWNER, [], [coverage(categories=['visits', 'registrations'], starts_on='2026-08-25', ends_on='2026-09-02')], now=NOW+timedelta(seconds=1))
    after = reports.calculate(PERIOD, now=NOW+timedelta(seconds=2))
    assert after['count_basis']['channel_first_payers']['status'] == 'complete'
