"""Investor-facing disclosure semantics, including the PDF's real examples."""
import json
from pathlib import Path

import pytest

import corporate_events as ce

FIXTURES = Path(__file__).parent / "fixtures/openinfo"


def recommendations():
    return json.loads((FIXTURES / "event_recommendations.json").read_text())


def test_all_46_official_codes_have_exactly_one_category():
    assert set(ce.FACTS) == set(range(1, 47))
    assert len(ce.CATEGORIES) == 8
    for code, spec in ce.FACTS.items():
        assert spec["category"] in ce.CATEGORIES
        assert spec["priority"] in range(4)
        assert all(spec["title"].get(lang) for lang in ("ru", "en", "uz"))
    assert ce.FACTS[41]["category"] == "dividends"
    assert ce.FACTS[39]["priority"] == 0


def test_uzgf_recommendation_is_not_approval_despite_portal_approved_status():
    event = ce.from_fact(recommendations()[0])
    assert event["code"] == 41  # API type=49 is NOT the public code.
    assert event["stage"] == "proposed"
    assert event["amounts"] == [{"security": "ordinary", "amount": 8.01}, {"security": "preferred", "amount": 71.5}]
    assert event["published_at"].startswith("2026-07-06")
    assert event["decision_date"] == "2026-06-22"
    assert event["source_url"] == "https://openinfo.uz/ru/facts/41/577"
    assert event["record_date"] is None and event["ex_dividend_date"] is None
    assert event["tickers"] == ["UZGF", "UZGFP"]


def test_tkvk_no_distribution_is_a_proposal_not_a_zero_payment():
    event = ce.from_fact(recommendations()[1])
    assert event["stage"] == "proposed"
    assert event["distribution"] == "not_proposed"
    assert event["amounts"] == []
    assert "не выплачивать" in event["title"]["ru"]


def test_hmkb_notice_keeps_meeting_register_dates_out_of_dividend_entitlement():
    notice = json.loads((FIXTURES / "hmkb_20828.json").read_text())
    event = ce.from_announcement({"announcement_id": "20828", "org_id": "8", "ticker": "HMKB",
                                  "pub_date": "2026-06-01T16:16:00", "meeting_date": "2026-06-25T15:00:00"}, notice)
    assert event["stage"] == "agenda"
    assert event["category"] == "dividends"
    assert event["period"] == "2025"
    assert event["event_date"] == "2026-06-25"
    assert event["published_at"].startswith("2026-06-01")
    assert event["record_date"] is None and event["amounts"] == []


@pytest.mark.parametrize("code,stage", [(31, "scheduled"), (32, "accrued"), (41, "proposed"), (42, "payment_disclosed")])
def test_disclosure_stages_are_distinct(code, stage):
    event = ce.from_fact({"fact_number": code, "id": 1, "status": "approved"})
    assert event["stage"] == stage
    assert event["confidence"] == "review"


def test_unrecognised_code_and_ambiguous_approval_are_reviewed():
    assert ce.from_fact({"fact_number": 99})["confidence"] == "review"
    event = ce.from_fact({"fact_number": 6, "status": "approved", "title": "Вопрос дивидендов"})
    assert event["stage"] == "decision_disclosed"
    assert event["amounts"] == []


def test_grouping_never_merges_unrelated_same_day_deals_or_missing_periods():
    first = ce.from_fact({"fact_number": 21, "id": 1, "organization": 8, "pub_date": "2026-06-01"})
    second = ce.from_fact({"fact_number": 21, "id": 2, "organization": 8, "pub_date": "2026-06-01"})
    assert len(ce.group_stories([first, second])) == 2
    a, b = [ce.from_fact(r) for r in recommendations()]
    b.update(issuer_id=a["issuer_id"])
    assert len(ce.group_stories([a, b])) == 2
    a.update(period="2025")
    b.update(period="2025", stage="accrued")
    stories = ce.group_stories([a, b, dict(a)])
    assert len(stories) == 1
    assert len(stories[0]["documents"]) == 2
    assert {x["stage"] for x in stories[0]["documents"]} == {"proposed", "accrued"}


