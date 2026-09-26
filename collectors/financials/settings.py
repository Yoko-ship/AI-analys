"""Financials settings operations with explicit dependencies."""
from __future__ import annotations

import logging


log = logging.getLogger("collector")


DEFAULT_URL = "https://uzstock.uz"


KEYS = ("revenue", "gross_profit", "cash", "total_liabilities", "net_income",

        "operating_income", "operating_expenses", "noninterest_income", "org_type", "balance")
