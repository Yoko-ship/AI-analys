"""Store source facts and audit their coverage and consistency."""
from __future__ import annotations
import catalogue.history as catalogue_history
from typing import Any
import sqlite3

from entity_resolver import ORG_OVERRIDES
import catalogue.periods as catalogue_periods
import catalogue.ratios as catalogue_ratios
import catalogue.settings as catalogue_settings
import catalogue.snapshots as catalogue_snapshots
import catalogue.storage as catalogue_storage


def purge_premature_annual_facts() -> int:
    """Delete ``financial_indicators`` facts for a not-yet-complete fiscal year.

    openinfo hands out a placeholder *annual* (quarter 0) indicator for the
    in-progress year; the collector now skips it, but a catalog populated before
    that guard can still carry the row. Left in place it keeps an issuer whose only
    fact is that placeholder "covered", blocking the NSBU-derived collector from
    re-covering it — so purge it. Quarterly current-year periods ('2026Q1') carry a
    'Q' and are not matched. Idempotent; safe to call each collector cycle.
    """
    cutoff = catalogue_periods._latest_complete_fiscal_year()
    conn = catalogue_storage.get_catalog_conn()
    with conn:
        cur = conn.execute(
            "DELETE FROM facts WHERE dataset='financial_indicators' "
            "AND period GLOB '20[0-9][0-9]' AND CAST(period AS INT) > ?",
            (cutoff,),
        )
        n = cur.rowcount
    conn.close()
    if n:
        catalogue_settings.logger.info("purged %d premature (> FY%d) annual financial_indicators facts", n, cutoff)
    return n


def upsert_facts(rows: list[dict[str, Any]]) -> int:
    """Upsert generic facts from any source adapter (forward-compatible storage).

    Each row: ``entity_id, dataset, field, value`` (+ optional ``period, unit,
    source, source_url``). Numeric values land in ``value_num``, others in
    ``value_text``. New datasets/fields require no schema change.
    """
    if not rows:
        return 0
    conn = catalogue_storage.get_catalog_conn()
    written = 0
    with conn:
        for r in rows:
            value = r.get("value")
            vnum = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            vtext = None if vnum is not None else (str(value) if value is not None else None)
            conn.execute(
                """
                INSERT INTO facts (entity_id, dataset, field, period, value_num, value_text, unit, source, source_url, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(entity_id, dataset, field, period, source) DO UPDATE SET
                    value_num  = excluded.value_num,
                    value_text = excluded.value_text,
                    unit       = excluded.unit,
                    source_url = excluded.source_url,
                    fetched_at = datetime('now')
                """,
                (str(r["entity_id"]), r["dataset"], r["field"], str(r.get("period", "")),
                 vnum, vtext, r.get("unit"), r.get("source", "unknown"), r.get("source_url")),
            )
            written += 1
        _cleanup_invalid_fact_periods(conn)
    conn.close()
    # The ratio memo is derived from exactly these rows.
    catalogue_ratios.invalidate_ratios_cache()
    return written


def _cleanup_invalid_fact_periods(conn: sqlite3.Connection) -> int:
    """Delete dated facts whose period fails validation ('2025Q7', '2026Q5', …).

    Runs on every fact upsert (local collect and prod admin push alike), so a
    DB that already contains corrupt periods heals itself without a hand-run
    migration. Period-less facts (period = '') are untouched.
    """
    periods = [
        r["period"]
        for r in conn.execute("SELECT DISTINCT period FROM facts WHERE period != ''").fetchall()
    ]
    bad = [p for p in periods if catalogue_periods._period_key(p) == (0, 0)]
    removed = 0
    for p in bad:
        removed += conn.execute("DELETE FROM facts WHERE period = ?", (p,)).rowcount
    if removed:
        catalogue_settings.logger.warning("fact store: removed %d rows with invalid periods %s", removed, bad)
        catalogue_ratios.invalidate_ratios_cache()
    return removed


