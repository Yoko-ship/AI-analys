"""Period ranking, de-cumulation and annualization — the numeric transforms.

These helpers decide which figure is "latest" and how a cumulative quarter is
converted to a comparable number. They are where the sign and unit-scale bugs
lived, and until now they had no test coverage at all.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

import analysis_service as svc
import reports_catalog as rc


class TestPeriodKey:
    """An annual is the year's FINAL figure, so it outranks that year's quarters."""

    @pytest.mark.parametrize(("period", "expected"), [
        ("2024", (2024, 5)),
        ("2024Q1", (2024, 1)),
        ("2024Q4", (2024, 4)),
        ("", (0, 0)),
        (None, (0, 0)),
        ("2024Q7", (0, 0)),      # corrupt source period — must never win
        ("2024Q0", (0, 0)),
        ("garbage", (0, 0)),
        ("24", (0, 0)),
    ])
    def test_keys(self, period, expected) -> None:
        assert rc._period_key(period) == expected

    def test_an_annual_outranks_its_own_quarters(self) -> None:
        assert rc._period_key("2024") > rc._period_key("2024Q4")

    def test_a_later_year_outranks_an_earlier_annual(self) -> None:
        assert rc._period_key("2025Q1") > rc._period_key("2024")

    def test_corrupt_periods_lose_to_everything_real(self) -> None:
        # '2025Q7' > '2025Q3' lexicographically, which is how it used to win.
        assert rc._period_key("2025Q7") < rc._period_key("2015Q1")


class TestPrematureAnnuals:
    def test_the_current_year_annual_is_premature(self) -> None:
        current = datetime.now(timezone.utc).year
        assert rc._is_premature_annual_period(str(current)) is True
        assert rc._is_premature_annual_year(current) is True

    def test_last_completed_year_is_not(self) -> None:
        assert rc._is_premature_annual_period(str(rc._latest_complete_fiscal_year())) is False

    def test_a_current_year_quarter_stays_valid(self) -> None:
        # Quarterly filings are point-in-time; only the ANNUAL placeholder is fake.
        current = datetime.now(timezone.utc).year
        assert rc._is_premature_annual_period(f"{current}Q1") is False

    def test_a_premature_annual_ranks_below_every_real_period(self) -> None:
        current = datetime.now(timezone.utc).year
        assert rc._fact_period_rank(str(current)) < rc._fact_period_rank("2015Q1")

    def test_but_still_above_junk(self) -> None:
        # An issuer whose ONLY datum is the placeholder should show it, not nothing.
        current = datetime.now(timezone.utc).year
        assert rc._fact_period_rank(str(current)) > rc._fact_period_rank("2025Q7")


class TestFinancialsPeriodSelectionSql:
    """The SQL ranking must agree with _period_key, and it did not.

    Rows are stored with quarter = 0 for an annual, so `MAX(year * 10 + quarter)`
    ranked a completed FY2025 annual BELOW 2025 Q1.
    """

    @pytest.fixture()
    def catalog(self, tmp_path, monkeypatch) -> sqlite3.Connection:
        db = tmp_path / "catalog.sqlite3"
        monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
        monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a, **k: None)
        monkeypatch.setenv("FINANCIALS_ENRICH_ON_READ", "0")
        conn = rc.get_catalog_conn()
        yield conn
        conn.close()

    def _insert(self, conn, ticker, year, quarter, revenue) -> None:
        conn.execute(
            "INSERT INTO catalog_financials (ticker, form, year, quarter, revenue) "
            "VALUES (?, 'NSBU', ?, ?, ?)",
            (ticker, year, quarter, revenue),
        )
        conn.commit()

    def test_a_completed_annual_beats_the_same_years_q1(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "AAA", last_fy, 1, 100.0)
        self._insert(catalog, "AAA", last_fy, 0, 400.0)  # the full year

        got = rc.get_all_financials()

        assert got["AAA"]["quarter"] == 0, "Q1 outranked its own completed annual"
        assert got["AAA"]["revenue"] == 400.0

    def test_a_newer_quarter_beats_an_older_annual(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "BBB", last_fy - 1, 0, 400.0)
        self._insert(catalog, "BBB", last_fy, 1, 100.0)

        got = rc.get_all_financials()

        assert (got["BBB"]["year"], got["BBB"]["quarter"]) == (last_fy, 1)

    def test_a_premature_annual_is_excluded(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "CCC", last_fy, 0, 400.0)
        self._insert(catalog, "CCC", last_fy + 2, 0, 999.0)  # placeholder

        got = rc.get_all_financials()

        assert got["CCC"]["year"] == last_fy

    def test_an_out_of_range_quarter_is_excluded(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "DDD", last_fy, 2, 200.0)
        self._insert(catalog, "DDD", last_fy, 7, 999.0)  # corrupt; ranked highest before

        got = rc.get_all_financials()

        assert got["DDD"]["quarter"] == 2
        assert got["DDD"]["revenue"] == 200.0

    def test_a_future_year_quarter_does_not_outrank_a_real_one(self, catalog) -> None:
        # A quarter mis-stamped years ahead is not a filing that can exist yet.
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "EEE", last_fy, 3, 300.0)
        self._insert(catalog, "EEE", last_fy + 5, 1, 999.0)

        got = rc.get_all_financials()

        assert got["EEE"]["revenue"] == 300.0, "a future-dated quarter won 'latest period'"

    def test_is_ytd_flags_a_cumulative_quarter(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "FFF", last_fy, 2, 200.0)
        assert rc.get_all_financials()["FFF"]["is_ytd"] is True

    def test_is_ytd_is_false_for_an_annual(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        self._insert(catalog, "GGG", last_fy, 0, 400.0)
        assert rc.get_all_financials()["GGG"]["is_ytd"] is False


class TestFuturePeriodsAreRefusedAtTheWriteBoundary:
    """The last defence for the period label.

    QZSM and UQEQ reached the served cache stamped "2026 Q4" — a quarter still
    months away — because openinfo signed their annual reports with a future
    year-end. A period is a claim about a closed interval; if the interval is
    still open the row is not a report, and no amount of ranking downstream can
    recover from having stored it.
    """

    @pytest.fixture()
    def catalog(self, tmp_path, monkeypatch) -> sqlite3.Connection:
        db = tmp_path / "catalog.sqlite3"
        monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
        monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a, **k: None)
        monkeypatch.setenv("FINANCIALS_ENRICH_ON_READ", "0")
        conn = rc.get_catalog_conn()
        yield conn
        conn.close()

    def _row(self, ticker: str, year: int, quarter: int, revenue: float) -> dict:
        return {"ticker": ticker, "year": year, "quarter": quarter, "revenue": revenue}

    def test_a_quarter_that_has_not_ended_is_rejected(self, catalog) -> None:
        current = datetime.now(timezone.utc).year
        assert rc.bulk_replace_financials([self._row("AAA", current, 4, 999.0)]) == 0
        assert rc.get_all_financials() == {}

    def test_an_annual_for_an_unfinished_year_is_rejected(self, catalog) -> None:
        current = datetime.now(timezone.utc).year
        assert rc.bulk_upsert_financials([self._row("AAA", current, 0, 999.0)]) == 0
        assert rc.get_all_financials() == {}

    def test_a_completed_period_is_stored(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        assert rc.bulk_replace_financials([self._row("AAA", last_fy, 0, 400.0)]) == 1
        assert rc.get_all_financials()["AAA"]["revenue"] == 400.0

    def test_a_rejected_row_does_not_wipe_what_is_already_stored(self, catalog) -> None:
        # The replace push clears a ticker before inserting. Clearing it for a row
        # that then turns out to be unstorable would trade a stale figure for none.
        last_fy = rc._latest_complete_fiscal_year()
        rc.bulk_replace_financials([self._row("AAA", last_fy, 0, 400.0)])

        rc.bulk_replace_financials([self._row("AAA", last_fy + 1, 4, 999.0)])

        assert rc.get_all_financials()["AAA"]["revenue"] == 400.0

    @pytest.mark.parametrize(("year", "quarter", "future"), [
        (2020, 1, False), (2020, 0, False),
        (2999, 1, True), (2999, 0, True),
        (None, 0, False),        # no period to judge
    ])
    def test_the_predicate(self, year, quarter, future) -> None:
        assert rc._is_future_period(year, quarter) is future


class TestSeveralPeriodsPerTicker:
    """A replace push carries the latest period AND the last complete year.

    Deleting per row — correct while every ticker had exactly one — keeps only
    whichever period happens to be written last, so the 12-month figure every
    ratio divides by would vanish the moment the companion was added.
    """

    @pytest.fixture()
    def catalog(self, tmp_path, monkeypatch) -> sqlite3.Connection:
        db = tmp_path / "catalog.sqlite3"
        monkeypatch.setattr(rc, "_catalog_db_path", lambda: str(db))
        monkeypatch.setattr(rc, "_maybe_seed_financials", lambda *a, **k: None)
        monkeypatch.setenv("FINANCIALS_ENRICH_ON_READ", "0")
        conn = rc.get_catalog_conn()
        yield conn
        conn.close()

    def test_both_periods_survive_the_replace(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        rows = [
            {"ticker": "AAA", "year": last_fy + 1, "quarter": 1, "net_income": 100.0},
            {"ticker": "AAA", "year": last_fy, "quarter": 0, "net_income": 400.0},
        ]

        assert rc.bulk_replace_financials(rows) == 2

        got = rc.get_all_financials()["AAA"]
        assert (got["year"], got["quarter"]) == (last_fy + 1, 1)
        assert got["net_income"] == 100.0
        assert got["annual"]["year"] == last_fy
        assert got["annual"]["net_income"] == 400.0

    def test_the_replace_still_clears_a_period_that_would_shadow_the_push(self, catalog) -> None:
        """Only a period ranked ABOVE the newest one pushed is stale.

        That is the whole of what a replace exists to remove — a spurious future
        quarter that the read path would serve as the latest figure.
        """
        last_fy = rc._latest_complete_fiscal_year()
        rc.bulk_upsert_financials([{"ticker": "AAA", "year": last_fy, "quarter": 3, "net_income": 7.0}])

        rc.bulk_replace_financials([{"ticker": "AAA", "year": last_fy, "quarter": 0, "net_income": 400.0}])

        rows = catalog.execute("SELECT year, quarter FROM catalog_financials "
                               "WHERE ticker='AAA' ORDER BY quarter").fetchall()
        # The annual is the year's final figure; its own nine-month filing ranks
        # below it, shadows nothing, and is the row Q4 is derived FROM.
        assert [(r["year"], r["quarter"]) for r in rows] == [(last_fy, 0), (last_fy, 3)]

    def test_the_replace_keeps_the_quarters_between_its_two_rows(self, catalog) -> None:
        """The daily reconcile must not erase the year's cumulative quarters.

        It pushes exactly two rows — the newest cumulative quarter and the last
        complete fiscal year — and the annual used to clear from the START of its
        year, so every quarter between the two went with it: on 2026-08-17 the
        served store held 19 quarterly periods for 2025 against 301 for 2023, and
        the Финансы tab's quarterly view showed a two-year hole ending at the
        current quarter. The nine-month filing is also Q4's minuend, so the year
        lost its fourth quarter as well.
        """
        last_fy = rc._latest_complete_fiscal_year()
        history = [{"ticker": "AAA", "year": last_fy, "quarter": q, "net_income": float(q)}
                   for q in (1, 2, 3)]
        history.append({"ticker": "AAA", "year": last_fy + 1, "quarter": 1, "net_income": 11.0})
        rc.bulk_upsert_financials(history)

        rc.bulk_replace_financials([
            {"ticker": "AAA", "year": last_fy + 1, "quarter": 2, "net_income": 100.0},
            {"ticker": "AAA", "year": last_fy, "quarter": 0, "net_income": 400.0},
        ])

        rows = catalog.execute(
            "SELECT year, quarter, net_income FROM catalog_financials "
            "WHERE ticker='AAA' ORDER BY year, quarter").fetchall()
        got = {(r["year"], r["quarter"]): r["net_income"] for r in rows}
        assert got[(last_fy, 1)] == 1.0
        assert got[(last_fy, 2)] == 2.0
        assert got[(last_fy, 3)] == 3.0
        assert got[(last_fy, 0)] == 400.0
        assert got[(last_fy + 1, 1)] == 11.0, "the quarter before the pushed one is history"
        assert got[(last_fy + 1, 2)] == 100.0

    def test_the_replace_clears_a_spurious_future_quarter(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        # A row that the входная проверка of a later release would have refused,
        # already sitting in the cache and outranking everything real.
        catalog.execute(
            "INSERT INTO catalog_financials (ticker, form, year, quarter, net_income) "
            "VALUES ('AAA','NSBU',?,4,999.0)", (last_fy + 1,))
        catalog.commit()

        rc.bulk_replace_financials([
            {"ticker": "AAA", "year": last_fy + 1, "quarter": 2, "net_income": 100.0}])

        rows = catalog.execute("SELECT year, quarter FROM catalog_financials "
                               "WHERE ticker='AAA'").fetchall()
        assert [(r["year"], r["quarter"]) for r in rows] == [(last_fy + 1, 2)]

    def test_the_replace_keeps_the_backfilled_history_behind_it(self, catalog) -> None:
        """The daily reconcile must not erase the historical annuals.

        A replace push speaks for the latest quarter and its companion year;
        deleting the whole ticker before the insert erased every backfilled
        historical year each time the reconcile or the filings watch ran — the
        multi-year income statement landed on 2026-08-08 and was gone by the
        next morning's cron, twice, before anyone saw it happen.
        """
        last_fy = rc._latest_complete_fiscal_year()
        history = [{"ticker": "AAA", "year": y, "quarter": 0, "net_income": float(y)}
                   for y in range(last_fy - 5, last_fy + 1)]
        rc.bulk_upsert_financials(history)

        rc.bulk_replace_financials([
            {"ticker": "AAA", "year": last_fy + 1, "quarter": 1, "net_income": 100.0},
            {"ticker": "AAA", "year": last_fy, "quarter": 0, "net_income": 400.0},
        ])

        rows = catalog.execute(
            "SELECT year, quarter, net_income FROM catalog_financials "
            "WHERE ticker='AAA' ORDER BY year, quarter").fetchall()
        got = {(r["year"], r["quarter"]): r["net_income"] for r in rows}
        for y in range(last_fy - 5, last_fy):
            assert got[(y, 0)] == float(y)
        assert got[(last_fy, 0)] == 400.0
        assert got[(last_fy + 1, 1)] == 100.0

    def test_an_annual_row_has_no_companion_of_its_own(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        rc.bulk_replace_financials([{"ticker": "AAA", "year": last_fy, "quarter": 0, "net_income": 400.0}])

        assert rc.get_all_financials()["AAA"]["annual"] is None

    def test_the_period_length_travels_with_the_row(self, catalog) -> None:
        last_fy = rc._latest_complete_fiscal_year()
        rc.bulk_replace_financials([{"ticker": "AAA", "year": last_fy, "quarter": 2, "net_income": 50.0}])

        got = rc.get_all_financials()["AAA"]
        assert got["period_months"] == 6, "a cumulative Q2 is six months of trading"
        assert got["is_ytd"] is True

    @pytest.mark.parametrize(("quarter", "months"), [(0, 12), (1, 3), (2, 6), (3, 9), (4, 12)])
    def test_months_per_period(self, quarter, months) -> None:
        assert rc._period_months(2020, quarter) == months


class TestAnnualizationFactor:
    """A blind x4 is right only for Q1: NSBU quarters are cumulative from Jan 1."""

    @pytest.mark.parametrize(("label", "expected"), [
        ("31.03.2025", 4.0),        # Q1: 3 months  -> x4
        ("30.06.2025", 2.0),        # H1: 6 months  -> x2
        ("30.09.2025", pytest.approx(4 / 3)),  # 9 months -> x1.33
        ("31.12.2025", 1.0),        # full year
    ])
    def test_factors(self, label, expected) -> None:
        assert svc._annualization_factor_from_label(label) == expected

    @pytest.mark.parametrize("label", ["", None, "not a date", "2025-03-31", "31.3.2025"])
    def test_an_undeterminable_period_produces_no_factor(self, label) -> None:
        # Better no annualized figure at all than a guessed one.
        assert svc._annualization_factor_from_label(label) is None


class TestUnitScale:
    """NSBU sums are stored in thousands of UZS; market caps are full UZS.

    Dividing one by the other without the scale understated P/E and P/B ~1000x.
    """

    def test_the_scale_factor_is_a_thousand(self) -> None:
        assert rc.NSBU_THOUSANDS_UZS == 1000.0

    def test_every_money_field_is_scaled(self) -> None:
        # If a money field is added to the row but not to this tuple, it reaches
        # the client in thousands while its neighbours are in full UZS.
        assert set(rc.FIN_MONEY_FIELDS) == {
            "revenue", "gross_profit", "cash",
            "total_liabilities", "net_income", "operating_income",
            "total_assets", "total_equity",
            "noninterest_income",
            # The balance's current section — sums in the same thousands, read so
            # the liquidity, quick and turnover coefficients can be computed for
            # the issuers whose indicator feed publishes none of them.
            "current_assets", "current_liabilities", "inventories",
        }
        # The filed balance rides as a nested dict and is scaled key-by-key at
        # the same boundary (api._market_inputs._scale).
        assert set(rc.BALANCE_MONEY_KEYS) == {
            "equity_start", "equity_end", "assets_start", "assets_end",
            "gross_insurance_reserves", "reinsurer_share_in_reserves",
            "net_insurance_reserves", "other_liabilities",
        }

    def test_absolute_ratio_sums_are_scaled_but_coefficients_are_not(self) -> None:
        assert set(rc.RATIO_MONEY_FIELDS) == {"total_equity", "total_assets"}
        for coefficient in ("roe", "roa", "net_profit_margin", "debt_to_equity"):
            assert coefficient not in rc.RATIO_MONEY_FIELDS
