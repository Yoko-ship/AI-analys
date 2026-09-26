from __future__ import annotations



from typing import Any
import asyncio
import fundamentals
import instruments
import public_contract
import reports_catalog as catalog_store
import securities_catalog as securities_store
import server.http as http
import server.market.board as market_board


# The 12-month earnings base used to be selected here (_earnings_for: the last
# complete fiscal year, else the raw cumulative quarter). ТЗ мультипликаторов
# (2026-08-10) replaced that with the TTM assembly — годовая величина + YTD
# текущего года − YTD прошлого года — which lives in
# fundamentals.twelve_month_flows and runs inside issuer_multiples, so the
# selection is no longer a caller's choice.


async def _market_inputs(ticker: str | None = None) -> dict[str, Any]:
    """Board, catalog, statements and ratios — fetched once, shared by every
    screen below so they cannot disagree about what exists."""
    loop = asyncio.get_running_loop()
    requested = str(ticker or "").strip().upper()
    if requested:
        # A company page needs one equity issuer, not a fresh rebuild of both
        # market boards. The stock board is already warmed on startup and its
        # short cache is the same snapshot the page header reads.
        shares = await market_board._cached_market_board("stock")
        bonds = {"stocks": []}
    else:
        # The market landing page requests several dependent endpoints in
        # parallel (instruments, summary and multiples).  Sending each one to
        # _build_board made a single first visit issue six identical remote
        # /stocks calls, which could exhaust the proxy timeout when the feed or
        # SQLite was briefly slow.  The board cache is lock-coalesced, so all
        # readers now share the same stock and bond snapshots for its short TTL.
        shares, bonds = await asyncio.gather(
            market_board._cached_market_board("stock"), market_board._cached_market_board("bond"),
        )
    securities, financials, ratios, listings, stats = await asyncio.gather(
        loop.run_in_executor(None, securities_store.get_securities_map),
        loop.run_in_executor(None, catalog_store.get_all_financials),
        loop.run_in_executor(None, catalog_store.get_all_ratios_cached),
        loop.run_in_executor(None, catalog_store.get_all_listings),
        loop.run_in_executor(None, catalog_store.get_all_trade_stats),
    )
    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    # Statement sums are stored in thousands of UZS; scale at the boundary so
    # every division below is like-for-like against a full-UZS market cap.
    # The nested blocks that ride on a row — the filing's own comparative
    # (``prior``, the TTM subtrahend) and the filed balance (``balance``, the
    # P/B and ROE denominators) — carry the same thousands and must cross the
    # boundary together, or the TTM would subtract thousands from full UZS.
    def _scale(row: dict[str, Any], fields) -> dict[str, Any]:
        out = {**row, **{k: row[k] * catalog_store.NSBU_THOUSANDS_UZS
                         for k in fields if isinstance(row.get(k), (int, float))}}
        prior = row.get("prior")
        if isinstance(prior, dict):
            out["prior"] = {**prior, **{k: prior[k] * catalog_store.NSBU_THOUSANDS_UZS
                                        for k in fields
                                        if isinstance(prior.get(k), (int, float))}}
        balance = row.get("balance")
        if isinstance(balance, dict):
            out["balance"] = {k: (v * catalog_store.NSBU_THOUSANDS_UZS
                                  if isinstance(v, (int, float)) else v)
                              for k, v in balance.items()}
        return out

    financials = {
        t: ({**_scale(r, catalog_store.FIN_MONEY_FIELDS), "annual": _scale(r["annual"], catalog_store.FIN_MONEY_FIELDS)}
            if r.get("annual") else _scale(r, catalog_store.FIN_MONEY_FIELDS))
        for t, r in (financials or {}).items()
    }
    ratios = {t: _scale(r, catalog_store.RATIO_MONEY_FIELDS) for t, r in (ratios or {}).items()}
    # The session the board describes: the latest day any row reports. The feed
    # writes DD.MM.YYYY and the day statistics YYYYMMDD, so compare normalised
    # values — ordering the raw strings put "31.01" above "05.02".
    trade_date = None
    for row in board:
        day = instruments._norm_day(row.get("last_trade_date"))
        if day and (trade_date is None or day > trade_date):
            trade_date = day
    if requested:
        catalog_rows = [
            {"ticker": str(key).upper(), **(value or {})}
            for key, value in securities.items()
        ]
        issuer_tickers = next((
            {str(row.get("ticker") or "").upper() for row in rows}
            for rows in fundamentals.group_by_issuer(catalog_rows).values()
            if any(str(row.get("ticker") or "").upper() == requested for row in rows)
        ), {requested})
        board = [row for row in board
                 if str(row.get("ticker") or "").upper() in issuer_tickers]
        securities = {key: value for key, value in securities.items()
                      if str(key).upper() in issuer_tickers}
        financials = {key: value for key, value in financials.items()
                      if str(key).upper() in issuer_tickers}
        ratios = {key: value for key, value in ratios.items()
                  if str(key).upper() in issuer_tickers}
        listings = {key: value for key, value in listings.items()
                    if str(key).upper() in issuer_tickers}
        stats = {key: value for key, value in stats.items()
                 if str(key).upper() in issuer_tickers}
    return {"board": board, "securities": securities, "financials": financials,
            "ratios": ratios, "listings": listings, "stats": stats,
            "trade_date": trade_date.isoformat() if trade_date else None}


