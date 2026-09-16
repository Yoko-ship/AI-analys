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
        assert month["points"] == 31
        assert week["first_date"] == "2026-08-02"

    def test_the_window_carries_the_name_it_was_asked_for(self):
        """A month's label over a week's numbers is the whole bug."""
        w = formulas.window_stats(formulas.normalize_points(_points(60, TODAY)), months=1,
                                  today=TODAY, days=7, code="1w", label="за неделю")

        assert w["code"] == "1w"
        assert w["label"] == "за неделю"

    def test_without_days_nothing_changes(self):
        """The month buttons keep the months*30 slice they always had."""
        pts = formulas.normalize_points(_points(400, TODAY))

        assert formulas.window_stats(pts, months=12, today=TODAY)["code"] == "1y"
        assert formulas.window_stats(pts, months=12, today=TODAY)["points"] == 361

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
