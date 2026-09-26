from __future__ import annotations

from functools import partial
import reports_catalog as catalog_store
import catalogue.market_store as catalogue_market_store

from typing import Any
import asyncio
import bonds
import cache_layer
import formulas
import server.http as http
import server.market.history as market_history


_BOND_QUALITY_TASKS: dict[str, asyncio.Task] = {}


async def _compute_bond_history_quality(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The data tier of each bond, from its own price history.

    §А.2 puts history quality in the bond table for the same reason the equity
    screens carry it: these issues trade in ones and twos, and a price series
    with 87% flat candles cannot support the same chart as one with 226 points.
    The bonds board shipped with the column and without the input, so every row
    showed a dash where the tier belongs.

    One history per issue, memoised for ten minutes and fetched concurrently; a
    failure costs that row its tier and nothing else, because a board must not
    go dark over an enrichment.
    """
    securities = inputs["securities"]
    targets = []
    for row in inputs["board"]:
        ticker = str(row.get("ticker") or "").upper()
        meta = securities.get(ticker) or {}
        if bonds.is_bond(row, meta) and (row.get("isin") or meta.get("isin")):
            targets.append((ticker, row.get("isin") or meta.get("isin")))

    async def one(ticker: str, isin: str):
        try:
            data = await market_history._full_history(isin)
            points = formulas.normalize_points(data.get("points") or [])
            return ticker, formulas.data_quality(points)
        except Exception:  # noqa: BLE001 — a missing tier is a dash, not a 502
            http.logger.debug("bond history quality failed for %s", ticker, exc_info=True)
            return ticker, None

    results = await asyncio.gather(*(one(t, i) for t, i in targets))
    return {t: q for t, q in results if q}


async def _bond_history_quality(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return cached enrichment immediately; warm a cold cache in background.

    Price-history quality is useful context, but it must not hold the entire
    bond screener behind dozens of upstream history downloads.
    """
    securities = inputs["securities"]
    targets = sorted(
        (str(row.get("ticker") or "").upper(), row.get("isin") or (securities.get(str(row.get("ticker") or "").upper()) or {}).get("isin"))
        for row in inputs["board"]
        if bonds.is_bond(row, securities.get(str(row.get("ticker") or "").upper()) or {})
    )
    revision = f"{inputs.get('trade_date') or 'none'}:{','.join(f'{ticker}={isin}' for ticker, isin in targets if isin)}"
    cache_key = cache_layer.key("bond:history-quality", revision)
    cached = cache_layer.get(cache_key)
    if cached is not None:
        return cached

    async def compute_and_store():
        value = await _compute_bond_history_quality(inputs)
        cache_layer.set(cache_key, value, ttl=3600)
        return value

    task = _BOND_QUALITY_TASKS.get(cache_key)
    if task is None or task.done():
        task = asyncio.create_task(compute_and_store())
        _BOND_QUALITY_TASKS[cache_key] = task
        task.add_done_callback(lambda _task: _BOND_QUALITY_TASKS.pop(cache_key, None))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=0.75)
    except asyncio.TimeoutError:
        return {}


async def _bond_price_histories(inputs: dict[str, Any],
                                references: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Recent stored sessions of every bond, keyed by ISIN — one query for all.

    The yield is struck on the volume-weighted price of these sessions
    (bonds.reference_price), not on whichever odd lot printed last.
    """
    securities = inputs["securities"]
    isins = {str(r.get("isin") or "").upper() for r in (references or {}).values() if r and r.get("isin")}
    for row in inputs["board"]:
        ticker = str(row.get("ticker") or "").upper()
        if bonds.is_bond(row, securities.get(ticker) or {}):
            code = row.get("isin") or (securities.get(ticker) or {}).get("isin")
            if code:
                isins.add(str(code).upper())
    isins.discard("")
    if not isins:
        return {}
    window = bonds.REFERENCE_PRICE_WINDOW_DAYS + 15
    return await asyncio.get_running_loop().run_in_executor(
        None, partial(catalogue_market_store.get_quote_history, sorted(isins), window))
