"""Daily financials collector.

Runs where openinfo.uz is reachable (a machine/proxy on a UZ-allowed network),
recomputes the NSBU headline indicators, and pushes them to the deployed API via
POST /api/admin/financials — because the Railway datacenter IP is blocked by
openinfo and cannot fetch the source data itself.

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
    args = ap.parse_args()

    rc_status = 0
    if not (args.no_financials or args.trades_only or args.facts_only):
        if not args.push_only:
            refresh_local()
        rows = collect_rows()
        filled = sum(1 for r in rows if all(r[k] is not None for k in ("revenue", "net_income", "cash")))
        log.info("collected %d companies (%d full non-bank)", len(rows), filled)
        if rows and not args.no_push:
            rc_status = push(rows) or rc_status

    if not (args.no_trades or args.no_push or args.facts_only):
        try:
            rc_status = push_trade_stats() or rc_status
        except Exception:
            log.exception("trade-stats step failed")
            rc_status = rc_status or 1

    if not (args.no_facts or args.no_push or args.trades_only):
        try:
            rc_status = collect_and_push_facts() or rc_status
        except Exception:
            log.exception("facts step failed")
            rc_status = rc_status or 1

    return rc_status


if __name__ == "__main__":
    sys.exit(main())
