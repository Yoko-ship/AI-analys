"""Public financial contract regression tests for the 2026-09-01 specification."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import fundamentals
import public_contract as contract


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
           shares=100.0, cap=1_000.0):
    raw = {
        "ticker": ticker, "last_trade_date": traded, "last_price": price,
        "shares_outstanding": shares, "market_cap": cap,
        "source_url": "https://uzse.example/quote",
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


def test_openinfo_reported_cap_replaces_a_stale_price_reconstruction():
    got = contract.market_class_input({
        "ticker": "ACMEP",
        "last_price": 10.0,
        "last_trade_date": "2025-02-26",
        "shares_outstanding": 25.0,
        "market_cap": 275.0,
        "market_cap_source": "openinfo_listing",
    }, reference_date=TODAY)

    assert got["calculation_status"] == contract.CALCULATED
    assert got["market_cap"] == 275.0
    assert got["price_age_days"] > got["max_price_age_days"]


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

    monkeypatch.setattr(api, "_apply_audit_blocks", lambda rows: 0)
    payload = api._multiples_payload({
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
    assert ordinary["market_cap_issuer"]["value"] == 1_025.0
    assert ordinary["market_cap_issuer"]["calculation_status"] == contract.CALCULATED
    assert ordinary["pe"]["value"] == 5.125
    assert {item["market_cap_method"]
            for item in ordinary["market_cap_issuer"]["class_inputs"]} == {"source_reported"}


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

    monkeypatch.setattr(api, "_apply_audit_blocks", lambda rows: 0)
    payload = api._multiples_payload({
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
