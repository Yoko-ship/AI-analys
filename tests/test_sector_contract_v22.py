"""Acceptance regressions: analytical safety, arithmetic, provenance and state."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json

import pytest

import sector_analysis as core
import fund_analysis
import analysis_monitor
import bonds
from bond_quality import freshness
from reports_catalog import extract_insurance_balance


TODAY = date(2026, 8, 30)
ISSUER = {"id": "1", "ticker": "FACT", "name": "Factory", "oked_code": "24100"}


@pytest.mark.parametrize("configured,expected", [
    ('{}', "administrator"),
    ('{"scoped@example.org":"viewer"}', "viewer"),
    ('{"scoped@example.org":"disabled"}', None),
    ('{"scoped@example.org":null}', None),
    ('{"scoped@example.org":[]}', None),
    ('[]', None),
    ('invalid-json', None),
])
def test_standalone_sector_access_fails_closed(monkeypatch, configured, expected):
    from sector_access import configured_role_for
    monkeypatch.setenv("ADMIN_EMAILS", "scoped@example.org")
    monkeypatch.setenv("ADMIN_ROLES", configured)
    assert configured_role_for(" Scoped@Example.org ") == expected
    assert configured_role_for("") is None


def snapshot(**updates):
    data = {
        "organization_type": "non_financial", "standard": "nsbu", "scope": "separate",
        "period": "2026Q2", "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
        "current_values": {"total_assets": 1000, "total_equity": 400, "total_liabilities": 600,
                           "revenue": 500, "net_income": 80, "operating_income": 100},
        "previous_values": {"revenue": 400, "net_income": 40, "operating_income": 80},
        "opening_values": {"total_assets": 900, "total_equity": 400, "total_liabilities": 500},
        "source": {"document_id": "filing-1", "url": "https://example.org/filing.pdf"},
        "quality": {"data_quality": []},
    }
    data.update(updates)
    return data


def test_routing_special_types_and_conflicts():
    assert core.resolve_template({"oked_code": "64190"}, "bank")["selected_template"] == "bank"
    assert core.resolve_template({"oked_code": "64190"}, "microfinance_bank")["selected_template"] == "microfinance_bank"
    assert core.resolve_template({})["selected_template"] == "generic_nsbu"
    conflict = core.resolve_template({**ISSUER, "verified_activity_template": "telecom"})
    assert conflict["resolution_status"] == "classification_conflict"
    report = core.make_report(snapshot(template_resolution=conflict), ISSUER, today=TODAY)
    assert report["status"] == "quality_blocked"
    assert not report["verified_facts"] and not report["ratios"]


def test_missing_zero_and_source_columns_are_not_interchangeable():
    parsed = {"sheets": [{"name": "Form1", "table_rows": [
        {"label": "Assets", "source_cells": ["Assets", 400.0, "120", None], "numeric_values": [400, 120]},
        {"label": "Cash", "source_cells": ["Cash", "320", "22", "0"]},
    ]}]}
    rows = core.source_line_pairs(parsed, "form1")
    assert rows["c400"]["current"] is None
    assert rows["c400"]["previous"] == 120
    assert rows["c320"]["current"] == 0
    assert core.total(1, None) is None
    assert core.ratio(12, 0) is None
    assert core.decimal("1 234,56") == Decimal("1234.56")
    assert core.decimal("NaN") is None


def test_form2_loss_and_structurally_crossed_out_cells():
    parsed = {"sheets": [{"table_rows": [
        {"source_cells": ["Net income", "270", 10, 0, 0, 7]},
        {"source_cells": ["Revenue", "010", 50, "X", None, "X"]},
    ]}]}
    rows = core.source_line_pairs(parsed, "form2")
    assert rows["c270"]["current"] == -7
    assert rows["c010"]["previous"] == 50
    assert rows["c010"]["current"] is None


def ratio_lines():
    vals = {
        "form2:c270": "80", "form2:c240": "100", "form2:c030": "200",
        "form2:c010": "500", "form2:c020": "300",
        "form1:c400": "1000", "form1:c390": "450", "form1:c480": "400",
        "form1:c570": "50", "form1:c580": "50", "form1:c130": "600",
        "form1:c320": "50", "form1:c370": "25", "form1:c210": "127",
        "form1:c140": "198", "form1:c600": "200",
    }
    return {k: {"raw_current": v, "raw_previous": v, "current": float(v)} for k, v in vals.items()}


def test_exact_nsbu_methods_and_sector_exclusions():
    lines = ratio_lines()
    ratios = {r["metric"]: r for r in core.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q2")}
    assert ratios["P1"]["value"] == 8
    assert ratios["P3"]["value"] == 20
    assert ratios["P4"]["value"] == 25
    assert ratios["current_ratio"]["value"] == 2
    assert ratios["quick_ratio"]["value"] == 1.01
    assert ratios["absolute_liquidity"]["value"] == .375
    assert ratios["P6"]["raw_result"].startswith("66.666666666666")
    del lines["form1:c580"]
    assert next(r for r in core.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q2") if r["metric"] == "P3")["value"] is None
    for organization in ("bank", "insurance", "microfinance", "microfinance_bank"):
        assert core.enterprise_ratios(lines, organization, "nsbu", "2026Q2") == []
    assert core.enterprise_ratios(lines, "non_financial", "ifrs", "2025") == []


def test_balance_requires_both_tolerances_and_percentage_reconciliation():
    assert core.balance_gate({"total_assets": 1000000, "total_equity": 400000, "total_liabilities": 599998})["status"] == "failed"
    assert core.balance_gate({"total_assets": 10, "total_equity": 4, "total_liabilities": 5.99})["status"] == "failed"
    assert core.balance_gate({"total_assets": 0, "total_equity": 5, "total_liabilities": 5})["status"] == "failed"
    report = core.make_report(snapshot(source_lines=ratio_lines(), reported_ratios={"P1": "8.11"}), ISSUER, today=TODAY)
    assert report["status"] == "quality_blocked"
    assert any(q["code"] == "PERCENTAGE_RECONCILIATION_FAILED" for q in report["data_quality"])


def test_fx_growth_does_not_hide_operating_decline_or_invent_cash():
    data = snapshot()
    data["current_values"].update(net_income=149.4, operating_income=91.1, fx_income=80, fx_expenses=10)
    data["previous_values"].update(net_income=10, operating_income=100, fx_income=10, fx_expenses=100)
    report = core.make_report(data, ISSUER, today=TODAY, lang="en")
    assert report["profit_quality"]["net_fx_result_change"] == 160
    assert report["verdict"]["status"] == "mixed"
    assert report["profit_quality"]["driver"] == "FX-driven"
    assert "100.00 → 91.10" in report["headline"]
    assert "Low-base" in report["headline"]
    assert report["profit_quality"]["cash_confirmation"] == "not_available"
    assert report["analytical_issues"]
    assert all(i["solution_code"] and i["evidence_fact_ids"] and i["source_ids"] for i in report["analytical_issues"])
    assert not any(word in json.dumps(report).lower() for word in ("ebitda", "cet1", "lcr", "capex", '"cfo"'))


def test_no_signal_does_not_invent_an_issue():
    data = snapshot(previous_values={"net_income": 100}, opening_values={})
    report = core.make_report(data, ISSUER, today=TODAY)
    assert report["verdict"]["status"] == "no_signal"
    assert not report["analytical_issues"] and not report["risks"]
    generic = core.make_report(snapshot(), {**ISSUER, "oked_code": None}, today=TODAY)
    assert generic["verdict"]["status"] == "no_signal"


def test_trend_requires_comparable_points_and_four_points_for_three_declines():
    context = {"period_basis": "cumulative_ytd", "accounting_standard": "nsbu",
               "consolidation_scope": "separate"}
    two = [
        {"period": "2025Q2", "value": 12, **context},
        {"period": "2026Q2", "value": 10, **context},
    ]
    assert core.trend_state(two)["status"] == "comparison_only"
    three = two + [{"period": "2027Q2", "value": 8, **context}]
    assert core.trend_state(three)["status"] == "trend"
    four = three + [{"period": "2028Q2", "value": 7, **context}]
    assert core.trend_state(four)["status"] == "three_consecutive_declines"
    mixed_basis = [two[0], {**two[1], "period_basis": "standalone_quarter"}]
    assert core.trend_state(mixed_basis)["status"] == "not_comparable"


def test_bank_without_prior_income_uses_required_comparison_limit():
    current = {
        "total_assets": 1000, "total_equity": 400, "total_liabilities": 600,
        "cash": 100, "loan_portfolio": 650, "customer_funds": 500,
        "interest_income": 90, "interest_expenses": 40, "net_income": 25,
    }
    data = snapshot(organization_type="bank", current_values=current,
                    previous_values={}, opening_values={"total_assets": 900, "total_equity": 380,
                                                       "total_liabilities": 520})
    bank = {"id": "BANK", "ticker": "BANK", "name": "Bank", "special_legal_type": "bank"}
    report = core.make_report(data, bank, today=TODAY, lang="ru")
    assert report["content_status"] == "complete"
    assert "Динамика баланса — относительно начала года; изменение прибыли и рентабельности не оценивается" in report["text"]


def test_zero_insurance_assets_are_not_replaced_by_previous_year():
    rows = [
        {"label": "Всего по активу баланса (стр.130+480)", "numeric_values": [490, 9999, 0]},
        {"label": "Итого по разделу I (стр.500+510+520-530+540+550+560)", "numeric_values": [570, 999, 50]},
        {"label": "Страховые резервы (стр.590+600+610+620+630+640+650+660)", "numeric_values": [580, 999, 80]},
        {"label": "Доля (стр.680+690+700+710)", "numeric_values": [670, 0, 20]},
        {"label": "Итого по разделу III (стр.730+930)", "numeric_values": [1190, 0, 40]},
    ]
    result = extract_insurance_balance({"sheets": [{"table_rows": rows}]})
    assert result["total_assets"] == 0
    assert result["net_insurance_reserves"] == 60
    assert result["total_liabilities"] == 100
    assert core.balance_gate(result)["status"] == "failed"
    rows[0]["source_cells"] = ["Assets", "490", 9999, None]
    assert extract_insurance_balance({"sheets": [{"table_rows": rows}]})["total_assets"] is None


def test_fund_audited_nav_lineage_and_share_reconciliation():
    issuer = {"id": "UZNF", "ticker": "UZNF", "name": "National Fund"}
    data = fund_analysis.audited_snapshot(issuer)
    report = fund_analysis.enrich(core.make_report(data, issuer, today=TODAY), data)
    assert report["sector_template_code"] == "investment_fund_ifrs_annual"
    assert report["nav"]["value_mln_uzs"] == 29861539
    assert report["portfolio"]["portfolio_to_assets_pct"] == pytest.approx(99.45, abs=.01)
    assert report["portfolio"]["top_5_pct"] == pytest.approx(68.23, abs=.01)
    assert report["portfolio"]["level_3_share_pct"] == 100
    assert report["valuation"]["price_to_nav"] is None
    assert all(f["source_line_id"].startswith("PDF:") for f in report["verified_facts"])
    assert not report["ratios"]
    assert report["comparison_status"] == "not_available_first_reporting_period"
    assert all(f["previous"] is None for f in report["verified_facts"])
    report["market_as_of"] = "2026-08-28"
    fund_analysis.reconcile_share_basis(report, {
        "exchange_shares": "5054262531127", "exchange_nominal_uzs": "5",
        "source_url": "https://example.org/verified-action", "verification_status": "verified",
        "effective_date": "2026-01-01",
    }, 6.75)
    assert report["nav"]["per_exchange_share_uzs"] == pytest.approx(5.908, abs=.001)
    assert report["valuation"]["price_to_nav"] == pytest.approx(1.1425, abs=.001)
    assert report["financial_as_of"] == "2025-12-31"


@pytest.mark.parametrize("market_date,price,effective,reason", [
    ("2026-08-01", 6.75, "2026-01-01", "STALE_OR_INVALID_QUOTE"),
    ("2026-08-28", 6.75, "2026-08-29", "QUOTE_PRECEDES_SHARE_BASIS"),
    ("2026-08-28", 0, "2026-01-01", "NO_VERIFIED_TRADE"),
    ("2026-08-28", 6.75, "2027-01-01", "SHARE_BASIS_NOT_RECONCILED"),
])
def test_fund_valuation_requires_valid_share_date_and_recent_positive_quote(market_date, price, effective, reason):
    issuer = {"id": "UZNF", "ticker": "UZNF"}
    data = fund_analysis.audited_snapshot(issuer)
    report = fund_analysis.enrich(core.make_report(data, issuer, today=TODAY), data)
    report["market_as_of"] = market_date
    fund_analysis.reconcile_share_basis(report, {
        "exchange_shares": "5054262531127", "exchange_nominal_uzs": "5",
        "source_url": "https://example.org/verified-action", "verification_status": "verified",
        "effective_date": effective,
    }, price, TODAY)
    assert report["valuation"]["price_to_nav"] is None
    assert report["valuation"]["blocked_reason"] == reason


@pytest.mark.parametrize("days,status", [(0, "fresh"), (7, "fresh"), (8, "aging"), (30, "aging"), (31, "stale"), (90, "stale"), (91, "very_stale")])
def test_bond_freshness_boundaries(days, status):
    assert freshness((TODAY - timedelta(days=days)).isoformat(), TODAY)["status"] == status


def bond_input(trade_date="2026-08-30"):
    row = {"ticker": "EX1B", "isin": "UZBOND", "last_price": 1000, "last_trade_date": trade_date}
    reference = {"isin": "UZBOND", "nominal": 1000, "coupon_rate": 20, "coupon_freq": 1,
                 "coupon_type": "fixed", "currency": "UZS", "status": "active", "issue_date": "2026-08-30",
                 "maturity_date": "2027-08-30", "day_count": "ACT/365",
                 "schedule_source": "prospectus", "cashflows_verified": True, "options_verified": True}
    payments = [{"pay_date": "2027-08-30", "amount": 200, "principal": 1000,
                 "period_from": "2026-08-30", "period_to": "2027-08-30", "source_url": "https://example.org/prospectus"}]
    return row, reference, payments


def test_verified_bond_ytm_gspread_and_staleness():
    row, ref, coupons = bond_input()
    curve = [{"term_days": 365, "rate": 10, "as_of": "2026-08-30", "currency": "UZS", "compounding": "continuous"}]
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY, gov_points=curve)
    assert result["dirty"]["value"] == 1000
    assert result["ytm"]["value"] == pytest.approx(20, abs=.001)
    assert result["ytm"]["status"] == "exact"
    assert result["duration"]["value"] == pytest.approx(1)
    assert result["modified_duration"]["value"] == pytest.approx(1 / 1.2)
    import math
    assert result["g_spread"]["bps"] == pytest.approx((math.log1p(.2) * 100 - 10) * 100, abs=.01)
    row["last_trade_date"] = "2026-05-01"
    stale = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert stale["instrument_verdict"] == "insufficient_data"
    assert stale["yield"]["ytm_effective"] is None
    assert stale["ytm"]["status"] == "stale_indicative"


def test_bond_unverified_schedule_no_trade_and_missing_daycount():
    row, ref, coupons = bond_input()
    ref["cashflows_verified"] = False
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["ytm"]["status"] == "indicative"
    assert result["ytm"]["confidence"] == "low"
    assert result["g_spread"]["value"] is None
    row["last_trade_date"] = None
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["freshness"]["status"] == "never_traded"
    assert result["ytm"]["value"] is None and result["duration"]["value"] is None
    ref.pop("day_count")
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["accrued"]["value"] is None and result["dirty"]["value"] is None


def test_bond_accrual_does_not_require_a_market_trade_but_does_require_its_period():
    row, ref, coupons = bond_input(trade_date=None)
    coupons[0]["period_from"] = "2026-08-01"
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["accrued"]["value"] == pytest.approx(200 * 29 / 394)
    assert result["accrued"]["status"] == "exact"
    assert result["dirty"]["value"] is None and result["ytm"]["value"] is None
    coupons[0].pop("period_from")
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["accrued"]["value"] is None
    assert result["accrued"]["blocked_reason"] == "ACCRUAL_PERIOD_NOT_VERIFIED"


@pytest.mark.parametrize("basis", ["ACT/360", "ACT/ACT", "30/360"])
def test_verified_bond_supports_disclosed_day_count_conventions(basis):
    row, ref, coupons = bond_input()
    ref["day_count"] = basis
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["day_count_basis"] == basis
    assert result["ytm"]["status"] == "exact"
    assert result["rate_scenarios"]["status"] == "ok"
    assert [item["shift_bps"] for item in result["rate_scenarios"]["items"]] == [-200, -100, 100, 200]
    assert result["dv01"]["value"] == pytest.approx(result["bpv"]["value"])


def test_negative_yield_and_verified_call_scenarios_are_supported():
    negative = bonds.yield_to_maturity([(1.0, 100.0)], 110.0, basis="ACT/365F")
    assert negative["value"] == pytest.approx(-9.090909, abs=1e-5)
    row, ref, coupons = bond_input()
    ref.update(has_call=True, call_schedule=[{"date": "2027-02-28", "price": 1000}])
    result = bonds.bond_row(row, reference=ref, coupons=coupons, today=TODAY)
    assert result["ytc"]["value"] is not None
    assert result["ytw"]["value"] == min(result["ytm"]["value"], result["ytc"]["value"])
    assert result["ytw"]["scenario"] in {"maturity", "issuer_call"}


def test_due_date_and_accrual_filing_do_not_claim_payment_execution():
    reference = {"nominal": 1000, "coupon_rate": 20, "coupon_freq": 1,
                 "issue_date": "2025-08-30", "maturity_date": "2027-08-30"}
    accrual = {"coupon_no": 1, "pay_date": "2026-08-30", "amount": 200,
               "source_url": "https://example.org/accrual"}
    due = next(item for item in bonds.issue_schedule(reference, [accrual], TODAY)
               if item["date"] == "2026-08-30")
    assert due["due"] is True and due["paid"] is False
    assert due["execution_status"] == "due_unconfirmed"
    confirmed = next(item for item in bonds.issue_schedule(reference, [{**accrual, "payment_confirmed": True}], TODAY)
                     if item["date"] == "2026-08-30")
    assert confirmed["paid"] is True and confirmed["execution_status"] == "paid_confirmed"


def test_monitor_idempotency_retains_last_good_and_audits_retries(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "monitor.sqlite3"))
    good = core.make_report(snapshot(), ISSUER, today=TODAY)
    analysis_monitor.record_report(deepcopy(good))
    analysis_monitor.record_report(deepcopy(good))
    bad = snapshot()
    bad["current_values"]["total_assets"] = 0
    blocked = analysis_monitor.record_report(core.make_report(bad, ISSUER, today=TODAY))
    assert blocked["last_successful_report"]["version"] == good["version"]
    assert len(analysis_monitor.overview()["runs"]) == 2
    job = analysis_monitor.enqueue("FACT", "source-1")
    assert analysis_monitor.enqueue("FACT", "source-1") == job
    assert len(analysis_monitor.overview()["jobs"]) == 1
    assert analysis_monitor.retry(job, "admin@example.org", "Corrected mapping")
    assert analysis_monitor.overview()["audit"][0]["actor"] == "admin@example.org"


def test_override_versions_impact_queue_and_publication_rollback(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "rules.sqlite3"))
    rule = {"override_template": "telecom", "evidence_source": "https://example.org/classification",
            "reason_code": "Verified principal activity", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    saved = analysis_monitor.save_override(ISSUER, rule, "admin@example.org")
    assert saved["regression"]["status"] == "passed"
    assert analysis_monitor.active_override("1", "2026-08-30")["version"] == saved["version"]
    assert analysis_monitor.active_override("1", "2027-01-01") is None
    assert len(analysis_monitor.overview()["jobs"]) == 1
    good = analysis_monitor.record_report(core.make_report(snapshot(), ISSUER, today=TODAY))
    newer_input = snapshot()
    newer_input["current_values"]["revenue"] = 550
    newer = analysis_monitor.record_report(core.make_report(newer_input, ISSUER, today=TODAY))
    assert analysis_monitor.rollback(good["version"], "admin@example.org", "Review source correction")
    restored = analysis_monitor.record_report(deepcopy(newer))
    assert restored["version"] == good["version"]
    assert restored["publication_restored"]
    newer_input["current_values"]["revenue"] = 600
    released = analysis_monitor.record_report(core.make_report(newer_input, ISSUER, today=TODAY))
    assert released["version"] != good["version"]
    assert not released.get("publication_restored")


def test_rollback_does_not_make_an_old_filing_current(monkeypatch, tmp_path):
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "stale-rollback.sqlite3"))
    old = analysis_monitor.record_report(core.make_report(snapshot(period="2025Q2"), ISSUER, today=date(2025, 8, 30)))
    current = analysis_monitor.record_report(core.make_report(snapshot(), ISSUER, today=TODAY))
    assert analysis_monitor.rollback(old["version"], "admin@example.org", "Review source change")
    current["generated_at"] = "2026-08-30T10:00:00+00:00"
    restored = analysis_monitor.record_report(current)
    assert restored["status"] == "stale"
    assert restored["last_successful_report"]["period"] == "2025Q2"


def test_worker_retries_then_deduplicates_incident(monkeypatch, tmp_path):
    import sector_report_service
    import issuer_analysis_api
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setattr(issuer_analysis_api, "_resolve_issuer", lambda _: ISSUER)
    def failure(*args, **kwargs):
        raise TimeoutError("Temporary source failure")
    monkeypatch.setattr(sector_report_service, "sector_report", failure)
    job = analysis_monitor.enqueue("FACT", "source-timeout")
    for attempt in range(1, 5):
        with analysis_monitor.connect() as connection:
            connection.execute("UPDATE sector_jobs SET next_attempt='2000-01-01' WHERE id=?", (job,))
        assert analysis_monitor.run_pending() == 1
        row = analysis_monitor.overview()["jobs"][0]
        assert row["attempts"] == attempt
        assert row["state"] == ("retry" if attempt < 4 else "incident")
    assert analysis_monitor.run_pending() == 0
    assert analysis_monitor.enqueue("FACT", "source-timeout") == job
    assert len(analysis_monitor.overview()["jobs"]) == 1


def test_sector_admin_requires_human_admin_and_audits_mutations(monkeypatch, tmp_path):
    import api
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "admin.sqlite3"))
    monkeypatch.setenv("ADMIN_CONTROL_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("ADMIN_EMAILS", "allowed@example.org")
    monkeypatch.setenv("ADMIN_API_SECRET", "collector-test-secret")
    user = type("User", (), {"email": "allowed@example.org", "id": 12})()
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda token: user if token == "test-token" else None)
    client = TestClient(api.app)
    path = "/api/admin/sector-analysis"
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"X-Admin-Secret": "collector-test-secret"}).status_code == 401
    headers = {"Authorization": "Bearer test-token"}
    assert client.get(path, headers=headers).status_code == 200
    user.email = "not-admin@example.org"
    assert client.get(path, headers=headers).status_code == 403
    user.email = "allowed@example.org"
    job = analysis_monitor.enqueue("FACT", "blocked-source")
    assert client.post(f"{path}/jobs/{job}/retry", headers=headers, json={"reason": "x"}).status_code == 422
    assert client.post(f"{path}/jobs/{job}/retry", headers=headers, json={"reason": "Retest corrected source"}).status_code == 200
    assert analysis_monitor.overview()["audit"][0]["actor"] == user.email


def test_sector_admin_role_capabilities_cannot_be_escalated(monkeypatch, tmp_path):
    import api
    import issuer_analysis_api
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "roles.sqlite3"))
    monkeypatch.setenv("ADMIN_CONTROL_DB", str(tmp_path / "access.sqlite3"))
    monkeypatch.setenv("ADMIN_EMAILS", "scoped@example.org")
    user = type("User", (), {"email": "scoped@example.org", "id": 3})()
    monkeypatch.setattr(api.web_auth_store, "get_user_by_token", lambda _: user)
    monkeypatch.setattr(issuer_analysis_api, "_resolve_issuer", lambda _: ISSUER)
    client = TestClient(api.app)
    headers = {"Authorization": "Bearer role-test"}
    path = "/api/admin/sector-analysis"
    job = analysis_monitor.enqueue("FACT", "role-test")
    payload = {"ticker": "FACT", "override_template": "metallurgy", "evidence_source": "https://example.org/activity",
               "reason_code": "Verified activity", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    for role in ("viewer", "analyst", "rule_editor", "administrator"):
        monkeypatch.setenv("ADMIN_ROLES", json.dumps({user.email: role}))
        response = client.get(path, headers=headers)
        assert response.status_code == 200 and response.json()["role"] == role
        retry = client.post(f"{path}/jobs/{job}/retry", headers=headers, json={"reason": "Review corrected filing"})
        assert retry.status_code == (403 if role == "viewer" else 200)
        update = client.post(f"{path}/overrides", headers=headers, json=payload)
        assert update.status_code == (409 if role in {"rule_editor", "administrator"} else 403)
        if role in {"rule_editor", "administrator"}:
            assert "USE_GOVERNED_WORKFLOW" in update.json()["detail"]


def test_real_combined_workbooks_do_not_mix_balance_and_income_rows():
    from pathlib import Path
    from sector_report_service import map_special_lines
    filings = json.loads((Path(__file__).parent / "fixtures/sector_v22_filings.json").read_text(encoding="utf8"))
    results = {}
    for ticker, filing in filings.items():
        data = snapshot(current_values={}, previous_values={}, opening_values={},
                        organization_type=filing["organization_type"], source=filing["source"])
        issuer = filing["issuer"]
        if ticker == "UZMK":
            issuer = {**issuer, "oked_code": "24100"}
        if filing["organization_type"] != "non_financial":
            map_special_lines(data, filing["workbook"], filing["organization_type"])
        result = core.make_report(data, issuer, "en", TODAY, filing["workbook"])
        assert result["status"] == "available", (ticker, result["data_quality"])
        results[ticker] = result
    steel = results["UZMK"]
    assert steel["profit_quality"]["net_fx_result_change"] == 499571337
    assert steel["profit_quality"]["operating_profit_change"]["change_pct"] == pytest.approx(-8.90, abs=.01)
    assert steel["verdict"]["status"] == "mixed"
    assert next(r for r in steel["ratios"] if r["metric"] == "quick_ratio")["value"] == pytest.approx(1.01913778)
    assert steel["capital_analysis"]["reconciliation_status"] == "passed"
    assert results["UZAS"]["balance_check"]["status"] == "passed"
    insurance = {f["metric"]: f["value"] for f in results["UZAS"]["verified_facts"]}
    assert insurance["total_liabilities"] == pytest.approx(184886318.3)
    assert insurance["operating_income"] == pytest.approx(-5547703.4)
    bank = {f["metric"]: f["value"] for f in results["HMKB"]["verified_facts"]}
    assert bank["interest_income"] == 2994355667
    assert bank["interest_expenses"] == 1520167682
    assert bank["net_income"] == 969962031
    assert bank["total_assets"] == bank["total_liabilities"] + bank["total_equity"]


def test_two_bonds_share_issuer_calculation_but_not_instrument_results(monkeypatch, tmp_path):
    import sector_report_service as service
    import issuer_analysis_api as api
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "shared.sqlite3"))
    monkeypatch.setattr(service, "_REPORT_CACHE", {})
    monkeypatch.setattr(api, "_resolve_issuer", lambda _: ISSUER)
    monkeypatch.setattr(api, "_organization_type", lambda *_: "non_financial")
    monkeypatch.setattr(api, "_financial_snapshot", lambda *_: snapshot())
    monkeypatch.setattr(api, "_report_rows", lambda *_: [])
    monkeypatch.setattr(api, "_quote_and_trade", lambda *_: ({"trade_date": "2026-08-28", "close_price": 123}, {}))
    calls = []
    make = core.make_report
    def counted(*args, **kwargs):
        calls.append(1)
        return make(*args, **kwargs)
    monkeypatch.setattr(core, "make_report", counted)
    first = service.bond_issuer_context({"issuer_id": "1", "isin": "ISSUE-1"})
    second = service.bond_issuer_context({"issuer_id": "1", "isin": "ISSUE-2"})
    assert first["issuer_id"] == second["issuer_id"] == "1"
    assert first["issuer_analysis_id"] == second["issuer_analysis_id"]
    assert len(calls) == 1
    assert "instrument" not in first["issuer_report"]
    assert first["issuer_report"]["market_as_of"] is None
    assert not service.bond_issuer_context({})["issuer_report"]


def test_cross_form_scale_also_withholds_market_multiples_without_prior_annual():
    import fundamentals
    fin = {"year": 2026, "quarter": 2, "period_months": 6, "revenue": 98000000000000,
           "net_income": 39000000000000, "total_liabilities": 189200000000,
           "balance": {"assets_end": 289200000000, "equity_end": 100000000000}}
    classes = [{"ticker": "UNIT", "type": "stock", "market_cap": 1000000000000,
                "last_price": 1000, "shares_outstanding": 1000000000}]
    result = fundamentals.issuer_multiples(classes, fin, {}, today=TODAY)
    for metric in ("pe", "pb", "ps", "roe", "roa", "net_margin", "equity_assets", "bvps"):
        assert result[metric]["value"] is None
        assert result[metric]["status"] == "blocked_unit_mismatch"
    assert result["market_cap_issuer"]["value"] == 1000000000000
