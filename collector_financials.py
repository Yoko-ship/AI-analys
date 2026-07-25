"""Daily financials collector.

Runs anywhere openinfo.uz is reachable, recomputes the NSBU headline indicators,
and pushes them to the deployed API via POST /api/admin/*. Verified: Railway's
own egress IP reaches openinfo directly (re-check live any time with
GET /api/admin/openinfo-probe), so the recommended setup is a Railway cron
service from this same repo (see railway.collector.json + DEPLOY.md). A local
PC or any other host works identically; if a host does get blocked, set
OPENINFO_PROXY to route through a relay. All openinfo traffic is paced and
retried via openinfo_http.py so bulk syncs stay polite and the IP stays clean.

Usage:
    python collector_financials.py              # sync catalog + recompute + push
    python collector_financials.py --push-only  # push the current local cache only
    python collector_financials.py --no-push    # refresh locally, skip the push

Config (env / .env):
    ADMIN_API_SECRET     shared secret for the admin endpoint (required to push)
    FINANCIALS_PUSH_URL  target base URL (default: prod)
    HTTPS_PROXY          optional; honored automatically for openinfo access
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

# The collector is the only place org/fact enrichment is correct (openinfo is
# reachable, org mapping is fresh). Enrich here, then push final values; the
# deployment serves them as-is (see reports_catalog._financials_enrich_enabled).
os.environ.setdefault("FINANCIALS_ENRICH_ON_READ", "1")

import reports_catalog as rc  # noqa: E402  (after load_dotenv)
import trade_stats as ts  # noqa: E402
from runtime_preflight import COLLECTOR_REQUIREMENTS, preflight  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")

DEFAULT_URL = "https://ai-analys-production.up.railway.app"
KEYS = ("revenue", "gross_profit", "cash", "total_liabilities", "net_income", "operating_income")


def refresh_local() -> None:
    """Sync the catalog (catch new filings) then recompute all latest annuals."""
    log.info("sync_all: refreshing report catalog ...")
    try:
        res = rc.sync_all()
        log.info("sync_all done: %s", {k: res.get(k) for k in ("synced", "skipped") if k in res} or "ok")
    except Exception:
        log.exception("sync_all failed (continuing with cached catalog)")
    log.info("recomputing financials for all annual reports ...")
    res = rc.refresh_financials_cache(ttl_days=0, sync_missing=False, limit=1000)
    log.info("financials refresh: %s", res)
    log.info("filling remaining gaps from report PDFs (broken-Excel issuers) ...")
    try:
        pdf = rc.refresh_financials_from_pdf()
        log.info("pdf fallback: %s", {k: pdf.get(k) for k in ("candidates", "updated")})
    except Exception:
        log.exception("pdf fallback failed")


def collect_rows() -> list[dict]:
    fin = rc.get_all_financials()
    rows = []
    for ticker, r in fin.items():
        # The latest period AND the last complete fiscal year beside it. Prod
        # serves what it is given; pushing only the newest cumulative quarter
        # leaves every 12-month denominator on the deployment out of date.
        for period in (r, r.get("annual")):
            if not period:
                continue
            rows.append({
                "ticker": ticker,
                "year": period.get("year"),
                "quarter": period.get("quarter"),
                # Which period each field actually describes, when it is not the row's
                # own — prod serves what we push verbatim, so the provenance has to
                # travel with the figures or the row lies about its own period.
                "field_periods": period.get("field_periods") or {},
                **{k: period.get(k) for k in KEYS},
            })
    return rows


def _post(path: str, body: dict) -> int:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        log.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    url = os.getenv("FINANCIALS_PUSH_URL", DEFAULT_URL).rstrip("/") + path
    resp = requests.post(url, json=body, headers={"X-Admin-Secret": secret}, timeout=120)
    if resp.status_code != 200:
        log.error("push %s failed: HTTP %s %s", path, resp.status_code, resp.text[:300])
        return 1
    log.info("push %s ok: %s", path, resp.json())
    return 0


def push(rows: list[dict]) -> int:
    log.info("pushing %d financials rows", len(rows))
    return _post("/api/admin/financials", {"form": "NSBU", "rows": rows})


def _stamp_step(step: str, detail: str = "") -> None:
    """Record that ONE pipeline step landed, and for which session.

    The run heartbeat is stamped by partial runs too (``--reconcile-only`` skips
    trade stats entirely), so "collector ok" said nothing about whether the board's
    turnover had been refreshed: the statistics sat three sessions behind while
    /api/coverage reported a healthy 20-hour-old run. Per-step stamps make a step
    that quietly stops running visible on its own.
    """
    from datetime import datetime, timezone

    try:
        _post("/api/admin/facts", {"rows": [
            {"entity_id": "_collector", "dataset": "meta", "field": f"{step}_last_run",
             "period": "", "value": datetime.now(timezone.utc).isoformat(), "source": "collector"},
            {"entity_id": "_collector", "dataset": "meta", "field": f"{step}_last_day",
             "period": "", "value": str(detail or ""), "source": "collector"},
        ]})
    except Exception:
        log.exception("step stamp failed: %s", step)


def push_trade_stats() -> int:
    """Fetch the latest-day per-trade stats from UZSE and push to prod."""
    log.info("fetching UZSE trade stats (latest day) ...")
    data = ts.fetch_trade_stats()
    stats = data.get("stats") or {}
    rows = list(stats.values())
    log.info("trade stats: %d securities for %s", len(rows), data.get("trade_date"))
    if not rows:
        log.warning("no trade stats fetched")
        return 1
    # Board rows whose security did not trade today otherwise show dashes in
    # the qty/avg-price/avg-trade/largest columns forever, even though their
    # price/OHLC columns already display the LAST trading day. Backfill that
    # same day's stats from openinfo's trade-results archive so the whole row
    # is coherently "as of the last trade date".
    try:
        base = os.getenv("FINANCIALS_PUSH_URL", DEFAULT_URL).rstrip("/")
        board_rows = []
        for kind in ("stock", "bond"):
            board = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60).json()
            board_rows.extend(board if isinstance(board, list) else board.get("stocks") or [])
        targets = []
        seen: set[str] = set()
        no_date: list[str] = []
        for r in board_rows:
            isin = str(r.get("isin") or "").strip().upper()
            if not isin or isin in stats or isin in seen:
                continue
            seen.add(isin)
            day = str(r.get("last_trade_date") or "").strip()
            if day:
                targets.append((isin, day))
            else:
                no_date.append(isin)
        # The live feed reports last_trade_date=null for some securities that
        # DID trade (e.g. FRAZP, UZML) — recover the day from the conclusions
        # archive; securities with genuinely no history are skipped.
        if no_date:
            import listings_collector as lc
            from openinfo_collector import _make_session
            session = _make_session()
            for isin in no_date:
                last = lc._last_conclusion(session, isin)
                day = str((last or {}).get("date") or "").strip()
                if day:
                    targets.append((isin, day))
        if targets:
            log.info("backfilling last-day stats for %d untraded securities ...", len(targets))
            back = ts.backfill_last_day_stats(targets)
            log.info("backfilled %d securities", len(back))
            rows.extend(back)
    except Exception:
        log.exception("last-day stats backfill failed (pushing today's only)")
    status = _post("/api/admin/trade-stats", {"trade_date": data.get("trade_date"), "rows": rows})
    if status == 0:
        _stamp_step("trade_stats", str(data.get("trade_date") or ""))
    return status


def push_listings() -> int:
    """Collect the RFB listing registry (openinfo) and push it to prod.

    Surfaces issuers that are listed on RFB Tashkent but missing from the live
    uzse-stock feed (no recent trades on the main board), so they still appear on
    the market board with their last-known price and market cap.
    """
    import listings_collector as lc

    log.info("collecting exchange-listing registry (openinfo info_rfb) ...")
    rows = lc.collect_listing_rows()
    log.info("listings: %d securities", len(rows))
    if not rows:
        log.warning("no listings collected")
        return 1
    return _post("/api/admin/listings", {"rows": rows})


def push_financials_aliases() -> int:
    """Copy each issuer's financials onto its sibling tickers, then push to prod.

    A company's financials are issuer-level, but the board keys them by ticker —
    so preferred lines, issuer bonds, and ordinary/preferred variants (AGMK vs
    AGMKP, KSCMP vs KSCM) showed blank. This fills them from the sibling that has
    them.
    """
    import listings_collector as lc

    log.info("collecting issuer financials aliases (openinfo info_rfb) ...")
    rows = lc.collect_financials_aliases()
    log.info("financials aliases: %d sibling tickers", len(rows))
    if not rows:
        return 0
    return _post("/api/admin/financials", {"form": "NSBU", "rows": rows})


def collect_and_push_facts() -> int:
    """Run every registered source adapter locally, then push the fact store to prod.

    This is the extensible half of the pipeline: any adapter registered in
    data_sources (financial_indicators today, shareholder structure / news /
    ratings tomorrow) is picked up automatically and its facts propagate.
    """
    import data_sources as ds
    import listings_collector as lc

    log.info("running source adapters (fact store) ...")
    res = ds.run_all()
    log.info("adapters: %s", res.get("collectors"))
    # Land the ticker→org map next to the facts: prod joins the fact store by
    # org id, and only this map (not prod's own drifting catalog) is guaranteed
    # to use the same IDs the facts were collected under — siblings included.
    try:
        org_map = lc.collect_org_map_rows()
        rc.upsert_facts(org_map)
        log.info("org map: %d ticker rows", len(org_map))
    except Exception:
        log.exception("org-map step failed (facts push continues without it)")
    facts = rc.get_facts()
    rows = [{
        "entity_id": f["entity_id"], "dataset": f["dataset"], "field": f["field"],
        "period": f["period"],
        "value": f["value_num"] if f["value_num"] is not None else f["value_text"],
        "unit": f["unit"], "source": f["source"], "source_url": f["source_url"],
    } for f in facts]
    if not rows:
        log.warning("no facts collected")
        return 1
    log.info("pushing %d facts", len(rows))
    return _post("/api/admin/facts", {"rows": rows})


def reconcile_and_push() -> int:
    """Reconcile every tracked ticker against openinfo's structured report JSON
    and push the corrected headline figures as the authoritative latest period.

    This runs LAST and uses the ``replace`` mode so it supersedes whatever the
    legacy Excel/PDF parse and the sibling-alias step wrote: the structured path
    (openinfo_reconcile) reads P&L, balance, period and issuer correctly, so its
    figures are the ones the site should serve. Tickers openinfo cannot source
    (bonds with no issuer, IFRS-only holdings) are left to the legacy rows.
    """
    import openinfo_reconcile as orc

    # Cover the full board registry. Source from /api/market/stocks (the stable
    # list of every listed security, stock + bond) so a ticker can't drop out just
    # because its served financials row is currently filtered; union with the
    # served financials keys and the local store as belt-and-braces.
    base = os.getenv("FINANCIALS_PUSH_URL", DEFAULT_URL).rstrip("/")
    tickers = set(rc.get_all_financials().keys())
    try:
        data = requests.get(f"{base}/api/market/financials", timeout=60).json()
        tickers |= set((data.get("financials") or {}).keys())
    except Exception:
        log.exception("could not fetch served financials ticker list")
    try:
        for kind in ("stock", "bond"):
            board = requests.get(f"{base}/api/market/stocks?type={kind}", timeout=60).json()
            rows = board if isinstance(board, list) else (board.get("stocks") or [])
            tickers |= {str(r.get("ticker")).strip().upper() for r in rows if r.get("ticker")}
    except Exception:
        log.exception("could not fetch market board ticker list")
    tickers = sorted(t for t in tickers if t)
    log.info("reconcile: %d tickers via structured openinfo JSON ...", len(tickers))
    rows, errors = orc.reconcile_all(
        tickers, progress=lambda i, n, t: log.info("reconcile %d/%d %s", i + 1, n, t) if (i % 25 == 0) else None)
    # Two rows per ticker where the latest period is a cumulative quarter: the
    # quarter itself, and the last complete fiscal year beside it. Replace mode
    # clears the ticker before inserting, so the companion has to travel in the
    # same push or the 12-month figure every ratio needs is simply gone.
    push_rows = [r for row in rows for r in orc.admin_push_rows(row)]
    log.info("reconcile: resolved %d tickers (%d period rows), unresolved %d (%s)",
             len(rows), len(push_rows), len(errors), ", ".join(sorted(errors)[:8]))
    if not push_rows:
        log.warning("reconcile produced no rows — skipping push")
        return 1
    return _post("/api/admin/financials", {"form": "NSBU", "rows": push_rows, "mode": "replace"})


def push_heartbeat(status: int) -> None:
    """Stamp this run on prod so a silently dead collector is observable.

    /api/coverage exposes the stamp as data age + staleness flag; a run that
    never completes simply stops refreshing it.
    """
    from datetime import datetime, timezone

    try:
        _post("/api/admin/facts", {"rows": [
            {"entity_id": "_collector", "dataset": "meta", "field": "last_run",
             "period": "", "value": datetime.now(timezone.utc).isoformat(), "source": "collector"},
            {"entity_id": "_collector", "dataset": "meta", "field": "last_run_status",
             "period": "", "value": "ok" if status == 0 else f"exit {status}", "source": "collector"},
        ]})
    except Exception:
        log.exception("heartbeat push failed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true", help="skip financials refresh, push current cache")
    ap.add_argument("--no-push", action="store_true", help="refresh locally, do not push")
    ap.add_argument("--no-financials", action="store_true", help="skip the financials step")
    ap.add_argument("--no-trades", action="store_true", help="skip the trade-stats step")
    ap.add_argument("--trades-only", action="store_true", help="only fetch+push trade stats")
    ap.add_argument("--no-facts", action="store_true", help="skip the source-adapter fact step")
    ap.add_argument("--facts-only", action="store_true", help="only run+push the source-adapter facts")
    ap.add_argument("--no-listings", action="store_true", help="skip the exchange-listing registry step")
    ap.add_argument("--listings-only", action="store_true", help="only collect+push the listing registry")
    ap.add_argument("--no-reconcile", action="store_true", help="skip the structured-JSON reconciliation push")
    ap.add_argument("--reconcile-only", action="store_true",
                    help="only reconcile financials against openinfo JSON and push (authoritative)")
    args = ap.parse_args()

    # Loudly name any package this pipeline needs but the image does not carry:
    # the per-issuer `except Exception` guards below would otherwise turn a
    # missing dependency into a run that "succeeds" having collected nothing.
    preflight(COLLECTOR_REQUIREMENTS, label="collector")

    if args.reconcile_only:
        status = 0
        try:
            status = reconcile_and_push()
        except Exception:
            log.exception("reconcile step failed")
            status = 1
        if not args.no_push:
            push_heartbeat(status)
        return status

    rc_status = 0
    if not (args.no_financials or args.trades_only or args.facts_only or args.listings_only):
        if not args.push_only:
            refresh_local()
        rows = collect_rows()
        filled = sum(1 for r in rows if all(r[k] is not None for k in ("revenue", "net_income", "cash")))
        log.info("collected %d companies (%d full non-bank)", len(rows), filled)
        if rows and not args.no_push:
            rc_status = push(rows) or rc_status

    if not (args.no_financials or args.no_push or args.trades_only or args.facts_only or args.listings_only):
        try:
            rc_status = push_financials_aliases() or rc_status
        except Exception:
            log.exception("financials aliases step failed")
            rc_status = rc_status or 1

    if not (args.no_trades or args.no_push or args.facts_only or args.listings_only):
        try:
            rc_status = push_trade_stats() or rc_status
        except Exception:
            log.exception("trade-stats step failed")
            rc_status = rc_status or 1

    if not (args.no_facts or args.no_push or args.trades_only or args.listings_only):
        try:
            rc_status = collect_and_push_facts() or rc_status
        except Exception:
            log.exception("facts step failed")
            rc_status = rc_status or 1

    if not (args.no_listings or args.no_push or args.trades_only or args.facts_only):
        try:
            rc_status = push_listings() or rc_status
        except Exception:
            log.exception("listings step failed")
            rc_status = rc_status or 1

    # Authoritative structured-JSON reconciliation — runs last so it supersedes the
    # legacy Excel/PDF figures and the alias copies for every ticker openinfo can
    # source directly.
    if not (args.no_reconcile or args.no_push or args.trades_only or args.facts_only or args.listings_only):
        try:
            rc_status = reconcile_and_push() or rc_status
        except Exception:
            log.exception("reconcile step failed")
            rc_status = rc_status or 1

    if not args.no_push:
        push_heartbeat(rc_status)

    return rc_status


if __name__ == "__main__":
    sys.exit(main())
