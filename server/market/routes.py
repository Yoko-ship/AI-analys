from __future__ import annotations



from company_catalog import COMPANY_SECTORS
from datetime import date
from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import Response
from functools import partial
from market_audit import audit_session
from typing import Any
from typing import Literal
import asyncio
import cache_layer
import corporate_actions
import formulas
import fundamentals
import heatmap
import instruments
import obs
import public_contract
import reports_catalog as catalog_store
import catalogue.fields as catalogue_fields
import catalogue.market_store as catalogue_market_store
import catalogue.ratios as catalogue_ratios
import catalogue.refresh as catalogue_refresh
import catalogue.snapshots as catalogue_snapshots
import requests
import securities_catalog as securities_store
import server.http as http
import server.market.board as market_board
import server.market.dates as market_dates
import server.market.history as market_history
import server.market.valuations as market_valuations
import server.settings as settings


router = APIRouter()


@router.get("/api/market/stocks")
async def api_market_stocks(request: Request, type: str | None = None,
                            refresh: bool = False) -> Response:
    security_type = (type or "").strip().lower()
    if security_type and security_type not in {"stock", "bond"}:
        raise HTTPException(status_code=400, detail="type must be stock or bond")
    payload = await market_board._cached_market_board(security_type, refresh=refresh)
    return http._etag_json(
        request,
        payload,
        max_age=0 if refresh else market_board.MARKET_BOARD_BROWSER_TTL_SEC,
    )


@router.get("/api/market/audit")
async def api_market_audit() -> dict[str, Any]:
    """Does the board agree with the exchange? Answered from stored data.

    The board's mismatches with the exchange's own bulletin were always found by a
    human comparing the two by eye, because nothing in the pipeline ever asserted
    that the securities we serve are the securities that traded, or that the
    numbers on a row come from the same session. This is that assertion, exposed
    so it can be asked at any time rather than discovered.
    """
    loop = asyncio.get_running_loop()
    try:
        stats, quotes = await asyncio.gather(
            loop.run_in_executor(None, catalogue_market_store.get_all_trade_stats),
            loop.run_in_executor(None, catalogue_market_store.get_all_quotes),
        )
        shares, bonds = await asyncio.gather(market_board._build_board("stock"), market_board._build_board("bond"))
    except Exception as exc:
        http.logger.exception("market audit failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    from datetime import datetime, timedelta, timezone

    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    # Which session is still being traded, in the exchange's own time — a run at
    # 13:00 audits a day that is still adding executions, and the two sides are
    # read minutes apart (see market_audit.audit_session).
    today = datetime.now(timezone(timedelta(hours=5))).strftime("%Y%m%d")
    return http._json_safe(audit_session(stats, quotes, board,
                                    denylist=settings.BOARD_DENYLIST, today=today))


@router.get("/api/market/trades")
async def api_market_trades() -> dict[str, Any]:
    """The latest session's totals: turnover, securities changing hands, trades.

    Summed from our own per-trade statistics — every execution the exchange
    published for that session. The ``/trades`` mirror this used to read is a
    44-row snapshot of a fixed universe, and it reported 120,7 млн over ~900
    trades for 31.07 while the session the exchange published was 1,56 млрд over
    6 507. It stays as the fallback for a deployment that holds no statistics yet.
    """
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, catalogue_market_store.get_all_trade_stats)
    except Exception:
        http.logger.exception("market/trades: trade-stats read failed")
        stats = {}
    day = max((str(s.get("trade_date") or "") for s in stats.values()), default="")
    session = [s for s in stats.values() if day and str(s.get("trade_date") or "") == day]
    if session:
        stamps = [s.get("updated_at") for s in session if s.get("updated_at")]
        return http._json_safe({
            "ok": True,
            "source": "uzse-trade-results",
            "trade_date": day,
            "updated_at": market_dates._as_utc_iso(max(stamps)) if stamps else None,
            "securities": len(session),
            "total_volume": sum((s.get("total_value") or 0) for s in session),
            "total_quantity": sum((s.get("total_qty") or 0) for s in session),
            "total_trade_count": sum((s.get("trade_count") or 0) for s in session),
        })

    if not settings.UZSE_STOCK_API_BASE:
        raise HTTPException(status_code=502, detail="Could not load trade data")
    try:
        response = await loop.run_in_executor(
            None, partial(requests.get, f"{settings.UZSE_STOCK_API_BASE}/trades", timeout=20))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        http.logger.exception("UZSE trades API request failed")
        raise HTTPException(status_code=502, detail="Could not load trade data") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Trades API returned invalid JSON") from exc

    trades = payload.get("trades", []) if isinstance(payload, dict) else []
    if not isinstance(trades, list):
        trades = []
    total_volume = sum((t.get("volume") or 0) for t in trades)
    total_quantity = sum((t.get("quantity") or 0) for t in trades)
    total_trade_count = sum((t.get("trade_count") or 0) for t in trades)
    return http._json_safe({
        "ok": True,
        # The mirror stamps naive UTC; say so, or the browser reads it as local.
        "updated_at": market_dates._as_utc_iso(payload.get("updated_at")) if isinstance(payload, dict) else None,
        "total_volume": total_volume,
        "total_quantity": total_quantity,
        "total_trade_count": total_trade_count,
    })


