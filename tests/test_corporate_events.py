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


@pytest.mark.parametrize("source", ["https://evil.test/x", "https://openinfo.uz.evil.test/ru/announce/1", "file:///etc/passwd", "https://openinfo.uz/ru/announce/99999999"])
def test_refresh_does_not_fetch_arbitrary_or_unstored_sources(source, monkeypatch, tmp_path):
    import catalogue.storage as cs
    monkeypatch.setattr(cs, "_catalog_db_path", lambda: str(tmp_path / "catalog.db"))
    with pytest.raises(ValueError):
        ce.refresh_document(source)
