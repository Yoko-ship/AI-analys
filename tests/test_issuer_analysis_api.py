from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import issuer_analysis_api as subject


@pytest.fixture()
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setenv("SECTOR_ANALYSIS_DB", str(tmp_path / "sector.sqlite3"))
    securities = {
        "BANK": {"ticker": "BANK", "isin": "UZBANK", "name": "Test Bank", "sector": "finance", "type": "stock"},
        "INS": {"ticker": "INS", "isin": "UZINS", "name": "Test Insurance", "sector": "finance", "type": "stock"},
        "FACT": {"ticker": "FACT", "isin": "UZFACT", "name": "Test Factory", "sector": "industry", "type": "stock"},
        "FAC2": {"ticker": "FAC2", "isin": "UZFAC2", "name": "Factory Two", "sector": "industry", "type": "stock"},
        "FAC3": {"ticker": "FAC3", "isin": "UZFAC3", "name": "Factory Three", "sector": "industry", "type": "stock"},
    }
    indexes = {
        ticker: {
            "ticker": ticker,
            "company_name": row["name"],
            "sector": row["sector"],
            "org_id": str(index + 1),
            "tickers": [ticker],
            "availability": {
                "NSBU": {
                    "quarter": [{"year": 2026, "quarter": 2, "published_at": "2026-07-30T09:00:00", "pdf_url": f"https://source/{ticker}/2026Q2.pdf"}],
                    "annual": [{"year": 2025, "quarter": 0, "published_at": "2026-03-28T09:00:00", "pdf_url": f"https://source/{ticker}/2025.pdf"}],
                },
                "MSFO": {
                    "quarter": [],
                    "annual": [{"year": 2025, "quarter": 0, "published_at": "2026-05-20T09:00:00", "pdf_url": f"https://source/{ticker}/ifrs-2025.pdf"}],
                },
            },
        }
        for index, (ticker, row) in enumerate(securities.items())
    }
    base = {"BANK": 100.0, "INS": 250.0, "FACT": 200.0, "FAC2": 300.0, "FAC3": 400.0}

    def annual(ticker, form="NSBU"):
        if form == "MSFO":
            return {"2025": {"revenue": base[ticker] * 10, "net_income": base[ticker], "total_assets": base[ticker] * 30, "total_equity": base[ticker] * 8, "total_liabilities": base[ticker] * 22}}
        return {
            "2024": {"revenue": base[ticker] * 8, "net_income": base[ticker] * 0.7},
            "2025": {"revenue": base[ticker] * 10, "net_income": base[ticker], "gross_profit": base[ticker] * 3, "operating_income": base[ticker] * 2, "cash": base[ticker] / 2, "total_assets": base[ticker] * 30, "total_equity": base[ticker] * 8, "total_liabilities": base[ticker] * 22, "roe": 12 + base[ticker] / 100, "roa": 4, "debt_ratio": 73.33},
        }

    def quarterly(ticker, form="NSBU"):
        if form != "NSBU":
            return {}
        return {
            "2025Q1": {"revenue": base[ticker] * 2, "net_income": base[ticker] * 0.15},
            "2025Q2": {"revenue": base[ticker] * 4, "net_income": base[ticker] * 0.35},
            "2026Q1": {"revenue": base[ticker] * 2.5, "net_income": base[ticker] * 0.2},
            "2026Q2": {"revenue": base[ticker] * 5, "net_income": base[ticker] * 0.5, "gross_profit": base[ticker] * 2, "operating_income": base[ticker] * 1.4, "cash": None, "total_assets": base[ticker] * 32, "total_equity": base[ticker] * 9, "total_liabilities": base[ticker] * 23},
        }

    ratios = {
        ticker: {
            "roe": 12 + base[ticker] / 100,
            "roa": 4,
            "debt_ratio": 72,
            "debt_to_equity": 2.5,
            "current_ratio": 1.4,
            "quick_ratio": 1.1,
            "nim": 5.2 if ticker == "BANK" else None,
            "period": "2026Q2",
            "periods": {},
        }
        for ticker in securities
    }
    latest = {
        ticker: {"org_type": "bank" if ticker == "BANK" else "insurance" if ticker == "INS" else "jsc", "year": 2026, "quarter": 2}
        for ticker in securities
    }

    def excel_data(ticker, form, year, quarter):
        assert ticker == "INS"
        rows = [
            {"label": "Всего по активу баланса (стр.130+480)", "numeric_values": [490, 0, 8000]},
            {"label": "Итого по разделу I (стр.500+510+520-530+540+550+560)", "numeric_values": [570, 0, 2250]},
            {"label": "Страховые резервы, всего (стр.590+600+610+620+630+640+650+660)", "numeric_values": [580, 0, 1800]},
            {"label": "Доля перестраховщиков в страховых резервах, Всего(стр.680+690+700+710)", "numeric_values": [670, 0, 800]},
            {"label": "Итого по разделу II (стр.580-670)", "numeric_values": [720, 0, 1000]},
            {"label": "Итого по разделу III (стр.730+930)", "numeric_values": [1190, 0, 4750]},
        ]
        parsed = {"sheets": [{"table_rows": rows}]}
        return {"ok": True, "income": parsed, "balance": parsed, "error": None}
    quotes = {
        row["isin"]: {"close_price": base[ticker] * 10, "change_percent": index + 1, "trade_date": "2026-08-26", "turnover": base[ticker] * 100}
        for index, (ticker, row) in enumerate(securities.items())
    }
    trades = {
        row["isin"]: {"total_value": base[ticker] * 100, "trade_count": index + 2}
        for index, (ticker, row) in enumerate(securities.items())
    }

    monkeypatch.setattr(subject, "_RUN_DB_PATH", tmp_path / "comparison.sqlite3")
    monkeypatch.setattr(subject, "get_securities_map", lambda: securities)
    monkeypatch.setattr(subject, "get_company_index", lambda ticker: indexes.get(ticker, {}))
    monkeypatch.setattr(subject, "get_company_reports", lambda ticker: [])
    monkeypatch.setattr(subject, "get_financials_series", annual)
    monkeypatch.setattr(subject, "get_financials_series_quarterly", quarterly)
    monkeypatch.setattr(subject, "get_all_ratios", lambda: ratios)
    monkeypatch.setattr(subject, "get_all_financials", lambda form="NSBU": latest)
    monkeypatch.setattr(subject, "fetch_report_excel_data", excel_data)
    monkeypatch.setattr(subject, "get_all_quotes", lambda: quotes)
    monkeypatch.setattr(subject, "get_all_trade_stats", lambda: trades)
    monkeypatch.setattr(subject.provenance, "bond_references", lambda: {})
    monkeypatch.setattr(subject.provenance, "bond_coupons", lambda: {})
    monkeypatch.setattr(subject.news_store, "get_news_for_ticker", lambda *args, **kwargs: [])
    monkeypatch.setattr(subject.dividends, "read_snapshot", lambda ticker: [])
    monkeypatch.setattr(subject.corporate_actions, "actions_for", lambda ticker: ())

    app = FastAPI()
    app.include_router(subject.router)
    return TestClient(app)


