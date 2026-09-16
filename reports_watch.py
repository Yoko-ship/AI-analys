# coding: utf-8
"""Catch a filing the same hour it lands, instead of at the next daily sweep.

The financials pipeline already reads a new quarterly report correctly the moment
it appears — ``openinfo_reconcile`` picks the latest reporting PERIOD and the
board renders it. What it does not do is *notice*. The full sweep runs once a
day; O'zbektelekom filed its half-year report on 2026-07-29 at 11:27, three hours
after that morning's run, so the board kept showing Q1 for the rest of the day —
and a report filed on a Friday evening (the deadline days are exactly when they
arrive in bulk, late) waited until Monday.

This module is the cheap half of the sweep: read openinfo's newest-first filing
feed, keep only the issuers we track, and hand back the tickers whose figures
would actually change. One listing request covers the whole market, and a quiet
hour reconciles nothing at all.

There is no watermark file. The feed says who filed; prod says what it currently
serves; a ticker is refreshed when the reconciled period outranks the served one,
or when the same period comes back with different figures (a restatement). That
makes the watcher stateless — it can run in a fresh container, be missed for a
day, or run twice in a minute, and still converge on the same answer. It also
heals a ticker that fell behind for any other reason, which a "since last run"
cursor never would.

Scope: issuers openinfo's own ticker registry knows, plus the reconciler's pinned
overrides — that is every equity line, ordinary and preferred together, since the
registry lists them under one organization ("UZTL, UZTLP"). Bond symbols that
inherit their issuer's figures through the alias step are left to the daily
sweep, which is where that step lives.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import openinfo_http as _http
import openinfo_reconcile as orc

log = logging.getLogger(__name__)

REPORTS_URL = f"{orc.API_BASE}/reports/main/"

# openinfo stamps pub_date in Tashkent wall-clock with no offset ("2026-07-29T11:27:42").
# Read as UTC it lands five hours in the future, and every filing of the last five
# hours — the ones this exists to catch — falls outside the window.
TASHKENT = timezone(timedelta(hours=5))

# Report forms the reconciler can read. An IFRS (MSFO) filing is a PDF; it changes
# nothing the board serves, so it must not trigger a refresh.
WATCHED_FORMS = ("NSBU",)

# A restatement of the same period is worth republishing, ordinary rounding noise
# is not. Half a percent is far below any real correction and far above float drift.
VALUE_TOLERANCE = 0.005

_HEADLINE_FIELDS = ("revenue", "gross_profit", "cash", "total_liabilities",
                    "net_income", "operating_income")


def _now_local() -> datetime:
    return datetime.now(TASHKENT).replace(tzinfo=None)


def _parse_pub(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def recent_filings(hours: int = 48, max_pages: int = 8, page_size: int = 100) -> list[dict[str, Any]]:
    """Filings published in the last ``hours``, newest first.

    The feed is global and ordered by publication, so paging stops at the first
    record older than the cutoff. ``max_pages`` is the backstop for a deadline day
    when hundreds land at once: hitting it is logged, because a silently truncated
    scan looks exactly like a quiet market.
    """
    cutoff = _now_local() - timedelta(hours=max(1, hours))
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        payload = orc._getj(REPORTS_URL, {
            "ordering": "-pub_date", "page": page, "page_size": page_size,
        })
        results = (payload or {}).get("results") or []
        if not results:
            return out
        for item in results:
            published = _parse_pub(item.get("pub_date"))
            if published is None or published < cutoff:
                return out
            props = item.get("properties") or {}
            out.append({
                "id": item.get("id"),
                "object_id": item.get("object_id"),
                "organization": item.get("organization"),
                "organization_name": item.get("organization_name"),
                "pub_date": item.get("pub_date"),
                "report_form": item.get("report_type"),
                "period_type": props.get("report_type"),
                "title": props.get("report_title"),
            })
        if not (payload or {}).get("next"):
            return out
    log.warning("filing feed: stopped at the %d-page cap — some filings inside the "
                "%dh window were not read", max_pages, hours)
    return out


_SEARCH_ORG_CACHE: dict[str, Any] = {}


def _search_org(ticker: str) -> Any:
    """The organization behind a ticker openinfo's registry does not carry.

    Eleven of the listed symbols resolve only through the reconciler's name search —
    TGPG as "Tashgiprogor", TKDM as "Toshkentdonmahsulotlari", the bond series through
    their issuer — so ``org_id_for`` returns nothing for them and they are invisible to
    the feed → ticker mapping. TGPG, TKDM and TKDMP were exactly the three the first
    run left behind while their half-year filings sat published.

    The search is looser than the registry: where the reconciler needs an extra name
    hint to tell two issuers apart, the top candidate here may be the wrong one. That
    only decides *whether to reconcile* — ``reconcile_ticker`` binds the issuer strictly
    on its own and ``_changed`` gates the push — so a wrong guess costs one lookup, not
    a wrong figure.
    """
    if ticker in _SEARCH_ORG_CACHE:
        return _SEARCH_ORG_CACHE[ticker]
    org = None
    try:
        for cand in orc.list_candidates(orc.SEARCH_OVERRIDE.get(ticker, ticker)):
            if cand.get("organization"):
                org = cand["organization"]
                break
    except Exception:  # noqa: BLE001 — one unmappable symbol must not stop the scan
        log.exception("could not resolve an organization for %s", ticker)
    _SEARCH_ORG_CACHE[ticker] = org
    return org


def tickers_by_org(extra_tickers: Iterable[str] = ()) -> dict[str, set[str]]:
    """organization id -> the tickers whose figures that organization's filings set.

    Hits the network for the handful of ``extra_tickers`` openinfo's registry cannot
    map (see :func:`_search_org`), once per process.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for ticker, org in orc.ticker_org_map().items():
        out[str(org)].add(str(ticker).upper())
    for ticker, org in orc.ORG_ID_OVERRIDE.items():
        out[str(org)].add(str(ticker).upper())
    unmapped: list[str] = []
    for ticker in extra_tickers:
        symbol = str(ticker or "").strip().upper()
        if not symbol:
            continue
        org = orc.org_id_for(symbol)
        if org:
            out[str(org)].add(symbol)
        else:
            unmapped.append(symbol)
    if unmapped:
        log.info("resolving %d ticker(s) openinfo's registry does not carry: %s",
                 len(unmapped), ", ".join(sorted(unmapped)))
    for symbol in unmapped:
        org = _search_org(symbol)
        if org:
            out[str(org)].add(symbol)
        else:
            log.warning("%s: no organization — a filing by its issuer cannot be noticed", symbol)
    return dict(out)


