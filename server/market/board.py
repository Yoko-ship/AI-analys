from __future__ import annotations



from company_catalog import COMPANY_CATALOG
from delisted import DELISTED_ISINS
from delisted import is_delisted_isin
from fastapi import HTTPException
from functools import partial
from typing import Any
import asyncio
import corporate_actions
import os
import provenance
import reports_catalog as catalog_store
import catalogue.market_store as catalogue_market_store
import requests
import securities_catalog as securities_store
import server.http as http
import server.market.dates as market_dates
import server.settings as settings
import time


def _listing_to_stock(lst: dict[str, Any]) -> dict[str, Any]:
    """Shape a stored RFB listing as a market-feed stock record, tagged inactive.

    Used to surface issuers that are listed on openinfo but absent from the live
    uzse-stock feed (no recent trades). Price falls back to the registry reference
    when no trade history exists.
    """
    price = lst.get("last_price")
    if price is None:
        price = lst.get("reference_price")
    return {
        "isin": lst.get("isin"),
        "ticker": lst.get("ticker"),
        "name": lst.get("name"),
        "type": "stock",
        "share_type": lst.get("share_type") or "ordinary",
        "close_price": price,
        "close_date": lst.get("last_trade_date"),
        "last_price": price,
        "last_trade_date": lst.get("last_trade_date"),
        "open": lst.get("open_price"),
        "high": lst.get("high_price"),
        "low": lst.get("low_price"),
        "volume": lst.get("volume"),
        "quantity": None,
        "trade_count": None,
        "security_type_text": None,
        "shares_outstanding": lst.get("shares_outstanding"),
        "shares_source": "openinfo_listing",
        "nominal": corporate_actions.current_par(lst.get("ticker"), lst.get("nominal")),
        "market_cap": lst.get("market_cap"),
        "market_cap_source": "openinfo_listing",
        "market_cap_source_url": "https://openinfo.uz/",
        "market_cap_as_of": lst.get("updated_at"),
        "inactive": True,
    }


_ISSUER_NAMES: dict[str, Any] = {"at": 0.0, "map": {}}


_ISSUER_NAMES_TTL = 600.0


def _issuer_names() -> dict[str, str]:
    """ticker → issuer name, for board rows the exchange feed leaves unnamed.

    The uzse mirror carries a ``name`` for only 9 of its 78 securities, so the
    board's company column read "—" for 69 rows (every preferred share, every
    bond, and majors like UZTL). The name is not missing from our data, only from
    that one feed: openinfo's issuer catalog (``catalog_companies``, kept current
    by the collector) knows it, and the static catalog covers what predates it.

    Cached for ten minutes — the board is the hottest endpoint and issuer names
    change about never.
    """
    now = time.monotonic()
    if _ISSUER_NAMES["map"] and now - _ISSUER_NAMES["at"] < _ISSUER_NAMES_TTL:
        return _ISSUER_NAMES["map"]
    names: dict[str, str] = {t.upper(): n for n, t in COMPANY_CATALOG.items()}
    try:
        from catalogue.storage import get_catalog_conn

        conn = get_catalog_conn()
        try:
            for r in conn.execute(
                    "SELECT ticker, company_name FROM catalog_companies").fetchall():
                ticker = (r["ticker"] or "").upper().strip()
                name = (r["company_name"] or "").strip()
                if ticker and name:
                    names[ticker] = name
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — the static catalog still answers
        http.logger.exception("issuer name catalog read failed")
    _ISSUER_NAMES.update(at=now, map=names)
    return names


_BOND_ISINS: dict[str, Any] = {"at": 0.0, "set": frozenset()}


_BOND_ISINS_TTL = 600.0


def _registered_bond_isins() -> frozenset[str]:
    """Every ISIN in the exchange's register of circulating bonds.

    Cached for ten minutes, like the issuer names above and for the same reason:
    the board is the hottest endpoint, and an issue joins the register when it is
    admitted, not within a session. An unreadable register answers with whatever
    was last read (empty on the first failure) — fail-soft, never an empty board.
    """
    now = time.monotonic()
    if _BOND_ISINS["set"] and now - _BOND_ISINS["at"] < _BOND_ISINS_TTL:
        return _BOND_ISINS["set"]
    try:
        isins = frozenset(
            str(ref.get("isin") or "").upper()
            for ref in provenance.bond_references().values() if ref.get("isin"))
    except Exception:
        http.logger.exception("bond register read failed; the equities board stays unfiltered")
        return _BOND_ISINS["set"]
    _BOND_ISINS.update(at=now, set=isins)
    return isins


