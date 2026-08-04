"""Dividend history per listed security.

openinfo publishes one *dividend calendar* for the whole market
(``/disclosure/dividend-calendar/``): ~4 000 filings covering ~600 issuers, each
row carrying the decision date, the per-share amount and percent for the
ordinary and the preferred line, and the record/payment window. What it does
NOT carry reliably is our ticker — ``ticker`` is null for more than half the
rows, and where it is filled it can hold a comma-separated pair
("ALKB, ALKBP"), a dash, or the issuer's full name. ``organization_id`` is
present on every row and IS the openinfo org id, the same key
``catalog_companies.org_id`` already stores.

So the mapping runs org-first and only falls back to weaker evidence:

  1. ``organization_id`` → the tickers we resolved to that org;
  2. the row's own ``ticker`` field, tokenised and kept only where the token is
     a security we actually list;
  3. the issuer name, normalised — accepted ONLY when exactly one issuer in our
     universe matches, because attaching another company's payout to a ticker
     is the failure mode this whole file exists to avoid (see
     ``entity_resolver`` for the same lesson learned on financials).

The result is snapshotted into ``catalog_dividends`` so a company page reads one
indexed table instead of paging openinfo per view. The previous implementation
asked openinfo to resolve the *ticker* as a company name on every request —
"UNVB" is not a company name, so every bank on the site answered
«Дивиденды не объявлялись» while openinfo held nine payouts for it.
"""
from __future__ import annotations

import calendar
import logging
import os
import re
import threading
import time
from typing import Any, Iterable

import requests

logger = logging.getLogger(__name__)

CALENDAR_PATH = "/disclosure/dividend-calendar/"
PAGE_SIZE = int(os.getenv("DIVIDENDS_PAGE_SIZE", "500"))
MAX_PAGES = int(os.getenv("DIVIDENDS_MAX_PAGES", "40"))
REFRESH_TTL_HOURS = int(os.getenv("DIVIDENDS_TTL_HOURS", "12"))

_REFRESH_LOCK = threading.Lock()
_REFRESH_RUNNING = threading.Event()
_last_refresh_attempt = 0.0


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

def fetch_calendar(
    session: requests.Session | None = None,
    *,
    page_size: int = PAGE_SIZE,
    max_pages: int = MAX_PAGES,
    search: str | None = None,
) -> list[dict[str, Any]]:
    """Every row of openinfo's dividend calendar (optionally one search).

    A short read is refused rather than returned: the snapshot replaces the
    stored table, so publishing half a calendar would delete real payout history
    and call it "no dividends".
    """
    from openinfo_collector import _json_get, _make_session

    client = session or _make_session()
    rows: list[dict[str, Any]] = []
    count: int | None = None
    page = 1
    while page <= max_pages:
        params: dict[str, Any] = {"page": page, "page_size": page_size, "ordering": ""}
        if search:
            params["search"] = search
        payload = _json_get(client, CALENDAR_PATH, params)
        if not isinstance(payload, dict):
            break
        batch = payload.get("results") or []
        rows.extend(batch)
        if count is None:
            try:
                count = int(payload.get("count"))
            except (TypeError, ValueError):
                count = None
        if not payload.get("next") or not batch:
            break
        page += 1

    if count is not None and len(rows) < count:
        raise RuntimeError(
            f"dividend calendar read short: {len(rows)} of {count} rows "
            f"(max_pages={max_pages}, page_size={page_size})"
        )
    return rows


# ---------------------------------------------------------------------------
# Name normalisation
#
# Both sides of a comparison go through the same reduction, so dropping a legal
# form is safe as long as it is dropped everywhere. Nothing here is allowed to
# *decide* a match on its own — see `_match_by_name`, which requires the reduced
# key to select exactly one issuer.
# ---------------------------------------------------------------------------