async def _heatmap_inputs() -> dict[str, Any]:
    """The small, bounded data set a heatmap actually needs.

    The map previously reused ``_market_inputs`` and therefore loaded every
    financial statement, ratio and listing merely to draw price tiles. Besides
    delaying the first paint, those extra SQLite reads could block the single
    web worker during a collector write. Keep the map independent: board,
    security metadata and today's trade statistics are its whole contract.
    """
    loop = asyncio.get_running_loop()
    # Keep the heatmap in the same coalesced board snapshot as the rest of the
    # landing page.  Its small SQLite input set remains deliberately separate.
    shares, bonds = await asyncio.gather(
        market_board._cached_market_board("stock"), market_board._cached_market_board("bond"),
    )
    securities, stats = await asyncio.gather(
        loop.run_in_executor(None, securities_store.get_securities_map),
        loop.run_in_executor(None, catalog_store.get_all_trade_stats),
    )
    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    trade_date = None
    for row in board:
        day = instruments._norm_day(row.get("last_trade_date"))
        if day and (trade_date is None or day > trade_date):
            trade_date = day
    return {"board": board, "securities": securities, "stats": stats,
            "trade_date": trade_date.isoformat() if trade_date else None}


def _multiples_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    """Issuer-level multiples for every listed share class (ТЗ §8)."""
    securities, financials, ratios = (inputs["securities"], inputs["financials"],
                                      inputs["ratios"])
    listings = inputs.get("listings") or {}
    board_by_ticker = {str(r.get("ticker") or "").upper(): r for r in inputs["board"]}

    # Share classes are grouped by issuer using the catalog, enriched with the
    # board's capitalisation and share count for each class.
    #
    # Registry nominal prices are never quotes. Confirmed inactive preferred
    # classes are explicitly excluded from cap, but retained for issued shares.
    # V9 (ТЗ мультипликаторов): a class that has never traded carries a price
    # taken from the registry's nominal/reference, and a capitalisation built
    # on a nominal is fiction — UZIN at 1 000, UZNG at 500, TGBK at 5 000 all
    # produced fictitious caps and the P/E, P/B chain downstream of them. Such
    # a class contributes NO capitalisation: the issuer's cap either comes from
    # classes that actually traded or is honestly incomplete.
    def _market_input(ticker: str, row: dict[str, Any], shares: Any) -> dict[str, Any]:
        listing = listings.get(ticker) or {}
        if listing.get("market_cap"):
            shares = listing.get("shares_outstanding") or shares
            row = {
                **listing,
                **row,
                "ticker": ticker,
                "shares_outstanding": (listing.get("shares_outstanding")
                                       or row.get("shares_outstanding")),
                "shares_source": "openinfo_listing",
                "market_cap": listing["market_cap"],
                "market_cap_source": "openinfo_listing",
                "market_cap_source_url": "https://openinfo.uz/",
                "market_cap_as_of": listing.get("updated_at"),
            }
        if not row:
            return public_contract.market_class_input({}, shares_outstanding=shares)
        return public_contract.market_class_input(row, shares_outstanding=shares)

    catalog_rows = []
    for ticker, meta in (securities or {}).items():
        row = board_by_ticker.get(str(ticker).upper()) or {}
        shares = row.get("shares_outstanding") or meta.get("shares_outstanding")
        market_input = _market_input(str(ticker).upper(), {
            **row, "ticker": str(ticker).upper(),
            "is_preferred": meta.get("is_preferred") or row.get("is_preferred"),
            "share_type": meta.get("share_type") or row.get("share_type"),
        }, shares)
        catalog_rows.append({
            "ticker": str(ticker).upper(), **meta,
            "market_cap": market_input["market_cap"],
            "last_price": market_input["price"],
            "last_trade_date": market_input["price_as_of"],
            "shares_outstanding": market_input["shares_outstanding"],
            "market_input": market_input,
        })
    # Board rows with no catalog card yet (ТЗ мультипликаторов, лист 15: EQQU
    # traded actively while its filings sat unread because the multiples
    # universe was the catalog alone). The board row itself carries everything
    # the grouping needs — name, class, cap — so the issuer appears on the
    # multiples screen the day it appears on the board, and the missing card
    # remains a catalog-sync task rather than a blank row.
    known = {str(t).upper() for t in (securities or {})}
    for ticker, row in board_by_ticker.items():
        if not ticker or ticker in known:
            continue
        market_input = _market_input(ticker, row, row.get("shares_outstanding"))
        catalog_rows.append({
            "ticker": ticker,
            "name": row.get("name"),
            "type": row.get("type") or "stock",
            "share_type": row.get("share_type"),
            "is_preferred": row.get("is_preferred"),
            "market_cap": market_input["market_cap"],
            "last_price": market_input["price"],
            "last_trade_date": market_input["price_as_of"],
            "shares_outstanding": market_input["shares_outstanding"],
            "market_input": market_input,
        })
    groups = fundamentals.group_by_issuer(catalog_rows)

    rows: list[dict[str, Any]] = []
    by_issuer: dict[str, Any] = {}
    for key, classes in groups.items():
        tickers = [c["ticker"] for c in classes]
        # The issuer's statement is whichever class carries one — they describe
        # the same legal entity, so a preferred-only filing still applies.
        fin = next((financials.get(t) for t in tickers if financials.get(t)), None)
        rat = next((ratios.get(t) for t in tickers if ratios.get(t)), None)
        multiples = fundamentals.issuer_multiples(classes, fin, rat)
        multiples = public_contract.multiplier_contract(
            multiples, classes, fin, rat, market_as_of=inputs.get("trade_date"))
        by_issuer[key] = {"tickers": tickers, "multiples": multiples}
        for cls in classes:
            rows.append({
                "ticker": cls["ticker"],
                "issuer": key,
                "issuer_classes": tickers,
                "share_class": "preferred" if cls.get("is_preferred") else "ordinary",
                # Class-specific, by design (ТЗ §8).
                "market_cap_class": cls.get("market_cap"),
                "market_input": cls.get("market_input"),
                # Issuer-level, identical across the classes above.
                **{k: v for k, v in multiples.items()},
            })
    rows.sort(key=lambda r: r["ticker"])
    _apply_audit_blocks(rows)
    return {"ok": True, "count": len(rows), "issuers": len(groups),
            "contract_version": public_contract.CONTRACT_VERSION,
            "input_snapshot": public_contract.market_inputs_version(inputs),
            "items": rows, "by_issuer": by_issuer}


