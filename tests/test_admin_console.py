"""The console that makes a wrong multiple debuggable.

Two screens, and their whole value is that they show what was previously
invisible: which stored record reached the calculation, and what the
calculation did with it once it had. So the tests here are about honesty of
reporting, not about arithmetic — the arithmetic is ``fundamentals``' and is
tested there.

The important one is :class:`TestNoSecondImplementation`. A panel that
recomputes the numbers itself would eventually disagree with the market screen,
and then it reports its own bug while the real one goes on being published.
"""
from __future__ import annotations

import admin_data
import fundamentals


def row(ticker="UZTL", year=2026, quarter=2, **kw):
    base = {"ticker": ticker, "form": "NSBU", "year": year, "quarter": quarter,
            "revenue": 1_000.0, "net_income": 100.0,
            "total_assets": 1_000.0, "total_equity": 400.0,
            "total_liabilities": 600.0}
    return {**base, **kw}


LAST_FY = 2025


class TestWhichRecordsReachedTheCalculation:
    def test_three_states_and_superseded_is_not_a_defect(self):
        """A record that a newer period outranks is a perfectly good record.
        Reporting it as a problem would bury the ones that are."""
        rows = [row(year=2026, quarter=2), row(year=2025, quarter=0)]
        out = admin_data.report_intake(rows, LAST_FY, {"UZTL": (2026, 2)})
        by_period = {r["period"]: r for r in out["items"]}
        assert by_period["2026Q2"]["state"] == "used"
        assert by_period["2025A"]["state"] == "superseded"
        assert by_period["2025A"]["flags"] == []
        assert out["used"] == 1 and out["superseded"] == 1 and out["ineligible"] == 0

    def test_a_record_the_read_path_drops_in_sql_is_visible_here(self):
        """The point of the screen. A quarter of 7 outranked every real period
        and was thrown away without a word; «не допущена» is that word."""
        out = admin_data.report_intake([row(quarter=7)], LAST_FY, {})
        one = out["items"][0]
        assert one["state"] == "ineligible"
        assert "bad_quarter" in one["flags"]

    def test_a_premature_annual_is_the_source_s_placeholder_not_a_year(self):
        out = admin_data.report_intake([row(year=2026, quarter=0)], LAST_FY, {})
        assert out["items"][0]["state"] == "ineligible"
        assert "premature_annual" in out["items"][0]["flags"]

    def test_a_period_stamped_beyond_next_year_cannot_be_a_filing_that_exists(self):
        out = admin_data.report_intake([row(year=2030, quarter=1)], LAST_FY, {})
        assert "future_year" in out["items"][0]["flags"]

    def test_two_records_claiming_one_period_are_both_named(self):
        out = admin_data.report_intake([row(), row(net_income=999.0)], LAST_FY, {"UZTL": (2026, 2)})
        assert all("duplicate_period" in r["flags"] for r in out["items"])

    def test_a_balance_that_does_not_close_is_flagged_not_silently_used(self):
        out = admin_data.report_intake(
            [row(total_assets=1_000.0, total_equity=400.0, total_liabilities=100.0)],
            LAST_FY, {})
        assert "balance_gap" in out["items"][0]["flags"]

    def test_a_row_of_nothing_says_so(self):
        out = admin_data.report_intake(
            [row(revenue=None, net_income=None, total_assets=None,
                 total_equity=None, total_liabilities=None)], LAST_FY, {})
        assert "zero_row" in out["items"][0]["flags"]

    def test_the_ineligible_rows_come_first(self):
        rows = [row(year=2025, quarter=0), row(quarter=7), row(year=2026, quarter=2)]
        out = admin_data.report_intake(rows, LAST_FY, {"UZTL": (2026, 2)})
        assert out["items"][0]["state"] == "ineligible"


