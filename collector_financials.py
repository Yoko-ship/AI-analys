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
        rows.append({
            "ticker": ticker,
            "year": r.get("year"),
            "quarter": r.get("quarter"),
            **{k: r.get(k) for k in KEYS},
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


def push_trade_stats() -> int:
    """Fetch the latest-day per-trade stats from UZSE and push to prod."""
    log.info("fetching UZSE trade stats (latest day) ...")
    data = ts.fetch_trade_stats()
    rows = list((data.get("stats") or {}).values())
    log.info("trade stats: %d securities for %s", len(rows), data.get("trade_date"))
    if not rows:
        log.warning("no trade stats fetched")
        return 1
    return _post("/api/admin/trade-stats", {"trade_date": data.get("trade_date"), "rows": rows})


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

    log.info("running source adapters (fact store) ...")
    res = ds.run_all()
    log.info("adapters: %s", res.get("collectors"))
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
    args = ap.parse_args()

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

    return rc_status


if __name__ == "__main__":
    sys.exit(main())
