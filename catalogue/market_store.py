"""Persist and query quotes, sessions, listings, and market history."""
from __future__ import annotations
from typing import Any
from typing import Sequence

from datetime import date
from datetime import timedelta
from delisted import DELISTED_ISINS
from delisted import DELISTED_TICKERS
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import dbx
import os
import re


_TRADE_STAT_KEYS = ("total_value", "total_qty", "trade_count", "avg_price",
                    "largest_qty", "largest_value", "largest_pct_value", "largest_pct_qty")


def bulk_upsert_trade_stats(rows: list[dict], trade_date: str | None = None) -> int:
    """Overwrite the latest-day per-ISIN trade statistics cache.

    A security's stats only ever move FORWARD in time: the backfill path derives
    a security's "last trading day" from the board, and a board row that lags (or
    an openinfo archive that answers for the wrong day) would otherwise replace a
    fresh session with an older one, leaving turnover that belongs to no quote on
    the page. Rows dated before what is already stored are skipped, not written.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    conn = catalogue_storage.get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                isin = str(r.get("isin") or "").strip().upper()
                if not isin:
                    continue
                cur = conn.execute(
                    """
                    INSERT INTO catalog_trade_stats
                        (isin, trade_date, total_value, total_qty, trade_count, avg_price,
                         largest_qty, largest_value, largest_pct_value, largest_pct_qty,
                         open_price, high_price, low_price, close_price,
                         block_count, block_qty, block_value, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(isin) DO UPDATE SET
                        trade_date=excluded.trade_date, total_value=excluded.total_value,
                        total_qty=excluded.total_qty, trade_count=excluded.trade_count,
                        avg_price=excluded.avg_price, largest_qty=excluded.largest_qty,
                        largest_value=excluded.largest_value,
                        largest_pct_value=excluded.largest_pct_value,
                        largest_pct_qty=excluded.largest_pct_qty,
                        open_price=excluded.open_price, high_price=excluded.high_price,
                        low_price=excluded.low_price, close_price=excluded.close_price,
                        block_count=excluded.block_count, block_qty=excluded.block_qty,
                        block_value=excluded.block_value,
                        updated_at=datetime('now')
                    WHERE excluded.trade_date >= catalog_trade_stats.trade_date
                    """,
                    (isin, str(r.get("trade_date") or trade_date or ""),
                     _num(r.get("total_value")), _num(r.get("total_qty")),
                     int(_num(r.get("trade_count")) or 0), _num(r.get("avg_price")),
                     _num(r.get("largest_qty")), _num(r.get("largest_value")),
                     _num(r.get("largest_pct_value")), _num(r.get("largest_pct_qty")),
                     _num(r.get("open_price")), _num(r.get("high_price")),
                     _num(r.get("low_price")), _num(r.get("close_price")),
                     (int(_num(r.get("block_count")) or 0) or None),
                     _num(r.get("block_qty")), _num(r.get("block_value"))),
                )
                n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    finally:
        conn.close()
    return n


def trade_stats_as_history(rows: list[dict], trade_date: str | None = None) -> list[dict]:
    """The day statistics restated as quote-history rows.

    ``catalog_trade_stats`` keeps ONE row per security — the latest session — so
    everything that made a session readable (its open, its high and low, how many
    deals made it up, the largest of them) was thrown away the moment the next
    session arrived. That is why the board could summarise a day and not a month:
    the month's sessions were stored as bare closes.

    This is the same numbers, banked per session, so tomorrow's «за месяц» is
    made of thirty real sessions rather than one. Session figures only —
    negotiated (block) deals are already excluded upstream and must stay out.
    """
    out: list[dict] = []
    for r in rows or []:
        isin = str(r.get("isin") or "").strip().upper()
        day = str(r.get("trade_date") or trade_date or "").strip()
        if not isin or not day:
            continue
        out.append({
            "isin": isin,
            "trade_date": day,
            "close_price": r.get("close_price"),
            "quantity": r.get("total_qty"),
            "turnover": r.get("total_value"),
            "open_price": r.get("open_price"),
            "high_price": r.get("high_price"),
            "low_price": r.get("low_price"),
            "trade_count": r.get("trade_count"),
            "largest_value": r.get("largest_value"),
            "largest_qty": r.get("largest_qty"),
        })
    return out


def get_all_trade_stats() -> dict[str, dict[str, Any]]:
    """Return the cached latest-day trade statistics per ISIN: {isin: {...}}."""
    conn = catalogue_storage.get_catalog_conn()
    rows = conn.execute(
        """SELECT isin, trade_date, total_value, total_qty, trade_count, avg_price,
                  largest_qty, largest_value, largest_pct_value, largest_pct_qty,
                  open_price, high_price, low_price, close_price,
                  block_count, block_qty, block_value, updated_at
           FROM catalog_trade_stats"""
    ).fetchall()
    conn.close()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = dict(r)
        # VWAP on read (ТЗ §3.4/§3.8): volume-weighted price = turnover / quantity.
        tv, tq = d.get("total_value"), d.get("total_qty")
        d["vwap"] = round(tv / tq, 2) if (tv and tq) else None
        out[r["isin"]] = d
    return out


_QUOTE_COLS = (
    "ticker", "name", "market", "share_type", "trade_date", "close_price", "prev_close",
    "prev_close_date", "change_value", "change_percent", "open_price", "high_price",
    "low_price", "quantity", "turnover", "shares_outstanding", "market_cap",
)


def bulk_upsert_quotes(rows: list[dict]) -> int:
    """Store the exchange's session quotes, newest session wins.

    Forward-only, for the same reason ``bulk_upsert_trade_stats`` is: a quote is
    written only for a session the security actually traded in, and a re-read of
    an older page (or a run that starts before the day's first execution) must
    never replace a fresh session with a stale one.

    A LATER session replaces the row outright. The SAME session may only add to
    it: the exchange publishes a finished session's close, change, quantity and
    turnover in its daily history, but not that session's open/high/low, so the
    morning run that settles yesterday's numbers carries no OHLC — and writing
    those NULLs over the columns the 16:10 run captured would lose them to a
    read that knew strictly less.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    numeric = {"close_price", "prev_close", "change_value", "change_percent", "open_price",
               "high_price", "low_price", "quantity", "turnover", "shares_outstanding",
               "market_cap"}
    assignments = ", ".join(
        f"{c}=CASE WHEN excluded.trade_date > catalog_quotes.trade_date "
        f"THEN excluded.{c} ELSE COALESCE(excluded.{c}, catalog_quotes.{c}) END"
        for c in _QUOTE_COLS)
    conn = catalogue_storage.get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                isin = str(r.get("isin") or "").strip().upper()
                day = str(r.get("trade_date") or "").strip()
                if not isin or not day:
                    continue
                values = [_num(r.get(c)) if c in numeric else (r.get(c) or None)
                          for c in _QUOTE_COLS]
                cur = conn.execute(
                    f"""
                    INSERT INTO catalog_quotes (isin, {', '.join(_QUOTE_COLS)}, updated_at)
                    VALUES ({','.join('?' * (len(_QUOTE_COLS) + 1))}, datetime('now'))
                    ON CONFLICT(isin) DO UPDATE SET {assignments}, updated_at=datetime('now')
                    WHERE excluded.trade_date >= catalog_quotes.trade_date
                    """,
                    [isin, *values],
                )
                n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    finally:
        conn.close()
    return n


_QUOTE_HISTORY_COLS = ("close_price", "change_value", "quantity", "turnover")


_QUOTE_HISTORY_DETAIL_COLS = ("open_price", "high_price", "low_price",
                              "trade_count", "largest_value", "largest_qty")


def bulk_upsert_quote_history(rows: list[dict]) -> int:
    """Store settled daily closes, one statement per batch.

    Row-at-a-time is what took the catalog register to a 120-second timeout on
    Postgres (7670 statements for 7670 rows). This writes ~2300 rows — every
    security's last ~21 sessions — on every collector run, so it batches or it
    does not ship: one executemany, and the round trip is the cost, not the row.

    The batch is deduplicated on (isin, trade_date) first. PostgreSQL refuses an
    ON CONFLICT that would touch the same key twice in one statement, and the
    same session legitimately arrives twice in a run — a security read once for
    its live quote and again for a settled row lands both.

    A real value wins over an older one on a repeated session, deliberately: a
    row read mid-session is provisional and a later read of the same day is
    strictly more settled. A NULL never wins — see the ON CONFLICT below.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def _day(v: Any) -> str | None:
        """YYYYMMDD, the form the catalog stores.

        Two sources feed this table and they disagree: the exchange page's daily
        history is already YYYYMMDD, openinfo's conclusions archive is ISO. Both
        sort correctly on their own and neither sorts against the other, so the
        normalisation happens here rather than at each call site — a series half
        in one form would order by its leading digits and draw a scrambled line.
        """
        s = str(v or "").strip()
        if re.fullmatch(r"\d{8}", s):
            return s
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
        return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else None

    seen: dict[tuple[str, str], list[Any]] = {}
    for r in rows or []:
        isin = str(r.get("isin") or "").strip().upper()
        day = _day(r.get("trade_date") or r.get("date"))
        if not isin or not day:
            continue
        seen[(isin, day)] = [isin, day, _num(r.get("close_price") if r.get("close_price") is not None
                                            else r.get("close")),
                             _num(r.get("change_value") if r.get("change_value") is not None
                                  else r.get("change")),
                             _num(r.get("quantity") if r.get("quantity") is not None
                                  else r.get("total_qty")),
                             _num(r.get("turnover") if r.get("turnover") is not None
                                  else r.get("total_value")),
                             _num(r.get("open_price") if r.get("open_price") is not None
                                  else r.get("open")),
                             _num(r.get("high_price") if r.get("high_price") is not None
                                  else r.get("high")),
                             _num(r.get("low_price") if r.get("low_price") is not None
                                  else r.get("low")),
                             _num(r.get("trade_count")),
                             _num(r.get("largest_value")), _num(r.get("largest_qty"))]
    if not seen:
        return 0
    # COALESCE on every column, not last-write-wins: three sources now feed this
    # table and each sees a different part of a session — the exchange page has
    # the close and the turnover but no trade count, the day statistics have the
    # count and the largest deal, openinfo's archive has the OHLC. A source
    # writing NULL is saying «I cannot see this», never «this is not there», and
    # under plain last-write-wins the day statistics landing after the page push
    # would have blanked every close on the board. A real value still always
    # wins over an older one, which is what settling a provisional session needs.
    assignments = ", ".join(
        f"{c}=COALESCE(excluded.{c}, catalog_quote_history.{c})"
        for c in _QUOTE_HISTORY_COLS + _QUOTE_HISTORY_DETAIL_COLS)
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            all_cols = _QUOTE_HISTORY_COLS + _QUOTE_HISTORY_DETAIL_COLS
            conn.executemany(
                f"""
                INSERT INTO catalog_quote_history
                    (isin, trade_date, {', '.join(all_cols)}, updated_at)
                VALUES ({','.join('?' * (len(all_cols) + 2))}, datetime('now'))
                ON CONFLICT(isin, trade_date) DO UPDATE SET
                    {assignments}, updated_at=datetime('now')
                """,
                list(seen.values()),
            )
    finally:
        conn.close()
    return len(seen)


def get_quote_history(isins: Sequence[str], days: int = 30) -> dict[str, list[dict[str, Any]]]:
    """Recent settled closes for several securities, oldest first, keyed by ISIN.

    One query for the whole set — the point of storing this at all was to stop
    a list of securities costing one upstream request per row.
    """
    codes = [str(i).strip().upper() for i in (isins or []) if str(i or "").strip()]
    if not codes:
        return {}
    days = max(1, min(int(days or 30), 3650))
    placeholders = ",".join("?" * len(codes))
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT isin, trade_date, close_price, change_value, quantity, turnover,
                   open_price, high_price, low_price, trade_count,
                   largest_value, largest_qty
            FROM catalog_quote_history
            WHERE isin IN ({placeholders})
            ORDER BY isin, trade_date
            """,
            codes,
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(r["isin"], []).append(dict(r))
    # The window is the last N SESSIONS the security has, not the last N calendar
    # days: a quiet security would otherwise return an empty series and read as
    # "no data" when what it did was not trade.
    return {isin: series[-days:] for isin, series in out.items()}


_INTRADAY_COLS = ("open_price", "high_price", "low_price", "close_price",
                  "quantity", "turnover")


INTRADAY_KEEP_DAYS = int(os.getenv("INTRADAY_KEEP_DAYS", "60"))


def bulk_upsert_intraday_history(rows: list[dict]) -> int:
    """Store hourly bars from the exchange's executions log, one statement per batch.

    Same shape and same reasons as ``bulk_upsert_quote_history`` above: one
    executemany (round trips are the Postgres cost model), deduplicated on the
    full key first (PG refuses one statement touching a key twice), last write
    wins (a later read of the same session is strictly more settled — the log
    grows through the day and is immutable after it).

    Also prunes bars older than ``INTRADAY_KEEP_DAYS``: the log feeds a day and
    a week view, and unlike daily closes this table gains hundreds of rows per
    session fleet-wide with no reader for the old ones.
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    seen: dict[tuple[str, str, int], list[Any]] = {}
    for r in rows or []:
        isin = str(r.get("isin") or "").strip().upper()
        day = str(r.get("trade_date") or r.get("date") or "").strip().replace("-", "")
        try:
            hour = int(r.get("hour"))
        except (TypeError, ValueError):
            continue
        if not isin or not re.fullmatch(r"\d{8}", day) or not 0 <= hour <= 23:
            continue
        seen[(isin, day, hour)] = [isin, day, hour,
                                   _num(r.get("open_price") or r.get("open")),
                                   _num(r.get("high_price") or r.get("high")),
                                   _num(r.get("low_price") or r.get("low")),
                                   _num(r.get("close_price") or r.get("close")),
                                   _num(r.get("quantity")), _num(r.get("turnover"))]
    if not seen:
        return 0
    assignments = ", ".join(f"{c}=excluded.{c}" for c in _INTRADAY_COLS)
    cutoff = (date.today() - timedelta(days=INTRADAY_KEEP_DAYS)).strftime("%Y%m%d")
    conn = catalogue_storage.get_catalog_conn()
    try:
        with conn:
            conn.executemany(
                f"""
                INSERT INTO catalog_intraday_history
                    (isin, trade_date, hour, {', '.join(_INTRADAY_COLS)}, updated_at)
                VALUES ({','.join('?' * (len(_INTRADAY_COLS) + 3))}, datetime('now'))
                ON CONFLICT(isin, trade_date, hour) DO UPDATE SET
                    {assignments}, updated_at=datetime('now')
                """,
                list(seen.values()),
            )
            conn.execute("DELETE FROM catalog_intraday_history WHERE trade_date < ?",
                         (cutoff,))
    finally:
        conn.close()
    return len(seen)


def get_intraday_history(isin: str, days: int = 7) -> list[dict[str, Any]]:
    """Hourly bars for one security over the last ``days`` CALENDAR days, oldest first.

    Calendar days, not sessions, unlike ``get_quote_history``: the hourly view
    answers "what happened this week", and stretching a quiet security's last
    active week under a «1Н» label would date the chart wrong. The chart falls
    back to daily closes for the days this table has nothing for.
    """
    code = str(isin or "").strip().upper()
    if not code:
        return []
    days = max(1, min(int(days or 7), INTRADAY_KEEP_DAYS))
    # Inclusive of today: days=1 is TODAY's bars, not today's and yesterday's.
    cutoff = (date.today() - timedelta(days=days - 1)).strftime("%Y%m%d")
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT trade_date, hour, {', '.join(_INTRADAY_COLS)}
            FROM catalog_intraday_history
            WHERE isin = ? AND trade_date >= ?
            ORDER BY trade_date, hour
            """,
            (code, cutoff),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_all_quotes() -> dict[str, dict[str, Any]]:
    """Every stored exchange quote, keyed by ISIN."""
    conn = catalogue_storage.get_catalog_conn()
    try:
        rows = conn.execute(
            f"SELECT isin, {', '.join(_QUOTE_COLS)}, updated_at FROM catalog_quotes"
        ).fetchall()
    finally:
        conn.close()
    return {r["isin"]: dict(r) for r in rows}


_LISTING_COLS = (
    "ticker", "isin", "name", "share_type", "listing_date", "shares_outstanding",
    # «Номинальная стоимость» — the exchange states it as `parval` on the security
    # card for both shares and bonds. Nullable: a card that leaves it at zero has
    # not stated a par, and a zero par is not a fact about any security.
    "nominal",
    "reference_price", "last_price", "last_trade_date", "open_price", "high_price",
    "low_price", "volume", "market_cap",
)


def bulk_upsert_listings(rows: list[dict]) -> int:
    """Overwrite the exchange-listing registry from an externally-computed batch.

    Pushed by the collector (where openinfo is reachable) so prod can show
    listed-but-inactive issuers on the market board even though they are missing
    from the live uzse-stock feed. Keyed by security ticker (ordinary + preferred
    lines are distinct rows, e.g. KSCM / KSCMP).
    """
    def _num(v: Any) -> float | None:
        try:
            return None if v is None or v == "" else float(v)
        except (TypeError, ValueError):
            return None

    conn = catalogue_storage.get_catalog_conn()
    n = 0
    try:
        with conn:
            for r in rows or []:
                ticker = str(r.get("ticker") or "").strip().upper()
                if not ticker or ticker in DELISTED_TICKERS:
                    # Deleted from the site: an older collector build still emits
                    # these, and the upsert would silently resurrect them.
                    continue
                conn.execute(
                    """
                    INSERT INTO catalog_listings
                        (ticker, isin, name, share_type, listing_date, shares_outstanding,
                         nominal,
                         reference_price, last_price, last_trade_date, open_price, high_price,
                         low_price, volume, market_cap, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(ticker) DO UPDATE SET
                        isin=excluded.isin, name=excluded.name, share_type=excluded.share_type,
                        listing_date=excluded.listing_date,
                        shares_outstanding=excluded.shares_outstanding,
                        -- A collector build from before the column existed sends
                        -- nothing for the par, and that nothing must not erase it.
                        nominal=COALESCE(excluded.nominal, catalog_listings.nominal),
                        reference_price=excluded.reference_price, last_price=excluded.last_price,
                        last_trade_date=excluded.last_trade_date, open_price=excluded.open_price,
                        high_price=excluded.high_price, low_price=excluded.low_price,
                        volume=excluded.volume, market_cap=excluded.market_cap,
                        updated_at=datetime('now')
                    """,
                    (ticker, str(r.get("isin") or "") or None, str(r.get("name") or "") or None,
                     str(r.get("share_type") or "") or None, str(r.get("listing_date") or "") or None,
                     _num(r.get("shares_outstanding")), _num(r.get("nominal")),
                     _num(r.get("reference_price")),
                     _num(r.get("last_price")), str(r.get("last_trade_date") or "") or None,
                     _num(r.get("open_price")), _num(r.get("high_price")), _num(r.get("low_price")),
                     _num(r.get("volume")), _num(r.get("market_cap"))),
                )
                n += 1
    finally:
        conn.close()
    return n


def get_all_listings() -> dict[str, dict[str, Any]]:
    """Return the cached exchange-listing registry per ticker: {ticker: {...}}."""
    conn = catalogue_storage.get_catalog_conn()
    rows = conn.execute(
        f"SELECT {', '.join(_LISTING_COLS)}, updated_at FROM catalog_listings"
    ).fetchall()
    conn.close()
    return {r["ticker"]: dict(r) for r in rows
            if r["ticker"] not in DELISTED_TICKERS}


_PURGE_TABLES = (
    ("catalog_listings", "ticker"),
    ("catalog_quotes", "ticker"),
    ("catalog_companies", "ticker"),
    ("catalog_reports", "ticker"),
    ("catalog_new_reports", "ticker"),
    ("catalog_ratios", "ticker"),
    ("catalog_financials", "ticker"),
    ("facts", "entity_id"),        # org_map rows are keyed by ticker, not org id
    ("news_entities", "ticker"),   # issuer tags on news stories (story itself stays)
)


def purge_delisted(tickers: set[str] | frozenset[str] | None = None) -> dict[str, int]:
    """Delete every trace of the delisted securities from the catalog DB.

    ``bulk_upsert_listings`` is upsert-only — it never drops rows the collector
    stopped emitting — so filtering the collector alone would leave these tickers
    in a persisted volume forever. This is the deletion half: idempotent, safe to
    run on every boot, and cheap when there is nothing left to remove. Returns
    ``{table: rows_deleted}`` for the tables that actually gave up rows.
    """
    targets = {t.upper() for t in (tickers if tickers is not None else DELISTED_TICKERS)}
    if not targets:
        return {}
    placeholders = ",".join("?" * len(targets))
    params = sorted(targets)
    deleted: dict[str, int] = {}
    conn = catalogue_storage.get_catalog_conn()
    try:
        # Through dbx, not by reading SQLite's own catalog table: that table does
        # not exist on Postgres, so since the cutover this raised before deleting
        # anything and the purge only ever *looked* done — the read filters were
        # hiding the very rows it had failed to remove.
        existing = set(dbx.tables(conn))
        with conn:
            # Trade stats are keyed by ISIN, so resolve them through the registry
            # rows before those rows are deleted and the link is lost.
            if {"catalog_listings", "catalog_trade_stats"} <= existing:
                isins = [r[0] for r in conn.execute(
                    f"SELECT isin FROM catalog_listings "
                    f"WHERE UPPER(ticker) IN ({placeholders}) AND isin IS NOT NULL AND isin != ''",
                    params)]
                if isins:
                    cur = conn.execute(
                        f"DELETE FROM catalog_trade_stats WHERE isin IN ({','.join('?' * len(isins))})",
                        isins)
                    if cur.rowcount > 0:
                        deleted["catalog_trade_stats"] = cur.rowcount
            for table, column in _PURGE_TABLES:
                if table not in existing:
                    continue
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE UPPER({column}) IN ({placeholders})", params)
                if cur.rowcount > 0:
                    deleted[table] = cur.rowcount
            # What a purge by ticker cannot reach. Both these tables are keyed by
            # ISIN, and the row holding both keys — the registry line — is the one
            # just deleted, so a quote for a security the mirror never named has
            # nothing left to resolve through. Left behind it survives every boot
            # and walks back onto the board without a ticker. Only for the standard
            # whole-set purge: a caller naming its own tickers gets exactly those.
            if tickers is None and DELISTED_ISINS:
                isins = sorted(DELISTED_ISINS)
                marks = ",".join("?" * len(isins))
                # The daily-close store is keyed by ISIN alone, so it outlives the
                # registry row too — a removed security's price series has no
                # reader left, but keeping it would mean the site still stores the
                # history of a company it no longer shows.
                for table in ("catalog_quotes", "catalog_trade_stats", "catalog_quote_history"):
                    if table not in existing:
                        continue
                    cur = conn.execute(
                        f"DELETE FROM {table} WHERE UPPER(isin) IN ({marks})", isins)
                    if cur.rowcount > 0:
                        deleted[table] = deleted.get(table, 0) + cur.rowcount
    finally:
        conn.close()
    if deleted:
        catalogue_settings.logger.info("purged delisted securities: %s", deleted)
    return deleted
