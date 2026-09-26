"""The «Коэффициенты» columns come off the filings where the feed is silent.

openinfo's indicator feed publishes a current ratio and an asset turnover for 56
of the 95 issuers on the board and ROCE for 64, so three of the four coefficient
columns were blank for two issuers in five — while every one of them files the
balance lines the ratios are made of.

The three identities below were MEASURED against the feed's own numbers (see the
comment in get_all_ratios): current and quick reproduce it 35 times in 38, the
turnover 34 in 37, to the two decimals it publishes. ROCE reproduces 7 in 42 and
is therefore never derived — that is the case these tests pin.
"""
from __future__ import annotations

import sqlite3

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

    def test_roce_is_never_derived(self, catalog) -> None:
        """The feed computes it on a base it does not name — 7 of 42 reproduce.

        Publishing our own different number under the source's label would be
        the worse of the two answers; a blank column is honest.
        """
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, revenue=500.0, operating_income=90.0, total_assets=1000.0,
            current_assets=300.0, current_liabilities=150.0, inventories=60.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got.get("return_to_capital_employed") is None

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

    def test_the_turnover_refuses_a_cumulative_quarter(self, catalog) -> None:
        """A Q2 revenue is six months. Over a full balance it reads as a business
        half its size — so the turnover comes off annual rows only, while the two
        balance ratios are point-in-time and any period states them."""
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(
            2025, quarter=2, revenue=500.0, total_assets=1000.0,
            current_assets=300.0, current_liabilities=150.0, inventories=60.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got.get("total_asset_turnover") is None
        assert got["current_ratio"] == 2.0, "a balance ratio holds in any period"

    def test_a_form_with_no_current_section_derives_nothing(self, catalog) -> None:
        """The bank balance is not split into current and non-current, and no
        current ratio is defined for one."""
        _fact(catalog, "roe", "2025", 12.0)
        catalogue_financial_store.bulk_upsert_financials([_filing(2025, revenue=500.0, total_assets=1000.0)])

        got = catalogue_ratios.get_all_ratios()["AAA"]

        assert got.get("current_ratio") is None
        assert got.get("quick_ratio") is None
        assert got["total_asset_turnover"] == 0.5, "the turnover needs no split"


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
