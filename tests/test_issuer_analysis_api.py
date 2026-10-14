from __future__ import annotations

import issuer_financials as issuer_sources

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import issuer_analysis_api as subject
from identity.users import WebUser
from datetime import datetime, timezone


_USER = WebUser(id=7, email="analyst@example.test", full_name="Analyst", avatar_data_url=None,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), last_login_at=None, is_active=True)


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
    monkeypatch.setattr(issuer_sources, 'get_securities_map', lambda: securities)
    monkeypatch.setattr(issuer_sources, 'get_company_index', lambda ticker: indexes.get(ticker, {}))
    monkeypatch.setattr(issuer_sources, 'get_company_reports', lambda ticker: [])
    monkeypatch.setattr(issuer_sources, 'get_financials_series', annual)
    monkeypatch.setattr(issuer_sources, 'get_financials_series_quarterly', quarterly)
    monkeypatch.setattr(issuer_sources, 'get_all_ratios', lambda: ratios)
    monkeypatch.setattr(issuer_sources, 'get_all_financials', lambda form="NSBU": latest)
    monkeypatch.setattr(issuer_sources, 'fetch_report_excel_data', excel_data)
    monkeypatch.setattr(issuer_sources, 'get_all_quotes', lambda: quotes)
    monkeypatch.setattr(issuer_sources, 'get_all_trade_stats', lambda: trades)
    monkeypatch.setattr(subject.provenance, "bond_references", lambda: {})
    monkeypatch.setattr(subject.provenance, "bond_coupons", lambda: {})
    monkeypatch.setattr(subject.news_store, "get_news_for_ticker", lambda *args, **kwargs: [])
    monkeypatch.setattr(subject.dividends, "read_snapshot", lambda ticker: [])
    monkeypatch.setattr(subject.corporate_actions, "actions_for", lambda ticker: ())

    app = FastAPI()
    app.include_router(subject.router)
    app.dependency_overrides[subject.auth_access._require_user] = lambda: _USER
    monkeypatch.setattr(subject.auth_limits, "_rate_limiter", subject.auth_limits._SlidingWindowLimiter())
    return TestClient(app)


def _observation(body, metric):
    return next(item for item in body["observations"] if item["metric"] == metric)


@pytest.mark.parametrize("failing_language", ["ru", "uz"])
def test_failed_publication_retries_and_recovers_without_duplicate_reports(client, monkeypatch, failing_language):
    """Use real report preparation and SQLite; fail only the publication write."""
    from reporting import publication, store, worker

    monkeypatch.setattr(publication, "record_analysis", lambda *args, **kwargs: None)
    job_id = store.enqueue("INS", "publication-recovery-test")
    record_report = store.record_report

    def unavailable(report):
        if report["language"] == failing_language:
            raise OSError("simulated publication storage failure")
        return record_report(report)

    with monkeypatch.context() as failing:
        failing.setattr(store, "record_report", unavailable)
        assert worker.run_pending() == 1

    with store.connect() as connection:
        job = dict(connection.execute("SELECT * FROM sector_jobs WHERE id=?", (job_id,)).fetchone())
        assert job["state"] == "retry", "Calculation success must not hide a failed publication"
        assert job["attempts"] == 1
        assert job["error_code"]
        assert connection.execute("SELECT count(*) FROM sector_runs").fetchone()[0] == (0 if failing_language == "ru" else 1)
        connection.execute("UPDATE sector_jobs SET next_attempt='2000-01-01' WHERE id=?", (job_id,))

    assert worker.run_pending() == 1
    assert worker.run_pending() == 0
    with store.connect() as connection:
        job = dict(connection.execute("SELECT * FROM sector_jobs WHERE id=?", (job_id,)).fetchone())
        assert job["state"] == "completed"
        assert job["attempts"] == 2
        assert job["error_code"] is None
        assert connection.execute("SELECT count(*) FROM sector_runs").fetchone()[0] == 2
        assert {row["language"] for row in connection.execute("SELECT * FROM sector_publications")} == {"ru", "uz"}


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
    # «AI-анализ отчётности» (2026-10-12): six blocks, at most 450 words, the
    # card is the one-sentence headline plus the verdict with its reason.
    assert body["word_count"] <= 450
    assert body["text_checks"]["status"] == "passed"
    assert 1 <= body["card_word_count"] <= 45
    assert body["card_text"] == body["short_summary"] == f"{body['headline']} {body['verdict_line']}"
    assert body["abstract"] == body["headline"]
    assert body["narrative_structure"] == "six-blocks-v1"
    ids = [section["id"] for section in body["task1_sections"]]
    assert ids[:2] == ["headline", "key_points"] and ids[-1] == "footnote"
    expected_titles = {
        "ru": ["Главное", "Результаты", "Баланс", "Устойчивость", "Риски и что смотреть дальше"],
        "uz": ["Asosiy", "Natijalar", "Balans", "Barqarorlik", "Xatarlar va nimani kuzatish kerak"],
        "en": ["Key points", "Results", "Balance sheet", "Financial strength", "Risks and what to watch"],
    }
    titled = [section for section in body["task1_sections"] if section["title"]]
    assert [section["title"] for section in titled] == [t for t in expected_titles[lang] if t in {s["title"] for s in titled}]
    assert all(section["number"] and section["text"] for section in titled)
    assert body["sections"] == body["task1_sections"]
    assert "тыс. сум" not in body["text"] and "ming so‘m" not in body["text"] and "thousand UZS" not in body["text"]
    assert len(body["monitoring_points"]) == 2
    assert all(point["current_baseline"]["period"] == body["period"] for point in body["monitoring_points"])
    assert body["verification_summary"]["checked"]
    assert all(item["metric_code"] not in {"current_ratio", "quick_ratio"} for item in body["ratios"])
    assert body["number_references"]
    assert all(item["period"] and item["source"]["document_id"] for item in body["number_references"])
    assert "buy" not in body["text"].lower()


