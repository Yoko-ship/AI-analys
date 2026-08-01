"""Price formulas: the five defects of ТЗ v1.2 §2.1, pinned.

Each class here is one claim from the audit, reproduced on a synthetic series
where the right answer is known analytically:

  * VWAP was sum(close*volume)/sum(volume) instead of turnover/volume — off by
    a median 0.69 % over 77 live securities, +33.0 % on UZHM.
  * volatility took the last 21 POINTS whatever calendar they covered (230 days
    for TRSBP, on 7 observations) and was never annualised.
  * YTD/YOY/QOQ were computed on the loaded slice, so the period button moved
    them on 76 of 77 securities and flipped the sign on 44.
  * moving averages ran over display buckets: "MA20" spanned 134 calendar days
    in candle mode against 25 in line mode, on 72 of 72 securities.
  * the OHLC check was series-wide (one bad point disabled candles for the
    whole instrument) and illiquidity was not reflected at all.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

import formulas


def series(rows):
    """[(date, open, high, low, close, volume, turnover)] -> raw point dicts."""
    return [
        {"date": d, "open": o, "high": h, "low": lo, "close": c,
         "trading_volume": v, "trading_value": t}
        for d, o, h, lo, c, v, t in rows
    ]


def daily(start: str, closes, volume=10.0, turnover=None, flat=False):
    """A point per calendar day from `start`, one close each."""
    d0 = date.fromisoformat(start)
    out = []
    for i, c in enumerate(closes):
        day = (d0 + timedelta(days=i)).isoformat()
        hi, lo = (c, c) if flat else (c * 1.02, c * 0.98)
        out.append((day, c, hi, lo, c, volume,
                    (c * volume if turnover is None else turnover)))
    return series(out)


# ---------------------------------------------------------------------------
# VWAP
# ---------------------------------------------------------------------------

class TestVwap:
    def test_is_turnover_over_volume_not_mean_close(self):
        # The gap only opens when the day's trades happen away from its close,
        # which is exactly what a thin order book does. Day 1: 10 shares change
        # hands for 500 sums (mean 50) but the last trade prints at 100.
        pts = formulas.normalize_points(series([
            ("2026-01-05", 40, 100, 40, 100, 10, 500),
            ("2026-01-06", 100, 100, 60, 60, 10, 700),
        ]))
        got = formulas.vwap(pts)
        assert got["status"] == "ok"
        assert got["value"] == pytest.approx(1200 / 20)          # turnover/volume = 60
        wrong = (100 * 10 + 60 * 10) / 20                        # the old formula = 80
        assert got["value"] != pytest.approx(wrong)

    def test_null_with_a_reason_when_turnover_is_missing(self):
        rows = series([("2026-01-05", 10, 10, 10, 10, 5, 50)])
        rows.append({"date": "2026-01-06", "open": 11, "high": 11, "low": 11,
                     "close": 11, "trading_volume": 5, "trading_value": None})
        got = formulas.vwap(formulas.normalize_points(rows))
        assert got["value"] is None
        assert got["status"] == "turnover_missing"
        assert got["missing_points"] == 1

    def test_no_volume_is_its_own_status(self):
        got = formulas.vwap(formulas.normalize_points(
            series([("2026-01-05", 10, 10, 10, 10, 0, 0)])))
        assert got["value"] is None and got["status"] == "no_volume"

    def test_mean_close_is_not_vwap(self):
        pts = formulas.normalize_points(series([
            ("2026-01-05", 100, 100, 100, 100, 1, 100),
            ("2026-01-06", 10, 10, 10, 10, 10, 100),
        ]))
        w = formulas.window_stats(pts, 12, today=date(2026, 1, 6))
        assert w["mean_close"]["value"] == pytest.approx(55.0)
        assert w["vwap"]["value"] == pytest.approx(200 / 11)


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

class TestVolatility:
    def test_window_is_calendar_days_not_point_count(self):
        # 40 daily points: only the last 30 calendar days may be used.
        pts = formulas.normalize_points(daily("2026-01-01", [100 + i for i in range(40)]))
        got = formulas.volatility(pts)
        assert got["status"] == "ok"
        assert got["window_days"] == 30
        assert got["observations"] == 30

    def test_null_when_the_window_holds_too_few_observations(self):
        # Seven trades spread over eight months — the old code averaged them
        # anyway and called the result a 20-day volatility.
        rows = [(f"2025-{m:02d}-01", 100, 102, 98, 100, 5, 500) for m in range(1, 8)]
        pts = formulas.normalize_points(series(rows))
        got = formulas.volatility(pts)
        assert got["value"] is None
        assert got["status"] == "insufficient_data"
        assert got["observations"] < 10

    def test_is_annualised(self):
        # A constant proportional step gives a known daily sigma of 0; perturb
        # one step so sigma > 0 and check the sqrt(252) scale is applied.
        closes = [100.0] * 20 + [110.0] + [100.0] * 9
        pts = formulas.normalize_points(daily("2026-01-01", closes))
        got = formulas.volatility(pts)
        assert got["status"] == "ok" and got["annualized"] is True
        # Recompute the same statistic by hand, unannualised, and compare scale.
        obs = [p for p in pts if p["d"] >= pts[-1]["d"] - timedelta(days=30)]
        rets = [math.log(b["close"] / a["close"]) / math.sqrt((b["d"] - a["d"]).days)
                for a, b in zip(obs, obs[1:])]
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        assert got["value"] == pytest.approx(sd * math.sqrt(252) * 100)

    def test_gaps_are_normalised_by_interval_length(self):
        # The same price move over one day and over four is not the same
        # volatility; dividing by sqrt(gap) is what makes them comparable.
        tight = formulas.normalize_points(series([
            ("2026-03-02", 100, 100, 100, 100, 5, 500),
            ("2026-03-03", 110, 110, 110, 110, 5, 550),
        ] + [(f"2026-03-{d:02d}", 110, 110, 110, 110, 5, 550) for d in range(4, 16)]))
        wide = formulas.normalize_points(series([
            ("2026-03-02", 100, 100, 100, 100, 5, 500),
            ("2026-03-06", 110, 110, 110, 110, 5, 550),
        ] + [(f"2026-03-{d:02d}", 110, 110, 110, 110, 5, 550) for d in range(7, 19)]))
        assert formulas.volatility(tight)["value"] > formulas.volatility(wide)["value"]


# ---------------------------------------------------------------------------
# Returns — the main invariant of the whole ТЗ
# ---------------------------------------------------------------------------

class TestReturns:
    def _two_years(self):
        # A point every third day across 2025 and 2026 so every horizon has a base.
        d0 = date(2025, 1, 2)
        rows = []
        price = 100.0
        for i in range(0, 500, 3):
            day = d0 + timedelta(days=i)
            price *= 1.004
            rows.append((day.isoformat(), price, price * 1.01, price * 0.99,
                         price, 10, price * 10))
        return formulas.normalize_points(series(rows))

    def test_absolute_block_is_identical_under_every_period(self):
        """ТЗ §3: 'Кнопка периода не имеет права менять абсолютную метрику.'"""
        pts = self._two_years()
        blocks = [formulas.absolute_metrics(pts) for _ in (1, 3, 6, 12, 36, 60)]
        for other in blocks[1:]:
            assert other == blocks[0]

    def test_company_metrics_absolute_block_survives_the_period_button(self):
        raw = series([(p["date"], p["open"], p["high"], p["low"], p["close"],
                       p["volume"], p["turnover"]) for p in self._two_years()])
        today = date.fromisoformat(raw[-1]["date"])
        first = formulas.company_metrics(raw, months=1, today=today)
        for months in (3, 6, 12, 36, 60):
            later = formulas.company_metrics(raw, months=months, today=today)
            assert later["absolute"] == first["absolute"]
            assert later["quality"] == first["quality"]
        # ...while the window block is expected to move.
        assert (formulas.company_metrics(raw, months=1, today=today)["window"]["points"]
                < formulas.company_metrics(raw, months=60, today=today)["window"]["points"])

    def test_ytd_uses_last_years_close(self):
        pts = formulas.normalize_points(series([
            ("2025-12-30", 100, 100, 100, 100, 5, 500),
            ("2026-01-15", 120, 120, 120, 120, 5, 600),
            ("2026-02-15", 150, 150, 150, 150, 5, 750),
        ]))
        got = formulas.returns(pts)["ytd"]
        assert got["status"] == "ok"
        assert got["value"] == pytest.approx(50.0)          # 150 vs last year's 100
        assert got["base_date"] == "2025-12-30"

    def test_ytd_falls_back_to_the_first_trade_of_the_year_and_says_so(self):
        pts = formulas.normalize_points(series([
            ("2026-02-02", 100, 100, 100, 100, 5, 500),
            ("2026-03-02", 130, 130, 130, 130, 5, 650),
        ]))
        got = formulas.returns(pts)["ytd"]
        assert got["value"] == pytest.approx(30.0)
        assert got["base_is_fallback"] is True

    def test_a_stale_base_is_null_with_a_reason(self):
        # Last trade in 2026-06; the nearest point to the YOY target of
        # 2025-06 is a year and a half away, so YOY has no honest base.
        pts = formulas.normalize_points(series([
            ("2024-01-10", 100, 100, 100, 100, 5, 500),
            ("2026-06-10", 300, 300, 300, 300, 5, 1500),
        ]))
        got = formulas.returns(pts)["yoy"]
        assert got["value"] is None
        assert got["status"] == "base_too_stale"

    def test_qoq_and_yoy_survive_a_short_window(self):
        """The data exists in the history; a one-month view must not hide it."""
        pts = self._two_years()
        got = formulas.returns(pts)
        assert got["qoq"]["value"] is not None
        assert got["yoy"]["value"] is not None


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

class TestMovingAverage:
    def test_window_is_calendar_days_on_the_daily_series(self):
        pts = formulas.normalize_points(daily("2026-01-01", [100.0] * 60))
        ma = formulas.moving_average(pts, 28)
        assert ma[-1] == pytest.approx(100.0)
        # The last MA point may only see the trailing 28 calendar days: with a
        # 30-day run of 200s behind it, none of the earlier 100s may leak in.
        pts2 = formulas.normalize_points(daily("2026-01-01", [100.0] * 40 + [200.0] * 30))
        ma2 = formulas.moving_average(pts2, 28)
        assert ma2[-1] == pytest.approx(200.0)
        # ...and a 20-day run of 200s must NOT read as 200: 8 of the 28 days
        # are still 100s. This is the bucket bug in miniature.
        pts3 = formulas.normalize_points(daily("2026-01-01", [100.0] * 40 + [200.0] * 20))
        assert formulas.moving_average(pts3, 28)[-1] == pytest.approx((8 * 100 + 20 * 200) / 28)

    def test_hidden_below_three_observations(self):
        pts = formulas.normalize_points(series([
            ("2026-01-01", 100, 100, 100, 100, 5, 500),
            ("2026-01-02", 101, 101, 101, 101, 5, 505),
        ]))
        assert formulas.moving_average(pts, 28) == [None, None]

    def test_ma20_spans_28_calendar_days(self):
        """ТЗ §11.5 invariant: MA20 covers 28 calendar days ±20 %."""
        assert formulas.thresholds()["moving_average"]["ma20_calendar_days"] == 28
        pts = formulas.normalize_points(daily("2026-01-01", [float(100 + i) for i in range(60)]))
        mas = formulas.moving_averages(pts)
        assert mas["ma20"]["window_days"] == 28
        assert mas["ma50"]["window_days"] == 70
        assert len(mas["ma20"]["values"]) == len(pts)


# ---------------------------------------------------------------------------
# OHLC validity and data quality
# ---------------------------------------------------------------------------

class TestQuality:
    def test_ohlc_check_is_per_point(self):
        good = {"open": 10, "high": 12, "low": 9, "close": 11}
        bad = {"open": 10, "high": 8, "low": 9, "close": 11}     # high below close
        missing = {"open": 10, "high": None, "low": 9, "close": 11}
        assert formulas.ohlc_valid(good) is True
        assert formulas.ohlc_valid(bad) is False
        assert formulas.ohlc_valid(missing) is False

    def test_one_bad_point_does_not_disable_candles_for_the_series(self):
        rows = [(f"2026-04-{d:02d}", 100, 102, 98, 100, 5, 500) for d in range(1, 29)]
        rows[10] = ("2026-04-11", 100, 0, 98, 100, 5, 500)       # one malformed record
        q = formulas.data_quality(formulas.normalize_points(series(rows)))
        assert q["candles_enabled"] is True
        assert q["ohlc_points"] == len(rows) - 1

    def test_flat_series_is_classified_not_drawn_as_candles(self):
        pts = formulas.normalize_points(daily("2026-04-01", [100.0] * 28, flat=True))
        q = formulas.data_quality(pts)
        assert q["flat_share"] == pytest.approx(1.0)
        assert q["data_tier"] == "illiquid"
        assert q["candles_enabled"] is False
        assert q["reason"]

    def test_thin_coverage_is_sparse(self):
        # One trade a week for a quarter: real prices, but not a daily series.
        rows = [((date(2026, 1, 5) + timedelta(days=7 * i)).isoformat(),
                 100, 102, 98, 100 + i, 5, 500) for i in range(13)]
        q = formulas.data_quality(formulas.normalize_points(series(rows)))
        assert q["coverage"] < 0.6
        assert q["data_tier"] in ("sparse", "illiquid")
        assert q["candles_enabled"] is False

    def test_liquid_series_keeps_its_candles(self):
        rows = [((date(2026, 1, 5) + timedelta(days=i)).isoformat(),
                 100, 103, 97, 100 + (i % 5), 5, 500)
                for i in range(120) if (date(2026, 1, 5) + timedelta(days=i)).weekday() < 5]
        q = formulas.data_quality(formulas.normalize_points(series(rows)))
        assert q["data_tier"] == "full"
        assert q["candles_enabled"] is True
        assert q["reason"] is None

    def test_no_data_below_two_points(self):
        q = formulas.data_quality(formulas.normalize_points(
            series([("2026-04-01", 100, 102, 98, 100, 5, 500)])))
        assert q["data_tier"] == "no_data"
        assert q["candles_enabled"] is False


# ---------------------------------------------------------------------------
# Edge cases the old code returned numbers for
# ---------------------------------------------------------------------------

class TestEdges:
    def test_empty_series(self):
        m = formulas.company_metrics([], months=12)
        assert m["window"]["vwap"]["value"] is None
        assert m["absolute"]["ytd"]["value"] is None
        assert m["quality"]["data_tier"] == "no_data"

    def test_single_point(self):
        m = formulas.company_metrics(series([("2026-04-01", 10, 10, 10, 10, 1, 10)]), months=12)
        assert m["absolute"]["day"]["value"] is None
        assert m["absolute"]["volatility"]["value"] is None

    def test_zero_and_negative_closes_are_dropped(self):
        pts = formulas.normalize_points(series([
            ("2026-04-01", 0, 0, 0, 0, 5, 0),
            ("2026-04-02", -5, -5, -5, -5, 5, 0),
            ("2026-04-03", 10, 10, 10, 10, 5, 50),
        ]))
        assert [p["date"] for p in pts] == ["2026-04-03"]

    def test_duplicate_dates_collapse(self):
        pts = formulas.normalize_points(series([
            ("2026-04-01", 10, 10, 10, 10, 5, 50),
            ("2026-04-01", 11, 11, 11, 11, 6, 66),
        ]))
        assert len(pts) == 1 and pts[0]["close"] == 11

    def test_sub_unit_prices_are_not_rounded_to_a_zero_change(self):
        """KASU trades at 0.01 sum — rounding inside the calculation erases it."""
        pts = formulas.normalize_points(series([
            ("2026-04-01", 0.01, 0.01, 0.01, 0.01, 100, 1.0),
            ("2026-04-02", 0.0125, 0.0125, 0.0125, 0.0125, 100, 1.25),
        ]))
        got = formulas.day_change(pts)
        assert got["value"] == pytest.approx(25.0)

    def test_thresholds_come_from_config_not_literals(self):
        cfg = formulas.thresholds()
        assert cfg["quality"]["flat_share_max"] == 0.5
        assert cfg["volatility"]["min_observations"] == 10
        assert cfg["returns"]["base_staleness_max_days"] == 30
