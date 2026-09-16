from forecast_engine import build_forecast
from backtest import walk_forward_annual


def test_forecast_uses_only_comparable_filed_annuals_and_withholds_probabilities():
    result = build_forecast("TEST", "NSBU", {
        "2022": {"revenue": 100, "net_income": 10},
        "2023": {"revenue": 120, "net_income": 12},
        "2024": {"revenue": 108, "net_income": 9},
    }, shares_outstanding=1_000, current_price=100, peer_pe=[4, 8, 12])

    assert result["status"] == "AVAILABLE"
    assert [s["scenario"] for s in result["scenarios"]] == ["downside", "base", "upside"]
    assert all(s["probability"] is None for s in result["scenarios"])
    assert result["quality"]["publication"] == "BLOCKED"
    assert result["fair_value"]["status"] == "AVAILABLE"


def test_forecast_refuses_short_history():
    result = build_forecast("TEST", "MSFO", {"2024": {"revenue": 100, "net_income": 10}})
    assert result["status"] == "NO_DATA"


def test_walk_forward_uses_only_prior_years():
    result = walk_forward_annual({str(year): {"revenue": 100 + (year - 2020) * 10, "net_income": 10}
                                  for year in range(2020, 2026)})
    assert result["status"] == "AVAILABLE"
    assert result["trials"][0]["year"] == 2023
