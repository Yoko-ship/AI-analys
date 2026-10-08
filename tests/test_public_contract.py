"""Public financial contract regression tests for the 2026-09-01 specification."""
from __future__ import annotations

import server.market.valuations as subject_server_market_valuations

import server.market.valuations as subject_server_market_valuations

from datetime import date, datetime, timedelta, timezone

import fundamentals
import public_contract as contract
import pytest


TODAY = date(2026, 9, 1)


def _statement(net_income=200.0):
    return {
        "year": 2025, "quarter": 0, "period_months": 12,
        "revenue": 1_000.0, "gross_profit": 400.0,
        "net_income": net_income, "total_liabilities": 500.0,
        "balance": {
            "equity_start": 900.0, "equity_end": 1_000.0,
            "assets_start": 1_900.0, "assets_end": 2_000.0,
        },
    }


def _ratio():
    return {"total_equity": 1_000.0, "total_assets": 2_000.0,
            "roe": None, "period": "2025"}


def _class(ticker="ACME", *, traded="2026-08-31", price=10.0,
           shares=100.0, cap=1_000.0, **metadata):
    raw = {
        "ticker": ticker, "last_trade_date": traded, "last_price": price,
        "shares_outstanding": shares, "market_cap": cap,
        "source_url": "https://uzse.example/quote",
        **metadata,
    }
    market_input = contract.market_class_input(
        raw, shares_outstanding=shares, reference_date=TODAY)
    return {**raw, "market_cap": market_input["market_cap"],
            "market_input": market_input, "type": "stock"}


def test_current_quote_and_shares_produce_a_class_cap():
    got = _class()["market_input"]
    assert got["calculation_status"] == contract.CALCULATED
    assert got["market_cap"] == 1_000.0
    assert got["price_age_days"] == 1


def test_stale_quote_is_not_allowed_into_issuer_capitalisation():
    got = _class(traded="2026-05-01")["market_input"]
    assert got["calculation_status"] == contract.STALE_PRICE
    assert got["market_cap"] is None
    assert got["reported_market_cap"] == 1_000.0


def test_quote_is_current_through_the_configured_ninetieth_day():
    traded = TODAY - timedelta(days=90)
    got = _class(traded=traded.isoformat())["market_input"]
    assert got["calculation_status"] == contract.CALCULATED


def test_missing_share_count_is_incomplete_not_zero():
    got = _class(shares=None)["market_input"]
    assert got["calculation_status"] == contract.INCOMPLETE_MARKET_CAP
    assert got["market_cap"] is None


def test_openinfo_reported_cap_is_usable_without_a_trade_quote():
    got = contract.market_class_input({
        "ticker": "ACME",
        "last_price": None,
        "last_trade_date": None,
        "shares_outstanding": 100.0,
        "market_cap": 1_250.0,
        "market_cap_source": "openinfo_listing",
        "market_cap_source_url": "https://openinfo.uz/",
        "market_cap_as_of": "2026-09-01 05:00:00",
    }, reference_date=TODAY)

    assert got["calculation_status"] == contract.CALCULATED
    assert got["market_cap"] == 1_250.0
    assert got["market_cap_method"] == "source_reported"
    assert got["market_cap_source"] == "openinfo_listing"


def test_a_listing_cap_on_a_stale_trade_is_refused_like_any_stale_price():
    """DRBK: shares x its 2019 trade at par stayed on the board as a cap and
    printed P/E 0,71×. The board may show it; the multiples may not use it."""
    got = contract.market_class_input({
        "ticker": "ACME",
        "last_price": 10.0,
        "last_trade_date": "2025-02-26",
        "shares_outstanding": 25.0,
        "market_cap": 250.0,
        "market_cap_source": "openinfo_listing",
    }, reference_date=TODAY)

    assert got["calculation_status"] == contract.STALE_PRICE
    assert got["market_cap"] is None and got["reported_market_cap"] == 250.0
    assert got["included_in_issuer_cap"] is True


def test_a_stale_preferred_listing_cap_leaves_the_issuer_cap():
    """IPKYP: last trade 2025-02-26. Like any inactive preferred class it is out
    of the issuer cap rather than blocking the traded ordinary."""
    got = contract.market_class_input({
        "ticker": "ACMEP",
        "is_preferred": True,
        "last_price": 10.0,
        "last_trade_date": "2025-02-26",
        "shares_outstanding": 25.0,
        "market_cap": 250.0,
        "market_cap_source": "openinfo_listing",
    }, reference_date=TODAY)

    assert got["included_in_issuer_cap"] is False
    assert got["exclusion_reason"] == "inactive_preferred"


