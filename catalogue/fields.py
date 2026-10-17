"""Field units and data contracts shared by catalogue readers and collectors."""
from __future__ import annotations

import catalogue.codecs as catalogue_codecs


_MIN_PLAUSIBLE = 10_000


_FIN_FIELDS = ("revenue", "gross_profit", "cash", "total_liabilities", "net_income",

               "operating_income", "operating_expenses", "total_assets", "total_equity")


_FIN_CURRENT_FIELDS = ("current_assets", "current_liabilities", "inventories")


_RATIO_FIELDS = ("roe", "roa", "net_profit_margin", "debt_to_equity", "current_ratio",
                 "quick_ratio", "debt_ratio", "total_asset_turnover",
                 "return_to_capital_employed", "total_equity", "total_assets")


NSBU_THOUSANDS_UZS = 1000.0


_IFRS_BANK_FIELDS = ("interest_income", "interest_expense")


# Every income line of the commercial form №2 (стр.010+090+110): the top line
# of an investment fund or holding, which sells nothing (catalogue.parsing).
_FIN_INCOME_FIELDS = ("total_income",)

FIN_MONEY_FIELDS = (_FIN_FIELDS + ("noninterest_income",) + _FIN_CURRENT_FIELDS + _IFRS_BANK_FIELDS
                    + _FIN_INCOME_FIELDS)


RATIO_MONEY_FIELDS = ("total_equity", "total_assets")


# The lines a filed statement is judged by, in thousands of UZS.
FILING_MONEY_KEYS = (
    "revenue", "net_income", "total_assets", "total_equity", "total_liabilities",
    "gross_profit", "operating_income", "operating_expenses", "cash",
)


def filing_problem(values: dict | None) -> dict | None:
    """Why a parsed filing carries no usable statement, or None when it does.

    Three shapes, each seen on openinfo (docs/catalog-terminal/02-data.md,
    R-D1): every line nought (UZNGP's 2024/2025 workbooks, KSCM 2021); a
    balance whose total is nought or negative (SQBN's 2024 annual states
    «Итого активов 0»); and the form's line numbers typed into the amount
    column (the same SQBN filing: «Итого процентных доходов 1», «Чистая
    прибыль 13»; UZNGP 2021–2023: 10, 270, 400) — every amount below the
    plausibility floor. The same rule judges a filing when it is loaded and a
    stored row when it is read, so the two can never disagree.
    """
    if not values:
        return {"code": "missing"}
    money = [catalogue_codecs._financials_num(values.get(key)) for key in FILING_MONEY_KEYS]
    money = [value for value in money if value is not None]
    if not money or not any(money):
        return {"code": "empty_filing"}
    assets = catalogue_codecs._financials_num(values.get("total_assets"))
    if assets is not None and assets <= 0:
        return {"code": "no_balance"}
    if max(abs(value) for value in money) < _MIN_PLAUSIBLE:
        return {"code": "implausible_scale"}
    return None


# The balance lines a filing's «Итого активов 0» leaves without a figure.
UNFILLED_BALANCE_KEYS = ("total_assets", "total_equity", "equity", "total_liabilities", "cash",
                      "current_assets", "current_liabilities", "inventories")


def usable_filing(values: dict | None) -> tuple[dict, dict | None]:
    """A filing's figures with what it does not state removed, and why.

    No usable statement at all: every amount goes. A nought balance beside a
    real income statement (ORGS 2025, TNBN 2017): the income lines stand and
    the balance is a gap, not a company with nothing on it. Measured on every
    period production serves (2026-10-17): the smallest real filing states
    20 682 thousand UZS, the junk ones 777 and 918, so the 10 000 floor has
    room on both sides.
    """
    values = dict(values or {})
    problem = filing_problem(values)
    if not problem or problem["code"] == "missing":
        return values, None
    keys = UNFILLED_BALANCE_KEYS if problem["code"] == "no_balance" else FIN_MONEY_FIELDS + ("equity",)
    for key in keys:
        if key in values:
            values[key] = None
    return values, problem


BALANCE_MONEY_KEYS = catalogue_codecs._BALANCE_KEYS


FACT_MONEY_FIELDS = ("net_revenue", "net_profit", "total_assets", "total_liabilities",
                     "total_equity")


FACT_PERCENT_FIELDS = ("roe", "roa", "debt_ratio")


FACT_SHARE_FIELDS = ()
