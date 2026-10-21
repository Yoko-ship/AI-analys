"""Indicators for banks, microfinance and insurers.

The ratio calculator used to know only the enterprise form's line codes, so
every bank, microfinance organization and insurer published an empty ratio
list and the AI report showed no financial indicators for them.  These tests
pin the rule that closed it — every organization type has an indicator set or
a stated reason it has none — and check the indicators against the real HMKB
(bank) and UZAS (insurer) filings.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

import financial_analysis.sector_calculations as calc
import financial_analysis.sector_report as financial_analysis_sector_report
import financial_analysis.sector_templates as financial_analysis_sector_templates
from sector_report_service import map_special_lines

TODAY = date(2026, 8, 30)
ROOT = Path(__file__).parent
FILINGS = json.loads((ROOT / "fixtures/sector_v22_filings.json").read_text(encoding="utf8"))
ENTERPRISE_CODES = set(calc.METHODS)


def _report(ticker):
    filing = FILINGS[ticker]
    data = {
        "organization_type": filing["organization_type"], "standard": "nsbu", "scope": "separate",
        "period": "2026Q2", "period_basis": "cumulative_ytd", "previous_comparable_period": "2025Q2",
        "current_values": {}, "previous_values": {}, "opening_values": {},
        "source": filing["source"], "quality": {"data_quality": []},
    }
    map_special_lines(data, filing["workbook"], filing["organization_type"])
    report = financial_analysis_sector_report.make_report(data, filing["issuer"], "ru", TODAY, filing["workbook"])
    assert report["status"] == "available", report["data_quality"]
    return report


def _ratios(report):
    return {item["metric_code"]: item for item in report["ratios"]}


def test_every_organization_type_has_indicators_or_a_reason():
    for org in financial_analysis_sector_templates.FINANCIAL_TYPES:
        assert (org in calc.FINANCIAL_RATIOS) != (org in calc.RATIOS_NOT_APPLICABLE), org
    for codes in calc.FINANCIAL_RATIOS.values():
        assert set(codes) <= set(calc.FINANCIAL_METHODS)


def test_every_indicator_the_server_emits_has_a_label_on_the_page():
    page = (ROOT.parent / "frontend/src/analysis/VerifiedReport.jsx").read_text(encoding="utf8")
    copy = page[page.index("const RATIO_COPY = {"):page.index("};", page.index("const RATIO_COPY = {"))]
    labelled = set(re.findall(r"^\s*([A-Za-z0-9_]+):\s*\[", copy, re.M))
    assert ENTERPRISE_CODES | set(calc.FINANCIAL_METHODS) <= labelled


def test_bank_publishes_bank_indicators_from_its_own_filing():
    ratios = _ratios(_report("HMKB"))
    assert not set(ratios) & ENTERPRISE_CODES
    assert set(ratios) == set(calc.FINANCIAL_RATIOS["bank"])
    # The same figures the analysis text states in words.
    assert ratios["loans_to_deposits"]["value"] == pytest.approx(1.724, abs=0.001)
    assert ratios["loans_to_deposits"]["unit"] == "ratio"
    assert ratios["loan_reserve_coverage"]["value"] == pytest.approx(1.65, abs=0.01)
    assert ratios["equity_to_assets"]["value"] == pytest.approx(18.6, abs=0.1)
    # A half-year return in the annual rate (ТЗ data rule 6).
    assert ratios["roe"]["value"] == pytest.approx(970.0 / 7674.7 * 100 * 2, abs=0.2)
    assert ratios["roe"]["annualised"] is True
    assert ratios["provisions_to_net_interest_income"]["value"] == pytest.approx(27.5, abs=0.1)
    # Never a prudential norm: the filing does not disclose its components.
    assert all(item["benchmark_type"] is None for item in ratios.values())
    assert all(item["calculation_status"] == "verified" for item in ratios.values())


def test_insurer_publishes_insurance_indicators_without_a_loss_ratio():
    ratios = _ratios(_report("UZAS"))
    assert set(ratios) == set(calc.FINANCIAL_RATIOS["insurance"])
    assert ratios["reinsurer_share_of_reserves"]["value"] == pytest.approx(156.5 / 261.0 * 100, abs=0.1)
    assert not any("loss" in code for code in ratios)


def test_a_negative_cost_line_withholds_its_share_but_a_loss_is_stated():
    values = {"net_income": -50, "total_assets": 1000, "total_equity": 100,
              "credit_loss_provisions": -3277, "net_interest_income_before_provisions": 607}
    ratios = {r["metric_code"]: r for r in calc.financial_ratios(values, {}, {}, "bank", "nsbu", "2026Q3")}
    assert ratios["provisions_to_net_interest_income"]["value"] is None
    assert ratios["provisions_to_net_interest_income"]["calculation_status"] == "missing_or_invalid_components"
    # Nine months of a loss, in the annual rate: −5% × 12/9.
    assert ratios["roa"]["value"] == pytest.approx(-5 * 12 / 9)
    assert ratios["roe"]["value"] == pytest.approx(-50 * 12 / 9)


def test_microfinance_takes_no_deposits_and_enterprises_keep_their_codes():
    assert not {"loans_to_deposits", "liquid_to_deposits"} & set(calc.FINANCIAL_RATIOS["microfinance"])
    assert calc.financial_ratios({"net_income": 1, "total_assets": 10}, {}, {}, "non_financial", "nsbu", "2026Q1") == []
