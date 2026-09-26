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

FIN_MONEY_FIELDS = _FIN_FIELDS + ("noninterest_income",) + _FIN_CURRENT_FIELDS + _IFRS_BANK_FIELDS


RATIO_MONEY_FIELDS = ("total_equity", "total_assets")


BALANCE_MONEY_KEYS = catalogue_codecs._BALANCE_KEYS


FACT_MONEY_FIELDS = ("net_revenue", "net_profit", "total_assets", "total_liabilities",
                     "total_equity")


FACT_PERCENT_FIELDS = ("roe", "roa", "debt_ratio")


FACT_SHARE_FIELDS = ()
