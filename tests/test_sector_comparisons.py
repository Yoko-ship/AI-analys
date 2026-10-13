"""Where a comparison comes from, and when a column is no comparison at all.

The audit of the published analyses found whole bank balance sheets «down
100%» (BRBN, SQBN: the current detail column parsed as zeros), whole opening
columns of zeros (INFB, IPKY), a single loan portfolio of zero beside 1.5 trn
of assets (GRBK), and banks with no income comparison because their income
form has one column.  A blank column is now no data, and the comparison comes
from the issuer's other filings: the same period a year earlier for results,
the previous annual filing for the start-of-year balance.
"""
from __future__ import annotations

from copy import deepcopy

import financial_analysis.sector_inputs as inputs
import issuer_financials as financials
import sector_report_service as service


def _bank_workbook(rows):
    return {"balance": {"sheets": [{"sheet": "bank", "table_rows": [
        {"row": index, "label": label, "numeric_values": [prior, current]} for index, (label, prior, current) in enumerate(rows, 1)
    ]}]}, "income": {"sheets": []}}


def _bank_snapshot():
    return {"current_values": {"total_assets": 41000, "total_equity": 7000, "total_liabilities": 34000},
            "previous_values": {}, "opening_values": {}}


def test_blank_column_rule():
    assert inputs.blank_column([0, 0, "0.00", None])
    assert inputs.blank_column([None, None])
    assert not inputs.blank_column([0, 0, 15])
    assert not inputs.blank_column([-3])


def test_a_current_column_of_zeros_is_not_a_balance_sheet_of_zeros():
    # BRBN 2026Q2: every detail line 0 at the period end, the opening filled.
    data = _bank_snapshot()
    service.map_special_lines(data, _bank_workbook([
        ("Кредиты и лизинговые операции", 25498, 0), ("Срочные депозиты", 14387, 0),
        ("Кассовая наличность", 899, 0), ("К получению из других банков", 4462, 0),
    ]), "bank")
    assert "loan_portfolio" not in data["current_values"]
    assert "cash" not in data["current_values"]
    assert data["opening_values"]["loan_portfolio"] == 25498


def test_an_opening_column_of_zeros_keeps_the_catalogue_opening():
    # INFB/IPKY 2026Q2: the opening column, totals included, is all zeros.
    data = _bank_snapshot()
    data["opening_values"] = {"total_assets": 39000}
    service.map_special_lines(data, _bank_workbook([
        ("Кредиты и лизинговые операции", 0, 18454), ("Кассовая наличность", 0, 1747), ("Итого активов", 0, 41000),
    ]), "bank")
    assert data["opening_values"] == {"total_assets": 39000}
    assert data["current_values"]["loan_portfolio"] == 18454
    assert data["comparison_sources"]["opening_from_filing"] is False


def test_a_bank_loan_portfolio_of_zero_beside_assets_is_a_missed_line():
    # GRBK 2026Q2: loans 0 against 1.5 trn at the start of the year.
    data = _bank_snapshot()
    service.map_special_lines(data, _bank_workbook([
        ("Кредиты и лизинговые операции", 1506, 0), ("Кассовая наличность", 300, 420),
    ]), "bank")
    assert "loan_portfolio" not in data["current_values"]
    assert data["current_values"]["cash"] == 420
    assert data["opening_values"]["loan_portfolio"] == 1506


def test_a_real_zero_line_in_a_filled_column_stays_zero():
    data = _bank_snapshot()
    service.map_special_lines(data, _bank_workbook([
        ("Кредиты и лизинговые операции", 1506, 1700), ("Сберегательные депозиты", 0, 0), ("Срочные депозиты", 10, 12),
    ]), "bank")
    assert data["current_values"]["savings_deposits"] == 0


