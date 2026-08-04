"""Which openinfo filing the reconciler serves, and what period it calls it.

The regression this pins is seasonal and silent. Uzbek issuers file the first
quarter in late April and the *previous* year's annual in July, so for half the
year the newest-published filing is the oldest period on file. Selecting by
publication date therefore overwrote Q1 2026 with FY2025 every summer:

    Agrobank    FY2025 annual filed 13.07.2026   liabilities 89 822 254 380 тыс.
                2026 Q1 filed 23.04.2026         liabilities 97 442 300 703 тыс.

and the site served the annual under a row whose figures were meant to be current.
Two further defects fall out of the same place and are pinned here too: annuals
openinfo signs with a year-end that has not happened ("2026 Q4" on the board in
July 2026), and the two-column NSBU form 2, whose loss column was read as profit.
"""
from __future__ import annotations

import datetime as dt

import pytest

import openinfo_reconcile as orc

TODAY = dt.date(2026, 7, 25)


# --------------------------------------------------------------------------- #
# period derivation
# --------------------------------------------------------------------------- #
class TestPeriodFromStamp:
    def test_a_clean_quarterly_stamp_is_taken_as_is(self) -> None:
        assert orc.period_year_quarter("2026-03-31", "quarter", today=TODAY,
                                       pub_date="2026-04-23T10:00:00") == (2026, 1)

    def test_a_clean_annual_stamp_is_taken_as_is(self) -> None:
        assert orc.period_year_quarter("2025-12-31", "annual", today=TODAY,
                                       pub_date="2026-07-13T14:49:44") == (2025, 0)

    def test_an_interim_stamped_with_its_filing_day_snaps_back(self) -> None:
        # Qizilqumsement: reporting_year=2026-04-27 on a report filed 2026-05-13.
        # Q2 had not ended, so the only quarter it can describe is Q1.
        assert orc.period_year_quarter("2026-04-27", "quarter", today=TODAY,
                                       pub_date="2026-05-13T14:33:04") == (2026, 1)

    def test_an_annual_stamped_with_a_future_year_end_is_clamped(self) -> None:
        # The "2026 Q4" on the board: openinfo signed the FY2025 annual
        # 2026-12-31 and the old code mapped that to Q4 of the stamped year.
        assert orc.period_year_quarter("2026-12-31", "annual", today=TODAY,
                                       pub_date="2026-06-29T16:08:22") == (2025, 0)

    def test_an_annual_stamped_with_its_filing_day_is_clamped(self) -> None:
        assert orc.period_year_quarter("2025-06-26", "annual", today=TODAY,
                                       pub_date="2025-06-26T14:16:37") == (2024, 0)

    def test_a_late_filed_annual_keeps_its_own_older_year(self) -> None:
        # Filing late is normal and says nothing about the period — only a stamp
        # LATER than the filing can be wrong.
        assert orc.period_year_quarter("2023-12-31", "annual", today=TODAY,
                                       pub_date="2026-07-24T00:00:00") == (2023, 0)

    def test_no_stamp_is_no_period(self) -> None:
        assert orc.period_year_quarter(None, "annual", today=TODAY) == (None, None)
        assert orc.period_year_quarter("", "quarter", today=TODAY) == (None, None)

    def test_today_bounds_a_report_with_no_filing_date(self) -> None:
        assert orc.period_year_quarter("2026-12-31", "annual", today=TODAY,
                                       pub_date=None) == (2025, 0)

    @pytest.mark.parametrize(("stamp", "expected"), [
        ("2026-01-15", (2026, 1)), ("2026-03-31", (2026, 1)),
        ("2026-04-01", (2026, 2)), ("2026-06-30", (2026, 2)),
        ("2026-09-30", (2026, 3)), ("2026-12-31", (2026, 4)),
    ])
    def test_an_interim_date_snaps_to_its_enclosing_quarter(self, stamp, expected) -> None:
        # Bounded by a filing at the very end of the year so nothing is clamped.
        assert orc.period_year_quarter(stamp, "quarter", today=dt.date(2027, 6, 1),
                                       pub_date="2026-12-31T00:00:00") == expected