def get_facts(entity_id: Any = None, dataset: str | None = None) -> list[dict[str, Any]]:
    """Query the fact store, optionally filtered by entity (org_id) and dataset."""
    conn = catalogue_storage.get_catalog_conn()
    query = "SELECT * FROM facts WHERE 1=1"
    params: list[Any] = []
    if entity_id is not None:
        query += " AND entity_id = ?"
        params.append(str(entity_id))
    if dataset:
        query += " AND dataset = ?"
        params.append(dataset)
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]
    conn.close()
    return rows


def audit_financials_consistency(form: str = "NSBU", tol: float = 0.05) -> list[dict[str, Any]]:
    """Reconcile served net_income against the authoritative fact-store net_profit.

    Flags any issuer whose stored/served net income differs by more than ``tol``
    from openinfo's own net_profit for the same entity — catching mislabels
    (revenue booked as profit) or stale NSBU parses before they mislead a user.
    """
    served = catalogue_snapshots.get_all_financials(form)
    conn = catalogue_storage.get_catalog_conn()
    try:
        comp = {
            r["ticker"]: ORG_OVERRIDES.get(r["ticker"], str(r["org_id"]))
            for r in conn.execute(
                "SELECT ticker, org_id FROM catalog_companies WHERE org_id IS NOT NULL AND org_id != ''"
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT entity_id, period, value_num FROM facts "
            "WHERE dataset='financial_indicators' AND field='net_profit' AND value_num IS NOT NULL"
        ).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        key = str(r["entity_id"])
        period = str(r["period"] or "")
        if catalogue_periods._period_key(period) == (0, 0):
            continue  # corrupt/unparseable source period
        if key not in best or catalogue_periods._period_key(period) > catalogue_periods._period_key(best[key][0]):
            best[key] = (period, r["value_num"])
    flags: list[dict[str, Any]] = []
    for ticker, fin in served.items():
        ni = fin.get("net_income")
        org = comp.get(ticker)
        if ni is None or not org:
            continue
        hit = best.get(org)
        if not hit or not hit[1]:
            continue
        if abs(ni - hit[1]) / max(abs(hit[1]), 1.0) > tol:
            flags.append({"ticker": ticker, "stored_net_income": ni, "authoritative_net_profit": hit[1]})
    return flags


def get_catalog_coverage(form: str = "NSBU") -> dict[str, dict[str, Any]]:

    """Per-ticker data coverage from the catalog DB (for /api/coverage).



    Returns {ticker: {org_id, reports, has_financials, sync_error, last_synced_at}}

    so the API can show, for every listed security, whether each dataset is

    filled / empty / failed — no openinfo access required (reads the local cache).

    """

    conn = catalogue_storage.get_catalog_conn()

    comp = {

        r["ticker"]: {

            "org_id": r["org_id"],

            "sync_error": r["sync_error"],

            "last_synced_at": r["last_synced_at"],

        }

        for r in conn.execute(

            "SELECT ticker, org_id, sync_error, last_synced_at FROM catalog_companies"

        ).fetchall()

    }

    rep_counts = {

        r["ticker"]: r["c"]

        for r in conn.execute(

            "SELECT ticker, COUNT(*) AS c FROM catalog_reports GROUP BY ticker"

        ).fetchall()

    }

    conn.close()

    fin = catalogue_snapshots.get_all_financials(form)

    history = catalogue_history.get_financial_history_coverage(form)

    out: dict[str, dict[str, Any]] = {}

    tickers = set(comp) | set(rep_counts) | set(fin)

    for tk in tickers:

        info = comp.get(tk, {})

        out[tk] = {

            "org_id": info.get("org_id"),

            "sync_error": info.get("sync_error"),

            "last_synced_at": info.get("last_synced_at"),

            "reports": rep_counts.get(tk, 0),

            "has_financials": tk in fin,

            "financial_history": history.get(tk),

        }

    return out