def test_store_preserves_revisions_and_does_not_replace_evidence_with_legacy(monkeypatch, tmp_path):
    import catalogue.storage as cs
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    event = ce.from_fact(recommendations()[0])
    ce.save_documents([event])
    ce.save_documents([event])
    revised = {**event, "amounts": [{"security": "ordinary", "amount": 9.0}]}
    ce.save_documents([revised])
    stored = ce.read_documents("2026-07-01", "2026-08-01")
    assert len(stored) == 1
    assert len(stored[0]["revisions"]) == 2
    assert stored[0]["amounts"][0]["amount"] == 9
    ce.save_documents([{**revised, "confidence": "review", "amounts": []}])
    assert ce.read_documents("2026-07-01", "2026-08-01")[0]["amounts"][0]["amount"] == 9


def test_collector_preserves_each_document_even_when_editorial_story_is_grouped(monkeypatch):
    from collectors.news import filings, facts, issuers
    import openinfo_http
    rows = [{"id": n, "object_id": n, "organization": 399, "organization_short_name": "UZGF",
             "fact_number": 41, "fact_short_title": "Рекомендация НС", "pub_date": "2026-07-06T15:00:00"}
            for n in (101, 102)]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"results": rows}
    monkeypatch.setattr(openinfo_http, "get", lambda *a, **k: Response())
    monkeypatch.setattr(issuers, "_openinfo_ticker_map", lambda: {"399": ["UZGF", "UZGFP"]})
    monkeypatch.setattr(facts, "_fact_detail", lambda n: {**recommendations()[0], "id": n, "fact_identifier": f"f-41-{n}"})
    items = filings.fetch_openinfo({}, 10)
    assert len(items) == 1
    docs = items[0]["disclosure_documents"]
    assert len(docs) == 2
    assert len({d["source_url"] for d in docs}) == 2
    assert all(d["amounts"][0]["amount"] == 8.01 for d in docs)


def test_news_ingestion_persists_source_documents(monkeypatch, tmp_path):
    import catalogue.storage as cs
    import news_store
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    document = ce.from_fact(recommendations()[0])
    news_store.upsert_news([{"url": "https://openinfo.uz/ru/organizations/399?fact=1",
                            "title": "UZGF: recommendation", "source_id": "openinfo_facts",
                            "disclosure_documents": [document]}])
    assert ce.read_documents("2026-07-01", "2026-08-01")[0]["stage"] == "proposed"


