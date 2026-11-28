"""Unknown acquisition evidence is not an observed zero return."""
import pytest

from test_marketing_analytics import event, report
from test_marketing_business_metrics import config
from test_marketing_core import isolated  # noqa: F401


def acquisition_case(*, touch=None, registration=True):
    rows = [event('ad-spend', 'expense', amount=1000, category='advertising', channel='telegram'),
            event('paid', 'payment', 'customer', amount=5000, transaction_id='confirmed-payment',
                  payment_type='first', legal_entity='ip', gross_profit=2000, at='2026-11-24T08:00:00Z')]
    if registration:
        rows.append(event('registered', 'registration', 'customer'))
    if touch:
        rows.append(event('touch', 'visit', 'customer', channel=touch, at='2026-11-23T07:00:00Z'))
    return rows


@pytest.mark.parametrize('registration', [True, False])
def test_confirmed_cash_with_unknown_acquisition_is_not_complete_zero_roas_or_minus_100_roi(registration):
    result = report(acquisition_case(registration=registration), **config())
    assert result['metrics']['revenue']['value'] == 5000
    assert result['metrics']['advertising_spend']['value'] == 1000
    for key in ('roi', 'roas', 'advertising_cac', 'full_cac'):
        metric = result['metrics'][key]
        assert metric['value'] is None and metric['status'] == 'incomplete', key
        assert metric['attribution']['unresolved_customers'] == 1
    assert result['metrics']['roas']['numerator'] is None
    assert result['metrics']['roas']['denominator'] == 1000
    assert result['metrics']['advertising_cac']['denominator'] is None


@pytest.mark.parametrize('channel', ['direct', 'linkedin'])
def test_known_outside_scope_and_direct_sources_allow_measured_zero_return(channel):
    result = report(acquisition_case(touch=channel), **config())
    assert result['metrics']['roas']['value'] == 0
    assert result['metrics']['roi']['value'] == -100
    assert result['metrics']['roi']['attribution']['status'] == 'complete'
    assert result['channels'][channel]['registrations'] == 1


def test_no_revenue_with_complete_inputs_is_a_measured_zero_not_missing_attribution():
    result = report([event('cost', 'expense', amount=1000, category='advertising', channel='telegram')], **config())
    assert result['metrics']['roas']['value'] == 0
    assert result['metrics']['roi']['value'] == -100
    assert result['metrics']['roas']['attribution']['customers'] == 0


@pytest.mark.parametrize('latest', ['unknown', 'conflicting'])
def test_later_unknown_or_simultaneous_conflicting_touches_cannot_reuse_an_earlier_known_source(latest):
    rows = acquisition_case(touch='telegram')
    at = '2026-11-23T07:30:00Z'
    rows.append(event('later-a', 'visit', 'customer', channel='unknown' if latest == 'unknown' else 'telegram', at=at))
    if latest == 'conflicting':
        rows.append(event('later-b', 'visit', 'customer', channel='linkedin', at=at))
    result = report(rows, **config())
    assert result['channels']['unknown']['registrations'] == 1
    assert result['metrics']['roas']['value'] is None
    assert result['metrics']['registration_cost']['value'] is None
    assert result['metrics']['registration_cost']['attribution']['unresolved_customers'] == 1


def test_earlier_unknown_and_later_direct_touches_do_not_override_a_known_non_direct_source():
    rows = acquisition_case(touch='telegram') + [
        event('earlier', 'visit', 'customer', channel='unknown', at='2026-11-23T06:00:00Z'),
        event('direct', 'visit', 'customer', channel='direct', at='2026-11-23T07:30:00Z')]
    result = report(rows, **config())
    assert result['metrics']['roi']['value'] == 100
    assert result['metrics']['roas']['value'] == 5
    assert result['channels']['telegram']['registrations'] == 1