def candidates(filings: Iterable[dict[str, Any]],
               known_tickers: Iterable[str] | None = None,
               extra_tickers: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """ticker -> the newest watched filing by its issuer, for the tickers we track.

    ``known_tickers`` is the universe the site carries — the market board plus
    whatever it already serves. openinfo's registry is wider than the exchange:
    it keeps filing issuers that were never listed and ones deliberately purged
    (MNGM, OCBK, dead bond series), and pushing a financials row for those would
    put a delisted symbol back on the board. Pass ``None`` only offline.
    """
    universe = {str(t).strip().upper() for t in known_tickers} if known_tickers is not None else None
    by_org = tickers_by_org(extra_tickers)
    out: dict[str, dict[str, Any]] = {}
    for filing in filings:
        if filing.get("report_form") not in WATCHED_FORMS:
            continue
        for ticker in by_org.get(str(filing.get("organization")), ()):
            if universe is not None and ticker not in universe:
                continue
            if ticker not in out:  # feed is newest-first
                out[ticker] = filing
    return out


def _changed(reconciled: dict[str, Any], served: dict[str, Any] | None) -> str | None:
    """Why this ticker needs republishing, or None when the board is already right."""
    if not served:
        return "not served yet"
    new_rank = orc.period_rank(reconciled.get("year"), reconciled.get("quarter"))
    old_rank = orc.period_rank(served.get("year"), served.get("quarter"))
    if new_rank > old_rank:
        return f"{served.get('year')}Q{served.get('quarter') or 0} -> {reconciled.get('year')}Q{reconciled.get('quarter') or 0}"
    if new_rank < old_rank:
        # Never push backwards on a hunch: the daily sweep re-derives everything and
        # is the right place to resolve a genuine disagreement.
        log.warning("%s: reconciled period %s is older than the served %s — leaving it alone",
                    reconciled.get("ticker"), new_rank, old_rank)
        return None
    for field in _HEADLINE_FIELDS:
        # Served values are full UZS; the reconciler carries both units.
        fresh = reconciled.get(f"{field}_full")
        current = served.get(field)
        if fresh is None or current is None:
            if fresh != current:
                return f"{field} appeared"
            continue
        if abs(fresh - current) > VALUE_TOLERANCE * max(abs(current), 1.0):
            return f"{field} restated"
    return None


def scan(served: dict[str, Any] | None = None, known_tickers: Iterable[str] | None = None,
         hours: int = 48, max_pages: int = 8, today=None) -> dict[str, Any]:
    """Find the tickers a new filing has moved, and the rows that would fix them.

    ``served`` is prod's ``/api/market/financials`` payload (ticker -> row, money in
    full UZS); pass ``None`` to refresh every candidate unconditionally.
    ``known_tickers`` bounds the result to securities the site carries. Returns the
    push rows plus the reasoning, so a run that pushes nothing still says what it saw.
    """
    filings = recent_filings(hours=hours, max_pages=max_pages)
    universe = known_tickers if known_tickers is not None else (
        list(served.keys()) if served is not None else None)
    found = candidates(filings, known_tickers=universe, extra_tickers=(served or {}).keys())
    log.info("filing feed: %d filings in %dh, %d tracked ticker(s) affected",
             len(filings), hours, len(found))

    push_rows: list[dict[str, Any]] = []
    refreshed: dict[str, str] = {}
    unchanged: list[str] = []
    errors: dict[str, str] = {}
    for ticker in sorted(found):
        try:
            row, meta = orc.reconcile_ticker(ticker, today=today)
        except Exception as exc:  # noqa: BLE001 — one bad issuer must not stop the scan
            errors[ticker] = f"exception: {exc}"
            continue
        if row is None:
            errors[ticker] = meta.get("error", "unresolved")
            continue
        reason = _changed(row, (served or {}).get(ticker)) if served is not None else "forced"
        if not reason:
            unchanged.append(ticker)
            continue
        refreshed[ticker] = reason
        push_rows.extend(orc.admin_push_rows(row))
        log.info("%s: %s (filed %s)", ticker, reason, found[ticker].get("pub_date"))

    return {
        "filings": len(filings),
        "window_hours": hours,
        "candidates": sorted(found),
        "refreshed": refreshed,
        "unchanged": unchanged,
        "errors": errors,
        "rows": push_rows,
    }


def board_tickers(base: str) -> set[str]:
    """Every security the deployment lists, stock and bond — the push universe."""
    import requests

    out: set[str] = set()
    for kind in ("stock", "bond"):
        payload = requests.get(f"{base.rstrip('/')}/api/market/stocks?type={kind}", timeout=60).json()
        rows = payload if isinstance(payload, list) else (payload.get("stocks") or [])
        out |= {str(r.get("ticker")).strip().upper() for r in rows if r.get("ticker")}
    return out


def _cli(argv: list[str]) -> int:
    import argparse
    import json
    import os

    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=int(os.getenv("REPORTS_WATCH_HOURS", "48")))
    ap.add_argument("--all", action="store_true",
                    help="ignore what prod serves and print every candidate's figures")
    ap.add_argument("--base", default=os.getenv("FINANCIALS_PUSH_URL",
                                                "https://ai-analys-production.up.railway.app"))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    base = args.base.rstrip("/")
    served = None
    if not args.all:
        served = requests.get(f"{base}/api/market/financials", timeout=60).json()
        served = served.get("financials") or served
    result = scan(served=served, known_tickers=board_tickers(base) | set(served or ()),
                  hours=args.hours)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"},
                     ensure_ascii=False, indent=1))
    print(f"{len(result['rows'])} row(s) would be pushed "
          f"(run collector_financials.py --watch-filings to push them)")
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_cli(sys.argv[1:]))
