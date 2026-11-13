"""Financials settings operations with explicit dependencies."""
from __future__ import annotations

import logging
from catalogue.fields import FIN_MONEY_FIELDS


log = logging.getLogger("collector")


DEFAULT_URL = "https://uzstock.uz"


# The delivery contract follows the financial store, including the current
# section used by ROCE and liquidity. A separate headline-only list silently
# discarded those inputs on every routine refresh.
KEYS = (*FIN_MONEY_FIELDS, "org_type", "balance")
