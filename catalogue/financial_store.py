"""Persist financial snapshots and bootstrap an empty cache."""
from __future__ import annotations
import catalogue.ratios as catalogue_ratios
from typing import Any
import sqlite3

import catalogue.codecs as catalogue_codecs
import catalogue.periods as catalogue_periods
import catalogue.settings as catalogue_settings
import catalogue.storage as catalogue_storage
import json
import os
import threading


def upsert_ratio_cache(ticker: str, form: str, year: int, quarter: int, metrics: dict[str, Any]) -> None:

    conn = catalogue_storage.get_catalog_conn()

    with conn:

        conn.execute(

            """

            INSERT INTO catalog_ratios

                (ticker, form, year, quarter, roa, roe, net_margin, debt_ratio, debt_to_equity, updated_at)

            VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))

            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET

                roa=excluded.roa, roe=excluded.roe, net_margin=excluded.net_margin,

                debt_ratio=excluded.debt_ratio, debt_to_equity=excluded.debt_to_equity,

                updated_at=datetime('now')

            """,

            (ticker, form, year, quarter,

             metrics.get("ROA"), metrics.get("ROE"), metrics.get("net_margin"),

             metrics.get("debt_ratio"), metrics.get("debt_to_equity")),

        )

    conn.close()

    catalogue_ratios.invalidate_ratios_cache()


_FINANCIAL_KEYS = ("revenue", "gross_profit", "cash", "total_liabilities",

                   "net_income", "operating_income", "operating_expenses")


def upsert_financials_cache(ticker: str, form: str, year: int, quarter: int,

                            values: dict[str, Any], report_id: int | None = None) -> None:

    """Store the six NSBU headline indicators for a ticker/period.



    Every value here is parsed from the (year, quarter) statement itself, so the

    row's ``field_periods`` is cleared: any stale provenance from a previous

    enrichment no longer describes what is stored.



    A period that has not ended yet is refused here as it is on the push path —

    every writer into this table applies the same rule, or the one that does not

    becomes the way a fabricated period gets in.

    """

    if catalogue_periods._is_future_period(year, quarter):

        catalogue_settings.logger.warning("financials: rejected %s %s Q%s — period has not ended", ticker, year, quarter)

        return

    conn = catalogue_storage.get_catalog_conn()

    with conn:

        conn.execute(

            """

            INSERT INTO catalog_financials

                (ticker, form, year, quarter, revenue, gross_profit, cash,

                 total_liabilities, net_income, operating_income, operating_expenses,

                 total_assets, total_equity,

                 current_assets, current_liabilities, inventories,

                 field_periods, report_id, updated_at)

            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))

            ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET

                revenue=excluded.revenue, gross_profit=excluded.gross_profit,

                cash=excluded.cash, total_liabilities=excluded.total_liabilities,

                net_income=excluded.net_income, operating_income=excluded.operating_income,

                operating_expenses=excluded.operating_expenses,

                total_assets=excluded.total_assets, total_equity=excluded.total_equity,

                -- A form with no current section (the bank balance) states none

                -- of these, and a re-parse of one must not blank what another

                -- form's filing established for an earlier period.

                current_assets=COALESCE(excluded.current_assets,

                                        catalog_financials.current_assets),

                current_liabilities=COALESCE(excluded.current_liabilities,

                                             catalog_financials.current_liabilities),

                inventories=COALESCE(excluded.inventories, catalog_financials.inventories),

                field_periods=excluded.field_periods,

                -- A re-parse that cannot name its source must not erase the

                -- link the previous one established.

                report_id=COALESCE(excluded.report_id, catalog_financials.report_id),

                updated_at=datetime('now')

            """,

            (ticker, form, year, quarter,

             values.get("revenue"), values.get("gross_profit"), values.get("cash"),

             values.get("total_liabilities"), values.get("net_income"),

             values.get("operating_income"), values.get("operating_expenses"),

             values.get("total_assets"),

             values.get("total_equity", values.get("equity")),

             values.get("current_assets"), values.get("current_liabilities"),

             values.get("inventories"),

             catalogue_codecs._encode_field_periods(values.get("field_periods")), report_id),

        )

    conn.close()


