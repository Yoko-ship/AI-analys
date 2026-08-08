"""/api/company/{ticker}/financials — the annual series behind the Финансы tab.

The one thing that matters here is the UNIT. The fact store keeps absolute sums
in thousands of UZS; the market cap beside them on the page is full UZS. Serving
the store raw puts a 10.5-trillion revenue on screen as ten billion — the same
~1000x class of defect that `FIN_MONEY_FIELDS` and `RATIO_MONEY_FIELDS` already
exist to prevent, so the money-field list is pinned rather than trusted.
"""
from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import reports_catalog as rc

api = importlib.import_module("api")


def _fact(field, period, value, unit="UZS", source="openinfo_financial_indicators"):
    return {"dataset": "financial_indicators", "field": field, "period": period,
            "value_num": value, "value_text": None, "unit": unit, "source": source}


FACTS = [
    _fact("net_revenue", "2025", 10_512_797_471.0),
    _fact("net_revenue", "2024", 7_849_956_534.0),
    _fact("net_profit", "2025", 590_906_080.0),
    _fact("total_assets", "2025", 13_530_348_888.0),
    _fact("total_equity", "2025", 3_030_753_112.0),
    _fact("total_liabilities", "2025", 10_499_595_776.0),
    # coefficients — must NOT be scaled
    _fact("roe", "2025", 19.5, unit="%"),
    _fact("net_profit_margin", "2025", 5.62, unit="x"),
    _fact("current_ratio", "2025", 0.65, unit=None),
    # a quarter must not become a column beside the years
    _fact("net_revenue", "2025Q1", 2_000_000.0),
    # a text-only fact has nothing to plot
    {"dataset": "financial_indicators", "field": "auditor", "period": "2025",
     "value_num": None, "value_text": "PwC", "unit": None, "source": "x"},
]


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 666} if t == "UZTL" else {})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: FACTS)
    return TestClient(api.app)


def test_money_fields_are_scaled_to_full_uzs(client):
    s = client.get("/api/company/UZTL/financials").json()["series"]
    # 10 512 797 471 thousand = 10.5 trillion UZS, which is what the board and
    # the multiples on the same page are denominated in.
    assert s["net_revenue"]["values"]["2025"] == 10_512_797_471_000.0
    assert s["net_profit"]["values"]["2025"] == 590_906_080_000.0
    assert s["total_assets"]["values"]["2025"] == 13_530_348_888_000.0
    assert s["total_equity"]["values"]["2025"] == 3_030_753_112_000.0
    assert s["total_liabilities"]["values"]["2025"] == 10_499_595_776_000.0


def test_coefficients_are_left_alone(client):
    s = client.get("/api/company/UZTL/financials").json()["series"]
    assert s["roe"]["values"]["2025"] == 19.5
    assert s["net_profit_margin"]["values"]["2025"] == 5.62
    assert s["current_ratio"]["values"]["2025"] == 0.65


def test_only_the_verified_identities_carry_a_unit(monkeypatch):
    """The feed publishes ratios without saying what they are computed on, and it
    is not one basis. Measured over every issuer-year the store holds:
    roe = profit/equity (225 of 225), roa = profit/assets (674 of 674),
    debt_ratio = liabilities/assets (401 of 401) — those get a %.
    debt_to_equity matched that identity 0 times of 225, and
    total_asset_turnover IS revenue/assets, a coefficient — both stay bare."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("roe", "2025", 19.5, unit="%"),
        _fact("roa", "2025", 4.37, unit="%"),
        _fact("debt_ratio", "2025", 77.6, unit=None),
        _fact("debt_to_equity", "2025", 249.63, unit="x"),
        _fact("total_asset_turnover", "2025", 0.78, unit=None),
        _fact("current_ratio", "2025", 0.65, unit=None),
    ])
    s = TestClient(api.app).get("/api/company/X/financials").json()["series"]
    assert all(s[f]["unit"] == "%" for f in ("roe", "roa", "debt_ratio"))
    assert all(s[f]["unit"] is None for f in
               ("debt_to_equity", "total_asset_turnover", "current_ratio"))
    # and none of them is rescaled
    assert s["debt_ratio"]["values"]["2025"] == 77.6
    assert s["total_asset_turnover"]["values"]["2025"] == 0.78


def test_net_margin_is_derived_not_republished(monkeypatch):
    """The fed net_profit_margin matched profit/revenue in only 396 of 655
    issuer-years — AGBA reads 0.05 where the sums give 24.08 %. So it is not
    published; the margin is computed from the two sums in this same payload."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_revenue", "2025", 4_265_600_000.0),
        _fact("net_profit", "2025", 1_880_100_000.0),
        _fact("net_profit_margin", "2025", 0.11, unit="x"),
        _fact("total_assets", "2025", 9_000_000.0),
    ])
    s = TestClient(api.app).get("/api/company/X/financials").json()["series"]
    assert s["net_margin"]["unit"] == "%"
    assert s["net_margin"]["derived"] is True
    assert abs(s["net_margin"]["values"]["2025"] - 44.0729) < 0.01
    # the untrusted one carries no unit, so nothing can print it as a percentage
    assert s["net_profit_margin"]["unit"] is None


