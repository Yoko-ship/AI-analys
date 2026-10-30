"""analytics_api.py — the HTTP face of web_analytics.

Two routers, mounted separately in api.py:

* ``public_router`` carries ``POST /api/track`` — the beacon endpoint. It is
  unauthenticated by design (the audience is anonymous), answers 204 to
  everything, and never raises: a tracking failure must not surface in the
  browser console of a visitor who never asked to be counted. The same router
  accepts explicit anonymous ratings at ``POST /api/feedback/ratings``; those
  confirm a durable write or return an error so the visitor can retry.
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
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from psycopg import Error as DatabaseError

from fastapi import APIRouter, HTTPException, Query, Request, Response

import server.auth.limits as auth_limits
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
        ip = auth_limits._client_ip(request)
        country = headers.get("cf-ipcountry") or headers.get("x-vercel-ip-country") \
            or headers.get("x-country-code")
        # ``uid`` is never trusted from this public body. A signed-in view is
        # associated only when the Bearer token resolves on the server; without
        # that, the same event remains anonymous instead of corrupting a user's
        # activity or the signed-in-user metrics.
        trusted_user_id = None
        team_member = False
        scheme, _, token = headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and token.strip():
            try:
                user = await asyncio.get_running_loop().run_in_executor(
                    None, web_auth_store.sessions.get_user_by_token, token.strip())
                trusted_user_id = user.id if user else None
                # An administrator's browsing is the team's, not the audience's.
                if user:
                    from identity.users import is_admin_email

                    team_member = is_admin_email(user.email)
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
            internal=team_member,
        )
    except Exception:
        # Deliberately silent: the beacon is fire-and-forget on both ends.
        logger.debug("track beacon rejected", exc_info=True)
    return Response(status_code=204)


def _run(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(None, partial(fn, *args, **kwargs))


class SiteRatingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_id: uuid.UUID
    rating: int = Field(strict=True, ge=1, le=3)
    page_path: str = Field(max_length=240, pattern=r"^/(?:[A-Za-z0-9_.%-][A-Za-z0-9_/%.\-]*)?$")
    language: Literal["ru", "uz", "en"]


@public_router.post("/api/feedback/ratings")
async def api_site_rating(payload: SiteRatingRequest, request: Request) -> dict[str, bool]:
    key = f"site-rating:{auth_limits._client_ip(request)}"
    if not auth_limits._rate_limiter.allow(key, 10, 3600):
        raise HTTPException(status_code=429, detail="Please try again later.", headers={
            "Retry-After": str(auth_limits._rate_limiter.retry_after(key, 3600)),
        })
    try:
        await _run(web_auth_store.support.create_site_rating, **payload.model_dump(mode="json"))
    except (RuntimeError, DatabaseError) as exc:
        logger.warning("Site rating could not be saved", exc_info=True)
        raise HTTPException(status_code=503, detail="Could not save your rating. Please retry.") from exc
    return {"ok": True}


@admin_router.get("/api/admin/feedback/ratings")
async def api_admin_site_ratings() -> dict[str, Any]:
    try:
        return await _run(web_auth_store.support.list_site_ratings)
    except (RuntimeError, DatabaseError) as exc:
        raise HTTPException(status_code=503, detail="Ratings are temporarily unavailable.") from exc


@admin_router.get("/api/admin/metrics/overview")
async def api_metrics_overview() -> dict[str, Any]:
    return await _run(web_analytics.overview)


@admin_router.get("/api/admin/metrics/audience")
async def api_metrics_audience(days: int = 30, day: str | None = None) -> dict[str, Any]:
    return await _run(web_analytics.audience, days, day)


@admin_router.get("/api/admin/metrics/engagement")
async def api_metrics_engagement(days: int = 30, day: str | None = None) -> dict[str, Any]:
    return await _run(web_analytics.engagement, days, day)


@admin_router.get("/api/admin/metrics/product")
async def api_metrics_product(days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    from product_analytics import product_report

    return await _run(product_report, days)


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
        return await _run(web_auth_store.support.list_support_requests, status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@admin_router.patch("/api/admin/feedback/{request_id}")
async def api_admin_feedback_status(request_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        item = await _run(
            web_auth_store.support.update_support_request_status,
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
    result = await _run(
        web_analytics.user_action, user_id, action,
        actor_user_id=actor.id, actor_email=actor.email,
        request_id=uuid.uuid4().hex,
        source_ip_hash=web_analytics.hash_ip(auth_limits._client_ip(request)),
    )
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    if not result.get("ok") and result.get("reason") == "protected admin":
        raise HTTPException(status_code=409, detail="Allowlisted admin accounts are protected")
    return result


@admin_router.get("/api/admin/metrics/journeys")
async def api_metrics_journeys(days: int = Query(default=7, ge=1, le=90),
                               limit: int = Query(default=50, ge=1, le=100),
                               before: int | None = Query(default=None, ge=1),
                               through: int | None = Query(default=None, ge=0)) -> dict[str, Any]:
    from journey_analytics import journeys_report
    return await _run(journeys_report, days, limit=limit, before=before, through=through)


@admin_router.get("/api/admin/metrics/journeys/{visit_id}")
async def api_metrics_journey(visit_id: int,
                              through: int | None = Query(default=None, ge=0),
                              after: int = Query(default=0, ge=0),
                              limit: int = Query(default=100, ge=1, le=200)) -> dict[str, Any]:
    from journey_analytics import session_journey
    result = await _run(session_journey, visit_id, through=through, after=after, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="Visit not found")
    return result
