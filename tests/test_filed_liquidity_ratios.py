"""The «Коэффициенты» columns come off the filings where the feed is silent.

openinfo's indicator feed publishes a current ratio and an asset turnover for 56
of the 95 issuers on the board and ROCE for 64, so three of the four coefficient
columns were blank for two issuers in five — while every one of them files the
balance lines the ratios are made of.

Calculated coefficients retain their formula and inputs separately from the
published indicator feed. Interim flows are explicitly annualized, while balance
ratios remain point-in-time. The reported UZTL Q3 regression exercises both
share classes and the stale annual values that previously remained on screen.
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

import reports_catalog as rc
import catalogue.financial_store as catalogue_financial_store
import catalogue.parsing as catalogue_parsing
import catalogue.ratios as catalogue_ratios
import catalogue.storage as catalogue_storage


@pytest.fixture()
def catalog(tmp_path, monkeypatch) -> sqlite3.Connection:
    db = tmp_path / "catalog.sqlite3"
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(db))
    monkeypatch.setattr(catalogue_financial_store, "_maybe_seed_financials", lambda *a, **k: None)
    monkeypatch.setenv("FINANCIALS_ENRICH_ON_READ", "0")
    conn = catalogue_storage.get_catalog_conn()
    with conn:
        conn.execute("INSERT INTO catalog_companies (ticker, company_name, org_id) "
                     "VALUES ('AAA','Aaa AJ','777')")
    yield conn
    conn.close()


def _fact(conn, field: str, period: str, value: float) -> None:
    with conn:
        conn.execute(
            "INSERT INTO facts (entity_id, dataset, field, period, value_num, source) "
            "VALUES ('777','financial_indicators',?,?,?,'openinfo')",
            (field, period, value))


def _filing(year: int, quarter: int = 0, **fields) -> dict:
    return {"ticker": "AAA", "year": year, "quarter": quarter, **fields}


class TestLiquidityFromTheFilings:
    def test_the_ratios_are_derived_where_the_feed_is_silent(self, catalog) -> None:
        # The feed knows this issuer — it publishes ROE — but none of the three.
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, revenue=500.0, total_assets=1000.0,
            current_assets=300.0, current_liabilities=150.0, inventories=60.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got["current_ratio"] == 2.0             # 300 / 150
        assert got["quick_ratio"] == 1.6               # (300 − 60) / 150
        assert got["total_asset_turnover"] == 0.5      # 500 / 1000
        assert got["periods"]["current_ratio"] == "2025"

    def test_roce_is_explicitly_calculated_with_its_own_formula(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, revenue=500.0, operating_income=90.0, total_assets=1000.0,
            current_assets=300.0, current_liabilities=150.0, inventories=60.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got['return_to_capital_employed'] == pytest.approx(90 / 850)
        assert got['calculations']['return_to_capital_employed']['origin'] == 'UZStock_calculated'
        assert got['calculations']['return_to_capital_employed']['formula'] == 'operating_income / (total_assets - current_liabilities)'

    def test_a_more_recent_filing_wins_over_the_feed(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        _fact(catalog, "current_ratio", "2023", 9.99)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, current_assets=300.0, current_liabilities=150.0, inventories=0.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got["current_ratio"] == 2.0
        assert got["periods"]["current_ratio"] == "2025"

    def test_the_feed_stands_when_it_is_the_more_recent_period(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        _fact(catalog, "current_ratio", "2025", 9.99)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2023, current_assets=300.0, current_liabilities=150.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got["current_ratio"] == 9.99
        assert got["periods"]["current_ratio"] == "2025"

    def test_quarterly_turnover_is_explicitly_annualized(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, quarter=2, revenue=500.0, total_assets=1000.0,
            current_assets=300.0, current_liabilities=150.0, inventories=60.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got['total_asset_turnover'] == 1.0
        calculation = got['calculations']['total_asset_turnover']
        assert calculation['annualized'] is True
        assert calculation['period_months'] == 6
        assert calculation['formula'] == 'revenue / total_assets * 12 / 6'
        assert got["current_ratio"] == 2.0, "a balance ratio holds in any period"

    def test_a_form_with_no_current_section_derives_no_liquidity(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(2025, revenue=500.0, total_assets=1000.0)])
        got = catalogue_ratios.get_all_ratios()["AAA"]
        assert got.get("current_ratio") is None
        assert got.get("quick_ratio") is None
        assert got["total_asset_turnover"] == 0.5


def test_uztl_q3_calculations_replace_stale_annual_coefficients_for_both_classes(catalog, monkeypatch):
    from catalogue import read_batch
    fixture = json.loads(Path('tests/fixtures/uztl_share_classes.json').read_text())
    monkeypatch.setattr(read_batch, 'securities', lambda: fixture['securities'])
    with catalog:
        catalog.execute("INSERT INTO catalog_companies(ticker,company_name,org_id) VALUES ('UZTL','Uzbektelecom','777')")
    for field, value in [('debt_ratio', 77.6), ('total_asset_turnover', .78), ('return_to_capital_employed', .07)]:
        _fact(catalog, field, '2025', value)
    catalogue_financial_store.bulk_upsert_financials(fixture['rows'])
    with catalog:
        catalog.execute("UPDATE catalog_financials SET report_id=3398 WHERE ticker='UZTL'")
    result = catalogue_ratios.get_all_ratios()
    for ticker in ('UZTL', 'UZTLP'):
        row = result[ticker]
        assert row['debt_ratio'] == pytest.approx(13530092389 / 17865340081 * 100)
        assert row['total_asset_turnover'] == pytest.approx(8771988231 / 17865340081 * 12 / 9)
        assert row['return_to_capital_employed'] == pytest.approx(1809880688 / (17865340081 - 4660538528) * 12 / 9)
        for field in ('debt_ratio', 'total_asset_turnover', 'return_to_capital_employed'):
            calc = row['calculations'][field]
            assert calc['period'] == row['periods'][field] == '2026Q3'
            assert calc['report_id'] == 3398
            assert calc['ticker'] == 'UZTL'
            assert calc['operand_unit'] == 'thousand_UZS'
            assert calc['annualized'] == (field != 'debt_ratio')
    result['UZTLP']['calculations']['debt_ratio']['operands']['total_assets'] = -1
    assert result['UZTL']['calculations']['debt_ratio']['operands']['total_assets'] > 0


@pytest.mark.parametrize('problem', ['missing_assets', 'zero_assets', 'negative_capital', 'mixed_period', 'future', 'invalid_quarter', 'bank'])
def test_unusable_inputs_never_produce_current_roce(catalog, problem):
    _fact(catalog, 'return_to_capital_employed', '2024', .07)
    row = _filing(2025, 2, operating_income=90, revenue=500, total_assets=1000, current_liabilities=150)
    row.update({
        'missing_assets': {'total_assets': None}, 'zero_assets': {'total_assets': 0},
        'negative_capital': {'current_liabilities': 1200},
        'mixed_period': {'field_periods': {'operating_income': '2024'}},
        'future': {'year': 2099}, 'invalid_quarter': {'quarter': 7},
        'bank': {'org_type': 'bank'},
    }[problem])
    catalogue_financial_store.bulk_upsert_financials([row])
    got = catalogue_ratios.get_all_ratios()['AAA']
    assert got['return_to_capital_employed'] == .07
    assert got['periods']['return_to_capital_employed'] == '2024'
    assert 'return_to_capital_employed' not in got.get('calculations', {})


def test_financial_rows_need_no_indicator_feed_and_keep_zero_and_negative_results(catalog):
    catalogue_financial_store.bulk_upsert_financials([_filing(
        2025, 2, revenue=0, operating_income=-90, total_assets=1000,
        total_liabilities=0, current_liabilities=150)])
    got = catalogue_ratios.get_all_ratios()['AAA']
    assert got['debt_ratio'] == got['total_asset_turnover'] == 0
    assert got['return_to_capital_employed'] == pytest.approx(-90 / 850 * 2)

class TestTheCurrentSectionIsParsed:
    """«Итого по разделу II» names four different lines across the two commercial
    forms; only the formula in its parentheses tells the asset side from the rest."""

    def _row(self, label: str, *values: float) -> dict:
        return {"label": label, "numeric_values": list(values)}

    def test_the_asset_side_subtotal_is_the_one_read(self) -> None:
        rows = [
            self._row("Итого по разделу I (стр. 012+022+030+090+100+110+120)", 130, 900, 950),
            self._row("Итого по разделу II (стр. 140+190+200+210+320+370+380)", 390, 280, 300),
            self._row("Всего по активу баланса (стр.130+стр.390)", 400, 1180, 1250),
            self._row("Итого по разделу I (стр.410+420+430-440+450+460+470)", 480, 700, 750),
            self._row("Итого по разделу II (стр.490+600)", 770, 480, 500),
        ]

        assert catalogue_parsing._extract_current_assets(rows) == 300
        assert catalogue_parsing._extract_liabilities_total(rows) == 500

    def test_the_insurance_form_has_its_own_formula(self) -> None:
        rows = [self._row("Итого по разделу II (стр. 140+170+180+190+410+460+470)",
                          480, 70, 90)]

        assert catalogue_parsing._extract_current_assets(rows) == 90

    def test_a_bank_balance_states_no_current_section(self) -> None:
        rows = [self._row("14. Итого активов", 5000),
                self._row("25. Итого обязательств", 4000)]

        assert catalogue_parsing._extract_current_assets(rows) is None


class TestWithheldLines:
    """A line withheld for contradicting its own form is a gap, not a nought."""

    def test_withheld_stocks_leave_the_quick_ratio_to_the_period_that_states_them(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([
            _filing(2025, quarter=1, current_assets=300.0, current_liabilities=150.0, inventories=60.0),
            _filing(2025, quarter=2, current_assets=400.0, current_liabilities=200.0, inventories=None)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert (got["current_ratio"], got["periods"]["current_ratio"]) == (2.0, "2025Q2")
        assert (got["quick_ratio"], got["periods"]["quick_ratio"]) == (1.6, "2025Q1")

    def test_withheld_current_liabilities_leave_both_ratios_to_an_earlier_period(self, catalog) -> None:
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([
            _filing(2025, quarter=1, current_assets=300.0, current_liabilities=150.0, inventories=60.0),
            _filing(2025, quarter=2, current_assets=400.0, current_liabilities=None, inventories=50.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got["periods"]["current_ratio"] == got["periods"]["quick_ratio"] == "2025Q1"
