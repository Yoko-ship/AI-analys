from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from urllib.parse import quote, urlencode
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analysis_service import build_company_comparison, build_summary, run_company_analysis
from company_catalog import COMPANY_CATALOG
from openinfo_collector import collect_company_data
from web_auth import WebUser, web_auth_store

logger = logging.getLogger(__name__)


def _json_safe(value):
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]


app = FastAPI(title="UZ Stock Analyzer API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_SOURCE_DIR = Path(__file__).with_name("web")
WEB_DIST_DIR = WEB_SOURCE_DIR / "dist"
WEB_DIR = WEB_DIST_DIR if (WEB_DIST_DIR / "index.html").exists() else WEB_SOURCE_DIR
ASSET_DIR = WEB_DIR / "assets" if WEB_DIR == WEB_DIST_DIR else WEB_DIR
if ASSET_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSET_DIR), name="assets")


class AnalyzeRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    language: Literal["ru", "en", "uz"] = "ru"
    force_refresh: bool = False
    include_html: bool = False
    include_raw: bool = False
    include_all_excel_reports: bool = False
    excel_report_limit: int | None = Field(default=None, ge=0, le=100)


class CompanyDataRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    history_months: int = Field(default=6, ge=1, le=60)
    include_raw_reports: bool = False
    include_document_previews: bool = False
    include_excel_reports: bool = False
    include_all_excel_reports: bool = False
    excel_report_limit: int | None = Field(default=None, ge=0, le=100)
    validate_documents: bool = False


class CompareRequest(BaseModel):
    companies: list[str] = Field(..., min_length=2, max_length=3)
    language: Literal["ru", "en", "uz"] = "ru"
    include_market_context: bool = False
    include_ai_summary: bool = True


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field("", max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    avatar_data_url: str | None = Field(default=None)


class FavoriteToggleRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=40)
    company_name: str | None = Field(default=None, max_length=240)


def _auth_payload(user: WebUser, token: str) -> dict[str, Any]:
    return {
        "ok": True,
        "user": user.to_public_dict(),
        "token": token,
        "token_type": "bearer",
    }