def _retype_registered_bonds(rows: list[dict[str, Any]]) -> int:
    """Say `bond` about every row the exchange's bond register claims. In place.

    A REGISTERED BOND is never a share. IPYB2B6 — «Ipak Yo'li» AITB's 20% issue,
    admitted on 04.08.2026 — reached the equities board through the live mirror,
    which types every row it carries as a share, and its placement (100 000 bonds
    at par on 06.08) entered the board as a 104,8 млрд turnover AND the same
    figure as a capitalisation. It led «Топ ликвидности» over the whole equity
    market, and an issue has no shares to capitalise at all.

    Matched on the ISIN and never on the ticker: the RFB register files an issue
    under the ISSUER's ticker when it has none of its own, so a ticker match
    would take Aloqabank's SHARE (ALKB, UZ7044760005) off the board along with
    its bond (UZ60447611B9).

    The class is corrected rather than the row merely filtered, so it is right
    wherever the row travels — the securities catalog is synced from these rows,
    and a filter is something every future consumer has to remember to apply.
    """
    bond_isins = _registered_bond_isins()
    if not bond_isins:
        return 0
    fixed = 0
    for row in rows:
        if str(row.get("isin") or "").upper() not in bond_isins:
            continue
        if row.get("type") == "bond" and row.get("market_cap") is None:
            continue
        row["type"] = "bond"
        row["share_type"] = "bond"
        # An issue has no shares to capitalise: the figure the mirror carried
        # here was the placement's own turnover, entered a second time.
        row["shares_outstanding"] = None
        row["market_cap"] = None
        row["url"] = _exchange_url(row.get("isin"), True)
        fixed += 1
    return fixed


def _fill_names(rows: list[dict[str, Any]], names: dict[str, str]) -> int:
    """Name every row the feed left unnamed, in place. Returns rows filled.

    A preferred share with no entry of its own borrows its common sibling's name
    (UPOSP → UPOS): the same issuer, and the row's own type cell already says
    which class it is.
    """
    filled = 0
    for row in rows:
        if (row.get("name") or "").strip():
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        name = names.get(ticker)
        if not name and ticker.endswith("P"):
            name = names.get(ticker[:-1])
        if name:
            row["name"] = name
            filled += 1
    return filled


def _carries(row: dict[str, Any], close: Any) -> bool:
    """Is the row showing no price of its own but carrying exactly this close?"""
    if row.get("last_price") is not None:
        return False
    try:
        carried, quoted = float(row.get("close_price")), float(close)
    except (TypeError, ValueError):
        return False
    scale = max(abs(carried), abs(quoted))
    return scale == 0 or abs(carried - quoted) / scale <= 1e-9


def _apply_quote(row: dict[str, Any], quote: dict[str, Any]) -> None:
    """Overlay the exchange's session quote on a board row, in place.

    The row's own session decides: a quote is applied only when it is at least as
    recent as what the row already shows, so a stored quote for a security that
    has since gone quiet cannot pull a live row backwards. ``close_date`` counts
    as the row's session even with no trade — the exchange carries the closing
    price forward, and that carried price is newer than an older real trade.

    A carried close is the last trade's close, though — the exchange repeats it,
    it does not restate it. So when the mirror carries no price of its own and
    the close it is carrying is the close our quote names, that quote IS the
    session behind it, and waiting for a newer one leaves the row with a date it
    cannot explain and no price at all. Eight rows sat like that (UTGA, UZML,
    TRSBP, TKDMP, FRAZP, UPOSP and two bonds) while uzse.uz dated and priced
    every one of them. A carried close that DIFFERS is a session the mirror knows
    and the quote does not, and there the quote still waits.
    """
    day = market_dates._iso_trade_date(quote.get("trade_date"))
    close = quote.get("close_price")
    if not day or close is None:
        return
    row_day = market_dates._iso_trade_date(row.get("last_trade_date"))
    if not row_day and not _carries(row, close):
        row_day = market_dates._iso_trade_date(row.get("close_date"))
    if row_day and row_day > day:
        return

    row["last_price"] = close
    row["last_trade_date"] = day
    if quote.get("prev_close") is not None:
        row["close_price"] = quote["prev_close"]
        row["close_date"] = market_dates._iso_trade_date(quote.get("prev_close_date")) or row.get("close_date")
    for src, dst in (("open_price", "open"), ("high_price", "high"), ("low_price", "low")):
        # An older listing's range cannot describe the quote's newer session.
        # Only a second read of the SAME dated session may retain known OHLC.
        if quote.get(src) is not None or row_day != day:
            row[dst] = quote.get(src)
    if quote.get("turnover") is not None:
        row["volume"] = quote["turnover"]
    if quote.get("quantity") is not None:
        row["quantity"] = quote["quantity"]
    if quote.get("shares_outstanding"):
        row["shares_outstanding"] = quote["shares_outstanding"]
    shares = row.get("shares_outstanding")
    if shares and close:
        row["market_cap"] = shares * close
    # It traded — the registry's "no recent trades" tag describes an older world.
    row["inactive"] = None