def _observation(body, metric):
    return next(item for item in body["observations"] if item["metric"] == metric)


def test_financial_layers_are_separate_and_missing_is_not_zero(client):
    response = client.get("/api/v1/issuers/FACT/financial-analysis?standard=nsbu&period=2026Q2")
    assert response.status_code == 200
    body = response.json()
    assert body["standard"] == "nsbu"
    assert body["period"] == "2026Q2"
    assert body["previous_comparable_period"] == "2025Q2"
    assert body["period_basis"] == "cumulative_ytd"
    assert _observation(body, "cash")["raw"] is None
    assert _observation(body, "cash")["quality"] == "missing"
    assert _observation(body, "revenue")["raw"] == pytest.approx(1000.0)
    assert _observation(body, "revenue")["normalized"] == pytest.approx(1000.0)
    assert _observation(body, "revenue_growth_pct")["raw"] == pytest.approx(25.0)
    assert _observation(body, "revenue")["source"]["url"].endswith("2026Q2.pdf")
    assert client.get("/api/v1/issuers/FACT/financial-analysis?standard=ifrs&period=2026Q2").status_code == 422


def test_profile_uses_fresh_quarter_and_keeps_two_freshness_states(client):
    body = client.get("/api/v1/issuers/FACT/profile").json()
    assert body["key_metrics"][0]["period"] == "2026Q2"
    assert {row["standard"] for row in body["report_freshness"]} == {"nsbu", "ifrs"}
    assert all(row["latest_period"] for row in body["report_freshness"])
    assert body["source_snapshot_hash"]