_LEGAL_TOKENS = {
    # Uzbek / transliterated legal forms. "banki" is the tail of the legal form
    # «aksiyadorlik-tijorat banki», so it goes; "bank" does NOT — it is part of
    # the trading name, and reducing «Universal bank» to "universal" is how the
    # first build of this matcher handed a bank the dividends of a bazaar named
    # «Namangan chorsu dehqon universal bozori».
    "aj", "ajmt", "ak", "akb", "atb", "atib", "chakb", "hk", "xk", "qk", "mchj",
    "aksiyadorlik", "aksiyadorlik-tijorat", "jamiyati", "jamiyat", "tijorat",
    "banki", "ochiq", "turdagi", "turidagi",
    # Russian
    "ао", "оао", "зао", "ооо", "акционерное", "акционерно", "акционерно-коммерческий",
    "коммерческий", "общество", "атб", "аж", "чакб", "ак",
    # English
    "jsc", "ojsc", "cjsc", "llc", "ltd", "plc",
}

_WORD_RE = re.compile(r"[0-9a-zA-Zа-яёА-ЯЁʻʼ'`’‘-]+", re.UNICODE)


def _name_key(value: Any) -> str:
    """Alphanumerics only, lowercased — punctuation and quoting carry no meaning."""
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _core_key(value: Any) -> str:
    """`_name_key` with legal-form words removed, so "ATB \"Universal bank\"" and
    "Aksiyadorlik-tijorat banki \"Universal bank\"" reduce to the same string."""
    words = _WORD_RE.findall(str(value or "").lower())
    kept = [w for w in words if w.strip("-'`ʻʼ’‘") and w not in _LEGAL_TOKENS]
    if not kept:  # a name made entirely of legal forms keeps its full key
        kept = words
    return "".join(ch for w in kept for ch in w if ch.isalnum())


def _ticker_tokens(value: Any) -> list[str]:
    """Tickers named in the calendar's free-text ``ticker`` field.

    It holds "ALKB, ALKBP", "-", null, or occasionally the issuer's full name,
    so tokens are only ever *candidates* — the caller keeps the ones we list.
    """
    return [t for t in re.split(r"[^A-Za-z0-9]+", str(value or "").upper()) if t]


# ---------------------------------------------------------------------------
# Our universe
# ---------------------------------------------------------------------------

def _base_ticker(ticker: str, listed: set[str]) -> str | None:
    """The ordinary line a secondary equity line belongs to, when that line is listed.

    Two shapes occur on this exchange: the preferred suffix (ALKB → ALKBP) and a
    numbered second line (UZAL → UZAL2). Both are only accepted when stripping
    the suffix lands on a ticker we actually list, so a name that merely ends in
    P or a digit is not mistaken for somebody's preferred share.
    """
    t = (ticker or "").upper()
    if len(t) > 1 and t.endswith("P") and t[:-1] in listed:
        return t[:-1]
    stripped = t.rstrip("0123456789")
    if stripped and stripped != t and stripped in listed:
        return stripped
    return None