def _exchange_url(isin: Any, is_bond: bool) -> str | None:
    """The exchange's own page for a security — the board's «источник» link.

    One shape, one place: rows reached the board from three sources and only two
    of them built this link, so the source column was empty for every row the
    live mirror carried (it sends ``url: null``).
    """
    code = str(isin or "").strip().upper()
    if not code:
        return None
    return f"https://uzse.uz/isu_infos/{'BND' if is_bond else 'STK'}?isu_cd={code}"


def _fill_source_urls(rows: list[dict[str, Any]]) -> int:
    """Give every row with an ISIN its exchange link, in place. Returns rows filled."""
    filled = 0
    for row in rows:
        if str(row.get("url") or "").strip():
            continue
        url = _exchange_url(row.get("isin"), str(row.get("type") or "").lower() == "bond")
        if url:
            row["url"] = url
            filled += 1
    return filled


def _quote_to_stock(quote: dict[str, Any]) -> dict[str, Any]:
    """Shape an exchange quote as a market-feed row for a security no feed carries."""
    isin = str(quote.get("isin") or "").upper()
    is_bond = str(quote.get("market") or "").upper() == "BND"
    close, shares = quote.get("close_price"), quote.get("shares_outstanding")
    return {
        "isin": isin,
        "ticker": quote.get("ticker"),
        "name": quote.get("name"),
        "type": "bond" if is_bond else "stock",
        "share_type": quote.get("share_type") or "ordinary",
        "close_price": quote.get("prev_close"),
        "close_date": market_dates._iso_trade_date(quote.get("prev_close_date")),
        "last_price": close,
        "last_trade_date": market_dates._iso_trade_date(quote.get("trade_date")),
        "open": quote.get("open_price"),
        "high": quote.get("high_price"),
        "low": quote.get("low_price"),
        "volume": quote.get("turnover"),
        "quantity": quote.get("quantity"),
        "trade_count": None,
        "security_type_text": None,
        "shares_outstanding": shares,
        "market_cap": (shares * close) if (shares and close) else quote.get("market_cap"),
        "url": _exchange_url(isin, is_bond),
    }


