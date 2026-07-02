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


def push(rows: list[dict]) -> int:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        log.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    url = os.getenv("FINANCIALS_PUSH_URL", DEFAULT_URL).rstrip("/") + "/api/admin/financials"
    log.info("pushing %d rows -> %s", len(rows), url)
    resp = requests.post(url, json={"form": "NSBU", "rows": rows},
                         headers={"X-Admin-Secret": secret}, timeout=90)
    if resp.status_code != 200:
        log.error("push failed: HTTP %s %s", resp.status_code, resp.text[:300])
        return 1
    log.info("push ok: %s", resp.json())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-only", action="store_true", help="skip refresh, push current cache")
    ap.add_argument("--no-push", action="store_true", help="refresh locally, do not push")
    args = ap.parse_args()

    if not args.push_only:
        refresh_local()

    rows = collect_rows()
    filled = sum(1 for r in rows if all(r[k] is not None for k in ("revenue", "net_income", "cash")))
    log.info("collected %d companies (%d full non-bank)", len(rows), filled)
    if not rows:
        log.error("no rows to push")
        return 1

    if args.no_push:
        return 0
    return push(rows)


if __name__ == "__main__":
    sys.exit(main())
