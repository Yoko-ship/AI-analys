from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analysis_service import build_summary, run_company_analysis
from company_catalog import COMPANY_CATALOG
from web_auth import WebUser, web_auth_store


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

WEB_DIR = Path(__file__).with_name("web")
if WEB_DIR.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


class AnalyzeRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    force_refresh: bool = False
    include_html: bool = False
    include_raw: bool = False


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field("", max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index() -> FileResponse:
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not built yet")
    return FileResponse(index_path)


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


@app.post("/api/analyze")
async def api_analyze(
    payload: AnalyzeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        result = await run_company_analysis(
            payload.company,
            force_refresh=payload.force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    response: dict[str, Any] = {
        "ok": True,
        "input": payload.company,
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
        "liquidity": result.get("liquidity"),
        "requested_by": current_user.to_public_dict(),
    }

    if payload.include_raw:
        response["raw_analysis"] = result.get("raw_analysis")
    if payload.include_html:
        response["html_report"] = result.get("html_report")

    return _json_safe(response)
