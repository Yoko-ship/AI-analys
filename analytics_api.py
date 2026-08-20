"""analytics_api.py — the HTTP face of web_analytics.

Two routers, mounted separately in api.py:

* ``public_router`` carries ``POST /api/track`` — the beacon endpoint. It is
  unauthenticated by design (the audience is anonymous), answers 204 to
  everything, and never raises: a tracking failure must not surface in the
  browser console of a visitor who never asked to be counted.
* ``admin_router`` carries the panel's read endpoints and the user actions.
  It is mounted with ``dependencies=[Depends(_admin_gate)]`` in api.py, so the
  gate stays where the other admin gates live.
"""
from __future__ import annotations

import asyncio
import json
import logging
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

import web_analytics

logger = logging.getLogger(__name__)

public_router = APIRouter()
admin_router = APIRouter()

_TRACK_MAX_BYTES = 4096


@public_router.post("/api/track", status_code=204)
async def api_track(request: Request) -> Response:
    """One beacon, one buffered row. The fast path does no I/O."""
    try:
        body = await request.body()
        if not body or len(body) > _TRACK_MAX_BYTES:
            return Response(status_code=204)
        data = json.loads(body)
        headers = request.headers
        forwarded = headers.get("x-forwarded-for", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else "")
        country = headers.get("cf-ipcountry") or headers.get("x-vercel-ip-country") \
            or headers.get("x-country-code")
        web_analytics.record_pageview(
            data,
            user_agent=headers.get("user-agent", ""),
            ip=ip,
            country=country,
        )
    except Exception:
        # Deliberately silent: the beacon is fire-and-forget on both ends.
        logger.debug("track beacon rejected", exc_info=True)
    return Response(status_code=204)


def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


@admin_router.get("/api/admin/metrics/overview")
async def api_metrics_overview() -> dict[str, Any]:
    return await _run(web_analytics.overview)


@admin_router.get("/api/admin/metrics/audience")
async def api_metrics_audience(days: int = 30) -> dict[str, Any]:
    return await _run(web_analytics.audience, days)


@admin_router.get("/api/admin/metrics/engagement")
async def api_metrics_engagement(days: int = 30) -> dict[str, Any]:
    return await _run(web_analytics.engagement, days)


@admin_router.get("/api/admin/metrics/analysis")
async def api_metrics_analysis(days: int = 30) -> dict[str, Any]:
    return await _run(web_analytics.analysis_usage, days)


@admin_router.get("/api/admin/users")
async def api_admin_users(query: str = "", limit: int = 50, offset: int = 0,
                          only: str = "") -> dict[str, Any]:
    return await _run(web_analytics.users_list, query=query, limit=limit,
                      offset=offset, only=only)


@admin_router.get("/api/admin/users/funnel")
async def api_admin_users_funnel(days: int = 30) -> dict[str, Any]:
    return await _run(web_analytics.users_funnel, days)


@admin_router.get("/api/admin/users/{user_id}")
async def api_admin_user_detail(user_id: int) -> dict[str, Any]:
    result = await _run(web_analytics.user_detail, user_id)
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    return result


@admin_router.post("/api/admin/users/{user_id}/action")
async def api_admin_user_action(user_id: int, payload: dict[str, Any],
                                request: Request) -> dict[str, Any]:
    action = str((payload or {}).get("action") or "").strip()
    if action not in {"deactivate", "reactivate", "revoke_sessions", "delete"}:
        raise HTTPException(status_code=400, detail="Unknown action")
    if action == "delete" and (payload or {}).get("confirm") is not True:
        raise HTTPException(status_code=400, detail="Deletion requires confirm: true")
    result = await _run(web_analytics.user_action, user_id, action,
                        acted_by=request.headers.get("x-request-id", "") or "admin-panel")
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    return result
