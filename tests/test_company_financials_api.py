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


def test_every_margin_leaves_in_percent(monkeypatch):
    """The feed does not publish margins on one scale and says nothing about it:
    gross_profit_margin arrives as a SHARE (0.36) and net_profit_margin as a
    PERCENT (5.62) for the same issuer and year. Measured against the sums —
    gross_profit/revenue was 0.3599 where the feed published 0.36, and
    net_income/revenue 0.0562 where it published 5.62 — so shares are converted
    once, here, and 0.36 never prints beside 5.62 under one heading again.

    monkeypatch, not a bare assignment: patching `api.get_facts` for the rest of
    the session made test_bonds_provenance fail forty files later.
    """
    facts = [_fact("gross_profit_margin", "2025", 0.36, unit=None),
             _fact("ebit_margin", "2025", 0.14, unit=None),
             _fact("net_profit_margin", "2025", 5.62, unit="x"),
             _fact("roe", "2025", 19.5, unit="%"),
             _fact("current_ratio", "2025", 0.65, unit=None)]
    monkeypatch.setattr(api, "get_company_index", lambda t: {"org_id": 1})
    monkeypatch.setattr(api, "get_facts", lambda org, dataset=None: facts)
    s = TestClient(api.app).get("/api/company/X/financials").json()["series"]
    assert s["gross_profit_margin"]["values"]["2025"] == 36.0
    assert s["ebit_margin"]["values"]["2025"] == 14.0
    assert s["net_profit_margin"]["values"]["2025"] == 5.62
    assert all(s[f]["unit"] == "%" for f in
               ("gross_profit_margin", "ebit_margin", "net_profit_margin", "roe"))
    # A plain coefficient is not a percentage and must not grow a % sign.
    assert s["current_ratio"]["unit"] is None
    assert s["current_ratio"]["values"]["2025"] == 0.65


def test_the_scale_lists_are_the_contract():
    assert set(rc.FACT_SHARE_FIELDS) == {"gross_profit_margin", "ebit_margin"}
    assert set(rc.FACT_PERCENT_FIELDS) == {"net_profit_margin", "roe", "roa", "debt_ratio"}
    # Verified as a bare coefficient, not a percentage: revenue/assets was
    # 0.5895 where the feed published 0.59.
    assert "total_asset_turnover" not in rc.FACT_PERCENT_FIELDS
    assert "total_asset_turnover" not in rc.FACT_SHARE_FIELDS
    # A field cannot be both, and money is never a percentage.
    assert not set(rc.FACT_SHARE_FIELDS) & set(rc.FACT_PERCENT_FIELDS)
    assert not set(rc.FACT_MONEY_FIELDS) & (set(rc.FACT_SHARE_FIELDS) | set(rc.FACT_PERCENT_FIELDS))


def test_the_money_field_list_is_the_contract():
    """A sum added to the series but not to this tuple reaches the client in
    thousands while its neighbours are in full UZS."""
    assert set(rc.FACT_MONEY_FIELDS) == {
        "net_revenue", "net_profit", "total_assets", "total_liabilities", "total_equity",
    }
    for coefficient in ("roe", "roa", "net_profit_margin", "current_ratio", "debt_to_equity"):
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