@pytest.mark.parametrize("metadata", [
    {"traded": "2026-01-08", "is_preferred": True},
    {"traded": "2026-01-08", "price": None, "is_preferred": True},
    {"traded": None, "inactive": True, "share_type": "preferred"},
])
def test_inactive_preferred_does_not_block_traded_ordinary_multiples(metadata):
    classes = [_class(), _class("ACMEP", **metadata)]
    fin, ratio = _statement(), _ratio()
    fin["total_liabilities"] = 1_000.0
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    got = contract.multiplier_contract(base, classes, fin, ratio)

    cap = got["market_cap_issuer"]
    assert cap["value"] == 1_000.0
    assert cap["calculation_status"] == contract.CALCULATED
    assert cap["basis"] == "active_share_classes"
    assert cap["excluded_classes"] == ["ACMEP"]
    excluded = cap["class_inputs"][1]
    assert excluded["included_in_issuer_cap"] is False
    assert excluded["usable_for_issuer_cap"] is False
    assert excluded["market_cap"] is None
    assert excluded["exclusion_reason"] == "inactive_preferred"
    for name, value in (("pe", 5.0), ("pb", 1.0), ("ps", 1.0)):
        assert got[name]["value"] == value
        assert got[name]["calculation_status"] == contract.CALCULATED
        assert got[name]["basis"] == "active_share_classes"
        assert "ACMEP" in got[name]["note"]
    # Excluding a market quote does not cancel the issuer's outstanding shares.
    assert got["bvps"]["value"] == 5.0
    assert got["bvps"]["inputs"]["total_issuer_shares_outstanding"] == 200.0


@pytest.mark.parametrize("metadata", [
    {"traded": "2026-05-01"},  # Ordinary ticker ending in P.
    {"traded": None, "is_preferred": True},  # Unknown activity.
    {"traded": "bad-date", "is_preferred": True, "inactive": True},
    {"traded": None, "is_preferred": True, "inactive": True, "trade_count": 2},
    {"shares": None, "is_preferred": True},  # Active but missing shares.
])
def test_unavailable_inputs_are_not_silently_excluded(metadata):
    classes = [_class(), _class("ACMEP", **metadata)]
    assert classes[1]["market_input"]["included_in_issuer_cap"] is True
    fin, ratio = _statement(), _ratio()
    got = contract.multiplier_contract(
        fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY),
        classes, fin, ratio)
    assert got["pe"]["value"] is None
    assert got["market_cap_issuer"]["missing_classes"] == ["ACMEP"]


def test_preferred_rejoins_capitalisation_when_trading_resumes():
    # The registry's inactive flag must not override a current execution.
    classes = [_class(), _class("ACMEP", is_preferred=True, inactive=True)]
    fin, ratio = _statement(), _ratio()
    got = contract.multiplier_contract(
        fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY),
        classes, fin, ratio)
    assert got["market_cap_issuer"]["value"] == 2_000.0
    assert got["pe"]["value"] == 10.0
    assert got["pe"]["basis"] == "issuer"


def test_only_inactive_preferred_never_produces_zero_cap_or_multiples():
    classes = [_class("ACMEP", traded="2026-01-08", is_preferred=True)]
    fin, ratio = _statement(), _ratio()
    got = contract.multiplier_contract(
        fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY),
        classes, fin, ratio)
    assert got["market_cap_issuer"]["value"] is None
    assert got["pe"]["value"] is None
    assert got["pe"]["calculation_status"] == contract.INCOMPLETE_MARKET_CAP


@pytest.mark.parametrize("preferred_quote", [
    {"last_trade_date": (date.today() - timedelta(days=254)).isoformat()},
    {"last_trade_date": None, "inactive": True},
])
def test_api_uses_catalog_share_class_to_exclude_inactive_preferred(monkeypatch, preferred_quote):
    import api

    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {
            "PLST": {"name": "Portlatishsanoat", "type": "stock"},
            "PLSTP": {"name": "Portlatishsanoat", "type": "stock", "is_preferred": True},
        },
        "board": [
            {"ticker": "PLST", "last_price": 10.0, "shares_outstanding": 100.0,
             "last_trade_date": date.today().isoformat()},
            {"ticker": "PLSTP", "last_price": 22.0, "shares_outstanding": 10.0,
             **preferred_quote},
        ],
        "financials": {"PLST": _statement()}, "ratios": {"PLST": _ratio()},
        "trade_date": date.today().isoformat(), "listings": {}, "stats": {},
    })
    ordinary = next(row for row in payload["items"] if row["ticker"] == "PLST")
    assert ordinary["pe"]["value"] == 5.0
    assert ordinary["market_cap_issuer"]["excluded_classes"] == ["PLSTP"]
    assert ordinary["issuer_classes"] == ["PLST", "PLSTP"]


