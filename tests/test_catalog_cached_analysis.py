from __future__ import annotations

import company_imports as subject_company_imports
import reports_catalog as subject_reports_catalog
import server.catalog.routes as subject_server_catalog_routes

import asyncio

import api
import reports_catalog


def test_cached_period_builds_ratios_from_verified_values(monkeypatch):
    monkeypatch.setattr(
        reports_catalog,
        "get_financials_series",
        lambda ticker, form: {
            "2025": {
                "revenue": 1_000.0,
                "net_income": 100.0,
                "total_assets": 2_000.0,
                "total_equity": 800.0,
                "total_liabilities": 1_200.0,
            }
        },
    )

    result = reports_catalog.get_cached_catalog_period("BECM", "NSBU", 2025)

    assert result["has_data"] is True
    assert result["source_values"]["equity"] == 800.0
    assert result["metrics"] == {
        "ROA": 5.0,
        "ROE": 12.5,
        "net_margin": 10.0,
        "debt_ratio": 60.0,
        "debt_to_equity": 1.5,
    }


def test_cached_dynamics_decumulates_quarterly_flows(monkeypatch):
    monkeypatch.setattr(
        reports_catalog,
        "get_financials_series",
        lambda ticker, form: {
            "2024": {"revenue": 500.0, "net_income": 50.0},
            "2025": {"revenue": 700.0, "net_income": 70.0},
        },
    )
    monkeypatch.setattr(
        reports_catalog,
        "get_financials_series_quarterly",
        lambda ticker, form: {
            "2025Q1": {"revenue": 100.0, "net_income": 10.0},
            "2025Q2": {"revenue": 260.0, "net_income": 35.0},
        },
    )

    result = reports_catalog.build_cached_catalog_dynamics("BECM", "NSBU")

    assert result["years"] == [2024, 2025]
    assert result["quarterly"][0]["revenue"] == 100.0
    assert result["quarterly"][1]["revenue"] == 160.0
    assert result["quarterly"][1]["net_income"] == 25.0
    assert result["quarterly"][1]["revenue_ytd"] == 260.0


def test_nonfinance_catalog_analysis_never_downloads_openinfo(monkeypatch):
    def no_upstream(*args, **kwargs):
        raise AssertionError("non-finance catalog analysis must use the local cache")

    def cached_period(ticker, form, year, quarter):
        values = {
            "revenue": 1_000.0 if year == 2025 else 800.0,
            "net_income": 100.0 if year == 2025 else 80.0,
            "total_assets": 2_000.0,
            "total_equity": 800.0,
            "total_liabilities": 1_200.0,
        }
        return {
            "period": str(year),
            "has_data": True,
            "source_values": {**values, "equity": values["total_equity"]},
            "all_values": values,
            "metrics": {"ROA": 5.0, "ROE": 12.5, "net_margin": 10.0,
                        "debt_ratio": 60.0, "debt_to_equity": 1.5},
        }

    monkeypatch.setattr(subject_company_imports, "approved_metadata_map", lambda: {})
    monkeypatch.setattr(subject_reports_catalog, 'fetch_report_excel_data', no_upstream)
    monkeypatch.setattr(subject_reports_catalog, 'get_cached_catalog_period', cached_period)
    request = subject_server_catalog_routes.CatalogAnalyzeRequest(
        ticker="BECM", year=2025, form="NSBU", analysis_type="financial", language="ru"
    )

    result = asyncio.run(subject_server_catalog_routes.api_catalog_analyze(request, object()))

    assert result["data_source"] == "verified_cache"
    assert result["sector"] == "manufacturing"
    assert result["sections"]["ЧТО_С_ДЕНЬГАМИ"]


def test_finance_catalog_analysis_keeps_existing_upstream_path(monkeypatch):
    calls = []

    def upstream(*args, **kwargs):
        calls.append(args)
        return {"ok": True, "income": None, "balance": None}

    monkeypatch.setattr(subject_company_imports, "approved_metadata_map", lambda: {})
    monkeypatch.setattr(subject_reports_catalog, 'fetch_report_excel_data', upstream)
    request = subject_server_catalog_routes.CatalogAnalyzeRequest(
        ticker="IPTB", year=2025, form="NSBU", analysis_type="ratio", language="ru"
    )

    result = asyncio.run(subject_server_catalog_routes.api_catalog_analyze(request, object()))

    assert len(calls) == 2
    assert "data_source" not in result

