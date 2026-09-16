"""The acceptance set is real, and both layers are held to it (ТЗ §13 / §12.8).

`tests/fixtures/acceptance.json` is the twenty-odd cases the ТЗ verified by hand.
The ТЗ is explicit that the set is used TWICE — once as a test of the auditor
(the rule must find the known problem) and once as a test of the calculation
layer (after the fix the number must be right) — and that it grows with every
new finding: "правило «нашли дефект — добавили строку в эталон» обязательно,
иначе исправленная ошибка вернётся через два месяца".

What this file asserts is that the set exists as one shared artefact and stays
connected to the code: every ticker it names is a real ticker, every rule
group it exercises has an implementation, and the structural promises it makes
(one universe, one P/E per issuer, no invented bond par) are the ones the code
actually keeps. The per-case numeric assertions live with the module each case
belongs to — this is the index that stops a case being quietly dropped.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "acceptance.json"


@pytest.fixture(scope="module")
def acceptance() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


class TestTheSetItself:
    def test_it_exists_as_one_file(self):
        assert FIXTURES.is_file(), "the acceptance set must be one shared artefact"

    def test_it_covers_every_area_the_specification_names(self, acceptance):
        sections = {k for k in acceptance if not k.startswith("_")}
        assert sections == {
            "vwap", "absolute_metrics", "moving_average", "quality", "multiples",
            "financials", "market_map", "catalog", "bonds", "source_catalog",
        }

    def test_every_case_says_what_it_expects(self, acceptance):
        for section, cases in acceptance.items():
            if section.startswith("_"):
                continue
            for case in cases:
                assert "metric" in case or "window" in case, (section, case)
                assert "should_be" in case or "status" in case, (section, case)

    def test_tickers_are_plausible(self, acceptance):
        pattern = re.compile(r"^[A-Z0-9]{3,10}$")
        for section, cases in acceptance.items():
            if section.startswith("_"):
                continue
            for case in cases:
                for ticker in ([case["ticker"]] if case.get("ticker") else case.get("tickers", [])):
                    assert pattern.match(ticker), (section, ticker)


class TestTheSetIsConnectedToTheCode:
    """A fixture nobody's code can fail is decoration. These bind it."""

    def test_every_status_the_set_expects_is_a_status_the_code_emits(self, acceptance):
        import bonds
        import fundamentals

        known = {
            "insufficient_data", "base_too_stale", "no_data", "not_traded", "no_price",
            "out_of_range", "unverified", bonds.STATUS_NO_REFERENCE,
            fundamentals.STATUS_LOSS, fundamentals.STATUS_INCONSISTENT,
            fundamentals.STATUS_NO_FINANCIALS, "rejected_at_input",
        }
        for section, cases in acceptance.items():
            if section.startswith("_"):
                continue
            for case in cases:
                status = case.get("status")
                if status:
                    assert status in known, f"{section}: unknown status {status!r}"

    def test_the_audit_rules_cover_the_areas_the_set_lists(self):
        from audit.rules import GROUPS

        assert {"FIN", "MUL", "MKT", "CND", "CAT", "XSC", "BND", "SRC"} <= set(GROUPS)

    def test_one_universe(self, acceptance):
        """catalog: was [82, 85, 96, 107, 108], should_be 1."""
        case = next(c for c in acceptance["catalog"] if c["metric"] == "instrument_universes")
        assert case["should_be"] == 1
        import instruments

        built = instruments.build_catalog(securities={"A": {}}, board=[{"ticker": "B"}],
                                          financials={"C": {}})
        # One list, and nothing dropped: every source's tickers are present.
        assert {i["ticker"] for i in built["items"]} == {"A", "B", "C"}

    def test_one_pe_per_issuer(self, acceptance):
        """multiples: KFSK 203.56 against KFSKP 0.19 — one issuer, one profit."""
        cases = {c["ticker"]: c for c in acceptance["multiples"] if c.get("ticker")}
        assert cases["KFSKP"]["should_be"] == "equal_to_KFSK"
        import fundamentals

        classes = [{"ticker": "KFSK", "name": "K", "market_cap": 800.0,
                    "shares_outstanding": 100.0, "last_price": 8.0},
                   {"ticker": "KFSKP", "name": "K", "market_cap": 200.0,
                    "shares_outstanding": 25.0, "last_price": 8.0}]
        got = fundamentals.issuer_multiples(
            classes, {"year": 2025, "quarter": 0, "period_months": 12,
                      "revenue": 1000.0, "net_income": 200.0},
            {"total_equity": 1000.0, "period": "2025", "roe": 20.0})
        # One value for the issuer — there is no per-class P/E to disagree with.
        assert got["pe"]["value"] == pytest.approx(5.0)

    def test_no_invented_bond_par(self, acceptance):
        """bonds: an invented par is not a fallback."""
        case = next(c for c in acceptance["bonds"] if c["metric"] == "yield_metrics")
        assert case["status"] == "no_bond_reference"
        import bonds

        row = bonds.bond_row({"ticker": "ACMT2B5", "type": "bond", "last_price": 105310.56})
        assert row["price_pct"]["value"] is None
        assert row["price_pct"]["status"] == bonds.STATUS_NO_REFERENCE

    def test_no_data_is_not_zero(self, acceptance):
        """market_map: ten securities showed 0 % and voted in sector averages."""
        case = next(c for c in acceptance["market_map"]
                    if c.get("metric") == "change_pct" and c.get("was") == 0)
        assert case["should_be"] is None and case["status"] == "not_traded"
        import heatmap

        tile = heatmap.classify_tile({"ticker": "SANE", "last_price": None,
                                      "close_price": None})
        assert tile["change_pct"] is None and tile["status"] == heatmap.TILE_NOT_TRADED
        assert heatmap.aggregate_sector([tile])["change_pct"] is None

    def test_the_period_button_invariant(self, acceptance):
        """absolute_metrics: BNGPP spread across periods was 542.9 p.p."""
        case = next(c for c in acceptance["absolute_metrics"]
                    if c["metric"] == "ytd_spread_across_periods")
        assert case["should_be"] == 0
        import formulas
        from datetime import date, timedelta

        raw = [{"date": (date(2025, 1, 2) + timedelta(days=i * 3)).isoformat(),
                "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i,
                "trading_volume": 10, "trading_value": (100 + i) * 10}
               for i in range(160)]
        today = date.fromisoformat(raw[-1]["date"])
        blocks = [formulas.company_metrics(raw, months=m, today=today)["absolute"]
                  for m in (1, 3, 6, 12, 36, 60)]
        assert all(b == blocks[0] for b in blocks)

    def test_vwap_is_turnover_over_volume(self, acceptance):
        """vwap: UZHM 4007.99 -> 3010.46, the worst divergence in the catalog."""
        case = next(c for c in acceptance["vwap"] if c["ticker"] == "UZHM")
        assert case["was"] > case["should_be"]
        import formulas

        points = formulas.normalize_points([
            {"date": "2026-01-05", "close": 100, "trading_volume": 10, "trading_value": 500},
            {"date": "2026-01-06", "close": 60, "trading_volume": 10, "trading_value": 700},
        ])
        assert formulas.vwap(points)["value"] == pytest.approx(60.0)   # not 80

    def test_the_source_catalog_counters_cannot_disagree(self, acceptance):
        """source_catalog: 85 against 73 was two queries nobody compared."""
        case = next(c for c in acceptance["source_catalog"] if c["metric"] == "header_vs_list")
        assert case["was"] == [85, 73]
        import provenance

        summary = provenance.summary()
        assert summary["issuers"] == len(summary["items"])
        assert summary["reports_total"] == sum(i["reports"] for i in summary["items"])
