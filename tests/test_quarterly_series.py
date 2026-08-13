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

import api


def _cum(**periods: dict) -> dict:
    return dict(periods)


class TestFlowsAreDifferenced:
    def test_q1_is_the_filing_itself(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0, "net_income": 10.0}}, {})

        assert periods == ["2024Q1"]
        assert series["net_revenue"]["2024Q1"] == 100.0
        assert series["net_profit"]["2024Q1"] == 10.0

    def test_later_quarters_are_the_difference_of_running_totals(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0},
             "2024Q2": {"revenue": 250.0},
             "2024Q3": {"revenue": 300.0}}, {})

        assert series["net_revenue"] == {"2024Q1": 100.0, "2024Q2": 150.0, "2024Q3": 50.0}

    def test_a_missing_predecessor_yields_no_figure_not_a_running_total(self):
        """A six-month sum in a column of quarters is the «full year beside a
        quarter» defect — absence is the honest answer."""
        periods, series = api.derive_quarterly_series(
            {"2024Q2": {"revenue": 250.0}}, {})

        assert "2024Q2" not in series.get("net_revenue", {})

    def test_a_restated_quarter_may_go_negative_and_stays(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"revenue": 300.0}, "2024Q2": {"revenue": 250.0}}, {})

        assert series["net_revenue"]["2024Q2"] == -50.0


class TestQ4ComesFromTheAnnual:
    def test_q4_is_the_annual_less_the_nine_month_filing(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q3": {"revenue": 300.0, "cash": 40.0}},
            {"2024": {"revenue": 420.0, "cash": 55.0}})

        assert series["net_revenue"]["2024Q4"] == 120.0
        # The year-end snapshot doubles as Q4's, untouched.
        assert series["cash"]["2024Q4"] == 55.0

    def test_no_q4_without_the_nine_month_filing_to_subtract(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"revenue": 100.0, "cash": 20.0}},
            {"2024": {"revenue": 420.0, "cash": 55.0}})

        assert "2024Q4" not in series.get("net_revenue", {})
        # ... but the balance snapshot needs no subtraction and still lands.
        assert series["cash"]["2024Q4"] == 55.0

    def test_an_annual_only_year_synthesises_no_quarters(self):
        """An issuer that files no quarterlies must not grow a lone Q4 column —
        that would dress the annual view up as a quarterly one."""
        periods, series = api.derive_quarterly_series(
            {"2023Q1": {"revenue": 10.0}},
            {"2024": {"revenue": 420.0}})

        assert all(not p.startswith("2024") for p in periods)


class TestStocksPassThrough:
    def test_balance_lines_are_snapshots_not_differences(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"cash": 20.0, "total_liabilities": 200.0},
             "2024Q2": {"cash": 30.0, "total_liabilities": 180.0}}, {})

        assert series["cash"] == {"2024Q1": 20.0, "2024Q2": 30.0}
        assert series["total_liabilities"] == {"2024Q1": 200.0, "2024Q2": 180.0}


class TestHygiene:
    def test_an_all_zero_row_is_an_empty_filing_and_is_dropped(self):
        periods, series = api.derive_quarterly_series(
            {"2024Q1": {"revenue": 0.0, "net_income": 0.0, "cash": 0.0}}, {})

        assert periods == []

    def test_periods_come_newest_first(self):
        periods, _ = api.derive_quarterly_series(
            {"2023Q3": {"revenue": 1.0, "cash": 5.0}, "2024Q1": {"revenue": 2.0},
             "2023Q1": {"revenue": 3.0}}, {})

        assert periods == ["2024Q1", "2023Q3", "2023Q1"]

    def test_a_quarter_with_nothing_derivable_gets_no_column(self):
        """A lone cumulative Q3 (no Q2 to subtract, no balance snapshot) has no
        figure to show — a column of dashes would be noise."""
        periods, _ = api.derive_quarterly_series({"2023Q3": {"revenue": 1.0}}, {})

        assert periods == []
