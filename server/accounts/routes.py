from __future__ import annotations



from datetime import datetime
from datetime import timezone
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
from fastapi.responses import Response
from functools import partial
from pydantic import BaseModel
from pydantic import Field
from typing import Any
from typing import Literal
import reporting.exports as report_exports
import asyncio
import json
import re
import reports_catalog as catalog_store
import catalogue.market_store as catalogue_market_store
import securities_catalog as securities_store
import server.auth.access as auth_access
import server.auth.limits as auth_limits
import server.http as http
import web_auth as identity
import identity.users as identity_users


router = APIRouter()


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    avatar_data_url: str | None = Field(default=None)


class SubscriptionUpdateRequest(BaseModel):
    """Administrative entitlement change after an external payment or trial."""
    tier: Literal["free", "pro"]
    subscription_until: datetime | None = None
    reason: str = Field(..., min_length=3, max_length=1000)


class ProfilePreferencesRequest(BaseModel):
    language: Literal["ru", "en", "uz"] | None = None
    theme: Literal["light", "dark"] | None = None
    text_scale: int | None = Field(default=None, ge=80, le=130)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    default_report_language: Literal["ru", "en", "uz"] | None = None
    default_analysis_period: Literal["latest", "quarterly", "annual"] | None = None
    notify_reports: bool | None = None
    notify_news: bool | None = None
    notify_price: bool | None = None
    notify_analysis: bool | None = None
    notify_patterns: bool | None = None
    pattern_alert_types: list[str] | None = Field(default=None, max_length=40)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class TwoFactorCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=12)


class AnalysisUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)
    archived: bool | None = None
    bookmarked: bool | None = None
    folder: str | None = Field(default=None, max_length=160)
    tags: list[str] | None = Field(default=None, max_length=12)
    pinned_note: str | None = Field(default=None, max_length=4000)


class FavoriteUpdateRequest(BaseModel):
    position: int | None = Field(default=None, ge=0, le=10000)
    price_alert_enabled: bool | None = None
    price_alert_above: float | None = Field(default=None, ge=0)
    price_alert_below: float | None = Field(default=None, ge=0)
    news_alert_enabled: bool | None = None
    report_alert_enabled: bool | None = None
    pattern_alert_enabled: bool | None = None


class PortfolioPositionRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=40)
    quantity: float = Field(..., gt=0, le=1_000_000_000_000)
    average_cost: float = Field(..., ge=0, le=1_000_000_000_000)
    currency: Literal["UZS"] = "UZS"
    note: str = Field(default="", max_length=1000)


class NoteWriteRequest(BaseModel):
    analysis_id: int | None = Field(default=None, ge=1)
    title: str = Field(default="", max_length=160)
    body: str = Field(default="", max_length=8000)
    pinned: bool = False
    tags: list[str] = Field(default_factory=list, max_length=12)


class NotificationStateRequest(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=200)


class ConfirmationRequest(BaseModel):
    confirmation: str = Field(..., min_length=1, max_length=320)


class SupportRequest(BaseModel):
    subject: str = Field(..., min_length=2, max_length=160)
    message: str = Field(..., min_length=5, max_length=6000)


class FavoriteToggleRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=40)
    company_name: str | None = Field(default=None, max_length=240)


