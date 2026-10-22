"""Portfolio valuations from the existing collector's stored market data only."""
from datetime import date
from decimal import Decimal, InvalidOperation

from identity.portfolio_math import ZERO, today_tashkent
from server.market.dates import _iso_trade_date, _as_utc_iso


def _quote(price, day, updated_at, source, today):
    try:
        price = Decimal(str(price))
        day = date.fromisoformat(_iso_trade_date(day) or "")
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not price.is_finite() or price <= 0 or day > today:
        return None
    return {"last_price": price, "price_date": day.isoformat(),
            "days_since_trade": (today - day).days, "price_source": source,
            "quote_updated_at": _as_utc_iso(updated_at)}


def value_portfolio(ledger, *, securities, listings, quotes, stats, today=None):
    today = today or today_tashkent()
    items = []
    total_cost = priced_value = priced_cost = ZERO
    priced_count = 0
    for held in ledger["items"]:
        ticker = held["ticker"]
        security, listing = securities.get(ticker, {}), listings.get(ticker, {})
        isin = security.get("isin") or listing.get("isin")
        candidates = []
        # Ascending preference: a settled quote wins a same-session execution
        # summary, while a newer execution beats yesterday's official close.
        if security.get("type") == "stock":
            for record, field, day_field, source in (
                (listing, "last_price", "last_trade_date", "stored_listing"),
                (stats.get(isin, {}), "close_price", "trade_date", "stored_executions"),
                (quotes.get(isin, {}), "close_price", "trade_date", "stored_quote"),
            ):
                # Never borrow another issue's price merely because its issuer
                # or ticker matches; ordinary and preferred shares are distinct.
                if record.get("isin") and isin and record["isin"] != isin:
                    continue
                candidate = _quote(record.get(field), record.get(day_field), record.get("updated_at"), source, today)
                if candidate:
                    candidates.append(candidate)
        selected = max(enumerate(candidates), key=lambda p: (p[1]["price_date"], p[0]))[1] if candidates else {}
        price = selected.get("last_price")
        cost = held["cost_value"]
        market_value = held["quantity"] * price if price is not None else None
        pnl = market_value - cost if market_value is not None else None
        total_cost += cost
        if market_value is not None:
            priced_count += 1
            priced_value += market_value
            priced_cost += cost
        items.append({**held, "company_name": security.get("name") or listing.get("name") or ticker,
                      "isin": isin, "last_price": None, "price_date": None, "days_since_trade": None,
                      "quote_updated_at": None, "price_source": None, **selected,
                      "market_value": market_value, "unrealized_pnl": pnl,
                      "unrealized_pnl_pct": pnl / cost * 100 if pnl is not None and cost else None,
                      "valuation_status": "AVAILABLE" if price is not None else "NO_DATA"})
    complete = priced_count == len(items)
    for item in items:
        item["allocation_pct"] = item["market_value"] / priced_value * 100 if complete and priced_value else None
    unrealized = priced_value - total_cost if complete else None
    return {**ledger, "items": items, "count": len(items), "priced_count": priced_count,
            "valuation_complete": complete, "market_value": priced_value if complete else None,
            "cost_value": total_cost, "priced_market_value": priced_value,
            "priced_unrealized_pnl": priced_value - priced_cost, "unrealized_pnl": unrealized,
            "total_pnl": unrealized + ledger["realized_pnl"] + ledger["dividend_income"] if complete else None,
            "currency": "UZS", "cost_method": "weighted_average", "price_basis": "last confirmed exchange trade"}