_FINANCIALS_SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "financials_seed.json")


_seed_lock = threading.Lock()


_seeded = False


def _maybe_seed_financials(conn: sqlite3.Connection, form: str = "NSBU") -> None:

    """Bootstrap catalog_financials from the bundled snapshot when it's empty.



    Only fills when no rows exist for the form — never overwrites values produced

    by a live sync. Guarded so it runs at most once per process.

    """

    global _seeded

    if form != "NSBU" or _seeded:

        return

    with _seed_lock:

        if _seeded:

            return

        try:

            n = conn.execute("SELECT COUNT(*) FROM catalog_financials WHERE form=?", (form,)).fetchone()[0]

            if not n and os.path.exists(_FINANCIALS_SEED_PATH):

                with open(_FINANCIALS_SEED_PATH, encoding="utf-8") as f:

                    rows = (json.load(f) or {}).get("rows") or []

                with conn:

                    for r in rows:

                        conn.execute(

                            """

                            INSERT INTO catalog_financials

                                (ticker, form, year, quarter, revenue, gross_profit, cash,

                                 total_liabilities, net_income, operating_income, updated_at)

                            VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))

                            ON CONFLICT DO NOTHING

                            """,

                            (r.get("ticker"), r.get("form") or form, r.get("year") or 0,

                             r.get("quarter") or 0, r.get("revenue"), r.get("gross_profit"),

                             r.get("cash"), r.get("total_liabilities"), r.get("net_income"),

                             r.get("operating_income")),

                        )

                catalogue_settings.logger.info("Seeded catalog_financials from snapshot: %d rows", len(rows))

        except Exception:

            catalogue_settings.logger.exception("financials seed failed")

        finally:

            _seeded = True


def bulk_upsert_financials(rows: list[dict], form: str = "NSBU") -> int:

    """Overwrite the financials cache from an externally-computed batch.



    Used by the admin push endpoint so a collector running where openinfo IS

    reachable can refresh prod (whose datacenter IP openinfo blocks). Unlike the

    seed loader, this overwrites existing values (ON CONFLICT DO UPDATE).

    """

    _num = catalogue_codecs._financials_num

    _bal_total = catalogue_codecs._balance_total_fallback



    conn = catalogue_storage.get_catalog_conn()

    n = 0

    try:

        with conn:

            for r in rows or []:

                ticker = str(r.get("ticker") or "").strip().upper()

                if not ticker:

                    continue

                period = catalogue_codecs._financials_period(r)

                if period is None:

                    continue

                year, quarter = period

                conn.execute(

                    """

                    INSERT INTO catalog_financials

                        (ticker, form, year, quarter, revenue, gross_profit, cash,

                         total_liabilities, net_income, operating_income, operating_expenses,

                         total_assets, total_equity,

                         current_assets, current_liabilities, inventories,

                         noninterest_income, org_type, balance_period,

                         field_periods, prior_period, updated_at)

                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))

                    ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET

                        revenue=excluded.revenue, gross_profit=excluded.gross_profit,

                        cash=excluded.cash, total_liabilities=excluded.total_liabilities,

                        net_income=excluded.net_income, operating_income=excluded.operating_income,

                        operating_expenses=COALESCE(excluded.operating_expenses,

                                                    catalog_financials.operating_expenses),

                        current_assets=COALESCE(excluded.current_assets,

                                                catalog_financials.current_assets),

                        current_liabilities=COALESCE(excluded.current_liabilities,

                                                     catalog_financials.current_liabilities),

                        inventories=COALESCE(excluded.inventories,

                                             catalog_financials.inventories),

                        noninterest_income=excluded.noninterest_income,

                        -- An upsert that says nothing about the form or the

                        -- balance must not erase what a reconcile established.

                        -- The balance totals likewise: a pusher still running

                        -- code from before the columns existed sends nothing

                        -- for them, and that nothing must not blank the

                        -- backfilled history.

                        total_assets=COALESCE(excluded.total_assets, catalog_financials.total_assets),

                        total_equity=COALESCE(excluded.total_equity, catalog_financials.total_equity),

                        org_type=COALESCE(excluded.org_type, catalog_financials.org_type),

                        balance_period=COALESCE(excluded.balance_period,

                                                catalog_financials.balance_period),

                        field_periods=excluded.field_periods,

                        prior_period=excluded.prior_period,

                        updated_at=datetime('now')

                    """,

                    (ticker, str(r.get("form") or form), year, quarter,

                     _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("cash")),

                     _num(r.get("total_liabilities")), _num(r.get("net_income")),

                     _num(r.get("operating_income")),

                     _num(r.get("operating_expenses")),

                     _bal_total(r, "total_assets", "assets_end"),

                     _bal_total(r, "total_equity", "equity_end"),

                     _num(r.get("current_assets")), _num(r.get("current_liabilities")),

                     _num(r.get("inventories")),

                     _num(r.get("noninterest_income")),

                     (str(r.get("org_type")) if r.get("org_type") else None),

                     catalogue_codecs._encode_balance_period(r.get("balance")),

                     catalogue_codecs._encode_field_periods(r.get("field_periods")),

                     catalogue_codecs._encode_prior_period(r.get("prior"))),

                )

                n += 1

    finally:

        conn.close()

    return n


