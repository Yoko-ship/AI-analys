"""Regression cases for comparison, new-quarter discovery and seven-day badges."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone, date
import sqlite3
import json
from pathlib import Path
import pytest

import fundamentals as f
import reports_catalog as rc
from market_comparison import build_market_comparison

FIXTURES = Path(__file__).parent / "fixtures"


def test_comparison_all_88_observed_instruments_preserves_all_616_cells():
    snapshot = json.loads((FIXTURES / "market_88_2026_08_30.json").read_text(encoding="utf8"))
    items = snapshot["items"]
    assert len(items) == 88
    inputs = {"board": snapshot["board"], "securities": {}}
    from market_comparison import METRICS
    checked = 0
    for start in range(0, 88, 4):
        group = items[start:start + 4]
        result = build_market_comparison([r["ticker"] for r in group], inputs, snapshot)["comparison"]
        for expected, actual in zip(group, result["rows"]):
            assert actual["ticker"] == expected["ticker"]
            for key, _, _ in METRICS:
                assert actual[key] == expected[key]["value"]
                assert actual["metric_details"][key] == expected[key]
                checked += 1
    assert checked == 616


@pytest.mark.parametrize("source", json.loads((FIXTURES / "bank_ttm_sources_2026_08_30.json").read_text(encoding="utf8"))["issuers"], ids=lambda s:s["ticker"])
def test_bank_margin_from_three_actual_openinfo_filings(source):
    current, annual, prior = (source[k]["fields"] for k in ("current", "annual", "prior"))
    # All source cells were independently extracted from downloaded workbooks,
    # normalised to UZS, and carry sheet/cell addresses in the fixture.
    fin = {**current, "year": 2026, "quarter": 2, "org_type": "bank",
           "annual": {**annual, "year": 2025, "quarter": 0},
           "prior": {**prior, "year": 2025, "quarter": 2}}
    result = f.issuer_multiples([], fin, {}, today=date(2026,8,31))
    profit = annual["net_income"] + current["net_income"] - prior["net_income"]
    income = sum(annual[k] + current[k] - prior[k] for k in ("revenue", "noninterest_income"))
    assert result["net_margin"]["value"] == pytest.approx(profit / income * 100)


def test_partial_prior_keeps_restatement_and_fills_noninterest():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE catalog_financials(ticker,form,year,quarter,revenue,gross_profit,net_income,operating_income,noninterest_income)")
    conn.execute("INSERT INTO catalog_financials VALUES ('BANK','NSBU',2025,2,100,20,10,12,50)")
    rows = {"BANK": {"year": 2026, "quarter": 2, "prior": {"year": 2025, "quarter": 2, "net_income": 11, "source": "restated"}}}
    rc._attach_prior_interim_companion(conn, rows, "NSBU")
    prior = rows["BANK"]["prior"]
    assert prior["net_income"] == 11
    assert prior["noninterest_income"] == 50
    assert prior["field_sources"]["noninterest_income"] == "catalog_same_interim"
    restored = rc._decode_prior_period(rc._encode_prior_period(prior))
    assert restored["noninterest_income"] == 50
    assert restored["field_sources"] == prior["field_sources"]
    conn.close()


def test_bank_margin_does_not_mix_annual_and_ttm():
    fin = {"year": 2026, "quarter": 2, "org_type": "bank", "revenue": 600,
           "net_income": 90, "noninterest_income": 300,
           "annual": {"year": 2025, "quarter": 0, "revenue": 1000, "net_income": 100, "noninterest_income": 500},
           "prior": {"year": 2025, "quarter": 2, "revenue": 500, "net_income": 50}}
    classes = [{"ticker": "BANK", "market_cap": 2000, "last_price": 2, "shares_outstanding": 1000}]
    result = f.issuer_multiples(classes, fin, {}, today=date(2026, 8, 31))
    assert result["net_margin"]["value"] == pytest.approx(100 / 1500 * 100)
    assert "2025" in result["net_margin"]["base_period"]
    fin["prior"]["noninterest_income"] = 250
    result = f.issuer_multiples(classes, fin, {}, today=date(2026, 8, 31))
    assert result["net_margin"]["value"] == pytest.approx(140 / 1650 * 100)


def test_new_quarter_is_not_blocked_by_fresh_annual_or_old_missing_periods():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""CREATE TABLE catalog_reports(ticker,period_type,year,quarter,report_form,excel_url);
        CREATE TABLE catalog_financials(ticker,form,year,quarter,updated_at);
        INSERT INTO catalog_reports VALUES ('A','annual',2025,0,'NSBU','annual'),('A','quarter',2026,2,'NSBU','new');
        INSERT INTO catalog_financials VALUES ('A','NSBU',2025,0,datetime('now'));""")
    assert rc._fin_candidates(conn, "NSBU", 14, None) == [{"ticker": "A", "year": 2026, "quarter": 2}]
    conn.execute("INSERT INTO catalog_financials VALUES ('A','NSBU',2026,2,datetime('now'))")
    conn.execute("INSERT INTO catalog_reports VALUES ('A','quarter',2024,2,'NSBU','old')")
    assert rc._fin_candidates(conn, "NSBU", 14, None) == []
    conn.close()


