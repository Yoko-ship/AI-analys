"""Financials delivery operations with explicit dependencies."""
from __future__ import annotations

import collectors.financials.settings as collectors_financials_settings
import os
import requests


def _post(path: str, body: dict) -> int:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        collectors_financials_settings.log.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    url = os.getenv("FINANCIALS_PUSH_URL", collectors_financials_settings.DEFAULT_URL).rstrip("/") + path
    resp = requests.post(url, json=body, headers={"X-Admin-Secret": secret}, timeout=120)
    if resp.status_code != 200:
        collectors_financials_settings.log.error("push %s failed: HTTP %s %s", path, resp.status_code, resp.text[:300])
        return 1
    collectors_financials_settings.log.info("push %s ok: %s", path, resp.json())
    return 0


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
        collectors_financials_settings.log.exception("step stamp failed: %s", step)


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
        collectors_financials_settings.log.exception("heartbeat push failed")