def test_multiplier_contract_discloses_formula_inputs_and_stable_snapshot():
    classes = [_class()]
    fin, ratio = _statement(), _ratio()
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    first = contract.multiplier_contract(base, classes, fin, ratio,
                                         market_as_of="2026-08-31")
    second = contract.multiplier_contract(base, classes, fin, ratio,
                                          market_as_of="2026-08-31")

    assert first["pe"]["calculation_status"] == contract.CALCULATED
    assert first["pe"]["formula"] == (
        "issuer_market_cap / ttm_net_income")
    assert first["pe"]["inputs"] == {
        "issuer_market_cap": 1_000.0,
        "ttm_net_income": 200.0,
    }
    assert first["pe"]["basis"] == "issuer"
    assert first["pe"]["display_value"] == 5.0
    assert first["pe"]["display_warning"] is False
    assert first["pe"]["financial_scope"] == "UNKNOWN"
    assert first["calculation_snapshot"]["id"] == second["calculation_snapshot"]["id"]
    assert len(first["calculation_snapshot"]["id"]) == 64


def test_cache_input_version_changes_when_a_same_day_statement_is_corrected():
    base = {
        "board": [{"ticker": "ACME", "last_price": 10.0,
                   "last_trade_date": "2026-08-31", "shares_outstanding": 100.0}],
        "securities": {"ACME": {"org_id": "issuer-1", "type": "stock"}},
        "financials": {"ACME": _statement()}, "ratios": {"ACME": _ratio()},
        "trade_date": "2026-08-31",
    }
    corrected = {**base, "financials": {"ACME": _statement(net_income=201.0)}}
    assert contract.market_inputs_version(base) != contract.market_inputs_version(corrected)


def test_cache_input_version_changes_when_openinfo_cap_changes():
    base = {"listings": {"ACME": {"market_cap": 1_000.0, "updated_at": "2026-09-01"}}}
    corrected = {"listings": {"ACME": {"market_cap": 1_250.0, "updated_at": "2026-09-02"}}}
    assert contract.market_inputs_version(base) != contract.market_inputs_version(corrected)


def test_api_uses_openinfo_cap_for_all_issuer_classes(monkeypatch):
    import api

    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {
            "ACME": {"name": "Acme AJ", "type": "stock"},
            "ACMEP": {"name": "Acme AJ", "type": "stock", "is_preferred": True},
        },
        "board": [
            {"ticker": "ACME", "last_price": 10.0, "last_trade_date": "2026-08-31"},
            {"ticker": "ACMEP", "last_price": 5.0, "last_trade_date": "2025-02-26"},
        ],
        "listings": {
            "ACME": {"shares_outstanding": 100.0, "market_cap": 1_000.0,
                     "updated_at": "2026-09-01 05:00:00"},
            "ACMEP": {"shares_outstanding": 5.0, "market_cap": 25.0,
                      "updated_at": "2026-09-01 05:00:00"},
        },
        "financials": {"ACME": _statement()},
        "ratios": {"ACME": _ratio()},
        "trade_date": "2026-08-31", "stats": {},
    })

    ordinary = next(row for row in payload["items"] if row["ticker"] == "ACME")
    # ACMEP last traded 2025-02-26: an inactive preferred class, out of the cap.
    assert ordinary["market_cap_issuer"]["value"] == 1_000.0
    assert ordinary["market_cap_issuer"]["calculation_status"] == contract.CALCULATED
    assert ordinary["pe"]["value"] == 5.0
    assert {item["market_cap_method"]
            for item in ordinary["market_cap_issuer"]["class_inputs"]} == {"source_reported"}


def test_cache_input_version_changes_when_preferred_activity_is_confirmed():
    base = {"board": [{"ticker": "ACMEP", "share_type": "preferred", "inactive": None}]}
    confirmed = {"board": [{**base["board"][0], "inactive": True}]}
    assert contract.market_inputs_version(base) != contract.market_inputs_version(confirmed)


def test_stale_class_price_overrides_cap_dependent_public_status():
    classes = [_class(traded="2026-05-01")]
    fin, ratio = _statement(), _ratio()
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    got = contract.multiplier_contract(base, classes, fin, ratio,
                                       market_as_of="2026-05-01")

    assert got["market_cap_issuer"]["calculation_status"] == contract.STALE_PRICE
    for metric in ("pe", "pb", "ps"):
        assert got[metric]["value"] is None
        assert got[metric]["calculation_status"] == contract.STALE_PRICE