def _issuer_groups(
    entries: Iterable[dict[str, Any]],
    listed: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Entries grouped by issuer — the ordinary line and its preferred twin."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        key = _base_ticker(entry["ticker"], listed) or entry["ticker"]
        groups.setdefault(key, []).append(entry)
    return groups


def build_universe() -> list[dict[str, Any]]:
    """Every security we can show a dividends tab for, with each name we know it by.

    Union of three stores so a security missing from one is still covered:
    ``securities`` (the market board's own registry), ``catalog_companies``
    (which additionally carries the openinfo ``org_id``) and ``catalog_listings``
    (listed-but-inactive issuers).
    """
    entries: dict[str, dict[str, Any]] = {}

    def _entry(ticker: str) -> dict[str, Any] | None:
        t = (ticker or "").strip().upper()
        if not t:
            return None
        return entries.setdefault(t, {"ticker": t, "type": None, "isin": None,
                                      "org_id": None, "names": set()})

    def _add_name(entry: dict[str, Any], name: Any) -> None:
        text = str(name or "").strip()
        if len(_name_key(text)) >= 3:
            entry["names"].add(text)

    try:
        from securities_catalog import get_securities_map

        for ticker, sec in get_securities_map().items():
            entry = _entry(ticker)
            if entry is None:
                continue
            entry["type"] = (sec.get("type") or entry["type"] or "").strip().lower() or None
            entry["isin"] = entry["isin"] or sec.get("isin")
            for key in ("name", "name_uz", "name_en"):
                _add_name(entry, sec.get(key))
    except Exception:  # noqa: BLE001 — one missing store must not empty the universe
        logger.warning("dividends: securities registry unavailable", exc_info=True)

    try:
        from reports_catalog import get_catalog_conn

        conn = get_catalog_conn()
        try:
            for row in conn.execute(
                "SELECT ticker, company_name, org_id FROM catalog_companies"
            ).fetchall():
                entry = _entry(row["ticker"])
                if entry is None:
                    continue
                entry["org_id"] = entry["org_id"] or (str(row["org_id"]).strip() if row["org_id"] else None)
                _add_name(entry, row["company_name"])
            for row in conn.execute("SELECT ticker, isin, name FROM catalog_listings").fetchall():
                entry = _entry(row["ticker"])
                if entry is None:
                    continue
                entry["isin"] = entry["isin"] or row["isin"]
                _add_name(entry, row["name"])
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        logger.warning("dividends: catalog store unavailable", exc_info=True)

    listed = set(entries)

    # Curated openinfo names (COMPANY_CATALOG) — the fallback the rest of the
    # codebase already uses where the exchange name is not how openinfo indexes
    # the issuer (Cyrillic-only names, missing apostrophes).
    try:
        from company_catalog import COMPANY_CATALOG

        for name, ticker in COMPANY_CATALOG.items():
            entry = entries.get((ticker or "").upper())
            if entry is not None:
                _add_name(entry, re.sub(r"\s*\(привилегированные\)\s*$", "", name))
    except Exception:  # noqa: BLE001
        logger.warning("dividends: company catalog unavailable", exc_info=True)

    # A preferred line is the same issuer as its ordinary line, so the two pool
    # their names — in both directions. The exchange sometimes carries the short
    # trading name on one line only (UZINP is «O'zbekinvest», UZIN is
    # «"O'zbekinvest" eksport-import sug'urta kompanyasi...»), and the short one
    # is what the calendar prints.
    for members in _issuer_groups(entries.values(), listed).values():
        shared: set[str] = set()
        for member in members:
            shared |= member["names"]
        for member in members:
            member["names"] = set(shared)

    for entry in entries.values():
        entry["names"] = sorted(entry["names"])
    return sorted(entries.values(), key=lambda e: e["ticker"])


def attach_org_ids(universe: list[dict[str, Any]], *, use_index: bool = True) -> list[dict[str, Any]]:
    """Fill each entry's ``org_id``: overrides → catalog → deterministic index,
    then share it across every line of the same issuer.

    ``use_index`` reaches openinfo (``entity_resolver``'s ticker/ISIN→INN→org
    join, cached 24h). It is best-effort: without it resolution falls back to
    what the catalog already stores plus name matching.
    """
    listed = {e["ticker"] for e in universe}

    try:
        from entity_resolver import ORG_OVERRIDES
    except Exception:  # noqa: BLE001
        ORG_OVERRIDES = {}

    for entry in universe:
        override = ORG_OVERRIDES.get(entry["ticker"])
        if override:
            entry["org_id"] = str(override)

    if use_index:
        for entry in universe:
            if entry.get("org_id"):
                continue
            try:
                from entity_resolver import resolve_by_index

                hit = resolve_by_index(entry["ticker"], entry.get("isin"))
            except Exception as exc:  # noqa: BLE001 — the index needs network
                logger.warning("dividends: org index unavailable (%s)", exc)
                break
            if hit:
                entry["org_id"] = str(hit["org_id"])

    # Ordinary and preferred lines of one issuer share an org in both directions:
    # the catalog stores the org against the ordinary ticker, the deterministic
    # index sometimes only knows the preferred one.
    for members in _issuer_groups(universe, listed).values():
        org = next((m["org_id"] for m in members if m.get("org_id")), None)
        if org:
            for member in members:
                member["org_id"] = member.get("org_id") or org
    return universe


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """One calendar filing in the shape the company page renders."""
    return {
        "filing_id": str(row.get("id") or "").strip() or None,
        "org_id": str(row.get("organization_id") or "").strip() or None,
        "organization": row.get("organization"),
        "decision_date": row.get("decision_date"),
        "pub_date": row.get("pub_date"),
        "ordinary_amount": _num(row.get("common_share_amount")),
        "ordinary_percent": _num(row.get("common_share_percent")),
        "ordinary_start": row.get("common_share_start_date"),
        "ordinary_end": row.get("common_share_end_date"),
        "preferred_amount": _num(row.get("priviliged_share_amount")),
        "preferred_percent": _num(row.get("priviliged_share_percent")),
        "preferred_start": row.get("priviliged_share_start_date"),
        "preferred_end": row.get("priviliged_share_end_date"),
        "link": row.get("link"),
    }


def _name_index(universe: list[dict[str, Any]]) -> dict[str, set[str]]:
    """core-name key → the tickers known by that name."""
    index: dict[str, set[str]] = {}
    for entry in universe:
        for name in entry["names"]:
            key = _core_key(name)
            if len(key) >= 4:
                index.setdefault(key, set()).add(entry["ticker"])
    return index


def _issuer_of(ticker: str, listed: set[str]) -> str:
    return _base_ticker(ticker, listed) or ticker


def map_rows(
    rows: Iterable[dict[str, Any]],
    universe: list[dict[str, Any]],
    *,
    include_bonds: bool = False,
) -> list[dict[str, Any]]:
    """Attach each calendar filing to the securities it belongs to.

    Returns one record per (ticker, filing). A filing lands on every line of the
    issuer — ordinary and preferred — because the filing itself declares both
    amounts and the page picks the column that matches the security.
    """
    pool = [e for e in universe if include_bonds or (e.get("type") or "stock") != "bond"]
    listed = {e["ticker"] for e in pool}

    by_org: dict[str, set[str]] = {}
    for entry in pool:
        if entry.get("org_id"):
            by_org.setdefault(str(entry["org_id"]), set()).add(entry["ticker"])
    by_name = _name_index(pool)
    # A ticker whose issuer we resolved deterministically takes filings from that
    # issuer and from nobody else. Without this, the weaker passes kept adding a
    # near-namesake's payouts on top of the right ones: BIOK (Andijon biokimyo,
    # org 78 — pinned in ORG_OVERRIDES precisely because of this) was collecting
    # «Biokimyo» AJ and «QO'QON BIOKIMYO» AJ as well, and openinfo's own ticker
    # column is what claimed one of them.
    org_known = {t for tickers in by_org.values() for t in tickers}

    out: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        item = normalize_row(raw)
        if not item["filing_id"]:
            continue

        matched_by = None
        targets: set[str] = set()

        org = item["org_id"]
        if org and by_org.get(org):
            targets, matched_by = set(by_org[org]), "org_id"

        if not targets:
            tokens = {t for t in _ticker_tokens(raw.get("ticker")) if t in listed}
            if tokens:
                # Expand to the whole issuer: a filing naming only "ALKB" still
                # declares the preferred amount ALKBP has to show.
                issuers = {_issuer_of(t, listed) for t in tokens}
                targets = {e["ticker"] for e in pool if _issuer_of(e["ticker"], listed) in issuers}
                matched_by = "ticker_field"

        if not targets:
            hit = _match_by_name(item["organization"], by_name, listed)
            if hit:
                targets, matched_by = hit, "name"

        if matched_by != "org_id":
            targets -= org_known

        for ticker in targets:
            record = dict(item)
            record["ticker"] = ticker
            record["matched_by"] = matched_by
            out[(ticker, item["filing_id"])] = record

    return sorted(
        out.values(),
        key=lambda r: (r["ticker"], str(r.get("decision_date") or ""), str(r["filing_id"])),
    )


def _match_by_name(
    organization: Any,
    by_name: dict[str, set[str]],
    listed: set[str],
) -> set[str] | None:
    """Tickers whose issuer name matches exactly once reduced, else None.

    Equality only. Substring matching was tried and withdrawn: company families
    here share a stem — «O'zbekinvest» and «O'zbekinvest Hayot» are different
    issuers, as are «Universal bank» and «Namangan chorsu dehqon universal
    bozori» — so containment attached one company's payouts to another's ticker.
    An ambiguous key resolves to nothing at all: a blank tab is a recoverable
    disappointment, someone else's dividends is not.
    """
    key = _core_key(organization)
    if len(key) < 6:
        return None
    hit = by_name.get(key)
    return _same_issuer_or_none(hit, listed) if hit else None


def _same_issuer_or_none(tickers: set[str], listed: set[str]) -> set[str] | None:
    """Accept a name match only while it points at ONE issuer."""
    if not tickers:
        return None
    if len({_issuer_of(t, listed) for t in tickers}) != 1:
        return None
    issuer = _issuer_of(next(iter(tickers)), listed)
    return {t for t in listed if _issuer_of(t, listed) == issuer}


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_COLUMNS = (
    "ticker", "filing_id", "org_id", "organization", "decision_date", "pub_date",
    "ordinary_amount", "ordinary_percent", "ordinary_start", "ordinary_end",
    "preferred_amount", "preferred_percent", "preferred_start", "preferred_end",
    "link", "matched_by",
)


INSERT_CHUNK = int(os.getenv("DIVIDENDS_INSERT_CHUNK", "250"))


def replace_snapshot(records: list[dict[str, Any]]) -> int:
    """Swap the stored calendar for a freshly mapped one, in one transaction.

    Written in multi-row chunks rather than a statement per filing: on
    PostgreSQL the round trip IS the cost, and ~1 200 of them is how the daily
    collector once ran past its timeout (see catalog/register). Records are
    unique on (ticker, filing_id) before they get here, so a chunk cannot
    conflict with itself.
    """
    from reports_catalog import get_catalog_conn

    row_sql = "(" + ",".join("?" * len(_COLUMNS)) + ", datetime('now'))"
    conn = get_catalog_conn()
    try:
        with conn:
            conn.execute("DELETE FROM catalog_dividends")
            for start in range(0, len(records), INSERT_CHUNK):
                chunk = records[start:start + INSERT_CHUNK]
                params: list[Any] = []
                for record in chunk:
                    params.extend(record.get(col) for col in _COLUMNS)
                conn.execute(
                    f"INSERT INTO catalog_dividends ({', '.join(_COLUMNS)}, updated_at) "
                    f"VALUES {', '.join([row_sql] * len(chunk))}",
                    params,
                )
    finally:
        conn.close()
    return len(records)


def read_snapshot(ticker: str) -> list[dict[str, Any]]:
    """Stored filings for one security, newest decision first."""
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)}, updated_at FROM catalog_dividends "
            "WHERE ticker = ? ORDER BY decision_date DESC, filing_id DESC",
            ((ticker or "").upper(),),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def snapshot_state() -> dict[str, Any]:
    """How many filings and tickers the store holds, and when it was written."""
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS filings, COUNT(DISTINCT ticker) AS tickers, "
            "MAX(updated_at) AS updated_at FROM catalog_dividends"
        ).fetchone()
    finally:
        conn.close()
    state = dict(row or {})
    state["age_hours"] = _age_hours(state.get("updated_at"))
    return state