class TestPeriodRank:
    def test_an_annual_outranks_its_own_fourth_quarter(self) -> None:
        assert orc.period_rank(2025, 0) > orc.period_rank(2025, 4)

    def test_any_quarter_of_the_next_year_outranks_an_annual(self) -> None:
        # The whole bug in one assertion.
        assert orc.period_rank(2026, 1) > orc.period_rank(2025, 0)

    def test_it_matches_the_read_paths_sql_ranking(self) -> None:
        import reports_catalog as rc

        for year, quarter in ((2025, 0), (2025, 1), (2025, 4), (2026, 1), (2026, 3)):
            period = str(year) if not quarter else f"{year}Q{quarter}"
            y, k = rc._period_key(period)
            assert orc.period_rank(year, quarter) == y * 10 + k

    def test_an_underivable_period_ranks_below_everything(self) -> None:
        assert orc.period_rank(None, None) < orc.period_rank(1990, 1)


class TestPeriodMonths:
    @pytest.mark.parametrize(("quarter", "months"), [(0, 12), (1, 3), (2, 6), (3, 9), (4, 12)])
    def test_quarters_are_cumulative_from_january(self, quarter, months) -> None:
        assert orc.period_months(2026, quarter) == months


# --------------------------------------------------------------------------- #
# form reading
# --------------------------------------------------------------------------- #
class TestProfitAndLossSign:
    """NSBU form 2 (jsc/insurance) has a "прибыль" column and an "убыток" column,
    both holding unsigned magnitudes. Reading "the first non-zero, keeping its
    stored sign" published every loss as a profit of the same size.

    The pair that carries the REPORTING period is value3/value4 — see
    ``pl_value`` and tests/test_prior_period.py for the chronology that settles
    it. value1/value2 is the prior-year comparative."""

    def test_a_profit_sits_in_the_profit_column(self) -> None:
        assert orc.pl_value({"value3": "527145.00", "value4": "0.00"}) == 527145.0

    def test_a_loss_sits_in_the_loss_column_and_is_negative(self) -> None:
        # Qizilqumsement Q1 2026: a 64.2 bn loss, served as a 64.2 bn profit.
        assert orc.pl_value({"value3": "0.00", "value4": "64238084.00"}) == -64238084.0

    def test_a_zero_line_is_zero_not_missing(self) -> None:
        assert orc.pl_value({"value3": "0.00", "value4": "0.00"}) == 0.0

    def test_an_absent_row_is_missing(self) -> None:
        assert orc.pl_value(None) is None

    def test_the_prior_year_columns_are_never_read_as_this_period(self) -> None:
        # value1/value2 is the comparative pair — reading it as the reporting
        # period is exactly the year-stale board this replaced.
        assert orc.pl_value({"value3": "0.00", "value4": "0.00",
                             "value1": "999.00", "value2": "0.00"}) == 0.0

    def test_a_single_column_form_keeps_its_own_sign(self) -> None:
        # Banks and microfinance organisations publish one signed column.
        assert orc.pl_value({"value": "-275224.94"}) == -275224.94
        assert orc.pl_value({"value": "35928852.00"}) == 35928852.0


# --------------------------------------------------------------------------- #
# report selection
# --------------------------------------------------------------------------- #
def _jsc_detail(reporting_year: str, revenue: float, net: float,
                liabilities: float = 1000.0, cash: float = 50.0, ticker: str = "AAA") -> dict:
    """A jsc quarter/annual detail carrying one revenue and one net-profit line."""
    def pair(value: float) -> dict:
        # value3/value4 is the reporting period; value1/value2 the comparative.
        return ({"value3": f"{value:.2f}", "value4": "0.00"} if value >= 0
                else {"value3": "0.00", "value4": f"{-value:.2f}"})

    return {
        "org_type": "jsc",
        "reporting_year": reporting_year,
        "organization_ticket_name": ticker,
        "financial_results_report": [
            {"tnum": "010", "title": "Чистая выручка от реализации продукции", **pair(revenue)},
            {"tnum": "270", "title": "Чистая прибыль (убыток) отчетного периода", **pair(net)},
        ],
        "balance_sheet_report": [
            {"title": "Текущие обязательства, всего", "value1": "0.00", "value2": f"{liabilities:.2f}"},
            {"title": "Денежные средства, всего", "value1": "0.00", "value2": f"{cash:.2f}"},
        ],
    }


