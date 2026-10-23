"""Acceptance cases for the PDF terminal, using the public financial contract."""
import pytest

from server.terminal import analytics


def series(values, **extra):
    return {"standard": "NSBU", "currency": "UZS", "scope": "separate",
            "periods": sorted({p for v in values.values() for p in v}, reverse=True),
            "series": {k: {"values": v, "money": True} for k, v in values.items()}, **extra}


def test_cagr_requires_exact_positive_endpoints_and_complete_deflators():
    # SQBN acceptance: +12.1% annually, approximately +2% after inflation.
    values = {"2020": 100, "2025": 100 * 1.121 ** 5}
    assert analytics.growth(values, "2025", 5)["nominal"] == pytest.approx(12.1)
    result = analytics.growth(values, "2025", 5, inflation={str(y): 10 for y in range(2021, 2026)},
                              fx={"2020": 10000, "2025": 12500})
    assert result["real"] == pytest.approx(1.9090909)
    assert result["usd"] == pytest.approx(((1.121 ** 5 / 1.25) ** .2 - 1) * 100)
    assert analytics.growth(values, "2025", 3)["nominal"] is None
    assert analytics.growth({"2020": -100, "2025": 200}, "2025", 5)["reason"] == "NON_POSITIVE_ENDPOINT"
    assert analytics.growth(values, "2025", 5, inflation={"2025": 10})["real"] is None


def test_ratios_use_the_selected_annual_and_never_bank_debt_equity():
    data = series({"net_profit": {"2025": 20}, "total_assets": {"2025": 200},
                   "total_equity": {"2025": 100}, "total_liabilities": {"2025": 100}})
    company = analytics.snapshot(data, kind="non_financial", market_cap=250)
    assert company["roe"] == 20 and company["roa"] == 10
    assert company["de"] == 1 and company["pe"] == 12.5 and company["pb"] == 2.5
    assert analytics.snapshot(data, kind="bank")["de"] is None
    assert analytics.snapshot(data, year="2024")["roe"] is None
    data["series"]["net_profit"]["values"]["2025"] = -2
    assert analytics.snapshot(data, market_cap=250)["pe"] is None


def test_reconciliation_keeps_standards_scopes_and_gaps_explicit():
    nsbu = series({"net_profit": {"2024": 10, "2025": 20}})
    ifrs = series({"net_profit": {"2025": 25}}, standard="MSFO", scope="consolidated")
    result = analytics.reconcile(nsbu, ifrs)
    row = next(r for r in result["rows"] if r["period"] == "2025")
    assert row["nsbu"] == 20 and row["ifrs"] == 25 and row["difference"] == 5
    assert result["same_scope"] is False
    assert next(r for r in result["rows"] if r["period"] == "2024")["difference"] is None


def test_quarterly_growth_ltm_and_seasonality_do_not_bridge_missing_quarters():
    data = series({"net_profit": {"2024Q1": 10, "2024Q2": 20, "2024Q3": 30, "2024Q4": 40,
                                   "2025Q1": 15, "2025Q3": 35}})
    rows = {r["period"]: r for r in analytics.quarters(data)["rows"]}
    assert rows["2024Q4"]["ltm"] == 100
    assert rows["2024Q1"]["seasonality"] == 10
    assert rows["2025Q1"]["yoy"] == 50
    assert rows["2025Q1"]["ltm"] == 105
    assert rows["2025Q3"]["ltm"] is None
    assert rows["2025Q1"]["seasonality"] is None
    assert analytics.quarters({**data, "period_basis": "cumulative_ytd"})["rows"] == []


def test_peers_require_same_type_standard_scope_and_period():
    base = {"ticker": "AGBA", "kind": "bank", "standard": "NSBU", "scope": "separate", "period": "2025"}
    candidates = [dict(base, ticker="SQBN"), dict(base, ticker="QZSM", kind="non_financial"),
                  dict(base, ticker="HMKB", standard="MSFO"), dict(base, ticker="IPTB", period="2024"),
                  dict(base, ticker="ALKB", scope="consolidated")]
    assert [r["ticker"] for r in analytics.peers(base, candidates)] == ["SQBN"]


def test_returns_share_the_existing_average_balance_rule():
    data = series({"net_profit": {"2025": 20}, "total_equity": {"2024": 60, "2025": 100}})
    assert analytics.snapshot(data)["roe"] == 25


def test_annual_bank_screener_nim_uses_shared_average_asset_method():
    data={'periods':['2024','2025'],'series':{'interest_income':{'values':{'2025':100}},'interest_expense':{'values':{'2025':40}},'total_assets':{'values':{'2024':800,'2025':1000}}}}
    row=analytics.snapshot(data,kind='bank')
    assert row['nim']==pytest.approx(60/900*100)
    assert row['cost_of_risk'] is None
    assert analytics.snapshot(data,kind='industry')['nim'] is None