def test_company_blank_prior_column_keeps_the_previous_filing():
    snapshot = {"organization_type": "non_financial", "current_values": {"revenue": 500},
                "previous_values": {"revenue": 400}, "opening_values": {"total_assets": 900},
                "source_lines": {"form2:c010": {"raw_current": "500", "raw_previous": "0"},
                                 "form2:c270": {"raw_current": "80", "raw_previous": "0"},
                                 "form1:c400": {"raw_current": "1000", "raw_previous": "950"}}}
    values, previous, opening, _ = inputs.prepare_inputs(snapshot)
    assert previous["revenue"] == 400          # the zero column did not erase it
    assert opening["total_assets"] == "950"     # a filled column is still the filing's own


def test_bank_income_comparison_comes_from_last_years_same_period(monkeypatch):
    snapshot = {"period": "2026Q2", "standard": "nsbu", "previous_comparable_period": "2025Q2",
                "template_resolution": {"selected_template": "bank"},
                "current_values": {"interest_income": 2994, "net_income": 970, "total_assets": 41000, "loan_portfolio": 29000},
                "previous_values": {"net_income": 808}, "opening_values": {"total_assets": 38600, "loan_portfolio": 26380}}
    prior = {"ok": True, "balance": {"sheets": []}, "income": {"sheets": [{"sheet": "p", "table_rows": [
        {"row": 1, "label": "Итого процентных доходов", "source_cells": ["Итого процентных доходов", 2500]},
    ]}]}}
    calls = []
    monkeypatch.setattr(financials, "fetch_report_excel_data", lambda ticker, form, year, quarter: calls.append((year, quarter)) or deepcopy(prior))
    reports = [{"period": "2025Q2", "excel_url": "https://example.org/2025q2.xlsx"}]
    service.fill_from_earlier_filings({"ticker": "BANK"}, snapshot, reports, "bank")
    assert calls == [(2025, 2)]
    assert snapshot["previous_values"]["interest_income"] == 2500
    assert snapshot["previous_values"]["net_income"] == 808          # never overwritten
    assert snapshot["comparison_sources"]["previous_fallback"] == "2025Q2"


def test_no_earlier_filing_no_fallback(monkeypatch):
    snapshot = {"period": "2026Q2", "standard": "nsbu", "previous_comparable_period": "2025Q2",
                "template_resolution": {"selected_template": "bank"},
                "current_values": {"interest_income": 2994}, "previous_values": {}, "opening_values": {}}
    monkeypatch.setattr(financials, "fetch_report_excel_data", lambda *a: (_ for _ in ()).throw(AssertionError("no fetch")))
    service.fill_from_earlier_filings({"ticker": "BANK"}, snapshot, [], "bank")
    assert snapshot["previous_values"] == {}
    assert "previous_fallback" not in snapshot["comparison_sources"]


def test_start_of_year_balance_comes_from_the_previous_annual_filing(monkeypatch):
    issuer = {"id": "1", "ticker": "FACT", "name": "Fact", "sector": "industry", "isin": "UZ1"}
    quarterly = {"2026Q2": {"revenue": 500, "net_income": 80, "total_assets": 1000, "total_equity": 400, "total_liabilities": 600},
                 "2025Q2": {"revenue": 400, "net_income": 60}}
    annual = {"2025": {"revenue": 900, "total_assets": 950, "total_equity": 390, "total_liabilities": 560, "cash": 40}}
    monkeypatch.setattr(financials, "get_financials_series_quarterly", lambda *a: quarterly)
    monkeypatch.setattr(financials, "get_financials_series", lambda *a: annual)
    monkeypatch.setattr(financials, "report_rows", lambda *a: [])
    monkeypatch.setattr(financials, "get_all_ratios", lambda: {})
    monkeypatch.setattr(financials, "classify_organization", lambda *a: "non_financial")
    snapshot = financials.financial_snapshot(issuer, "nsbu", "2026Q2", "separate")
    assert snapshot["opening_values"] == {"total_assets": 950, "total_equity": 390, "total_liabilities": 560, "cash": 40}
    assert snapshot["comparison_sources"] == {"previous_period": "2025Q2", "previous_available": True,
                                              "opening_period": "2025", "opening_available": True}
