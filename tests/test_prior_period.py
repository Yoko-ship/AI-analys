"""The comparative column is a different period, not a different number.

O'zRTXB's H1 2026 report gives revenue as 237 634 918 (thousand UZS) and prints
264 737 847 in the cell beside it. Read across the row in openinfo's Excel and
the second one looks like the figure the board is getting wrong — it is the same
line for H1 2025. NSBU form 2 carries FOUR value columns: value1/value2 are
"доходы (прибыль)" and "расходы (убытки)" for the reporting period, value3/value4
the same pair "за соответствующий период прошлого года".

Each pair balances against itself, which is what proves they are two statements
and not one:

    отчётный:  237 634 918 - 28 451 551 = 209 183 367 = row 030 value1
    прошлый:   264 737 847 - 33 883 416 = 230 854 431 = row 030 value3

So the comparative is collected as what it is — labelled with its own period,
carried on the filing that printed it, and never mistaken for this period's.
"""
from __future__ import annotations

import json

import pytest

import openinfo_reconcile as orc
import reports_catalog as rc

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
    def test_the_reporting_period_is_the_first_pair(self, metrics) -> None:
        assert metrics["revenue"] == pytest.approx(237_634_918)
        assert metrics["gross_profit"] == pytest.approx(209_183_367)
        assert metrics["operating_income"] == pytest.approx(135_029_437)
        assert metrics["net_income"] == pytest.approx(186_787_068)

    def test_the_comparative_is_the_second_pair(self, metrics) -> None:
        assert metrics["prior"] == {
            "revenue": pytest.approx(264_737_847),
            "gross_profit": pytest.approx(230_854_431),
            "operating_income": pytest.approx(157_748_082),
            "net_income": pytest.approx(221_484_280),
        }

    def test_a_loss_in_the_comparative_keeps_its_sign(self) -> None:
        """A result line puts a profit in the доходы column and a LOSS in the
        расходы one, unsigned — the same trap value1/value2 already had."""
        loss = orc.prior_value({"tnum": "270", "title": "Чистая прибыль (убыток) отчетного периода",
                                "value1": "1.0", "value2": "0.0",
                                "value3": "0.00", "value4": "64238084.00"})

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
        assert (row["prior"]["year"], row["prior"]["quarter"]) == (2025, 2)
        assert row["prior"]["period_months"] == 6
        assert row["prior"]["revenue_thousand"] == pytest.approx(264_737_847)
        assert row["prior"]["revenue_full"] == pytest.approx(264_737_847_000)

    def test_an_annual_report_compares_with_the_year_before_it(self, metrics) -> None:
        row = orc._figures("URTS", metrics, {"year": 2025, "quarter": 0})

        assert (row["prior"]["year"], row["prior"]["quarter"]) == (2024, 0)
        assert row["prior"]["period_months"] == 12

    def test_the_push_carries_it_beside_the_row_not_as_a_row(self, metrics) -> None:
        """A period row of its own would be ranked as a period — and it has no
        balance sheet, so anything dividing by one would divide by nothing."""
        rows = orc.admin_push_rows(orc._figures("URTS", metrics, {"year": 2026, "quarter": 2}))

        assert [(r["year"], r["quarter"]) for r in rows] == [(2026, 2)]
        assert rows[0]["prior"] == {"year": 2025, "quarter": 2,
                                    "revenue": pytest.approx(264_737_847),
                                    "gross_profit": pytest.approx(230_854_431),
                                    "operating_income": pytest.approx(157_748_082),
                                    "net_income": pytest.approx(221_484_280)}


@pytest.fixture()
def catalog_db(tmp_path, monkeypatch):
    path = tmp_path / "catalog.db"
    monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(path))
    rc.get_catalog_conn().close()
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
        rc.bulk_replace_financials([self._row()])

        served = rc.get_all_financials()["URTS"]
        assert served["revenue"] == pytest.approx(237_634_918.0)
        assert served["prior"]["year"] == 2025
        assert served["prior"]["revenue"] == pytest.approx(264_737_847.0)
        assert served["prior"]["period_months"] == 6

    def test_it_never_becomes_a_period_of_its_own(self, catalog_db) -> None:
        rc.bulk_replace_financials([self._row()])

        stored = rc.get_catalog_conn().execute(
            "SELECT year, quarter FROM catalog_financials ORDER BY year").fetchall()
        assert [(r["year"], r["quarter"]) for r in stored] == [(2026, 2)]

    def test_a_row_with_no_comparative_stores_nothing(self, catalog_db) -> None:
        rc.bulk_replace_financials([self._row(prior=None)])

        assert rc.get_all_financials()["URTS"]["prior"] is None

    def test_an_all_empty_comparative_is_not_stored(self, catalog_db) -> None:
        rc.bulk_replace_financials([self._row(prior={"year": 2025, "quarter": 2})])

        assert rc.get_all_financials()["URTS"]["prior"] is None

    def test_a_legacy_row_written_before_the_column_still_reads(self, catalog_db) -> None:
        assert rc._decode_prior_period(None) is None
        assert rc._decode_prior_period("not json") is None
        assert rc._decode_prior_period(json.dumps({"revenue": 1.0})) is None