def test_badge_expires_exactly_after_seven_days():
    start = datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert rc.report_freshness(start.isoformat(), start + timedelta(days=7, microseconds=-1))["is_new"]
    assert not rc.report_freshness(start.isoformat(), start + timedelta(days=7))["is_new"]
    assert not rc.report_freshness("broken")["is_new"]
    assert not rc.report_freshness(start.isoformat(), start - timedelta(seconds=1))["is_new"]


def test_analysis_badge_tracks_source_not_daily_regeneration(monkeypatch, tmp_path):
    import analysis_monitor as monitor
    import admin_control.adapters as adapters
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "analysis.db"))
    monkeypatch.setattr(adapters, "record_analysis", lambda report: None)
    report = {"issuer": {"id": "1", "ticker": "A"}, "language": "ru", "standard": "nsbu",
              "status": "available", "period": "2026Q2", "financial_as_of": "2026-06-30",
              "source_snapshot_hash": "source-one", "version": "v1", "availability": {},
              "generated_at": "2026-08-20T10:00:00+00:00"}
    first = monitor.record_report(deepcopy(report))
    second = monitor.record_report({**deepcopy(report), "version": "v2", "generated_at": "2026-08-25T10:00:00+00:00"})
    assert first["new_until"] == second["new_until"] == "2026-08-27T10:00:00+00:00"
    changed = monitor.record_report({**deepcopy(report), "version": "v3", "source_snapshot_hash": "source-two", "generated_at": "2026-08-25T10:00:00+00:00"})
    assert changed["new_until"] == "2026-09-01T10:00:00+00:00"


def test_comparison_http_uses_market_and_no_llm_quota_for_numbers(monkeypatch):
    import api
    import audit
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    import io
    from openpyxl import load_workbook
    inputs = {"board": [{"ticker": t, "last_trade_date": "2026-08-28", "last_price": 10, "market_cap": 1000, "shares_outstanding": 100} for t in ("A", "B")],
              "securities": {t: {"name": "Company " + t, "type": "stock"} for t in ("A", "B")},
              "financials": {t: {"year": 2025, "quarter": 0, "revenue": 100, "net_income": 20} for t in ("A", "B")},
              "ratios": {}, "listings": {}, "stats": {}}
    async def market_inputs(): return inputs
    monkeypatch.setattr(api, "_market_inputs", market_inputs)
    monkeypatch.setattr(audit, "blocking_index", lambda: {"A": ["pe"]})
    monkeypatch.setattr(api, "_enforce_llm_quota", lambda user: pytest.fail("Numeric comparison must not require AI quota"))
    client = TestClient(api.app)
    api.app.dependency_overrides[api._require_user] = lambda: SimpleNamespace(to_public_dict=lambda: {"id": "test"})
    try:
        response = client.post("/api/compare", json={"companies": ["A", "B"], "include_ai_summary": False})
        assert response.status_code == 200, response.text
        result = response.json()
        a, b = result["comparison"]["rows"]
        assert a["pe"] is None and a["metric_details"]["pe"]["status"] == "audit_blocked"
        assert b["pe"] == 50
        from analysis_service import build_comparison_excel, build_comparison_pdf
        wb = load_workbook(io.BytesIO(build_comparison_excel(result)))
        assert wb["Показатели"].freeze_panes == "B2"
        assert any("audit_blocked" in str(cell.value) for row in wb["Показатели"] for cell in row)
        assert build_comparison_pdf(result).startswith(b"%PDF")
    finally:
        api.app.dependency_overrides.pop(api._require_user, None)


