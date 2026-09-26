"""Financial history input shared by independent rule groups.

The legacy missing/zero conventions and financial assumptions are preserved;
changing them is a separate calculation-policy change, not this refactor.
"""
from dataclasses import dataclass
import math


def value(record, key, default=None):
    result = record.get(key, default)
    return result if result and not (isinstance(result, float) and math.isnan(result)) else default


@dataclass(frozen=True)
class FinancialHistory:
    annual: list
    quarterly: list

    @property
    def latest(self):
        return self.annual[-1]

    @property
    def previous(self):
        return self.annual[-2] if len(self.annual) >= 2 else {}

    @property
    def revenue_growth(self):
        first = value(self.annual[0], "revenue", 0)
        last = value(self.latest, "revenue", 0)
        return ((last / first) - 1) * 100 if first and first > 0 else 0

    @property
    def net_margin(self):
        revenue = value(self.latest, "revenue", 0)
        return value(self.latest, "net_income", 0) / revenue if revenue else 0
