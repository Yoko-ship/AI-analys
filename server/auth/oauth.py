from __future__ import annotations



from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import RedirectResponse
from typing import Any
from urllib.parse import quote
from urllib.parse import urlencode
import hmac
import os
import requests
import secrets
import threading
import time


# ---------------------------------------------------------------------------
# OAuth handoff: the access token must never appear in a URL (it lands in
# browser history, logs and referrers). The callback stores it under a
# short-lived one-time code; the SPA exchanges the code via POST.
# ---------------------------------------------------------------------------

_OAUTH_CODE_TTL_SECONDS = 120


_oauth_codes: dict[str, tuple[str, str, float]] = {}  # code -> (provider, token, expires_at)


_oauth_codes_lock = threading.Lock()


def _issue_oauth_code(provider: str, token: str) -> str:
    code = secrets.token_urlsafe(32)
    now = time.monotonic()
    with _oauth_codes_lock:
        for stale in [c for c, (_, _, exp) in _oauth_codes.items() if exp < now]:
            _oauth_codes.pop(stale, None)
        _oauth_codes[code] = (provider, token, now + _OAUTH_CODE_TTL_SECONDS)
    return code


def _redeem_oauth_code(code: str) -> tuple[str, str] | None:
    with _oauth_codes_lock:
        entry = _oauth_codes.pop(code, None)
    if not entry or entry[2] < time.monotonic():
        return None
    return entry[0], entry[1]


def _oauth_failure(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/#oauth_error={quote(message)}", status_code=302)


def _oauth_success(provider: str, token: str) -> RedirectResponse:
    code = _issue_oauth_code(provider, token)
    return RedirectResponse(
        url=f"/#provider={quote(provider)}&oauth_code={quote(code)}",
        status_code=302,
    )


def _env_required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(status_code=503, detail=f"{name} is not configured")
    return value


def _public_base_url() -> str:
    raw = os.getenv("PUBLIC_BASE_URL", "").strip()
    if not raw:
        return ""
    return raw.rstrip("/")


def _google_redirect_uri(request: Request | None = None) -> str:
    explicit = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    base_url = _public_base_url()
    if base_url:
        return f"{base_url}/api/auth/oauth/google/callback"
    if request is not None:
        return str(request.url_for("api_oauth_google_callback"))
    raise HTTPException(status_code=503, detail="GOOGLE_REDIRECT_URI or PUBLIC_BASE_URL is not configured")


def _oauth_callback_url(path: str, endpoint_name: str, request: Request | None = None) -> str:
    base_url = _public_base_url()
    if base_url:
        return f"{base_url}{path}"
    if request is not None:
        return str(request.url_for(endpoint_name))
    raise HTTPException(status_code=503, detail="PUBLIC_BASE_URL is not configured")


# ---------------------------------------------------------------------------
# OAuth CSRF protection (RFC 6749 §10.12). Without a `state` bound to the
# browser that started the flow, anyone can feed a victim a callback URL carrying
# an attacker-obtained authorization code and silently sign the victim's browser
# into the ATTACKER's account (login CSRF), and a leaked code can be replayed.
# The state is a random nonce kept in a short-lived HttpOnly, SameSite=Lax cookie
# — the cookie is what proves "the browser hitting the callback is the browser
# that started the flow", so the value never needs to be stored server-side.
# ---------------------------------------------------------------------------

_OAUTH_STATE_COOKIE = "oauth_state"


_OAUTH_STATE_TTL_SECONDS = 600


def _cookies_are_secure(request: Request) -> bool:
    """Whether to mark the state cookie Secure.

    Keyed on the deployment's own public scheme when configured, else on the
    forwarded scheme of this request — a Secure cookie over plain HTTP is dropped
    by the browser, which would break the flow for a local HTTP dev server.
    """
    base = _public_base_url()
    if base:
        return base.startswith("https://")
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").lower()
    return scheme == "https"


def _issue_oauth_state(request: Request, response: RedirectResponse) -> str:
    state = secrets.token_urlsafe(32)
    response.set_cookie(
        _OAUTH_STATE_COOKIE, state,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        secure=_cookies_are_secure(request),
        samesite="lax",  # must survive the top-level redirect back from Google
        path="/api/auth/oauth",
    )
    return state


def _verify_oauth_state(request: Request, state: str | None) -> bool:
    """Constant-time check that the callback's state matches this browser's cookie."""
    expected = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not expected or not state:
        return False
    return hmac.compare_digest(expected, state)


def _clear_oauth_state(response: RedirectResponse) -> None:
    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/api/auth/oauth")


def _build_google_auth_url(request: Request, state: str) -> str:
    client_id = _env_required("GOOGLE_CLIENT_ID")
    redirect_uri = _google_redirect_uri(request)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def _exchange_google_code(code: str, request: Request) -> dict[str, Any]:
    client_id = _env_required("GOOGLE_CLIENT_ID")
    client_secret = _env_required("GOOGLE_CLIENT_SECRET")
    redirect_uri = _google_redirect_uri(request)
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise ValueError(payload.get("error_description") or payload.get("error") or "Google login failed")

    profile_response = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    profile_response.raise_for_status()
    profile = profile_response.json()
    return {
        "provider_user_id": str(profile.get("id") or profile.get("sub") or ""),
        "email": profile.get("email"),
        # Google can return an address it has not verified (non-Gmail sign-ups);
        # only a verified one may join an existing account by email.
        "email_verified": profile.get("verified_email") is True or profile.get("email_verified") is True,
        "full_name": profile.get("name") or "",
    }
