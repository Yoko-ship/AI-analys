from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from functools import partial
from urllib.parse import quote, urlencode
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Load .env BEFORE any project import: several modules (db paths, API keys,
# cache locations) read the environment at import time. Previously this worked
# only via an accidental load_dotenv() buried in analyzer.py's import chain.
load_dotenv()

from analysis_service import build_analysis_excel, build_analysis_pdf, build_company_comparison, build_comparison_excel, build_comparison_pdf, build_summary, report_disclaimer, run_company_analysis  # noqa: E402
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from delisted import DELISTED_TICKERS
from openinfo_collector import collect_company_data, get_company_periods
import news_store  # noqa: E402 — §3.11 editorial-news store
from reports_catalog import (
    _TICKER_TO_NAME,
    FIN_MONEY_FIELDS,
    NSBU_THOUSANDS_UZS,
    RATIO_MONEY_FIELDS,
    build_dynamics_data,
    compute_financial_ratios,
    fetch_report_excel_data,
    audit_financials_consistency,
    get_catalog_coverage,
    get_catalog_stats,
    get_company_index,
    get_facts,
    upsert_facts,
    get_company_reports,
    get_company_ratios_cached,
    get_all_financials,
    get_all_ratios,
    bulk_upsert_financials,
    bulk_replace_financials,
    get_all_trade_stats,
    bulk_upsert_trade_stats,
    get_all_quotes,
    bulk_upsert_quotes,
    get_all_listings,
    bulk_upsert_listings,
    purge_delisted,
    refresh_financials_cache,
    get_new_reports_for_tickers,
    get_recent_new_reports,
    get_report_urls,
    get_sector_averages,
    list_companies_with_stats,
    upsert_ratio_cache,
    sync_company as catalog_sync_company,
    sync_all as catalog_sync_all,
)
from market_audit import audit_session
# ТЗ v1.2 domain layer: every formula lives in these, and nothing above them
# recomputes one. The API is serialisation and cache headers only (§11.1).
import formulas  # noqa: E402
import fundamentals  # noqa: E402
import heatmap  # noqa: E402
import instruments  # noqa: E402
import invariants  # noqa: E402
import obs  # noqa: E402
import cache_layer  # noqa: E402
import logo_store  # noqa: E402
import migrations  # noqa: E402
import bonds  # noqa: E402
import provenance  # noqa: E402

# ТЗ §11.6: each change ships behind a flag so it can be turned off without a
# rollback. The interface reads them from /api/config rather than guessing.
FEATURE_FLAGS: dict[str, bool] = {
    key: os.getenv(f"FLAG_{key.upper()}", "1").strip().lower() not in {"0", "false", "no"}
    for key in ("catalog_v2", "metrics_v2", "tiers_v1", "multiples_v2",
                "market_validation_v1", "map_v2", "audit_v1")
}
from securities_catalog import get_securities_map, get_wiki_info, record_volume, resolve_logo, sync_securities
from web_auth import WebUser, web_auth_store, is_admin_email

logger = logging.getLogger(__name__)

_LOGOS_PATH = Path(__file__).with_name("company_logos.json")


def _load_logos() -> dict[str, str]:
    try:
        import json
        return json.loads(_LOGOS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


COMPANY_LOGOS: dict[str, str] = _load_logos()


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


# ТЗ §10.10: /docs and /openapi.json describe every route including the ones
# authorisation protects, together with their request shapes. That is a fine
# thing to hand a developer on staging and a poor thing to publish.
_EXPOSE_SCHEMA = os.getenv("APP_ENV", "production").strip().lower() in {"local", "dev", "staging"}
app = FastAPI(
    title="UZ Stock Analyzer API", version="1.2.0",
    docs_url="/docs" if _EXPOSE_SCHEMA else None,
    redoc_url="/redoc" if _EXPOSE_SCHEMA else None,
    openapi_url="/openapi.json" if _EXPOSE_SCHEMA else None,
)
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


class _ImmutableAssets(StaticFiles):
    """Content-hashed bundles, cached for a year (ТЗ §10.9).

    Vite writes the content hash into every asset filename, so `index-a1b2c3.js`
    can never change meaning — a new build is a new name. Serving it with no
    cache header at all, which is what happened before, made the browser
    revalidate a file that is immutable by construction on every single load.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


if ASSET_DIR.exists():
    app.mount("/assets", _ImmutableAssets(directory=ASSET_DIR), name="assets")

LOGO_DIR = Path(__file__).with_name("logos")
if LOGO_DIR.exists():
    app.mount("/logos", StaticFiles(directory=LOGO_DIR), name="logos")

UZSE_STOCK_API_BASE = os.getenv("UZSE_STOCK_API_BASE", "https://uzse-stock-production.up.railway.app").rstrip("/")

# Tickers suppressed from the market board. Display-only: the underlying
# financials/catalog data is left intact and each /company/<ticker> page stays
# reachable by direct link — which is the difference from DELISTED_TICKERS, whose
# rows are deleted outright and are folded in here so the board filter covers both.
# Extend at runtime via BOARD_DENYLIST_EXTRA (comma-separated) without a code change.
# KFSKP was suppressed here as a dormant registry line; it is not one — Kafolat's
# preferred share traded 39 times on 31.07 and closed +17.27%, third on the
# exchange's own top-gainers board. It was invisible because the /stocks mirror
# does not carry it, not because it is quiet.
BOARD_DENYLIST = DELISTED_TICKERS | frozenset(
    {t.strip().upper() for t in os.getenv("BOARD_DENYLIST_EXTRA", "").split(",") if t.strip()})


async def _populate_securities_on_startup() -> None:
    """Seed the securities table after a (re)deploy.

    The catalog table is otherwise only filled as a side effect of
    ``/api/market/stocks`` (i.e. when the Market view is opened). On Railway the
    SQLite file is ephemeral, so it is empty on every boot — which makes every
    ``/company/<ticker>`` page 404 ("no information") until someone loads Market.
    Pull the stock and bond lists once at startup so the catalog is ready
    immediately. Runs in the background and swallows errors so a slow or
    unreachable UZSE API never blocks (or crashes) boot.
    """
    loop = asyncio.get_running_loop()
    logos = _load_logos()
    for security_type in (None, "bond"):
        try:
            params = {"type": security_type} if security_type else None
            resp = await loop.run_in_executor(
                None, partial(requests.get, f"{UZSE_STOCK_API_BASE}/stocks", params=params, timeout=20)
            )
            resp.raise_for_status()
            payload = resp.json()
            stocks = payload.get("stocks") if isinstance(payload, dict) else []
            stocks_list = stocks if isinstance(stocks, list) else []
            if stocks_list:
                count = await loop.run_in_executor(None, partial(sync_securities, stocks_list, logos))
                await loop.run_in_executor(None, partial(record_volume, stocks_list))
                logger.info("startup securities sync (%s): %d rows", security_type or "all", count)
        except Exception:
            logger.exception("startup securities sync failed for type=%s", security_type)


@app.on_event("startup")
async def _on_startup() -> None:
    # ТЗ §10.10: migrations are applied before deploy, so a process that has just
    # started serves a shape it recognises. Additive and idempotent, so a boot
    # with nothing pending costs one query; a failure leaves /ready answering 503
    # rather than a request answering wrongly.
    try:
        from reports_catalog import get_catalog_conn

        def _migrate() -> dict[str, Any]:
            conn = get_catalog_conn()
            try:
                return migrations.upgrade(conn)
            finally:
                conn.close()

        result = await asyncio.get_running_loop().run_in_executor(None, _migrate)
        if result.get("applied"):
            logger.info("startup migrations applied: %s", ", ".join(result["applied"]))
        elif not result.get("ok"):
            logger.error("startup migrations FAILED at version %s: %s",
                         result.get("failed"), result.get("error"))
    except Exception:
        logger.exception("startup migrations could not run")
    # The catalog DB lives on a mounted volume, so rows removed from the site
    # survive a redeploy. Purge on boot — idempotent, and it makes deleting a
    # ticker a code change rather than a manual DB step.
    try:
        removed = await asyncio.get_running_loop().run_in_executor(None, purge_delisted)
        if removed:
            logger.info("startup purge of delisted securities: %s", removed)
    except Exception:
        logger.exception("startup purge of delisted securities failed")
    # Fire-and-forget: seed the catalog without blocking the server from accepting
    # requests. The Market endpoint still refreshes it on demand afterwards.
    asyncio.create_task(_populate_securities_on_startup())


class AnalyzeRequest(BaseModel):
    company: str = Field(..., min_length=1, max_length=200)
    language: Literal["ru", "en", "uz"] = "ru"
    force_refresh: bool = False
    include_html: bool = False
    include_raw: bool = False
    include_all_excel_reports: bool = False
    excel_report_limit: int | None = Field(default=None, ge=0, le=100)
    report_analysis_type: Literal["latest", "quarterly", "annual"] = "latest"
    report_quarter: int | None = Field(default=None, ge=1, le=4)
    report_current_year: int | None = Field(default=None, ge=1900, le=2100)
    report_previous_year: int | None = Field(default=None, ge=1900, le=2100)
    report_form: Literal["IFRS", "NAS", "Audit"] = "IFRS"


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
    companies: list[str] = Field(..., min_length=2, max_length=5)
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


class CatalogSyncRequest(BaseModel):
    ticker: str | None = Field(default=None, max_length=40)
    force: bool = False


class CatalogAnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=40)
    year: int = Field(..., ge=2000, le=2100)
    quarter: int = Field(default=0, ge=0, le=3)
    form: Literal["NSBU", "MSFO", "Audition"] = "NSBU"
    analysis_type: str = Field(default="financial", max_length=40)
    language: Literal["ru", "en", "uz"] = "ru"
    # Used by the quarter_compare / annual_compare / multi_company modes. These
    # fields used to sit on the Admin* models by mistake, so all three modes
    # died with AttributeError → HTTP 500 on every request.
    compare_ticker: str | None = Field(default=None, max_length=40)
    compare_year: int | None = Field(default=None, ge=2000, le=2100)
    compare_quarter: int | None = Field(default=None, ge=0, le=3)


class AdminFinancialsRequest(BaseModel):
    form: Literal["NSBU", "MSFO", "Audition"] = "NSBU"
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    # "upsert" (default) keeps other stored periods; "replace" makes each row the
    # sole/authoritative period for its ticker (used by the reconciler push).
    mode: Literal["upsert", "replace"] = "upsert"


class AdminTradeStatsRequest(BaseModel):
    trade_date: str | None = Field(default=None, max_length=16)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminQuotesRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminFactsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)


class AdminListingsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminNewsRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class AdminNewsImagesRequest(BaseModel):
    """url → preview-image URL, for image-only updates of already-stored items."""
    images: dict[str, str] = Field(default_factory=dict)


class AdminNewsSnippetsRequest(BaseModel):
    """url → replacement snippet, for enriching already-stored filings in place."""
    snippets: dict[str, str] = Field(default_factory=dict)


class AdminNewsTranslationsRequest(BaseModel):
    """url → {"en": ..., "uz": ...}, for rows stored before those columns existed."""
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)


class AdminNewsKnownRequest(BaseModel):
    """Candidate URLs a collector is about to classify, for a dedup check against prod."""
    urls: list[str] = Field(default_factory=list, max_length=5000)


# TZ §3.11: every news signal is statistical/analytical, never a diagnosis or a
# claim of manipulation. Returned with every editorial-news response.
NEWS_DISCLAIMER = (
    "Тональность новостей и оценка влияния — статистический сигнал, а не рекомендация "
    "и не утверждение о манипуляции. Оценки сформированы моделью и могут быть неточными."
)


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


def _require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    """Guard for machine-to-machine admin pushes via a shared secret header."""
    secret = os.getenv("ADMIN_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Admin API is not configured")
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret.strip(), secret):
        raise HTTPException(status_code=401, detail="Invalid admin secret")


# ---------------------------------------------------------------------------
# Abuse limits (in-memory; prod runs a single uvicorn worker).
# ---------------------------------------------------------------------------

AUTH_RATE_LIMIT_PER_MINUTE = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "10"))
LLM_RATE_LIMIT_PER_MINUTE = int(os.getenv("LLM_RATE_LIMIT_PER_MINUTE", "5"))
LLM_DAILY_LIMIT = int(os.getenv("LLM_DAILY_LIMIT", "50"))
# Deployment-wide daily ceiling on paid LLM calls. Registration is open and
# unverified, so a per-user cap bounds nothing on its own — N accounts buy N
# quotas. Raise deliberately; 0 disables the ceiling.
LLM_GLOBAL_DAILY_LIMIT = int(os.getenv("LLM_GLOBAL_DAILY_LIMIT", "500"))


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            events = [t for t in self._events.get(key, []) if now - t < window_seconds]
            if len(events) >= limit:
                self._events[key] = events
                return False
            events.append(now)
            self._events[key] = events
            if len(self._events) > _LIMITER_MAX_KEYS:
                self._evict_expired(now, window_seconds)
            return True

    def _evict_expired(self, now: float, window_seconds: float) -> None:
        """Drop buckets with nothing left in the window (caller holds the lock).

        Without this the dict grows one entry per distinct key forever, which on a
        long-lived single-worker process is an unbounded memory leak driven by
        untrusted input (one bucket per client IP that ever hit an auth endpoint).
        """
        stale = [k for k, ts in self._events.items()
                 if not ts or now - ts[-1] >= window_seconds]
        for k in stale:
            self._events.pop(k, None)


# Guard-rail before eviction runs — high enough that normal traffic never pays
# for the sweep, low enough that the dict cannot grow without bound.
_LIMITER_MAX_KEYS = int(os.getenv("RATE_LIMIT_MAX_KEYS", "20000"))

_rate_limiter = _SlidingWindowLimiter()

# How many reverse proxies sit in front of this process. X-Forwarded-For is
# APPEND-only: each hop adds the address it saw, so the last entry is the one
# added by our own edge proxy and the leftmost entries are whatever the client
# chose to send. Trusting the leftmost entry — as this did — let any client
# supply "X-Forwarded-For: <random>" and get a brand-new rate-limit bucket on
# every request, which defeats login brute-force and mass-signup protection
# entirely. Railway terminates TLS and adds exactly one hop; set this to the real
# number of trusted proxies if the topology changes, or 0 to ignore the header.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


def _client_ip(request: Request) -> str:
    """The client address, taken only from hops we actually trust.

    Counts ``TRUSTED_PROXY_HOPS`` entries in from the RIGHT of X-Forwarded-For.
    Anything further left is client-supplied and is never used. With no header (or
    a shorter one than the configured hop count) this falls back to the peer
    address, which cannot be spoofed.
    """
    peer = request.client.host if request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return peer
    forwarded = request.headers.get("x-forwarded-for") or ""
    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if len(chain) < TRUSTED_PROXY_HOPS:
        # Fewer hops than configured: the request did not traverse the expected
        # proxy chain, so no entry in it is trustworthy.
        return peer
    return chain[-TRUSTED_PROXY_HOPS]


def _enforce_auth_rate_limit(request: Request, scope: str) -> None:
    """Per-IP limit on credential endpoints — blocks brute force and mass signup."""
    if not _rate_limiter.allow(f"{scope}:{_client_ip(request)}", AUTH_RATE_LIMIT_PER_MINUTE, 60.0):
        raise HTTPException(status_code=429, detail="Too many attempts — try again in a minute")


def _enforce_llm_quota(user: WebUser) -> None:
    """Per-user pacing + daily cap, and a deployment-wide daily ceiling.

    A per-user cap alone does not bound spend: registration is open and
    unverified, so N accounts buy N times the quota. The global bucket is the
    actual budget guard-rail — it turns "unbounded paid LLM spend" into a number
    someone chose (LLM_GLOBAL_DAILY_LIMIT), and it is enforced before the
    per-user checks so a burst of fresh accounts cannot walk past it.
    """
    if not _rate_limiter.allow("llm-day:__global__", LLM_GLOBAL_DAILY_LIMIT, 86400.0):
        logger.warning("global daily LLM cap (%d) reached — refusing paid analysis requests",
                       LLM_GLOBAL_DAILY_LIMIT)
        raise HTTPException(
            status_code=429,
            detail="The service reached its daily analysis capacity — please try again tomorrow",
        )
    if not _rate_limiter.allow(f"llm-min:{user.id}", LLM_RATE_LIMIT_PER_MINUTE, 60.0):
        raise HTTPException(status_code=429, detail="Too many analysis requests — try again in a minute")
    if not _rate_limiter.allow(f"llm-day:{user.id}", LLM_DAILY_LIMIT, 86400.0):
        raise HTTPException(status_code=429, detail="Daily analysis limit reached — try again tomorrow")


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
            {
                "company_name": name,
                "ticker": ticker,
                "sector": COMPANY_SECTORS.get(ticker, "other"),
                "logo": resolve_logo(ticker, COMPANY_LOGOS) or "",
            }
            for name, ticker in COMPANY_CATALOG.items()
        ],
    }


@app.get("/api/periods")
async def api_periods(company: str) -> dict[str, Any]:
    """Return the available annual years and quarterly periods for a specific company.

    Each company on openinfo.uz publishes its own reports independently. This endpoint
    fetches the actual published records so the frontend shows only periods that exist,
    not a static global list.
    """
    if not company or not company.strip():
        raise HTTPException(status_code=400, detail="company is required")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, partial(get_company_periods, company.strip()))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenInfo request failed: {exc}") from exc
    except Exception as exc:
        logger.exception("Periods fetch failed for %s", company)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _json_safe(result)


def _listing_to_stock(lst: dict[str, Any]) -> dict[str, Any]:
    """Shape a stored RFB listing as a market-feed stock record, tagged inactive.

    Used to surface issuers that are listed on openinfo but absent from the live
    uzse-stock feed (no recent trades). Price falls back to the registry reference
    when no trade history exists.
    """
    price = lst.get("last_price")
    if price is None:
        price = lst.get("reference_price")
    return {
        "isin": lst.get("isin"),
        "ticker": lst.get("ticker"),
        "name": lst.get("name"),
        "type": "stock",
        "share_type": lst.get("share_type") or "ordinary",
        "close_price": price,
        "close_date": lst.get("last_trade_date"),
        "last_price": price,
        "last_trade_date": lst.get("last_trade_date"),
        "open": lst.get("open_price"),
        "high": lst.get("high_price"),
        "low": lst.get("low_price"),
        "volume": lst.get("volume"),
        "quantity": None,
        "trade_count": None,
        "security_type_text": None,
        "shares_outstanding": lst.get("shares_outstanding"),
        "market_cap": lst.get("market_cap"),
        "inactive": True,
    }


def _apply_quote(row: dict[str, Any], quote: dict[str, Any]) -> None:
    """Overlay the exchange's session quote on a board row, in place.

    The row's own session decides: a quote is applied only when it is at least as
    recent as what the row already shows, so a stored quote for a security that
    has since gone quiet cannot pull a live row backwards. ``close_date`` counts
    as the row's session even with no trade — the exchange carries the closing
    price forward, and that carried price is newer than an older real trade.
    """
    day = _iso_trade_date(quote.get("trade_date"))
    close = quote.get("close_price")
    if not day or close is None:
        return
    row_day = _iso_trade_date(row.get("last_trade_date")) or _iso_trade_date(row.get("close_date"))
    if row_day and row_day > day:
        return

    row["last_price"] = close
    row["last_trade_date"] = day
    if quote.get("prev_close") is not None:
        row["close_price"] = quote["prev_close"]
        row["close_date"] = _iso_trade_date(quote.get("prev_close_date")) or row.get("close_date")
    for src, dst in (("open_price", "open"), ("high_price", "high"), ("low_price", "low")):
        if quote.get(src) is not None:
            row[dst] = quote[src]
    if quote.get("turnover") is not None:
        row["volume"] = quote["turnover"]
    if quote.get("quantity") is not None:
        row["quantity"] = quote["quantity"]
    if quote.get("shares_outstanding"):
        row["shares_outstanding"] = quote["shares_outstanding"]
    shares = row.get("shares_outstanding")
    if shares and close:
        row["market_cap"] = shares * close
    # It traded — the registry's "no recent trades" tag describes an older world.
    row["inactive"] = None


def _quote_to_stock(quote: dict[str, Any]) -> dict[str, Any]:
    """Shape an exchange quote as a market-feed row for a security no feed carries."""
    isin = str(quote.get("isin") or "").upper()
    is_bond = str(quote.get("market") or "").upper() == "BND"
    close, shares = quote.get("close_price"), quote.get("shares_outstanding")
    return {
        "isin": isin,
        "ticker": quote.get("ticker"),
        "name": quote.get("name"),
        "type": "bond" if is_bond else "stock",
        "share_type": quote.get("share_type") or "ordinary",
        "close_price": quote.get("prev_close"),
        "close_date": _iso_trade_date(quote.get("prev_close_date")),
        "last_price": close,
        "last_trade_date": _iso_trade_date(quote.get("trade_date")),
        "open": quote.get("open_price"),
        "high": quote.get("high_price"),
        "low": quote.get("low_price"),
        "volume": quote.get("turnover"),
        "quantity": quote.get("quantity"),
        "trade_count": None,
        "security_type_text": None,
        "shares_outstanding": shares,
        "market_cap": (shares * close) if (shares and close) else quote.get("market_cap"),
        "url": f"https://uzse.uz/isu_infos/{'BND' if is_bond else 'STK'}?isu_cd={isin}",
    }


async def _build_board(security_type: str = "") -> dict[str, Any]:
    """The market board: the live feed, the listing registry and the exchange's
    own quotes merged into one set of rows.

    Extracted from the endpoint so every consumer sees the SAME board. /api/coverage
    used to report on the raw mirror instead, which made it structurally blind to the
    securities the mirror does not carry — the gap it exists to surface.
    """

    try:
        # Executor-wrapped: a sync HTTP call here stalled the whole event loop
        # (single worker) for up to 20s on the hottest endpoint.
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, partial(
            requests.get,
            f"{UZSE_STOCK_API_BASE}/stocks",
            params={"type": security_type} if security_type else None,
            timeout=20,
        ))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.exception("UZSE stock API request failed")
        raise HTTPException(status_code=502, detail="Could not load stock prices") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Stock price API returned invalid JSON") from exc

    stocks = payload.get("stocks") if isinstance(payload, dict) else []
    stocks_list = stocks if isinstance(stocks, list) else []

    # Background sync into securities DB (fire-and-forget). Copy the list so the
    # inactive-listing merge below cannot leak synthetic rows into the executor.
    if stocks_list:
        logos = _load_logos()
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, partial(sync_securities, list(stocks_list), logos))
        # Track the record (largest) daily turnover per stock over time.
        loop.run_in_executor(None, partial(record_volume, list(stocks_list)))

    # Merge in listed-but-inactive issuers (openinfo RFB registry, pushed by the
    # collector) that the live feed omits, so they still show on the market board —
    # tagged inactive with their last-known trade. The registry mixes an issuer's
    # bonds in with its shares (openinfo has no security-kind field there), so route
    # each row by the securities catalog: bond tickers go to the bond view tagged
    # type=bond, everything else to the stock view — never bonds labeled as shares.
    merged = list(stocks_list)
    added_inactive = 0
    feed_tickers = {str(s.get("ticker") or "").upper() for s in stocks_list}
    feed_isins = {str(s.get("isin") or "").upper() for s in stocks_list if s.get("isin")}
    try:
        listings = get_all_listings()
    except Exception:
        logger.exception("market/stocks: listings merge read failed")
        listings = {}
    catalog: dict[str, dict] = {}
    if listings:
        try:
            catalog = get_securities_map()
        except Exception:
            logger.exception("market/stocks: securities catalog read failed")

    # The live uzse feed carries no market cap, so the mktCap/P/E/P/B columns sat
    # empty for every actively traded stock while the RFB registry (pushed by the
    # collector) already knows each line's shares outstanding. Join it onto live
    # rows and value the shares at the live price — the registry's own market_cap
    # (struck at the last collector run's price) is only a staleness fallback.
    listings_by_isin = {
        str(lst.get("isin") or "").upper(): lst
        for lst in listings.values() if lst.get("isin")
    }
    for row in merged:
        if row.get("market_cap"):
            continue
        lst = (listings.get(str(row.get("ticker") or "").upper())
               or listings_by_isin.get(str(row.get("isin") or "").upper()))
        if not lst:
            continue
        shares = lst.get("shares_outstanding")
        if row.get("shares_outstanding") is None and shares is not None:
            row["shares_outstanding"] = shares
        price = row.get("last_price") or row.get("close_price")
        if shares and price:
            row["market_cap"] = shares * price
        elif lst.get("market_cap"):
            row["market_cap"] = lst.get("market_cap")

    want_bonds = security_type == "bond"
    for tk, lst in listings.items():
        if tk in feed_tickers:
            continue
        isin = str(lst.get("isin") or "").upper()
        if isin and isin in feed_isins:
            continue
        sec = catalog.get(str(tk or "").upper()) or {}
        is_bond = sec.get("type") == "bond"
        if is_bond != want_bonds:
            continue
        row = _listing_to_stock(lst)
        if is_bond:
            row["type"] = "bond"
            # Registry fallback rows (issuer with empty info_rfb isin_codes) have
            # no ISIN of their own — take the bond's ISIN from the catalog.
            if not row.get("isin"):
                row["isin"] = sec.get("isin")
        # Registry rows carry no exchange link — build it from the ISIN so the
        # source column links to uzse.uz like live-feed rows do.
        if not row.get("url") and row.get("isin"):
            kind = "BND" if is_bond else "STK"
            row["url"] = f"https://uzse.uz/isu_infos/{kind}?isu_cd={row['isin']}"
        merged.append(row)
        added_inactive += 1

    # Lay the exchange's own session quotes over the board. This is what makes a
    # row say what the exchange says: the close it published, and the previous
    # close it measured the day's move against — which it CARRIES FORWARD through
    # sessions with no trades, so neither the execution feed nor the openinfo
    # registry can reproduce it. It also completes the board: the /stocks mirror
    # is a fixed 78-security universe, and the securities outside it were either
    # missing (KFSKP, EQQU) or priced from a week-old registry row (UQEQ shown at
    # 32 000 from 24.07 while the exchange closed it at 30 720, +20%).
    try:
        quotes = get_all_quotes()
    except Exception:
        logger.exception("market/stocks: quote cache read failed")
        quotes = {}
    quoted_added = 0
    if quotes:
        for row in merged:
            quote = quotes.get(str(row.get("isin") or "").upper())
            if quote:
                _apply_quote(row, quote)
        on_board = {str(r.get("isin") or "").upper() for r in merged if r.get("isin")}
        board_tickers = {str(r.get("ticker") or "").upper() for r in merged}
        for isin, quote in quotes.items():
            if isin in on_board or str(quote.get("ticker") or "").upper() in board_tickers:
                continue
            if (str(quote.get("market") or "").upper() == "BND") != want_bonds:
                continue
            merged.append(_quote_to_stock(quote))
            quoted_added += 1
        # A security the /stocks feed never carried is absent from the securities
        # catalog too, so its board row had no name, logo, sector or company page.
        # Having traded is the qualification: every row the exchange quoted gets
        # catalogued, whether it reached the board from a feed, the registry or
        # the quote itself.
        quoted_rows = [r for r in merged if str(r.get("isin") or "").upper() in quotes]
        if quoted_rows:
            loop.run_in_executor(None, partial(sync_securities, quoted_rows, _load_logos()))

    # Drop board-suppressed tickers (dormant registry lines) from the view. Applied
    # to the fully merged list so it holds regardless of source (live feed or the
    # inactive registry merge above); data itself is left untouched.
    if BOARD_DENYLIST:
        merged = [r for r in merged
                  if str(r.get("ticker") or "").upper() not in BOARD_DENYLIST]
        added_inactive = sum(1 for r in merged if r.get("inactive"))

    return _json_safe({
        "ok": True,
        "source": "uzse-stock-production",
        "source_url": f"{UZSE_STOCK_API_BASE}/stocks",
        # The mirror stamps naive UTC; say so, or the browser reads it as local.
        "updated_at": _as_utc_iso(payload.get("updated_at")) if isinstance(payload, dict) else None,
        "count": len(merged),
        "inactive_listings": added_inactive,
        "type": security_type or "all",
        "stocks": merged,
    })


@app.get("/api/market/stocks")
async def api_market_stocks(type: str | None = None) -> dict[str, Any]:
    security_type = (type or "").strip().lower()
    if security_type and security_type not in {"stock", "bond"}:
        raise HTTPException(status_code=400, detail="type must be stock or bond")
    return await _build_board(security_type)


@app.get("/api/market/audit")
async def api_market_audit() -> dict[str, Any]:
    """Does the board agree with the exchange? Answered from stored data.

    The board's mismatches with the exchange's own bulletin were always found by a
    human comparing the two by eye, because nothing in the pipeline ever asserted
    that the securities we serve are the securities that traded, or that the
    numbers on a row come from the same session. This is that assertion, exposed
    so it can be asked at any time rather than discovered.
    """
    loop = asyncio.get_running_loop()
    try:
        stats, quotes = await asyncio.gather(
            loop.run_in_executor(None, get_all_trade_stats),
            loop.run_in_executor(None, get_all_quotes),
        )
        shares, bonds = await asyncio.gather(_build_board("stock"), _build_board("bond"))
    except Exception as exc:
        logger.exception("market audit failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    return _json_safe(audit_session(stats, quotes, board, denylist=BOARD_DENYLIST))


@app.get("/api/market/trades")
async def api_market_trades() -> dict[str, Any]:
    """The latest session's totals: turnover, securities changing hands, trades.

    Summed from our own per-trade statistics — every execution the exchange
    published for that session. The ``/trades`` mirror this used to read is a
    44-row snapshot of a fixed universe, and it reported 120,7 млн over ~900
    trades for 31.07 while the session the exchange published was 1,56 млрд over
    6 507. It stays as the fallback for a deployment that holds no statistics yet.
    """
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, get_all_trade_stats)
    except Exception:
        logger.exception("market/trades: trade-stats read failed")
        stats = {}
    day = max((str(s.get("trade_date") or "") for s in stats.values()), default="")
    session = [s for s in stats.values() if day and str(s.get("trade_date") or "") == day]
    if session:
        stamps = [s.get("updated_at") for s in session if s.get("updated_at")]
        return _json_safe({
            "ok": True,
            "source": "uzse-trade-results",
            "trade_date": day,
            "updated_at": _as_utc_iso(max(stamps)) if stamps else None,
            "securities": len(session),
            "total_volume": sum((s.get("total_value") or 0) for s in session),
            "total_quantity": sum((s.get("total_qty") or 0) for s in session),
            "total_trade_count": sum((s.get("trade_count") or 0) for s in session),
        })

    try:
        response = await loop.run_in_executor(
            None, partial(requests.get, f"{UZSE_STOCK_API_BASE}/trades", timeout=20))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.exception("UZSE trades API request failed")
        raise HTTPException(status_code=502, detail="Could not load trade data") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Trades API returned invalid JSON") from exc

    trades = payload.get("trades", []) if isinstance(payload, dict) else []
    if not isinstance(trades, list):
        trades = []
    total_volume = sum((t.get("volume") or 0) for t in trades)
    total_quantity = sum((t.get("quantity") or 0) for t in trades)
    total_trade_count = sum((t.get("trade_count") or 0) for t in trades)
    return _json_safe({
        "ok": True,
        # The mirror stamps naive UTC; say so, or the browser reads it as local.
        "updated_at": _as_utc_iso(payload.get("updated_at")) if isinstance(payload, dict) else None,
        "total_volume": total_volume,
        "total_quantity": total_quantity,
        "total_trade_count": total_trade_count,
    })


@app.get("/api/market/financials")
async def api_market_financials() -> dict[str, Any]:
    """Return cached NSBU headline indicators per ticker: {ticker: {...}}.

    Reads the pre-computed cache instantly and kicks a fire-and-forget background
    refresh so the cache fills/refreshes progressively as the market is browsed.
    """
    loop = asyncio.get_running_loop()
    try:
        financials = await loop.run_in_executor(None, get_all_financials)
    except Exception as exc:
        logger.exception("financials cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Progressive background fill (non-blocking; self-throttled and lock-guarded).
    loop.run_in_executor(None, refresh_financials_cache)
    # Stored NSBU sums are thousands of UZS; serve full UZS so the client can
    # relate them to market caps/prices without unit knowledge. The `annual`
    # companion carries the same money fields and must be scaled with the row —
    # a 12-month denominator left in thousands would understate P/E ~1000x for
    # exactly the issuers the companion exists to make comparable.
    def _scaled(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            **{k: row[k] * NSBU_THOUSANDS_UZS
               for k in FIN_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }

    financials = {
        ticker: ({**_scaled(row), "annual": _scaled(row["annual"])} if row.get("annual")
                 else _scaled(row))
        for ticker, row in financials.items()
    }
    return _json_safe({
        "ok": True,
        "count": len(financials),
        "financials": financials,
    })


@app.get("/api/market/ratios")
async def api_market_ratios() -> dict[str, Any]:
    """Per-ticker financial ratios & equity (openinfo financial_indicators),
    keyed by ticker. Feeds the market-wide multiplier columns (P/E, P/B) and
    ratio coefficients of the §3.8 tabular reports."""
    loop = asyncio.get_running_loop()
    try:
        ratios = await loop.run_in_executor(None, get_all_ratios)
    except Exception as exc:
        logger.exception("ratios cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # Absolute sums (equity/assets) are stored in thousands of UZS; serve full
    # UZS so P/B = market_cap / total_equity divides like units.
    ratios = {
        ticker: {
            **row,
            **{k: row[k] * NSBU_THOUSANDS_UZS
               for k in RATIO_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }
        for ticker, row in ratios.items()
    }
    return _json_safe({"ok": True, "count": len(ratios), "ratios": ratios})


# ---------------------------------------------------------------------------
# ТЗ v1.2 §7–§9, §4, §10.9 — one calc layer, one universe, cached by content.
# ---------------------------------------------------------------------------

def _etag_json(request: Request, payload: dict[str, Any], max_age: int) -> Response:
    """Serve a payload with a content ETag (ТЗ §10.9).

    The cache key is the data, not the clock: while the numbers have not changed
    the same response is valid however old it is. Before this, static bundles
    carried no cache header at all and the browser refetched an immutable file on
    every load.
    """
    body = _json_safe(payload)
    etag = '"%s"' % hashlib.sha256(
        json.dumps(body, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:32]
    headers = {"ETag": etag, "Cache-Control": f"public, max-age={max_age}"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)


def _earnings_for(fin: dict[str, Any] | None) -> dict[str, Any]:
    """The 12-month profit a multiple divides by, and the period it covers.

    NSBU quarterlies accumulate from 1 January, so an issuer's latest filing is
    3, 6 or 9 months of profit depending only on when it filed. Prefer the last
    complete fiscal year the collector stores alongside it, so P/E means the same
    thing in every row (ТЗ §7).
    """
    if not fin:
        return {"net_income": None, "period": None, "months": None}
    annual = fin.get("annual")
    if annual and annual.get("net_income") is not None:
        return {"net_income": annual["net_income"],
                "period": fundamentals.period_label(annual), "months": 12}
    return {"net_income": fin.get("net_income"),
            "period": fundamentals.period_label(fin),
            "months": fundamentals.period_months(fin)}


async def _market_inputs() -> dict[str, Any]:
    """Board, catalog, statements and ratios — fetched once, shared by every
    screen below so they cannot disagree about what exists."""
    loop = asyncio.get_running_loop()
    shares, bonds = await asyncio.gather(_build_board("stock"), _build_board("bond"))
    securities, financials, ratios, listings, stats = await asyncio.gather(
        loop.run_in_executor(None, get_securities_map),
        loop.run_in_executor(None, get_all_financials),
        loop.run_in_executor(None, get_all_ratios),
        loop.run_in_executor(None, get_all_listings),
        loop.run_in_executor(None, get_all_trade_stats),
    )
    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    # Statement sums are stored in thousands of UZS; scale at the boundary so
    # every division below is like-for-like against a full-UZS market cap.
    def _scale(row: dict[str, Any], fields) -> dict[str, Any]:
        return {**row, **{k: row[k] * NSBU_THOUSANDS_UZS
                          for k in fields if isinstance(row.get(k), (int, float))}}

    financials = {
        t: ({**_scale(r, FIN_MONEY_FIELDS), "annual": _scale(r["annual"], FIN_MONEY_FIELDS)}
            if r.get("annual") else _scale(r, FIN_MONEY_FIELDS))
        for t, r in (financials or {}).items()
    }
    ratios = {t: _scale(r, RATIO_MONEY_FIELDS) for t, r in (ratios or {}).items()}
    # The session the board describes: the latest day any row reports. The feed
    # writes DD.MM.YYYY and the day statistics YYYYMMDD, so compare normalised
    # values — ordering the raw strings put "31.01" above "05.02".
    trade_date = None
    for row in board:
        day = instruments._norm_day(row.get("last_trade_date"))
        if day and (trade_date is None or day > trade_date):
            trade_date = day
    return {"board": board, "securities": securities, "financials": financials,
            "ratios": ratios, "listings": listings, "stats": stats,
            "trade_date": trade_date.isoformat() if trade_date else None}


def _multiples_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    """Issuer-level multiples for every listed share class (ТЗ §8)."""
    securities, financials, ratios = (inputs["securities"], inputs["financials"],
                                      inputs["ratios"])
    board_by_ticker = {str(r.get("ticker") or "").upper(): r for r in inputs["board"]}

    # Share classes are grouped by issuer using the catalog, enriched with the
    # board's capitalisation and share count for each class.
    catalog_rows = []
    for ticker, meta in (securities or {}).items():
        row = board_by_ticker.get(str(ticker).upper()) or {}
        catalog_rows.append({
            "ticker": str(ticker).upper(), **meta,
            "market_cap": row.get("market_cap"),
            "shares_outstanding": row.get("shares_outstanding") or meta.get("shares_outstanding"),
        })
    groups = fundamentals.group_by_issuer(catalog_rows)

    rows: list[dict[str, Any]] = []
    by_issuer: dict[str, Any] = {}
    for key, classes in groups.items():
        tickers = [c["ticker"] for c in classes]
        # The issuer's statement is whichever class carries one — they describe
        # the same legal entity, so a preferred-only filing still applies.
        fin = next((financials.get(t) for t in tickers if financials.get(t)), None)
        rat = next((ratios.get(t) for t in tickers if ratios.get(t)), None)
        multiples = fundamentals.issuer_multiples(classes, fin, rat, _earnings_for(fin))
        by_issuer[key] = {"tickers": tickers, "multiples": multiples}
        for cls in classes:
            rows.append({
                "ticker": cls["ticker"],
                "issuer": key,
                "issuer_classes": tickers,
                "share_class": "preferred" if cls.get("is_preferred") else "ordinary",
                # Class-specific, by design (ТЗ §8).
                "market_cap_class": cls.get("market_cap"),
                # Issuer-level, identical across the classes above.
                **{k: v for k, v in multiples.items()},
            })
    rows.sort(key=lambda r: r["ticker"])
    _apply_audit_blocks(rows)
    return {"ok": True, "count": len(rows), "issuers": len(groups),
            "items": rows, "by_issuer": by_issuer}


def _apply_audit_blocks(rows: list[dict[str, Any]]) -> int:
    """Withhold every metric an open BLOCKING finding covers (ТЗ v1.3 §12.2).

    This is the line between a report and a control. The auditor is allowed to
    take a number off the screen: the cell becomes a dash carrying the rule that
    withheld it. Without this the module would only describe problems it had no
    power to stop, and a wrong figure would keep being published next to a
    perfectly accurate description of why it is wrong.

    An audit outage must never blank the board, so a failure here leaves the
    data untouched.
    """
    try:
        from audit import blocking_index

        index = blocking_index()
    except Exception:  # noqa: BLE001
        logger.exception("audit blocking index unavailable; publishing unfiltered")
        return 0
    if not index:
        return 0
    blocked = 0
    for row in rows:
        metrics = index.get(str(row.get("ticker") or "").upper())
        if not metrics:
            continue
        for metric in metrics:
            current = row.get(metric)
            if isinstance(current, dict) and current.get("value") is not None:
                row[metric] = {"value": None, "status": "audit_blocked",
                               "note": "значение снято аудитором данных",
                               "audit_metric": metric}
                blocked += 1
    return blocked


@app.get("/api/market/multiples")
async def api_market_multiples(request: Request) -> Response:
    """P/E, P/B, ROE, ROA, margin and D/E — computed once, per ISSUER.

    Both classes of an issuer receive identical values by construction; only
    price, change, volume and the class's own capitalisation differ. This is the
    endpoint that makes KFSK 203.6 / KFSKP 0.19 impossible.
    """
    trace = obs.Trace(endpoint="market/multiples")
    try:
        inputs = await _market_inputs()
        trace.step("inputs", instruments=len(inputs["board"]),
                   financials=len(inputs["financials"]), ratios=len(inputs["ratios"]))
        # ТЗ §10.9: keyed by the session the data describes, not by a clock.
        # While that has not moved the answer cannot have changed, so the entry
        # stays valid however old it is — and a new session simply misses.
        cache_key = cache_layer.key("market:multiples", inputs["trade_date"] or "none",
                                    len(inputs["board"]), len(inputs["financials"]))
        payload = cache_layer.cached(cache_key, lambda: _multiples_payload(inputs))
        suppressed = sum(1 for r in payload["items"]
                         if not (r.get("validation") or {}).get("valid", True))
        trace.step("multiples", issuers=payload["issuers"], suppressed=suppressed)
        payload["trace_id"] = trace.trace_id
        return _etag_json(request, payload, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        trace.reject("multiples", reason=str(exc))
        logger.exception("market multiples failed")
        raise HTTPException(status_code=502, detail="multiples unavailable") from exc
    finally:
        trace.close()


@app.get("/api/market/summary")
async def api_market_summary(request: Request) -> Response:
    """The headline cards: capitalisation with its exclusions, and the counters."""
    try:
        inputs = await _market_inputs()
        cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
        board = inputs["board"]
        traded = [r for r in board if (formulas.to_number(r.get("trade_count")) or 0) > 0
                  or (formulas.to_number(r.get("volume")) or 0) > 0]
        up = down = flat = 0
        for row in traded:
            change = heatmap.day_change(formulas.to_number(row.get("last_price")),
                                        formulas.to_number(row.get("close_price")))
            if change is None:
                continue
            if change > 0.05:
                up += 1
            elif change < -0.05:
                down += 1
            else:
                flat += 1
        return _etag_json(request, {
            "ok": True,
            "instruments": len(board),
            "traded_today": len(traded),
            "up": up, "down": down, "flat": flat,
            "market_cap": cap,
            "turnover_today": sum((formulas.to_number(r.get("volume")) or 0) for r in traded),
            "trades_today": sum((formulas.to_number(r.get("trade_count")) or 0) for r in traded),
            "trade_date": inputs["trade_date"],
        }, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("market summary failed")
        raise HTTPException(status_code=502, detail="summary unavailable") from exc


@app.get("/api/heatmap")
async def api_heatmap(request: Request) -> Response:
    """The market map: tiles, sectors and metadata in ONE response (ТЗ §9)."""
    trace = obs.Trace(endpoint="heatmap")
    try:
        inputs = await _market_inputs()
        payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
        trace.step("tiles", **payload["counts"])
        payload["ok"] = True
        payload["trace_id"] = trace.trace_id
        return _etag_json(request, payload, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        trace.reject("heatmap", reason=str(exc))
        logger.exception("heatmap failed")
        raise HTTPException(status_code=502, detail="heatmap unavailable") from exc
    finally:
        trace.close()


@app.get("/api/instruments")
async def api_instruments(request: Request, include_inactive: bool = True) -> Response:
    """The single instrument universe (ТЗ §4).

    Inactive listings are returned by default and flagged, never dropped: a
    security that stopped trading is a fact about the market, and hiding it is
    how five references came to hold five different counts.
    """
    try:
        inputs = await _market_inputs()
        catalog = instruments.build_catalog(
            securities=inputs["securities"], board=inputs["board"],
            listings=inputs["listings"], financials=inputs["financials"],
            ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
        if not include_inactive:
            catalog = {**catalog,
                       "items": [i for i in catalog["items"] if i["is_active"]]}
        catalog["ok"] = True
        return _etag_json(request, catalog, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("instruments failed")
        raise HTTPException(status_code=502, detail="catalog unavailable") from exc


@app.get("/api/bonds")
async def api_bonds(request: Request) -> Response:
    """The bond contour (Дополнение 1 §А.6).

    Eleven issues trade genuinely and appear nowhere in the interface. They get
    their own section with the metrics that CAN be computed honestly from what
    the source publishes, and an explicit `no_bond_reference` for everything
    that needs a nominal, a coupon and a maturity — none of which any endpoint
    carries yet.
    """
    try:
        inputs = await _market_inputs()
        references, coupons = provenance.bond_references(), provenance.bond_coupons()
        payload = bonds.build_bond_board(inputs["board"], inputs["securities"],
                                         references, coupons)
        payload["ok"] = True
        payload["trade_date"] = inputs["trade_date"]
        return _etag_json(request, payload, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("bonds failed")
        raise HTTPException(status_code=502, detail="bonds unavailable") from exc


@app.get("/api/bonds/{ticker}")
async def api_bond_detail(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()
    inputs = await _market_inputs()
    references, coupons = provenance.bond_references(), provenance.bond_coupons()
    payload = bonds.build_bond_board(inputs["board"], inputs["securities"], references, coupons)
    row = next((r for r in payload["items"] if r["ticker"] == ticker), None)
    if not row:
        raise HTTPException(status_code=404, detail="bond not found")
    return _json_safe({"ok": True, **row, "coupons": coupons.get(ticker, [])})


@app.get("/api/bonds/{ticker}/coupons")
async def api_bond_coupons(ticker: str) -> dict[str, Any]:
    rows = provenance.bond_coupons().get(ticker.upper(), [])
    return _json_safe({"ok": True, "ticker": ticker.upper(), "count": len(rows), "items": rows})


@app.post("/api/admin/bonds/reference")
async def api_admin_bond_reference(payload: dict[str, Any],
                                   _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Load the issue reference — the second half of the contour (§А.4).

    `is_complete` is the master switch: while the nominal, coupon rate and
    maturity are missing every yield metric stays a dash, and the moment they
    arrive the metrics turn on with no code change.
    """
    written = provenance.upsert_bond_reference(payload.get("rows") or [])
    return {"ok": True, "upserted": written}


@app.get("/api/catalog/reports/summary")
async def api_catalog_reports_summary(request: Request) -> Response:
    """Counters AND the issuer list from ONE query (Дополнение 1 §Б.5).

    The header said 85 companies and the list returned 73 because they were two
    queries nobody compared. Reading both from the same statement makes them
    unable to disagree, and the catalog's own age is a stated fact rather than a
    date the reader has to subtract from today.
    """
    payload = provenance.summary()
    payload["ok"] = True
    return _etag_json(request, payload, max_age=120)


@app.get("/api/catalog/reports/{report_id}")
async def api_catalog_report(report_id: int) -> dict[str, Any]:
    """One report: its parse state, the figures taken from it, and why it was
    rejected if it was. `used_by` answers the reverse question — is this report
    behind a number we publish?"""
    row = provenance.report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return _json_safe({"ok": True, **row})


@app.get("/api/catalog/reports/queue")
async def api_catalog_queue(limit: int = 200,
                            _: None = Depends(_require_admin)) -> dict[str, Any]:
    """What has not been parsed — a work queue, not a shelf of links."""
    rows = provenance.queue(max(1, min(limit, 1000)))
    return _json_safe({"ok": True, "count": len(rows), "items": rows})


@app.get("/ready")
async def api_ready() -> Response:
    """Readiness, not liveness (ТЗ §10.4.1/§10.4.6).

    503 while the database is behind the code: serving from a shape the code
    does not expect is not an honest 200. /health stays a liveness probe.
    """
    from reports_catalog import get_catalog_conn

    conn = get_catalog_conn()
    try:
        schema = migrations.status(conn)
    finally:
        conn.close()
    payload = {"ok": schema["ready"], "schema": schema, "cache": cache_layer.backend()}
    return JSONResponse(payload, status_code=200 if schema["ready"] else 503)


@app.post("/api/admin/migrate")
async def api_admin_migrate(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """Apply pending migrations. Additive only, ordered, recorded, idempotent."""
    from reports_catalog import get_catalog_conn

    loop = asyncio.get_running_loop()

    def _run() -> dict[str, Any]:
        conn = get_catalog_conn()
        try:
            return migrations.upgrade(conn)
        finally:
            conn.close()

    return _json_safe(await loop.run_in_executor(None, _run))


@app.get("/api/config")
async def api_config(request: Request) -> Response:
    """Thresholds and feature flags the interface is allowed to know about.

    ТЗ §10.10: thresholds are configuration in the repository, not constants in
    code — and the screen reads the same ones the calc layer applied, so a label
    can never claim a window the server did not use.
    """
    return _etag_json(request, {
        "ok": True,
        "thresholds": formulas.thresholds(),
        "flags": FEATURE_FLAGS,
    }, max_age=300)


async def _audit_context(with_history: int = 0):
    """Assemble everything the auditor looks at (ТЗ v1.3 §12).

    Raw sources AND what the API currently publishes — the auditor's whole
    method is to recompute the first and compare against the second.
    """
    from audit.checks import AuditContext

    inputs = await _market_inputs()
    multiples = _multiples_payload(inputs)
    map_payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
    catalog = instruments.build_catalog(
        securities=inputs["securities"], board=inputs["board"], listings=inputs["listings"],
        financials=inputs["financials"], ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
    cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
    board = inputs["board"]
    traded = [r for r in board if (formulas.to_number(r.get("trade_count")) or 0) > 0
              or (formulas.to_number(r.get("volume")) or 0) > 0]
    up = down = flat = 0
    for row in traded:
        change = heatmap.day_change(formulas.to_number(row.get("last_price")),
                                    formulas.to_number(row.get("close_price")))
        if change is None:
            continue
        up += change > 0.05
        down += change < -0.05
        flat += -0.05 <= change <= 0.05
    summary = {"instruments": len(board), "traded_today": len(traded), "up": up, "down": down,
               "flat": flat, "market_cap": cap,
               "turnover_today": sum((formulas.to_number(r.get("volume")) or 0) for r in traded),
               "trades_today": sum((formulas.to_number(r.get("trade_count")) or 0) for r in traded)}

    # XSC-03 needs the same security's absolute block under every period button.
    # History is expensive, so it is sampled unless explicitly asked for.
    history: dict[str, list] = {}
    metrics_by_period: dict[str, dict[int, Any]] = {}
    if with_history:
        active = [i for i in catalog["items"] if i["is_active"] and i["isin"]][:int(with_history)]
        for item in active:
            try:
                data = await _full_history(item["isin"])
            except Exception:  # noqa: BLE001 — one unreachable series is a finding, not a crash
                continue
            points = data.get("points") or []
            history[item["ticker"]] = points
            metrics_by_period[item["ticker"]] = {
                months: formulas.company_metrics(points, months=months)["absolute"]
                for months in (1, 3, 6, 12, 36, 60)
            }

    references, coupons = provenance.bond_references(), provenance.bond_coupons()
    bond_board = bonds.build_bond_board(board, inputs["securities"], references, coupons)
    catalog_reports = provenance.summary()
    source_reports = [provenance.report(r["id"]) or r
                      for r in provenance.queue(200)]

    return AuditContext(
        board=board, securities=inputs["securities"], financials=inputs["financials"],
        ratios=inputs["ratios"], listings=inputs["listings"], stats=inputs["stats"],
        history=history, published_multiples=multiples["items"], published_map=map_payload,
        published_summary=summary, published_catalog=catalog,
        published_metrics_by_period=metrics_by_period,
        published_ma_windows=formulas.company_metrics([], months=12)["ma_windows"],
        published_bonds=bond_board["items"],
        bond_references=references,
        bond_coupons=coupons,
        published_catalog_reports=catalog_reports,
        source_reports=source_reports,
        parse_queue=provenance.queue(1000),
    )


_audit_lock = threading.Lock()
_audit_last_started = 0.0
_AUDIT_MIN_INTERVAL = 120.0


def _schedule_audit(trigger: str) -> bool:
    """Run the auditor after a data load, in the background (ТЗ v1.3 §12.7).

    The check is worth having precisely because data changes without anyone
    looking, so it fires on the load rather than on a person remembering. It
    never blocks the ingest that triggered it and never raises into it: a failed
    audit is a failed audit, not a failed collection.
    """
    global _audit_last_started
    if not FEATURE_FLAGS.get("audit_v1", True):
        return False
    now = time.time()
    with _audit_lock:
        if now - _audit_last_started < _AUDIT_MIN_INTERVAL:
            return False
        _audit_last_started = now

    async def _go() -> None:
        from audit import run_audit
        try:
            ctx = await _audit_context()
            report = run_audit(ctx, trigger=trigger)
            logger.info("audit after %s: %s, blocking=%d", trigger, report["status"],
                        report["summary"]["blocking"])
        except Exception:  # noqa: BLE001 — never propagate into the ingest path
            logger.exception("scheduled audit after %s failed", trigger)

    try:
        asyncio.get_running_loop().create_task(_go())
        return True
    except RuntimeError:
        return False


@app.post("/api/audit/run")
async def api_audit_run(payload: dict[str, Any] | None = None,
                        _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Run the auditor (ТЗ §12.5). Scope: all, one group, one rule, one ticker."""
    from audit import run_audit

    payload = payload or {}
    trace = obs.Trace(endpoint="audit/run")
    try:
        ctx = await _audit_context(with_history=int(payload.get("with_history") or 0))
        trace.step("context", instruments=len(ctx.board),
                   published=len(ctx.published_multiples), history=len(ctx.history))
        report = run_audit(
            ctx, trigger=str(payload.get("trigger") or "manual"),
            codes=payload.get("codes"), group=payload.get("group"),
            ticker=payload.get("ticker"), trace_id=trace.trace_id)
        trace.step("audit", decision=report["status"], **report["summary"])
        return _json_safe(report)
    finally:
        trace.close()


@app.get("/api/audit/runs")
async def api_audit_runs(limit: int = 20, _: None = Depends(_require_admin)) -> dict[str, Any]:
    from audit import list_runs
    return _json_safe({"ok": True, "items": list_runs(max(1, min(limit, 200)))})


@app.get("/api/audit/runs/{run_id}")
async def api_audit_run_detail(run_id: str, _: None = Depends(_require_admin)) -> dict[str, Any]:
    from audit import find_findings, get_run

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return _json_safe({"ok": True, "run": run, "findings": find_findings(run_id=run_id)})


@app.get("/api/audit/findings")
async def api_audit_findings(severity: str | None = None, group: str | None = None,
                             status: str | None = None, ticker: str | None = None,
                             limit: int = 200,
                             _: None = Depends(_require_admin)) -> dict[str, Any]:
    from audit import find_findings
    return _json_safe({"ok": True, "items": find_findings(
        severity=severity, group=group, status=status, ticker=ticker,
        limit=max(1, min(limit, 2000)))})


@app.patch("/api/audit/findings/{finding_id}")
async def api_audit_update_finding(finding_id: int, payload: dict[str, Any],
                                   _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Move a finding to `accepted` (a known exception) or `confirmed`/`fixed`.

    §12.2: no finding disappears silently — a decision about one is recorded on
    it, with its note, rather than expressed by deleting the row.
    """
    from audit import update_finding

    try:
        row = update_finding(finding_id, status=str(payload.get("status")),
                             note=payload.get("note"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="finding not found")
    return _json_safe({"ok": True, "finding": row})


@app.get("/api/audit/rules")
async def api_audit_rules(request: Request) -> Response:
    """The rule book, readable without credentials: what is checked and why."""
    from audit import ALL_RULES, GROUPS
    return _etag_json(request, {
        "ok": True,
        "groups": GROUPS,
        "count": len(ALL_RULES),
        "items": [{"code": r.code, "group": r.group, "title": r.title,
                   "severity": r.severity, "threshold": r.threshold, "note": r.note}
                  for r in ALL_RULES],
    }, max_age=3600)


@app.get("/api/audit/diff")
async def api_audit_diff(from_run: str | None = None, to_run: str | None = None,
                         _: None = Depends(_require_admin)) -> dict[str, Any]:
    """What changed between two runs (ТЗ v1.3 §12.5).

    Without this a regression reads as one more line in a list nobody finishes.
    Findings are matched by fingerprint, so the answer is in three buckets:
    appeared, resolved, still open.
    """
    from audit import find_findings, list_runs
    from audit.store import fingerprint

    runs = list_runs(50)
    if not to_run:
        to_run = runs[0]["id"] if runs else None
    if not from_run:
        from_run = runs[1]["id"] if len(runs) > 1 else None
    if not to_run or not from_run:
        raise HTTPException(status_code=404, detail="not enough runs to compare")

    def keyed(run_id: str) -> dict[str, dict[str, Any]]:
        # Every row the run touched, resolved ones included: a finding that was
        # fixed between the two runs is exactly what the diff is asked about.
        return {fingerprint(f["rule_code"], f["ticker"], f["metric"]): f
                for f in find_findings(run_id=run_id, limit=5000, include_resolved=True)}

    before, after = keyed(from_run), keyed(to_run)
    appeared = [v for k, v in after.items() if k not in before]
    resolved = [v for k, v in before.items() if k not in after]
    return _json_safe({
        "ok": True, "from_run": from_run, "to_run": to_run,
        "appeared": appeared, "resolved": resolved,
        "still_open": [v for k, v in after.items() if k in before],
        "summary": {"appeared": len(appeared), "resolved": len(resolved),
                    "regressions": sum(1 for f in appeared if f["severity"] == "blocking")},
    })


@app.get("/api/audit/export")
async def api_audit_export(run_id: str | None = None,
                           _: None = Depends(_require_admin)) -> Response:
    """The full report as CSV (ТЗ v1.3 §12.5)."""
    import csv
    import io

    from audit import find_findings, latest_run

    if not run_id:
        run = latest_run()
        run_id = (run or {}).get("id")
    rows = find_findings(run_id=run_id, limit=5000) if run_id else []
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["rule_code", "severity", "ticker", "metric", "expected", "actual",
                     "deviation", "status", "seen_count", "first_seen", "last_seen", "message"])
    for row in rows:
        writer.writerow([row.get(k) for k in (
            "rule_code", "severity", "ticker", "metric", "expected", "actual", "deviation",
            "status", "seen_count", "first_seen", "last_seen", "message")])
    # BOM so Excel opens the Cyrillic messages correctly rather than as mojibake.
    body = "﻿" + buffer.getvalue()
    return Response(body, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="audit-{run_id or "empty"}.csv"'})


@app.get("/api/audit/badge/{ticker}")
async def api_audit_badge(ticker: str) -> dict[str, Any]:
    """Can this security's numbers be trusted right now? (ТЗ §12.5/§12.6)

    Public: this is the fact the reader needs. They do not need rule codes.
    """
    from audit import ticker_badge
    return _json_safe({"ok": True, **ticker_badge(ticker)})


@app.get("/api/admin/invariants")
async def api_admin_invariants(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """Daily property check on live data (ТЗ §11.5). Empty is the good outcome."""
    inputs = await _market_inputs()
    payload = _multiples_payload(inputs)
    map_payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
    catalog = instruments.build_catalog(
        securities=inputs["securities"], board=inputs["board"],
        listings=inputs["listings"], financials=inputs["financials"],
        ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
    cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
    report = invariants.run([
        ("multiples_agree", lambda: invariants.check_multiples_agree_across_classes(
            payload["by_issuer"])),
        ("multiples_in_range", lambda: invariants.check_multiples_in_range(payload["items"])),
        ("statements_suppressed", lambda: invariants.check_invalid_statements_are_suppressed(
            payload["items"])),
        ("market_map", lambda: invariants.check_map(map_payload)),
        ("catalog", lambda: invariants.check_catalog(catalog)),
        ("market_cap", lambda: invariants.check_market_cap(cap)),
    ])
    return _json_safe(report)


@app.get("/api/admin/trace/{trace_id}")
async def api_admin_trace(trace_id: str, _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Replay one number's chain of derivation (ТЗ §12)."""
    record = obs.get_trace(trace_id)
    if not record:
        raise HTTPException(status_code=404, detail="trace not found or expired")
    return _json_safe(record)


@app.get("/api/admin/traces")
async def api_admin_traces(limit: int = 50,
                           _: None = Depends(_require_admin)) -> dict[str, Any]:
    return _json_safe({"ok": True, "items": obs.recent_traces(max(1, min(limit, 200)))})


@app.get("/api/coverage")
async def api_coverage() -> dict[str, Any]:
    """Data-coverage report: for every listed security, which datasets are filled.

    Shows price / volume / financials / reports coverage + resolution status and
    any sync error per ticker, plus a per-dataset summary — so gaps are visible
    and actionable instead of silent (ТЗ scalable-pipeline observability).

    Reports on the board we actually serve, not on the raw /stocks mirror: reading
    the mirror made this report blind to every security outside its fixed universe,
    which is to say blind to precisely the gap it exists to surface.
    """
    loop = asyncio.get_running_loop()
    try:
        shares, bonds = await asyncio.gather(_build_board("stock"), _build_board("bond"))
        stocks = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    except Exception as exc:
        logger.exception("coverage: board build failed")
        raise HTTPException(status_code=502, detail="Could not load the securities feed") from exc

    coverage = await loop.run_in_executor(None, get_catalog_coverage)

    items: list[dict[str, Any]] = []
    counts = {"price": 0, "volume": 0, "financials": 0, "reports": 0, "resolved": 0}
    for stock in stocks:
        ticker = str(stock.get("ticker") or "").upper()
        cov = coverage.get(ticker, {})
        has_price = bool(stock.get("last_price") or stock.get("close_price"))
        has_volume = bool(stock.get("volume"))
        has_fin = bool(cov.get("has_financials"))
        has_reports = int(cov.get("reports") or 0) > 0
        resolved = bool(cov.get("org_id"))
        counts["price"] += has_price
        counts["volume"] += has_volume
        counts["financials"] += has_fin
        counts["reports"] += has_reports
        counts["resolved"] += resolved
        items.append({
            "ticker": ticker,
            "name": stock.get("name"),
            "type": stock.get("type"),
            "org_id": cov.get("org_id"),
            "resolved": resolved,
            "has_price": has_price,
            "has_volume": has_volume,
            "has_financials": has_fin,
            "reports": int(cov.get("reports") or 0),
            "sync_error": cov.get("sync_error"),
        })

    total = len(items) or 1
    summary = {
        key: {"filled": val, "total": len(items), "pct": round(val / total * 100)}
        for key, val in counts.items()
    }
    items.sort(key=lambda r: (r["has_financials"], r["resolved"], r["ticker"]))
    # Consistency guard: net_income that disagrees with openinfo's own net_profit.
    try:
        flags = await loop.run_in_executor(None, audit_financials_consistency)
    except Exception:
        logger.exception("financials consistency audit failed")
        flags = []
    # Collector heartbeat: the last completed ingestion run (pushed as a meta
    # fact) — a silently dead collector shows up here as growing data age.
    collector: dict[str, Any] = {"last_run": None, "age_hours": None, "stale": None}
    try:
        meta = await loop.run_in_executor(None, partial(get_facts, "_collector", "meta"))
        fields = {f.get("field"): f.get("value_text") for f in meta}
        last_run = fields.get("last_run")
        status = fields.get("last_run_status")
        from datetime import datetime, timezone

        def _age(stamp: str | None) -> float | None:
            try:
                return (datetime.now(timezone.utc)
                        - datetime.fromisoformat(stamp)).total_seconds() / 3600 if stamp else None
            except ValueError:
                return None

        if last_run:
            age = _age(last_run)
            collector = {"last_run": last_run, "last_run_status": status,
                         "age_hours": round(age, 1) if age is not None else None,
                         "stale": age > 26 if age is not None else None}
        # A whole-run "ok" covers only the steps that run: --reconcile-only stamps
        # the heartbeat while the board's turnover stays frozen. Report each step
        # that stamps itself separately, with the session it last ingested.
        steps: dict[str, Any] = {}
        for field, value in fields.items():
            if not str(field).endswith("_last_run") or field == "last_run":
                continue
            name = str(field)[: -len("_last_run")]
            age = _age(value)
            steps[name] = {
                "last_run": value,
                "last_day": fields.get(f"{name}_last_day") or None,
                "age_hours": round(age, 1) if age is not None else None,
                "stale": age > 26 if age is not None else None,
            }
        if steps:
            collector["steps"] = steps
    except Exception:
        logger.exception("collector heartbeat read failed")
    return _json_safe({
        "ok": True, "total": len(items), "summary": summary,
        "collector": collector,
        "financials_flags": flags, "securities": items,
    })


@app.get("/api/facts/{ticker}")
async def api_facts(ticker: str, dataset: str | None = None) -> dict[str, Any]:
    """Generic fact store for a ticker's issuer (adapter-landed data).

    Resolves the ticker to its issuer org and returns every stored fact, grouped
    by dataset/field. New source adapters surface here automatically.
    """
    ticker = ticker.strip().upper()
    loop = asyncio.get_running_loop()
    index = await loop.run_in_executor(None, partial(get_company_index, ticker))
    org_id = (index or {}).get("org_id")
    if not org_id:
        return {"ok": True, "ticker": ticker, "org_id": None, "facts": []}
    facts = await loop.run_in_executor(None, partial(get_facts, org_id, dataset))
    grouped: dict[str, dict[str, list]] = {}
    for f in facts:
        grouped.setdefault(f["dataset"], {}).setdefault(f["field"], []).append(
            {"period": f["period"], "value": f["value_num"] if f["value_num"] is not None else f["value_text"], "unit": f["unit"], "source": f["source"]}
        )
    return _json_safe({"ok": True, "ticker": ticker, "org_id": org_id, "count": len(facts), "datasets": grouped})


def _as_utc_iso(value: Any) -> str | None:
    """Stamp a naive timestamp as UTC so the browser cannot misread it.

    Both clocks behind the board write naive strings. SQLite's `datetime('now')`
    is UTC by definition, and the uzse mirror stamps a UTC container: its
    /health advertises the schedule as `10:00:00+05:00` while the run it fired
    is stamped `05:30` — the same moment, five hours apart. A naive string
    reaches `new Date(...)` in the browser, which reads a zone-less ISO string
    as the READER's local time, so a Tashkent reader was shown 14:00 for data
    that was in fact five hours younger than that.
    """
    if not value:
        return None
    s = str(value).strip().replace(" ", "T")
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        return s[:-1] + "Z"
    # An explicit offset (+05:00 / -0500) already says what it means.
    tail = s[-6:]
    if len(s) > 6 and tail[0] in "+-" and tail[3] == ":" and tail[1:3].isdigit():
        return s
    tail5 = s[-5:]
    if len(s) > 5 and tail5[0] in "+-" and tail5[1:].isdigit():
        return s
    return s + "Z"


@app.get("/api/market/trade-stats")
async def api_market_trade_stats() -> dict[str, Any]:
    """Per-ISIN latest-day trade statistics (turnover, avg price, largest trade)."""
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, get_all_trade_stats)
    except Exception as exc:
        logger.exception("trade-stats cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    # When the board was last refreshed BY US — the moment the collector's
    # quotes run (08:00 / 13:00 / 16:10 Tashkent) wrote these rows. This is what
    # the page's "Обновлено" badge reports: the uzse mirror's own stamp answers a
    # different question (when someone else's cache refreshed) and can never
    # show our schedule.
    stamps = [s.get("updated_at") for s in stats.values() if s.get("updated_at")]
    dates = [s.get("trade_date") for s in stats.values() if s.get("trade_date")]
    return _json_safe({
        "ok": True,
        "count": len(stats),
        "refreshed_at": _as_utc_iso(max(stamps)) if stamps else None,
        "trade_date": max(dates) if dates else None,
        "stats": stats,
    })


def _iso_trade_date(value: Any) -> str | None:
    """Normalise a last-trade date to YYYY-MM-DD.

    The three sources that know when a security last traded each state it
    differently — the RFB registry in ISO, the live UZSE feed as DD.MM.YYYY, the
    trade-stats cache as YYYYMMDD — and they are compared against each other and
    against a date cutoff, so they have to be reduced to one sortable form first.
    """
    s = str(value or "").strip()
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        return f"{s[6:]}-{s[3:5]}-{s[:2]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return None


def _live_last_trade_dates() -> dict[str, str]:
    """ticker → last trade date (ISO) as the live exchange feed reports it.

    The registry's own ``last_trade_date`` is missing for securities that trade
    perfectly normally — it is derived from openinfo's conclusions history, which
    is empty or stale for whole classes of line (ALKB, the microfinance bonds).
    Reading the exchange feed as well is what stops the delisting section from
    accusing a security that traded this morning. Best-effort: on a fetch failure
    the caller simply falls back to the registry, which is the older behaviour.

    Only evidence of an actual trade counts. ``close_date`` is the session the
    closing *quote* belongs to and the exchange carries it forward through days
    with no trading — FRAZP, MXUS, TRSBP and UZML all show yesterday's close_date
    with no volume while their last real trade was in June. So a close date is
    accepted only when the session also reports turnover.
    """
    out: dict[str, str] = {}
    for security_type in (None, "bond"):
        try:
            resp = requests.get(
                f"{UZSE_STOCK_API_BASE}/stocks",
                params={"type": security_type} if security_type else None,
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError):
            logger.warning("listings feed: live trade dates unavailable (type=%s)", security_type)
            continue
        rows = payload.get("stocks") if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            ticker = str(row.get("ticker") or "").strip().upper()
            date = _iso_trade_date(row.get("last_trade_date"))
            if not date and any(row.get(k) for k in ("volume", "quantity", "trade_count")):
                date = _iso_trade_date(row.get("close_date"))
            if ticker and date and date > out.get(ticker, ""):
                out[ticker] = date
    return out


@app.get("/api/listings/feed")
async def api_listings_feed(inactive_days: int = 30) -> dict[str, Any]:
    """Listing / delisting feed (ТЗ §3.2, item 7): who recently appeared on the
    exchange and who has gone quiet (no trades anywhere → possible delisting).

    The registry (catalog_listings, pushed by the collector) says when it last saw
    a trade, but its answer is only as good as openinfo's conclusions history —
    which is blank for securities that are trading daily. Flagging on that field
    alone put actively traded lines under "возможный делистинг", so the live
    exchange feed and the trade-stats cache are consulted too and the freshest of
    the three decides. A security is inactive only when *no* source has seen it
    trade inside the window."""
    from datetime import datetime, timedelta

    loop = asyncio.get_running_loop()
    try:
        listings, live_dates, stats = await asyncio.gather(
            loop.run_in_executor(None, get_all_listings),
            loop.run_in_executor(None, _live_last_trade_dates),
            loop.run_in_executor(None, get_all_trade_stats),
        )
    except Exception as exc:
        logger.exception("listings feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _mk(tk: str, lst: dict[str, Any]) -> dict[str, Any]:
        isin = str(lst.get("isin") or "").upper()
        candidates = (
            _iso_trade_date(lst.get("last_trade_date")),
            live_dates.get(tk.upper()),
            _iso_trade_date(((stats or {}).get(isin) or {}).get("trade_date")),
        )
        known = [d for d in candidates if d]
        return {
            "ticker": tk,
            "name": lst.get("name"),
            "isin": lst.get("isin"),
            "share_type": lst.get("share_type"),
            "listing_date": lst.get("listing_date") or None,
            "last_trade_date": max(known) if known else None,
            "market_cap": lst.get("market_cap"),
        }

    items = [_mk(tk, lst) for tk, lst in (listings or {}).items()]
    # Recently listed — those with a known listing date, newest first (ISO dates sort lexically).
    listed = sorted((i for i in items if i["listing_date"]), key=lambda i: i["listing_date"], reverse=True)
    # Delisting candidates — nothing has seen a trade inside the window.
    cutoff = (datetime.now() - timedelta(days=max(1, inactive_days))).strftime("%Y-%m-%d")
    inactive = sorted(
        (i for i in items if not i["last_trade_date"] or i["last_trade_date"] < cutoff),
        key=lambda i: (i["last_trade_date"] or ""),
    )
    return _json_safe({"ok": True, "count": len(items), "listed": listed, "inactive": inactive, "inactive_days": inactive_days})


@app.get("/api/news")
async def api_news(limit: int = 60, days: int = 180) -> dict[str, Any]:
    """Public market-news feed (ТЗ §3.2, item 6). A single dated timeline of real
    market events — new report filings + listing / delisting — so the News section
    has genuine content. (Editorial news aggregation with AI sentiment is the
    separate §3.11 module and stays out of scope.) Items carry structured fields;
    the client composes the localized headline."""
    from datetime import datetime, timedelta

    loop = asyncio.get_running_loop()
    try:
        reports, listings = await asyncio.gather(
            loop.run_in_executor(None, partial(get_recent_new_reports, max(1, days), max(1, limit))),
            loop.run_in_executor(None, get_all_listings),
        )
    except Exception as exc:
        logger.exception("news feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    items: list[dict[str, Any]] = []
    for r in reports or []:
        tk = r.get("ticker")
        items.append({
            "type": "report",
            "ticker": tk,
            "company": _TICKER_TO_NAME.get(tk, tk),
            "report_form": r.get("report_form"),
            "period_type": r.get("period_type"),
            "year": r.get("year"),
            "quarter": r.get("quarter"),
            "title": r.get("title"),
            "date": r.get("detected_at"),
        })

    listing_map = listings or {}
    listed = sorted(
        ((tk, l) for tk, l in listing_map.items() if l.get("listing_date")),
        key=lambda kv: kv[1]["listing_date"], reverse=True,
    )[:20]
    for tk, l in listed:
        items.append({
            "type": "listing", "ticker": tk, "company": l.get("name") or tk,
            "share_type": l.get("share_type"), "market_cap": l.get("market_cap"),
            "date": l.get("listing_date"),
        })

    cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    delisted = sorted(
        ((tk, l) for tk, l in listing_map.items()
         if l.get("last_trade_date") and l["last_trade_date"] < cutoff),
        key=lambda kv: kv[1]["last_trade_date"], reverse=True,
    )[:12]
    for tk, l in delisted:
        items.append({
            "type": "delisting", "ticker": tk, "company": l.get("name") or tk,
            "date": l.get("last_trade_date"),
        })

    # Unified timeline, newest first. Mixed "YYYY-MM-DD[ HH:MM:SS]" formats sort
    # correctly lexically; dateless items fall to the end.
    items.sort(key=lambda i: (i.get("date") or ""), reverse=True)
    return _json_safe({"ok": True, "count": len(items), "items": items[: max(1, limit)]})


@app.get("/api/news/feed")
async def api_news_feed(limit: int = 60, days: int = 30, type: str | None = None,
                        order: str = "rank") -> dict[str, Any]:
    """Editorial news feed (§3.11): classified, market-relevant items, ranked by impact.

    Distinct from /api/news (the market-events timeline). Each item carries a
    model-estimated tone / impact / direction — an analytical signal, not advice — plus the
    ``rank`` it was ordered by. ``order=recent`` returns plain newest-first instead.
    Low-relevance items are skipped and the same story from several outlets is merged.
    """
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_feed, limit=limit, days=days, news_type=type,
                      order="recent" if order == "recent" else "rank"))
    return _json_safe({"ok": True, "count": len(items), "items": items, "disclaimer": NEWS_DISCLAIMER})


@app.get("/api/news/item/{news_id}")
async def api_news_item(news_id: int, related: int = 6) -> dict[str, Any]:
    """One news item + its neighbours — the read path behind the /news/{id} page (§3.11).

    Pure database read of what the collector already stored (headline, our own summary, the
    classifier's tone / impact / direction, issuer links, source link), so opening an
    article never triggers a model call and costs nothing. The source's article body is
    not served here — it is never stored; the page links out for the full text.
    """
    loop = asyncio.get_running_loop()
    item = await loop.run_in_executor(None, partial(news_store.get_news_item, news_id))
    if item is None:
        raise HTTPException(status_code=404, detail="news item not found")
    neighbours: list[dict[str, Any]] = []
    if related > 0:
        neighbours = await loop.run_in_executor(
            None, partial(news_store.get_related_news, news_id, limit=min(related, 20)))
    return _json_safe({"ok": True, "item": item, "related": neighbours,
                       "disclaimer": NEWS_DISCLAIMER})


@app.get("/api/news/ticker/{ticker}")
async def api_news_ticker(ticker: str, limit: int = 30, days: int = 90) -> dict[str, Any]:
    """Per-issuer news + coverage-weighted background tone (the §3.4 info dimension)."""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_for_ticker, ticker, limit=limit, days=days))
    sentiment = await loop.run_in_executor(
        None, partial(news_store.get_news_sentiment, ticker, days=days))
    return _json_safe({"ok": True, "ticker": ticker.upper(), "count": len(items),
                       "items": items, "sentiment": sentiment, "disclaimer": NEWS_DISCLAIMER})


@app.post("/api/admin/news")
async def api_admin_news(
    payload: AdminNewsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Ingest classified news items from the external news collector (§3.11).

    Mirrors /api/admin/facts: the collector runs where the sources are reachable
    and pushes here. Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.upsert_news, payload.items))
    except Exception as exc:
        logger.exception("admin news upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@app.post("/api/admin/news/images")
async def api_admin_news_images(
    payload: AdminNewsImagesRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Fill preview images (url → image_url) on already-stored news rows (§3.11).

    The collector's ``--backfill-images`` pass pushes here rather than to
    /api/admin/news: this only touches ``news.image_url`` on rows that have none, so a
    stored item's classification (tone/impact/relevance) can never be overwritten.
    """
    images = payload.images or {}
    if len(images) > 2000:
        raise HTTPException(status_code=422, detail="too many images (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.set_image_urls, images))
    except Exception as exc:
        logger.exception("admin news image update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@app.post("/api/admin/news/snippets")
async def api_admin_news_snippets(
    payload: AdminNewsSnippetsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Replace the snippet on already-stored news rows (§3.11).

    The openinfo enrichment pass pushes here rather than to /api/admin/news: a full upsert
    there would rewrite the item's classification from a snippet-only record and drop it out
    of the feed. Only ``news.snippet`` is touched, and only when the new text is longer, so a
    re-run can never shrink a row back to its bare "Существенный факт №21".
    """
    snippets = payload.snippets or {}
    if len(snippets) > 2000:
        raise HTTPException(status_code=422, detail="too many snippets (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.set_snippets, snippets))
    except Exception as exc:
        logger.exception("admin news snippet update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@app.post("/api/admin/news/translations")
async def api_admin_news_translations(
    payload: AdminNewsTranslationsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Fill the English and Uzbek summaries on already-stored news rows (§3.11).

    The site is served in three languages but every summary used to be Russian, so an
    English or Uzbek reader got a Russian feed. New items now get all three from the same
    classification call; this is the backfill route for the rows that predate it.

    Pushes here rather than to /api/admin/news for the same reason as the image and snippet
    routes: a full upsert would rewrite the item's classification from a partial record and
    drop it out of the feed. Only the two summary columns are touched, and only where they
    are still empty, so this can never overwrite what the classifier itself wrote.
    """
    translations = payload.translations or {}
    if len(translations) > 2000:
        raise HTTPException(status_code=422, detail="too many translations (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(news_store.set_translations, translations))
    except Exception as exc:
        logger.exception("admin news translation update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@app.get("/api/admin/catalog/issuers")
async def api_admin_catalog_issuers(
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """The issuer catalog — ticker, name and openinfo `org_id` — for a collector that has no
    catalog database of its own.

    The scheduled news collector runs in a container with an empty filesystem (a Railway
    volume mounts to exactly one service), so without this it falls back to the static ticker
    list and, worse, cannot attribute openinfo filings at all — `org_id` is what maps a filing
    to a ticker. Read-only.
    """
    import reports_catalog as rc

    def _read() -> list[dict[str, Any]]:
        conn = rc.get_catalog_conn()
        rows = conn.execute(
            "SELECT ticker, company_name, org_id FROM catalog_companies ORDER BY ticker"
        ).fetchall()
        conn.close()
        return [{"ticker": r["ticker"], "company_name": r["company_name"],
                 "org_id": r["org_id"]} for r in rows if r["ticker"]]

    loop = asyncio.get_running_loop()
    try:
        issuers = await loop.run_in_executor(None, _read)
    except Exception as exc:
        logger.exception("issuer catalog read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "count": len(issuers),
            "with_org_id": sum(1 for i in issuers if i.get("org_id")), "issuers": issuers}


@app.post("/api/admin/news/known")
async def api_admin_news_known(
    payload: AdminNewsKnownRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Which of these URLs prod already stores — the collector's dedup memory when it has no
    local history of its own.

    The collector normally remembers what it has classified in its own SQLite file. A
    scheduled run in a fresh container has no such file, so without this it would re-classify
    (and re-pay for) every item on every run; prod's UNIQUE(url) would keep the rows clean
    while the LLM bill quietly doubled. Read-only: nothing is written.
    """
    urls = [u for u in (payload.urls or []) if u]
    loop = asyncio.get_running_loop()
    known = await loop.run_in_executor(None, partial(news_store.existing_urls, urls))
    return {"ok": True, "checked": len(urls), "known": sorted(known)}


@app.post("/api/admin/news/purge-failed")
async def api_admin_news_purge_failed(
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Delete news items whose classification failed, so the collector retries them.

    Those rows sit at ``relevant = 0`` — invisible in the feed, yet their URLs make the
    collector's dedup skip them forever. Deleting them is the only retry. Rows carrying a
    real classifier verdict are never touched.
    """
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, news_store.delete_failed_classifications)
    except Exception as exc:
        logger.exception("admin news purge-failed failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, **result}


def _issuer_universe() -> dict[str, str]:
    """ticker → name, to constrain the classifier's ticker tags (mirrors the collector)."""
    import reports_catalog as rc
    universe: dict[str, str] = {}
    try:
        conn = rc.get_catalog_conn()
        for r in conn.execute("SELECT ticker, company_name FROM catalog_companies").fetchall():
            if r["ticker"]:
                universe[r["ticker"].upper()] = r["company_name"] or r["ticker"]
        conn.close()
    except Exception:  # noqa: BLE001 — fall back to the static catalog
        logger.exception("issuer universe query failed; classifier will infer sectors only")
    if not universe:
        try:
            universe = {t.upper(): n for t, n in rc._TICKER_TO_NAME.items()}
        except Exception:  # noqa: BLE001
            pass
    return universe


def _news_search_sync(query: str, days: int, store: bool) -> dict[str, Any]:
    """Run the Layer-B search agent, classify each hit, and (by default) store it.

    Blocking (network + LLM) — called via run_in_executor. Reuses the collector's
    classify → upsert path so agent-found items are indistinguishable from
    feed-collected ones (same tables, same /api/news/feed). Already-stored URLs are
    skipped so we never re-pay to classify them.
    """
    from news_agent import find_news
    from news_classifier import classify_item
    from llm_client import Usage

    findings = find_news(query, days=days)
    universe = _issuer_universe()
    usage = Usage()
    model = os.getenv("NEWS_CLASSIFIER_MODEL", "").strip() or os.getenv("LLM_MODEL", "grok-4.3")

    seen = news_store.existing_urls([it["url"] for it in findings.items if it.get("url")])
    records: list[dict[str, Any]] = []
    for it in findings.items:
        if not it.get("url") or it["url"] in seen:
            continue
        # triage=False: the admin asked for this company by name, so relevance is already
        # established — the cheap gate exists for whole-feed collection, not targeted search.
        cls = classify_item({**it, "lang": None}, universe, usage=usage, triage=False)
        records.append({
            "url": it["url"],
            "title": it.get("title", ""),
            "snippet": it.get("snippet", ""),
            "source": it.get("source") or "grok-search",
            "source_id": "grok_search",
            "lang": None,
            "image_url": it.get("image_url"),
            "published_at": it.get("published"),
            "coverage_weight": 0.5,
            "model": model,
            **cls.model_dump(),
        })

    stored = news_store.upsert_news(records) if (store and records) else 0
    relevant = [r for r in records if r.get("relevant")]
    return {
        "query": query,
        "backend": findings.backend,
        "note": findings.note,
        "queries": findings.queries,
        "found": len(findings.items),
        "new": len(records),
        "already_stored": len(findings.items) - len(records),
        "relevant": len(relevant),
        "stored": stored,
        "items": [{
            "url": r["url"], "title": r["title"], "source": r["source"],
            "published_at": r["published_at"], "relevant": r.get("relevant"),
            "type": r.get("type"), "tone": r.get("tone"), "impact": r.get("impact"),
            "direction": r.get("direction"), "tickers": r.get("tickers"),
            "summary_ru": r.get("summary_ru"), "image_url": r.get("image_url"),
        } for r in records],
        "tokens": findings.usage.total_tokens + usage.total_tokens,
    }


@app.get("/api/admin/news/search")
async def api_admin_news_search(
    q: str,
    days: int = 7,
    store: bool = True,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """On-demand Layer-B news search (§3.11): the Grok agent actively finds news for
    a company/ticker/topic via server-side web + X search, classifies each hit, and
    (by default, store=true) stores it so it surfaces in /api/news/feed and the
    per-ticker endpoints. Admin-only — each call triggers billed searches.
    Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="q (search query) is required")
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="q too long (max 200 chars)")
    days = max(1, min(days, 30))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, partial(_news_search_sync, query, days, store))
    except Exception as exc:
        logger.exception("admin news search failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _json_safe({"ok": True, **result, "disclaimer": NEWS_DISCLAIMER})


def _require_admin_user(current_user: WebUser = Depends(_require_user)) -> WebUser:
    """Gate a route to admin web users (email in ADMIN_EMAILS). Unlike ``_require_admin``
    (machine X-Admin-Secret), this authorises a logged-in user via their Bearer token —
    so the frontend admin panel can call it without the shared secret ever reaching
    the browser."""
    if not is_admin_email(current_user.email):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.get("/api/news/agent-search")
async def api_news_agent_search(
    q: str,
    days: int = 7,
    store: bool = True,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Admin-only news-agent search for the web UI (§3.11). Same engine as
    ``/api/admin/news/search`` (Grok finds → grok-4.3 classifies → upsert into the
    news tables), but authenticated by an admin web-user's Bearer token instead of
    the machine secret. Each call triggers billed Grok searches, hence admin-gated.
    """
    query = (q or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="q (search query) is required")
    if len(query) > 200:
        raise HTTPException(status_code=422, detail="q too long (max 200 chars)")
    days = max(1, min(days, 30))
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, partial(_news_search_sync, query, days, store))
    except Exception as exc:
        logger.exception("news agent search failed for user %s", current_user.id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _json_safe({"ok": True, **result, "disclaimer": NEWS_DISCLAIMER})


@app.post("/api/admin/trade-stats")
async def api_admin_trade_stats(
    payload: AdminTradeStatsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Overwrite the trade-statistics cache from an externally-computed batch."""
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(bulk_upsert_trade_stats, payload.rows, payload.trade_date))
    except Exception as exc:
        logger.exception("admin trade-stats upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@app.post("/api/admin/quotes")
async def api_admin_quotes(
    payload: AdminQuotesRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Store the exchange's own session quotes (close, previous close, change)."""
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(bulk_upsert_quotes, payload.rows))
    except Exception as exc:
        logger.exception("admin quotes upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    _schedule_audit("ingest:quotes")
    return {"ok": True, "upserted": n}


@app.post("/api/admin/financials")
async def api_admin_financials(
    payload: AdminFinancialsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Overwrite the NSBU financials cache from an externally-computed batch.

    Lets a collector running where openinfo.uz is reachable refresh this
    deployment (whose datacenter IP openinfo blocks). Authenticated via the
    ADMIN_API_SECRET shared secret in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    writer = bulk_replace_financials if payload.mode == "replace" else bulk_upsert_financials
    try:
        n = await loop.run_in_executor(None, partial(writer, payload.rows, payload.form))
    except Exception as exc:
        logger.exception("admin financials %s failed", payload.mode)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, ("replaced" if payload.mode == "replace" else "upserted"): n}


@app.post("/api/admin/facts")
async def api_admin_facts(
    payload: AdminFactsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Ingest generic facts from an external collector (adapter output).

    Lets the ingestion job — running where openinfo is reachable (a UZ host or a
    proxy) — push the fact store to this deployment, which openinfo blocks.
    Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(upsert_facts, payload.rows))
    except Exception as exc:
        logger.exception("admin facts upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@app.post("/api/admin/listings")
async def api_admin_listings(
    payload: AdminListingsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Overwrite the exchange-listing registry from an externally-computed batch.

    Lets the collector (where openinfo is reachable) push listed-but-inactive
    issuers — the ones absent from the live uzse-stock feed — so they still appear
    on the market board. Authenticated via ADMIN_API_SECRET in X-Admin-Secret.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(bulk_upsert_listings, payload.rows))
    except Exception as exc:
        logger.exception("admin listings upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@app.get("/api/admin/openinfo-probe")
async def api_admin_openinfo_probe(
    search: str = "Hamkorbank",
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Live connectivity matrix: which openinfo endpoint classes THIS deployment
    can reach from its own egress IP, using the same client configuration the
    collector uses (proxy, TLS). Diagnoses full/partial IP blocks without guessing.
    """
    from openinfo_probe import run_probe

    loop = asyncio.get_running_loop()
    try:
        return _json_safe(await loop.run_in_executor(None, partial(run_probe, search)))
    except Exception as exc:
        logger.exception("openinfo probe failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_admin_catalog_sync_running = threading.Event()


@app.post("/api/admin/logos/materialise")
async def api_admin_materialise_logos(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """Pull externally hosted logos into our own storage (Дополнение 1 §Б.7).

    Idempotent — a logo already stored is left alone. Run it after adding a new
    company, or the interface starts depending on somebody else's service again.
    """
    loop = asyncio.get_running_loop()
    return _json_safe(await loop.run_in_executor(None, logo_store.materialise_all))


@app.get("/api/admin/logos/audit")
async def api_admin_logo_audit(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """How much of the interface still depends on a third party."""
    return _json_safe({"ok": True, **logo_store.audit()})


@app.post("/api/admin/catalog/register")
async def api_admin_catalog_register(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """Register the catalog's issuers and reports in the provenance registry.

    Idempotent, and safe to run at any time: a report already registered keeps
    the state it reached, so this never resets something already parsed.
    """
    from reports_catalog import backfill_report_links

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, provenance.sync_from_catalog)
    # Figures cached before provenance existed are linked to the filing they were
    # read from — the mapping is deterministic, so nothing has to be re-downloaded.
    backfilled = await loop.run_in_executor(None, backfill_report_links)
    return {"ok": True, **result, "backfilled": backfilled}


@app.post("/api/admin/catalog-sync")
async def api_admin_catalog_sync(
    force: bool = False,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Trigger this deployment's own full catalog sync in the background.

    openinfo is reachable from the deployment itself (verify via
    /api/admin/openinfo-probe), so the org map, report catalog and sync-error
    states can be rebuilt in place — including the self-healing purge for
    tickers whose issuer resolution changed. Returns immediately; progress is
    visible in /api/coverage.
    """
    if _admin_catalog_sync_running.is_set():
        return {"ok": True, "started": False, "detail": "catalog sync already running"}

    def _run() -> None:
        _admin_catalog_sync_running.set()
        try:
            res = catalog_sync_all(force=force)
            logger.info("admin catalog sync done: %s",
                        {k: res.get(k) for k in ("total", "synced", "skipped") if isinstance(res, dict)})
        except Exception:
            logger.exception("admin catalog sync failed")
        finally:
            _admin_catalog_sync_running.clear()

    asyncio.get_running_loop().run_in_executor(None, _run)
    return {"ok": True, "started": True, "force": force}


@app.get("/api/securities")
async def api_securities() -> dict[str, Any]:
    """Return the full securities map {ticker: info}."""
    try:
        loop = asyncio.get_running_loop()
        smap = await loop.run_in_executor(None, get_securities_map)
        return {"ok": True, "count": len(smap), "securities": smap}
    except Exception as exc:
        logger.exception("securities map failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/securities/{ticker}/info")
async def api_securities_info(ticker: str, language: str = "ru") -> dict[str, Any]:
    """Return company info including Wikipedia extract for a ticker."""
    ticker = ticker.upper()
    try:
        loop = asyncio.get_running_loop()
        smap = await loop.run_in_executor(None, get_securities_map)
        sec = smap.get(ticker)
        if not sec:
            # The securities map is filled from the live trading feed only, so
            # listed-but-inactive securities (present in the RFB registry) used
            # to 404 into a blank company page. Serve their registry data.
            listings = await loop.run_in_executor(None, get_all_listings)
            listing = (listings or {}).get(ticker)
            if listing:
                sec = {
                    "ticker": ticker,
                    "company_name": listing.get("name"),
                    "security_name": listing.get("name"),
                    "isin": listing.get("isin"),
                    "share_type": listing.get("share_type"),
                    "listing_date": listing.get("listing_date"),
                    "shares_outstanding": listing.get("shares_outstanding"),
                    "last_price": listing.get("last_price"),
                    "last_trade_date": listing.get("last_trade_date"),
                    "market_cap": listing.get("market_cap"),
                    "inactive": True,
                }
        if not sec:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in securities")
        wiki = await loop.run_in_executor(
            None, partial(get_wiki_info, ticker, sec.get("company_name") or sec.get("security_name") or "", language)
        )
        return {"ok": True, "ticker": ticker, "security": sec, "wiki": wiki}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("securities info failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class OAuthExchangeRequest(BaseModel):
    code: str = Field(..., min_length=8, max_length=128)


@app.post("/api/auth/oauth/exchange")
async def api_oauth_exchange(payload: OAuthExchangeRequest, request: Request) -> dict[str, Any]:
    """Redeem the one-time code from the OAuth redirect for the access token."""
    _enforce_auth_rate_limit(request, "oauth-exchange")
    redeemed = _redeem_oauth_code(payload.code)
    if not redeemed:
        raise HTTPException(status_code=400, detail="Invalid or expired sign-in code")
    provider, token = redeemed
    return {"ok": True, "provider": provider, "token": token}


@app.post("/api/auth/register")
async def api_register(payload: RegisterRequest, request: Request) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, "register")
    try:
        # Executor-wrapped: PBKDF2 (~100ms CPU) + a sync Postgres roundtrip
        # would otherwise run on the event loop.
        user, token = await asyncio.get_running_loop().run_in_executor(None, partial(
            web_auth_store.register_user,
            payload.email,
            payload.password,
            payload.full_name,
        ))
    except ValueError as exc:
        message = str(exc)
        status = 409 if "already registered" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@app.post("/api/auth/login")
async def api_login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    _enforce_auth_rate_limit(request, "login")
    try:
        user, token = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.login_user, payload.email, payload.password))
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
        revoked = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.revoke_token, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"ok": True, "revoked": revoked}


@app.get("/api/profile")
async def api_profile(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    try:
        profile = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.get_profile, current_user.id))
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
        updated_user = await asyncio.get_running_loop().run_in_executor(None, partial(
            web_auth_store.update_profile,
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

    return {"ok": True, "user": _json_safe(updated_user.to_public_dict())}


@app.get("/api/favorites")
async def api_favorites(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    try:
        favorites = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.list_favorites, current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "count": len(favorites), "favorites": _json_safe(favorites)}


@app.post("/api/favorites/toggle")
async def api_favorites_toggle(
    payload: FavoriteToggleRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, partial(
            web_auth_store.toggle_favorite,
            current_user.id,
            payload.ticker,
            payload.company_name,
        ))
        favorites = await loop.run_in_executor(
            None, partial(web_auth_store.list_favorites, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, **_json_safe(result), "favorites": _json_safe(favorites)}


@app.get("/api/auth/oauth/google/start")
async def api_oauth_google_start(request: Request) -> RedirectResponse:
    try:
        # The state cookie must be set on the SAME response that redirects to the
        # provider, so build the response first and mint the nonce onto it.
        response = RedirectResponse("about:blank", status_code=302)
        state = _issue_oauth_state(request, response)
        response.headers["location"] = _build_google_auth_url(request, state)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/auth/oauth/google/callback", name="api_oauth_google_callback")
async def api_oauth_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return _oauth_failure(error)
    # Check state BEFORE spending a token exchange on it: an unmatched state means
    # this callback did not originate from a flow this browser started.
    if not _verify_oauth_state(request, state):
        logger.warning("oauth callback rejected: state missing or does not match the browser cookie")
        failed = _oauth_failure("Login session expired or invalid — please try signing in again")
        _clear_oauth_state(failed)
        return failed
    if not code:
        return _oauth_failure("Google login was cancelled or did not return a code")

    try:
        loop = asyncio.get_running_loop()
        profile = await loop.run_in_executor(None, partial(_exchange_google_code, code, request))
        user, token = await loop.run_in_executor(None, partial(
            web_auth_store.oauth_login,
            "google",
            profile["provider_user_id"],
            profile.get("email"),
            profile.get("full_name") or "",
        ))
    except HTTPException:
        raise
    except requests.RequestException as exc:
        return _oauth_failure(f"Google auth failed: {exc}")
    except Exception as exc:
        return _oauth_failure(str(exc))

    # Single-use: the nonce is spent whether or not the login succeeded, so a
    # replayed callback cannot reuse it.
    success = _oauth_success("google", token)
    _clear_oauth_state(success)
    return success


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
    _enforce_llm_quota(current_user)
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


class ExcelExportRequest(BaseModel):
    result: dict[str, Any]
    language: str = "ru"


@app.post("/api/analyze/export/excel")
async def api_export_excel(
    payload: ExcelExportRequest,
    current_user: WebUser = Depends(_require_user),
) -> Response:
    """Export a completed analysis result to .xlsx (ТЗ §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(build_analysis_excel, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        logger.exception("excel export failed")
        raise HTTPException(status_code=500, detail="Could not build the Excel file") from exc

    company = payload.result.get("company_name") or payload.result.get("input") or "analysis"
    safe = "".join(ch for ch in str(company) if ch.isalnum() or ch in "-_")[:40] or "analysis"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe}_analysis.xlsx"'},
    )


@app.post("/api/analyze/export/pdf")
async def api_export_pdf(
    payload: ExcelExportRequest,
    current_user: WebUser = Depends(_require_user),
) -> Response:
    """Export a completed analysis result to PDF (ТЗ §3.13 / C5)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(build_analysis_pdf, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        logger.exception("pdf export failed")
        raise HTTPException(status_code=500, detail="Could not build the PDF file") from exc

    company = payload.result.get("company_name") or payload.result.get("input") or "analysis"
    safe = "".join(ch for ch in str(company) if ch.isalnum() or ch in "-_")[:40] or "analysis"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}_analysis.pdf"'},
    )


@app.post("/api/compare/export/excel")
async def api_compare_export_excel(
    payload: ExcelExportRequest,
    current_user: WebUser = Depends(_require_user),
) -> Response:
    """Export a completed comparison result to .xlsx (ТЗ §3.6 / §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(build_comparison_excel, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        logger.exception("compare excel export failed")
        raise HTTPException(status_code=500, detail="Could not build the Excel file") from exc

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="comparison.xlsx"'},
    )


@app.post("/api/compare/export/pdf")
async def api_compare_export_pdf(
    payload: ExcelExportRequest,
    current_user: WebUser = Depends(_require_user),
) -> Response:
    """Export a completed comparison result to PDF (ТЗ §3.6 / §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(build_comparison_pdf, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        logger.exception("compare pdf export failed")
        raise HTTPException(status_code=500, detail="Could not build the PDF file") from exc

    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="comparison.pdf"'},
    )


@app.post("/api/analyze")
async def api_analyze(
    payload: AnalyzeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    _enforce_llm_quota(current_user)
    try:
        result = await run_company_analysis(
            payload.company,
            language=payload.language,
            force_refresh=payload.force_refresh,
            include_all_excel_reports=payload.include_all_excel_reports,
            excel_report_limit=payload.excel_report_limit,
            report_analysis_type=payload.report_analysis_type,
            report_quarter=payload.report_quarter,
            report_current_year=payload.report_current_year,
            report_previous_year=payload.report_previous_year,
            report_form=payload.report_form,
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
        "cache_mode": result.get("cache_mode"),
        "summary": build_summary(result),
        "sections": result.get("sections", {}),
        "report_tables": result.get("report_tables"),
        "report_tables_version": result.get("report_tables_version"),
        "article_report": result.get("article_report"),
        "article_report_version": result.get("article_report_version"),
        "metrics": result.get("metrics"),
        "ifrs_snapshot": result.get("ifrs_snapshot"),
        # ТЗ §3.4 / §3.5 — the risk profile and statistical observations are
        # computed in the engine; forward them so the RiskProfilePanel and
        # ObservationsPanel actually render on the Analysis screen.
        "risk_profile": result.get("risk_profile"),
        "observations": result.get("observations"),
        "liquidity": result.get("liquidity"),
        "market_data": result.get("market_data"),
        "market_context": result.get("market_context"),
        "excel_report_mode": result.get("excel_report_mode"),
        "report_comparison": result.get("report_comparison"),
        "analysis_policy_version": result.get("analysis_policy_version"),
        "analysis_policy": result.get("analysis_policy"),
        # ТЗ §3.3: mandatory, non-removable disclaimer travels inside every report payload.
        "disclaimer": report_disclaimer(result.get("language", payload.language)),
        "requested_by": current_user.to_public_dict(),
    }

    if payload.include_raw:
        response["raw_analysis"] = result.get("raw_analysis")
    if payload.include_html:
        response["html_report"] = result.get("html_report")

    try:
        await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.record_analysis, current_user.id, payload.model_dump(), result))
    except Exception as exc:
        logger.warning("Failed to record analysis history for user %s: %s", current_user.id, exc)

    return _json_safe(response)


# ---------------------------------------------------------------------------
# Report Catalog endpoints
# ---------------------------------------------------------------------------

@app.get("/api/catalog/status")
async def api_catalog_status() -> dict[str, Any]:
    try:
        return {"ok": True, **get_catalog_stats()}
    except Exception as exc:
        logger.exception("Catalog status failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/catalog/companies")
async def api_catalog_companies() -> dict[str, Any]:
    try:
        companies = list_companies_with_stats()
        for c in companies:
            c["logo"] = resolve_logo(c.get("ticker", ""), COMPANY_LOGOS) or ""
        return {"ok": True, "count": len(companies), "companies": companies}
    except Exception as exc:
        logger.exception("Catalog companies list failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/catalog/index/{ticker}")
async def api_catalog_index(ticker: str) -> dict[str, Any]:
    try:
        index = get_company_index(ticker.upper())
        return {"ok": True, **index}
    except Exception as exc:
        logger.exception("Catalog index failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/catalog/sync")
async def api_catalog_sync(
    payload: CatalogSyncRequest,
    current_user: WebUser = Depends(_require_user),
    x_admin_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    # A single-ticker sync is a bounded refresh any signed-in user may run; the
    # FULL catalog scrape is minutes of upstream traffic and admin-only
    # (X-Admin-Secret, same as /api/admin/catalog-sync).
    if not payload.ticker:
        _require_admin(x_admin_secret)
    loop = asyncio.get_running_loop()
    try:
        if payload.ticker:
            ticker = payload.ticker.upper()
            company_name = _TICKER_TO_NAME.get(ticker)
            if not company_name:
                raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
            result = await loop.run_in_executor(
                None, partial(catalog_sync_company, ticker, company_name, force=payload.force)
            )
        else:
            result = await loop.run_in_executor(
                None, partial(catalog_sync_all, force=payload.force)
            )
        return {"ok": True, **_json_safe(result)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Catalog sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/catalog/analyze")
async def api_catalog_analyze(
    payload: CatalogAnalyzeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    ticker = payload.ticker.upper()
    company_name = _TICKER_TO_NAME.get(ticker, ticker)
    loop = asyncio.get_running_loop()
    form_map = {"NSBU": "NAS", "MSFO": "IFRS", "Audition": "Audit"}

    try:
        if payload.analysis_type == "ratio":
            prev_year = payload.year - 1
            excel, excel_prev = await asyncio.gather(
                loop.run_in_executor(None, partial(fetch_report_excel_data, ticker, payload.form, payload.year, payload.quarter)),
                loop.run_in_executor(None, partial(fetch_report_excel_data, ticker, payload.form, prev_year, payload.quarter)),
            )
            if not excel.get("ok"):
                raise HTTPException(status_code=400, detail=excel.get("error") or "Could not fetch report")
            ratios = compute_financial_ratios(excel.get("income"), excel.get("balance"))
            ratios_prev = compute_financial_ratios(excel_prev.get("income"), excel_prev.get("balance")) if excel_prev.get("ok") else {}
            # Cache ratios for sector averaging
            if ratios.get("metrics"):
                try:
                    await loop.run_in_executor(None, partial(upsert_ratio_cache, ticker, payload.form, payload.year, payload.quarter, ratios["metrics"]))
                except Exception:
                    pass
            # Sector peers — COMPANY_SECTORS is {ticker: sector_name}
            sector = COMPANY_SECTORS.get(ticker)
            sector_peers = [t for t, s in COMPANY_SECTORS.items() if s == sector and t != ticker] if sector else []
            sector_avg: dict = {}
            if sector_peers:
                try:
                    sector_avg = await loop.run_in_executor(None, partial(get_sector_averages, sector_peers, payload.form, payload.year))
                except Exception:
                    pass
            return _json_safe({
                "ok": True, "analysis_type": "ratio", "ticker": ticker,
                "year": payload.year, "quarter": payload.quarter, "form": payload.form,
                **ratios,
                "prev_year": prev_year,
                "prev_metrics": ratios_prev.get("metrics"),
                "sector": sector,
                "sector_avg": sector_avg,
            })

        if payload.analysis_type == "dynamics":
            dynamics = await loop.run_in_executor(
                None, partial(build_dynamics_data, ticker, payload.form)
            )
            return _json_safe({"ok": True, "analysis_type": "dynamics", "ticker": ticker, **dynamics})

        if payload.analysis_type in ("quarter_compare", "annual_compare"):
            q2 = payload.compare_quarter if payload.compare_quarter is not None else payload.quarter
            y2 = payload.compare_year or (payload.year - 1)
            excel1, excel2 = await asyncio.gather(
                loop.run_in_executor(None, partial(fetch_report_excel_data, ticker, payload.form, payload.year, payload.quarter)),
                loop.run_in_executor(None, partial(fetch_report_excel_data, ticker, payload.form, y2, q2)),
            )
            ratios1 = compute_financial_ratios(excel1.get("income"), excel1.get("balance")) if excel1.get("ok") else {}
            ratios2 = compute_financial_ratios(excel2.get("income"), excel2.get("balance")) if excel2.get("ok") else {}
            return _json_safe({
                "ok": True, "analysis_type": payload.analysis_type, "ticker": ticker,
                "period1": {"year": payload.year, "quarter": payload.quarter, "form": payload.form, **ratios1},
                "period2": {"year": y2, "quarter": q2, "form": payload.form, **ratios2},
            })

        if payload.analysis_type == "multi_company":
            _enforce_llm_quota(current_user)
            compare_ticker = (payload.compare_ticker or "").upper()
            compare_name = _TICKER_TO_NAME.get(compare_ticker, compare_ticker)
            if not compare_name:
                raise HTTPException(status_code=400, detail="compare_ticker is required")
            result = await loop.run_in_executor(
                None, partial(build_company_comparison, [company_name, compare_name], payload.language, True)
            )
            return _json_safe({"ok": True, "analysis_type": "multi_company", **result})

        # AI-based: financial / swot / recommendation
        _enforce_llm_quota(current_user)
        period_type = "quarterly" if payload.quarter > 0 else "annual"
        result = await run_company_analysis(
            company_name,
            language=payload.language,
            report_analysis_type=period_type,
            report_quarter=payload.quarter if payload.quarter > 0 else None,
            report_current_year=payload.year,
            report_previous_year=payload.year - 1,
            report_form=form_map.get(payload.form, "NAS"),
        )
        return _json_safe({
            "ok": True, "analysis_type": payload.analysis_type, "ticker": ticker,
            "company_name": result.get("company_name"),
            "year": payload.year, "quarter": payload.quarter, "language": payload.language,
            "sections": result.get("sections", {}),
            "metrics": result.get("metrics"),
            "summary": build_summary(result),
            "article_report": result.get("article_report"),
            "report_tables": result.get("report_tables"),
        })

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Catalog analyze failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _resolve_isin(ticker: str) -> str | None:
    """ISIN for a ticker: local catalog first, listing registry, then the feed.

    The ISIN is known locally (securities catalog / listing registry) — resolve
    there first. The live feed only lists actively traded tickers, so inactive
    listings used to die with "ISIN not found"; it remains the last-resort
    fallback for brand-new tickers.
    """
    import os
    import requests as _req

    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    try:
        smap = await loop.run_in_executor(None, get_securities_map)
        isin = str((smap.get(ticker) or {}).get("isin") or "").strip() or None
        if isin:
            return isin
    except Exception:  # noqa: BLE001
        pass
    try:
        listings = await loop.run_in_executor(None, get_all_listings)
        isin = str(((listings or {}).get(ticker) or {}).get("isin") or "").strip() or None
        if isin:
            return isin
    except Exception:  # noqa: BLE001
        pass
    try:
        uzse_base = os.getenv("UZSE_STOCK_API_BASE", "https://uzse-stock-production.up.railway.app").rstrip("/")
        resp = await loop.run_in_executor(None, lambda: _req.get(f"{uzse_base}/stocks", timeout=15))
        stocks = resp.json().get("stocks", []) if resp.ok else []
        return next((s["isin"] for s in stocks if s.get("ticker", "").upper() == ticker), None)
    except Exception:  # noqa: BLE001
        return None


# Full history per ISIN, kept briefly in-process. The metrics endpoint needs the
# WHOLE series on every call (absolute metrics are computed on it by definition),
# so without this a period switch would refetch five years from openinfo.
_HISTORY_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HISTORY_CACHE_TTL = 600.0
_HISTORY_CACHE_MAX = 256


async def _full_history(isin: str, months: int = 60) -> dict[str, Any]:
    """Full price history for an ISIN, memoised for _HISTORY_CACHE_TTL seconds."""
    from openinfo_collector import fetch_price_history

    key = f"{isin}:{months}"
    now = time.time()
    hit = _HISTORY_CACHE.get(key)
    if hit and now - hit[0] < _HISTORY_CACHE_TTL:
        return hit[1]
    loop = asyncio.get_running_loop()
    data = await loop.run_in_executor(None, partial(fetch_price_history, isin, None, months))
    if len(_HISTORY_CACHE) >= _HISTORY_CACHE_MAX:
        oldest = min(_HISTORY_CACHE, key=lambda k: _HISTORY_CACHE[k][0])
        _HISTORY_CACHE.pop(oldest, None)
    _HISTORY_CACHE[key] = (now, data)
    return data


@app.get("/api/company/{ticker}/metrics")
async def api_company_metrics(ticker: str, months: int = 12) -> dict[str, Any]:
    """Window and absolute price metrics for one instrument (ТЗ v1.2 §5).

    The two blocks are the contract: ``window`` follows the period button,
    ``absolute`` never does. Both are computed by formulas.py from one full
    history fetch, so the card, the market screen and the export cannot each
    arrive at a different VWAP or a different YTD.
    """
    from datetime import datetime, timezone

    import formulas

    ticker = ticker.upper()
    months = max(1, min(months, 60))
    # ТЗ §12: every number on the card can be replayed step by step under one
    # trace_id — input, decision with its reason, output.
    trace = obs.Trace(endpoint="company/metrics", ticker=ticker, months=months)
    try:
        isin = await _resolve_isin(ticker)
        if not isin:
            trace.reject("resolve_isin", reason="ISIN not found")
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "trace_id": trace.trace_id}, status_code=404)
        trace.step("resolve_isin", out={"isin": isin})
        data = await _full_history(isin)
        points = data.get("points") or []
        trace.step("history_fetch", out={"points": len(points)})
        metrics = formulas.company_metrics(points, months=months)
        window, absolute, quality = metrics["window"], metrics["absolute"], metrics["quality"]
        trace.step("window_metrics", out={"code": window["code"], "points": window["points"],
                                          "vwap": window["vwap"].get("value"),
                                          "method": window["vwap"].get("method")})
        trace.step("absolute_metrics", decision="no_window_param",
                   out={k: (v or {}).get("value") for k, v in absolute.items()})
        trace.step("quality", decision=quality["data_tier"], reason=quality.get("reason"),
                   out={"candles": quality["candles_enabled"]})
        return {
            "ok": True, "ticker": ticker, "isin": isin,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trace_id": trace.trace_id,
            **metrics,
        }
    except Exception as exc:
        trace.reject("metrics", reason=str(exc))
        logger.exception("metrics failed for %s", ticker)
        return JSONResponse({"ok": False, "ticker": ticker, "error": str(exc),
                             "trace_id": trace.trace_id}, status_code=502)
    finally:
        trace.close()


@app.get("/api/price-history/{ticker}")
async def api_price_history(ticker: str, months: int = 12) -> dict[str, Any]:
    """Close price history for a ticker via UZSE ISIN lookup."""
    ticker = ticker.upper()
    months = max(1, min(months, 60))
    loop = asyncio.get_running_loop()
    try:
        isin = await _resolve_isin(ticker)
        if not isin:
            # ТЗ §10.4.6: an unknown instrument is a 404. Returning 200 with a
            # failure body is why neither the browser, retries nor monitoring
            # could tell a fault from a normal answer.
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "points": []}, status_code=404)
        from openinfo_collector import fetch_price_history
        data = await loop.run_in_executor(None, partial(fetch_price_history, isin, None, months))
        points = [
            {
                "date": p.get("date"),
                "open": p.get("open"),
                "high": p.get("high"),
                "low": p.get("low"),
                "close": p.get("close"),
                "change": p.get("change"),
                "volume": p.get("trading_volume"),
                "value": p.get("trading_value"),
            }
            for p in (data.get("points") or [])
            if p.get("date") and p.get("close") is not None
        ]
        # Non-empty only when the series spans a split or a bonus issue: the older prices
        # have been restated onto today's share, so the chart says so rather than let a
        # reader reconcile it against uzse.uz and conclude we are wrong.
        return {
            "ok": True, "ticker": ticker, "isin": isin, "points": points,
            "adjustments": data.get("adjustments") or [],
        }
    except Exception as exc:
        logger.exception("price-history failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "points": []}


def _normalize_dividends(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map raw openinfo dividend-calendar rows to a stable frontend shape."""
    def _num(value: Any) -> float | None:
        try:
            if value in (None, "", "-"):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    rows = []
    for item in items:
        rows.append({
            "decision_date": item.get("decision_date"),
            "pub_date": item.get("pub_date"),
            "organization": item.get("organization"),
            "ordinary_amount": _num(item.get("common_share_amount")),
            "ordinary_percent": _num(item.get("common_share_percent")),
            "ordinary_start": item.get("common_share_start_date"),
            "ordinary_end": item.get("common_share_end_date"),
            "preferred_amount": _num(item.get("priviliged_share_amount")),
            "preferred_percent": _num(item.get("priviliged_share_percent")),
            "preferred_start": item.get("priviliged_share_start_date"),
            "preferred_end": item.get("priviliged_share_end_date"),
            "link": item.get("link"),
        })
    rows.sort(key=lambda r: str(r.get("decision_date") or ""), reverse=True)
    return rows


@app.get("/api/dividends/{ticker}")
async def api_dividends(ticker: str) -> dict[str, Any]:
    """Dividend history for a ticker, resolved via the company's legal name."""
    from openinfo_collector import resolve_company, fetch_dividends

    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    try:
        company = await loop.run_in_executor(None, partial(resolve_company, ticker))
        company_name = (company or {}).get("company_name") or ticker
        data = await loop.run_in_executor(None, partial(fetch_dividends, company_name, None, 50))
        if not data.get("count") and company_name != ticker:
            data = await loop.run_in_executor(None, partial(fetch_dividends, ticker, None, 50))
        items = _normalize_dividends(data.get("items") or [])
        return {"ok": True, "ticker": ticker, "company_name": company_name, "count": len(items), "items": items}
    except Exception as exc:
        logger.exception("dividends failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "items": []}


@app.get("/api/catalog/company/{ticker}/reports")
async def api_company_reports(ticker: str) -> dict[str, Any]:
    """Return all catalog reports and cached ratios for a ticker."""
    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    reports = await loop.run_in_executor(None, partial(get_company_reports, ticker))
    ratios = await loop.run_in_executor(None, partial(get_company_ratios_cached, ticker))
    return _json_safe({"ok": True, "ticker": ticker, "reports": reports, "ratios": ratios})


@app.get("/api/notifications")
async def api_notifications(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    """New catalog reports for the user's favorited tickers (last 7 days)."""
    try:
        loop = asyncio.get_running_loop()
        favorites = await loop.run_in_executor(
            None, partial(web_auth_store.list_favorites, current_user.id))
        tickers = [f["ticker"] for f in favorites]
        if not tickers:
            return {"ok": True, "count": 0, "items": []}
        items = await loop.run_in_executor(None, partial(get_new_reports_for_tickers, tickers, 7))
        return {"ok": True, "count": len(items), "items": _json_safe(items)}
    except Exception as exc:
        logger.exception("notifications failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# ТЗ §10.11 — v2 lives BESIDE v1, and v1 is switched off only after the
# acceptance set passes. Every /api route is therefore also reachable under
# /api/v2 with the same handler: no fork, no second implementation, nothing to
# drift. Clients migrate at their own pace and a rollback is a URL, not a
# release.
#
# Registered here, before the SPA catch-all: FastAPI matches in registration
# order, and a catch-all added first would swallow every v2 path.
# ---------------------------------------------------------------------------

def _mount_v2_alias() -> int:
    from fastapi.routing import APIRoute

    aliased = 0
    for route in list(app.router.routes):
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/") or path.startswith("/api/v2/"):
            continue
        app.router.add_api_route(
            f"/api/v2{path[len('/api'):]}",
            route.endpoint,
            methods=list(route.methods or []),
            response_model=route.response_model,
            status_code=route.status_code,
            dependencies=list(route.dependencies or []),
            summary=route.summary,
            description=route.description,
            # Out of the schema: one route documented twice reads as two
            # different endpoints, which is the confusion this alias avoids.
            include_in_schema=False,
            name=f"{route.name}__v2" if route.name else None,
        )
        aliased += 1
    return aliased


API_V2_ROUTES = _mount_v2_alias()
logger.info("api: %d routes also served under /api/v2", API_V2_ROUTES)


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str) -> FileResponse:
    """Serve the SPA shell for client-side routes (/market, /heatmap, /catalog…).

    Registered last so real API and static routes match first; unknown /api
    paths still resolve to a JSON 404 instead of the HTML shell.
    """
    if full_path == "api" or full_path.startswith(("api/", "assets/", "logos/")) or full_path == "health":
        raise HTTPException(status_code=404, detail="Not found")
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend is not built yet")
    return FileResponse(
        index_path,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