@router.get("/api/market/financials")
async def api_market_financials(ticker: str | None = None) -> dict[str, Any]:
    """Return cached NSBU headline indicators per ticker: {ticker: {...}}.

    Reads the pre-computed cache instantly and kicks a fire-and-forget background
    refresh so the cache fills/refreshes progressively as the market is browsed.
    """
    loop = asyncio.get_running_loop()
    try:
        financials = await loop.run_in_executor(None, catalogue_snapshots.get_all_financials)
    except Exception as exc:
        http.logger.exception("financials cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Progressive background fill (non-blocking; self-throttled and lock-guarded).
    loop.run_in_executor(None, catalogue_refresh.refresh_financials_cache)
    # Stored NSBU sums are thousands of UZS; serve full UZS so the client can
    # relate them to market caps/prices without unit knowledge. The `annual`
    # companion carries the same money fields and must be scaled with the row —
    # a 12-month denominator left in thousands would understate P/E ~1000x for
    # exactly the issuers the companion exists to make comparable.
    def _scaled(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            **{k: row[k] * catalogue_fields.NSBU_THOUSANDS_UZS
               for k in catalogue_fields.FIN_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }

    def _with_companions(row: dict[str, Any]) -> dict[str, Any]:
        out = _scaled(row)
        # Both companions are money in the same thousands, so both scale with the
        # row. `prior` is the comparative the filing itself prints for the year
        # before — the year-on-year denominator.
        for key in ("annual", "prior"):
            if row.get(key):
                out[key] = _scaled(row[key])
        return out

    financials = {ticker: _with_companions(row) for ticker, row in financials.items()}
    if ticker:
        requested = ticker.strip().upper()
        sibling = requested[:-1] if requested.endswith("P") else f"{requested}P"
        financials = {
            key: value for key, value in financials.items()
            if str(key).upper() in {requested, sibling}
        }
    return http._json_safe({
        "ok": True,
        "count": len(financials),
        "financials": financials,
    })


@router.get("/api/market/ratios")
async def api_market_ratios() -> dict[str, Any]:
    """Per-ticker financial ratios & equity (openinfo financial_indicators),
    keyed by ticker. Feeds the market-wide multiplier columns (P/E, P/B) and
    ratio coefficients of the §3.8 tabular reports.

    Two exclusions by the 2026-08-10 audit: ``debt_to_equity`` left the
    storefront entirely (лист 06 — 47 of 99 values reproduced under no formula,
    the units were mixed and for banks the number was meaningless), and bond
    tickers are not served (V17 — ten bond issues were inheriting their
    issuer's ROE/ROA as if a coupon security had a return on equity).

    Beside ROE/ROA/current ratio this also serves the published coefficients the
    company page's «Коэффициенты» card already shows — quick ratio, debt/assets,
    asset turnover and ROCE — in the units the issuer published them in
    (debt/assets a percent, the rest bare). ``periods`` names the reporting year
    of each field on its own: one issuer can file liquidity for 2023 and ROE for
    2025, and the single ``period`` above is only the newest of them.
    """
    loop = asyncio.get_running_loop()
    try:
        ratios = await loop.run_in_executor(None, catalogue_ratios.get_all_ratios)
        securities = await loop.run_in_executor(None, securities_store.get_securities_map)
    except Exception as exc:
        http.logger.exception("ratios cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bonds = {t for t, meta in (securities or {}).items()
             if str((meta or {}).get("type") or "").lower() == "bond"}
    # Absolute sums (equity/assets) are stored in thousands of UZS; serve full
    # UZS so P/B = market_cap / total_equity divides like units.
    ratios = {
        ticker: {
            **{k: v for k, v in row.items() if k != "debt_to_equity"},
            # The withheld field must not survive in the period map either.
            "periods": {k: v for k, v in (row.get("periods") or {}).items()
                        if k != "debt_to_equity"},
            **{k: row[k] * catalogue_fields.NSBU_THOUSANDS_UZS
               for k in catalogue_fields.RATIO_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }
        for ticker, row in ratios.items()
        if str(ticker).upper() not in bonds
    }
    return http._json_safe({"ok": True, "count": len(ratios), "ratios": ratios})


@router.get("/api/market/multiples")
async def api_market_multiples(request: Request, view: Literal["full", "board"] = "full",
                               ticker: str | None = None) -> Response:
    """P/E, P/B, ROE, ROA, margin and D/E — computed once, per ISSUER.

    Both classes of an issuer receive identical values by construction; only
    price, change, volume and the class's own capitalisation differ. This is the
    endpoint that makes KFSK 203.6 / KFSKP 0.19 impossible.
    """
    trace = obs.Trace(endpoint="market/multiples")
    try:
        requested = str(ticker or "").strip().upper() or None
        inputs = await market_valuations._market_inputs(requested)
        trace.step("inputs", instruments=len(inputs["board"]),
                   financials=len(inputs["financials"]), ratios=len(inputs["ratios"]))
        # The session date alone is insufficient: a corrected statement or
        # share count can arrive before the next trade.  The dependency hash
        # makes that correction miss the old cache immediately.
        input_version = public_contract.market_inputs_version(inputs)
        cache_key = cache_layer.key(f"market:multiples:{requested or 'all'}", inputs["trade_date"] or "none",
                                    input_version)
        payload = cache_layer.cached(cache_key, lambda: market_valuations._multiples_payload(inputs))
        if requested:
            selected = [row for row in payload["items"]
                        if str(row.get("ticker") or "").upper() == requested]
            issuer_keys = {row.get("issuer") for row in selected}
            payload = {
                **payload,
                "count": len(selected),
                "issuers": len(issuer_keys),
                "items": selected,
                "by_issuer": {
                    key: value for key, value in payload.get("by_issuer", {}).items()
                    if key in issuer_keys
                },
            }
        suppressed = sum(1 for r in payload["items"]
                         if not (r.get("validation") or {}).get("valid", True))
        if view == "board":
            payload = market_valuations._board_multiples_payload(payload)
        trace.step("multiples", issuers=payload["issuers"], suppressed=suppressed)
        payload["trace_id"] = trace.trace_id
        return http._etag_json(request, payload, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        trace.reject("multiples", reason=str(exc))
        http.logger.exception("market multiples failed")
        raise HTTPException(status_code=502, detail="multiples unavailable") from exc
    finally:
        trace.close()


@router.get("/api/market/summary")
async def api_market_summary(request: Request) -> Response:
    """The headline cards: capitalisation with its exclusions, and the counters."""
    try:
        inputs = await market_valuations._market_inputs()
        cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
        board = inputs["board"]
        traded = [r for r in board if (formulas.to_number(r.get("trade_count")) or 0) > 0
                  or (formulas.to_number(r.get("volume")) or 0) > 0]
        up = down = flat = 0
        for row in traded:
            change = heatmap.day_change(formulas.to_number(row.get("last_price")),
                                        formulas.to_number(row.get("close_price")))
            if change is None:
                continue
            if change > 0.05:
                up += 1
            elif change < -0.05:
                down += 1
            else:
                flat += 1
        return http._etag_json(request, {
            "ok": True,
            "instruments": len(board),
            "traded_today": len(traded),
            "up": up, "down": down, "flat": flat,
            "market_cap": cap,
            "turnover_today": sum((formulas.to_number(r.get("volume")) or 0) for r in traded),
            "trades_today": sum((formulas.to_number(r.get("trade_count")) or 0) for r in traded),
            "trade_date": inputs["trade_date"],
        }, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("market summary failed")
        raise HTTPException(status_code=502, detail="summary unavailable") from exc


@router.get("/api/market/changes")
async def api_market_changes(request: Request) -> Response:
    """Per-security price change over each period the board offers.

    The board's «Изменение» column measured one thing — the session — so a reader
    who wanted to know what a week or a month had done had to open every company
    page in turn. These are the same closes the sparklines are drawn from
    (`catalog_quote_history`), so the column and the chart cannot disagree.

    Every figure names the session its base came from: a change is a statement
    about two dates, and on this market the earlier one is rarely the date the
    label implies. The client shows it in the cell's tooltip.
    """
    loop = asyncio.get_running_loop()
    try:
        smap = await loop.run_in_executor(None, securities_store.get_securities_map)
        isin_of = {t: str((meta or {}).get("isin") or "").upper()
                   for t, meta in (smap or {}).items()}
        codes = sorted({i for i in isin_of.values() if i})
        # 400 sessions is over a year of trading for even the most liquid line,
        # and many more for a quiet one — get_quote_history counts sessions, not
        # days, precisely so a security that rarely trades still answers.
        history = await loop.run_in_executor(None, partial(catalogue_market_store.get_quote_history, codes, 400))
    except Exception as exc:
        http.logger.exception("market changes failed")
        raise HTTPException(status_code=502, detail="changes unavailable") from exc

    ticker_of = {isin: ticker for ticker, isin in isin_of.items() if isin}
    series: dict[str, list[dict[str, Any]]] = {}
    for isin, rows in history.items():
        # Back-adjusted for splits and bonus issues FIRST. The stored closes are
        # what the exchange printed on the day, and a window spanning ALSM's 2025
        # recapitalisation (one April share is three of today's) would otherwise
        # report a 40 % collapse to a holder who had in fact gained. This is the
        # same restatement the price chart applies; the two must not disagree.
        rows, _applied = corporate_actions.adjust_history(
            rows, ticker_of.get(isin), isin, date_key="trade_date",
            price_fields=("close_price", "open_price", "high_price", "low_price"))
        points = []
        for r in rows:
            close = formulas.to_number(r.get("close_price"))
            stamp = str(r.get("trade_date") or "")
            if close is None or len(stamp) != 8 or not stamp.isdigit():
                continue
            # Turnover rides along on the same point. It is money, so the split
            # restatement above must not touch it — a сум in April is a сум now,
            # whatever happened to the share count in between.
            points.append({"d": date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])),
                           "date": stamp, "close": close,
                           # Prices, so the split restatement above applies to
                           # them exactly as it does to the close: a window
                           # spanning a recapitalisation must report one unit.
                           "open": formulas.to_number(r.get("open_price")),
                           "high": formulas.to_number(r.get("high_price")),
                           "low": formulas.to_number(r.get("low_price")),
                           "quantity": formulas.to_number(r.get("quantity")),
                           "trade_count": formulas.to_number(r.get("trade_count")),
                           # Money and share counts. The split restatement must
                           # NOT touch these — a сум in April is a сум now,
                           # whatever happened to the share count in between.
                           "largest_value": formulas.to_number(r.get("largest_value")),
                           "largest_qty": formulas.to_number(r.get("largest_qty")),
                           "turnover": formulas.to_number(r.get("turnover"))})
        if points:
            series[isin] = sorted(points, key=lambda p: p["d"])

    changes: dict[str, dict[str, Any]] = {}
    for ticker, isin in isin_of.items():
        points = series.get(isin)
        if not points:
            continue
        as_of = points[-1]["d"]
        row = {code: market_history._window_change(points, span, as_of)
               for code, span in market_history.MARKET_CHANGE_WINDOWS.items()}
        row = {k: v for k, v in row.items() if v}
        # The window's own session figures, under their own key rather than beside
        # `pct` in each window's object: a security can have traded over a month
        # without having a base close a month back (its history starts inside the
        # window), and the volume columns must still answer. Keeping the two
        # independent is what lets each answer when the other cannot.
        stats = {code: market_history._window_stats(points, span, as_of)
                 for code, span in market_history.MARKET_CHANGE_WINDOWS.items()}
        stats = {k: v for k, v in stats.items() if v}
        if row or stats:
            row["as_of"] = points[-1]["date"]
            if stats:
                row["stats"] = stats
                # `turnover` is the same sum under the key the liquidity panel
                # has read since 2026-08-18. Kept so a client that has not been
                # redeployed alongside this one keeps its panel.
                row["turnover"] = {code: {"value": st["value"], "sessions": st["sessions"],
                                          "from": st["from"]}
                                   for code, st in stats.items()}
            changes[ticker] = row
    return http._etag_json(request, {"ok": True, "windows": list(market_history.MARKET_CHANGE_WINDOWS),
                               "count": len(changes), "changes": changes}, max_age=300)


@router.get("/api/heatmap")
async def api_heatmap(request: Request) -> Response:
    """The market map: tiles, sectors and metadata in ONE response (ТЗ §9)."""
    trace = obs.Trace(endpoint="heatmap")
    try:
        inputs = await market_valuations._heatmap_inputs()
        payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
        trace.step("tiles", **payload["counts"])
        payload["ok"] = True
        payload["trace_id"] = trace.trace_id
        return http._etag_json(request, payload, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        trace.reject("heatmap", reason=str(exc))
        http.logger.exception("heatmap failed")
        raise HTTPException(status_code=502, detail="heatmap unavailable") from exc
    finally:
        trace.close()


@router.get("/api/instruments")
async def api_instruments(request: Request, include_inactive: bool = True) -> Response:
    """The single instrument universe (ТЗ §4).

    Inactive listings are returned by default and flagged, never dropped: a
    security that stopped trading is a fact about the market, and hiding it is
    how five references came to hold five different counts.
    """
    try:
        inputs = await market_valuations._market_inputs()
        catalog = instruments.build_catalog(
            securities=inputs["securities"], board=inputs["board"],
            listings=inputs["listings"], financials=inputs["financials"],
            ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
        if not include_inactive:
            catalog = {**catalog,
                       "items": [i for i in catalog["items"] if i["is_active"]]}
        catalog["ok"] = True
        return http._etag_json(request, catalog, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("instruments failed")
        raise HTTPException(status_code=502, detail="catalog unavailable") from exc


@router.get("/api/market/trade-stats")
async def api_market_trade_stats() -> dict[str, Any]:
    """Per-ISIN latest-day trade statistics (turnover, avg price, largest trade)."""
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, catalogue_market_store.get_all_trade_stats)
    except Exception as exc:
        http.logger.exception("trade-stats cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # When the board was last refreshed BY US — the moment the collector's
    # quotes run (08:00 / 13:00 / 16:10 Tashkent) wrote these rows. This is what
    # the page's "Обновлено" badge reports: the uzse mirror's own stamp answers a
    # different question (when someone else's cache refreshed) and can never
    # show our schedule.
    stamps = [s.get("updated_at") for s in stats.values() if s.get("updated_at")]
    dates = [s.get("trade_date") for s in stats.values() if s.get("trade_date")]
    return http._json_safe({
        "ok": True,
        "count": len(stats),
        "refreshed_at": market_dates._as_utc_iso(max(stamps)) if stamps else None,
        "trade_date": max(dates) if dates else None,
        "stats": stats,
    })