def test_partial_attribution_cannot_turn_known_subtotals_into_complete_channel_kpis():
    rows = acquisition_case(touch='telegram') + [event('other-reg', 'registration', 'unlinked'),
        event('other-pay', 'payment', 'unlinked', at='2026-11-24T09:00:00Z', transaction_id='other-payment',
              amount=3000, gross_profit=1000, payment_type='first', legal_entity='ip')]
    result = report(rows, **config())
    assert result['metrics']['revenue']['value'] == 8000
    for key in ('roi', 'roas', 'registration_cost', 'advertising_cac', 'full_cac'):
        assert result['metrics'][key]['value'] is None, key
        assert result['metrics'][key]['attribution']['customers'] == 2
        assert result['metrics'][key]['attribution']['unresolved_customers'] == 1


def test_unknown_nonpaying_registrations_and_unrelated_receipts_do_not_block_paid_customer_metrics():
    rows = acquisition_case(touch='telegram') + [
        event('unpaid-reg', 'registration', 'unpaid'),
        event('old-pay', 'payment', 'old', at='2026-10-01T00:00:00Z', transaction_id='old', amount=600, payment_type='first', legal_entity='ip'),
        event('foreign-pay', 'payment', 'foreign', transaction_id='foreign', currency='USD', amount=20, payment_type='first', legal_entity='ip'),
        event('zero-pay', 'payment', 'zero', transaction_id='zero', amount=0, payment_type='first', legal_entity='ip')]
    rows.append(event('zero-known', 'payment', 'customer', transaction_id='zero-known', amount=0, payment_type='renewal', legal_entity='ip'))
    result = report(rows, **config())
    assert result['metrics']['registration_cost']['value'] is None
    assert result['metrics']['advertising_cac']['value'] == 1000
    assert result['metrics']['roas']['value'] == 5
    assert result['metrics']['roi']['value'] == 100


def test_payment_cannot_borrow_acquisition_from_a_later_registration():
    rows = acquisition_case(touch='telegram')
    rows[1]['at'] = '2026-11-23T05:00:00Z'
    result = report(rows, **config())
    assert result['metrics']['revenue']['value'] == 5000
    assert result['metrics']['roi']['value'] is None
    assert result['metrics']['roi']['attribution']['reasons'][0]['code'] == 'registration_after_payment'


@pytest.mark.parametrize('publications', [('a', 'b'), ('a', 'a')])
def test_equal_time_publications_can_prove_the_channel_without_guessing_the_publication(publications):
    rows = acquisition_case()
    for index, post in enumerate(publications):
        rows.append(event('arrival-' + str(index), 'publication_visit', 'customer', at='2026-11-23T07:00:00Z',
                          channel='telegram', publication_id=post))
    result = report(rows, **config())
    assert result['metrics']['roas']['value'] == 5
    ambiguous = len(set(publications)) > 1
    assert result['publication_attribution']['unattributed_registrations'] == int(ambiguous)
    assert result['publication_attribution']['status'] == ('incomplete' if ambiguous else 'complete')
    assert sum(row['attributed_registrations'] for row in result['publication_attribution']['rows']) == int(not ambiguous)


def test_observed_counts_keep_their_numbers_but_expose_independent_completeness():
    settings = config()
    settings['source_status']['visits'] = 'incomplete'
    result = report(acquisition_case(touch='telegram'), **settings)
    assert result['channels']['telegram'] == {'registrations': 1, 'first_paying_customers': 1}
    assert result['cohorts'] == {'registrations': 1, 'paid_customers': 1}
    basis = result['count_basis']
    assert basis['channel_registrations']['status'] == 'incomplete'
    assert basis['channel_first_payers']['status'] == 'incomplete'
    assert basis['cohort_registrations']['status'] == 'complete'
    assert basis['cohort_paid_customers']['status'] == 'complete'
    missing_identity = report(acquisition_case(), **config())
    assert missing_identity['count_basis']['channel_registrations']['status'] == 'incomplete'
    assert missing_identity['count_basis']['cohort_registrations']['status'] == 'complete'
    before_launch = report(acquisition_case(), **config(monetization_live=False))
    assert before_launch['count_basis']['channel_first_payers']['status'] == 'not_applicable'
    assert before_launch['count_basis']['cohort_paid_customers']['status'] == 'not_applicable'
