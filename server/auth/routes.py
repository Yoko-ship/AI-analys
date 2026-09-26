from __future__ import annotations

import email_delivery
import password_policy

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Header
from fastapi import Request
from fastapi.responses import RedirectResponse
from functools import partial
from pydantic import BaseModel
from pydantic import Field
from typing import Any
import asyncio
import requests
import server.auth.access as auth_access
import server.auth.limits as auth_limits
import server.auth.oauth as auth_oauth
import server.http as http
import web_auth as identity
import identity.settings as identity_settings
import identity.users as identity_users
import identity.users as identity_users


router = APIRouter()


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field("", max_length=120)
    language: str = Field("ru", max_length=8)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)
    otp: str | None = Field(default=None, max_length=12)
    language: str = Field("ru", max_length=8)


def _auth_payload(user: identity_users.WebUser, token: str) -> dict[str, Any]:
    return {
        "ok": True,
        "user": user.to_public_dict(),
        "token": token,
        "token_type": "bearer",
    }


class OAuthExchangeRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=128)


@router.post("/api/auth/oauth/exchange")
async def api_oauth_exchange(payload: OAuthExchangeRequest, request: Request) -> dict[str, Any]:
    """Redeem the one-time code from the OAuth redirect for the access token."""
    auth_limits._enforce_auth_rate_limit(request, "oauth-exchange")
    redeemed = auth_oauth._redeem_oauth_code(payload.code)
    if not redeemed:
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in code")
    provider, token = redeemed
    return {"ok": True, "provider": provider, "token": token}


