"""Collect the exchange-listing registry (openinfo info_rfb) + last trade.

Runs where openinfo.uz is reachable. For every catalogued issuer it reads the
org's RFB securities (ISIN, shares outstanding, reference price, listing date)
from ``/home/organizations/{org_id}/`` and the last trade from
``/iuzse/conclusions/``, producing one row per security (ordinary + preferred
are separate rows). ``collector_financials`` pushes these to prod so that
issuers listed on RFB Tashkent but absent from the live uzse-stock feed (no
recent trades) still appear on the market board, tagged inactive.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import reports_catalog as rc
from openinfo_collector import OPENINFO_API_BASE, _json_get, _make_session

log = logging.getLogger("listings")

# openinfo stock_type codes → the market feed's share_type vocabulary.
_STOCK_TYPE = {"01": "ordinary", "02": "preferred"}
_CONCLUSIONS_LOOKBACK_DAYS = 3650


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "", "-") else float(v)
    except (TypeError, ValueError):
        return None


def _fmt_date(v: Any) -> str | None:
    """openinfo listing_date is 'YYYYMMDD' → 'YYYY-MM-DD'."""
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s or None


def _org_ids() -> dict[str, str]:
    """ticker → org_id from the local catalog (already resolved by sync_all)."""
    conn = rc.get_catalog_conn()
    rows = conn.execute(
        "SELECT ticker, org_id FROM catalog_companies "
        "WHERE org_id IS NOT NULL AND org_id != ''"
    ).fetchall()
    conn.close()
    return {r["ticker"]: str(r["org_id"]) for r in rows}


def _last_conclusion(session: Any, isin: str) -> dict[str, Any] | None:
    """Latest OHLC trade point for an ISIN, or None if it has never traded."""
    end = date.today()
    start = end - timedelta(days=_CONCLUSIONS_LOOKBACK_DAYS)
    try:
        payload = _json_get(
            session, "/iuzse/conclusions/",
            {"isu_cd": isin, "start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    except Exception:  # noqa: BLE001 — no history just means no last trade
        return None
    points = (payload.get("results") or []) if isinstance(payload, dict) else []
    if not points:
        return None
    points.sort(key=lambda p: str(p.get("date") or ""))
    return points[-1]


def collect_listing_rows() -> list[dict[str, Any]]:
    """One row per RFB-registered security across all catalogued issuers."""
    session = _make_session()
    org_ids = _org_ids()
    org_detail_cache: dict[str, dict] = {}
    seen_tickers: set[str] = set()
    rows: list[dict[str, Any]] = []

    for ticker, org_id in org_ids.items():
        detail = org_detail_cache.get(org_id)
        if detail is None:
            # Many tickers share an org (common + preferred); info_rfb already
            # lists all of the org's securities, so fetch each org only once.
            try:
                resp = session.get(f"{OPENINFO_API_BASE}/home/organizations/{org_id}/", timeout=30)
                resp.raise_for_status()
                detail = resp.json()
            except Exception:  # noqa: BLE001
                log.warning("org %s (%s) detail fetch failed", org_id, ticker)
                detail = {}
            org_detail_cache[org_id] = detail

        rfb = (detail.get("info_rfb") or {}) if isinstance(detail, dict) else {}
        name = detail.get("full_name_text") or detail.get("short_name_text") or ticker
        for ic in rfb.get("isin_codes") or []:
            tk = str(ic.get("ticker") or "").strip().upper()
            isin = str(ic.get("isu_cd") or "").strip().upper()
            if not tk or not isin or tk in seen_tickers:
                continue
            seen_tickers.add(tk)

            shares = _num(ic.get("list_shares"))
            reference_price = _num(ic.get("price"))
            last = _last_conclusion(session, isin)
            last_price = _num(last.get("close")) if last else None
            price_for_cap = last_price if last_price is not None else reference_price
            rows.append({
                "ticker": tk,
                "isin": isin,
                "name": name,
                "share_type": _STOCK_TYPE.get(str(ic.get("stock_type") or ""), "ordinary"),
                "listing_date": _fmt_date(ic.get("listing_date")),
                "shares_outstanding": shares,
                "reference_price": reference_price,
                "last_price": last_price,
                "last_trade_date": (last or {}).get("date"),
                "open_price": _num(last.get("open")) if last else None,
                "high_price": _num(last.get("high")) if last else None,
                "low_price": _num(last.get("low")) if last else None,
                "volume": _num(last.get("trading_volume")) if last else None,
                "market_cap": (shares * price_for_cap) if (shares and price_for_cap) else None,
            })

    log.info("collected %d listing rows from %d orgs", len(rows), len(org_detail_cache))
    return rows


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(json.dumps(collect_listing_rows(), ensure_ascii=False, indent=2))
