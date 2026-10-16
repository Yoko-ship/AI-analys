from __future__ import annotations

import email_delivery

from fastapi import Depends
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
import hashlib
import hmac
import os
import sector_access
import server.auth.limits as auth_limits
import threading
import time
import web_auth as identity
import identity.users as identity_users
import identity.users as identity_users


# ---------------------------------------------------------------------------
# Admin step-up. A session token sits in the browser's storage for 30 days, so
# on its own it must not be enough to change anything through an admin route:
# whoever holds a copied token would hold the whole panel. Every admin gate that
# admits a person asks this for any request that is not a read; the person
# proves their authenticator once, and the proof is bound to this session for
# ADMIN_STEP_UP_SECONDS. The machine secret (collectors) is not a person and
# is not asked. In memory, like the rate limiter: prod runs one worker, and a
# restart only means entering the code again.
# ---------------------------------------------------------------------------

ADMIN_STEP_UP_SECONDS = int(os.getenv("ADMIN_STEP_UP_SECONDS", "900"))
STEP_UP_ATTEMPTS_PER_MINUTE = 5
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_step_ups: dict[str, tuple[int, float]] = {}  # session token hash -> (user id, valid until)
_step_ups_lock = threading.Lock()

MFA_REQUIRED_MESSAGE = ("Enter a current authenticator code. Enable two-factor "
                        "authentication in your account settings first.")


def _session_key(request: Request) -> str:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return ""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def _record_step_up(request: Request, user_id: int) -> None:
    key = _session_key(request)
    if not key:
        return
    now = time.monotonic()
    with _step_ups_lock:
        for stale in [k for k, (_, until) in _step_ups.items() if until <= now]:
            _step_ups.pop(stale, None)
        _step_ups[key] = (user_id, now + ADMIN_STEP_UP_SECONDS)


def _step_up_attempt_allowed(user_id: int) -> bool:
    """Six digits are guessable without a ceiling; a stolen token gets 5 a minute."""
    return auth_limits._rate_limiter.allow(f"step-up:{user_id}", STEP_UP_ATTEMPTS_PER_MINUTE, 60.0)


def _verify_step_up_code(request: Request, user_id: int, code: str) -> bool:
    if not identity.web_auth_store.security.verify_admin_two_factor(user_id, code):
        return False
    _record_step_up(request, user_id)
    return True


def _step_up_satisfied(request: Request, user_id: int) -> bool:
    """Whether this request may change state on behalf of an admin person.

    Reads always may. A change may when this session proved the authenticator
    recently, or when the request itself carries a valid ``X-Admin-OTP``.
    """
    if request.method in _READ_METHODS:
        return True
    key = _session_key(request)
    with _step_ups_lock:
        entry = _step_ups.get(key)
    if entry and entry[0] == user_id and entry[1] > time.monotonic():
        return True
    code = request.headers.get("x-admin-otp") or ""
    if not code or not _step_up_attempt_allowed(user_id):
        return False
    return _verify_step_up_code(request, user_id, code)


def _require_step_up(request: Request, user: identity_users.WebUser) -> None:
    if not _step_up_satisfied(request, user.id):
        raise HTTPException(status_code=403, detail={"code": "MFA_REQUIRED", "message": MFA_REQUIRED_MESSAGE})


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


# Values published in this public repository (.env.example and the docs). A
# deployment left on one is open to anyone who reads the repo, so it counts as
# not configured: machine pushes answer 503 instead of accepting the world.
PUBLISHED_PLACEHOLDER_SECRETS = frozenset({"your_admin_push_secret", "changeme", "change-me", "secret"})


def _machine_secret() -> str:
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if secret.lower() in PUBLISHED_PLACEHOLDER_SECRETS:
        return ""
    return secret


def _require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    """Guard for machine-to-machine admin pushes via a shared secret header."""
    secret = _machine_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret.strip(), secret):
        raise HTTPException(status_code=401, detail="Invalid admin secret")


def _admin_gate(request: Request,
                x_admin_secret: str | None = Header(default=None),
                authorization: str | None = Header(default=None)) -> None:
    """Either credential opens the door: the machine secret, or a logged-in admin.

    The collectors present ``X-Admin-Secret`` and must keep working untouched.
    The admin panel runs in a browser, where that secret has no business being вЂ”
    it authenticates as the person who is signed in, and ``ADMIN_EMAILS`` decides
    whether that person is an administrator. Neither path weakens the other:
    a wrong secret is still rejected, and a signed-in non-admin still gets 403.
    """
    secret = _machine_secret()
    if x_admin_secret is not None:
        if not secret:
            raise HTTPException(status_code=503, detail="Admin API is not configured")
        if not hmac.compare_digest(x_admin_secret.strip(), secret):
            raise HTTPException(status_code=401, detail="Invalid admin secret")
        return

    user = _require_user(authorization)          # raises 401 when not signed in
    if _admin_role(user) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_step_up(request, user)


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
    _require_step_up(request, user)
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
    if not _step_up_satisfied(request, user.id):
        raise ControlError("MFA_REQUIRED", MFA_REQUIRED_MESSAGE, 403)
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


def _sector_analysis_gate(request: Request, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    role = _admin_role(user, sector_access.role_for)
    if not role:
        raise HTTPException(status_code=403, detail="Your account does not have administrative access.")
    _require_step_up(request, user)
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Bearer token authentication")

    return token.strip()


def _require_admin_user(request: Request,
                        current_user: identity_users.WebUser = Depends(_require_user)) -> identity_users.WebUser:
    """Gate a route to admin web users (email in ADMIN_EMAILS). Unlike ``_require_admin``
    (machine X-Admin-Secret), this authorises a logged-in user via their Bearer token вЂ”
    so the frontend admin panel can call it without the shared secret ever reaching
    the browser."""
    if _admin_role(current_user) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_step_up(request, current_user)
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
