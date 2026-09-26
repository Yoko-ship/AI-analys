"""Which of NSBU form 2's four value columns is the reporting period.

It is **value3/value4**, and value1/value2 is the prior-year comparative — the
opposite of the intuitive order, and the opposite of what this code did until
2026-08-04. Nothing caught it because each pair balances against itself:

    value1/value2:  264 737 847 - 33 883 416 = 230 854 431 = row 030 value1
    value3/value4:  237 634 918 - 28 451 551 = 209 183 367 = row 030 value3

Chronology settles it, and assumes nothing. A filing's comparative is the same
quarter one year earlier, so for the same quarter in consecutive years the newer
report's comparative must equal the older report's own period. O'zRTXB:

    2025-06-30 filing (published 2025-07-29):  value1=208 988 570  value3=237 634 918
    2026-06-30 filing (published 2026-07-30):  value1=237 634 918  value3=264 737 847

237 634 918 is in a report published in **July 2025**, so it cannot be H1 2026 —
it is H1 2025, sitting in value3 of its own filing and in value1 of the next.
Measured over thirty matched year-pairs across eight issuers: thirty say value3,
none say value1. The balance sheet is NOT reversed — its value1 is "на начало
года" (the same number repeats across Q1/Q2/Q3 of a year) and value2 the period
end.

For four months the board published every non-bank issuer's revenue, gross
profit, operating income and net income one year stale. These tests are that
mistake, pinned as data.
"""
from __future__ import annotations

import json

import pytest

import openinfo_reconcile as orc
import reports_catalog as rc
import catalogue.codecs as catalogue_codecs
import catalogue.financial_store as catalogue_financial_store
import catalogue.snapshots as catalogue_snapshots
import catalogue.storage as catalogue_storage

# URTS, object 18622, filed 2026-07-30, in openinfo thousands.
URTS_PL = [
    {"tnum": "010", "title": "Чистая выручка от реализации продукции (товаров, работ и услуг)",
     "value1": "237634918.00", "value2": "0.00", "value3": "264737847.00", "value4": "0.00"},
    {"tnum": "020", "title": "Себестоимость реализованной продукции (товаров, работ и услуг)",
     "value1": "0.00", "value2": "28451551.00", "value3": "0.00", "value4": "33883416.00"},
    {"tnum": "030", "title": "Валовая прибыль (убыток) от реализации продукции",
     "value1": "209183367.00", "value2": "0.00", "value3": "230854431.00", "value4": "0.00"},
    {"tnum": "100", "title": "Прибыль (убыток) от основной деятельности (стр.030-040+090)",
     "value1": "135029437.00", "value2": "0.00", "value3": "157748082.00", "value4": "0.00"},
    {"tnum": "270", "title": "Чистая прибыль (убыток) отчетного периода (стр.240-250-260)",
     "value1": "186787068.00", "value2": "0.00", "value3": "221484280.00", "value4": "0.00"},
]
URTS_BAL = [
    {"title": "Денежные средства, всего", "value1": "0.00", "value2": "6095241350.00"},
    {"title": "Долгосрочные обязательства, всего", "value1": "0.00", "value2": "0.00"},
    {"title": "Текущие обязательства, всего", "value1": "0.00", "value2": "6847597151.00"},
]


@pytest.fixture()
def metrics() -> dict:
    return orc.extract_metrics({
        "org_type": "jsc", "reporting_year": "2026-06-30",
        "quarter_financial_results_report": URTS_PL,
        "quarter_balance_sheet_report": URTS_BAL,
    })


class TestWhichColumnIsWhich:
    def test_the_reporting_period_is_the_THIRD_pair(self, metrics) -> None:
        """H1 2026, as O'zRTXB's own filing of 30.07.2026 states it."""
        assert metrics["revenue"] == pytest.approx(264_737_847)
        assert metrics["gross_profit"] == pytest.approx(230_854_431)
        assert metrics["operating_income"] == pytest.approx(157_748_082)
        assert metrics["net_income"] == pytest.approx(221_484_280)

    def test_the_comparative_is_the_first_pair(self, metrics) -> None:
        """H1 2025 — the figure this board published as H1 2026 for four months."""
        assert metrics["prior"] == {
            "revenue": pytest.approx(237_634_918),
            "gross_profit": pytest.approx(209_183_367),
            "operating_income": pytest.approx(135_029_437),
            "net_income": pytest.approx(186_787_068),
        }

    def test_a_loss_in_the_comparative_keeps_its_sign(self) -> None:
        """A result line puts a profit in the доходы column and a LOSS in the
        расходы one, unsigned — the same trap the reporting pair has."""
        loss = orc.prior_value({"tnum": "270", "title": "Чистая прибыль (убыток) отчетного периода",
                                "value3": "1.0", "value4": "0.0",
                                "value1": "0.00", "value2": "64238084.00"})

        assert loss == pytest.approx(-64_238_084)

    def test_a_bank_form_has_no_comparative_at_all(self) -> None:
        """The bank and microfinance forms publish ONE `value` column."""
        assert orc.prior_value({"title": "Чистая прибыль", "value": "123.0"}) is None
        assert orc.extract_metrics({
            "org_type": "bank", "reporting_year": "2026-06-30",
            "quarter_financial_results_report": [
                {"title": "Итого процентных доходов", "value": "500.0"},
                {"title": "Чистая прибыль", "value": "100.0"}],
            "quarter_balance_sheet_report": [],
        })["prior"] is None

    def test_the_balance_sheet_contributes_nothing_to_it(self, metrics) -> None:
        """Its two columns are "на начало года" and "на конец периода" — not last
        year's same period — so cash and liabilities have no prior figure."""
        assert set(metrics["prior"]) == {"revenue", "gross_profit",
                                         "operating_income", "net_income"}