def _age_hours(stamp: Any) -> float | None:
    """Hours since the snapshot was written.

    ``updated_at`` is UTC on both backends — SQLite's ``datetime('now')`` and the
    PostgreSQL rewrite dbx substitutes for it both render UTC in the same format
    — so it is read with ``timegm``. ``mktime`` would read it as local time and
    report a snapshot written minutes ago as hours old (or negative) on any
    machine that is not on UTC.
    """
    if not stamp:
        return None
    text = str(stamp).strip().replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = time.strptime(text, fmt)
        except ValueError:
            continue
        return max(0.0, (time.time() - calendar.timegm(parsed)) / 3600.0)
    return None


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------

def refresh(*, force: bool = False, use_index: bool = True) -> dict[str, Any]:
    """Re-read the whole calendar and rewrite the snapshot.

    Serialised: a second caller while a refresh is running is told so instead of
    starting a duplicate crawl of openinfo.
    """
    if not _REFRESH_LOCK.acquire(blocking=False):
        return {"ok": True, "skipped": "already running"}
    _REFRESH_RUNNING.set()
    try:
        state = snapshot_state()
        age = state.get("age_hours")
        if not force and state.get("filings") and age is not None and age < REFRESH_TTL_HOURS:
            return {"ok": True, "skipped": "fresh", **state}

        rows = fetch_calendar()
        universe = attach_org_ids(build_universe(), use_index=use_index)
        records = map_rows(rows, universe)
        stored = replace_snapshot(records)
        covered = len({r["ticker"] for r in records})
        logger.info(
            "dividends snapshot: %d filings from openinfo -> %d records across %d tickers",
            len(rows), stored, covered,
        )
        return {
            "ok": True, "filings_read": len(rows), "records": stored,
            "tickers": covered, "universe": len(universe),
        }
    finally:
        _REFRESH_RUNNING.clear()
        _REFRESH_LOCK.release()