def test_ai_report_summary_defers_the_full_report(client):
    body = client.get(
        "/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true"
    ).json()

    assert body["status"] == "available"
    assert body["deferred_full_report"] is True
    assert body["headline"] == body["card_text"] == body["short_summary"]
    assert body["card_word_count"] <= 40
    assert "sections" not in body
    assert "number_references" not in body


def test_bank_ai_report_summary_uses_bank_metrics_and_keeps_period(client):
    body = client.get(
        "/api/v1/issuers/BANK/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true"
    ).json()

    assert body["status"] == "available"
    assert body["content_status"] == "complete"
    assert body["deferred_full_report"] is True
    assert body["period"] == "2026Q2"
    assert body["availability"]["last_source_period"] == "2026Q2"
    assert "недостаточно" not in body["headline"].lower()


def test_insurance_ai_report_summary_uses_insurance_core_totals(client):
    body = client.get(
        "/api/v1/issuers/INS/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true"
    ).json()

    assert body["status"] == "available"
    assert body["content_status"] == "complete"
    assert body["deferred_full_report"] is True
    assert body["period"] == "2026Q2"
    assert "недостаточно" not in body["headline"].lower()


def test_commodity_exchange_summary_matches_available_full_report(monkeypatch):
    issuer = {"id": "717", "ticker": "URTS", "name": "O'zRTXB", "sector": "finance"}
    metrics = {
        "revenue": 264_737_847,
        "net_income": 221_484_280,
        "total_assets": 7_382_902_408,
        "total_equity": 535_305_257,
        "total_liabilities": 6_847_597_151,
        "revenue_growth_pct": 11.4,
        "net_income_growth_pct": 18.6,
    }
    snapshot = {
        "period": "2026Q2",
        "organization_type": "commodity_exchange",
        "observations": [
            {"metric": metric, "normalized": value}
            for metric, value in metrics.items()
        ],
        "quality": {
            "verification_status": "blocked",
            "data_quality": [{
                "code": "SECTOR_TEMPLATE_MISSING",
                "severity": "blocking",
            }],
        },
        "source_snapshot_hash": "urts-snapshot",
    }
    monkeypatch.setattr(issuer_sources, 'resolve_issuer', lambda _issuer_id: issuer)
    monkeypatch.setattr(issuer_sources, 'financial_snapshot', lambda *_args: snapshot)

    body = subject.issuer_ai_report(
        "URTS", "nsbu", None, "separate", "ru", True,
    )

    assert body["status"] == "available"
    assert body["content_status"] == "complete"
    assert body["deferred_full_report"] is True
    assert body["availability"]["last_successful_period"] == "2026Q2"
    assert "недостаточно" not in body["headline"].lower()


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
    monkeypatch.setattr(issuer_sources, 'get_financials_series_quarterly', lambda ticker, form="NSBU": {"2026Q2": {"revenue": 100.0}})
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
    # A bank publishes its own indicators, never the enterprise form ratios.
    assert body["ratios"]
    assert not {item["metric_code"] for item in body["ratios"]} & {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "current_ratio", "quick_ratio", "absolute_liquidity"}
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
    original = issuer_sources.get_financials_series_quarterly

    def mismatched(ticker, form="NSBU"):
        rows = original(ticker, form)
        if ticker == "FACT":
            rows = {key: dict(value) for key, value in rows.items()}
            rows["2026Q2"]["total_assets"] = 99999
        return rows

    monkeypatch.setattr(issuer_sources, 'get_financials_series_quarterly', mismatched)
    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    assert body["status"] == "quality_blocked"
    assert body["paragraph_count"] == 1
    assert any(item["code"] == "BALANCE_IDENTITY_FAILED" for item in body["data_quality"])
    assert "current ratio" not in body["text"].lower()


