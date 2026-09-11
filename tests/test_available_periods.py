"""The analysis-period selector must retain OpenInfo's full quarterly history."""
from __future__ import annotations

import openinfo_collector as collector


def test_available_periods_merges_quarters_older_than_structured_window(monkeypatch):
    """The structured endpoint has only ten records; unified retains 2016."""
    def fake_get(_session, path, params=None):
        if path == "/reports/accounting-report/7/":
            if params["report_type"] == "annual":
                return [{"reporting_year": 2016}, {"reporting_year": 2025}]
            return [
                {"period": "Q2 2023"},
                {"period": "Q3 2023"},
            ]
        assert path == "/reports/unified-financial-reports/"
        assert params["organization"] == "7"
        assert params["page"] == 1
        return {
            "results": [
                # Structured data wins where the same period is present.
                {"report_type": "NSBU", "pub_date": "2023-07-20T10:00:00",
                 "properties": {"report_type": "quarter"}},
                {"report_type": "NSBU", "pub_date": "2016-04-29T10:00:00",
                 "properties": {"report_type": "quarter"}},
                {"report_type": "NSBU", "pub_date": "2016-07-15T10:00:00",
                 "properties": {"report_type": "quarter"}},
                {"report_type": "NSBU", "pub_date": "2016-10-24T10:00:00",
                 "properties": {"report_type": "quarter"}},
                # A January filing is the prior year's Q3, not a fictional Q4.
                {"report_type": "NSBU", "pub_date": "2017-01-17T10:00:00",
                 "properties": {"report_type": "quarter"}},
                {"report_type": "MSFO", "pub_date": "2016-04-29T10:00:00",
                 "properties": {"report_type": "quarter"}},
            ],
            "next": None,
        }

    monkeypatch.setattr(collector, "_json_get", fake_get)

    periods = collector.fetch_available_periods("7", session=object())

    assert periods["annual_years"] == [2025, 2016]
    assert periods["quarterly"] == [
        {"year": 2023, "quarter": 3},
        {"year": 2023, "quarter": 2},
        {"year": 2016, "quarter": 3},
        {"year": 2016, "quarter": 2},
        {"year": 2016, "quarter": 1},
    ]
    assert periods["latest_quarterly"] == {"year": 2023, "quarter": 3}