def test_comparison_preserves_market_blocks_classes_periods_and_zero():
    base = {"issuer": "bank", "issuer_classes": ["A", "AP"], "org_type": "bank",
            "base_period": "TTM2026Q2", "balance_period": "2026Q2",
            "market_cap_issuer": {"value": 10000},
            "pe": {"value": None, "status": "audit_blocked", "note": "share check"},
            "ps": {"value": None, "status": "not_applicable"},
            "roa": {"value": 0, "status": "ok"}}
    items = [{**deepcopy(base), "ticker": t, "share_class": cls, "market_cap_class": cap}
             for t, cls, cap in [("A", "ordinary", 8000), ("AP", "preferred", 2000)]]
    inputs = {"board": [{"ticker": t, "name": "Bank", "last_price": 10, "last_trade_date": "2026-08-28"} for t in ("A", "AP")], "securities": {}}
    result = build_market_comparison(["a", "AP"], inputs, {"items": items})["comparison"]
    assert len(result["rows"]) == 2
    assert result["rows"][0]["pe"] is None
    assert result["rows"][0]["roa"] == 0
    assert result["tables"]["market"]["rows"][0]["ps"]["status"] == "not_applicable"
    assert result["rows"][1]["market_cap_class"] == 2000
    assert result["rows"][1]["market_cap_issuer"] == 10000
    assert result["warnings"] and not result["ranking"]
    assert not result["tables"]["market"]["allow_average"]
    with pytest.raises(ValueError):
        build_market_comparison(["A", "a"], inputs, {"items": items})
    with pytest.raises(ValueError):
        build_market_comparison(["A", "UNKNOWN"], inputs, {"items": items})
    inputs["board"].append({"ticker": "BOND", "name": "Unpublished bond"})
    with pytest.raises(ValueError):
        build_market_comparison(["A", "Unpublished bond"], inputs, {"items": items})


def test_comparison_financial_cells_keep_individual_periods_and_validation():
    fin = {"year": 2026, "quarter": 2, "revenue": 100, "net_income": 10,
           "field_periods": {"revenue": "2025A"},
           "balance": {"assets_end": 200, "equity_end": 80}}
    items = [{"ticker": t, "issuer": t, "validation": {"findings": [
        {"field": "net_income", "reason": "Unit mismatch"}]}} for t in ("A", "B")]
    inputs = {"board": [], "securities": {}, "financials": {"A": fin, "B": fin}}
    comparison = build_market_comparison(["A", "B"], inputs, {"items": items})["comparison"]
    cell = comparison["tables"]["market"]["rows"][0]
    assert cell["revenue"]["raw"] == 100
    assert cell["revenue"]["base_period"] == "2025A"
    assert cell["total_assets"]["base_period"] == f.period_label(fin)
    assert cell["net_income"]["raw"] is None
    assert cell["net_income"]["status"] == "audit_blocked"
    assert "Unit mismatch" in comparison["rows"][0]["net_income_basis"]