def test_curated_share_action_is_exposed_with_its_real_fields(client, monkeypatch):
    action = subject.corporate_actions.ShareAction("2026-01-15", 2.0, "split", "https://source/action")
    monkeypatch.setattr(subject.corporate_actions, "actions_for", lambda ticker: (action,))
    body = client.get("/api/v1/issuers/FACT/events").json()
    event = next(item for item in body["items"] if item["category"] == "share_count_change")
    assert event["effective_date"] == "2026-01-15"
    assert event["factor"] == 2.0
    assert event["source_url"] == "https://source/action"


@pytest.mark.parametrize("lang", ["ru", "uz", "en"])
def test_complete_ai_report_meets_length_and_traceability_contract(client, lang):
    body = client.get(f"/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang={lang}").json()
    assert body["status"] == "available"
    assert body["content_status"] == "complete"
    assert body["headline"]
    assert len(body["headline"].split()) <= 40
    assert body["headline_tone"] in {"positive", "warning", "danger", "neutral"}
    assert 3 <= body["paragraph_count"] <= 7
    assert 200 <= body["word_count"] <= 250
    assert 1 <= body["card_word_count"] <= 40
    assert body["card_text"] == body["short_summary"]
    assert body["abstract"] == body["headline"]
    assert [section["id"] for section in body["sections"]] == [
        "methodology", "financial_results", "balance_sheet", "risks", "conclusion",
    ]
    assert all(section["number"] and section["title"] and section["text"] for section in body["sections"])
    assert len(body["monitoring_points"]) == 2
    assert all(point["current_baseline"]["period"] == body["period"] for point in body["monitoring_points"])
    assert body["verification_summary"]["checked"]
    assert all(item["metric_code"] not in {"current_ratio", "quick_ratio"} for item in body["ratios"])
    assert body["number_references"]
    assert all(item["period"] and item["source"]["document_id"] for item in body["number_references"])
    assert "buy" not in body["text"].lower()


def test_mixed_sector_metric_is_blocked_before_ranking(client):
    response = client.post("/api/v1/comparisons", json={
        "object_type": "issuer",
        "ids": ["BANK", "FACT"],
        "standard": "nsbu",
        "period": "2026Q2",
        "metrics": ["revenue", "current_ratio"],
    })
    assert response.status_code == 201
    body = response.json()
    current = next(column for column in body["table"]["columns"] if column["metric"] == "current_ratio")
    assert current["blocked"] is True
    assert all(item["rank"] is None for item in current["values"])
    assert any(warning["code"] == "metric_not_comparable" for warning in body["warnings"])
    assert any(warning["code"] == "percentile_requires_three" for warning in body["warnings"])
    assert client.get(f"/api/v1/comparisons/{body['run_id']}").json()["snapshot_hash"] == body["snapshot_hash"]


def test_three_object_run_has_reproducible_table_csv_pdf_and_summary(client):
    response = client.post("/api/v1/comparisons", json={
        "object_type": "issuer",
        "ids": ["FACT", "FAC2", "FAC3"],
        "standard": "nsbu",
        "period": "2026Q2",
        "metrics": ["revenue", "net_income", "roe_pct"],
    })
    assert response.status_code == 201
    body = response.json()
    revenue = next(column for column in body["table"]["columns"] if column["metric"] == "revenue")
    assert next(item for item in revenue["values"] if item["object_id"] == "FAC3")["rank"] == 1
    assert all(item["percentile"] is not None for item in revenue["values"])
    assert any(item["metric"] == "revenue" and item["object_ids"] == ["FAC3"] for item in body["summary"]["leaders"])
    csv_response = client.get(f"/api/v1/comparisons/{body['run_id']}/export.csv")
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbf")
    assert b"raw,normalized,rank,percentile" in csv_response.content
    pdf_response = client.get(f"/api/v1/comparisons/{body['run_id']}/report.pdf")
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF")
    assert len(body["charts"]) <= 2


