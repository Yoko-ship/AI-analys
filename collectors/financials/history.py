"""Financials history operations with explicit dependencies."""
from __future__ import annotations

import collectors.financials.delivery as collectors_financials_delivery
import collectors.financials.settings as collectors_financials_settings
import os

import catalogue.market_store as catalogue_market_store
import requests
import time


def _history_universe() -> set[str]:

    """Every ISIN the DEPLOYMENT's board carries, plus the local catalog's.



    The board is the universe the interface quotes, and it is not this machine's

    catalog: production carried 95 securities where the local one held 78, so a

    backfill sourced from here alone left 29 board rows with no series and no way

    to know it — the same shape as the quote-universe fix that sat inert for

    three days because its backfill read the collector's own scratch DB.



    The local catalog is unioned in rather than replaced: it holds codes that

    have stopped trading and dropped off the live feed, and their past is still

    their past.

    """

    codes: set[str] = set()

    try:

        from securities_catalog import get_securities_map



        for meta in (get_securities_map() or {}).values():

            isin = str((meta or {}).get("isin") or "").strip().upper()

            if isin:

                codes.add(isin)

    except Exception:  # noqa: BLE001

        collectors_financials_settings.log.exception("history backfill: local catalog unreadable")

    local = len(codes)

    base = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/")

    for kind in ("stock", "bond"):

        try:

            resp = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60)

            resp.raise_for_status()

            for row in (resp.json().get("stocks") or []):

                isin = str(row.get("isin") or "").strip().upper()

                if isin:

                    codes.add(isin)

        except Exception:  # noqa: BLE001 — the local catalog still gives us a run

            collectors_financials_settings.log.exception("history backfill: could not read the deployment's %s board", kind)

    collectors_financials_settings.log.info("history backfill universe: %d codes (%d local, %d added from the board)",

             len(codes), local, len(codes) - local)

    return codes


def backfill_quote_history(months: int = 12) -> int:
    """Seed `catalog_quote_history` from openinfo's conclusions archive.

    The collector keeps this table current from the exchange page, which carries
    about twenty-one sessions — enough for a sparkline the day after a run, and
    it deepens by itself from there. This is the one-off that gives it a real
    past instead of waiting a year for one, and the only place we ask openinfo
    for a per-security series: once, paced, for every listed code — not once per
    ticker every time somebody opens a page, which is the cost this whole table
    exists to remove.
    """
    from collectors.openinfo.transport import _make_session
    from collectors.openinfo.market import fetch_price_history

    session = _make_session()
    codes = sorted(_history_universe())
    collectors_financials_settings.log.info("history backfill: %d securities, %d months each", len(codes), months)
    rows: list[dict] = []
    failed = 0
    for index, isin in enumerate(codes, 1):
        try:
            data = fetch_price_history(isin, session, months)
        except Exception:  # noqa: BLE001 — one unreadable code is not the run
            collectors_financials_settings.log.exception("history backfill: %s unreadable", isin)
            failed += 1
            continue
        points = data.get("points") or []
        for p in points:
            if p.get("date") and p.get("close") is not None:
                rows.append({"isin": isin, "trade_date": p["date"], "close_price": p["close"],
                             "change_value": p.get("change"),
                             "quantity": p.get("trading_volume"),
                             "turnover": p.get("trading_value"),
                             # The archive carries the session's OHLC too, and it
                             # is the only source that has it for sessions older
                             # than the collector. Split-restated with the close
                             # by adjust_history (corporate_actions._PRICE_FIELDS).
                             "open_price": p.get("open"),
                             "high_price": p.get("high"),
                             "low_price": p.get("low")})
        if index % 20 == 0:
            collectors_financials_settings.log.info("history backfill: %d/%d codes, %d sessions so far", index, len(codes), len(rows))
        time.sleep(0.25)
    collectors_financials_settings.log.info("history backfill: %d sessions from %d codes (%d unreadable)",
             len(rows), len(codes) - failed, failed)
    if not rows:
        return 1
    # The admin endpoint caps a batch; the series is deep enough to exceed it.
    status = 0
    for start in range(0, len(rows), 20000):
        status = collectors_financials_delivery._post("/api/admin/quotes",
                       {"rows": [], "history": rows[start:start + 20000]}) or status
    return status
