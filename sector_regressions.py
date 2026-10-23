"""Small release gate executed before rule activation and publication.

Expected results are fixed acceptance examples, not copied computed outputs.
The larger pytest suite exercises persistence, adapters, failures and the UI.
"""
from functools import lru_cache
from datetime import date
from pathlib import Path

import sector_analysis as core
import financial_analysis.sector_calculations as financial_analysis_sector_calculations
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_report as financial_analysis_sector_report
import financial_analysis.sector_templates as financial_analysis_sector_templates


def code_fingerprint():
    paths = ("issuer_financials.py", "sector_analysis.py", "sector_report_service.py", "fund_analysis.py",
             "bond_quality.py", "sector_regressions.py", "reporting/store.py",
             "reporting/publication.py", "config/verified_fund_reports.json",
             "config/verified_sector_classifications.json")
    return financial_analysis_sector_numbers.digest({name: (Path(__file__).parent / name).read_bytes().hex() for name in paths})


@lru_cache(maxsize=4)
def _run(fingerprint):
    checks = []

    def check(code, condition):
        checks.append({"code": code, "status": "passed" if condition else "failed"})

    check("null_is_not_zero", financial_analysis_sector_numbers.total(1, None) is None and financial_analysis_sector_numbers.ratio(1, 0) is None)
    check("balance_absolute_and_relative", financial_analysis_sector_calculations.balance_gate({"total_assets": 1000000, "total_equity": 400000, "total_liabilities": 599998})["status"] == "failed")
    check("bank_routing", financial_analysis_sector_templates.resolve_template({"oked_code": "64190"}, "bank")["selected_template"] == "bank")
    check("trade_oked_routing", financial_analysis_sector_templates.resolve_template({"oked_code": "47110"})["selected_template"] == "trade")
    check("transport_oked_routing", financial_analysis_sector_templates.resolve_template({"oked_code": "49410"})["selected_template"] == "transport")
    check("telecom_oked_routing", financial_analysis_sector_templates.resolve_template({"oked_code": "61100"})["selected_template"] == "telecom")
    check("catalog_sector_fallback", financial_analysis_sector_templates.resolve_template({"sector": "mining"})["selected_template"] == "extractive")
    check("unknown_oked", financial_analysis_sector_templates.resolve_template({})["selected_template"] == "generic_nsbu")
    check("bank_no_enterprise_ratios", not financial_analysis_sector_calculations.enterprise_ratios({}, "bank", "nsbu", "2026Q1"))
    check("sign_change", financial_analysis_sector_numbers.change(-10, 20)["change_value"] == -30 and financial_analysis_sector_numbers.change(-10, 20)["base_effect"])
    lines = {k: {"raw_current": v} for k, v in {
        "form2:c270": "80", "form2:c240": "100", "form1:c400": "1000",
        "form1:c480": "400", "form1:c570": "50", "form1:c580": "50",
        "form1:c320": "50", "form1:c370": "25", "form1:c210": "129", "form1:c600": "200",
    }.items()}
    ratios = {r["metric"]: r["value"] for r in financial_analysis_sector_calculations.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q1")}
    check("P1", ratios["P1"] == 8)
    check("P3", ratios["P3"] == 20)
    check("P4", ratios["P4"] == 25)
    check("quick_liquidity", ratios["quick_ratio"] == 1.02)
    bank = financial_analysis_sector_report.make_report(
        {
            "organization_type": "bank", "standard": "nsbu", "period": "2026Q1",
            "period_basis": "quarter", "scope": "standalone", "display_divisor": 1000,
            "source": {"url": "https://example.test/bank-q1.xlsx", "unit": "thousand UZS"},
            "current_values": {
                "interest_income": 3112700, "interest_expenses": 2080900,
                "noninterest_income": 1353200, "noninterest_expenses": 310000,
                "operating_expenses": 545600, "profit_before_tax": 968500,
                "net_income": 846400, "total_assets": 20000000,
                "total_liabilities": 17000000, "total_equity": 3000000,
                "loan_portfolio": 12000000, "customer_funds": 11000000,
            },
            "previous_values": {"net_income": 700000, "interest_income": 2800000},
            "opening_values": {"total_assets": 19000000, "total_liabilities": 16200000, "total_equity": 2800000},
        },
        {"id": "bank-fixture", "ticker": "BANK", "name": "Fixture Bank"},
        lang="ru", today=date(2026, 4, 10),
    )
    company = financial_analysis_sector_report.make_report(
        {
            "organization_type": "non_financial", "standard": "nsbu", "period": "2026Q1",
            "period_basis": "quarter", "scope": "standalone", "display_divisor": 1000,
            "source": {"url": "https://example.test/company-q1.xlsx", "unit": "thousand UZS"},
            "current_values": {
                "revenue": 36093389, "cost_of_sales": 21000000, "gross_profit": 15093389,
                "period_expenses": 8000000, "operating_income": 770288,
                "profit_before_tax": 650000, "net_income": 572101,
                "cash": 900000, "receivables": 2400000, "inventories": 3100000,
                "total_assets": 18000000, "total_liabilities": 11000000, "total_equity": 7000000,
            },
            "previous_values": {"revenue": 16238868, "net_income": 833000, "operating_income": 814595},
            "opening_values": {"cash": 700000, "receivables": 2000000, "inventories": 2800000,
                               "total_assets": 16500000, "total_liabilities": 10000000, "total_equity": 6500000},
        },
        {"id": "company-fixture", "ticker": "COMP", "name": "Fixture Company", "oked_code": "10"},
        lang="ru", today=date(2026, 4, 10),
    )
    # The written analysis must pass every publication check of the text
    # specification on both fixtures, and keep its six-block order.
    for name, report in (("bank", bank), ("company", company)):
        text_checks = report.get("text_checks") or {}
        check(f"{name}_published", report.get("status") == "available")
        for item in text_checks.get("checks") or [{"code": "missing", "status": "failed"}]:
            check(f"{name}_{item['code']}", item["status"] != "failed")
        ids = [section.get("id") for section in report.get("sections", [])]
        check(f"{name}_block_order", ids[:2] == ["headline", "key_points"] and ids[-1] == "footnote"
              and ids == sorted(ids, key=["headline", "key_points", "results", "balance", "strength", "risks", "footnote"].index))
        check(f"{name}_verdict_reason", bool(report.get("verdict", {}).get("reason")) and "—" in (report.get("verdict_line") or ""))
        check(f"{name}_card_is_headline", (report.get("card_text") or "").startswith(report.get("headline") or "\0"))
    company_text = company.get("text") or ""
    check("company_no_profile_meta_text", "Аналитический профиль" not in company_text and "Для производства ключевой вопрос" not in company_text)
    check("company_amounts_scaled", "млн сум" in company_text and "тыс. сум" not in company_text)
    check("company_high_risk_requires_attention", company["verdict"]["status"] == "attention" and bool(company["verdict"]["reason"]))
    return {"status": "passed" if all(c["status"] == "passed" for c in checks) else "failed",
            "code_fingerprint": fingerprint, "checks": checks}


def run():
    return _run(code_fingerprint())
