"""The full NSBU sweep resumes source-backed periods and repairs share aliases."""
import pytest

import reports_catalog as rc
import catalogue.filings as catalogue_filings
import catalogue.financial_store as catalogue_financial_store
import catalogue.history as catalogue_history
import catalogue.parsing as catalogue_parsing
import catalogue.refresh as catalogue_refresh
import catalogue.sources as catalogue_sources
import catalogue.storage as catalogue_storage
from financial_ingestion import nsbu_history as history

_HARVEST = catalogue_history.harvest_historical_quarters


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    monkeypatch.setattr(history, "implementation_digest", lambda: "parser-v1")
    monkeypatch.setattr(catalogue_history, "harvest_historical_quarters", lambda ticker, **kw: {"added": 0, "errors": []})
    c = catalogue_storage.get_catalog_conn()
    with c:
        for ticker in ("UZIR", "UZIRP"):
            c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES(?,?,?)",
                      (ticker, "Coal", "42"))
    c.close()
    values = {field: 100.0 for field in history._REQUIRED}
    values["operating_expenses"] = 0.0
    monkeypatch.setattr(catalogue_parsing, "compute_financial_ratios", lambda *a: {"source_values": dict(values), "metrics": {"ROA": 1.0}})
    calls = []
    def fetch(ticker, form, year, quarter, **kwargs):
        assert kwargs == {"use_snapshot_cache": False}
        calls.append((ticker, year, quarter))
        return {"ok": True, "income": {}, "balance": {}}
    monkeypatch.setattr(catalogue_sources, "fetch_report_excel_data", fetch)
    monkeypatch.setattr(catalogue_refresh, "_register_parse", lambda *a: 42)
    return calls, values


def report(ticker="UZIR", year=2018, quarter=3, url="https://openinfo.uz/42.xlsx", record="42", form="NSBU", published="2018-11-01"):
    c = catalogue_storage.get_catalog_conn()
    with c:
        catalogue_filings._upsert_report(c, ticker, report_form=form, period_type="quarter" if quarter else "annual",
                          year=year, quarter=quarter, title="Report", published_at=published,
                          pdf_url=None, excel_url=url, excel_url_form1=url, openinfo_report_id=record, object_id=None)
    c.close()


def test_all_periods_and_aliases_resume_and_msfo_is_untouched(catalog):
    report()
    report(quarter=0)
    report(form="MSFO")
    catalogue_financial_store.upsert_financials_cache("UZIRP", "NSBU", 2018, 3, {"revenue": 1})
    result = history.run(["uzirp"])
    assert result["complete"] == 2
    assert result["processed"] == 2
    assert history.run()["skipped"] == 2
    c = catalogue_storage.get_catalog_conn()
    assert c.execute("SELECT count(*) FROM catalog_financials WHERE form='NSBU'").fetchone()[0] == 4
    assert c.execute("SELECT revenue FROM catalog_financials WHERE ticker='UZIRP' AND quarter=3").fetchone()[0] == 100
    assert c.execute("SELECT count(*) FROM catalog_financials WHERE form='MSFO'").fetchone()[0] == 0
    c.close()


def test_changed_url_record_parser_and_lost_cache_require_retry(catalog, monkeypatch):
    report()
    assert history.run()["complete"] == 1
    report(url="https://openinfo.uz/new.xlsx", record="43", published="2018-12-01")
    assert history.run()["processed"] == 1
    assert catalogue_filings.get_report_urls("UZIRP", "NSBU", 2018, 3)["excel_url"].endswith("new.xlsx")
    monkeypatch.setattr(history, "implementation_digest", lambda: "parser-v2")
    assert history.run()["processed"] == 1
    catalogue_financial_store.upsert_financials_cache("UZIRP", "NSBU", 2018, 3, {"revenue": 1})
    assert history.run()["processed"] == 1
    assert history.run(force=True)["processed"] == 1


def test_partial_and_failed_periods_retry_without_stopping_other_periods(catalog, monkeypatch):
    report(quarter=1)
    report(quarter=2)
    calls, values = catalog
    values["cash"] = None
    original = catalogue_sources.fetch_report_excel_data
    def fetch(ticker, form, year, quarter, **kw):
        if quarter == 1:
            raise RuntimeError("temporary upstream failure")
        return original(ticker, form, year, quarter, **kw)
    monkeypatch.setattr(catalogue_sources, "fetch_report_excel_data", fetch)
    first = history.run()
    assert first["processed"] == 2 and first["partial"] == 1
    assert len(first["errors"]) == 1
    assert history.run()["processed"] == 2