@pytest.fixture()
def openinfo(monkeypatch):
    """A stub issuer whose filings the test declares, with fetches counted."""
    state = {"candidates": [], "details": {}, "fetched": []}

    def _candidates(_arg):
        return sorted(state["candidates"], key=lambda c: c["pub_date"], reverse=True)

    def _fetch(cand):
        state["fetched"].append(cand["object_id"])
        return state["details"][cand["object_id"]]

    monkeypatch.setattr(orc, "org_id_for", lambda _t: None)
    monkeypatch.setattr(orc, "list_candidates", _candidates)
    monkeypatch.setattr(orc, "fetch_detail", _fetch)

    def add(object_id, period_type, pub_date, reporting_year, revenue=1000.0, net=100.0,
            **balance):
        state["candidates"].append({
            "object_id": object_id, "org_type": "jsc", "period_type": period_type,
            "pub_date": pub_date, "organization": 1,
        })
        state["details"][object_id] = _jsc_detail(reporting_year, revenue, net, **balance)

    state["add"] = add
    return state


class TestTheSummerOverwrite:
    """The reported defect: the annual filed in July is not the latest period."""

    def test_a_july_annual_does_not_beat_an_april_quarter(self, openinfo) -> None:
        openinfo["add"](1, "annual", "2026-07-13T14:49:44", "2025-12-31", revenue=17_518.0)
        openinfo["add"](2, "quarter", "2026-04-23T10:00:00", "2026-03-31", revenue=5_530.0)

        best, annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2026, 1)
        assert best["metrics"]["revenue"] == 5_530.0
        assert (annual["meta"]["year"], annual["meta"]["quarter"]) == (2025, 0)
        assert annual["metrics"]["revenue"] == 17_518.0

    def test_the_annual_still_wins_when_it_is_the_latest_period(self, openinfo) -> None:
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31", revenue=17_518.0)
        openinfo["add"](2, "quarter", "2025-10-30T00:00:00", "2025-09-30", revenue=4_000.0)

        best, annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2025, 0)
        assert best["metrics"]["revenue"] == 17_518.0
        # No companion: the row already IS a complete year.
        assert annual is None

    def test_a_future_stamped_annual_never_produces_a_future_quarter(self, openinfo) -> None:
        # Qizilqumsement / O'zQEQ, which sat at "2026 Q4" on a July 2026 board.
        openinfo["add"](1, "annual", "2026-06-29T16:08:22", "2026-12-31", revenue=1_538.0)
        openinfo["add"](2, "quarter", "2026-05-13T14:33:04", "2026-04-27", revenue=275.0)

        best, annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2026, 1)
        assert (annual["meta"]["year"], annual["meta"]["quarter"]) == (2025, 0)
        assert best["metrics"]["revenue"] == 275.0

    def test_publication_date_only_breaks_ties_within_one_period(self, openinfo) -> None:
        # A restated/audited refiling of the same quarter — the later one wins.
        openinfo["add"](1, "quarter", "2026-06-01T00:00:00", "2026-03-31", revenue=999.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", revenue=111.0)

        best, _annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2026, 1)
        assert best["metrics"]["revenue"] == 999.0

    def test_an_empty_placeholder_is_skipped_for_the_period_below_it(self, openinfo) -> None:
        openinfo["add"](1, "quarter", "2026-07-20T00:00:00", "2026-06-30",
                        revenue=0.0, net=0.0, liabilities=0.0, cash=0.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", revenue=5_530.0)

        best, _annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2026, 1)
        assert best["metrics"]["revenue"] == 5_530.0

    def test_older_filings_are_not_fetched_once_they_cannot_win(self, openinfo) -> None:
        # The walk is newest-filed first and a filing cannot describe a period
        # that ends after it — so everything below the best period in hand is
        # skipped without a request. Without this, ranking by period would cost a
        # detail fetch per filing per ticker on every collector run.
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31")
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31")
        openinfo["add"](3, "quarter", "2026-01-30T00:00:00", "2025-12-31")
        openinfo["add"](4, "quarter", "2025-10-30T00:00:00", "2025-09-30")

        orc.select_reports("AAA", today=TODAY)

        assert openinfo["fetched"] == [1, 2]

    def test_a_report_with_no_readable_period_is_skipped(self, openinfo) -> None:
        openinfo["add"](1, "quarter", "2026-07-20T00:00:00", "", revenue=999.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", revenue=5_530.0)

        best, _annual, meta = orc.select_reports("AAA", today=TODAY)

        assert (meta["year"], meta["quarter"]) == (2026, 1)
        assert best["metrics"]["revenue"] == 5_530.0

    def test_no_candidates_is_reported_not_guessed(self, openinfo) -> None:
        best, annual, meta = orc.select_reports("AAA", today=TODAY)

        assert best is None and annual is None
        assert meta["error"] == "no candidates"


class TestReconciledRow:
    def test_the_row_carries_its_period_length_and_annual_companion(self, openinfo, monkeypatch) -> None:
        monkeypatch.setattr(orc, "NO_SOURCE", set())
        monkeypatch.setattr(orc, "MANUAL_SKIP", set())
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31", net=400.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", net=100.0)

        row, _meta = orc.reconcile_ticker("AAA", today=TODAY)

        assert (row["year"], row["quarter"]) == (2026, 1)
        assert row["period_months"] == 3 and row["is_ytd"] is True
        assert row["net_income_thousand"] == 100.0
        assert row["net_income_full"] == 100_000.0
        assert row["annual"]["year"] == 2025 and row["annual"]["period_months"] == 12
        assert row["annual"]["net_income_thousand"] == 400.0

    def test_both_periods_are_pushed(self, openinfo, monkeypatch) -> None:
        # mode=replace clears the ticker first, so a period missing from this list
        # stops being served — including the 12-month figure ratios divide by.
        monkeypatch.setattr(orc, "NO_SOURCE", set())
        monkeypatch.setattr(orc, "MANUAL_SKIP", set())
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31", net=400.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", net=100.0)

        row, _meta = orc.reconcile_ticker("AAA", today=TODAY)
        pushed = orc.admin_push_rows(row)

        assert [(r["year"], r["quarter"]) for r in pushed] == [(2026, 1), (2025, 0)]
        assert [r["net_income"] for r in pushed] == [100.0, 400.0]

    def test_an_annual_row_pushes_one_period(self, openinfo, monkeypatch) -> None:
        monkeypatch.setattr(orc, "NO_SOURCE", set())
        monkeypatch.setattr(orc, "MANUAL_SKIP", set())
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31", net=400.0)

        row, _meta = orc.reconcile_ticker("AAA", today=TODAY)

        assert row["annual"] is None
        assert len(orc.admin_push_rows(row)) == 1


