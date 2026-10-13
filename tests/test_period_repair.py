"""Quarterly workbooks the history import misdated are refiled by their own header."""
from io import BytesIO

import pandas as pd
import pytest

import catalogue.filings as catalogue_filings
import catalogue.financial_store as catalogue_financial_store
import catalogue.history as catalogue_history
import catalogue.storage as catalogue_storage
from collectors.openinfo.workbooks import _parse_excel_workbook
from financial_ingestion import period_repair
import provenance


def workbook(quarter, reporting_date):
    buf = BytesIO()
    pd.DataFrame([["Период квартала:", quarter], ["Дата отчетности:", reporting_date],
                  ["Чистая выручка от реализации продукции", 10, 1, 2]]
                 ).to_excel(buf, header=False, index=False)
    return {"ok": True, **_parse_excel_workbook(buf.getvalue())}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
    provenance.init()
    c = catalogue_storage.get_catalog_conn()
    with c:
        c.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES('UQEQ','Q','7')")
    c.close()
    books = {}
    monkeypatch.setattr(catalogue_history, "_parse_workbook_uncached", lambda session, url: books[url])
    return books


def report(year, quarter, url, record, published):
    c = catalogue_storage.get_catalog_conn()
    with c:
        catalogue_filings._upsert_report(c, "UQEQ", report_form="NSBU", period_type="quarter", year=year,
                                         quarter=quarter, title="Report", published_at=published, pdf_url=None,
                                         excel_url=url, excel_url_form1=url, openinfo_report_id=record, object_id=None)
    c.close()


def periods():
    c = catalogue_storage.get_catalog_conn()
    try:
        return {(r["year"], r["quarter"]): r["openinfo_report_id"] for r in c.execute(
            "SELECT year, quarter, openinfo_report_id FROM catalog_reports WHERE ticker='UQEQ'")}
    finally:
        c.close()


def test_a_late_half_year_moves_to_its_stated_year_and_its_wrong_figures_go(catalog):
    catalog["late"] = workbook(2, "2021-07-29")
    catalog["q1"] = workbook(1, "2022-04-29")
    report(2022, 2, "late", "11260", "2022-09-14T10:58:39")
    report(2022, 1, "q1", "12546", "2022-04-29T17:21:10")
    catalogue_financial_store.upsert_financials_cache("UQEQ", "NSBU", 2022, 2, {"revenue": 111441498.0})
    rid = provenance.upsert_report("7", "NSBU", "quarter", 2022, 2, excel_url="late")

    found = period_repair.scan(pace=0)
    assert [(m["year"], m["quarter"], m["to_year"], m["to_quarter"]) for m in found["misfiled"]] == [(2022, 2, 2021, 2)]

    done = period_repair.refile(found["misfiled"])
    assert done[0]["action"] == "moved"
    assert periods() == {(2021, 2): "11260", (2022, 1): "12546"}
    c = catalogue_storage.get_catalog_conn()
    try:
        assert c.execute("SELECT count(*) FROM catalog_financials WHERE ticker='UQEQ' AND year=2022 AND quarter=2").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM source_reports WHERE id=?", (rid,)).fetchone()[0] == 0
    finally:
        c.close()
    # A second scan finds nothing left to move.
    assert period_repair.scan(pace=0)["misfiled"] == []


def test_an_occupied_period_keeps_the_later_publication(catalog):
    catalog["late"] = workbook(2, "2021-07-29")
    catalog["orig"] = workbook(2, "2021-07-20")
    report(2022, 2, "late", "11260", "2022-09-14T10:58:39")
    report(2021, 2, "orig", "11000", "2021-07-20T09:00:00")
    period_repair.refile(period_repair.scan(pace=0)["misfiled"])
    assert periods() == {(2021, 2): "11260"}


def test_a_header_without_a_reporting_date_is_never_acted_on(catalog):
    catalog["bare"] = workbook(2, None)
    report(2022, 2, "bare", "1", "2022-09-14T10:58:39")
    found = period_repair.scan(pace=0)
    assert found["misfiled"] == [] and found["unreadable"][0]["error"] == "header states no period"
