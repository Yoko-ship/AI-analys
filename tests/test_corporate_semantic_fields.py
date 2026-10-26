"""Field extraction is checked against issuer filings, not just invented shapes."""
import json
from pathlib import Path
import pytest
import corporate_events as ce

SAMPLES=json.loads((Path(__file__).parent/'fixtures/openinfo/semantic_facts.json').read_text())

@pytest.mark.parametrize('sample',SAMPLES,ids=lambda x:str(x['global_id']))
def test_real_disclosure_fields_have_source_paths_and_distinct_summaries(sample):
    event=ce.from_fact(sample['raw'],source_url=sample['source_url'])
    assert event['extraction_version'] >= 2
    assert event['facts']
    assert all(f['source_field'] and f['label']['en'] and f['value'] is not None for f in event['facts'])
    assert event['summary'] != event['title']
    assert event['priority_explanation']['en']


def sample(code,index=0):
    return [x['raw'] for x in SAMPLES if int(x['raw']['fact_number'])==code][index]


def test_registry_covers_all_46_forms_including_empty_public_types():
    from corporate_event_fields import SCHEMAS
    assert set(SCHEMAS)==set(range(1,47))
    for code in SCHEMAS:
        event=ce.from_fact({'fact_number':code,'id':123,'pub_date':'2026-10-26','decision_date':'2026-10-25'})
        assert event['confidence']=='review'  # A date and a code alone are insufficient.
        assert event['priority_provisional']


def test_voluntary_license_return_is_distinct_from_enforced_suspension():
    returned=ce.from_fact(sample(23));suspended=ce.from_fact(sample(24))
    assert returned['priority']==1 and returned['priority_reason']=='voluntary_license_return'
    assert suspended['priority']==0 and not suspended['priority_provisional']
    assert suspended['event_date']=='2026-08-25'


def test_issue_amendment_without_quantity_or_value_change_is_administrative():
    event=ce.from_fact(sample(40))
    assert event['priority']==2 and event['priority_reason']=='unchanged_issue_size'
    changed=ce.from_fact({**sample(40),'securities_count_after':'160000000'})
    assert changed['priority']==1 and changed['priority_reason']=='changed_issue_size'


def test_real_credit_and_transaction_percentages_keep_their_distinct_bases():
    loan=ce.from_fact(sample(15));deal=ce.from_fact(sample(20))
    assert any(f['source_field']=='loan_capital' and f['value']==176.19 and f['unit']=='percent' for f in loan['facts'])
    assert any(f['source_field']=='assets_issuer' and f['value']==64.93 for f in deal['facts'])
    assert loan['priority']==deal['priority']==1
    assert loan['event_date']=='2026-09-12' and deal['decision_date']=='2026-10-16'
    assert deal['event_date']=='2026-10-21'


def test_declared_ownership_is_extracted_without_inventing_a_previous_stake():
    event=ce.from_fact(sample(43))
    assert any(f['source_field']=='securities_percent' and f['value']==98.55 for f in event['facts'])
    assert event['event_date']=='2026-09-22'
    assert all('before' not in f['source_field'] for f in event['facts'])


def test_unknown_unit_never_becomes_per_share_income_and_malformed_values_stay_missing():
    event=ce.from_fact({**sample(20),'transaction_amount':'1,234,567.89','assets_issuer':'not known'})
    assert not event['amounts']
    assert any(f['value']==1234567.89 and f['unit']=='source_units' for f in event['facts'])
    assert not any(f['source_field']=='assets_issuer' for f in event['facts'])


def test_null_nested_tables_and_unknown_code_are_safe():
    event=ce.from_fact({**sample(6),'facts_decisions_wording':None})
    assert event['confidence']=='review'
    assert ce.from_fact({'fact_number':999})['confidence']=='review'


def test_wrong_form_body_keeps_evidence_but_does_not_confirm_the_named_event():
    raw=next(x['raw'] for x in SAMPLES if x['global_id']==84524)
    event=ce.from_fact(raw)
    assert event['facts']
    assert event['confidence']=='review' and event['priority_provisional']


@pytest.mark.parametrize('value',['1e999','Infinity','NaN',True,'1,2,3'])
def test_invalid_or_unrepresentable_numbers_are_not_evidence(value):
    from corporate_event_fields import numeric
    assert numeric(value) is None


def test_blank_resolution_rows_are_not_content_evidence():
    event=ce.from_fact({**sample(6),'facts_decisions_wording':[{'decisions_wording':'','question_name':'Dividends?'}]})
    assert event['confidence']=='review' and event['priority_provisional']


def test_resolution_mentioning_shareholders_does_not_imply_capital_change():
    event=ce.from_fact({**sample(6),'facts_decisions_wording':[{'decisions_wording':'Shareholders approved the meeting secretary.'}]})
    assert event['priority']==2


def test_real_nested_fields_show_the_event_content_not_only_a_row_count():
    for code,field in [(6,'decisions_wording'),(8,'position'),(17,'akt_name'),(34,'to_change_num')]:
        event=ce.from_fact(sample(code))
        assert any(f['source_field'].endswith('.'+field) for f in event['facts'])


def test_nonvoluntary_license_cancellation_keeps_critical_priority():
    event=ce.from_fact({**sample(23),'revocation_reason':'Лицензия аннулирована по решению уполномоченного органа.'})
    assert event['priority']==0


def test_summary_identifies_undocumented_amount_units_and_empty_table_rows_stay_review():
    event=ce.from_fact(sample(20))
    assert 'source units' in event['summary']['en']
    event=ce.from_fact({**sample(8),'factscaseelection':[{'num':1}],'factsterminationpowers':[]})
    assert event['confidence']=='review' and event['priority_provisional']


@pytest.mark.parametrize('code,body,priority',[(26,{'suspension_reason':'Decision to suspend this issue','paper_num':100},1),(46,{'facts_decisions_wording':[{'decisions_wording':'Approve the procurement procedure.'}]},2)])
def test_sparse_public_types_have_explicit_contracts_without_invented_historical_samples(code,body,priority):
    event=ce.from_fact({'fact_number':code,'id':1,'pub_date':'2026-10-26',**body})
    assert event['facts'] and event['priority']==priority and event['confidence']=='confirmed'


def test_real_asset_growth_over_100_percent_is_not_an_ownership_percentage():
    raw=next(x['raw'] for x in SAMPLES if x['global_id']==99257)
    event=ce.from_fact(raw)
    assert [f['value'] for f in event['facts'] if f['source_field'].endswith('.prosent')]==[197,150,133,124]
    ownership=ce.from_fact({**sample(34),'factsshareinauthorized':[{'to_change_pro':197,'after_change_pro':150}]})
    assert not any(f['unit']=='percent' for f in ownership['facts'])


def test_table_evidence_keeps_original_row_indexes_after_ignoring_empty_rows():
    event=ce.from_fact({**sample(6),'facts_decisions_wording':[{'decisions_wording':''},{'decisions_wording':'Appoint the meeting secretary.'}]})
    assert any(f['source_field']=='facts_decisions_wording.1.decisions_wording' for f in event['facts'])


def test_invalid_ownership_values_alone_cannot_confirm_a_holding_change():
    event=ce.from_fact({**sample(34),'factsshareinauthorized':[{'to_change_pro':197,'after_change_pro':150}]})
    assert event['confidence']=='review'