class TestItIsLabelledWithItsOwnPeriod:
    def test_the_period_is_the_year_before_at_the_same_quarter(self, metrics) -> None:
        row = orc._figures("URTS", metrics, {"year": 2026, "quarter": 2})

        assert (row["year"], row["quarter"]) == (2026, 2)
        assert row["revenue_full"] == pytest.approx(264_737_847_000)
        assert (row["prior"]["year"], row["prior"]["quarter"]) == (2025, 2)
        assert row["prior"]["period_months"] == 6
        assert row["prior"]["revenue_thousand"] == pytest.approx(237_634_918)
        assert row["prior"]["revenue_full"] == pytest.approx(237_634_918_000)

    def test_an_annual_report_compares_with_the_year_before_it(self, metrics) -> None:
        row = orc._figures("URTS", metrics, {"year": 2025, "quarter": 0})

        assert (row["prior"]["year"], row["prior"]["quarter"]) == (2024, 0)
        assert row["prior"]["period_months"] == 12

    def test_the_push_carries_it_beside_the_row_not_as_a_row(self, metrics) -> None:
        """A period row of its own would be ranked as a period — and it has no
        balance sheet, so anything dividing by one would divide by nothing."""
        rows = orc.admin_push_rows(orc._figures("URTS", metrics, {"year": 2026, "quarter": 2}))

        assert [(r["year"], r["quarter"]) for r in rows] == [(2026, 2)]
        assert rows[0]["revenue"] == pytest.approx(264_737_847)
        assert rows[0]["prior"] == {"year": 2025, "quarter": 2,
                                    "revenue": pytest.approx(237_634_918),
                                    "gross_profit": pytest.approx(209_183_367),
                                    "operating_income": pytest.approx(135_029_437),
                                    "operating_expenses": None,
                                    "net_income": pytest.approx(186_787_068)}


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(catalogue_storage, "_catalog_db_path", lambda: str(path))
    catalogue_storage.get_catalog_conn().close()
    return str(path)


class TestItSurvivesStorage:
    def _row(self, **over) -> dict:
        row = {"ticker": "URTS", "year": 2026, "quarter": 2, "revenue": 237_634_918.0,
               "net_income": 186_787_068.0, "cash": 6_095_241_350.0,
               "prior": {"year": 2025, "quarter": 2, "revenue": 264_737_847.0,
                         "net_income": 221_484_280.0}}
        row.update(over)
        return row

    def test_it_is_stored_and_served_with_the_row(self, catalog_db) -> None:
        catalogue_financial_store.bulk_replace_financials([self._row()])

        served = catalogue_snapshots.get_all_financials()["URTS"]
        assert served["revenue"] == pytest.approx(237_634_918.0)
        assert served["prior"]["year"] == 2025
        assert served["prior"]["revenue"] == pytest.approx(264_737_847.0)
        assert served["prior"]["period_months"] == 6

    def test_it_never_becomes_a_period_of_its_own(self, catalog_db) -> None:
        catalogue_financial_store.bulk_replace_financials([self._row()])

        stored = catalogue_storage.get_catalog_conn().execute(
            "SELECT year, quarter FROM catalog_financials ORDER BY year").fetchall()
        assert [(r["year"], r["quarter"]) for r in stored] == [(2026, 2)]

    def test_a_row_with_no_comparative_stores_nothing(self, catalog_db) -> None:
        catalogue_financial_store.bulk_replace_financials([self._row(prior=None)])

        assert catalogue_snapshots.get_all_financials()["URTS"]["prior"] is None

    def test_an_all_empty_comparative_is_not_stored(self, catalog_db) -> None:
        catalogue_financial_store.bulk_replace_financials([self._row(prior={"year": 2025, "quarter": 2})])

        assert catalogue_snapshots.get_all_financials()["URTS"]["prior"] is None

    def test_a_legacy_row_written_before_the_column_still_reads(self, catalog_db) -> None:
        assert catalogue_codecs._decode_prior_period(None) is None
        assert catalogue_codecs._decode_prior_period("not json") is None
        assert catalogue_codecs._decode_prior_period(json.dumps({"revenue": 1.0})) is None