def test_public_api_serves_classified_stories_and_validates_range(monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setattr(ce, "feed", lambda start, end: {"ok": True, "items": ce.group_stories([ce.from_fact(recommendations()[0])])})
    result = TestClient(api.app).get("/api/news/corporate-events")
    assert result.status_code == 200
    assert result.json()["items"][0]["stage"] == "proposed"


def test_refresh_reads_existing_announcement_and_keeps_agenda(monkeypatch, tmp_path):
    import catalogue.storage as cs
    import meetings
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    row = {"announcement_id": "20828", "org_id": "8", "ticker": "HMKB", "pub_date": "2026-06-01", "meeting_date": "2026-06-25"}
    ce.save_documents([ce.from_announcement(row)])
    monkeypatch.setattr(meetings, "announcement_detail", lambda *a: json.loads((FIXTURES / "hmkb_20828.json").read_text()))
    event = ce.refresh_document("https://openinfo.uz/ru/announce/20828")
    assert event["stage"] == "agenda" and event["period"] == "2025"
    assert len(event["revisions"]) == 2


@pytest.mark.parametrize("detail", [{}, {"title": "OpenInfo", "content": []}])
def test_empty_announcement_response_preserves_confirmed_evidence(monkeypatch, tmp_path, detail):
    import catalogue.storage as cs
    import meetings
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    row = {"announcement_id": "20828", "org_id": "8", "ticker": "HMKB", "pub_date": "2026-06-01", "meeting_date": "2026-06-25"}
    original = ce.from_announcement(row, json.loads((FIXTURES / "hmkb_20828.json").read_text()))
    ce.save_documents([original])
    monkeypatch.setattr(meetings, "announcement_detail", lambda *a: detail)
    with pytest.raises(RuntimeError, match="Source unavailable"):
        ce.refresh_document(original["source_url"])
    saved = ce.read_documents("2026-06-01", "2026-06-02")[0]
    assert saved["confidence"] == "confirmed" and saved["stage"] == "agenda"
    assert len(saved["revisions"]) == 1


@pytest.mark.parametrize("source", ["https://evil.test/x", "https://openinfo.uz.evil.test/ru/announce/1", "file:///etc/passwd", "https://openinfo.uz/ru/announce/99999999"])
def test_refresh_does_not_fetch_arbitrary_or_unstored_sources(source, monkeypatch, tmp_path):
    import catalogue.storage as cs
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    with pytest.raises(ValueError):
        ce.refresh_document(source)


def test_security_filters_use_registry_even_without_dividend_amounts():
    document = ce.from_fact({"fact_number": 23, "id": 1}, tickers=["HMKB"])
    bond = ce.from_fact({"fact_number": 21, "id": 2}, tickers=["TESTB"])
    unknown = ce.from_fact({"fact_number": 6, "id": 3}, tickers=["UNKNOWNP"])
    ce.attach_securities([document, bond, unknown], {"HMKB": {"share_type": "ordinary", "isin": "UZ7011340005"}, "TESTB": {"share_type": "ordinary"}}, {"TESTB": {"type": "bond"}})
    assert document["security_types"] == ["stock"]
    assert document["isins"] == ["UZ7011340005"]
    assert bond["security_types"] == ["bond"]
    assert unknown["security_types"] == []


def stage_fixtures():
    return json.loads((FIXTURES / 'event_stages.json').read_text())


def test_hmkb_42_148_reports_completed_payment_from_consistent_amounts():
    event = ce.from_fact(stage_fixtures()[0])
    assert event['stage'] == 'paid'
    assert event['payment_start'] == '2024-12-26'
    assert event['payment_end'] == '2025-02-24'
    assert event['payment']['paid'] == 6060825
    assert event['payment']['unit'] == 'thousand_uzs'
    assert event['amounts'] == []  # aggregate is never a per-share dividend


@pytest.mark.parametrize('change', [{'overall_paid_sum':'0'}, {'overall_debt_sum':'10'}, {'overall_paid_percent':'101'}])
def test_inconsistent_payment_totals_never_claim_paid(change):
    event = ce.from_fact({**stage_fixtures()[0], **change})
    assert event['stage'] == 'payment_disclosed'
    assert event['confidence'] == 'review'


def test_uzmk_actual_resolutions_approve_dividends_without_guessing_share_amounts_or_deadline():
    event = ce.from_fact(stage_fixtures()[1])
    assert event['stage'] == 'approved'
    assert event['category'] == 'dividends'
    assert event['period'] == '2025'
    assert event['capitalization_disclosed'] is True
    assert event['amounts'] == []  # totals for each class, not sums per share
    assert event['payment_end'] is None  # "within sixty days" is not an explicit date
    assert event['summary']['en'] and event['evidence']
    assert event['priority_provisional'] is False


def test_administrative_resolution_is_not_dividend_approval():
    event = ce.from_fact(stage_fixtures()[2])
    assert event['stage'] == 'decision_disclosed'
    assert event['category'] == 'governance'
    assert event['priority'] == 2


def test_agat_bond_accrual_keeps_its_own_payment_window_and_no_zero_dividend_from_saxovat():
    bond = ce.from_fact(stage_fixtures()[3])
    assert bond['payment_start'] == '2026-10-21'
    assert bond['payment_end'] == '2026-11-03'
    assert bond['decision_date'] == '2026-03-06'
    assert bond['amounts'] == [{'security':'bond','amount':2054.79}]
    empty = ce.from_fact(stage_fixtures()[4])
    assert empty['amounts'] == [] and empty['confidence'] == 'review'


def test_proposal_in_a_voting_question_never_becomes_a_resolution():
    raw = {**stage_fixtures()[2], 'facts_decisions_wording':[], 'facts_voting_results':[{'question_name':'Утвердить дивиденды за 2025 год'}]}
    event = ce.from_fact(raw)
    assert event['stage'] == 'decision_disclosed'
    assert event['category'] == 'governance'


def test_latest_agenda_does_not_downgrade_an_already_approved_story():
    approved = ce.from_fact(stage_fixtures()[1])
    agenda = {**approved, 'id':'agenda', 'stage':'agenda', 'published_at':'2026-10-26', 'confidence':'confirmed'}
    story = ce.group_stories([approved,agenda])[0]
    assert story['stage'] == 'approved'
    assert story['document_count'] == 2
    assert story['published_at'] == '2026-10-26'


def test_security_class_is_known_for_nonpayment_disclosures_and_bonds():
    share=ce.from_fact({'fact_number':23,'id':1},tickers=['HMKB'])
    bond=ce.from_fact({'fact_number':21,'id':2},tickers=['BOND'])
    ce.attach_securities([share,bond],{'HMKB':{'share_type':'ordinary'}},{'BOND':{'type':'bond'}})
    assert share['security_classes']==['ordinary']
    assert bond['security_classes']==['bond']


def test_matching_decision_date_can_link_a_payment_to_an_unambiguous_annual_resolution():
    approved=ce.from_fact(stage_fixtures()[1])
    payment={**approved,'id':'payment','period':None,'stage':'paid','published_at':'2026-10-26'}
    stories=ce.group_stories([approved,payment])
    assert len(stories)==1 and stories[0]['document_count']==2
    payment['decision_date']='2026-07-01'
    assert len(ce.group_stories([approved,payment]))==2


def test_checked_source_correction_can_lower_confidence_without_erasing_history(monkeypatch,tmp_path):
    import catalogue.storage as cs
    monkeypatch.setattr(cs,'_catalog_db_path',lambda:str(tmp_path/'events.db'))
    old=ce.from_fact(stage_fixtures()[0])
    ce.save_documents([old])
    revised={**old,'confidence':'review','stage':'payment_disclosed','evidence_checked':True}
    ce.save_documents([revised])
    rows=ce.read_documents('2025-02-25','2025-02-26')
    assert rows[0]['confidence']=='review'
    assert len(rows[0]['revisions'])==2


def test_real_hmkb_announcement_summary_and_priority_use_its_agenda_evidence():
    notice=json.loads((FIXTURES/'hmkb_20828.json').read_text())
    event=ce.from_announcement({'announcement_id':'20828','org_id':'8','ticker':'HMKB','pub_date':'2026-06-01','meeting_date':'2026-06-25'},notice)
    assert event['confidence']=='confirmed' and not event['priority_provisional']
    assert event['priority_reason']=='agenda_evidence'
    assert '2026-06-25' in event['summary']['en']
    assert 'approval is not confirmed' in event['summary']['en']
    assert event['evidence']
    assert 'Insufficient' not in event['priority_explanation']['en']


def test_announcement_without_body_retains_review_without_an_unknown_fact_summary():
    event=ce.from_announcement({'announcement_id':'20828','ticker':'HMKB','pub_date':'2026-06-01','meeting_date':'2026-06-25'})
    assert event['confidence']=='review' and event['priority_provisional']
    assert '2026-06-25' in event['summary']['en']


def test_readable_summary_formats_real_issue_quantity_without_float_artifacts():
    from corporate_event_fields import summary_value
    field = {'value': 30000000000.0, 'unit': 'count'}
    assert summary_value(field, 'ru') == '30 000 000 000'
    assert summary_value(field, 'en') == '30,000,000,000'
    assert summary_value({'value': 1429129211.04, 'unit':'source_units'}, 'ru') == '1 429 129 211,04 (единицы источника)'
    assert summary_value({'value': 1, 'unit':'records'}, 'ru') == '1 запись'


def test_agat_bond_income_summary_does_not_promote_empty_share_fields():
    raw = next(x['raw'] for x in json.loads((FIXTURES/'semantic_facts.json').read_text())
               if str(x['raw'].get('fact_number')) == '32' and x['raw'].get('sum_per') == '2054.7900')
    event = ce.from_fact(raw)
    assert '2 054,79' in event['summary']['ru']
    assert 'на акцию' not in event['summary']['ru']
    # Keep the zero as original source evidence, but out of the lead summary.
    assert any(f['source_field']=='sum_aksiya' and f['value']==0 for f in event['facts'])
