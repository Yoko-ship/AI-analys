"""Decimal, average-cost accounting for a user's manually recorded shares.

An opening balance has no invented purchase date. Dated records follow in
calendar order, with insertion sequence breaking ties within a day. Dividends
are actual receipts, not inferred entitlements from the disclosure calendar.
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
import re
from zoneinfo import ZoneInfo


ZERO = Decimal(0)
FIELDS = ("ticker", "kind", "trade_date", "quantity", "price", "fees", "amount", "note")


def today_tashkent():
    return datetime.now(ZoneInfo("Asia/Tashkent")).date()


def normalize_transaction(payload, *, stored=False):
    row = {key: payload.get(key) for key in FIELDS}
    row["ticker"] = str(row["ticker"] or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{0,39}", row["ticker"]):
        raise ValueError("INVALID_TICKER")
    kind = row["kind"]
    if kind not in {"buy", "sell", "dividend", "opening"}:
        raise ValueError("INVALID_TRANSACTION_KIND")
    for key in ("quantity", "price", "fees", "amount"):
        try:
            number = Decimal(str(row[key] if row[key] is not None else 0))
        except (InvalidOperation, ValueError):
            raise ValueError("INVALID_NUMBER") from None
        if (not number.is_finite() or number < 0 or number > Decimal("1e12")
                or (not stored and number.as_tuple().exponent < -6)):
            raise ValueError("INVALID_NUMBER")
        row[key] = number
    if kind == "dividend":
        if row["amount"] <= 0 or row["quantity"] or row["price"] or row["fees"] > row["amount"]:
            raise ValueError("INVALID_DIVIDEND")
    elif row["quantity"] <= 0 or row["amount"]:
        raise ValueError("INVALID_QUANTITY")
    if kind == "opening":
        if row["trade_date"] is not None or row["fees"]:
            raise ValueError("INVALID_OPENING")
    else:
        try:
            day = date.fromisoformat(str(row["trade_date"]))
        except (ValueError, TypeError):
            raise ValueError("INVALID_DATE") from None
        if not date(1900, 1, 1) <= day <= today_tashkent():
            raise ValueError("INVALID_DATE")
        row["trade_date"] = day.isoformat()
    row["note"] = str(row["note"] or "").strip()
    if len(row["note"]) > 1000:
        raise ValueError("NOTE_TOO_LONG")
    return row


def calculate_ledger(transactions):
    """Replay already validated records, retaining closed-position income."""
    holdings = {}
    realized = dividends = ZERO
    openings = set()
    ordered = sorted(transactions, key=lambda r: (str(r.get("trade_date") or ""), r.get("sequence", 0)))
    # Keep intermediate ratios at high precision; never round cost per share
    # before allocating basis. A full sale releases the exact remaining basis.
    with localcontext() as ctx:
        ctx.prec = 50
        for raw in ordered:
            row = normalize_transaction(raw, stored=True)
            ticker, kind = row["ticker"], row["kind"]
            held = holdings.setdefault(ticker, dict(ticker=ticker, quantity=ZERO, cost_value=ZERO))
            qty, price, fees = row["quantity"], row["price"], row["fees"]
            if kind == "opening":
                if ticker in openings:
                    raise ValueError("DUPLICATE_OPENING")
                openings.add(ticker)
            if kind in {"opening", "buy"}:
                held["quantity"] += qty
                held["cost_value"] += qty * price + fees
            elif kind == "sell":
                if qty > held["quantity"]:
                    raise ValueError(f"INSUFFICIENT_SHARES: {ticker} ({row['trade_date']})")
                basis = (held["cost_value"] if qty == held["quantity"]
                         else held["cost_value"] * qty / held["quantity"])
                realized += qty * price - fees - basis
                held["quantity"] -= qty
                held["cost_value"] -= basis
            else:
                dividends += row["amount"] - fees
        items = []
        for ticker, held in sorted(holdings.items()):
            if held["quantity"] > 0:
                items.append({**held, "average_cost": held["cost_value"] / held["quantity"], "currency": "UZS"})
        return {"items": items, "realized_pnl": realized, "dividend_income": dividends}


def json_values(value):
    """Transmit exact monetary decimals as strings, including PostgreSQL values."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_values(item) for item in value]
    return value
