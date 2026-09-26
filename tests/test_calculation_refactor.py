"""Capture complete calculation contracts before splitting the large workflows."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import random

import pytest
import analyzer
import financial_analysis.metrics as financial_analysis_metrics
import sector_analysis
import financial_analysis.sector_report as financial_analysis_sector_report

FIXTURE = Path(__file__).with_name("fixtures") / "calculation_contracts.json"


def metric_cases():
    yield "empty", [], []
    yield "missing", [{"year": 2024}], []
    rng = random.Random(260926)
    for case in range(12):
        annual = []
        for year in range(2020, 2025):
            revenue = (year - 2018) * (1000 if case % 2 else 1_000_000_000)
            assets = revenue * 3
            annual.append({
                "year": year, "revenue": revenue, "total_assets": assets,
                "equity": 0 if case == 0 else assets * (.4 if case < 6 else -.2),
                "net_income": revenue * rng.choice([-.2, 0, .05, .2]),
                "current_assets": assets * .3, "current_liabilities": assets * .2,
                "long_term_debt": 0 if case == 1 else assets * .4,
                "cash": assets * .05, "inventory": assets * .1,
                "accounts_receivable": assets * .15, "accounts_payable": assets * .1,
                "ebit": revenue * .2, "interest_expense": 0 if case == 2 else revenue * .04,
                "gross_profit": revenue * .4, "cogs": revenue * .6,
                "retained_earnings": assets * .1,
            })
        quarterly = [dict(annual[-1], quarter=f"Q{q}", year=y, revenue=100 * q, net_income=q * 10)
                     for y in (2023, 2024) for q in (1, 2, 3, 4)] if case > 3 else []
        yield f"case-{case}", annual, quarterly


def sector_cases():
    for organization, oked in [("non_financial", "24100"), ("bank", "64190"),
                               ("insurance", "65120"), ("microfinance", "64920")]:
        for variant in ("valid", "missing_source", "unbalanced"):
            snapshot = {
                "organization_type": organization, "standard": "nsbu", "scope": "separate",
                "period": "2026Q2", "period_basis": "cumulative_ytd",
                "previous_comparable_period": "2025Q2",
                "current_values": {"total_assets": 1000, "total_equity": 400,
                                   "total_liabilities": 600, "revenue": 500, "net_income": 80,
                                   "operating_income": 100, "cash": 50},
                "previous_values": {"revenue": 400, "net_income": 40, "operating_income": 80},
                "opening_values": {"total_assets": 900, "total_equity": 400, "total_liabilities": 500},
                "source": {"document_id": "fixture", "url": "https://example.test/filing.pdf"},
                "quality": {"data_quality": []},
            }
            if variant == "missing_source":
                snapshot["source"] = {}
            if variant == "unbalanced":
                snapshot["current_values"]["total_assets"] = 1234
            issuer = {"id": "1", "ticker": "TEST", "name": "Test issuer", "oked_code": oked}
            for lang in ("ru", "uz", "en"):
                yield f"{organization}-{variant}-{lang}", snapshot, issuer, lang


@pytest.mark.parametrize("name,annual,quarterly", list(metric_cases()))
def test_metric_results_are_preserved(name, annual, quarterly):
    original = deepcopy((annual, quarterly))
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["metrics"][name]
    assert financial_analysis_metrics.compute_metrics(annual, quarterly) == expected
    assert (annual, quarterly) == original


@pytest.mark.parametrize("name,snapshot,issuer,lang", list(sector_cases()))
def test_sector_results_are_preserved(name, snapshot, issuer, lang):
    original = deepcopy(snapshot)
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))["sectors"][name]
    assert financial_analysis_sector_report.make_report(snapshot, issuer, lang, today=date(2026, 8, 30)) == expected
    assert snapshot == original
