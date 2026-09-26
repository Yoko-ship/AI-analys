from __future__ import annotations

import email_delivery

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
import hmac
import os
import sector_access
import web_auth as identity
import identity.users as identity_users
import identity.users as identity_users


def _require_user(authorization: str | None = Header(default=None)) -> identity_users.WebUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Bearer token authentication")

    try:
        user = identity.web_auth_store.sessions.get_user_by_token(token.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def _require_pro(current_user: identity_users.WebUser = Depends(_require_user)) -> identity_users.WebUser:
    """Protect paid analytical work on the server, not just in the browser.

    A hidden button is not an entitlement boundary: a free user could otherwise
    call an analysis/export endpoint directly.  The response is deliberately
    structured so every client can keep the locked feature's context and offer
    the same upgrade path instead of pretending the requested data is absent.
    """
    if not bool(getattr(current_user, "has_pro_access", False)):
        raise HTTPException(status_code=403, detail={
            "code": "PRO_REQUIRED",
            "message": "A PRO subscription is required for this analytical feature.",
            "required_tier": "pro",
        })
    return current_user


def _require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    """Guard for machine-to-machine admin pushes via a shared secret header."""
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret.strip(), secret):
        raise HTTPException(status_code=401, detail="Invalid admin secret")


def _admin_gate(x_admin_secret: str | None = Header(default=None),
                authorization: str | None = Header(default=None)) -> None:
    """Either credential opens the door: the machine secret, or a logged-in admin.

    The collectors present ``X-Admin-Secret`` and must keep working untouched.
    The admin panel runs in a browser, where that secret has no business being вЂ”
    it authenticates as the person who is signed in, and ``ADMIN_EMAILS`` decides
    whether that person is an administrator. Neither path weakens the other:
    a wrong secret is still rejected, and a signed-in non-admin still gets 403.
    """
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if x_admin_secret is not None:
        if not secret:
            raise HTTPException(status_code=503, detail="Admin API is not configured")
        if not hmac.compare_digest(x_admin_secret.strip(), secret):
            raise HTTPException(status_code=401, detail="Invalid admin secret")
        return

    user = _require_user(authorization)          # raises 401 when not signed in
    if _admin_role(user) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")


def _admin_panel_gate(request: Request,
                      authorization: str | None = Header(default=None)) -> identity_users.WebUser:
    """Human-only gate for product metrics, user data and account actions.

    The collector secret deliberately has no authority here.  Keeping it off
    this router is least privilege: a leaked ingestion credential must not be
    able to enumerate users or delete an account.
    """
    user = _require_user(authorization)
    if _admin_role(user) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    request.state.admin_user = user
    return user


def _control_gate(request: Request, authorization: str | None = Header(default=None)):
    from admin_control.store import ControlError
    try:
        user = _require_user(authorization)
    except HTTPException as exc:
        raise ControlError("AUTHENTICATION_REQUIRED", "Sign in with an administrative account.", exc.status_code) from None
    role = _admin_role(user)
    if not role:
        raise ControlError("PERMISSION_DENIED", "Your account does not have administrative access.", 403)
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


def _sector_analysis_gate(request: Request, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    role = _admin_role(user, sector_access.role_for)
    if not role:
        raise HTTPException(status_code=403, detail="Your account does not have administrative access.")
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Bearer token authentication")

    return token.strip()


def _require_admin_user(current_user: identity_users.WebUser = Depends(_require_user)) -> identity_users.WebUser:
    """Gate a route to admin web users (email in ADMIN_EMAILS). Unlike ``_require_admin``
    (machine X-Admin-Secret), this authorises a logged-in user via their Bearer token вЂ”
    so the frontend admin panel can call it without the shared secret ever reaching
    the browser."""
    if _admin_role(current_user) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def _admin_role(user: identity_users.WebUser, resolve=None) -> str | None:
    """The account's administrative role, granted only to a proven inbox.

    Roles are assigned by email address (ADMIN_EMAILS / ADMIN_ROLES), so once
    email verification is on, an address nobody has proven carries no role вЂ”
    registering an allowlisted address must not be a way into the admin panel.
    """
    if email_delivery.verification_enabled() and not user.email_verified:
        return None
    if resolve is None:
        from admin_control.service import role_for as resolve
    return resolve(user.email)