async def _build_board(security_type: str = "") -> dict[str, Any]:
    """The market board: the live feed, the listing registry and the exchange's
    own quotes merged into one set of rows.

    Extracted from the endpoint so every consumer sees the SAME board. /api/coverage
    used to report on the raw mirror instead, which made it structurally blind to the
    securities the mirror does not carry — the gap it exists to surface.
    """

    loop = asyncio.get_running_loop()
    mirror_available = bool(settings.UZSE_STOCK_API_BASE)
    payload: Any = {}
    try:
        if mirror_available:
            # Executor-wrapped: a sync HTTP call here stalled the whole event loop
            # (single worker) for up to 20s on the hottest endpoint.
            response = await loop.run_in_executor(None, partial(
                requests.get,
                f"{settings.UZSE_STOCK_API_BASE}/stocks",
                params={"type": security_type} if security_type else None,
                timeout=20,
            ))
            response.raise_for_status()
            payload = response.json()
    except requests.RequestException as exc:
        http.logger.warning("UZSE stock API unavailable; using stored listings and quotes: %s", exc)
        mirror_available = False
        payload = {}
    except ValueError as exc:
        http.logger.warning("UZSE stock API returned invalid JSON; using stored listings and quotes: %s", exc)
        mirror_available = False
        payload = {}

    stocks = payload.get("stocks") if isinstance(payload, dict) else []
    stocks_list = stocks if isinstance(stocks, list) else []

    # Name the rows the feed leaves unnamed BEFORE the catalog sync below, so the
    # securities table (and everything reading it — company pages, search, logos)
    # stores the name too instead of the feed's null.
    # Both reads are memoised; warming them off-thread is what keeps the single
    # worker's event loop free — the two callers below then hit the cache.
    issuer_names, _ = await asyncio.gather(
        loop.run_in_executor(None, _issuer_names),
        loop.run_in_executor(None, _registered_bond_isins),
    )
    _fill_names(stocks_list, issuer_names)
    # Before the sync below: the securities catalog is written from these rows,
    # so a bond the mirror called a share would be catalogued as one.
    _retype_registered_bonds(stocks_list)
    _fill_source_urls(stocks_list)

    # Background sync into securities DB (fire-and-forget). Copy the list so the
    # inactive-listing merge below cannot leak synthetic rows into the executor.
    if stocks_list:
        logos = settings._load_logos()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, partial(securities_store.sync_securities, list(stocks_list), logos))
        # Track the record (largest) daily turnover per stock over time.
        loop.run_in_executor(None, partial(securities_store.record_volume, list(stocks_list)))

    # Merge in listed-but-inactive issuers (openinfo RFB registry, pushed by the
    # collector) that the live feed omits, so they still show on the market board —
    # tagged inactive with their last-known trade. The registry mixes an issuer's
    # bonds in with its shares (openinfo has no security-kind field there), so route
    # each row by the securities catalog: bond tickers go to the bond view tagged
    # type=bond, everything else to the stock view — never bonds labeled as shares.
    merged = list(stocks_list)
    added_inactive = 0
    feed_tickers = {str(s.get("ticker") or "").upper() for s in stocks_list}
    feed_isins = {str(s.get("isin") or "").upper() for s in stocks_list if s.get("isin")}
    try:
        # These are SQLite-backed cache reads. Never perform them on the
        # event-loop thread: a collector holding the database lock otherwise
        # freezes every route (including /health), not just the market page.
        listings = await loop.run_in_executor(None, catalogue_market_store.get_all_listings)
    except Exception:
        http.logger.exception("market/stocks: listings merge read failed")
        listings = {}
    catalog: dict[str, dict] = {}
    if listings:
        try:
            catalog = await loop.run_in_executor(None, securities_store.get_securities_map)
        except Exception:
            http.logger.exception("market/stocks: securities catalog read failed")

    # The live uzse feed carries no market cap, so the mktCap/P/E/P/B columns sat
    # empty for every actively traded stock while the RFB registry (pushed by the
    # collector) already knows each line's shares outstanding. Join it onto live
    # rows and value the shares at the live price — the registry's own market_cap
    # (struck at the last collector run's price) is only a staleness fallback.
    listings_by_isin = {
        str(lst.get("isin") or "").upper(): lst
        for lst in listings.values() if lst.get("isin")
    }
    # The par value comes only from the registry — the live feed does not carry it
    # — so it is joined for EVERY row, including the ones that already have a
    # capitalisation and skip the loop below.
    for row in merged:
        if row.get("nominal") is None:
            lst = (listings.get(str(row.get("ticker") or "").upper())
                   or listings_by_isin.get(str(row.get("isin") or "").upper()))
            if lst and lst.get("nominal") is not None:
                row["nominal"] = lst["nominal"]
        row["nominal"] = corporate_actions.current_par(row.get("ticker"), row.get("nominal"))
    for row in merged:
        if row.get("market_cap"):
            continue
        lst = (listings.get(str(row.get("ticker") or "").upper())
               or listings_by_isin.get(str(row.get("isin") or "").upper()))
        if not lst:
            continue
        shares = lst.get("shares_outstanding")
        if row.get("shares_outstanding") is None and shares is not None:
            row["shares_outstanding"] = shares
            row["shares_source"] = "openinfo_listing"
        price = row.get("last_price") or row.get("close_price")
        if shares and price:
            row["market_cap"] = shares * price
        elif lst.get("market_cap"):
            row["market_cap"] = lst.get("market_cap")
            row["market_cap_source"] = "openinfo_listing"
            row["market_cap_source_url"] = "https://openinfo.uz/"
            row["market_cap_as_of"] = lst.get("updated_at")

    want_bonds = security_type == "bond"
    uncatalogued: list[dict[str, Any]] = []
    for tk, lst in listings.items():
        if tk in feed_tickers:
            continue
        isin = str(lst.get("isin") or "").upper()
        if isin and isin in feed_isins:
            continue
        sec = catalog.get(str(tk or "").upper()) or {}
        is_bond = sec.get("type") == "bond"
        if is_bond != want_bonds:
            continue
        row = _listing_to_stock(lst)
        if is_bond:
            row["type"] = "bond"
            # Registry fallback rows (issuer with empty info_rfb isin_codes) have
            # no ISIN of their own — take the bond's ISIN from the catalog.
            if not row.get("isin"):
                row["isin"] = sec.get("isin")
        # Registry rows carry no exchange link — build it from the ISIN so the
        # source column links to uzse.uz. (Live-feed rows get theirs below; the
        # mirror sends url=null for all of them.)
        if not row.get("url"):
            row["url"] = _exchange_url(row.get("isin"), is_bond)
        merged.append(row)
        added_inactive += 1
        if not sec:
            uncatalogued.append(row)

    # A registry line the catalog has never seen (DRBK, listed 28.08 with no
    # trade since) reached the board but not the securities table, so its
    # company page, search entry and logo waited for a live feed that no longer
    # exists. Catalogue it from the registry, typed by the bond register first
    # so a bond the registry mixes in is never stored as a share.
    if uncatalogued:
        _retype_registered_bonds(uncatalogued)
        loop.run_in_executor(None, partial(securities_store.sync_securities, list(uncatalogued), settings._load_logos()))

    # Lay the exchange's own session quotes over the board. This is what makes a
    # row say what the exchange says: the close it published, and the previous
    # close it measured the day's move against — which it CARRIES FORWARD through
    # sessions with no trades, so neither the execution feed nor the openinfo
    # registry can reproduce it. It also completes the board: the /stocks mirror
    # is a fixed 78-security universe, and the securities outside it were either
    # missing (KFSKP, EQQU) or priced from a week-old registry row (UQEQ shown at
    # 32 000 from 24.07 while the exchange closed it at 30 720, +20%).
    try:
        quotes = await loop.run_in_executor(None, catalogue_market_store.get_all_quotes)
    except Exception:
        http.logger.exception("market/stocks: quote cache read failed")
        quotes = {}
    quoted_added = 0
    if quotes:
        for row in merged:
            quote = quotes.get(str(row.get("isin") or "").upper())
            if quote:
                _apply_quote(row, quote)
        on_board = {str(r.get("isin") or "").upper() for r in merged if r.get("isin")}
        board_tickers = {str(r.get("ticker") or "").upper() for r in merged}
        for isin, quote in quotes.items():
            if isin in on_board or str(quote.get("ticker") or "").upper() in board_tickers:
                continue
            if (str(quote.get("market") or "").upper() == "BND") != want_bonds:
                continue
            merged.append(_quote_to_stock(quote))
            quoted_added += 1
        # A security the /stocks feed never carried is absent from the securities
        # catalog too, so its board row had no name, logo, sector or company page.
        # Having traded is the qualification: every row the exchange quoted gets
        # catalogued, whether it reached the board from a feed, the registry or
        # the quote itself.
        quoted_rows = [r for r in merged if str(r.get("isin") or "").upper() in quotes]
        _fill_names(quoted_rows, issuer_names)
        _fill_source_urls(quoted_rows)
        if quoted_rows:
            loop.run_in_executor(None, partial(securities_store.sync_securities, quoted_rows, settings._load_logos()))

    # Drop board-suppressed tickers (dormant registry lines) from the view. Applied
    # to the fully merged list so it holds regardless of source (live feed, the
    # inactive registry merge or the quote cache above); data itself is left
    # untouched. The ISIN is tested as well as the ticker because a quote-cache row
    # may have no ticker to test — that is how UZAL2 returned as a nameless tile
    # once its registry line was purged.
    if settings.BOARD_DENYLIST or DELISTED_ISINS:
        merged = [r for r in merged
                  if str(r.get("ticker") or "").upper() not in settings.BOARD_DENYLIST
                  and not is_delisted_isin(r.get("isin"))]
        added_inactive = sum(1 for r in merged if r.get("inactive"))

    # Again on the merged list: the registry and the quote cache append rows of
    # their own after the sync above, and the market-cap join runs over all of
    # them. The equities view then loses them; the «all» view keeps them, because
    # it is the everything board and they now say on it what they are.
    _retype_registered_bonds(merged)
    if security_type == "stock":
        bond_isins = await loop.run_in_executor(None, _registered_bond_isins)
        if bond_isins:
            merged = [r for r in merged
                      if str(r.get("isin") or "").upper() not in bond_isins]
            added_inactive = sum(1 for r in merged if r.get("inactive"))

    # Registry and quote-cache rows joined the board after the first pass; name
    # them too, so no row reaches the company column as a bare ISIN.
    _fill_names(merged, issuer_names)
    _fill_source_urls(merged)

    return http._json_safe({
        "ok": True,
        "source": ("uzse-stock-production" if mirror_available
                   else "stored-openinfo-listings+uzse-quotes"),
        "source_url": f"{settings.UZSE_STOCK_API_BASE}/stocks" if mirror_available else None,
        # The mirror stamps naive UTC; say so, or the browser reads it as local.
        "updated_at": market_dates._as_utc_iso(payload.get("updated_at")) if isinstance(payload, dict) else None,
        "count": len(merged),
        "inactive_listings": added_inactive,
        "type": security_type or "all",
        "stocks": merged,
    })