def test_changed_mapping_during_download_cannot_publish(catalog, monkeypatch):
    report()
    def fetch(*args, **kwargs):
        report(record="new-record")
        return {"ok": True, "income": {}, "balance": {}}
    monkeypatch.setattr(catalogue_sources, "fetch_report_excel_data", fetch)
    result = history.run()
    assert "mapping changed" in result["errors"][0]["error"]
    c = catalogue_storage.get_catalog_conn()
    assert c.execute("SELECT count(*) FROM catalog_financials").fetchone()[0] == 0
    c.close()


def test_budget_future_periods_and_discovery_failure(catalog, monkeypatch):
    report(quarter=1)
    report(quarter=2)
    report(year=2099)
    def fail(*a, **kw):
        assert kw["limit"] == 1000
        raise RuntimeError("feed unavailable")
    monkeypatch.setattr(catalogue_history, "harvest_historical_quarters", fail)
    first = history.run(max_periods=1)
    assert first["processed"] == 1 and first["stopped_by_budget"]
    assert first["errors"][0]["stage"] == "discovery"
    second = history.run()
    assert second["processed"] == 1 and second["skipped"] == 1
    with pytest.raises(ValueError, match="Unknown"):
        history.run(["MISSING"])


def test_incomplete_parse_preserves_published_fields_and_nonfinite_is_rejected(catalog):
    report()
    catalogue_financial_store.upsert_financials_cache("UZIRP", "NSBU", 2018, 3, {"cash": 10, "revenue": 20})
    calls, values = catalog
    values["cash"] = None
    result = history.run()
    assert "erase existing fields: cash" in result["errors"][0]["error"]
    c = catalogue_storage.get_catalog_conn()
    row = c.execute("SELECT cash,revenue FROM catalog_financials WHERE ticker='UZIRP'").fetchone()
    assert (row["cash"], row["revenue"]) == (10, 20)
    c.close()
    values["cash"] = float("nan")
    assert "Invalid financial value: cash" in history.run()["errors"][0]["error"]


def test_new_alias_invalidates_completed_checkpoint(catalog):
    report()
    history.run()
    c = catalogue_storage.get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES('UZIR2','Coal','42')")
    c.close()
    assert history.run()["processed"] == 1
    c = catalogue_storage.get_catalog_conn()
    assert c.execute("SELECT revenue FROM catalog_financials WHERE ticker='UZIR2'").fetchone()[0] == 100
    c.close()


def test_discovery_cannot_publish_before_validation(catalog, monkeypatch):
    monkeypatch.setattr(catalogue_history, "unified_quarterly_records", lambda *a: [{
        "accounting_id": "42", "pdf_id": "123", "pub_date": "2018-11-01",
        "excel_url": "https://openinfo.uz/42.xlsx", "title": "Q3",
    }])
    monkeypatch.setattr(catalogue_history, "_parse_workbook_uncached", lambda *a: {"ok": True})
    monkeypatch.setattr(catalogue_parsing, "compute_financial_ratios", lambda *a: {"source_values": {"revenue": 1}})
    monkeypatch.setattr(catalogue_refresh, "_register_parse", lambda *a: pytest.fail("discovery published provenance"))
    catalogue_financial_store.upsert_financials_cache("UZIR", "NSBU", 2018, 3, {"revenue": 100, "cash": 10})
    found = _HARVEST("UZIR", session=object(), pace=0, publish=False)
    assert found["added"] == 1
    c = catalogue_storage.get_catalog_conn()
    row = c.execute("SELECT revenue,cash FROM catalog_financials WHERE ticker='UZIR'").fetchone()
    assert (row["revenue"], row["cash"]) == (100, 10)
    c.close()
    assert catalogue_filings.get_report_urls("UZIR", "NSBU", 2018, 3)["excel_url"].endswith("42.xlsx")


def test_runner_discovery_is_catalog_only(catalog, monkeypatch):
    calls = []
    monkeypatch.setattr(catalogue_history, "harvest_historical_quarters", lambda *a, **kw: calls.append(kw) or {})
    history.run()
    assert calls == [{"limit": 1000, "publish": False}]


def test_bank_optional_fields_do_not_invalidate_successful_checkpoint(catalog):
    report()
    _, values = catalog
    values["noninterest_income"] = 20.0
    catalogue_financial_store.upsert_financials_cache("UZIR", "NSBU", 2018, 3, {"current_assets": 50})
    assert history.run()["complete"] == 1
    assert history.run()["skipped"] == 1