def _require_user(authorization: str | None = Header(default=None)) -> WebUser:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Bearer token authentication")

    try:
        user = web_auth_store.get_user_by_token(token.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Use Bearer token authentication")

    return token.strip()


def _oauth_failure(message: str) -> RedirectResponse:
    return RedirectResponse(url=f"/#oauth_error={quote(message)}", status_code=302)


def _oauth_success(provider: str, token: str) -> RedirectResponse:
    return RedirectResponse(
        url=f"/#provider={quote(provider)}&token={quote(token)}",
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


def _build_google_auth_url(request: Request) -> str:
    client_id = _env_required("GOOGLE_CLIENT_ID")
    redirect_uri = _google_redirect_uri(request)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
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
        "full_name": profile.get("name") or "",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not built yet")
    return FileResponse(
        index_path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/companies")
async def api_companies() -> dict[str, Any]:
    return {
        "ok": True,
        "count": len(COMPANY_CATALOG),
        "companies": [
            {"company_name": name, "ticker": ticker}
            for name, ticker in COMPANY_CATALOG.items()
        ],
    }


@app.post("/api/auth/register")
async def api_register(payload: RegisterRequest) -> dict[str, Any]:
    try:
        user, token = web_auth_store.register_user(
            payload.email,
            payload.password,
            payload.full_name,
        )
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already registered" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@app.post("/api/auth/login")
async def api_login(payload: LoginRequest) -> dict[str, Any]:
    try:
        user, token = web_auth_store.login_user(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@app.get("/api/auth/me")
async def api_me(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    return {"ok": True, "user": current_user.to_public_dict()}


@app.post("/api/auth/logout")
async def api_logout(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    try:
        token = _extract_bearer_token(authorization)
        revoked = web_auth_store.revoke_token(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "revoked": revoked}


@app.get("/api/profile")
async def api_profile(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    try:
        profile = web_auth_store.get_profile(current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **_json_safe(profile)}


@app.patch("/api/profile")
async def api_profile_update(
    payload: ProfileUpdateRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        updated_user = web_auth_store.update_profile(
            current_user.id,
            full_name=payload.full_name,
            avatar_data_url=payload.avatar_data_url,
            set_full_name="full_name" in payload.model_fields_set,
            set_avatar="avatar_data_url" in payload.model_fields_set,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "user": _json_safe(updated_user.to_public_dict())}


@app.get("/api/favorites")
async def api_favorites(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    try:
        favorites = web_auth_store.list_favorites(current_user.id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "count": len(favorites), "favorites": _json_safe(favorites)}


@app.post("/api/favorites/toggle")
async def api_favorites_toggle(
    payload: FavoriteToggleRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        result = web_auth_store.toggle_favorite(
            current_user.id,
            payload.ticker,
            payload.company_name,
        )
        favorites = web_auth_store.list_favorites(current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **_json_safe(result), "favorites": _json_safe(favorites)}


@app.get("/api/auth/oauth/google/start")
async def api_oauth_google_start(request: Request) -> RedirectResponse:
    try:
        return RedirectResponse(_build_google_auth_url(request), status_code=302)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/auth/oauth/google/callback", name="api_oauth_google_callback")
async def api_oauth_google_callback(request: Request, code: str | None = None, error: str | None = None) -> RedirectResponse:
    if error:
        return _oauth_failure(error)
    if not code:
        return _oauth_failure("Google login was cancelled or did not return a code")

    try:
        profile = _exchange_google_code(code, request)
        user, token = web_auth_store.oauth_login(
            "google",
            profile["provider_user_id"],
            profile.get("email"),
            profile.get("full_name") or "",
        )
    except HTTPException:
        raise
    except requests.RequestException as exc:
        return _oauth_failure(f"Google auth failed: {exc}")
    except Exception as exc:
        return _oauth_failure(str(exc))

    return _oauth_success("google", token)


@app.post("/api/company-data")
async def api_company_data(
    payload: CompanyDataRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                collect_company_data,
                payload.company,
                history_months=payload.history_months,
                include_raw_reports=payload.include_raw_reports,
                include_document_previews=payload.include_document_previews,
                include_excel_reports=payload.include_excel_reports,
                include_all_excel_reports=payload.include_all_excel_reports,
                excel_report_limit=payload.excel_report_limit,
                validate_documents=payload.validate_documents,
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenInfo request failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Company data collection failed for %s", payload.company)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result["requested_by"] = current_user.to_public_dict()
    return _json_safe(result)


@app.post("/api/compare")
async def api_compare(
    payload: CompareRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                build_company_comparison,
                payload.companies,
                payload.language,
                payload.include_ai_summary,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Company comparison failed for %s", payload.companies)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not payload.include_market_context:
        for row in (result.get("comparison") or {}).get("rows", []):
            row.pop("market_context", None)

    result["requested_by"] = current_user.to_public_dict()
    return _json_safe(result)


@app.post("/api/analyze")
async def api_analyze(
    payload: AnalyzeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        result = await run_company_analysis(
            payload.company,
            language=payload.language,
            force_refresh=payload.force_refresh,
            include_all_excel_reports=payload.include_all_excel_reports,
            excel_report_limit=payload.excel_report_limit,
        )
    except ValueError as exc:
        logger.exception("Analysis failed with value error for %s", payload.company)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Analysis failed for %s", payload.company)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "ok": True,
        "input": payload.company,
        "language": result.get("language", payload.language),
        "ticker": result.get("ticker"),
        "company_name": result.get("company_name"),
        "model": result.get("model"),
        "annual_period": result.get("annual_period"),
        "quarterly_period": result.get("quarterly_period"),
        "cost": result.get("cost"),
        "from_cache": result.get("from_cache", False),
        "source": result.get("source", "fresh"),
        "summary": build_summary(result),
        "sections": result.get("sections", {}),
        "metrics": result.get("metrics"),
        "ifrs_snapshot": result.get("ifrs_snapshot"),
        "liquidity": result.get("liquidity"),
        "market_data": result.get("market_data"),
        "market_context": result.get("market_context"),
        "excel_report_mode": result.get("excel_report_mode"),
        "analysis_policy_version": result.get("analysis_policy_version"),
        "analysis_policy": result.get("analysis_policy"),
        "requested_by": current_user.to_public_dict(),
    }

    if payload.include_raw:
        response["raw_analysis"] = result.get("raw_analysis")
    if payload.include_html:
        response["html_report"] = result.get("html_report")

    try:
        web_auth_store.record_analysis(current_user.id, payload.model_dump(), result)
    except Exception as exc:
        logger.warning("Failed to record analysis history for user %s: %s", current_user.id, exc)

    return _json_safe(response)