@router.patch("/api/admin/users/{user_id}/subscription")
async def api_admin_user_subscription(
    user_id: int,
    payload: SubscriptionUpdateRequest,
    request: Request,
    current_user: identity_users.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Record a manual subscription entitlement with a durable audit entry.

    The payment processor remains external to this product by specification;
    this route is the controlled hand-off after a verified payment, invoice, or
    approved trial.  It intentionally cannot create an administrator role.
    """
    import uuid
    import web_analytics

    until = payload.subscription_until
    if until is not None and until.tzinfo is None:
        raise HTTPException(status_code=422, detail="subscription_until must include a timezone")
    if payload.tier == "pro" and until is not None and until <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="subscription_until must be in the future")
    result = await asyncio.get_running_loop().run_in_executor(
        None,
        partial(
            web_analytics.set_subscription,
            user_id,
            payload.tier,
            until,
            reason=payload.reason,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            request_id=uuid.uuid4().hex,
            source_ip_hash=web_analytics.hash_ip(auth_limits._client_ip(request)),
        ),
    )
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason") or "Subscription was not updated")
    return http._json_safe(result)


@router.get("/api/profile")
async def api_profile(current_user: identity_users.WebUser = Depends(auth_access._require_user)) -> dict[str, Any]:
    try:
        profile = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.profile.get_profile, current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **http._json_safe(profile)}


@router.patch("/api/profile")
async def api_profile_update(
    payload: ProfileUpdateRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        updated_user = await asyncio.get_running_loop().run_in_executor(None, partial(
            identity.web_auth_store.profile.update_profile,
            current_user.id,
            full_name=payload.full_name,
            avatar_data_url=payload.avatar_data_url,
            set_full_name="full_name" in payload.model_fields_set,
            set_avatar="avatar_data_url" in payload.model_fields_set,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "user": http._json_safe(updated_user.to_public_dict())}


@router.get("/api/favorites")
async def api_favorites(current_user: identity_users.WebUser = Depends(auth_access._require_user)) -> dict[str, Any]:
    try:
        favorites = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.favorites.list_favorites, current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "count": len(favorites), "favorites": http._json_safe(favorites)}


@router.post("/api/favorites/toggle")
async def api_favorites_toggle(
    payload: FavoriteToggleRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, partial(
            identity.web_auth_store.favorites.toggle_favorite,
            current_user.id,
            payload.ticker,
            payload.company_name,
        ))
        favorites = await loop.run_in_executor(
            None, partial(identity.web_auth_store.favorites.list_favorites, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **http._json_safe(result), "favorites": http._json_safe(favorites)}


@router.patch("/api/profile/preferences")
async def api_profile_preferences(
    payload: ProfilePreferencesRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        preferences = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.profile.update_preferences,
                current_user.id,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "preferences": http._json_safe(preferences)}


@router.post("/api/profile/password")
async def api_profile_password(
    payload: PasswordChangeRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = auth_access._extract_bearer_token(authorization)
        revoked = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.security.change_password,
                current_user.id,
                payload.current_password,
                payload.new_password,
                token,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "revoked_sessions": revoked}


@router.get("/api/profile/sessions")
async def api_profile_sessions(
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = auth_access._extract_bearer_token(authorization)
        sessions = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.sessions.list_sessions, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "sessions": http._json_safe(sessions)}


@router.delete("/api/profile/sessions/{session_id}")
async def api_profile_session_delete(
    session_id: int,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = auth_access._extract_bearer_token(authorization)
        revoked = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.sessions.revoke_session, current_user.id, session_id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found or cannot revoke current session")
    return {"ok": True, "revoked": True}


@router.post("/api/profile/sessions/revoke-others")
async def api_profile_sessions_revoke_others(
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = auth_access._extract_bearer_token(authorization)
        count = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.sessions.revoke_other_sessions, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "revoked_sessions": count}


@router.post("/api/profile/2fa/setup")
async def api_profile_two_factor_setup(
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        setup = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.security.begin_two_factor, current_user.id))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, **setup}


@router.post("/api/profile/2fa/enable")
async def api_profile_two_factor_enable(
    payload: TwoFactorCodeRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.security.enable_two_factor, current_user.id, payload.code))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "two_factor_enabled": True}


@router.post("/api/profile/2fa/disable")
async def api_profile_two_factor_disable(
    payload: TwoFactorCodeRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.security.disable_two_factor, current_user.id, payload.code))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "two_factor_enabled": False}


@router.patch("/api/profile/analyses/{analysis_id}")
async def api_profile_analysis_update(
    analysis_id: int,
    payload: AnalysisUpdateRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.research.update_analysis,
                current_user.id,
                analysis_id,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "analysis": http._json_safe(analysis)}


@router.delete("/api/profile/analyses/{analysis_id}")
async def api_profile_analysis_delete(
    analysis_id: int,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.research.delete_analysis, current_user.id, analysis_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"ok": True, "deleted": True}


@router.get("/api/profile/analyses/{analysis_id}/export")
async def api_profile_analysis_export(
    analysis_id: int,
    format: Literal["pdf", "csv"] = "pdf",
    language: Literal["ru", "en", "uz"] = "ru",
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> Response:
    try:
        analysis = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.research.get_analysis, current_user.id, analysis_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ticker = re.sub(r"[^A-Za-z0-9_-]+", "-", analysis.get("ticker") or f"analysis-{analysis_id}")
    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["field", "value"])
        for key in ("title", "company_name", "ticker", "score", "grade", "verdict", "summary_text", "folder", "tags", "pinned_note", "created_at"):
            value = analysis.get(key)
            writer.writerow([key, ", ".join(value) if isinstance(value, list) else value or ""])
        return Response(
            content=output.getvalue().encode("utf-8-sig"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{ticker}-analysis.csv"'},
        )

    export_result = {
        "company_name": analysis.get("company_name") or analysis.get("company_input"),
        "ticker": analysis.get("ticker"),
        "summary": {
            "score": analysis.get("score"),
            "grade": analysis.get("grade"),
            "verdict": analysis.get("verdict"),
            "itog": analysis.get("summary_text"),
        },
        "sections": {
            "Saved note": analysis.get("pinned_note") or "",
        },
    }
    content = await asyncio.get_running_loop().run_in_executor(
        None, partial(report_exports.build_analysis_pdf, export_result, language, datetime.now()))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ticker}-analysis.pdf"'},
    )


@router.patch("/api/favorites/{ticker}")
async def api_favorite_update(
    ticker: str,
    payload: FavoriteUpdateRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        favorite = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.favorites.update_favorite,
                current_user.id,
                ticker,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "favorite": http._json_safe(favorite)}


@router.get("/api/portfolio")
async def api_portfolio(current_user: identity_users.WebUser = Depends(auth_access._require_pro)) -> dict[str, Any]:
    """Value explicitly entered holdings against the last confirmed UZSE price.

    A missing or stale quote remains a missing valuation; it is never filled
    from an external aggregator or from the user's acquisition cost.
    """
    loop = asyncio.get_running_loop()
    positions, listings, securities = await asyncio.gather(
        loop.run_in_executor(None, partial(identity.web_auth_store.portfolio.list_portfolio_positions, current_user.id)),
        loop.run_in_executor(None, catalogue_market_store.get_all_listings),
        loop.run_in_executor(None, securities_store.get_securities_map),
    )
    items: list[dict[str, Any]] = []
    total_market_value = total_cost = 0.0
    priced_count = 0
    for position in positions:
        ticker = str(position["ticker"]).upper()
        listing, security = listings.get(ticker) or {}, securities.get(ticker) or {}
        try:
            price = float(listing.get("last_price"))
            if price <= 0:
                raise ValueError
        except (TypeError, ValueError):
            price = None
        quantity, average_cost = float(position["quantity"]), float(position["average_cost"])
        cost_value = quantity * average_cost
        market_value = quantity * price if price is not None else None
        pnl = market_value - cost_value if market_value is not None else None
        if market_value is not None:
            priced_count += 1
            total_market_value += market_value
            total_cost += cost_value
        item = {**position, "security_type": security.get("type") or security.get("security_type"),
                "company_name": security.get("company_name") or security.get("name"),
                "last_price": price, "quote_updated_at": listing.get("updated_at"),
                "cost_value": cost_value, "market_value": market_value, "unrealized_pnl": pnl,
                "unrealized_pnl_pct": (pnl / cost_value * 100) if pnl is not None and cost_value > 0 else None,
                "valuation_status": "AVAILABLE" if market_value is not None else "NO_DATA"}
        items.append(item)
    return http._json_safe({"ok": True, "items": items, "count": len(items),
                       "priced_count": priced_count, "market_value": total_market_value if priced_count else None,
                       "cost_value": total_cost if priced_count else None,
                       "unrealized_pnl": (total_market_value - total_cost) if priced_count else None,
                       "price_basis": "last confirmed exchange trade", "currency": "UZS"})


@router.put("/api/portfolio/positions")
async def api_portfolio_position_upsert(
    payload: PortfolioPositionRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    ticker = payload.ticker.strip().upper()
    securities = await asyncio.get_running_loop().run_in_executor(None, securities_store.get_securities_map)
    if ticker not in securities:
        raise HTTPException(status_code=404, detail="Unknown security ticker")
    try:
        position = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.portfolio.upsert_portfolio_position, current_user.id, ticker,
                          quantity=payload.quantity, average_cost=payload.average_cost,
                          currency=payload.currency, note=payload.note))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "position": http._json_safe(position)}


@router.delete("/api/portfolio/positions/{ticker}")
async def api_portfolio_position_delete(
    ticker: str, current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    deleted = await asyncio.get_running_loop().run_in_executor(
        None, partial(identity.web_auth_store.portfolio.delete_portfolio_position, current_user.id, ticker))
    if not deleted:
        raise HTTPException(status_code=404, detail="Portfolio position not found")
    return {"ok": True, "ticker": ticker.strip().upper(), "deleted": True}


@router.post("/api/profile/notes")
async def api_profile_note_create(
    payload: NoteWriteRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        note = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.notes.save_note, current_user.id, None, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "note": http._json_safe(note)}


@router.patch("/api/profile/notes/{note_id}")
async def api_profile_note_update(
    note_id: int,
    payload: NoteWriteRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        note = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.notes.save_note, current_user.id, note_id, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "note": http._json_safe(note)}


@router.delete("/api/profile/notes/{note_id}")
async def api_profile_note_delete(
    note_id: int,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.notes.delete_note, current_user.id, note_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True, "deleted": True}


@router.post("/api/profile/support")
async def api_profile_support(
    payload: SupportRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        request = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                identity.web_auth_store.support.create_support_request,
                current_user.id,
                payload.subject,
                payload.message,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "request": http._json_safe(request)}


@router.get("/api/profile/export")
async def api_profile_export(
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
    authorization: str | None = Header(default=None),
) -> Response:
    try:
        token = auth_access._extract_bearer_token(authorization)
        exported = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.profile.export_user_data, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=json.dumps(http._json_safe(exported), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="uz-stock-profile-data.json"'},
    )


@router.delete("/api/profile/history")
async def api_profile_history_clear(
    payload: ConfirmationRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    if payload.confirmation.strip() != "CLEAR":
        raise HTTPException(status_code=400, detail='Enter "CLEAR" to confirm history deletion')
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.research.clear_analysis_history, current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "deleted_analyses": count}


@router.delete("/api/profile/account")
async def api_profile_account_delete(
    payload: ConfirmationRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.profile.delete_account, current_user.id, payload.confirmation))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "deleted": deleted}