def refresh_in_background(*, force: bool = False) -> bool:
    """Kick a refresh off a request thread, at most one attempt per minute."""
    global _last_refresh_attempt
    if _REFRESH_RUNNING.is_set():
        return False
    now = time.time()
    if not force and now - _last_refresh_attempt < 60:
        return False
    _last_refresh_attempt = now

    def _run() -> None:
        try:
            refresh(force=force)
        except Exception:  # noqa: BLE001 — a background refresh may not kill the app
            logger.exception("dividends background refresh failed")

    threading.Thread(target=_run, name="dividends-refresh", daemon=True).start()
    return True


def _live_lookup(ticker: str) -> list[dict[str, Any]]:
    """One openinfo search, mapped through the same guards as the snapshot.

    Covers the window after a cold deploy when the snapshot has not been written
    yet: a single request instead of the eight-page crawl, so the first visitor
    still sees the history.
    """
    universe = attach_org_ids(build_universe(), use_index=False)
    entry = next((e for e in universe if e["ticker"] == ticker), None)
    queries = [ticker] + ([n for n in (entry or {}).get("names", [])][:2])
    for query in queries:
        try:
            rows = fetch_calendar(search=query, max_pages=4)
        except Exception:  # noqa: BLE001
            logger.warning("dividends live lookup failed for %s", query, exc_info=True)
            continue
        if not rows:
            continue
        mapped = [r for r in map_rows(rows, universe) if r["ticker"] == ticker]
        if mapped:
            return mapped
    return []


def dividends_for(ticker: str) -> dict[str, Any]:
    """The dividends payload for one security, newest first."""
    ticker = (ticker or "").strip().upper()
    state = snapshot_state()
    age = state.get("age_hours")
    stale = (not state.get("filings")) or age is None or age >= REFRESH_TTL_HOURS
    source = "snapshot"

    items = read_snapshot(ticker)
    if not items and not state.get("filings"):
        items = _live_lookup(ticker)
        source = "openinfo" if items else "snapshot"

    if stale:
        refresh_in_background()

    items.sort(key=lambda r: (str(r.get("decision_date") or ""), str(r.get("filing_id") or "")), reverse=True)
    return {
        "ok": True,
        "ticker": ticker,
        "count": len(items),
        "items": items,
        "source": source,
        "as_of": state.get("updated_at"),
    }


if __name__ == "__main__":  # pragma: no cover — operational entry point
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Refresh the dividend snapshot")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-index", action="store_true", help="skip the openinfo org index")
    parser.add_argument("--ticker", help="print one ticker's stored history and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.ticker:
        print(json.dumps(dividends_for(args.ticker), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(refresh(force=args.force, use_index=not args.no_index),
                         ensure_ascii=False, indent=2))
