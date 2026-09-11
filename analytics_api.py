"""analytics_api.py — the HTTP face of web_analytics.

Two routers, mounted separately in api.py:

* ``public_router`` carries ``POST /api/track`` — the beacon endpoint. It is
  unauthenticated by design (the audience is anonymous), answers 204 to
  everything, and never raises: a tracking failure must not surface in the
  browser console of a visitor who never asked to be counted.
* ``admin_router`` carries the panel's read endpoints and the user actions.
  It is mounted behind the human-admin gate in api.py. Collector secrets are
  intentionally insufficient for user data and account mutations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response

import web_analytics
from web_auth import web_auth_store

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
        # ``uid`` is never trusted from this public body. A signed-in view is
        # associated only when the Bearer token resolves on the server; without
        # that, the same event remains anonymous instead of corrupting a user's
        # activity or the signed-in-user metrics.
        trusted_user_id = None
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            try:
                user = await asyncio.get_running_loop().run_in_executor(
                    None, web_auth_store.get_user_by_token, token.strip())
                trusted_user_id = user.id if user else None
            except Exception:
                # Authentication availability must not turn a best-effort
                # analytics call into a visible application failure.
                logger.debug("track bearer could not be resolved", exc_info=True)
        clean_data = dict(data) if isinstance(data, dict) else data
        if isinstance(clean_data, dict):
            clean_data["uid"] = trusted_user_id
        web_analytics.record_pageview(
            clean_data,
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


@admin_router.get("/api/admin/audit-log")
async def api_admin_audit_log(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    return await _run(web_analytics.admin_audit_log, limit=limit, offset=offset)


@admin_router.get("/api/admin/feedback")
async def api_admin_feedback(status: str = "", limit: int = 100) -> dict[str, Any]:
    """Human-admin inbox for account-linked feedback and support messages."""
    try:
        return await _run(web_auth_store.list_support_requests, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@admin_router.patch("/api/admin/feedback/{request_id}")
async def api_admin_feedback_status(request_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        item = await _run(
            web_auth_store.update_support_request_status,
            request_id,
            (payload or {}).get("status"),
        )
    except ValueError as exc:
        detail = str(exc)
        raise HTTPException(status_code=404 if "not found" in detail.lower() else 400, detail=detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "feedback": item}


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
    actor = getattr(request.state, "admin_user", None)
    if actor is None:  # fail closed even if the router is mounted incorrectly
        raise HTTPException(status_code=403, detail="Admin access required")
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "")
    result = await _run(
        web_analytics.user_action, user_id, action,
        actor_user_id=actor.id, actor_email=actor.email,
        request_id=uuid.uuid4().hex,
        source_ip_hash=web_analytics.hash_ip(ip),
    )
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    if not result.get("ok") and result.get("reason") == "protected admin":
        raise HTTPException(status_code=409, detail="Allowlisted admin accounts are protected")
    return result