def test_no_margin_on_a_zero_revenue_base(monkeypatch):
    """BRBN files no revenue line. A margin on a zero base is a division, not a
    fact about the issuer."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_revenue", "2024", 0.0),
        _fact("net_profit", "2024", -2_231_102_237.0),
        _fact("total_assets", "2024", 32_133_397_827.0),
    ])
    s = TestClient(api.app).get("/api/company/X/financials").json()["series"]
    assert "net_margin" not in s


def test_the_money_field_list_is_the_contract():
    """A sum added to the series but not to this tuple reaches the client in
    thousands while its neighbours are in full UZS."""
    assert set(rc.FACT_MONEY_FIELDS) == {
        "net_revenue", "net_profit", "total_assets", "total_liabilities", "total_equity",
    }
    for coefficient in ("roe", "roa", "net_margin", "current_ratio", "debt_to_equity"):
        assert coefficient not in rc.FACT_MONEY_FIELDS


def test_only_annual_columns(client):
    body = client.get("/api/company/UZTL/financials").json()
    assert body["periods"] == ["2025", "2024"]
    assert "2025Q1" not in body["series"]["net_revenue"]["values"]


def test_periods_are_newest_first(client):
    assert client.get("/api/company/UZTL/financials").json()["periods"] == ["2025", "2024"]


def test_a_text_fact_is_not_a_row(client):
    assert "auditor" not in client.get("/api/company/UZTL/financials").json()["series"]


def test_an_issuer_we_cannot_resolve_is_empty_not_an_error(client):
    body = client.get("/api/company/NOPE/financials").json()
    assert body["ok"] is True and body["series"] == {} and body["periods"] == []


def test_a_year_filed_entirely_as_zero_is_not_a_column(monkeypatch):
    """openinfo publishes KSCM 2021 as revenue 0, profit 0 AND total assets 0,
    with no margins. A balance sheet cannot total zero, so that is an empty
    filing — publishing it drew a cement plant collapsing to nothing with a
    -100 % growth row underneath."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_revenue", "2021", 0.0), _fact("net_profit", "2021", 0.0),
        _fact("total_assets", "2021", 0.0),
        _fact("net_revenue", "2020", 551_396_888.0),
        _fact("total_assets", "2020", 470_730_359.0),
    ])
    body = TestClient(api.app).get("/api/company/KSCM/financials").json()
    assert body["periods"] == ["2020"]
    assert "2021" not in body["series"]["net_revenue"]["values"]


def test_a_zero_balance_sheet_is_dropped_even_with_a_stray_figure(monkeypatch):
    """SQBN 2024 defeated the first rule. openinfo files it with assets, equity,
    liabilities and revenue all zero — and a net profit of 13 000 sums, which
    was enough to keep the column and draw a bank collapsing to nothing and back.
    A going concern cannot have no balance sheet, so zero total assets is the
    test, not "every money field is zero"."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("total_assets", "2024", 0.0), _fact("total_equity", "2024", 0.0),
        _fact("total_liabilities", "2024", 0.0), _fact("net_revenue", "2024", 0.0),
        _fact("net_profit", "2024", 13.0),
        _fact("total_assets", "2023", 74_630_000_000.0),
        _fact("net_revenue", "2023", 2_698_000_000.0),
    ])
    body = TestClient(api.app).get("/api/company/SQBN/financials").json()
    assert body["periods"] == ["2023"]


def test_a_zero_income_line_on_a_real_balance_sheet_is_kept(monkeypatch):
    """BRBN and UZNGP file on forms with no revenue line, and UZNF is a fund
    that genuinely earns nothing while holding 30 T of assets. Those zeros are
    what the source says — only a missing STATEMENT is dropped."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_revenue", "2024", 0.0),
        _fact("net_profit", "2024", -2_231_102_237.0),
        _fact("total_assets", "2024", 32_133_397_827.0),
    ])
    body = TestClient(api.app).get("/api/company/BRBN/financials").json()
    assert body["periods"] == ["2024"]
    assert body["series"]["net_revenue"]["values"]["2024"] == 0.0


def test_a_single_zero_is_kept(monkeypatch):
    """UZNF is a fund: it genuinely earns no revenue while holding assets, and
    that zero is a fact about the issuer rather than a missing filing."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_revenue", "2025", 0.0),
        _fact("total_assets", "2025", 4_000_000.0),
    ])
    body = TestClient(api.app).get("/api/company/UZNF/financials").json()
    assert body["periods"] == ["2025"]
    assert body["series"]["net_revenue"]["values"]["2025"] == 0.0


def test_the_newest_write_wins_a_repeated_period(monkeypatch):
    """openinfo publishes an indicator and the NSBU pass derives it; the derived
    one is computed from the filing this platform parsed."""
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 666})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: [
        _fact("net_profit", "2025", 1.0),
        _fact("net_profit", "2025", 2.0, source="nsbu_derived_indicators"),
    ])
    s = TestClient(api.app).get("/api/company/UZTL/financials").json()["series"]
    assert s["net_profit"]["values"]["2025"] == 2000.0
