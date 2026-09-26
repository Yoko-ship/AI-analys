from __future__ import annotations

import server.market.patterns as market_patterns

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from functools import partial
from typing import Any
import asyncio
import hashlib
import json
import reports_catalog as catalog_store
import server.accounts.routes as accounts_routes
import server.auth.access as auth_access
import server.http as http
import web_auth as identity


router = APIRouter()


@router.get("/api/notifications")
async def api_notifications(current_user: identity.WebUser = Depends(auth_access._require_user)) -> dict[str, Any]:
    """Personal PRO alerts plus unread feedback alerts for human admins."""
    try:
        loop = asyncio.get_running_loop()
        # Keep investment notifications a paid feature, while allowing an
        # administrator to use the same bell for operational feedback even if
        # their account's consumer subscription has expired.
        has_pro_access = bool(getattr(current_user, "has_pro_access", False))
        is_human_admin = auth_access._admin_role(current_user) == "administrator"
        favorites = await loop.run_in_executor(
            None, partial(identity.web_auth_store.list_favorites, current_user.id)) if has_pro_access else []
        preferences = await loop.run_in_executor(
            None, partial(identity.web_auth_store.get_preferences, current_user.id)) if has_pro_access else {}
        tickers = [f["ticker"] for f in favorites if f.get("report_alert_enabled", True)] \
            if preferences.get("notify_reports", True) else []
        items = (await loop.run_in_executor(None, partial(catalog_store.get_new_reports_for_tickers, tickers, 7))) \
            if tickers else []
        listings = await loop.run_in_executor(None, catalog_store.get_all_listings) if favorites else {}
        for favorite in favorites if preferences.get("notify_price", True) else []:
            ticker = str(favorite.get("ticker") or "").upper()
            if not ticker:
                continue
            price = (listings.get(ticker) or {}).get("last_price")
            above, below = favorite.get("price_alert_above"), favorite.get("price_alert_below")
            try:
                hit_above = bool(favorite.get("price_alert_enabled")) and above is not None and float(price) >= float(above)
                hit_below = bool(favorite.get("price_alert_enabled")) and below is not None and float(price) <= float(below)
            except (TypeError, ValueError):
                hit_above = hit_below = False
            if hit_above or hit_below:
                threshold = above if hit_above else below
                items.append({"ticker": ticker, "report_form": "PRICE", "year": None, "quarter": 0,
                              "title": f"Price {price:g} reached threshold {threshold:g}",
                              "detected_at": (listings.get(ticker) or {}).get("updated_at"),
                              "kind": "price_threshold", "price": price, "threshold": threshold})
        if favorites and preferences.get("notify_patterns", True):
            items.extend(await market_patterns._pattern_alerts(favorites, list(preferences.get("pattern_alert_types") or [])))
        if is_human_admin:
            from financial_ingestion.maintenance import incidents
            ingestion_alerts = await loop.run_in_executor(None, incidents)
            for incident in ingestion_alerts:
                items.append({"ticker": "ADMIN", "report_form": "DATA_PIPELINE", "year": None, "quarter": 0,
                              "title": f"Bank data: {incident['code']} — {incident['detail']}",
                              "detected_at": incident["first_seen"], "kind": "data_pipeline", "href": "/admin"})
            feedback = await loop.run_in_executor(
                None, partial(identity.web_auth_store.list_support_requests, status="open", limit=100))
            for request in feedback.get("items", []):
                items.append({
                    "ticker": "ADMIN",
                    "report_form": "FEEDBACK",
                    "year": None,
                    "quarter": 0,
                    "title": f"{request.get('full_name') or 'User'}: {request.get('subject') or 'Feedback'}",
                    "detected_at": request.get("created_at"),
                    "kind": "feedback",
                    "feedback_id": request.get("id"),
                    "href": "/admin/feedback",
                })
        states = await loop.run_in_executor(
            None, partial(identity.web_auth_store.notification_states, current_user.id))
        visible: list[dict[str, Any]] = []
        for raw_item in items:
            item = dict(http._json_safe(raw_item))
            fingerprint = json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
            notification_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
            state = states.get(notification_id, {})
            if state.get("dismissed"):
                continue
            item["id"] = notification_id
            item["read"] = bool(state.get("read"))
            visible.append(item)
        unread = sum(1 for item in visible if not item["read"])
        return {"ok": True, "count": unread, "total": len(visible), "items": visible}
    except Exception as exc:
        http.logger.exception("notifications failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/notifications/read")
async def api_notifications_read(
    payload: accounts_routes.NotificationStateRequest,
    current_user: identity.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(identity.web_auth_store.set_notification_state, current_user.id, payload.ids),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "updated": count}


@router.post("/api/notifications/clear")
async def api_notifications_clear(
    payload: accounts_routes.NotificationStateRequest,
    current_user: identity.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.set_notification_state,
                current_user.id,
                payload.ids,
                dismissed=True,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "updated": count}