def test_loss_keeps_negative_pe_out_of_rankings_but_exposes_the_candidate():
    classes = [_class()]
    fin, ratio = _statement(net_income=-50.0), _ratio()
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    got = contract.multiplier_contract(base, classes, fin, ratio,
                                       market_as_of="2026-08-31")
    assert got["pe"]["value"] is None
    assert got["pe"]["calculation_status"] == contract.NOT_MEANINGFUL
    assert got["pe"]["display_value"] == -20.0
    assert got["pe"]["display_warning"] is True


def test_conflicted_statement_keeps_a_numeric_display_candidate():
    classes = [_class()]
    fin, ratio = _statement(), _ratio()
    fin["gross_profit"] = 2_000.0
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    got = contract.multiplier_contract(base, classes, fin, ratio,
                                       market_as_of="2026-08-31")

    assert got["pe"]["value"] is None
    assert got["pe"]["calculation_status"] == contract.DATA_CONFLICT
    assert got["pe"]["display_value"] == 5.0
    assert got["pe"]["display_warning"] is True


def test_structurally_inapplicable_metric_has_no_display_candidate():
    classes = [_class()]
    fin, ratio = _statement(), _ratio()
    fin["org_type"] = "bank"
    base = fundamentals.issuer_multiples(classes, fin, ratio, today=TODAY)
    got = contract.multiplier_contract(base, classes, fin, ratio,
                                       market_as_of="2026-08-31")

    assert got["ps"]["calculation_status"] == contract.NOT_APPLICABLE
    assert got["ps"]["display_value"] is None


def test_new_badge_expires_at_exactly_168_hours():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    just_inside = (now - timedelta(hours=168) + timedelta(seconds=1)).isoformat()
    boundary = (now - timedelta(hours=168)).isoformat()
    rows = contract.catalog_report_contract([
        {"report_form": "NSBU", "period_type": "quarter", "year": 2026,
         "quarter": 2, "published_at": just_inside},
        {"report_form": "IFRS", "period_type": "annual", "year": 2025,
         "quarter": 0, "published_at": boundary},
    ], now=now)

    assert rows[0]["library_status"] == "new"
    assert rows[0]["badge"]["window_hours"] == 168
    assert rows[1]["library_status"] == "latest_available"
    assert rows[1]["badge"] is None
    assert rows[1]["verification_status"] == "UNKNOWN"
    assert rows[1]["calculation_eligible"] is False


def test_pipeline_and_correction_states_are_distinct():
    now = datetime(2026, 9, 1, tzinfo=timezone.utc)
    rows = contract.catalog_report_contract([
        {"report_form": "IFRS", "period_type": "annual", "pipeline_stage": "PARSING"},
        {"report_form": "NSBU", "period_type": "quarter", "workflow_status": "NEEDS_REVIEW"},
        {"report_form": "audit", "period_type": "annual", "version": 2,
         "published_at": (now - timedelta(hours=2)).isoformat(), "verified": True},
    ], now=now)
    assert [row["library_status"] for row in rows] == [
        "processing", "requires_review", "corrected"]


def test_api_payload_passes_price_and_freshness_into_the_contract(monkeypatch):
    # Importing here keeps the pure contract tests independent of the web app.
    import api

    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {"ACME": {"name": "Acme", "type": "stock"}},
        "board": [{
            "ticker": "ACME", "name": "Acme", "type": "stock",
            "last_price": 10.0, "last_trade_date": "2026-05-01",
            "shares_outstanding": 100.0, "market_cap": 1_000.0,
        }],
        "financials": {"ACME": _statement()},
        "ratios": {"ACME": _ratio()},
        "trade_date": "2026-05-01", "listings": {}, "stats": {},
    })

    row = payload["items"][0]
    assert row["market_input"]["calculation_status"] == contract.STALE_PRICE
    assert row["pe"]["calculation_status"] == contract.STALE_PRICE
    assert row["pe"]["inputs"]["issuer_market_cap"] is None


