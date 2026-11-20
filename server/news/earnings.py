"""As-filed figures for private, manually published issuer earnings posts."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

import data_quality
from financial_columns import matrix, observations, source_store

METRICS = {
    "net_income", "revenue", "selling_expense", "total_assets", "total_equity",
    "retained_earnings", "bank_borrowings_long", "other_borrowings_short",
}


def periods(ticker, issuer_id):
    held = data_quality.held_public_periods(ticker, "NSBU")
    docs = source_store.read(issuer_id, standard="NSBU", scope="separate")
    result = []
    for doc in docs:
        end = date.fromisoformat(doc["period_end"])
        quarter = (end.month + 2) // 3
        period = str(end.year) if quarter == 4 else f"{end.year}Q{quarter}"
        if period in held or end >= date.today() or doc.get("currency") != "UZS":
            continue
        rows = [r for r in observations.nsbu([doc]) if r["role"] == "PRIMARY"]
        observations.check(rows)
        groups = defaultdict(list)
        for row in rows:
            if row["metric_id"] in METRICS and row["unit"] == "UZS_thousand":
                groups[row["metric_id"]].append(row)
        values, sources = {}, set()
        profit_mismatch = False
        for metric, items in groups.items():
            cell = matrix.choose(items)
            if cell.get("value") is None or not cell.get("source_url"):
                continue
            # The editorial desk may quote an issuer's literal profit line with
            # its discrepancy disclosed. Other blocked amounts stay unavailable.
            filed_profit = metric == "net_income" and cell.get("reason") == "SOURCE_NET_PROFIT_MISMATCH"
            if cell["quality"] not in {"valid", "warn"} and not filed_profit:
                continue
            profit_mismatch |= filed_profit
            values[metric] = Decimal(cell["value"]) * 1000
            sources.add(cell["source_url"])
        if "net_income" in values or "revenue" in values:
            result.append(dict(end=end.isoformat(), values=values, sources=sorted(sources),
                               profit_mismatch=profit_mismatch))
    return sorted(result, key=lambda row: row["end"], reverse=True)
