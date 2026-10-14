from __future__ import annotations

import company_imports as subject_company_imports
import reports_catalog as subject_reports_catalog
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots
import catalogue.sources as catalogue_sources
import server.catalog.routes as subject_server_catalog_routes

import asyncio

import api
import reports_catalog
import catalogue.ratios as catalogue_ratios
import catalogue.snapshots as catalogue_snapshots
import catalogue.sources as catalogue_sources


def test_cached_period_builds_ratios_from_verified_values(monkeypatch):
    monkeypatch.setattr(
        catalogue_snapshots,
        "get_financials_series",
        lambda ticker, form: {
            "2025": {
                "revenue": 1_000_000.0,
                "net_income": 100_000.0,
                "total_assets": 2_000_000.0,
                "total_equity": 800_000.0,
                "total_liabilities": 1_200_000.0,
            }
        },
    )
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda ticker, form: {"2025"})

    result = catalogue_ratios.get_cached_catalog_period("BECM", "NSBU", 2025)

    assert result["has_data"] is True
    assert result["source_values"]["equity"] == 800_000.0
    assert result["metrics"] == {
        "ROA": 5.0,
        "ROE": 12.5,
        "net_margin": 10.0,
        "debt_ratio": 60.0,
        "debt_to_equity": 1.5,
    }


def test_cached_dynamics_decumulates_quarterly_flows(monkeypatch):
    monkeypatch.setattr(
        catalogue_snapshots,
        "get_financials_series",
        lambda ticker, form: {
            "2024": {"revenue": 500_000.0, "net_income": 50_000.0},
            "2025": {"revenue": 700_000.0, "net_income": 70_000.0},
        },
    )
    monkeypatch.setattr(
        catalogue_snapshots,
        "get_financials_series_quarterly",
        lambda ticker, form: {
            "2025Q1": {"revenue": 100_000.0, "net_income": 10_000.0},
            "2025Q2": {"revenue": 260_000.0, "net_income": 35_000.0},
        },
    )
    monkeypatch.setattr(catalogue_ratios, "_filed_periods", lambda ticker, form: None)

    result = catalogue_ratios.build_cached_catalog_dynamics("BECM", "NSBU")

    assert result["years"] == [2024, 2025]
    assert result["quarterly"][0]["revenue"] == 100_000.0
    assert result["quarterly"][1]["revenue"] == 160_000.0
    assert result["quarterly"][1]["net_income"] == 25_000.0
    assert result["quarterly"][1]["revenue_ytd"] == 260_000.0


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
    monkeypatch.setattr(catalogue_sources, 'fetch_report_excel_data', no_upstream)
    monkeypatch.setattr(catalogue_ratios, 'get_cached_catalog_period', cached_period)
    request = subject_server_catalog_routes.CatalogAnalyzeRequest(
        ticker="BECM", year=2025, form="NSBU", analysis_type="financial", language="ru"
    )

    result = asyncio.run(subject_server_catalog_routes.api_catalog_analyze(request, object()))

    assert result["data_source"] == "verified_cache"
    assert result["sector"] == "manufacturing"
    assert result["sections"]["ЧТО_С_ДЕНЬГАМИ"]


def test_finance_catalog_analysis_uses_the_same_verified_cache(monkeypatch):
    """Banks used to take a path that re-downloaded openinfo and ran them
    through the industrial form (HTTP 500 for SQBN/HMKB/ALSM). Every issuer now
    reads the cache, and a bank is analysed as a bank."""
    import catalogue.organization as catalogue_organization
    import server.auth.limits as auth_limits

    def no_upstream(*args, **kwargs):
        raise AssertionError("catalogue analysis must not download filings")

    def no_quota(*args, **kwargs):
        raise AssertionError("deterministic catalogue analysis spends no LLM quota")

    def cached_period(ticker, form, year, quarter):
        values = {"revenue": 5_174_244_859.0, "net_income": 1_704_969_118.0,
                  "total_assets": 35_911_649_727.0, "total_equity": 6_704_709_904.0,
                  "total_liabilities": 29_206_939_823.0, "gross_profit": 3_956_102_734.0,
                  "operating_expenses": 1_890_152_285.0}
        return catalogue_ratios._cached_catalog_ratio_payload(values) | {"period": str(year)}

    monkeypatch.setattr(subject_company_imports, "approved_metadata_map", lambda: {})
    monkeypatch.setattr(catalogue_sources, "fetch_report_excel_data", no_upstream)
    monkeypatch.setattr(auth_limits, "_enforce_llm_quota", no_quota)
    monkeypatch.setattr(catalogue_ratios, "get_cached_catalog_period", cached_period)
    monkeypatch.setattr(catalogue_organization, "filing_org_type", lambda ticker: "bank")
    for analysis_type in ("financial", "swot", "recommendation", "ratio"):
        request = subject_server_catalog_routes.CatalogAnalyzeRequest(
            ticker="IPTB", year=2025, form="NSBU", analysis_type=analysis_type, language="ru")
        result = asyncio.run(subject_server_catalog_routes.api_catalog_analyze(request, object()))
        assert result["data_source"] == "verified_cache"
        assert result["org_kind"] == "bank"
        assert "cost_to_income" in result["metrics"] and "net_margin" not in result["metrics"]