_BOARD_MULTIPLE_FIELDS = (
    "pe", "pb", "ps", "roe", "roa", "net_margin", "equity_assets",
)


_BOARD_METRIC_FIELDS = (
    # The table needs the published figure and enough context to show the same
    # audit/status tooltip as the detailed company view.  Calculation inputs,
    # class ledgers and snapshots are deliberately left on the detailed route.
    "value", "status", "base_period", "financial_period", "note", "reasons",
    "allowed", "estimate", "computed",
)


def _board_multiples_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """The small, table-safe form of the multiples contract.

    The market board never renders the issuer ledger or calculation inputs.  It
    used to download those repeated objects for every class (over 1 MB) just to
    print seven cells.  Keep the display value, audit status and tooltip context
    here; a company page requests its one complete record separately.
    """
    items: list[dict[str, Any]] = []
    for source in payload.get("items") or []:
        row: dict[str, Any] = {"ticker": source.get("ticker")}
        for field in _BOARD_MULTIPLE_FIELDS:
            metric = source.get(field)
            if isinstance(metric, dict):
                row[field] = {key: metric[key] for key in _BOARD_METRIC_FIELDS
                              if key in metric}
            else:
                row[field] = metric
        items.append(row)
    return {
        "ok": True,
        "count": len(items),
        "issuers": payload.get("issuers", 0),
        "contract_version": payload.get("contract_version"),
        "input_snapshot": payload.get("input_snapshot"),
        "items": items,
    }


def _apply_audit_blocks(rows: list[dict[str, Any]]) -> int:
    """Withhold every metric an open BLOCKING finding covers (ТЗ v1.3 §12.2).

    This is the line between a report and a control. The auditor is allowed to
    take a number off the screen: the cell becomes a dash carrying the rule that
    withheld it. Without this the module would only describe problems it had no
    power to stop, and a wrong figure would keep being published next to a
    perfectly accurate description of why it is wrong.

    An audit outage must never blank the board, so a failure here leaves the
    data untouched.
    """
    try:
        from audit import blocking_index

        index = blocking_index()
    except Exception:  # noqa: BLE001
        http.logger.exception("audit blocking index unavailable; publishing unfiltered")
        return 0
    if not index:
        return 0
    blocked = 0
    for row in rows:
        metrics = index.get(str(row.get("ticker") or "").upper())
        if not metrics:
            continue
        for metric in metrics:
            current = row.get(metric)
            if isinstance(current, dict) and current.get("value") is not None:
                # The calculated value is withheld; the figure a reader sees stays,
                # flagged «проверить», like every other value under review.
                row[metric] = {**current, "value": None, "status": "audit_blocked",
                               "computed": current.get("computed", current["value"]),
                               "display_value": current.get("display_value", current["value"]), "display_warning": True,
                               "calculation_status": public_contract.DATA_CONFLICT,
                               "note": "значение снято аудитором данных",
                               "limitation_reason": "значение снято аудитором данных",
                               "audit_metric": metric}
                blocked += 1
    return blocked
