import pytest

from marketing import source_adapters
from test_marketing_sources import source_input


def ready_report(**changes):
    return {"version": "report-hmkb-q3", "issuer": {"id": "123", "ticker": "HMKB"}, "language": "ru",
            "standard": "nsbu", "scope": "separate", "period": "2026Q3", "financial_as_of": "2026-09-30",
            "status": "available", "text_checks": {"status": "passed"}, "availability": {},
            "headline": "HMKB · готовый разбор", "short_summary": "Generated commentary must not become the original",
            "generated_at": "2026-11-23T08:00:00+00:00", "verified_facts": [
                {"metric_code": "net_income", "raw": 900, "unit_raw": "thousand UZS", "currency": "UZS",
                 "verification_status": "verified", "source_url": "https://openinfo.uz/reports/123",
                 "source_published_at": "2026-10-25T09:00:00+05:00", "source_original_line": "Чистая прибыль",
                 "period_end": "2026-09-30", "consolidation_scope": "separate", "accounting_standard": "NSBU"}], **changes}


def test_internal_news_reads_stored_original_not_ai_summary_and_preserves_dates(monkeypatch):
    import news_store
    monkeypatch.setattr(news_store, "get_news_feed", lambda **kw: [{"id": 123, "url": "https://issuer.test/decision",
        "source": "Issuer", "title": "Decision", "snippet": "Original extract", "summary_ru": "Model opinion",
        "published_at": "2026-11-23T08:00:00Z", "tickers": ["HMKB"]}])
    batch = source_adapters.fetch({**source_input(), "id": "news"})
    assert batch.materials[0]["excerpt"] == "Original extract"
    assert batch.materials[0]["destination_url"] == "https://uzstock.uz/news/123"
    assert batch.verified_ids == set()


def test_rss_uses_bounded_public_fetch_and_leaves_unconfirmed_values_empty(monkeypatch):
    import public_fetch
    calls = []
    def fetch(session, url, **options):
        calls.append((url, options))
        return public_fetch.Fetched(url, 200, {}, b'<rss><channel><item><guid>one</guid><title>News</title><link>https://issuer.test/one</link><pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate><description>Approved 120 UZS</description></item></channel></rss>', 'utf-8')
    monkeypatch.setattr(public_fetch, "fetch", fetch)
    batch = source_adapters.fetch({**source_input(method="rss", url="https://issuer.test/feed.xml"), "id": "rss"})
    assert len(batch.materials) == 1 and batch.materials[0]["data"] == {}
    assert calls[0][1]["max_bytes"] <= 2_000_000
    assert not batch.verified_ids


def test_public_site_crawl_cannot_be_selected_as_rss_or_redirect(monkeypatch):
    import public_fetch
    with pytest.raises(ValueError, match="internal"):
        source_adapters.fetch({**source_input(method="rss"), "id": "public"})
    with pytest.raises(ValueError, match="internal"):
        source_adapters.rss_url_check("https://uzstock.uz/news")


def test_market_source_requires_explicit_complete_session_validation(monkeypatch):
    import catalogue.facts
    import catalogue.market_store
    monkeypatch.setattr(catalogue.facts, "get_facts", lambda *args: [])
    monkeypatch.setattr(catalogue.market_store, "get_all_trade_stats", lambda: {})
    with pytest.raises(ValueError, match="complete"):
        source_adapters.fetch({**source_input(method="internal_market"), "id": "market"})


def test_ready_analysis_retains_original_filing_date_units_and_extract_not_generated_commentary():
    from reporting import store
    store.record_report(ready_report())
    batch = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})
    assert len(batch.materials) == 1
    material = batch.materials[0]
    assert material["published_at"] == "2026-10-25T09:00:00+05:00"
    assert material["data"]["net_income"] == 900
    assert material["units"]["net_income"] == "thousand UZS"
    assert "Generated commentary" not in material["excerpt"]
    assert "Чистая прибыль" in material["excerpt"]
    assert material["source_item_id"] in batch.verified_ids


