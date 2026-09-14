"""Reviewed financial-organization corrections and their catalog integration."""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import financial_corrections as fc
import reports_catalog as rc

api = importlib.import_module("api")


def test_v3_register_is_complete_unique_and_converted_to_catalog_units():
    rows = fc.financial_corrections()
    assert len(rows) == 459
    assert len({(r.ticker, r.period, r.field) for r in rows}) == 459

    agba = fc.corrections_for("agba", "2016q4")
    assert agba["total_assets"].value_thousands_uzs == 3_949_374_649.0
    assert agba["total_equity"].source_url == "https://openinfo.uz/ru/reports/to_pdf6001/"

    # The source uses a Unicode minus for this legitimate negative equity.
    assert fc.corrections_for("UZAS", "2017Q4")["total_equity"].value_thousands_uzs == pytest.approx(
        -29_927_795.4
    )


def test_unknown_ticker_or_period_has_no_overlay():
    assert fc.corrections_for("NOPE", "2025Q4") == {}
    assert fc.corrections_for("AGBA", "2099Q4") == {}
    assert fc.correction_periods_for("NOPE") == {}


def test_catalog_readers_apply_registered_values_after_cached_values(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "corrections.db"))

    rc.upsert_financials_cache("AGBA", "NSBU", 2016, 0, {
        "total_assets": 1.0,
        "total_equity": 2.0,
    })
    rc.upsert_financials_cache("AGBA", "NSBU", 2023, 3, {
        "total_assets": 100.0,
        "total_equity": 3.0,
    })

    annual = rc.get_financials_series("AGBA")
    assert annual["2016"]["total_assets"] == 3_949_374_649.0
    assert annual["2016"]["total_equity"] == 531_834_075.0
    # No 2017 row was cached, but the register's Add rows must still surface it.
    assert annual["2017"]["total_assets"] == 4_981_542_046.0

    quarterly = rc.get_financials_series_quarterly("AGBA")
    assert quarterly["2023Q3"]["total_equity"] == 9_785_156_539.0

    # OCBK's production cache currently has no 2023Q2 row at all.  The reviewed
    # register is sufficient to create the missing balance snapshot.
    correction_only = rc.get_financials_series_quarterly("OCBK")
    assert correction_only["2023Q2"]["cash"] == 35_094_315.0
    assert correction_only["2023Q2"]["total_assets"] == 778_235_028.0

    latest = rc.get_all_financials()["AGBA"]
    assert latest["total_equity"] == 9_785_156_539.0
    assert latest["balance"]["equity_end"] == 9_785_156_539.0
    assert latest["annual"]["total_assets"] == 3_949_374_649.0
    assert latest["annual"]["balance"]["assets_end"] == 3_949_374_649.0


def test_every_registered_row_is_available_even_with_an_empty_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "empty-corrections.db"))
    tickers = sorted({row.ticker for row in fc.financial_corrections()})
    annual = {ticker: rc.get_financials_series(ticker) for ticker in tickers}
    quarterly = {ticker: rc.get_financials_series_quarterly(ticker) for ticker in tickers}

    for correction in fc.financial_corrections():
        if correction.period.endswith("Q4"):
            fields = annual[correction.ticker][correction.period[:4]]
        else:
            fields = quarterly[correction.ticker][correction.period]
        assert fields[correction.field] == correction.value_thousands_uzs, (
            correction.ticker,
            correction.period,
            correction.field,
        )


def test_every_correction_reaches_the_public_api_in_full_uzs(monkeypatch, tmp_path):
    monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "api-corrections.db"))
    monkeypatch.setattr(api, "get_company_index", lambda ticker: {"org_id": ticker})

    def facts(org_id, dataset=None):
        if org_id != "UZAS":
            return []
        # Production carries an all-zero 2025 indicator placeholder for UZAS.
        # The reviewed Q4 register must win instead of being purged with it.
        return [
            {"field": field, "period": "2025", "value_num": 0.0}
            for field in ("total_assets", "total_equity", "total_liabilities", "cash")
        ]

    monkeypatch.setattr(api, "get_facts", facts)
    monkeypatch.setattr(api, "get_company_reports", lambda ticker: [])

    client = TestClient(api.app)
    responses = {}
    for ticker in sorted({row.ticker for row in fc.financial_corrections()}):
        responses[(ticker, "annual")] = client.get(
            f"/api/company/{ticker}/financials"
        ).json()
        responses[(ticker, "quarterly")] = client.get(
            f"/api/company/{ticker}/financials?freq=quarterly"
        ).json()

    for correction in fc.financial_corrections():
        annual = correction.period.endswith("Q4")
        body = responses[(correction.ticker, "annual" if annual else "quarterly")]
        period = correction.period[:4] if annual else correction.period
        assert period in body["periods"], (correction.ticker, correction.period)
        expected = correction.value_thousands_uzs
        # Income-statement corrections are filed year-to-date and the public
        # quarterly API deliberately presents a standalone three-month result.
        if correction.field == "operating_expenses" and correction.period[-1] != "1":
            prior = fc.corrections_for(
                correction.ticker, f"{correction.period[:4]}Q{int(correction.period[-1]) - 1}")
            expected -= prior["operating_expenses"].value_thousands_uzs
        assert body["series"][correction.field]["values"][period] == pytest.approx(
            expected * rc.NSBU_THOUSANDS_UZS
        ), (correction.ticker, correction.period, correction.field)
