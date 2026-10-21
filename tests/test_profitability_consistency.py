"""ROE/ROA must describe the same filing on the board and in its analysis."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest

import fundamentals
import public_contract
from catalogue.parsing import compute_filing_values
from financial_analysis.sector_calculations import financial_ratios
from financial_analysis.sector_report import make_report
from sector_report_service import map_special_lines


TODAY = date(2026, 10, 21)
FILINGS = json.loads((Path(__file__).parent / "fixtures/sector_v22_filings.json").read_text(encoding="utf8"))


def board(fin, indicators=None):
    result = fundamentals.issuer_multiples([], fin, indicators or {}, today=TODAY)
    return public_contract.multiplier_contract(result, [], fin, indicators or {})


def statement(profit=50, opening=80, closing=120, quarter=2):
    return {"year": 2026, "quarter": quarter, "net_income": profit,
            "balance": {"equity_start": opening, "equity_end": closing,
                        "assets_start": 800, "assets_end": 1200}}


@pytest.mark.parametrize("ticker", ["HMKB", "UZAS", "UZMK"])
def test_real_workbook_has_identical_returns_through_both_public_paths(ticker):
    filing = FILINGS[ticker]
    workbook = deepcopy(filing["workbook"])
    fin = {**compute_filing_values(workbook["income"], workbook["balance"])["source_values"],
           "year": 2026, "quarter": 2, "org_type": filing["organization_type"]}
    snapshot = {"organization_type": filing["organization_type"], "standard": "nsbu", "scope": "separate",
                "period": "2026Q2", "period_basis": "cumulative_ytd", "source": filing["source"],
                "current_values": {}, "previous_values": {}, "opening_values": {}, "quality": {"data_quality": []}}
    if filing["organization_type"] != "non_financial":
        map_special_lines(snapshot, workbook, filing["organization_type"])
    report = make_report(snapshot, filing["issuer"], today=TODAY, workbook=workbook)
    assert report["status"] == "available"
    analysis = {r["metric_code"]: r for r in report["ratios"]}
    market = board(fin)
    # Independently calculated from the recorded source rows. HMKB's undated
    # bank comparison column is not proof of a year-opening balance.
    expected = {"HMKB": (25.27696399833148, 4.695468463768888),
                "UZAS": (0.398936377693087, 0.16907820997416934),
                "UZMK": (10.160896136682771, 4.443895811997218)}[ticker]
    for code, value in zip(("roe", "roa"), expected):
        assert market[code]["value"] == pytest.approx(value, rel=1e-10)
        assert analysis[code]["value"] == pytest.approx(value, rel=1e-10)
        assert market[code]["financial_period"] == "2026Q2"


def test_ttm_and_prior_annual_do_not_change_selected_period_returns():
    fin = statement()
    fin["annual"] = {"year": 2025, "net_income": 300}
    fin["prior"] = {"year": 2025, "quarter": 2, "net_income": 200}
    result = board(fin)
    assert result["roe"]["value"] == 100  # 50 * 2 / mean(80,120) * 100
    assert result["roa"]["value"] == 10
    assert result["roe"]["financial_period"] == "2026Q2"
    assert result["roe"]["annualised"] is True
    assert result["roe"]["inputs"]["annualised_net_income"] == 100
    assert "ttm_net_income" not in result["roe"]["formula"]
    # Other earnings-based metrics retain their TTM inputs.
    assert result["pe"]["inputs"]["ttm_net_income"] == 150


@pytest.mark.parametrize("profit,opening,closing,expected", [
    (0, 80, 120, 0), (-50, 80, 120, -100), (50, None, 100, 100),
    (50, 0, 100, 100), (50, -20, 120, 200), (None, 80, 120, None),
    (50, 100, 0, None), (50, 120, -20, None), (50, -200, 120, None),
    (50, 80, None, None), (float("nan"), 80, 120, None), (True, 80, 120, None),
])
def test_missing_zero_losses_and_invalid_denominators_agree(profit, opening, closing, expected):
    fin = statement(profit, opening, closing)
    market = board(fin)["roe"]
    analysis = next(r for r in financial_ratios(
        {"net_income": profit, "total_equity": closing}, {}, {"total_equity": opening},
        "bank", "nsbu", "2026Q2") if r["metric"] == "roe")
    if expected is None:
        assert market["value"] is None
        assert market["display_value"] is None
        assert analysis["value"] is None
    else:
        assert market["value"] == pytest.approx(expected)
        assert analysis["value"] == pytest.approx(expected)


@pytest.mark.parametrize("quarter,expected", [(1, 200), (2, 100), (3, 200/3), (4, 50), (0, 50)])
def test_cumulative_periods_are_not_treated_as_standalone_quarters(quarter, expected):
    assert board(statement(quarter=quarter))["roe"]["value"] == pytest.approx(expected)


def test_missing_profit_cannot_borrow_old_profit_or_published_returns():
    fin = statement(profit=None)
    fin["annual"] = {"year": 2025, "net_income": 300}
    result = board(fin, {"roe": 25, "roa": 5, "period": "2025A"})
    assert result["roe"]["value"] is None
    assert result["roa"]["value"] is None
    assert result["roe"]["display_value"] is None


def test_balance_indicator_must_match_the_profit_period_per_field():
    fin = {"year": 2026, "quarter": 2, "net_income": 50}
    result = board(fin, {"period": "2026Q2", "total_equity": 100, "total_assets": 1000,
                         "periods": {"total_equity": "2025A", "total_assets": "2026Q2"}})
    assert result["roe"]["value"] is None
    assert result["roa"]["value"] == 10
    assert result["roe"]["display_value"] is None


def test_borrowed_income_is_not_current_period_profit():
    fin = statement()
    fin["field_periods"] = {"net_income": "2025A"}
    assert board(fin)["roe"]["value"] is None


def test_bank_return_uses_year_opening_not_undated_comparison_column():
    fin = {**statement(), "org_type": "bank", "annual": {
        "year": 2025, "net_income": 300,
        "balance": {"equity_end": 60, "assets_end": 600}}}
    assert board(fin)["roe"]["value"] == pytest.approx(100 / 90 * 100)
    assert board(fin)["roa"]["value"] == pytest.approx(100 / 900 * 100)


def test_no_false_pe_roe_identity_alarm_when_profit_periods_differ():
    fin = statement()
    fin.update(revenue=1000, annual={"year": 2025, "net_income": 300, "revenue": 2000},
               prior={"year": 2025, "quarter": 2, "net_income": 200, "revenue": 500})
    result = fundamentals.issuer_multiples([{"ticker": "A", "market_cap": 1000}], fin, {}, today=TODAY)
    assert result["roe"]["value"] == 100
    assert result["checks"]["results"]["v11_pe_roe_pb"] is None
    assert not result["checks"]["flags"]


def test_returns_have_distinct_render_keys_and_unambiguous_method_names():
    from financial_analysis.metric_names import named
    ratios = financial_ratios({"net_income": 50, "total_assets": 1000, "total_equity": 100},
                              {}, {}, "bank", "nsbu", "2026Q2")
    assert len({r["method_id"] for r in ratios}) == len(ratios)
    assert "closing" in named("P1")["name_en"].lower()
    assert "pre-tax" in named("P4")["name_en"].lower()


def test_bank_analysis_rejects_a_previous_quarter_as_ytd_opening():
    filing = FILINGS["HMKB"]
    snapshot = {"organization_type": "bank", "standard": "nsbu", "period": "2026Q2",
                "source": filing["source"], "current_values": {}, "previous_values": {}, "opening_values": {}}
    map_special_lines(snapshot, filing["workbook"], "bank")
    snapshot["comparison_sources"]["opening_date"] = "2026-03-31"
    snapshot["return_opening_values"] = {"total_assets": 30000000000, "total_equity": 6000000000}
    report = make_report(snapshot, filing["issuer"], today=TODAY, workbook=filing["workbook"])
    ratios = {r["metric_code"]: r for r in report["ratios"]}
    assert ratios["roe"]["value"] == pytest.approx(969962031 * 200 / ((6000000000 + 7674671935) / 2))


def test_a_borrowed_annual_balance_cannot_be_used_as_the_year_opening():
    fin = {**statement(), "org_type": "bank", "annual": {
        "year": 2025, "net_income": 300, "field_periods": {"total_equity": "2024A"},
        "balance": {"equity_end": 60, "assets_end": 600}}}
    assert board(fin)["roe"]["value"] == pytest.approx(100 / 120 * 100)


def test_return_scale_does_not_change_between_thousands_and_full_uzs():
    fin = statement()
    scaled = deepcopy(fin)
    scaled["net_income"] *= 1000
    scaled["balance"] = {key: value * 1000 for key, value in fin["balance"].items()}
    for code in ("roe", "roa"):
        assert board(fin)[code]["value"] == board(scaled)[code]["value"]
