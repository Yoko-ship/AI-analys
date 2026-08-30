"""Small release gate executed before rule activation and publication.

Expected results are fixed acceptance examples, not copied computed outputs.
The larger pytest suite exercises persistence, adapters, failures and the UI.
"""
from functools import lru_cache
from pathlib import Path

import sector_analysis as core


def code_fingerprint():
    paths = ("sector_analysis.py", "sector_report_service.py", "fund_analysis.py",
             "bond_quality.py", "sector_regressions.py", "config/verified_fund_reports.json",
             "config/verified_sector_classifications.json")
    return core.digest({name: (Path(__file__).parent / name).read_bytes().hex() for name in paths})


@lru_cache(maxsize=4)
def _run(fingerprint):
    checks = []

    def check(code, condition):
        checks.append({"code": code, "status": "passed" if condition else "failed"})

    check("null_is_not_zero", core.total(1, None) is None and core.ratio(1, 0) is None)
    check("balance_absolute_and_relative", core.balance_gate({"total_assets": 1000000, "total_equity": 400000, "total_liabilities": 599998})["status"] == "failed")
    check("bank_routing", core.resolve_template({"oked_code": "64190"}, "bank")["selected_template"] == "bank")
    check("unknown_oked", core.resolve_template({})["selected_template"] == "generic_nsbu")
    check("bank_no_enterprise_ratios", not core.enterprise_ratios({}, "bank", "nsbu", "2026Q1"))
    check("sign_change", core.change(-10, 20)["change_value"] == -30 and core.change(-10, 20)["base_effect"])
    lines = {k: {"raw_current": v} for k, v in {
        "form2:c270": "80", "form2:c240": "100", "form1:c400": "1000",
        "form1:c480": "400", "form1:c570": "50", "form1:c580": "50",
        "form1:c320": "50", "form1:c370": "25", "form1:c210": "129", "form1:c600": "200",
    }.items()}
    ratios = {r["metric"]: r["value"] for r in core.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q1")}
    check("P1", ratios["P1"] == 8)
    check("P3", ratios["P3"] == 20)
    check("P4", ratios["P4"] == 25)
    check("quick_liquidity", ratios["quick_ratio"] == 1.02)
    return {"status": "passed" if all(c["status"] == "passed" for c in checks) else "failed",
            "code_fingerprint": fingerprint, "checks": checks}


def run():
    return _run(code_fingerprint())
