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
        }

    def test_absolute_ratio_sums_are_scaled_but_coefficients_are_not(self) -> None:
        assert set(rc.RATIO_MONEY_FIELDS) == {"total_equity", "total_assets"}
        for coefficient in ("roe", "roa", "net_profit_margin", "debt_to_equity"):
            assert coefficient not in rc.RATIO_MONEY_FIELDS
