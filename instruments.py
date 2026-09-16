"""instruments.py — ONE instrument universe.

ТЗ v1.2 §4. Five references disagreed about which securities exist: the local
catalog holds 78, catalog_companies 91, the financials cache 89 and the ratios
cache 66 (the ТЗ counted 82 / 85 / 96 / 107 / 108 in production). Each screen
picked a different one, so an issuer could be on the market board and missing
from the map, or carry a sector on one screen and another sector elsewhere.

This module merges them into a single list and — the part that matters — does
not lose a security quietly. Anything only one source knows about is still
returned, tagged with where it came from, and every disagreement is recorded in
``discrepancies`` for the administrative report instead of being resolved by
whichever dictionary happened to be read last.

``is_active`` is a fact about trading, not a flag someone set: no execution for
``catalog.inactive_after_days`` days and the security is inactive, whatever the
registry says.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from formulas import _as_date, _num, thresholds

logger = logging.getLogger(__name__)


def _norm_day(value: Any) -> date | None:
    """The three date spellings in this codebase: DD.MM.YYYY, YYYY-MM-DD, YYYYMMDD."""
    s = str(value or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", s)
    if m:
        s = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    elif re.match(r"^\d{8}$", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return _as_date(s)


def _share_class(sec: dict[str, Any]) -> str:
    if str(sec.get("type") or "").lower() == "bond":
        return "bond"
    if sec.get("is_preferred") or str(sec.get("share_type") or "").lower().startswith("prefer"):
        return "preferred"
    return "ordinary"


def build_catalog(securities: dict[str, dict[str, Any]] | None = None,
                  board: Iterable[dict[str, Any]] | None = None,
                  listings: dict[str, dict[str, Any]] | None = None,
                  financials: dict[str, Any] | None = None,
                  ratios: dict[str, Any] | None = None,
                  sectors: dict[str, str] | None = None,
                  today: date | None = None) -> dict[str, Any]:
    """One row per instrument, plus the list of things the sources disagree on."""
    cfg = thresholds()["catalog"]
    inactive_after = int(cfg["inactive_after_days"])
    today = today or date.today()
    securities = securities or {}
    listings = listings or {}
    financials = financials or {}
    ratios = ratios or {}
    sectors = sectors or {}
    board_rows = {str(r.get("ticker") or "").upper(): r for r in (board or [])}

    tickers = set()
    for source in (securities, listings, board_rows, financials, ratios):
        tickers.update(str(t).upper() for t in source)

    discrepancies: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []

    for ticker in sorted(tickers):
        sec = securities.get(ticker) or {}
        listing = listings.get(ticker) or {}
        row = board_rows.get(ticker) or {}
        present_in = [name for name, src in (
            ("securities", securities), ("listings", listings), ("board", board_rows),
            ("financials", financials), ("ratios", ratios)) if ticker in src]

        # --- sector: ONE classifier -----------------------------------------
        candidates = {
            "securities": sec.get("sector"),
            "board": row.get("sector"),
            "reference": sectors.get(ticker),
        }
        distinct = {k: v for k, v in candidates.items() if v}
        unique_values = set(distinct.values())
        if len(unique_values) > 1:
            discrepancies.append({
                "ticker": ticker, "field": "sector", "values": distinct,
                "resolution": "securities catalog wins",
            })
        # Precedence is fixed and documented, so the answer does not depend on
        # which dictionary was read last.
        sector = sec.get("sector") or sectors.get(ticker) or row.get("sector") or None

        # --- ISIN -------------------------------------------------------------
        isins = {v for v in (sec.get("isin"), listing.get("isin"), row.get("isin")) if v}
        if len(isins) > 1:
            discrepancies.append({
                "ticker": ticker, "field": "isin", "values": sorted(isins),
                "resolution": "securities catalog wins",
            })
        isin = sec.get("isin") or listing.get("isin") or row.get("isin") or None

        # --- last trade and activity -----------------------------------------
        days = [d for d in (_norm_day(sec.get("last_trade_date")),
                            _norm_day(listing.get("last_trade_date")),
                            _norm_day(row.get("last_trade_date"))) if d]
        last_trade = max(days) if days else None
        traded_today = bool(_num(row.get("trade_count")) or _num(row.get("volume")))
        if traded_today:
            last_trade = max([d for d in (last_trade, today) if d])
        stale_days = (today - last_trade).days if last_trade else None
        is_active = bool(last_trade and stale_days is not None and stale_days <= inactive_after)

        registry_inactive = bool(row.get("inactive"))
        if registry_inactive != (not is_active) and last_trade:
            discrepancies.append({
                "ticker": ticker, "field": "is_active",
                "values": {"registry_inactive": registry_inactive,
                           "days_since_trade": stale_days},
                "resolution": f"trading wins: inactive after {inactive_after} days",
            })

        shares = (_num(row.get("shares_outstanding"))
                  or _num(listing.get("shares_outstanding"))
                  or _num(sec.get("shares_outstanding")))

        items.append({
            "ticker": ticker,
            "isin": isin,
            "name": sec.get("name") or listing.get("name") or row.get("name"),
            "type": (sec.get("type") or row.get("type") or "stock"),
            "share_class": _share_class({**sec, **row}),
            "sector": sector,
            "is_listed": bool(present_in and ("listings" in present_in or "board" in present_in
                                              or "securities" in present_in)),
            "is_active": is_active,
            "last_trade_date": last_trade.isoformat() if last_trade else None,
            "days_since_trade": stale_days,
            "shares_outstanding": shares,
            "market_cap": _num(row.get("market_cap")),
            "has_financials": ticker in financials,
            "has_ratios": ticker in ratios,
            "sources": present_in,
        })

    return {
        "count": len(items),
        "active": sum(1 for i in items if i["is_active"]),
        "inactive": sum(1 for i in items if not i["is_active"]),
        "items": items,
        "discrepancies": discrepancies,
        "source_counts": {
            "securities": len(securities), "listings": len(listings),
            "board": len(board_rows), "financials": len(financials), "ratios": len(ratios),
        },
        "inactive_after_days": inactive_after,
    }