MARKET_BOARD_CACHE_TTL_SEC = max(
    0, int(os.getenv("MARKET_BOARD_CACHE_TTL_SEC", "60")),
)


MARKET_BOARD_BROWSER_TTL_SEC = max(
    0, int(os.getenv("MARKET_BOARD_BROWSER_TTL_SEC", "15")),
)


_MARKET_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


_MARKET_BOARD_LOCKS: dict[str, asyncio.Lock] = {}


_MARKET_BOARD_REFRESH_TASKS: dict[str, asyncio.Task[Any]] = {}


def _reset_market_board_cache() -> None:
    """Drop process-local board snapshots and loop-bound locks."""
    for task in tuple(_MARKET_BOARD_REFRESH_TASKS.values()):
        task.cancel()
    _MARKET_BOARD_REFRESH_TASKS.clear()
    _MARKET_BOARD_CACHE.clear()
    _MARKET_BOARD_LOCKS.clear()


async def _refresh_market_board_in_background(security_type: str) -> None:
    """Refresh one stale snapshot without making a reader wait for UZSE."""
    try:
        await _cached_market_board(security_type, refresh=True)
    except Exception:
        # Availability wins over freshness here: keep serving the last complete
        # snapshot and let a later request retry the upstream feed.
        http.logger.exception("background market-board refresh failed for type=%s", security_type)