class TestTheLedgerShowsTheArithmetic:
    FIN = {"year": 2026, "quarter": 2, "net_income": 896.0, "revenue": 5_000.0,
           "annual": {"year": 2025, "quarter": 0, "net_income": 590.0, "revenue": 9_000.0},
           "prior": {"year": 2025, "quarter": 2, "net_income": 10.0, "revenue": 4_000.0}}

    def test_every_component_carries_its_period_and_its_sign(self):
        ledger = admin_data.ttm_ledger(self.FIN)
        assert ledger["method"] == "ttm"
        signs = {c["label"]: c["sign"] for c in ledger["components"]}
        assert signs["Годовой отчёт"] == "+"
        assert signs["Текущий период"] == "+"
        assert signs["Сопоставимый период прошлого года"] == "−"
        assert ledger["result"]["net_income"] == 590.0 + 896.0 - 10.0

    def test_a_component_that_did_not_enter_is_struck_through_not_hidden(self):
        """«Почему это число — один интервал?» is the question the screen is
        for; hiding the component that failed to join makes it unanswerable."""
        fin = {"year": 2026, "quarter": 2, "net_income": 896.0,
               "annual": {"year": 2025, "quarter": 0, "net_income": 590.0}}
        ledger = admin_data.ttm_ledger(fin)
        assert ledger["method"] == "annual"
        dropped = [c["label"] for c in ledger["components"] if c["dropped"]]
        assert "Текущий период" in dropped
        # And the component itself is still on screen, with its own value.
        assert any(c["label"] == "Текущий период" and c["net_income"] == 896.0
                   for c in ledger["components"])

    def test_an_annualised_base_is_named_an_estimate(self):
        ledger = admin_data.ttm_ledger({"year": 2026, "quarter": 2, "net_income": 100.0})
        assert ledger["method"] == "annualized"
        assert ledger["estimate"] is True
        assert "ОЦЕНКА" in ledger["method_note"].upper()

    def test_no_statement_at_all_is_a_reason_not_an_empty_worksheet(self):
        ledger = admin_data.ttm_ledger(None)
        assert ledger["available"] is False and ledger["reason"]


class TestNoSecondImplementation:
    """The panel reads the published path. If it recomputed the numbers itself
    the two would drift, and the console would be reporting its own bug while
    the real one went on being published."""

    CLASSES = [{"ticker": "UZTL", "market_cap": 1_000_000.0, "shares_outstanding": 1_000.0},
               {"ticker": "UZTLP", "is_preferred": True, "market_cap": 100_000.0,
                "shares_outstanding": 100.0}]
    FIN = {"year": 2026, "quarter": 2, "net_income": 896.0, "revenue": 5_000.0,
           "total_equity": 4_000.0, "total_assets": 10_000.0,
           "annual": {"year": 2025, "quarter": 0, "net_income": 590.0, "revenue": 9_000.0},
           "prior": {"year": 2025, "quarter": 2, "net_income": 10.0, "revenue": 4_000.0}}

    def test_every_multiple_on_the_screen_is_the_published_one(self):
        published = fundamentals.issuer_multiples(self.CLASSES, self.FIN, {})
        ledger = admin_data.issuer_ledger("UZTL", self.CLASSES, self.FIN, {})
        for name in ("pe", "pb", "ps", "roe", "roa", "net_margin"):
            assert ledger["inputs"][name]["value"] == (published.get(name) or {}).get("value")

    def test_the_numerator_shown_is_the_one_the_multiple_divided(self):
        ledger = admin_data.issuer_ledger("UZTL", self.CLASSES, self.FIN, {})
        ttm = ledger["ttm"]["result"]["net_income"]
        assert ledger["inputs"]["pe"]["denominator"] == ttm
        assert ledger["inputs"]["roe"]["numerator"] == ttm

    def test_a_class_that_never_traded_is_named_rather_than_left_blank(self):
        classes = [{"ticker": "UZTL", "market_cap": 1_000_000.0},
                   {"ticker": "UZTLP", "is_preferred": True, "market_cap": None}]
        ledger = admin_data.issuer_ledger("UZTL", classes, self.FIN, {})
        counted = {c["ticker"]: c["counted"] for c in ledger["classes"]}
        assert counted == {"UZTL": True, "UZTLP": False}
        assert ledger["market_cap"]["counted"] == 1 and ledger["market_cap"]["total"] == 2

    def test_the_denominator_rule_is_named_on_screen_not_buried_in_code(self):
        """An unfilled opening balance arrives as a literal zero, and averaging
        it printed ROE at exactly 2,00× for three issuers. The rule that
        prevents it is stated where an operator reads the number."""
        ledger = admin_data.issuer_ledger("UZTL", self.CLASSES, self.FIN, {})
        assert ledger["balance"]["rule"]


