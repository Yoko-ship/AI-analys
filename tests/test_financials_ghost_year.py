"""A filing counted twice must not become a year of its own.

`catalog_financials` is written by upsert and pruned by nothing, so a report
once catalogued under one year and later under another leaves the first behind.
Measured on the live market: BECM and UZHM publish 2025 and 2024 identical to
the sum on revenue, gross profit, operating income, net profit, cash AND
liabilities — six lines, two "trading years" — and the page then stated
«Рост г/г 0.00%» for a year that was never filed.

The registry is what separates them: one of the pair has an annual filing, the
other does not. Five rows on the market match, and on UQEQ it is the NEWER year
that is unsupported — which is why the rule cannot be "keep the newest".
"""
from __future__ import annotations

import api


def _series(values_by_field: dict[str, dict[str, float]], filed: bool = True) -> dict:
    return {f: {"money": True, "filed": filed, "values": dict(v)}
            for f, v in values_by_field.items()}


LINES = ("net_revenue", "gross_profit", "operating_income", "net_profit")


def _identical(a: str, b: str, extra: dict | None = None) -> dict:
    out = {f: {a: 100.0 + i, b: 100.0 + i} for i, f in enumerate(LINES)}
    out.update(extra or {})
    return _series(out)


class TestTheGhostYearIsTheUnfiledOne:
    def test_the_year_with_no_filing_goes(self):
        series = _identical("2025", "2024")

        assert api.duplicate_filed_years(series, {"2025", "2024"}, {"2025"}) == ["2024"]

    def test_the_newer_year_goes_when_it_is_the_unfiled_one(self):
        """UQEQ: 2026 duplicates 2025 and only 2025 has a filing."""
        series = _identical("2026", "2025")

        assert api.duplicate_filed_years(series, {"2026", "2025"}, {"2025"}) == ["2026"]

    def test_two_filed_years_are_both_kept(self):
        """UZNGP and BNGPP: identical, but nothing here can say which is wrong."""
        series = _identical("2023", "2022")

        assert api.duplicate_filed_years(series, {"2023", "2022"}, {"2023", "2022"}) == []

    def test_two_unfiled_years_are_both_kept(self):
        """No evidence either way — the report catalog is itself incomplete."""
        series = _identical("2023", "2022")

        assert api.duplicate_filed_years(series, {"2023", "2022"}, set()) == []

    def test_years_that_merely_differ_are_untouched(self):
        series = _series({f: {"2025": 1.0 + i, "2024": 2.0 + i} for i, f in enumerate(LINES)})

        assert api.duplicate_filed_years(series, {"2025", "2024"}, {"2025"}) == []

    def test_one_matching_line_is_a_coincidence_not_a_copy(self):
        """Dropping a year on a single equal figure would lose real history."""
        series = _series({"net_revenue": {"2025": 5.0, "2024": 5.0},
                          "net_profit": {"2025": 9.0, "2024": 3.0}})

        assert api.duplicate_filed_years(series, {"2025", "2024"}, {"2025"}) == []

    def test_only_filed_lines_count(self):
        """total_assets comes from the indicator feed and never duplicated."""
        series = _identical("2025", "2024")
        series["total_assets"] = {"money": True, "values": {"2025": 7.0}}

        assert api.duplicate_filed_years(series, {"2025", "2024"}, {"2025"}) == ["2024"]

    def test_a_run_of_three_drops_at_most_the_unfiled_neighbour(self):
        """UZNGP has 2023 == 2022 == 2021; all three are filed, none may go."""
        series = _series({f: {"2023": 10.0, "2022": 10.0, "2021": 10.0} for f in LINES})

        assert api.duplicate_filed_years(
            series, {"2023", "2022", "2021"}, {"2023", "2022", "2021"}) == []
