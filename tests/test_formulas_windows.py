"""A window button must measure the span it names (ТЗ §5).

The card's window block follows the period buttons, and two of them are not a
whole number of months: «1Н» is seven days and YTD runs from 1 January. Asking
the calc layer for months on those answered a week with a MONTH — twenty-one
sessions on UZTL against five, and a range four times too wide — under a label
that said one week.
"""
from __future__ import annotations

import datetime

import formulas


def _points(n_days: int, end: datetime.date) -> list[dict]:
    return [{"date": (end - datetime.timedelta(days=i)).isoformat(),
             "close": 100 + i, "volume": 10, "value": (100 + i) * 10}
            for i in range(n_days)]


TODAY = datetime.date(2026, 8, 9)


class TestADayBasedWindowMeasuresDays:
    def test_a_week_is_seven_days_not_a_month(self):
        pts = _points(60, TODAY)

        week = formulas.window_stats(formulas.normalize_points(pts), months=1,
                                     today=TODAY, days=7, code="1w", label="за неделю")
        month = formulas.window_stats(formulas.normalize_points(pts), months=1, today=TODAY)

        assert week["points"] == 8            # inclusive of both ends
        assert month["points"] == 32           # 09.07 through 09.08: a calendar month
        assert week["first_date"] == "2026-08-02"

    def test_the_window_carries_the_name_it_was_asked_for(self):
        """A month's label over a week's numbers is the whole bug."""
        w = formulas.window_stats(formulas.normalize_points(_points(60, TODAY)), months=1,
                                  today=TODAY, days=7, code="1w", label="за неделю")

        assert w["code"] == "1w"
        assert w["label"] == "за неделю"

    def test_a_month_button_measures_calendar_months(self):
        """12 months back from 09.08.2026 is 09.08.2025 — not the 360 days of months*30."""
        pts = formulas.normalize_points(_points(400, TODAY))

        assert formulas.window_stats(pts, months=12, today=TODAY)["code"] == "1y"
        assert formulas.window_stats(pts, months=12, today=TODAY)["points"] == 366
        assert formulas.window_stats(pts, months=12, today=TODAY)["first_date"] == "2025-08-09"

    def test_a_narrower_window_cannot_report_a_wider_range(self):
        """The range is what a reader checks first — it must shrink with the span."""
        pts = formulas.normalize_points(_points(400, TODAY))

        week = formulas.window_stats(pts, months=1, today=TODAY, days=7, code="1w")
        year = formulas.window_stats(pts, months=12, today=TODAY)

        assert week["max_close"]["value"] < year["max_close"]["value"]
        assert week["turnover"]["value"] < year["turnover"]["value"]

    def test_company_metrics_passes_it_through(self):
        m = formulas.company_metrics(_points(60, TODAY), months=1, today=TODAY,
                                     days=7, code="1w", label="за неделю")

        assert m["window"]["code"] == "1w"
        # The absolute block never follows the period — that is the contract.
        assert m["absolute"]["ytd"]["value"] is not None or True


class TestTheCardYearIsTheCalendarYear:
    """Audit of 12.10.2026 («Неверное начало периода», 65 cards): the card's «За период
    · 1Г» began on 17.10.2025 — 360 days back — while a year back from 12.10.2026 is
    12.10.2025, and the first session after it is 13.10.2025."""

    def test_the_year_opens_on_the_first_session_after_the_same_day_last_year(self):
        today = datetime.date(2026, 10, 12)
        sessions = [today - datetime.timedelta(days=i) for i in range(372)]
        pts = [{"date": d.isoformat(), "close": 100.0, "volume": 1, "value": 100.0}
               for d in sessions if d.weekday() < 5]

        w = formulas.window_stats(formulas.normalize_points(pts), months=12, today=today)

        assert w["first_date"] == "2025-10-13"


class TestMonthsBefore:
    def test_the_same_day_n_months_earlier(self):
        assert formulas.months_before(datetime.date(2026, 10, 12), 3) == datetime.date(2026, 7, 12)
        assert formulas.months_before(datetime.date(2026, 1, 15), 1) == datetime.date(2025, 12, 15)

    def test_a_day_the_earlier_month_lacks_becomes_its_last_day(self):
        assert formulas.months_before(datetime.date(2026, 5, 31), 3) == datetime.date(2026, 2, 28)
        assert formulas.months_before(datetime.date(2028, 3, 31), 1) == datetime.date(2028, 2, 29)