def test_a_preferred_class_the_catalog_misnames_joins_its_ordinary_by_the_board_class(monkeypatch):
    """UZNGP: renamed plain «O'zbekneftgaz», the catalog read it as ordinary and
    it printed P/E 0,04× alone. The board's class field (openinfo stock_type 02)
    keeps it with UZNG."""
    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {
            "ACME": {"name": '"Acme" Aksiyadorlik jamiyati', "type": "stock"},
            "ACMEP": {"name": "Acme", "type": "stock"},
        },
        "board": [
            {"ticker": "ACME", "share_type": "ordinary", "last_price": 10.0,
             "last_trade_date": "2026-08-31", "shares_outstanding": 100.0},
            {"ticker": "ACMEP", "share_type": "preferred", "last_price": 5.0,
             "last_trade_date": "2026-08-31", "shares_outstanding": 5.0},
        ],
        "listings": {},
        "financials": {"ACME": _statement()},
        "ratios": {"ACME": _ratio()},
        "trade_date": "2026-08-31", "stats": {},
    })
    rows = {row["ticker"]: row for row in payload["items"]}
    assert rows["ACMEP"]["share_class"] == "preferred"
    assert rows["ACMEP"]["issuer_classes"] == rows["ACME"]["issuer_classes"] == ["ACME", "ACMEP"]


def test_a_board_class_never_turns_an_ordinary_line_preferred():
    assert subject_server_market_valuations._board_says_preferred({"share_type": "ordinary"}) is False
    assert subject_server_market_valuations._board_says_preferred({}) is False
    assert subject_server_market_valuations._board_says_preferred({"share_type": "Preferred"}) is True


def test_a_class_with_only_an_archived_negotiated_deal_is_valued_at_it(monkeypatch):
    # AGMK: no session price ever, one NC block in openinfo's archive
    # (19.11.2024 at 69 499). Customer decision 2026-10-08: that deal counts,
    # however old, and every cap multiple says so.
    import api

    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    monkeypatch.setattr(subject_server_market_valuations.catalogue_market_store, "_share_registry", lambda: {
        "AGMK": {"last_execution": {"date": "2024-11-19", "price": 69499, "board": "NC",
                                    "source": "https://openinfo.example/trade-results"}},
    })
    def scaled(row):  # a statement on the cap's scale (~7 mln), not the toy 1 000
        return {k: (v * 10_000 if isinstance(v, float) else scaled(v) if isinstance(v, dict) else v)
                for k, v in row.items()}

    today = date.today().isoformat()
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {
            "AGMK": {"name": "Olmaliq KMK", "type": "stock"},
            "AGMKP": {"name": "Olmaliq KMK", "type": "stock", "is_preferred": True},
        },
        "board": [
            {"ticker": "AGMK", "last_price": 3914.0, "shares_outstanding": 100.0},
            {"ticker": "AGMKP", "last_price": 31850.0, "shares_outstanding": 10.0,
             "last_trade_date": today},
        ],
        "financials": {"AGMK": scaled(_statement())}, "ratios": {"AGMK": scaled(_ratio())},
        "trade_date": today, "listings": {}, "stats": {},
    })
    row = next(r for r in payload["items"] if r["ticker"] == "AGMKP")
    agmk = next(c for c in row["market_cap_issuer"]["class_inputs"] if c["ticker"] == "AGMK")

    assert agmk["usable_for_issuer_cap"] is True
    assert agmk["price_basis"] == contract.NEGOTIATED_EXECUTION
    assert agmk["price_as_of"] == "2024-11-19"
    assert agmk["market_cap"] == 100.0 * 69499
    assert row["market_cap_issuer"]["value"] == 100.0 * 69499 + 10.0 * 31850
    assert row["pe"]["value"] == pytest.approx((100.0 * 69499 + 10.0 * 31850) / 2_000_000.0, rel=1e-3)
    assert row["pe"]["estimate"] is True
    assert "по сделке 19.11.2024 (NC), 69 499 сум" in row["pe"]["note"]
    assert row["roe"].get("estimate") is not True


def test_a_session_trade_beats_the_archived_deal(monkeypatch):
    import api

    monkeypatch.setattr(subject_server_market_valuations, '_apply_audit_blocks', lambda rows: 0)
    monkeypatch.setattr(subject_server_market_valuations.catalogue_market_store, "_share_registry", lambda: {
        "AGMK": {"last_execution": {"date": "2024-11-19", "price": 69499, "board": "NC"}},
    })
    today = date.today().isoformat()
    payload = subject_server_market_valuations._multiples_payload({
        "securities": {"AGMK": {"name": "Olmaliq KMK", "type": "stock"}},
        "board": [{"ticker": "AGMK", "last_price": 50000.0, "shares_outstanding": 100.0,
                   "last_trade_date": today}],
        "financials": {"AGMK": _statement()}, "ratios": {"AGMK": _ratio()},
        "trade_date": today, "listings": {}, "stats": {},
    })
    agmk = payload["items"][0]["market_input"]
    assert agmk["price"] == 50000.0
    assert agmk["price_basis"] == "session"
    assert payload["items"][0]["pe"].get("estimate") is not True