class TestTheRuleBookDrawsTheLine:
    def test_the_panel_holds_parameters_and_the_code_holds_the_computation(self):
        book = admin_data.rule_book()
        assert "формулы" in book["boundary"]["code"]
        assert "пороги" in book["boundary"]["panel"]
        # And the reason is stated, because the boundary is a decision and not
        # an accident of what was easy to build.
        assert "без теста" in book["boundary"]["why"]

    def test_every_threshold_it_lists_has_a_value(self):
        book = admin_data.rule_book()
        assert book["thresholds"]
        assert all(r["value"] is not None for r in book["thresholds"])


class TestTheVerdictIsPinnedToTheReadPath:
    """``period_status`` re-expresses in Python what ``get_all_financials``
    filters in SQL. Two expressions of one rule drift, so this test holds them
    together: whatever the panel calls ineligible must be a row the read path
    genuinely never serves."""

    PERIODS = [
        (2025, 0),   # last complete year — eligible
        (2026, 2),   # this year's interim — eligible
        (2026, 0),   # annual for a year that has not closed — the placeholder
        (2025, 7),   # a corrupt source quarter
        (2031, 1),   # stamped beyond next year
    ]

    def test_every_period_the_panel_rejects_is_one_the_read_path_never_serves(
            self, tmp_path, monkeypatch):
        import reports_catalog as rc

        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "cat.db"))
        last_fy = rc._latest_complete_fiscal_year()
        rows = [{"ticker": f"T{i}", "year": y, "quarter": q,
                 "revenue": 100.0, "net_income": 10.0}
                for i, (y, q) in enumerate(self.PERIODS)]
        rc.bulk_upsert_financials(rows)
        served = rc.get_all_financials()

        for i, (year, quarter) in enumerate(self.PERIODS):
            ticker = f"T{i}"
            rejected = bool(admin_data.period_status(year, quarter, last_fy))
            assert rejected == (ticker not in served), (
                f"{ticker} {year}Q{quarter}: panel rejected={rejected}, "
                f"read path served={ticker in served}")


class TestWhoWasDueToFile:
    """Being late is a fact about the ISSUER, and the screen states it as one.
    The distinction that matters is between «has not filed yet» and «stopped
    filing»: adding them together hides the second behind the first."""

    from datetime import date as _date
    TODAY = _date(2026, 8, 20)

    def test_the_expected_period_is_the_last_quarter_whose_window_has_opened(self):
        from datetime import date

        # 20 August: Q2 closed on 30 June, disclosure opened on 25 July.
        assert admin_data.expected_period(date(2026, 8, 20)) == (2026, 2)
        # 10 July: Q2 closed but the window has not opened yet, so Q1 is still
        # the newest period anyone was due to file.
        assert admin_data.expected_period(date(2026, 7, 10)) == (2026, 1)

    def test_an_issuer_that_filed_the_expected_period_is_simply_done(self):
        cal = admin_data.disclosure_calendar({"HMKB": (2026, 2)}, self.TODAY)
        one = cal["items"][0]
        assert one["filed"] is True and one["state"] == "сдан"
        assert one["quarters_behind"] == 0

    def test_inside_an_open_window_a_missing_report_is_expected_not_late(self):
        cal = admin_data.disclosure_calendar({"QZSM": (2026, 1)}, self.TODAY)
        assert cal["items"][0]["state"] == "ожидается"
        assert cal["overdue_days"] == 0

    def test_after_the_window_closes_the_same_gap_becomes_a_delay(self):
        from datetime import date

        cal = admin_data.disclosure_calendar({"QZSM": (2026, 1)}, date(2026, 9, 20))
        assert cal["items"][0]["state"] == "просрочен"
        assert cal["items"][0]["overdue_days"] == 12

    def test_a_year_of_silence_is_its_own_state(self):
        """UZMT has filed nothing since 2019. Calling that «late» puts it beside
        an issuer that is three weeks behind, and the two are not alike."""
        cal = admin_data.disclosure_calendar({"UZMT": (2019, 0)}, self.TODAY)
        one = cal["items"][0]
        assert one["state"] == "молчит"
        assert one["latest"] == "2019A"
        assert one["quarters_behind"] > 20

    def test_the_quietest_issuers_come_first(self):
        cal = admin_data.disclosure_calendar(
            {"HMKB": (2026, 2), "QZSM": (2026, 1), "UZMT": (2019, 0)}, self.TODAY)
        assert [r["ticker"] for r in cal["items"]] == ["UZMT", "QZSM", "HMKB"]