def _schedule_market_board_refresh(security_type: str) -> None:
    """Start at most one retained background refresh task per cache burst."""
    existing = _MARKET_BOARD_REFRESH_TASKS.get(security_type)
    if existing and not existing.done():
        return
    task = asyncio.create_task(_refresh_market_board_in_background(security_type))
    _MARKET_BOARD_REFRESH_TASKS[security_type] = task

    def discard(completed: asyncio.Task[Any]) -> None:
        if _MARKET_BOARD_REFRESH_TASKS.get(security_type) is completed:
            _MARKET_BOARD_REFRESH_TASKS.pop(security_type, None)

    task.add_done_callback(discard)


async def _cached_market_board(security_type: str, *, refresh: bool = False) -> dict[str, Any]:
    """Reuse a recently assembled board and collapse concurrent cold requests.

    Building the board starts with a remote mirror request and then joins several
    local catalogs.  A burst of visitors used to repeat that entire path once per
    browser.  The exchange feed refreshes on a schedule, so a short process-local
    snapshot is both fresher than that schedule and much faster for readers.
    """
    now = time.monotonic()
    cached = _MARKET_BOARD_CACHE.get(security_type)
    if not refresh and cached:
        if now - cached[0] >= MARKET_BOARD_CACHE_TTL_SEC:
            # Stale-while-revalidate: the upstream feed is allowed 20 seconds,
            # but a previously healthy board should never turn that delay into
            # a blank table for readers.
            _schedule_market_board_refresh(security_type)
        return cached[1]

    observed_at = cached[0] if cached else None
    lock = _MARKET_BOARD_LOCKS.setdefault(security_type, asyncio.Lock())
    async with lock:
        # Another request may have completed the same refresh while this one was
        # waiting.  Reuse it even for an explicit refresh: one upstream pull is
        # enough for all requests that arrived in the same burst.
        current = _MARKET_BOARD_CACHE.get(security_type)
        if current and (observed_at is None or current[0] > observed_at):
            return current[1]
        if not refresh and current and time.monotonic() - current[0] < MARKET_BOARD_CACHE_TTL_SEC:
            return current[1]

        payload = await _build_board(security_type)
        _MARKET_BOARD_CACHE[security_type] = (time.monotonic(), payload)
        return payload