def test_short_report_does_not_pad_missing_data(client, monkeypatch):
    monkeypatch.setattr(subject, "get_financials_series_quarterly", lambda ticker, form="NSBU": {"2026Q2": {"revenue": 100.0}})
    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    assert body["status"] == "quality_blocked"
    assert body["verified_facts"] == []
    assert body["analytical_issues"] == []
    assert body["content_status"] == "shortened"
    assert body["shortened_reason"] == "insufficient_traceable_metrics"
    assert body["headline_tone"] == "neutral"
    assert body["headline"]
    assert body["paragraph_count"] < 6
    assert body["word_count"] < 300


def test_bank_report_uses_bank_template_and_never_industrial_liquidity(client):
    body = client.get("/api/v1/issuers/BANK/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    assert body["status"] == "available"
    assert body["sector_template_code"] == "bank"
    assert body["period_basis"] == "cumulative_ytd"
    assert body["balance_check"]["status"] == "passed"
    assert "regulatory_compliance" not in body
    assert not body["ratios"]
    forbidden = ("cfo", "capex", "fcf", "current ratio", "коэффициент текущей ликвидности", "валовая маржа", "cet1", "lcr", "regulatory_compliance")
    assert not any(token in body["text"].lower() for token in forbidden)


def test_insurance_reserves_are_separate_and_included_in_liabilities(client):
    body = client.get("/api/v1/issuers/INS/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    facts = {item["metric"]: item["value"] for item in body["verified_facts"]}
    assert body["status"] == "available"
    assert body["sector_template_code"] == "insurance"
    assert facts["gross_insurance_reserves"] == pytest.approx(1800)
    assert facts["reinsurer_share_in_reserves"] == pytest.approx(800)
    assert facts["net_insurance_reserves"] == pytest.approx(1000)
    assert facts["other_liabilities"] == pytest.approx(4750)
    assert facts["total_liabilities"] == pytest.approx(5750)
    assert body["balance_check"]["status"] == "passed"
    assert "коэффициент текущей ликвидности" not in body["text"].lower()


def test_balance_mismatch_blocks_text_generation(client, monkeypatch):
    original = subject.get_financials_series_quarterly

    def mismatched(ticker, form="NSBU"):
        rows = original(ticker, form)
        if ticker == "FACT":
            rows = {key: dict(value) for key, value in rows.items()}
            rows["2026Q2"]["total_assets"] = 99999
        return rows

    monkeypatch.setattr(subject, "get_financials_series_quarterly", mismatched)
    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    assert body["status"] == "quality_blocked"
    assert body["paragraph_count"] == 1
    assert any(item["code"] == "BALANCE_IDENTITY_FAILED" for item in body["data_quality"])
    assert "current ratio" not in body["text"].lower()


def test_missing_filing_returns_coded_unavailable_state(client, monkeypatch):
    monkeypatch.setattr(subject, "get_financials_series", lambda ticker, form="NSBU": {})
    monkeypatch.setattr(subject, "get_financials_series_quarterly", lambda ticker, form="NSBU": {})

    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&lang=ru").json()

    assert body["status"] == "no_source"
    assert body["report"]["status"] == "no_source"
    assert body["short_summary"] is None
    assert body["paragraph_count"] == 1
    assert "отчётность НСБУ не найдена" in body["headline"]


def test_bond_comparison_with_no_cashflows_never_publishes_ytm(client, monkeypatch):
    references = {
        "BOND1": {"isin": "UZBOND1", "issuer": "Issuer One", "nominal": 100_000, "coupon_rate": 24, "maturity_date": None, "source_url": "https://source/bond1"},
        "BOND2": {"isin": "UZBOND2", "issuer": "Issuer Two", "nominal": 100_000, "coupon_rate": 25, "maturity_date": None, "source_url": "https://source/bond2"},
    }
    monkeypatch.setattr(subject.provenance, "bond_references", lambda: references)
    response = client.post("/api/v1/comparisons", json={
        "object_type": "bond",
        "ids": ["BOND1", "BOND2"],
        "metrics": ["coupon_rate_pct", "ytm_pct", "duration_years"],
    })
    assert response.status_code == 201
    body = response.json()
    for metric in ("ytm_pct", "duration_years"):
        column = next(item for item in body["table"]["columns"] if item["metric"] == metric)
        assert all(value["raw"] is None and value["rank"] is None for value in column["values"])
    assert any(warning["code"] == "metric_unavailable" and warning.get("metric") == "ytm_pct" for warning in body["warnings"])