class TestFieldProvenance:
    """Every figure in a reconciled row comes from ONE filing, which is why
    ``field_periods`` is empty for these rows rather than unfilled. The moment a
    row is assembled from more than one report, the period of the borrowed field
    has to travel with it — that is what field_periods is for, and this pins the
    invariant so a future merge cannot land silently."""

    def test_a_reconciled_row_declares_no_borrowed_periods(self, openinfo, monkeypatch) -> None:
        monkeypatch.setattr(orc, "NO_SOURCE", set())
        monkeypatch.setattr(orc, "MANUAL_SKIP", set())
        openinfo["add"](1, "quarter", "2026-04-23T00:00:00", "2026-03-31")

        row, _meta = orc.reconcile_ticker("AAA", today=TODAY)
        pushed = orc.admin_push_rows(row)[0]

        assert not pushed.get("field_periods")

    def test_the_companion_is_a_separate_row_not_a_merge(self, openinfo, monkeypatch) -> None:
        # The annual travels as its own period row. Folding its figures into the
        # quarter's row instead would be exactly the silent cross-period mix that
        # field_periods exists to prevent.
        monkeypatch.setattr(orc, "NO_SOURCE", set())
        monkeypatch.setattr(orc, "MANUAL_SKIP", set())
        openinfo["add"](1, "annual", "2026-07-13T00:00:00", "2025-12-31", revenue=17_518.0)
        openinfo["add"](2, "quarter", "2026-04-23T00:00:00", "2026-03-31", revenue=5_530.0)

        row, _meta = orc.reconcile_ticker("AAA", today=TODAY)

        assert row["revenue_thousand"] == 5_530.0
        assert row["annual"]["revenue_thousand"] == 17_518.0
        assert all(not r.get("field_periods") for r in orc.admin_push_rows(row))
