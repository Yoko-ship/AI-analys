"""Cumulative NSBU quarters must leave the API as three-month columns.

NSBU quarterly form 2 is a running total from 1 January — a Q2 revenue is six
months of revenue — and no issuer on this market files a fourth quarterly: the
annual report IS the Q4 disclosure. `derive_quarterly_series` is the arithmetic
that turns the filings into the standard discrete-quarter presentation, and
these are its rules: difference the flows, pass the balance snapshots through,
form Q4 from the annual, and yield a dash rather than a running total wherever
the predecessor filing is missing.
"""
from __future__ import annotations

import catalogue.snapshots as catalogue_snapshots

import server.company.financials as subject_server_company_financials

import server.company.financials as subject_server_company_financials

import api


def _cum(**periods: dict) -> dict:
    return dict(periods)


class TestFlowsAreDifferenced:
    def test_q1_is_the_filing_itself(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0, "net_income": 10.0}}, {})

        assert periods == ["2024Q1"]
        assert series["net_revenue"]["2024Q1"] == 100.0
        assert series["net_profit"]["2024Q1"] == 10.0

    def test_later_quarters_are_the_difference_of_running_totals(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0},
             "2024Q2": {"revenue": 250.0},
             "2024Q3": {"revenue": 300.0}}, {})

        assert series["net_revenue"] == {"2024Q1": 100.0, "2024Q2": 150.0, "2024Q3": 50.0}

    def test_filed_period_expenses_are_differenced_like_other_income_statement_flows(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2026Q1": {"revenue": 100.0, "operating_expenses": 74.424438},
             "2026Q2": {"revenue": 250.0, "operating_expenses": 151.604589}}, {})

        assert periods == ["2026Q2", "2026Q1"]
        assert series["operating_expenses"] == {
            "2026Q1": 74.424438,
            "2026Q2": 77.180151,
        }

    def test_a_missing_predecessor_yields_no_figure_not_a_running_total(self):
        """A six-month sum in a column of quarters is the «full year beside a
        quarter» defect — absence is the honest answer."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q2": {"revenue": 250.0}}, {})

        assert "2024Q2" not in series.get("net_revenue", {})

    def test_a_loss_quarter_goes_negative_and_stays(self):
        """Cumulative PROFIT legitimately falls when a quarter loses money —
        only the revenue witness polices the chain, never the profit lines."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0, "net_income": 40.0},
             "2024Q2": {"revenue": 250.0, "net_income": 25.0}}, {})

        assert series["net_profit"]["2024Q2"] == -15.0


class TestQ4ComesFromTheAnnual:
    def test_q4_is_the_annual_less_the_nine_month_filing(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q3": {"revenue": 300.0, "cash": 40.0}},
            {"2024": {"revenue": 420.0, "cash": 55.0}})

        assert series["net_revenue"]["2024Q4"] == 120.0
        # The year-end snapshot doubles as Q4's, untouched.
        assert series["cash"]["2024Q4"] == 55.0

    def test_no_q4_without_the_nine_month_filing_to_subtract(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0, "cash": 20.0}},
            {"2024": {"revenue": 420.0, "cash": 55.0}})

        assert "2024Q4" not in series.get("net_revenue", {})
        # ... but the balance snapshot needs no subtraction and still lands.
        assert series["cash"]["2024Q4"] == 55.0

    def test_an_annual_only_year_synthesises_no_quarters(self):
        """An issuer that files no quarterlies must not grow a lone Q4 column —
        that would dress the annual view up as a quarterly one."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2023Q1": {"revenue": 10.0}},
            {"2024": {"revenue": 420.0}})

        assert all(not p.startswith("2024") for p in periods)


class TestStocksPassThrough:
    def test_balance_lines_are_snapshots_not_differences(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"cash": 20.0, "total_liabilities": 200.0},
             "2024Q2": {"cash": 30.0, "total_liabilities": 180.0}}, {})

        assert series["cash"] == {"2024Q1": 20.0, "2024Q2": 30.0}
        assert series["total_liabilities"] == {"2024Q1": 200.0, "2024Q2": 180.0}

    def test_assets_and_equity_pass_through_and_q4_takes_the_annuals(self):
        """The quarterly Баланс shows the annual view's three lines — Активы,
        Обязательства, Капитал — so the balance totals ride the same snapshot
        rule as cash, year-end doubling as Q4's."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q3": {"revenue": 300.0, "total_assets": 1000.0, "total_equity": 400.0}},
            {"2024": {"revenue": 420.0, "total_assets": 1100.0, "total_equity": 450.0}})

        assert series["total_assets"] == {"2024Q3": 1000.0, "2024Q4": 1100.0}
        assert series["total_equity"] == {"2024Q3": 400.0, "2024Q4": 450.0}


class TestEquityByIdentity:
    """assets = liabilities + equity on every published balance, so a period
    that states the first two states the third — the dash was a presentation
    gap, not a missing fact."""

    def _series(self, equity_values=None, with_equity=True):
        s = {"total_assets": {"unit": "UZS", "money": True,
                              "values": {"2015": 1000.0, "2016": 1200.0}},
             "total_liabilities": {"unit": "UZS", "money": True,
                                   "values": {"2015": 600.0, "2016": 700.0}}}
        if with_equity:
            s["total_equity"] = {"unit": "UZS", "money": True,
                                 "values": dict(equity_values or {})}
        return s

    def test_a_missing_period_is_closed_by_the_identity(self):
        s = self._series(equity_values={"2016": 480.0})
        subject_server_company_financials._fill_equity_by_identity(s)
        assert s["total_equity"]["values"]["2015"] == 400.0
        # ... and a figure the source carries always wins over the derivation.
        assert s["total_equity"]["values"]["2016"] == 480.0

    def test_an_absent_series_is_created_and_marked_derived(self):
        s = self._series(with_equity=False)
        subject_server_company_financials._fill_equity_by_identity(s)
        assert s["total_equity"]["derived"] is True
        assert s["total_equity"]["values"] == {"2015": 400.0, "2016": 500.0}

    def test_one_side_missing_derives_nothing(self):
        s = {"total_assets": {"unit": "UZS", "money": True, "values": {"2015": 1000.0}}}
        subject_server_company_financials._fill_equity_by_identity(s)
        assert "total_equity" not in s