@pytest.mark.parametrize("same_url", [False, True])
def test_analysis_keeps_half_year_and_nine_month_originals_separate(same_url):
    from reporting import store
    report = ready_report()
    nine = report["verified_facts"][0]
    report["verified_facts"].append({**nine, "raw": 600, "period_end": "2026-06-30",
        "source_url": nine["source_url"] if same_url else "https://openinfo.uz/reports/half-year",
        "source_published_at": nine["source_published_at"] if same_url else "2026-07-25T09:00:00+05:00"})
    store.record_report(report)
    batch = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})
    by_period = {item["period"]: item for item in batch.materials}
    assert set(by_period) == {"2026-06-30", "2026-09-30"}
    assert by_period["2026-06-30"]["data"]["net_income"] == 600
    assert by_period["2026-09-30"]["data"]["net_income"] == 900
    assert len({item["source_item_id"] for item in batch.materials}) == 2
    assert all(item["analysis_version"] == report["version"] for item in batch.materials)
    assert by_period["2026-06-30"]["published_at"] == report["verified_facts"][1]["source_published_at"]


def test_same_period_end_does_not_merge_cumulative_and_standalone_quarter_profit():
    from reporting import store
    report = ready_report()
    fact = report["verified_facts"][0]
    fact.update(period_start="2026-01-01", period_kind="cumulative")
    report["verified_facts"].append({**fact, "raw": 300, "period_start": "2026-07-01", "period_kind": "quarter"})
    store.record_report(report)
    batch = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})
    assert {(row["period_start"], row["period"], row["period_kind"], row["data"]["net_income"]) for row in batch.materials} == {
        ("2026-01-01", "2026-09-30", "cumulative", 900), ("2026-07-01", "2026-09-30", "quarter", 300)}
    assert len({row["source_item_id"] for row in batch.materials}) == 2


@pytest.mark.parametrize("missing", ["period_end", "accounting_standard", "consolidation_scope", "currency"])
def test_analysis_does_not_invent_missing_original_financial_scope(missing):
    from reporting import store
    report = ready_report()
    report["verified_facts"][0].pop(missing)
    store.record_report(report)
    with pytest.raises(ValueError, match="financial scope"):
        source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})


def test_analysis_retains_currency_and_refuses_conflicting_same_period_values():
    from reporting import store
    report = ready_report()
    first = report["verified_facts"][0]
    first.update(currency="USD", unit_raw="USD")
    store.record_report(report)
    material, = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"}).materials
    assert material["currency"] == "USD" and material["units"]["net_income"] == "USD"
    # Exact duplicate facts are harmless; a different number in that same scope is not.
    report = ready_report(version="same-fact-repeat", verified_facts=[first, dict(first)])
    store.record_report(report)
    assert len(source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"}).materials) == 1
    report = ready_report(version="conflicting-original", verified_facts=[first, {**first, "raw": 800}])
    store.record_report(report)
    with pytest.raises(ValueError, match="conflicting"):
        source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})


def test_analysis_link_pins_published_standard_scope_language_period_and_version():
    from reporting import store
    from urllib.parse import urlsplit, parse_qs
    report = ready_report(standard="ifrs", scope="consolidated", language="uz")
    store.record_report(report)
    batch = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis", "language": "uz"})
    url = urlsplit(batch.materials[0]["destination_url"])
    assert url.path == "/uz/company/HMKB"
    assert parse_qs(url.query) == {"report": ["ai"], "report_standard": ["ifrs"], "report_scope": ["consolidated"],
                                 "report_period": ["2026Q3"], "report_lang": ["uz"], "report_version": [report["version"]]}


def test_report_without_original_publication_date_is_not_silently_dated_by_generation_time():
    from reporting import store
    report = ready_report()
    report["verified_facts"][0]["source_published_at"] = None
    store.record_report(report)
    with pytest.raises(ValueError, match="publication date"):
        source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"})


def test_corrected_analysis_keeps_the_same_original_identity_so_queued_versions_invalidate():
    from reporting import store
    store.record_report(ready_report())
    first = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"}).materials[0]
    corrected = ready_report(version="report-hmkb-q3-corrected")
    corrected["verified_facts"][0]["raw"] = 1000
    store.record_report(corrected)
    second = source_adapters.fetch({**source_input(method="internal_analysis"), "id": "analysis"}).materials[0]
    assert second["source_item_id"] == first["source_item_id"]
    assert second["analysis_version"] != first["analysis_version"]