def bulk_replace_financials(rows: list[dict], form: str = "NSBU") -> int:

    """Make the supplied rows the *authoritative* set of periods for their tickers.



    Unlike :func:`bulk_upsert_financials` (which only upserts one (ticker, form,

    year, quarter) key and leaves every other period row alone), this also clears

    the periods stored ABOVE the newest one supplied. It is used to push

    structured-JSON reconciled figures (openinfo_reconcile): the read path serves

    the highest-ranked period, so a stale or spurious higher period already in the

    cache would otherwise shadow the figures this push establishes.



    A ticker may legitimately supply SEVERAL periods — the latest cumulative

    quarter plus the last complete fiscal year that ratios need a 12-month

    denominator from — so the delete happens once per ticker, before any insert.

    Deleting per row instead (as this did while every ticker had exactly one row)

    silently keeps only whichever period happens to be pushed last. Values are

    stored in thousands of UZS, as everywhere in this cache.

    """

    _num = catalogue_codecs._financials_num

    _bal_total = catalogue_codecs._balance_total_fallback



    # A replace push speaks for a ticker's LATEST periods — the newest cumulative

    # quarter plus its companion fiscal year — and its job is to clear a stale or

    # spurious period that would SHADOW them (the read path serves the

    # highest-ranked period). Deleting the whole ticker did far more than that:

    # every backfilled historical year went with it, so the multi-year income

    # statement landed on 2026-08-08 and was gone by the next daily reconcile,

    # with the hourly filings watch erasing it ticker by ticker in between.

    #

    # Only a period ranked ABOVE the newest one pushed can shadow it, so that —

    # strictly above the CEILING — is the whole of what a replace may clear.

    # Clearing from the push's oldest period upward, as this did, deleted the

    # periods BETWEEN the two rows of a normal reconcile push: an annual ranked

    # from the start of its year, so the daily push of «2026Q2 + FY2025» erased

    # 2025Q1, 2025Q2, 2025Q3 and 2026Q1 every single day. Measured fleet-wide

    # 2026-08-17: 19 quarterly periods stored for 2025 against 301 for 2023,

    # and the quarterly view showed a two-year hole between 2024Q4 and the

    # current quarter. Worse, the 9-month filing it deleted is the very row Q4

    # is derived from (annual − 9M), so the year lost its fourth quarter too.

    def _rank(year: int, quarter: int) -> int:

        # The rank the DELETE below computes, and the one get_company_ratios_cached

        # orders by: an annual (quarter 0) is the year's FINAL figure, year*10+5,

        # so a cumulative quarter of the same year always ranks below it and can

        # never shadow it.

        return year * 10 + (5 if not quarter else int(quarter))



    ceilings: dict[tuple[str, str], int] = {}

    for r in rows or []:

        ticker = str(r.get("ticker") or "").strip().upper()

        period = catalogue_codecs._financials_period(r)

        if not ticker or period is None:

            continue

        key = (ticker, str(r.get("form") or form))

        rank = _rank(*period)

        ceilings[key] = max(ceilings.get(key, rank), rank)



    conn = catalogue_storage.get_catalog_conn()

    n = 0

    cleared: set[tuple[str, str]] = set()

    try:

        with conn:

            for r in rows or []:

                ticker = str(r.get("ticker") or "").strip().upper()

                if not ticker:

                    continue

                period = catalogue_codecs._financials_period(r)

                if period is None:

                    continue

                year, quarter = period

                row_form = str(r.get("form") or form)

                if (ticker, row_form) not in cleared:

                    conn.execute(

                        "DELETE FROM catalog_financials WHERE ticker=? AND form=? "

                        "AND (year*10 + CASE WHEN quarter=0 THEN 5 ELSE quarter END) > ?",

                        (ticker, row_form, ceilings[(ticker, row_form)]))

                    cleared.add((ticker, row_form))

                conn.execute(

                    """

                    -- ON CONFLICT rather than INSERT OR REPLACE: the SQLite

                    -- form deletes the old row and inserts a new one, which

                    -- drops any column this statement does not name, and it

                    -- exists in no other dialect.

                    INSERT INTO catalog_financials

                        (ticker, form, year, quarter, revenue, gross_profit, cash,

                         total_liabilities, net_income, operating_income, operating_expenses,

                         total_assets, total_equity,

                         current_assets, current_liabilities, inventories,

                         noninterest_income, org_type, balance_period,

                         field_periods, prior_period, updated_at)

                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))

                    ON CONFLICT(ticker, form, year, quarter) DO UPDATE SET

                        revenue=excluded.revenue, gross_profit=excluded.gross_profit,

                        cash=excluded.cash, total_liabilities=excluded.total_liabilities,

                        net_income=excluded.net_income,

                        operating_income=excluded.operating_income,

                        -- A structured reconciliation may not carry an expense

                        -- line although an Excel parser already read the filed

                        -- one. Keep that filed value; an explicit zero still

                        -- overwrites it because COALESCE treats zero as data.

                        operating_expenses=COALESCE(excluded.operating_expenses,

                                                    catalog_financials.operating_expenses),

                        total_assets=excluded.total_assets,

                        total_equity=excluded.total_equity,

                        current_assets=COALESCE(excluded.current_assets,

                                                catalog_financials.current_assets),

                        current_liabilities=COALESCE(excluded.current_liabilities,

                                                     catalog_financials.current_liabilities),

                        inventories=COALESCE(excluded.inventories,

                                             catalog_financials.inventories),

                        noninterest_income=excluded.noninterest_income,

                        org_type=excluded.org_type,

                        balance_period=excluded.balance_period,

                        field_periods=excluded.field_periods,

                        prior_period=excluded.prior_period,

                        updated_at=excluded.updated_at

                    """,

                    (ticker, row_form, year, quarter,

                     _num(r.get("revenue")), _num(r.get("gross_profit")), _num(r.get("cash")),

                     _num(r.get("total_liabilities")), _num(r.get("net_income")),

                     _num(r.get("operating_income")),

                     _num(r.get("operating_expenses")),

                     _bal_total(r, "total_assets", "assets_end"),

                     _bal_total(r, "total_equity", "equity_end"),

                     _num(r.get("current_assets")), _num(r.get("current_liabilities")),

                     _num(r.get("inventories")),

                     _num(r.get("noninterest_income")),

                     (str(r.get("org_type")) if r.get("org_type") else None),

                     catalogue_codecs._encode_balance_period(r.get("balance")),

                     catalogue_codecs._encode_field_periods(r.get("field_periods")),

                     catalogue_codecs._encode_prior_period(r.get("prior"))),

                )

                n += 1

    finally:

        conn.close()

    return n