class TestBalancePeriodFallback:
    def test_a_row_without_the_columns_reads_its_filed_balance_block(self):
        """Rows the reconcile pushed before the total_assets/total_equity
        columns existed carry the same figures in balance_period; the series
        reader serves them rather than a dash on the newest quarters."""
        import reports_catalog as rc
        import catalogue.snapshots as catalogue_snapshots

        row = {"revenue": 100.0, "gross_profit": None, "cash": 5.0,
               "total_liabilities": 600.0, "net_income": 10.0,
               "operating_income": None, "total_assets": None, "total_equity": None,
               "balance_period": '{"assets_end": 1000.0, "assets_start": 900.0, '
                                 '"equity_end": 400.0, "equity_start": 380.0}'}
        fields = catalogue_snapshots._fin_row_fields(row)
        assert fields["total_assets"] == 1000.0
        assert fields["total_equity"] == 400.0

    def test_the_columns_win_over_the_balance_block(self):
        import reports_catalog as rc
        import catalogue.snapshots as catalogue_snapshots

        row = {"revenue": None, "gross_profit": None, "cash": None,
               "total_liabilities": None, "net_income": None,
               "operating_income": None, "total_assets": 1234.0, "total_equity": None,
               "balance_period": '{"assets_end": 1000.0, "equity_end": 400.0}'}
        fields = catalogue_snapshots._fin_row_fields(row)
        assert fields["total_assets"] == 1234.0
        assert fields["total_equity"] == 400.0


class TestTheWitnessLine:
    """Cumulative revenue cannot decrease; a filing that breaks the year's
    chain misstates its period and its INCOME lines must not be differenced."""

    def test_tnbn_2023_q1_larger_than_the_half_year_is_dropped_not_subtracted(self):
        """The live defect: 932 B «Q1» against a 585 B half-year printed a
        revenue of −347 B. The odd point out loses its flows; its balance
        snapshot stays."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2023Q1": {"revenue": 932.0, "net_income": 21.0, "cash": 50.0},
             "2023Q2": {"revenue": 585.0, "net_income": 28.0},
             "2023Q3": {"revenue": 894.0, "net_income": 33.0}},
            {"2023": {"revenue": 1256.0}})

        assert "2023Q1" not in series["net_revenue"]
        assert "2023Q1" not in series["net_profit"]
        assert series["cash"]["2023Q1"] == 50.0
        # Q2 has no trusted predecessor left — a dash, never the running total.
        assert "2023Q2" not in series["net_revenue"]
        assert series["net_revenue"]["2023Q3"] == 894.0 - 585.0
        assert series["net_revenue"]["2023Q4"] == 1256.0 - 894.0

    def test_an_empty_annual_never_becomes_a_negative_q4(self):
        """SQBN 2024: a zero annual against a 8 018 B nine-month would have
        printed Q4 revenue of −8 T. The rejected annual contributes nothing —
        not even its (equally empty) balance."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 2551.0}, "2024Q2": {"revenue": 5196.0},
             "2024Q3": {"revenue": 8018.0, "cash": 100.0}},
            {"2024": {"revenue": 0.0, "cash": 0.0}})

        assert "2024Q4" not in periods
        assert series["net_revenue"]["2024Q3"] == 8018.0 - 5196.0

    def test_a_consistent_chain_is_left_alone(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0}, "2024Q2": {"revenue": 100.0},
             "2024Q3": {"revenue": 300.0}},
            {"2024": {"revenue": 420.0}})

        assert series["net_revenue"] == {"2024Q1": 100.0, "2024Q2": 0.0,
                                         "2024Q3": 200.0, "2024Q4": 120.0}

    def test_on_a_tie_the_later_filing_is_believed(self):
        """KSCM 2024: Q1 36.5 against Q2 27.3 with Q3 91.5 — either of the
        first two chains with Q3. The later filing wins the tie."""
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 36.5}, "2024Q2": {"revenue": 27.3},
             "2024Q3": {"revenue": 91.5}}, {})

        assert "2024Q1" not in series["net_revenue"]
        assert series["net_revenue"]["2024Q3"] == 91.5 - 27.3


class TestHygiene:
    def test_an_all_zero_row_is_an_empty_filing_and_is_dropped(self):
        periods, series = subject_server_company_financials.derive_quarterly_series(
            {"2024Q1": {"revenue": 0.0, "net_income": 0.0, "cash": 0.0}}, {})

        assert periods == []

    def test_periods_come_newest_first(self):
        periods, _ = subject_server_company_financials.derive_quarterly_series(
            {"2023Q3": {"revenue": 3.0, "cash": 5.0}, "2024Q1": {"revenue": 2.0},
             "2023Q1": {"revenue": 1.0}}, {})

        assert periods == ["2024Q1", "2023Q3", "2023Q1"]

    def test_a_quarter_with_nothing_derivable_gets_no_column(self):
        """A lone cumulative Q3 (no Q2 to subtract, no balance snapshot) has no
        figure to show — a column of dashes would be noise."""
        periods, _ = subject_server_company_financials.derive_quarterly_series({"2023Q3": {"revenue": 1.0}}, {})

        assert periods == []
