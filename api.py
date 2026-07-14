from __future__ import annotations

import asyncio
import hmac
import logging
import os
from functools import partial
from urllib.parse import quote, urlencode
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analysis_service import build_analysis_excel, build_analysis_pdf, build_company_comparison, build_comparison_excel, build_comparison_pdf, build_summary, report_disclaimer, run_company_analysis
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from openinfo_collector import collect_company_data, get_company_periods
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
    get_all_trade_stats,
    bulk_upsert_trade_stats,
    get_all_listings,
    bulk_upsert_listings,
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
from securities_catalog import get_securities_map, get_wiki_info, record_volume, resolve_logo, sync_securities
from web_auth import WebUser, web_auth_store

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

LOGO_DIR = Path(__file__).with_name("logos")
if LOGO_DIR.exists():
    app.mount("/logos", StaticFiles(directory=LOGO_DIR), name="logos")

UZSE_STOCK_API_BASE = os.getenv("UZSE_STOCK_API_BASE", "https://uzse-stock-production.up.railway.app").rstrip("/")


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


class AdminTradeStatsRequest(BaseModel):
    trade_date: str | None = Field(default=None, max_length=16)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminFactsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)


class AdminListingsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


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


@app.get("/api/market/stocks")
async def api_market_stocks(type: str | None = None) -> dict[str, Any]:
    security_type = (type or "").strip().lower()
    if security_type and security_type not in {"stock", "bond"}:
        raise HTTPException(status_code=400, detail="type must be stock or bond")

    try:
        response = requests.get(
            f"{UZSE_STOCK_API_BASE}/stocks",
            params={"type": security_type} if security_type else None,
            timeout=20,
        )
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
        merged.append(row)
        added_inactive += 1

    return _json_safe({
        "ok": True,
        "source": "uzse-stock-production",
        "source_url": f"{UZSE_STOCK_API_BASE}/stocks",
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "count": len(merged),
        "inactive_listings": added_inactive,
        "type": security_type or "all",
        "stocks": merged,
    })


@app.get("/api/market/trades")
async def api_market_trades() -> dict[str, Any]:
    try:
        response = requests.get(f"{UZSE_STOCK_API_BASE}/trades", timeout=20)
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
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
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
    # relate them to market caps/prices without unit knowledge.
    financials = {
        ticker: {
            **row,
            **{k: row[k] * NSBU_THOUSANDS_UZS
               for k in FIN_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }
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


@app.get("/api/coverage")
async def api_coverage() -> dict[str, Any]:
    """Data-coverage report: for every listed security, which datasets are filled.

    Shows price / volume / financials / reports coverage + resolution status and
    any sync error per ticker, plus a per-dataset summary — so gaps are visible
    and actionable instead of silent (ТЗ scalable-pipeline observability).
    """
    loop = asyncio.get_running_loop()
    try:
        response = await loop.run_in_executor(
            None, partial(requests.get, f"{UZSE_STOCK_API_BASE}/stocks", timeout=20)
        )
        response.raise_for_status()
        stocks = (response.json() or {}).get("stocks") or []
    except Exception as exc:
        logger.exception("coverage: UZSE feed failed")
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
    return _json_safe({
        "ok": True, "total": len(items), "summary": summary,
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


@app.get("/api/market/trade-stats")
async def api_market_trade_stats() -> dict[str, Any]:
    """Per-ISIN latest-day trade statistics (turnover, avg price, largest trade)."""
    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, get_all_trade_stats)
    except Exception as exc:
        logger.exception("trade-stats cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _json_safe({"ok": True, "count": len(stats), "stats": stats})


@app.get("/api/listings/feed")
async def api_listings_feed(inactive_days: int = 30) -> dict[str, Any]:
    """Listing / delisting feed (ТЗ §3.2, item 7): who recently appeared on the
    exchange and who has gone quiet (off the live feed → possible delisting). Data
    is the RFB listing registry (catalog_listings), pushed by the collector."""
    from datetime import datetime, timedelta

    loop = asyncio.get_running_loop()
    try:
        listings = await loop.run_in_executor(None, get_all_listings)
    except Exception as exc:
        logger.exception("listings feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _mk(tk: str, lst: dict[str, Any]) -> dict[str, Any]:
        return {
            "ticker": tk,
            "name": lst.get("name"),
            "isin": lst.get("isin"),
            "share_type": lst.get("share_type"),
            "listing_date": lst.get("listing_date") or None,
            "last_trade_date": lst.get("last_trade_date") or None,
            "market_cap": lst.get("market_cap"),
        }

    items = [_mk(tk, lst) for tk, lst in (listings or {}).items()]
    # Recently listed — those with a known listing date, newest first (ISO dates sort lexically).
    listed = sorted((i for i in items if i["listing_date"]), key=lambda i: i["listing_date"], reverse=True)
    # Delisting candidates — no trades within the window (off the live feed).
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
    try:
        n = await loop.run_in_executor(None, partial(bulk_upsert_financials, payload.rows, payload.form))
    except Exception as exc:
        logger.exception("admin financials upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


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
        web_auth_store.record_analysis(current_user.id, payload.model_dump(), result)
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
) -> dict[str, Any]:
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
            compare_ticker = (payload.compare_ticker or "").upper()
            compare_name = _TICKER_TO_NAME.get(compare_ticker, compare_ticker)
            if not compare_name:
                raise HTTPException(status_code=400, detail="compare_ticker is required")
            result = await loop.run_in_executor(
                None, partial(build_company_comparison, [company_name, compare_name], payload.language, True)
            )
            return _json_safe({"ok": True, "analysis_type": "multi_company", **result})

        # AI-based: financial / swot / recommendation
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


@app.get("/api/price-history/{ticker}")
async def api_price_history(ticker: str, months: int = 12) -> dict[str, Any]:
    """Close price history for a ticker via UZSE ISIN lookup."""
    import os
    import requests as _req
    from openinfo_collector import fetch_price_history

    ticker = ticker.upper()
    months = max(1, min(months, 60))
    loop = asyncio.get_running_loop()
    try:
        uzse_base = os.getenv("UZSE_STOCK_API_BASE", "https://uzse-stock-production.up.railway.app").rstrip("/")
        resp = await loop.run_in_executor(None, lambda: _req.get(f"{uzse_base}/stocks", timeout=15))
        stocks = resp.json().get("stocks", []) if resp.ok else []
        isin = next((s["isin"] for s in stocks if s.get("ticker", "").upper() == ticker), None)
        if not isin:
            return {"ok": False, "ticker": ticker, "error": "ISIN not found", "points": []}
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
        return {"ok": True, "ticker": ticker, "isin": isin, "points": points}
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
        favorites = web_auth_store.list_favorites(current_user.id)
        tickers = [f["ticker"] for f in favorites]
        if not tickers:
            return {"ok": True, "count": 0, "items": []}
        loop = asyncio.get_running_loop()
        items = await loop.run_in_executor(None, partial(get_new_reports_for_tickers, tickers, 7))
        return {"ok": True, "count": len(items), "items": _json_safe(items)}
    except Exception as exc:
        logger.exception("notifications failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