def test_missing_filing_returns_coded_unavailable_state(client, monkeypatch):
    monkeypatch.setattr(issuer_sources, 'get_financials_series', lambda ticker, form="NSBU": {})
    monkeypatch.setattr(issuer_sources, 'get_financials_series_quarterly', lambda ticker, form="NSBU": {})

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


_LITE = {"object_type": "issuer", "ids": ["FACT", "FAC2"], "standard": "nsbu", "period": "2026Q2", "metrics": ["revenue"]}


def test_creating_a_comparison_requires_an_account(client):
    client.app.dependency_overrides.clear()
    response = client.post("/api/v1/comparisons", json=_LITE)
    assert response.status_code == 401


def test_free_form_comparison_options_are_size_capped(client):
    response = client.post("/api/v1/comparisons", json={**_LITE, "normalization_options": {"pad": "x" * 5000}})
    assert response.status_code == 422
    peer = {"peer_rule": {"sector": "industry", "pad": "x" * 5000}}
    response = client.post("/api/v1/comparisons", json={**{k: v for k, v in _LITE.items() if k != "ids"}, **peer})
    assert response.status_code == 422


def test_comparison_creation_is_paced_per_account(client, monkeypatch):
    monkeypatch.setattr(subject, "COMPARISON_RATE_LIMIT_PER_MINUTE", 2)
    assert [client.post("/api/v1/comparisons", json=_LITE).status_code for _ in range(3)] == [201, 201, 429]


def test_summary_card_is_the_published_analysis_headline_and_verdict(client, monkeypatch):
    from reporting import store
    published = {
        "narrative_structure": "six-blocks-v1", "period": "2026Q2", "headline_tone": "warning",
        "headline": "Выручка выросла на 9%, но операционная прибыль сократилась на четверть.",
        "verdict_line": "Вердикт: смешанно — выручка растёт, но маржа снижается.",
    }
    published["card_text"] = f"{published['headline']} {published['verdict_line']}"
    monkeypatch.setattr(store, "latest_publication", lambda *args: published)
    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true").json()
    assert body["card_text"] == body["short_summary"] == published["card_text"]
    assert body["verdict_line"] == published["verdict_line"]
    assert body["headline_tone"] == "warning"
    assert body["deferred_full_report"] is True

    # A publication of another period (or the old text structure) is not shown.
    monkeypatch.setattr(store, "latest_publication", lambda *args: {**published, "period": "2026Q1"})
    body = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true").json()
    assert body["card_text"] != published["card_text"]


def test_blocked_filing_shows_a_snapshot_and_one_reason_on_the_card_and_report(client, monkeypatch):
    original = issuer_sources.get_financials_series_quarterly

    def mismatched(ticker, form="NSBU"):
        rows = {key: dict(value) for key, value in original(ticker, form).items()}
        if ticker == "FACT":
            rows["2026Q2"]["total_assets"] = 99999
        return rows

    monkeypatch.setattr(issuer_sources, 'get_financials_series_quarterly', mismatched)
    full = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru").json()
    card = client.get("/api/v1/issuers/FACT/ai-report?standard=nsbu&period=2026Q2&lang=ru&summary=true").json()
    for body in (full, card):
        assert body["status"] == "quality_blocked"
        assert body["headline"].startswith("Срез на 30.06.2026: выручка за период —")
        assert "Анализ не публикуется: баланс в отчёте не сходится на" in body["headline"]
        assert "временно недоступен" not in body["headline"]
        assert body["availability"]["reason_text"].startswith("баланс в отчёте не сходится на")