@router.post("/api/auth/register")
async def api_register(payload: RegisterRequest, request: Request) -> dict[str, Any]:
    auth_limits._enforce_auth_rate_limit(request, "register")
    try:
        password_policy.validate_new_password(payload.password, email=payload.email, full_name=payload.full_name)
    except password_policy.WeakPassword as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    loop = asyncio.get_running_loop()
    if email_delivery.verification_enabled():
        # With mail configured, an account is created unusable and a code is
        # sent; the session is issued only by /api/auth/email/verify.
        try:
            code = await loop.run_in_executor(None, partial(
                identity.web_auth_store.accounts.start_registration, payload.email, payload.password, payload.full_name))
        except identity_users.EmailCodeThrottled as exc:
            return _verification_pending(payload.email, exc.retry_after)
        except ValueError as exc:
            message = str(exc)
            status = 409 if "already registered" in message.lower() else 400
            raise HTTPException(status_code=status, detail=message) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await _send_code(identity_users._normalize_email(payload.email), "verify", code, payload.language)
        return _verification_pending(payload.email)

    try:
        # Executor-wrapped: PBKDF2 (~100ms CPU) + a sync Postgres roundtrip
        # would otherwise run on the event loop.
        user, token = await loop.run_in_executor(None, partial(
            identity.web_auth_store.accounts.register_user,
            payload.email,
            payload.password,
            payload.full_name,
            request.headers.get("user-agent"),
            auth_limits._client_ip(request),
        ))
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already registered" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@router.post("/api/auth/login")
async def api_login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    auth_limits._enforce_auth_rate_limit(request, "login")
    loop = asyncio.get_running_loop()
    try:
        user, token = await loop.run_in_executor(
            None, partial(
                identity.web_auth_store.accounts.login_user,
                payload.email,
                payload.password,
                payload.otp,
                request.headers.get("user-agent"),
                auth_limits._client_ip(request),
                require_verified_email=email_delivery.verification_enabled(),
            ))
    except identity_users.AccountLocked as exc:
        if exc.newly_locked and email_delivery.verification_enabled():
            try:
                await loop.run_in_executor(None, partial(
                    email_delivery.send_notice, exc.email, "login_locked", exc.language,
                    limit=identity_settings.LOGIN_FAILURE_LIMIT, minutes=identity_settings.LOGIN_LOCK_MINUTES))
            except Exception:  # noqa: BLE001 - the refusal must not depend on mail
                http.logger.exception("login lock notice could not be sent")
        minutes = max(1, -(-exc.retry_after // 60))
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed sign-in attempts. Try again in {minutes} min or reset your password.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except identity_users.EmailNotVerified as exc:
        # The password was right, so this is the owner (or someone who knows
        # it): send a code to the inbox rather than refusing outright.
        try:
            code = await loop.run_in_executor(None, partial(
                identity.web_auth_store.accounts.issue_email_code, exc.email, "verify"))
        except identity_users.EmailCodeThrottled as throttled:
            return _verification_pending(exc.email, throttled.retry_after)
        if code:
            await _send_code(exc.email, "verify", code, payload.language)
        return _verification_pending(exc.email)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@router.get("/api/auth/me")
async def api_me(current_user: identity_users.WebUser = Depends(auth_access._require_user)) -> dict[str, Any]:
    return {"ok": True, "user": current_user.to_public_dict()}


@router.post("/api/auth/logout")
async def api_logout(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    try:
        token = auth_access._extract_bearer_token(authorization)
        revoked = await asyncio.get_running_loop().run_in_executor(
            None, partial(identity.web_auth_store.sessions.revoke_token, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "revoked": revoked}


@router.get("/api/auth/oauth/google/start")
async def api_oauth_google_start(request: Request) -> RedirectResponse:
    try:
        # The state cookie must be set on the SAME response that redirects to the
        # provider, so build the response first and mint the nonce onto it.
        response = RedirectResponse("about:blank", status_code=302)
        state = auth_oauth._issue_oauth_state(request, response)
        response.headers["location"] = auth_oauth._build_google_auth_url(request, state)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/auth/oauth/google/callback", name="api_oauth_google_callback")
async def api_oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return auth_oauth._oauth_failure(error)
    # Check state BEFORE spending a token exchange on it: an unmatched state means
    # this callback did not originate from a flow this browser started.
    if not auth_oauth._verify_oauth_state(request, state):
        http.logger.warning("oauth callback rejected: state missing or does not match the browser cookie")
        failed = auth_oauth._oauth_failure("Login session expired or invalid — please try signing in again")
        auth_oauth._clear_oauth_state(failed)
        return failed
    if not code:
        return auth_oauth._oauth_failure("Google login was cancelled or did not return a code")

    try:
        loop = asyncio.get_running_loop()
        profile = await loop.run_in_executor(None, partial(auth_oauth._exchange_google_code, code, request))
        user, token = await loop.run_in_executor(None, partial(
            identity.web_auth_store.oauth.oauth_login,
            "google",
            profile["provider_user_id"],
            profile.get("email"),
            profile.get("full_name") or "",
            email_verified=bool(profile.get("email_verified")),
        ))
    except HTTPException:
        raise
    except requests.RequestException as exc:
        return auth_oauth._oauth_failure(f"Google auth failed: {exc}")
    except Exception as exc:
        return auth_oauth._oauth_failure(str(exc))

    # Single-use: the nonce is spent whether or not the login succeeded, so a
    # replayed callback cannot reuse it.
    success = auth_oauth._oauth_success("google", token)
    auth_oauth._clear_oauth_state(success)
    return success


class EmailVerifyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    code: str = Field(..., min_length=6, max_length=12)
    # The browser that proves the inbox chooses the password (see
    # WebAuthStore.verify_email_code); omitted, the current one is kept.
    password: str | None = Field(default=None, min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=120)


class EmailAddressRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    language: str = Field("ru", max_length=8)


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    code: str = Field(..., min_length=6, max_length=12)
    new_password: str = Field(..., min_length=8, max_length=128)


def _mail_language(language: str | None) -> str:
    value = (language or "").strip().lower()[:2]
    return value if value in {"ru", "uz", "en"} else "ru"


async def _send_code(email: str, purpose: str, code: str, language: str | None) -> None:
    try:
        await asyncio.get_running_loop().run_in_executor(None, partial(
            email_delivery.send_code, email, purpose, code, _mail_language(language)))
    except email_delivery.EmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail="Could not send the email — try again later") from exc


def _verification_pending(email: str, retry_after: int | None = None) -> dict[str, Any]:
    """Credentials accepted, no session yet: the client shows the code screen."""
    body: dict[str, Any] = {"ok": True, "verification_required": True,
                            "email": identity_users._normalize_email(email)}
    if retry_after:
        body["retry_after"] = retry_after
    return body


@router.get("/api/auth/options")
async def api_auth_options() -> dict[str, Any]:
    """What the sign-in page may offer: code screens and password reset need mail."""
    return {"ok": True, "email_codes": email_delivery.verification_enabled()}


@router.post("/api/auth/email/verify")
async def api_email_verify(payload: EmailVerifyRequest, request: Request) -> dict[str, Any]:
    auth_limits._enforce_auth_rate_limit(request, "email-verify")
    if payload.password is not None:
        try:
            password_policy.validate_new_password(payload.password, email=payload.email, full_name=payload.full_name or "")
        except password_policy.WeakPassword as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        user, token = await asyncio.get_running_loop().run_in_executor(None, partial(
            identity.web_auth_store.accounts.verify_email_code,
            payload.email,
            payload.code,
            password=payload.password,
            full_name=payload.full_name,
            user_agent=request.headers.get("user-agent"),
            ip_address=auth_limits._client_ip(request),
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not token:
        # Two-factor accounts still owe their authenticator code.
        return {"ok": True, "verified": True, "sign_in_required": True}
    return _auth_payload(user, token)


@router.post("/api/auth/email/resend")
async def api_email_resend(payload: EmailAddressRequest, request: Request) -> dict[str, Any]:
    """Same answer whether or not the address exists, is verified, or is throttled."""
    auth_limits._enforce_auth_rate_limit(request, "email-resend")
    if not email_delivery.verification_enabled():
        return {"ok": True}
    email = identity_users._normalize_email(payload.email)
    try:
        code = await asyncio.get_running_loop().run_in_executor(None, partial(
            identity.web_auth_store.accounts.issue_email_code, email, "verify"))
    except identity_users.EmailCodeThrottled:
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if code:
        await _send_code(email, "verify", code, payload.language)
    return {"ok": True}


@router.post("/api/auth/password/forgot")
async def api_password_forgot(payload: EmailAddressRequest, request: Request) -> dict[str, Any]:
    """Email a reset code; the answer never reveals whether the account exists."""
    auth_limits._enforce_auth_rate_limit(request, "password-forgot")
    if not email_delivery.verification_enabled():
        raise HTTPException(status_code=503, detail="Password reset by email is not available")
    email = identity_users._normalize_email(payload.email)
    try:
        code = await asyncio.get_running_loop().run_in_executor(None, partial(
            identity.web_auth_store.accounts.issue_email_code, email, "reset"))
    except identity_users.EmailCodeThrottled:
        return {"ok": True}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if code:
        await _send_code(email, "reset", code, payload.language)
    return {"ok": True}


@router.post("/api/auth/password/reset")
async def api_password_reset(payload: PasswordResetRequest, request: Request) -> dict[str, Any]:
    auth_limits._enforce_auth_rate_limit(request, "password-reset")
    try:
        password_policy.validate_new_password(payload.new_password, email=payload.email)
    except password_policy.WeakPassword as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        user, token = await asyncio.get_running_loop().run_in_executor(None, partial(
            identity.web_auth_store.accounts.reset_password_with_code,
            payload.email,
            payload.code,
            payload.new_password,
            user_agent=request.headers.get("user-agent"),
            ip_address=auth_limits._client_ip(request),
        ))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not token:
        return {"ok": True, "password_reset": True, "sign_in_required": True}
    return _auth_payload(user, token)
