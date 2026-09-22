from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
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
import company_imports  # noqa: E402
from company_catalog import COMPANY_CATALOG, COMPANY_SECTORS
from delisted import DELISTED_ISINS, DELISTED_TICKERS, is_delisted_isin
from financial_corrections import correction_periods_for
from openinfo_collector import collect_company_data, get_company_periods
import news_store  # noqa: E402 — §3.11 editorial-news store
from reports_catalog import (
    _TICKER_TO_NAME,
    FIN_MONEY_FIELDS,
    NSBU_THOUSANDS_UZS,
    FACT_MONEY_FIELDS,
    FIN_MONEY_FIELDS,
    get_financials_series,
    get_financials_series_quarterly,
    get_financial_value_passport,
    FACT_PERCENT_FIELDS,
    FACT_SHARE_FIELDS,
    RATIO_MONEY_FIELDS,
    build_cached_catalog_dynamics,
    build_dynamics_data,
    compute_financial_ratios,
    fetch_report_excel_data,
    get_cached_catalog_period,
    audit_financials_consistency,
    get_catalog_coverage,
    get_catalog_stats,
    get_company_index,
    get_facts,
    upsert_facts,
    get_company_reports,
    get_company_ratios_cached,
    get_all_financials,
    get_all_listings,
    get_all_ratios,
    bulk_upsert_financials,
    bulk_replace_financials,
    get_all_trade_stats,
    bulk_upsert_trade_stats,
    get_all_quotes,
    bulk_upsert_quotes,
    bulk_upsert_quote_history,
    trade_stats_as_history,
    get_quote_history,
    bulk_upsert_intraday_history,
    get_intraday_history,
    get_all_listings,
    bulk_upsert_listings,
    purge_delisted,
    refresh_financials_cache,
    get_new_reports_for_tickers,
    get_recent_filings,
    get_recent_new_reports,
    get_report_urls,
    get_sector_averages,
    list_companies_with_stats,
    upsert_ratio_cache,
    _latest_complete_fiscal_year,
    sync_company as catalog_sync_company,
    sync_all as catalog_sync_all,
)
from forecast_engine import build_forecast
from backtest import walk_forward_annual
from technical_backtest import run_sma20_backtest
from market_audit import audit_session
# ТЗ v1.2 domain layer: every formula lives in these, and nothing above them
# recomputes one. The API is serialisation and cache headers only (§11.1).
import corporate_actions  # noqa: E402
import formulas  # noqa: E402
import fundamentals  # noqa: E402
import heatmap  # noqa: E402
import instruments  # noqa: E402
import invariants  # noqa: E402
import obs  # noqa: E402
import cache_layer  # noqa: E402
import logo_store  # noqa: E402
import migrations  # noqa: E402
import bond_registry  # noqa: E402
import bonds  # noqa: E402
import provenance  # noqa: E402
import public_contract  # noqa: E402
import soliq_company  # noqa: E402 — server-only Soliq company registry client
from issuer_analysis_api import router as issuer_analysis_v1_router  # noqa: E402

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
app.include_router(issuer_analysis_v1_router)

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
    """Warm both market boards and seed the securities table after a deploy.

    The catalog table is otherwise only filled as a side effect of
    ``/api/market/stocks`` (i.e. when the Market view is opened). On Railway the
    SQLite file is ephemeral, so it is empty on every boot — which makes every
    ``/company/<ticker>`` page 404 ("no information") until someone loads Market.
    Build the stock and bond boards once in the background so both the catalog
    and the short-lived response cache are ready before the first reader arrives.
    The same single-flight cache collapses a visitor racing this warm-up into the
    in-progress build. Errors remain isolated so an unreachable mirror never
    blocks (or crashes) boot.
    """
    kinds = ("stock", "bond")
    results = await asyncio.gather(
        *(_cached_market_board(kind, refresh=True) for kind in kinds),
        return_exceptions=True,
    )
    for kind, result in zip(kinds, results):
        if isinstance(result, Exception):
            logger.error("startup market warm-up failed for type=%s: %s", kind, result)
        else:
            logger.info("startup market warm-up (%s): %d rows", kind, result.get("count", 0))


# The report catalog keeps itself current. Nothing did before: `sync_all` runs in
# the daily collector, but the collectors have no database of their own — they
# POST results to this service over HTTP, and the catalog is not among what they
# post. So `catalog_reports` only ever moved when an admin pressed
# «Синхронизировать всё». It was last pressed on 2026-07-21, and fifty issuers
# filed their half-year report after that: the site simply did not have them.
# This runs where the database is, which is also the only place that redeploys on
# a push (the cron services have no deployment trigger).
CATALOG_WATCH = os.getenv("CATALOG_WATCH", "1").strip().lower() not in {"0", "false", "no"}
CATALOG_WATCH_INTERVAL_MIN = int(os.getenv("CATALOG_WATCH_INTERVAL_MIN", "60"))
# Wider than the interval on purpose: a missed tick (restart, deploy, a failed
# request) heals on the next one instead of leaving a hole in the record.
CATALOG_WATCH_WINDOW_HOURS = int(os.getenv("CATALOG_WATCH_WINDOW_HOURS", "12"))
# The feed-driven pass cannot see an issuer we have never catalogued, and the
# audit-opinion endpoint has no per-issuer filter. The full sweep covers both.
CATALOG_FULL_SYNC_HOURS = int(os.getenv("CATALOG_FULL_SYNC_HOURS", "24"))
# How many of the longest-unsynced issuers each hourly pass also refreshes. Sixty-six
# issuers at eight an hour is a working day, and a pass this size is short enough
# that a redeploy landing on it costs almost nothing.
CATALOG_WATCH_BATCH = int(os.getenv("CATALOG_WATCH_BATCH", "8"))

# Keep the public news calendar current even when nobody has the page open.
# Client reads still have a stale-while-revalidate guard, but a scheduler is
# what makes a newly published meeting or dividend appear without depending on
# visitor traffic or the once-daily collector.
NEWS_CALENDAR_WATCH = os.getenv("NEWS_CALENDAR_WATCH", "1").strip().lower() not in {"0", "false", "no"}
NEWS_CALENDAR_WATCH_INTERVAL_MIN = int(os.getenv("NEWS_CALENDAR_WATCH_INTERVAL_MIN", "60"))


def _catalog_watch_once() -> dict[str, Any]:
    """One pass: whoever just filed, then whoever has waited longest.

    The full sweep runs when it is due, and its completion is RECORDED — a sweep
    a redeploy cut short does not count, or the issuers it never reached would
    wait another day. Everything here is bounded so that being cut short costs
    one pass, not a day.

    Blocking (openinfo HTTP + DB writes) — always called in an executor.
    """
    from datetime import datetime, timezone

    from reports_catalog import (FULL_SWEEP_KEY, full_sweep_age_hours, set_state,
                                 sync_recent_filings, sync_stale_companies)

    age = full_sweep_age_hours()
    if age is None or age >= CATALOG_FULL_SYNC_HOURS:
        result = catalog_sync_all()
        set_state(FULL_SWEEP_KEY, datetime.now(timezone.utc).isoformat())
        logger.info("catalog watch: full sweep (last %s h ago) %s",
                    None if age is None else round(age, 1),
                    {k: result.get(k) for k in ("total", "synced", "skipped")})
        return {"mode": "full", **result}

    filings = sync_recent_filings(hours=CATALOG_WATCH_WINDOW_HOURS)
    # The feed only knows who filed. An issuer that fell behind for any other
    # reason — a failed request, a pass a deploy interrupted — is caught by
    # taking the stalest few every hour, which converges without a cursor.
    stale = sync_stale_companies(limit=CATALOG_WATCH_BATCH,
                                 older_than_hours=CATALOG_FULL_SYNC_HOURS)
    if filings.get("synced") or filings.get("errors") or stale.get("synced"):
        logger.info("catalog watch: filed=%s stale=%s remaining=%s",
                    filings.get("targets"), stale.get("targets"), stale.get("remaining"))
    return {"mode": "filings", "filings": filings, "stale": stale}


async def _catalog_watch_loop() -> None:
    """Keep the report catalog level with openinfo, hourly, for as long as we run."""
    loop = asyncio.get_running_loop()
    # Let boot finish first: migrations, the delisted purge and the securities
    # seed are all in flight, and none of them should queue behind a sync.
    await asyncio.sleep(90)
    while True:
        if not _admin_catalog_sync_running.is_set():
            _admin_catalog_sync_running.set()
            try:
                await loop.run_in_executor(None, _catalog_watch_once)
            except Exception:
                logger.exception("catalog watch pass failed")
            finally:
                _admin_catalog_sync_running.clear()
        await asyncio.sleep(max(60, CATALOG_WATCH_INTERVAL_MIN * 60))


def _news_calendar_watch_once() -> dict[str, Any]:
    """Refresh both source-backed news calendars without visitor traffic."""
    import dividends as dividends_store
    import meetings as meetings_store

    result: dict[str, Any] = {"ok": True}
    for name, refresh in (("meetings", meetings_store.refresh),
                          ("dividends", dividends_store.refresh)):
        try:
            result[name] = refresh(force=True)
        except Exception as exc:  # one source must not stop the other
            logger.exception("news calendar watch failed for %s", name)
            result["ok"] = False
            result[name] = {"ok": False, "error": str(exc)}
    return result


async def _news_calendar_watch_loop() -> None:
    """Refresh after boot and then hourly (configurable) for the process lifetime."""
    loop = asyncio.get_running_loop()
    await asyncio.sleep(60)
    while True:
        await loop.run_in_executor(None, _news_calendar_watch_once)
        await asyncio.sleep(max(300, NEWS_CALENDAR_WATCH_INTERVAL_MIN * 60))


@app.on_event("startup")
async def _on_startup() -> None:
    # In-process market snapshots belong to this worker lifetime. Clearing them
    # here also prevents a test/dev app restart from inheriting an old board.
    _reset_market_board_cache()
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
    # The visit record's table lives in the same Postgres as web auth; creating
    # it is additive and idempotent. A missing DATABASE_URL only disables
    # tracking — the site itself must never depend on it.
    try:
        import web_analytics

        await asyncio.get_running_loop().run_in_executor(None, web_analytics.init_db)
    except Exception:
        logger.exception("web analytics init failed; tracking is off")
    # Fire-and-forget: seed the catalog without blocking the server from accepting
    # requests. The Market endpoint still refreshes it on demand afterwards.
    asyncio.create_task(_populate_securities_on_startup())
    if CATALOG_WATCH:
        asyncio.create_task(_catalog_watch_loop())
    if NEWS_CALENDAR_WATCH:
        asyncio.create_task(_news_calendar_watch_loop())
    if os.getenv("SECTOR_ANALYSIS_WORKER", "1") == "1":
        app.state.sector_worker = asyncio.create_task(_sector_analysis_loop())
    if os.getenv("ADMIN_CONTROL_WORKER", "1") == "1":
        app.state.admin_control_worker = asyncio.create_task(_admin_control_loop())


async def _admin_control_loop():
    """Compatibility worker; dedicated services can disable it and run the same module."""
    from admin_control import adapters, worker
    loop = asyncio.get_running_loop()
    last_indexed = 0.0
    while True:
        try:
            if loop.time() - last_indexed > 300:
                last_indexed = loop.time()
                try:
                    await loop.run_in_executor(None, adapters.refresh_catalog)
                    await loop.run_in_executor(None, adapters.refresh_analyses)
                except Exception:
                    logger.exception("Administrative indexing failed; queued jobs will still run")
            await loop.run_in_executor(None, worker.run_one)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Administrative control worker failed")
        await asyncio.sleep(2)


async def _sector_analysis_loop():
    import analysis_monitor
    while True:
        try:
            await asyncio.get_running_loop().run_in_executor(None, analysis_monitor.run_pending)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("sector analysis worker failed")
        await asyncio.sleep(30)


@app.on_event("shutdown")
async def _stop_sector_analysis_worker():
    control_task = getattr(app.state, "admin_control_worker", None)
    if control_task:
        control_task.cancel()
        try:
            await control_task
        except asyncio.CancelledError:
            pass
    task = getattr(app.state, "sector_worker", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


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
    otp: str | None = Field(default=None, max_length=12)


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


class CatalogSyncRequest(BaseModel):
    ticker: str | None = Field(default=None, max_length=40)
    force: bool = False


class AdminCompanyApproveRequest(BaseModel):
    company_name: str | None = Field(default=None, max_length=240)
    org_id: str | None = Field(default=None, max_length=80)
    isin: str | None = Field(default=None, max_length=20)
    sector: str | None = Field(default=None, max_length=40)
    logo_url: str | None = Field(default=None, max_length=1000)
    security_type: str | None = Field(default=None, max_length=40)
    share_type: str | None = Field(default=None, max_length=40)
    review_note: str | None = Field(default=None, max_length=2000)
    sync: bool = True


class AdminCompanyRejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class AdminCompanyVisibilityRequest(BaseModel):
    visible: bool


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
    # Ratios computed from the SAME two statements as the sums beside them. They
    # had no transport before, so a backfill could give the deployment nine years
    # of revenue while its ROE still came from the indicator feed — on the feed's
    # own period labels, which is exactly what was found transposed.
    ratios: list[dict[str, Any]] = Field(default_factory=list, max_length=4000)
    # "upsert" (default) keeps other stored periods; "replace" makes each row the
    # sole/authoritative period for its ticker (used by the reconciler push).
    mode: Literal["upsert", "replace"] = "upsert"


class DataCorrectionRequest(BaseModel):
    """A financial correction expressed in the catalogue's thousands-of-UZS unit."""
    ticker: str = Field(..., min_length=2, max_length=40)
    form: Literal["NSBU", "MSFO", "Audition"] = "NSBU"
    year: int = Field(..., ge=2000, le=2100)
    quarter: int = Field(default=0, ge=0, le=4)
    field: str = Field(..., min_length=1, max_length=80)
    value_thousands_uzs: float
    source_url: str = Field(..., min_length=8, max_length=2000)
    source_reference: str = Field(..., min_length=1, max_length=500)
    reason: str = Field(..., min_length=1, max_length=2000)


class DataCorrectionReviewRequest(BaseModel):
    status: Literal["approved", "rejected", "reverted"]
    note: str | None = Field(default=None, max_length=2000)


class PublicationHoldRequest(BaseModel):
    """An admin-controlled pause for one public filing period."""
    ticker: str = Field(..., min_length=2, max_length=40)
    form: Literal["NSBU", "MSFO", "Audition"] = "NSBU"
    year: int = Field(..., ge=2000, le=2100)
    quarter: int = Field(default=0, ge=0, le=4)
    active: bool = True
    reason: str = Field(..., min_length=1, max_length=2000)


class AdminTradeStatsRequest(BaseModel):
    trade_date: str | None = Field(default=None, max_length=16)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminQuotesRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    # Settled daily closes riding along with the session quotes: ~21 sessions
    # for each security the run read, so the cap is an order above `rows`.
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=40000)
    # Hourly bars from the executions log on the same pages — at most ~7 trading
    # hours per session per security, so the quotes cap times ten holds it.
    intraday: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)


class AdminFactsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=20000)


class AdminListingsRequest(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminGovAuctionsRequest(BaseModel):
    """ГЦБ auction results from the fiscal-agent page, plus the key rate the
    Central Bank's front page states — both read, never configured."""
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    key_rate: dict[str, Any] | None = None


class AdminBankFxRequest(BaseModel):
    """Commercial-bank exchange rates from bankxizmatlari.uz — 31 banks x 3
    currencies x 3 channels is under 300 rows a poll; the ceiling is headroom,
    not a real bound."""
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class AdminNewsRequest(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


class AdminNewsImagesRequest(BaseModel):
    """url → preview-image URL, for image-only updates of already-stored items.

    ``replace`` is the upgrade pass: swapping a feed's thumbnail for the full-size original
    behind it, which is the one case where an image already on a row should be overwritten.
    """
    images: dict[str, str] = Field(default_factory=dict)
    replace: bool = False


class AdminNewsSnippetsRequest(BaseModel):
    """url → replacement snippet, for enriching already-stored filings in place."""
    snippets: dict[str, str] = Field(default_factory=dict)


class AdminNewsTranslationsRequest(BaseModel):
    """url → {"en": ..., "uz": ...}, for rows stored before those columns existed."""
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)


class AdminNewsDetailsRequest(BaseModel):
    """url → {"ru": ..., "en": ..., "uz": ...} — the story page's long read.

    Our own multi-paragraph account of what the source published, written by the collector's
    detail pass from the article page. Never the source's own text.
    """
    details: dict[str, dict[str, str]] = Field(default_factory=dict)
    replace: bool = False


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


def _require_pro(current_user: WebUser = Depends(_require_user)) -> WebUser:
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
    The admin panel runs in a browser, where that secret has no business being —
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
    from admin_control.service import role_for
    if role_for(user.email) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")


def _admin_panel_gate(request: Request,
                      authorization: str | None = Header(default=None)) -> WebUser:
    """Human-only gate for product metrics, user data and account actions.

    The collector secret deliberately has no authority here.  Keeping it off
    this router is least privilege: a leaked ingestion credential must not be
    able to enumerate users or delete an account.
    """
    user = _require_user(authorization)
    from admin_control.service import role_for
    if role_for(user.email) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    request.state.admin_user = user
    return user


# The visit beacon and the panel's product metrics live in their own module;
# the admin router is gated here so every credential rule stays in one place.
import analytics_api  # noqa: E402 - needs the app and the gate above

app.include_router(analytics_api.public_router)
app.include_router(analytics_api.admin_router, dependencies=[Depends(_admin_panel_gate)])

import admin_railway  # noqa: E402 - shares the human-only administrator gate
app.include_router(admin_railway.router, dependencies=[Depends(_admin_panel_gate)])

import sector_admin_api  # noqa: E402

import admin_control.api as control_api  # noqa: E402
import v3_api  # noqa: E402


def _control_gate(request: Request, authorization: str | None = Header(default=None)):
    from admin_control.service import role_for
    from admin_control.store import ControlError
    try:
        user = _require_user(authorization)
    except HTTPException as exc:
        raise ControlError("AUTHENTICATION_REQUIRED", "Sign in with an administrative account.", exc.status_code) from None
    role = role_for(user.email)
    if not role:
        raise ControlError("PERMISSION_DENIED", "Your account does not have administrative access.", 403)
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


app.include_router(control_api.router, dependencies=[Depends(_control_gate)])
app.include_router(v3_api.router, dependencies=[Depends(_control_gate)])


def _sector_analysis_gate(request: Request, authorization: str | None = Header(default=None)):
    user = _require_user(authorization)
    role = sector_admin_api.role_for(user.email)
    if not role:
        raise HTTPException(status_code=403, detail="Your account does not have administrative access.")
    request.state.control_actor = {"id": user.id, "email": user.email.lower(), "role": role}


app.include_router(sector_admin_api.router, dependencies=[Depends(_sector_analysis_gate)])


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
    # Static entries remain the migration fallback; companies approved in the
    # admin import flow override them and append newly discovered tickers.  This
    # is the list used by search and AI analysis, so approval becomes visible
    # without editing company_catalog.py or redeploying the application.
    approved = await asyncio.get_running_loop().run_in_executor(
        None, company_imports.approved_metadata_map)
    companies: dict[str, dict[str, Any]] = {
        ticker.upper(): {
            "company_name": name,
            "ticker": ticker.upper(),
            "sector": COMPANY_SECTORS.get(ticker.upper(), "other"),
            "logo": resolve_logo(ticker, COMPANY_LOGOS) or "",
        }
        for name, ticker in COMPANY_CATALOG.items()
    }
    for ticker, item in approved.items():
        companies[ticker] = {
            "company_name": item.get("company_name") or ticker,
            "ticker": ticker,
            "sector": item.get("sector") or "other",
            "logo": item.get("logo_url") or companies.get(ticker, {}).get("logo", ""),
        }
    return {
        "ok": True,
        "count": len(companies),
        "companies": sorted(companies.values(), key=lambda item: item["ticker"]),
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
        "shares_source": "openinfo_listing",
        "nominal": corporate_actions.current_par(lst.get("ticker"), lst.get("nominal")),
        "market_cap": lst.get("market_cap"),
        "market_cap_source": "openinfo_listing",
        "market_cap_source_url": "https://openinfo.uz/",
        "market_cap_as_of": lst.get("updated_at"),
        "inactive": True,
    }


_ISSUER_NAMES: dict[str, Any] = {"at": 0.0, "map": {}}
_ISSUER_NAMES_TTL = 600.0


def _issuer_names() -> dict[str, str]:
    """ticker → issuer name, for board rows the exchange feed leaves unnamed.

    The uzse mirror carries a ``name`` for only 9 of its 78 securities, so the
    board's company column read "—" for 69 rows (every preferred share, every
    bond, and majors like UZTL). The name is not missing from our data, only from
    that one feed: openinfo's issuer catalog (``catalog_companies``, kept current
    by the collector) knows it, and the static catalog covers what predates it.

    Cached for ten minutes — the board is the hottest endpoint and issuer names
    change about never.
    """
    now = time.monotonic()
    if _ISSUER_NAMES["map"] and now - _ISSUER_NAMES["at"] < _ISSUER_NAMES_TTL:
        return _ISSUER_NAMES["map"]
    names: dict[str, str] = {t.upper(): n for n, t in COMPANY_CATALOG.items()}
    try:
        from reports_catalog import get_catalog_conn

        conn = get_catalog_conn()
        try:
            for r in conn.execute(
                    "SELECT ticker, company_name FROM catalog_companies").fetchall():
                ticker = (r["ticker"] or "").upper().strip()
                name = (r["company_name"] or "").strip()
                if ticker and name:
                    names[ticker] = name
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — the static catalog still answers
        logger.exception("issuer name catalog read failed")
    _ISSUER_NAMES.update(at=now, map=names)
    return names


_BOND_ISINS: dict[str, Any] = {"at": 0.0, "set": frozenset()}
_BOND_ISINS_TTL = 600.0


def _registered_bond_isins() -> frozenset[str]:
    """Every ISIN in the exchange's register of circulating bonds.

    Cached for ten minutes, like the issuer names above and for the same reason:
    the board is the hottest endpoint, and an issue joins the register when it is
    admitted, not within a session. An unreadable register answers with whatever
    was last read (empty on the first failure) — fail-soft, never an empty board.
    """
    now = time.monotonic()
    if _BOND_ISINS["set"] and now - _BOND_ISINS["at"] < _BOND_ISINS_TTL:
        return _BOND_ISINS["set"]
    try:
        isins = frozenset(
            str(ref.get("isin") or "").upper()
            for ref in provenance.bond_references().values() if ref.get("isin"))
    except Exception:
        logger.exception("bond register read failed; the equities board stays unfiltered")
        return _BOND_ISINS["set"]
    _BOND_ISINS.update(at=now, set=isins)
    return isins


def _retype_registered_bonds(rows: list[dict[str, Any]]) -> int:
    """Say `bond` about every row the exchange's bond register claims. In place.

    A REGISTERED BOND is never a share. IPYB2B6 — «Ipak Yo'li» AITB's 20% issue,
    admitted on 04.08.2026 — reached the equities board through the live mirror,
    which types every row it carries as a share, and its placement (100 000 bonds
    at par on 06.08) entered the board as a 104,8 млрд turnover AND the same
    figure as a capitalisation. It led «Топ ликвидности» over the whole equity
    market, and an issue has no shares to capitalise at all.

    Matched on the ISIN and never on the ticker: the RFB register files an issue
    under the ISSUER's ticker when it has none of its own, so a ticker match
    would take Aloqabank's SHARE (ALKB, UZ7044760005) off the board along with
    its bond (UZ60447611B9).

    The class is corrected rather than the row merely filtered, so it is right
    wherever the row travels — the securities catalog is synced from these rows,
    and a filter is something every future consumer has to remember to apply.
    """
    bond_isins = _registered_bond_isins()
    if not bond_isins:
        return 0
    fixed = 0
    for row in rows:
        if str(row.get("isin") or "").upper() not in bond_isins:
            continue
        if row.get("type") == "bond" and row.get("market_cap") is None:
            continue
        row["type"] = "bond"
        row["share_type"] = "bond"
        # An issue has no shares to capitalise: the figure the mirror carried
        # here was the placement's own turnover, entered a second time.
        row["shares_outstanding"] = None
        row["market_cap"] = None
        row["url"] = _exchange_url(row.get("isin"), True)
        fixed += 1
    return fixed


def _fill_names(rows: list[dict[str, Any]], names: dict[str, str]) -> int:
    """Name every row the feed left unnamed, in place. Returns rows filled.

    A preferred share with no entry of its own borrows its common sibling's name
    (UPOSP → UPOS): the same issuer, and the row's own type cell already says
    which class it is.
    """
    filled = 0
    for row in rows:
        if (row.get("name") or "").strip():
            continue
        ticker = str(row.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        name = names.get(ticker)
        if not name and ticker.endswith("P"):
            name = names.get(ticker[:-1])
        if name:
            row["name"] = name
            filled += 1
    return filled


def _carries(row: dict[str, Any], close: Any) -> bool:
    """Is the row showing no price of its own but carrying exactly this close?"""
    if row.get("last_price") is not None:
        return False
    try:
        carried, quoted = float(row.get("close_price")), float(close)
    except (TypeError, ValueError):
        return False
    scale = max(abs(carried), abs(quoted))
    return scale == 0 or abs(carried - quoted) / scale <= 1e-9


def _apply_quote(row: dict[str, Any], quote: dict[str, Any]) -> None:
    """Overlay the exchange's session quote on a board row, in place.

    The row's own session decides: a quote is applied only when it is at least as
    recent as what the row already shows, so a stored quote for a security that
    has since gone quiet cannot pull a live row backwards. ``close_date`` counts
    as the row's session even with no trade — the exchange carries the closing
    price forward, and that carried price is newer than an older real trade.

    A carried close is the last trade's close, though — the exchange repeats it,
    it does not restate it. So when the mirror carries no price of its own and
    the close it is carrying is the close our quote names, that quote IS the
    session behind it, and waiting for a newer one leaves the row with a date it
    cannot explain and no price at all. Eight rows sat like that (UTGA, UZML,
    TRSBP, TKDMP, FRAZP, UPOSP and two bonds) while uzse.uz dated and priced
    every one of them. A carried close that DIFFERS is a session the mirror knows
    and the quote does not, and there the quote still waits.
    """
    day = _iso_trade_date(quote.get("trade_date"))
    close = quote.get("close_price")
    if not day or close is None:
        return
    row_day = _iso_trade_date(row.get("last_trade_date"))
    if not row_day and not _carries(row, close):
        row_day = _iso_trade_date(row.get("close_date"))
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


def _exchange_url(isin: Any, is_bond: bool) -> str | None:
    """The exchange's own page for a security — the board's «источник» link.

    One shape, one place: rows reached the board from three sources and only two
    of them built this link, so the source column was empty for every row the
    live mirror carried (it sends ``url: null``).
    """
    code = str(isin or "").strip().upper()
    if not code:
        return None
    return f"https://uzse.uz/isu_infos/{'BND' if is_bond else 'STK'}?isu_cd={code}"


def _fill_source_urls(rows: list[dict[str, Any]]) -> int:
    """Give every row with an ISIN its exchange link, in place. Returns rows filled."""
    filled = 0
    for row in rows:
        if str(row.get("url") or "").strip():
            continue
        url = _exchange_url(row.get("isin"), str(row.get("type") or "").lower() == "bond")
        if url:
            row["url"] = url
            filled += 1
    return filled


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
        "url": _exchange_url(isin, is_bond),
    }


async def _build_board(security_type: str = "") -> dict[str, Any]:
    """The market board: the live feed, the listing registry and the exchange's
    own quotes merged into one set of rows.

    Extracted from the endpoint so every consumer sees the SAME board. /api/coverage
    used to report on the raw mirror instead, which made it structurally blind to the
    securities the mirror does not carry — the gap it exists to surface.
    """

    loop = asyncio.get_running_loop()
    mirror_available = True
    try:
        # Executor-wrapped: a sync HTTP call here stalled the whole event loop
        # (single worker) for up to 20s on the hottest endpoint.
        response = await loop.run_in_executor(None, partial(
            requests.get,
            f"{UZSE_STOCK_API_BASE}/stocks",
            params={"type": security_type} if security_type else None,
            timeout=20,
        ))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        logger.warning("UZSE stock API unavailable; using stored listings and quotes: %s", exc)
        mirror_available = False
        payload = {}
    except ValueError as exc:
        logger.warning("UZSE stock API returned invalid JSON; using stored listings and quotes: %s", exc)
        mirror_available = False
        payload = {}

    stocks = payload.get("stocks") if isinstance(payload, dict) else []
    stocks_list = stocks if isinstance(stocks, list) else []

    # Name the rows the feed leaves unnamed BEFORE the catalog sync below, so the
    # securities table (and everything reading it — company pages, search, logos)
    # stores the name too instead of the feed's null.
    # Both reads are memoised; warming them off-thread is what keeps the single
    # worker's event loop free — the two callers below then hit the cache.
    issuer_names, _ = await asyncio.gather(
        loop.run_in_executor(None, _issuer_names),
        loop.run_in_executor(None, _registered_bond_isins),
    )
    _fill_names(stocks_list, issuer_names)
    # Before the sync below: the securities catalog is written from these rows,
    # so a bond the mirror called a share would be catalogued as one.
    _retype_registered_bonds(stocks_list)
    _fill_source_urls(stocks_list)

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
        # These are SQLite-backed cache reads. Never perform them on the
        # event-loop thread: a collector holding the database lock otherwise
        # freezes every route (including /health), not just the market page.
        listings = await loop.run_in_executor(None, get_all_listings)
    except Exception:
        logger.exception("market/stocks: listings merge read failed")
        listings = {}
    catalog: dict[str, dict] = {}
    if listings:
        try:
            catalog = await loop.run_in_executor(None, get_securities_map)
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
    # The par value comes only from the registry — the live feed does not carry it
    # — so it is joined for EVERY row, including the ones that already have a
    # capitalisation and skip the loop below.
    for row in merged:
        if row.get("nominal") is None:
            lst = (listings.get(str(row.get("ticker") or "").upper())
                   or listings_by_isin.get(str(row.get("isin") or "").upper()))
            if lst and lst.get("nominal") is not None:
                row["nominal"] = lst["nominal"]
        row["nominal"] = corporate_actions.current_par(row.get("ticker"), row.get("nominal"))
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
            row["shares_source"] = "openinfo_listing"
        price = row.get("last_price") or row.get("close_price")
        if shares and price:
            row["market_cap"] = shares * price
        elif lst.get("market_cap"):
            row["market_cap"] = lst.get("market_cap")
            row["market_cap_source"] = "openinfo_listing"
            row["market_cap_source_url"] = "https://openinfo.uz/"
            row["market_cap_as_of"] = lst.get("updated_at")

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
        # source column links to uzse.uz. (Live-feed rows get theirs below; the
        # mirror sends url=null for all of them.)
        if not row.get("url"):
            row["url"] = _exchange_url(row.get("isin"), is_bond)
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
        quotes = await loop.run_in_executor(None, get_all_quotes)
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
        _fill_names(quoted_rows, issuer_names)
        _fill_source_urls(quoted_rows)
        if quoted_rows:
            loop.run_in_executor(None, partial(sync_securities, quoted_rows, _load_logos()))

    # Drop board-suppressed tickers (dormant registry lines) from the view. Applied
    # to the fully merged list so it holds regardless of source (live feed, the
    # inactive registry merge or the quote cache above); data itself is left
    # untouched. The ISIN is tested as well as the ticker because a quote-cache row
    # may have no ticker to test — that is how UZAL2 returned as a nameless tile
    # once its registry line was purged.
    if BOARD_DENYLIST or DELISTED_ISINS:
        merged = [r for r in merged
                  if str(r.get("ticker") or "").upper() not in BOARD_DENYLIST
                  and not is_delisted_isin(r.get("isin"))]
        added_inactive = sum(1 for r in merged if r.get("inactive"))

    # Again on the merged list: the registry and the quote cache append rows of
    # their own after the sync above, and the market-cap join runs over all of
    # them. The equities view then loses them; the «all» view keeps them, because
    # it is the everything board and they now say on it what they are.
    _retype_registered_bonds(merged)
    if security_type == "stock":
        bond_isins = await loop.run_in_executor(None, _registered_bond_isins)
        if bond_isins:
            merged = [r for r in merged
                      if str(r.get("isin") or "").upper() not in bond_isins]
            added_inactive = sum(1 for r in merged if r.get("inactive"))

    # Registry and quote-cache rows joined the board after the first pass; name
    # them too, so no row reaches the company column as a bare ISIN.
    _fill_names(merged, issuer_names)
    _fill_source_urls(merged)

    return _json_safe({
        "ok": True,
        "source": ("uzse-stock-production" if mirror_available
                   else "stored-openinfo-listings+uzse-quotes"),
        "source_url": f"{UZSE_STOCK_API_BASE}/stocks",
        # The mirror stamps naive UTC; say so, or the browser reads it as local.
        "updated_at": _as_utc_iso(payload.get("updated_at")) if isinstance(payload, dict) else None,
        "count": len(merged),
        "inactive_listings": added_inactive,
        "type": security_type or "all",
        "stocks": merged,
    })


MARKET_BOARD_CACHE_TTL_SEC = max(
    0, int(os.getenv("MARKET_BOARD_CACHE_TTL_SEC", "60")),
)
MARKET_BOARD_BROWSER_TTL_SEC = max(
    0, int(os.getenv("MARKET_BOARD_BROWSER_TTL_SEC", "15")),
)
_MARKET_BOARD_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MARKET_BOARD_LOCKS: dict[str, asyncio.Lock] = {}


def _reset_market_board_cache() -> None:
    """Drop process-local board snapshots and loop-bound locks."""
    _MARKET_BOARD_CACHE.clear()
    _MARKET_BOARD_LOCKS.clear()


async def _cached_market_board(security_type: str, *, refresh: bool = False) -> dict[str, Any]:
    """Reuse a recently assembled board and collapse concurrent cold requests."""
    now = time.monotonic()
    cached = _MARKET_BOARD_CACHE.get(security_type)
    if not refresh and cached and now - cached[0] < MARKET_BOARD_CACHE_TTL_SEC:
        return cached[1]

    observed_at = cached[0] if cached else None
    lock = _MARKET_BOARD_LOCKS.setdefault(security_type, asyncio.Lock())
    async with lock:
        current = _MARKET_BOARD_CACHE.get(security_type)
        if current and (observed_at is None or current[0] > observed_at):
            return current[1]
        if not refresh and current and time.monotonic() - current[0] < MARKET_BOARD_CACHE_TTL_SEC:
            return current[1]

        payload = await _build_board(security_type)
        _MARKET_BOARD_CACHE[security_type] = (time.monotonic(), payload)
        return payload


@app.get("/api/market/stocks")
async def api_market_stocks(request: Request, type: str | None = None,
                            refresh: bool = False) -> Response:
    security_type = (type or "").strip().lower()
    if security_type and security_type not in {"stock", "bond"}:
        raise HTTPException(status_code=400, detail="type must be stock or bond")
    payload = await _cached_market_board(security_type, refresh=refresh)
    return _etag_json(
        request,
        payload,
        max_age=0 if refresh else MARKET_BOARD_BROWSER_TTL_SEC,
    )


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

    from datetime import datetime, timedelta, timezone

    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    # Which session is still being traded, in the exchange's own time — a run at
    # 13:00 audits a day that is still adding executions, and the two sides are
    # read minutes apart (see market_audit.audit_session).
    today = datetime.now(timezone(timedelta(hours=5))).strftime("%Y%m%d")
    return _json_safe(audit_session(stats, quotes, board,
                                    denylist=BOARD_DENYLIST, today=today))


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
async def api_market_financials(ticker: str | None = None) -> dict[str, Any]:
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

    def _with_companions(row: dict[str, Any]) -> dict[str, Any]:
        out = _scaled(row)
        # Both companions are money in the same thousands, so both scale with the
        # row. `prior` is the comparative the filing itself prints for the year
        # before — the year-on-year denominator.
        for key in ("annual", "prior"):
            if row.get(key):
                out[key] = _scaled(row[key])
        return out

    financials = {ticker: _with_companions(row) for ticker, row in financials.items()}
    if ticker:
        requested = ticker.strip().upper()
        sibling = requested[:-1] if requested.endswith("P") else f"{requested}P"
        financials = {
            key: value for key, value in financials.items()
            if str(key).upper() in {requested, sibling}
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
    ratio coefficients of the §3.8 tabular reports.

    Two exclusions by the 2026-08-10 audit: ``debt_to_equity`` left the
    storefront entirely (лист 06 — 47 of 99 values reproduced under no formula,
    the units were mixed and for banks the number was meaningless), and bond
    tickers are not served (V17 — ten bond issues were inheriting their
    issuer's ROE/ROA as if a coupon security had a return on equity).

    Beside ROE/ROA/current ratio this also serves the published coefficients the
    company page's «Коэффициенты» card already shows — quick ratio, debt/assets,
    asset turnover and ROCE — in the units the issuer published them in
    (debt/assets a percent, the rest bare). ``periods`` names the reporting year
    of each field on its own: one issuer can file liquidity for 2023 and ROE for
    2025, and the single ``period`` above is only the newest of them.
    """
    loop = asyncio.get_running_loop()
    try:
        ratios = await loop.run_in_executor(None, get_all_ratios)
        securities = await loop.run_in_executor(None, get_securities_map)
    except Exception as exc:
        logger.exception("ratios cache read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bonds = {t for t, meta in (securities or {}).items()
             if str((meta or {}).get("type") or "").lower() == "bond"}
    # Absolute sums (equity/assets) are stored in thousands of UZS; serve full
    # UZS so P/B = market_cap / total_equity divides like units.
    ratios = {
        ticker: {
            **{k: v for k, v in row.items() if k != "debt_to_equity"},
            # The withheld field must not survive in the period map either.
            "periods": {k: v for k, v in (row.get("periods") or {}).items()
                        if k != "debt_to_equity"},
            **{k: row[k] * NSBU_THOUSANDS_UZS
               for k in RATIO_MONEY_FIELDS if isinstance(row.get(k), (int, float))},
        }
        for ticker, row in ratios.items()
        if str(ticker).upper() not in bonds
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


# The 12-month earnings base used to be selected here (_earnings_for: the last
# complete fiscal year, else the raw cumulative quarter). ТЗ мультипликаторов
# (2026-08-10) replaced that with the TTM assembly — годовая величина + YTD
# текущего года − YTD прошлого года — which lives in
# fundamentals.twelve_month_flows and runs inside issuer_multiples, so the
# selection is no longer a caller's choice.


async def _market_inputs(ticker: str | None = None) -> dict[str, Any]:
    """Board, catalog, statements and ratios — fetched once, shared by every
    screen below so they cannot disagree about what exists."""
    loop = asyncio.get_running_loop()
    requested = str(ticker or "").strip().upper()
    if requested:
        # A company page needs one equity issuer, not a fresh rebuild of both
        # market boards. The stock board is already warmed on startup and its
        # short cache is the same snapshot the page header reads.
        shares = await _cached_market_board("stock")
        bonds = {"stocks": []}
    else:
        # The market landing page requests several dependent endpoints in
        # parallel (instruments, summary and multiples).  Sending each one to
        # _build_board made a single first visit issue six identical remote
        # /stocks calls, which could exhaust the proxy timeout when the feed or
        # SQLite was briefly slow.  The board cache is lock-coalesced, so all
        # readers now share the same stock and bond snapshots for its short TTL.
        shares, bonds = await asyncio.gather(
            _cached_market_board("stock"), _cached_market_board("bond"),
        )
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
    # The nested blocks that ride on a row — the filing's own comparative
    # (``prior``, the TTM subtrahend) and the filed balance (``balance``, the
    # P/B and ROE denominators) — carry the same thousands and must cross the
    # boundary together, or the TTM would subtract thousands from full UZS.
    def _scale(row: dict[str, Any], fields) -> dict[str, Any]:
        out = {**row, **{k: row[k] * NSBU_THOUSANDS_UZS
                         for k in fields if isinstance(row.get(k), (int, float))}}
        prior = row.get("prior")
        if isinstance(prior, dict):
            out["prior"] = {**prior, **{k: prior[k] * NSBU_THOUSANDS_UZS
                                        for k in fields
                                        if isinstance(prior.get(k), (int, float))}}
        balance = row.get("balance")
        if isinstance(balance, dict):
            out["balance"] = {k: (v * NSBU_THOUSANDS_UZS
                                  if isinstance(v, (int, float)) else v)
                              for k, v in balance.items()}
        return out

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
    if requested:
        catalog_rows = [
            {"ticker": str(key).upper(), **(value or {})}
            for key, value in securities.items()
        ]
        issuer_tickers = next((
            {str(row.get("ticker") or "").upper() for row in rows}
            for rows in fundamentals.group_by_issuer(catalog_rows).values()
            if any(str(row.get("ticker") or "").upper() == requested for row in rows)
        ), {requested})
        board = [row for row in board
                 if str(row.get("ticker") or "").upper() in issuer_tickers]
        securities = {key: value for key, value in securities.items()
                      if str(key).upper() in issuer_tickers}
        financials = {key: value for key, value in financials.items()
                      if str(key).upper() in issuer_tickers}
        ratios = {key: value for key, value in ratios.items()
                  if str(key).upper() in issuer_tickers}
        listings = {key: value for key, value in listings.items()
                    if str(key).upper() in issuer_tickers}
        stats = {key: value for key, value in stats.items()
                 if str(key).upper() in issuer_tickers}
    return {"board": board, "securities": securities, "financials": financials,
            "ratios": ratios, "listings": listings, "stats": stats,
            "trade_date": trade_date.isoformat() if trade_date else None}


async def _heatmap_inputs() -> dict[str, Any]:
    """The small, bounded data set a heatmap actually needs.

    The map previously reused ``_market_inputs`` and therefore loaded every
    financial statement, ratio and listing merely to draw price tiles. Besides
    delaying the first paint, those extra SQLite reads could block the single
    web worker during a collector write. Keep the map independent: board,
    security metadata and today's trade statistics are its whole contract.
    """
    loop = asyncio.get_running_loop()
    # Keep the heatmap in the same coalesced board snapshot as the rest of the
    # landing page.  Its small SQLite input set remains deliberately separate.
    shares, bonds = await asyncio.gather(
        _cached_market_board("stock"), _cached_market_board("bond"),
    )
    securities, stats = await asyncio.gather(
        loop.run_in_executor(None, get_securities_map),
        loop.run_in_executor(None, get_all_trade_stats),
    )
    board = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    trade_date = None
    for row in board:
        day = instruments._norm_day(row.get("last_trade_date"))
        if day and (trade_date is None or day > trade_date):
            trade_date = day
    return {"board": board, "securities": securities, "stats": stats,
            "trade_date": trade_date.isoformat() if trade_date else None}


def _multiples_payload(inputs: dict[str, Any]) -> dict[str, Any]:
    """Issuer-level multiples for every listed share class (ТЗ §8)."""
    securities, financials, ratios = (inputs["securities"], inputs["financials"],
                                      inputs["ratios"])
    listings = inputs.get("listings") or {}
    board_by_ticker = {str(r.get("ticker") or "").upper(): r for r in inputs["board"]}

    # Share classes are grouped by issuer using the catalog, enriched with the
    # board's capitalisation and share count for each class.
    #
    # V9 (ТЗ мультипликаторов): a class that has never traded carries a price
    # taken from the registry's nominal/reference, and a capitalisation built
    # on a nominal is fiction — UZIN at 1 000, UZNG at 500, TGBK at 5 000 all
    # produced fictitious caps and the P/E, P/B chain downstream of them. Such
    # a class contributes NO capitalisation: the issuer's cap either comes from
    # classes that actually traded or is honestly incomplete.
    def _market_input(ticker: str, row: dict[str, Any], shares: Any) -> dict[str, Any]:
        listing = listings.get(ticker) or {}
        if listing.get("market_cap"):
            shares = listing.get("shares_outstanding") or shares
            row = {
                **listing,
                **row,
                "ticker": ticker,
                "shares_outstanding": (listing.get("shares_outstanding")
                                       or row.get("shares_outstanding")),
                "shares_source": "openinfo_listing",
                "market_cap": listing["market_cap"],
                "market_cap_source": "openinfo_listing",
                "market_cap_source_url": "https://openinfo.uz/",
                "market_cap_as_of": listing.get("updated_at"),
            }
        if not row:
            return public_contract.market_class_input({}, shares_outstanding=shares)
        return public_contract.market_class_input(row, shares_outstanding=shares)

    catalog_rows = []
    for ticker, meta in (securities or {}).items():
        row = board_by_ticker.get(str(ticker).upper()) or {}
        shares = row.get("shares_outstanding") or meta.get("shares_outstanding")
        market_input = _market_input(str(ticker).upper(), row, shares)
        catalog_rows.append({
            "ticker": str(ticker).upper(), **meta,
            "market_cap": market_input["market_cap"],
            "last_price": market_input["price"],
            "last_trade_date": market_input["price_as_of"],
            "shares_outstanding": market_input["shares_outstanding"],
            "market_input": market_input,
        })
    # Board rows with no catalog card yet (ТЗ мультипликаторов, лист 15: EQQU
    # traded actively while its filings sat unread because the multiples
    # universe was the catalog alone). The board row itself carries everything
    # the grouping needs — name, class, cap — so the issuer appears on the
    # multiples screen the day it appears on the board, and the missing card
    # remains a catalog-sync task rather than a blank row.
    known = {str(t).upper() for t in (securities or {})}
    for ticker, row in board_by_ticker.items():
        if not ticker or ticker in known:
            continue
        market_input = _market_input(ticker, row, row.get("shares_outstanding"))
        catalog_rows.append({
            "ticker": ticker,
            "name": row.get("name"),
            "type": row.get("type") or "stock",
            "share_type": row.get("share_type"),
            "is_preferred": row.get("is_preferred"),
            "market_cap": market_input["market_cap"],
            "last_price": market_input["price"],
            "last_trade_date": market_input["price_as_of"],
            "shares_outstanding": market_input["shares_outstanding"],
            "market_input": market_input,
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
        multiples = fundamentals.issuer_multiples(classes, fin, rat)
        multiples = public_contract.multiplier_contract(
            multiples, classes, fin, rat, market_as_of=inputs.get("trade_date"))
        by_issuer[key] = {"tickers": tickers, "multiples": multiples}
        for cls in classes:
            rows.append({
                "ticker": cls["ticker"],
                "issuer": key,
                "issuer_classes": tickers,
                "share_class": "preferred" if cls.get("is_preferred") else "ordinary",
                # Class-specific, by design (ТЗ §8).
                "market_cap_class": cls.get("market_cap"),
                "market_input": cls.get("market_input"),
                # Issuer-level, identical across the classes above.
                **{k: v for k, v in multiples.items()},
            })
    rows.sort(key=lambda r: r["ticker"])
    _apply_audit_blocks(rows)
    return {"ok": True, "count": len(rows), "issuers": len(groups),
            "contract_version": public_contract.CONTRACT_VERSION,
            "input_snapshot": public_contract.market_inputs_version(inputs),
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
                row[metric] = {**current, "value": None, "status": "audit_blocked",
                               "calculation_status": public_contract.DATA_CONFLICT,
                               "note": "значение снято аудитором данных",
                               "limitation_reason": "значение снято аудитором данных",
                               "audit_metric": metric}
                blocked += 1
    return blocked


@app.get("/api/market/multiples")
async def api_market_multiples(request: Request, ticker: str | None = None) -> Response:
    """P/E, P/B, ROE, ROA, margin and D/E — computed once, per ISSUER.

    Both classes of an issuer receive identical values by construction; only
    price, change, volume and the class's own capitalisation differ. This is the
    endpoint that makes KFSK 203.6 / KFSKP 0.19 impossible.
    """
    trace = obs.Trace(endpoint="market/multiples")
    try:
        requested = str(ticker or "").strip().upper() or None
        inputs = await _market_inputs(requested)
        trace.step("inputs", instruments=len(inputs["board"]),
                   financials=len(inputs["financials"]), ratios=len(inputs["ratios"]))
        # The session date alone is insufficient: a corrected statement or
        # share count can arrive before the next trade.  The dependency hash
        # makes that correction miss the old cache immediately.
        input_version = public_contract.market_inputs_version(inputs)
        cache_key = cache_layer.key(f"market:multiples:{requested or 'all'}", inputs["trade_date"] or "none",
                                    input_version)
        payload = cache_layer.cached(cache_key, lambda: _multiples_payload(inputs))
        if requested:
            selected = [row for row in payload["items"]
                        if str(row.get("ticker") or "").upper() == requested]
            issuer_keys = {row.get("issuer") for row in selected}
            payload = {
                **payload,
                "count": len(selected),
                "issuers": len(issuer_keys),
                "items": selected,
                "by_issuer": {
                    key: value for key, value in payload.get("by_issuer", {}).items()
                    if key in issuer_keys
                },
            }
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


# The periods the board can measure a change over, in calendar days back from the
# last settled session. Calendar, not sessions: «за неделю» means the price seven
# days ago, and on a market where a security can go a fortnight without a trade,
# counting sessions would call a three-month-old price a week old. YTD carries no
# span — its base is 1 January, however far back that is today.
MARKET_CHANGE_WINDOWS: dict[str, int | None] = {
    "1w": 7, "1m": 30, "3m": 91, "6m": 182, "1y": 365, "ytd": None,
}


def _window_change(points: list[dict[str, Any]], span_days: int | None,
                   as_of: date) -> dict[str, Any] | None:
    """The change from the price ``span_days`` ago to the latest close.

    The base is the LAST close at or before the cutoff — the price the security
    was worth then — not the first close after it. On a market where a security
    can go weeks without a trade the two are wildly different things: the first
    close inside a seven-day window is routinely yesterday's, which would print a
    one-session move under a label that says a week.

    A carried-forward close (the store's turnover 0) is a legitimate base: it is
    what the security was last worth, and it is what the exchange itself shows.
    Where the store reaches no further back than the cutoff there is no base and
    no figure — an issuer whose history starts inside the window has not moved
    over it, it simply was not there.
    """
    if not points:
        return None
    cutoff = date(as_of.year, 1, 1) if span_days is None else as_of - timedelta(days=span_days)
    if cutoff >= as_of:
        return None
    base = None
    for p in points:
        if p["d"] <= cutoff:
            base = p
        else:
            break
    last = points[-1]
    if base is None or last is base or not base["close"]:
        return None
    return {"pct": round((last["close"] - base["close"]) / abs(base["close"]) * 100.0, 2),
            "from": base["date"], "base": base["close"]}


def _window_stats(points: list[dict[str, Any]], span_days: int | None,
                  as_of: date) -> dict[str, Any] | None:
    """What the security DID over the window, stated the way a session is stated.

    The board could summarise one day — open, high, low, turnover in сумы and in
    bumagi, the average share price, the average deal, the biggest deal — and for
    any longer period it could only offer a percent, because a period's figures
    were a sum nobody held. They are held now: every settled session is banked
    per security, with its own open/high/low, deal count and largest deal beside
    the close, so «за месяц» is thirty sessions added up rather than one session
    reprinted under a heading that says a month.

    Only sessions the security actually TRADED in are counted. The exchange
    repeats a close at zero quantity when nothing traded, and a carried-forward
    day is not a small session: adding it would change no sum but it would make
    ``sessions`` claim activity that did not happen, and ``sessions`` is what
    tells a reader whether «5,6 млрд за полгода» is eighty sessions or three.

    The window is the same half-open span the change over it uses — everything
    strictly after the cutoff, through the latest session — so a figure and the
    percent beside it describe the same stretch of calendar.

    Every field answers or is absent; nothing is estimated to fill a column.
    Where a banked session carries no high/low (openinfo's archive reaches
    further back than the day statistics do) the session's close stands in for
    it — a real traded price of that session, and a bound the true extreme can
    only be wider than — and ``approx`` says so, so the interface can mark it.
    """
    if not points:
        return None
    cutoff = date(as_of.year, 1, 1) if span_days is None else as_of - timedelta(days=span_days)
    if cutoff >= as_of:
        return None
    inside = [p for p in points if p["d"] > cutoff]
    traded = [p for p in inside if (p.get("turnover") or 0) > 0 or (p.get("quantity") or 0) > 0]
    if not traded:
        return None
    total = sum(p.get("turnover") or 0.0 for p in traded)
    qty = sum(p.get("quantity") or 0.0 for p in traded)
    # Sessions banked with the day statistics beside them — the ones that can say
    # how many deals they were made of and which was the biggest. openinfo's
    # archive reaches further back than those statistics do, so over a year this
    # is routinely a SUBSET, and the average deal must be computed inside it:
    # the whole window's сумы over part of the window's deals would overstate the
    # average by exactly the sessions it could not see.
    counted = [p for p in traded if p.get("trade_count") is not None]
    trades = sum(int(p["trade_count"]) for p in counted) if counted else None
    counted_value = sum(p.get("turnover") or 0.0 for p in counted)
    highs = [p.get("high") if p.get("high") is not None else p.get("close") for p in traded]
    lows = [p.get("low") if p.get("low") is not None else p.get("close") for p in traded]
    highs = [h for h in highs if h is not None]
    lows = [low for low in lows if low is not None]
    first = traded[0]
    last = traded[-1]
    biggest = max((p for p in traded if p.get("largest_value") is not None),
                  key=lambda p: p["largest_value"], default=None)
    out: dict[str, Any] = {
        "value": round(total),
        "sessions": len(traded),
        "from": first["date"],
        "to": last["date"],
        # The period's opening price is the first session INSIDE it that traded —
        # its own open where the session was banked with one, its close where it
        # was not. Not the base the percent is measured from: that close belongs
        # to a session before the window, and a period's open is a price the
        # period itself printed.
        "open": first.get("open") if first.get("open") is not None else first.get("close"),
        "close": last.get("close"),
    }
    if qty > 0:
        out["qty"] = round(qty)
        # Средневзвешенная по объёму цена периода: what the whole window's сумы
        # bought, divided by the bumagi they bought. Over one session this is the
        # session VWAP the column already shows, which is the point.
        if total > 0:
            out["vwap"] = round(total / qty, 2)
    if highs:
        out["high"] = round(max(highs), 2)
    if lows:
        out["low"] = round(min(lows), 2)
    if trades:
        out["trades"] = trades
        if counted_value > 0:
            out["avg_trade"] = round(counted_value / trades)
    if biggest is not None:
        out["largest_value"] = round(biggest["largest_value"])
        if biggest.get("largest_qty") is not None:
            out["largest_qty"] = round(biggest["largest_qty"])
        if total > 0:
            out["largest_pct"] = round(biggest["largest_value"] / total * 100, 2)
        out["largest_from"] = biggest["date"]
    # How much of the window those two figures actually saw. Only when it is less
    # than the whole: the deal count and the largest deal are then a floor and the
    # interface says so, rather than printing a partial answer as a complete one.
    if counted and len(counted) < len(traded):
        out["detail_sessions"] = len(counted)
    # True session extremes are banked only for the sessions the day statistics
    # or openinfo's archive could see. Where some session inside the window stood
    # in with its close, the high and low are bounds and the interface says so.
    if any(p.get("high") is None or p.get("low") is None for p in traded):
        out["approx"] = True
    return out


@app.get("/api/market/changes")
async def api_market_changes(request: Request) -> Response:
    """Per-security price change over each period the board offers.

    The board's «Изменение» column measured one thing — the session — so a reader
    who wanted to know what a week or a month had done had to open every company
    page in turn. These are the same closes the sparklines are drawn from
    (`catalog_quote_history`), so the column and the chart cannot disagree.

    Every figure names the session its base came from: a change is a statement
    about two dates, and on this market the earlier one is rarely the date the
    label implies. The client shows it in the cell's tooltip.
    """
    loop = asyncio.get_running_loop()
    try:
        smap = await loop.run_in_executor(None, get_securities_map)
        isin_of = {t: str((meta or {}).get("isin") or "").upper()
                   for t, meta in (smap or {}).items()}
        codes = sorted({i for i in isin_of.values() if i})
        # 400 sessions is over a year of trading for even the most liquid line,
        # and many more for a quiet one — get_quote_history counts sessions, not
        # days, precisely so a security that rarely trades still answers.
        history = await loop.run_in_executor(None, partial(get_quote_history, codes, 400))
    except Exception as exc:
        logger.exception("market changes failed")
        raise HTTPException(status_code=502, detail="changes unavailable") from exc

    ticker_of = {isin: ticker for ticker, isin in isin_of.items() if isin}
    series: dict[str, list[dict[str, Any]]] = {}
    for isin, rows in history.items():
        # Back-adjusted for splits and bonus issues FIRST. The stored closes are
        # what the exchange printed on the day, and a window spanning ALSM's 2025
        # recapitalisation (one April share is three of today's) would otherwise
        # report a 40 % collapse to a holder who had in fact gained. This is the
        # same restatement the price chart applies; the two must not disagree.
        rows, _applied = corporate_actions.adjust_history(
            rows, ticker_of.get(isin), isin, date_key="trade_date",
            price_fields=("close_price", "open_price", "high_price", "low_price"))
        points = []
        for r in rows:
            close = formulas.to_number(r.get("close_price"))
            stamp = str(r.get("trade_date") or "")
            if close is None or len(stamp) != 8 or not stamp.isdigit():
                continue
            # Turnover rides along on the same point. It is money, so the split
            # restatement above must not touch it — a сум in April is a сум now,
            # whatever happened to the share count in between.
            points.append({"d": date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8])),
                           "date": stamp, "close": close,
                           # Prices, so the split restatement above applies to
                           # them exactly as it does to the close: a window
                           # spanning a recapitalisation must report one unit.
                           "open": formulas.to_number(r.get("open_price")),
                           "high": formulas.to_number(r.get("high_price")),
                           "low": formulas.to_number(r.get("low_price")),
                           "quantity": formulas.to_number(r.get("quantity")),
                           "trade_count": formulas.to_number(r.get("trade_count")),
                           # Money and share counts. The split restatement must
                           # NOT touch these — a сум in April is a сум now,
                           # whatever happened to the share count in between.
                           "largest_value": formulas.to_number(r.get("largest_value")),
                           "largest_qty": formulas.to_number(r.get("largest_qty")),
                           "turnover": formulas.to_number(r.get("turnover"))})
        if points:
            series[isin] = sorted(points, key=lambda p: p["d"])

    changes: dict[str, dict[str, Any]] = {}
    for ticker, isin in isin_of.items():
        points = series.get(isin)
        if not points:
            continue
        as_of = points[-1]["d"]
        row = {code: _window_change(points, span, as_of)
               for code, span in MARKET_CHANGE_WINDOWS.items()}
        row = {k: v for k, v in row.items() if v}
        # The window's own session figures, under their own key rather than beside
        # `pct` in each window's object: a security can have traded over a month
        # without having a base close a month back (its history starts inside the
        # window), and the volume columns must still answer. Keeping the two
        # independent is what lets each answer when the other cannot.
        stats = {code: _window_stats(points, span, as_of)
                 for code, span in MARKET_CHANGE_WINDOWS.items()}
        stats = {k: v for k, v in stats.items() if v}
        if row or stats:
            row["as_of"] = points[-1]["date"]
            if stats:
                row["stats"] = stats
                # `turnover` is the same sum under the key the liquidity panel
                # has read since 2026-08-18. Kept so a client that has not been
                # redeployed alongside this one keeps its panel.
                row["turnover"] = {code: {"value": st["value"], "sessions": st["sessions"],
                                          "from": st["from"]}
                                   for code, st in stats.items()}
            changes[ticker] = row
    return _etag_json(request, {"ok": True, "windows": list(MARKET_CHANGE_WINDOWS),
                               "count": len(changes), "changes": changes}, max_age=300)


# Official daily exchange rates. cbu.uz publishes them as JSON — no scraping —
# and sets them once per business day, so a half-hour in-process cache keeps the
# site current without leaning on the bank's server. A failed refresh serves the
# last good answer: yesterday's official rate stays official until the bank
# publishes the next one.
CBU_RATES_URL = "https://cbu.uz/uz/arkhiv-kursov-valyut/json/"
CBU_RATES_TTL_SEC = int(os.getenv("CBU_RATES_TTL_SEC", "1800"))
CBU_RATES_CURRENCIES = tuple(
    c.strip().upper()
    # GBP/CNY/JPY/KZT were dropped at the customer's request (2026-08-12);
    # the env var can widen the set back without a code change.
    for c in os.getenv("CBU_RATES_CURRENCIES", "USD,EUR,RUB").split(",")
    if c.strip())
_cbu_rates_cache: dict[str, Any] = {"at": 0.0, "payload": None}
_cbu_rates_lock = threading.Lock()


def _fetch_cbu_rates() -> list[dict[str, Any]]:
    resp = requests.get(CBU_RATES_URL, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


def _cbu_rates_payload() -> dict[str, Any]:
    raw = _fetch_cbu_rates()
    by_ccy = {str(r.get("Ccy", "")).upper(): r for r in raw if isinstance(r, dict)}
    rates = []
    for ccy in CBU_RATES_CURRENCIES:
        row = by_ccy.get(ccy)
        if not row:
            continue
        rates.append({
            "ccy": ccy,
            "name_ru": row.get("CcyNm_RU"),
            "name_uz": row.get("CcyNm_UZ"),
            "name_en": row.get("CcyNm_EN"),
            "nominal": formulas.to_number(row.get("Nominal")),
            "rate": formulas.to_number(row.get("Rate")),
            "diff": formulas.to_number(row.get("Diff")),
        })
    return {
        "ok": True,
        "source": "cbu.uz",
        "date": next((r.get("Date") for r in raw if r.get("Date")), None),
        "rates": rates,
    }


@app.get("/api/currency/rates")
async def api_currency_rates(request: Request) -> Response:
    now = time.time()
    if _cbu_rates_cache["payload"] is None or now - _cbu_rates_cache["at"] > CBU_RATES_TTL_SEC:
        loop = asyncio.get_running_loop()
        try:
            payload = await loop.run_in_executor(None, _cbu_rates_payload)
            with _cbu_rates_lock:
                _cbu_rates_cache["payload"] = payload
                _cbu_rates_cache["at"] = now
        except Exception:
            logger.exception("CBU rates refresh failed")
            if _cbu_rates_cache["payload"] is None:
                # Nothing cached and the bank unreachable — say so honestly
                # rather than 502: the strip simply does not render.
                return _etag_json(request, {"ok": False, "rates": []}, max_age=60)
    return _etag_json(request, _cbu_rates_cache["payload"], max_age=300)


def _bank_fx_payload() -> dict[str, Any]:
    """Group the flat rate-cell rows into one entry per bank, plus the best
    buy/sell across banks for each currency+channel — flagged cells are
    excluded from "best" so a suspect quote never wins the ranking, but they
    are still served on the bank's own card (ТЗ: show the real number, mark
    uncertainty, never hide it)."""
    rows = provenance.bank_fx_rates_latest()
    banks: dict[str, dict[str, Any]] = {}
    best: dict[str, dict[str, Any]] = {}
    for r in rows:
        code = r["bank_code"]
        bank = banks.setdefault(code, {
            "bank_code": code, "bank_name": r["bank_name"],
            "updated_at": r["bank_updated_at"], "rates": {},
        })
        # A bank's cards can carry more than one bank_updated_at across
        # currencies (a channel refreshed independently) — the newest wins as
        # the bank's headline "as of" stamp.
        if r["bank_updated_at"] and r["bank_updated_at"] > (bank["updated_at"] or ""):
            bank["updated_at"] = r["bank_updated_at"]
        bank["rates"].setdefault(r["ccy"], {})[r["channel"]] = {
            "buy": r["buy"], "sell": r["sell"], "flag": r["flag"],
        }
        if r["flag"]:
            continue
        slot = best.setdefault(r["ccy"], {}).setdefault(r["channel"], {"best_buy": None, "best_sell": None})
        if r["buy"] is not None and (slot["best_buy"] is None or r["buy"] > slot["best_buy"]["value"]):
            slot["best_buy"] = {"bank_code": code, "bank_name": r["bank_name"], "value": r["buy"]}
        if r["sell"] is not None and (slot["best_sell"] is None or r["sell"] < slot["best_sell"]["value"]):
            slot["best_sell"] = {"bank_code": code, "bank_name": r["bank_name"], "value": r["sell"]}
    return {
        "ok": True,
        "source": "bankxizmatlari.uz",
        "banks": sorted(banks.values(), key=lambda b: b["bank_name"] or ""),
        "best": best,
    }


@app.get("/api/bank-fx")
async def api_bank_fx(request: Request) -> Response:
    """Every commercial bank's published exchange rate, refreshed hourly by
    the collector — see bank_fx_collector.py for what the source publishes
    and why a wide spread is flagged rather than dropped."""
    try:
        payload = _bank_fx_payload()
    except Exception:
        logger.exception("bank-fx read failed")
        return _etag_json(request, {"ok": False, "banks": [], "best": {}}, max_age=60)
    return _etag_json(request, payload, max_age=300)


@app.get("/api/heatmap")
async def api_heatmap(request: Request) -> Response:
    """The market map: tiles, sectors and metadata in ONE response (ТЗ §9)."""
    trace = obs.Trace(endpoint="heatmap")
    try:
        inputs = await _heatmap_inputs()
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


_BOND_QUALITY_TASKS: dict[str, asyncio.Task] = {}


async def _compute_bond_history_quality(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The data tier of each bond, from its own price history.

    §А.2 puts history quality in the bond table for the same reason the equity
    screens carry it: these issues trade in ones and twos, and a price series
    with 87% flat candles cannot support the same chart as one with 226 points.
    The bonds board shipped with the column and without the input, so every row
    showed a dash where the tier belongs.

    One history per issue, memoised for ten minutes and fetched concurrently; a
    failure costs that row its tier and nothing else, because a board must not
    go dark over an enrichment.
    """
    securities = inputs["securities"]
    targets = []
    for row in inputs["board"]:
        ticker = str(row.get("ticker") or "").upper()
        meta = securities.get(ticker) or {}
        if bonds.is_bond(row, meta) and (row.get("isin") or meta.get("isin")):
            targets.append((ticker, row.get("isin") or meta.get("isin")))

    async def one(ticker: str, isin: str):
        try:
            data = await _full_history(isin)
            points = formulas.normalize_points(data.get("points") or [])
            return ticker, formulas.data_quality(points)
        except Exception:  # noqa: BLE001 — a missing tier is a dash, not a 502
            logger.debug("bond history quality failed for %s", ticker, exc_info=True)
            return ticker, None

    results = await asyncio.gather(*(one(t, i) for t, i in targets))
    return {t: q for t, q in results if q}


async def _bond_history_quality(inputs: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return cached enrichment immediately; warm a cold cache in background.

    Price-history quality is useful context, but it must not hold the entire
    bond screener behind dozens of upstream history downloads.
    """
    securities = inputs["securities"]
    targets = sorted(
        (str(row.get("ticker") or "").upper(), row.get("isin") or (securities.get(str(row.get("ticker") or "").upper()) or {}).get("isin"))
        for row in inputs["board"]
        if bonds.is_bond(row, securities.get(str(row.get("ticker") or "").upper()) or {})
    )
    revision = f"{inputs.get('trade_date') or 'none'}:{','.join(f'{ticker}={isin}' for ticker, isin in targets if isin)}"
    cache_key = cache_layer.key("bond:history-quality", revision)
    cached = cache_layer.get(cache_key)
    if cached is not None:
        return cached

    async def compute_and_store():
        value = await _compute_bond_history_quality(inputs)
        cache_layer.set(cache_key, value, ttl=3600)
        return value

    task = _BOND_QUALITY_TASKS.get(cache_key)
    if task is None or task.done():
        task = asyncio.create_task(compute_and_store())
        _BOND_QUALITY_TASKS[cache_key] = task
        task.add_done_callback(lambda _task: _BOND_QUALITY_TASKS.pop(cache_key, None))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=0.75)
    except asyncio.TimeoutError:
        return {}


@app.get("/api/bonds")
async def api_bonds(request: Request) -> Response:
    """The bond contour (Дополнение 1 §А.6).

    Twelve issues trade genuinely and appeared nowhere in the interface. They get
    their own section with the metrics that CAN be computed honestly from what
    the sources publish: the par from the exchange, the coupon from the issuer's
    own payment filings, and an explicit `no_bond_reference` for the discounting
    metrics, which need a redemption date nobody files until they redeem.
    """
    try:
        inputs = await _market_inputs()
        references, coupons = provenance.bond_references(), provenance.bond_coupons()
        quality = await _bond_history_quality(inputs)
        # The base curve and the key rate ride in from their own store: the
        # spread columns were shipped with no key rate ever passed, so every
        # row answered `no_bond_reference` about a number nobody had given it.
        gov_points = bonds.gov_curve_points(provenance.gov_auctions())
        key_rate = provenance.key_rate()
        # The day statistics go in with the board: the quote feed lags for a thin
        # issue (IQMK5B8 carried its 3 April print while the protocol held today's)
        # and it carries no trade count for a bond at all.
        payload = bonds.build_bond_board(inputs["board"], inputs["securities"],
                                         references, coupons, quality,
                                         key_rate=(key_rate or {}).get("rate"),
                                         stats=inputs["stats"], gov_points=gov_points)
        payload["ok"] = True
        payload["trade_date"] = inputs["trade_date"]
        payload["gov_curve"] = gov_points
        payload["key_rate"] = key_rate
        return _etag_json(request, payload, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("bonds failed")
        raise HTTPException(status_code=502, detail="bonds unavailable") from exc


@app.get("/api/bonds/curve")
async def api_bonds_curve(request: Request) -> Response:
    """The UZS base curve: every ГЦБ auction on record, the interpolable points
    of the current curve (freshest auction per tenor), and the key rate.

    Declared before /api/bonds/{ticker} so "curve" cannot be read as a ticker.
    """
    try:
        auctions = provenance.gov_auctions()
        payload = {
            "ok": True,
            "count": len(auctions),
            "auctions": auctions,
            "points": bonds.gov_curve_points(auctions),
            "window_days": bonds.GOV_CURVE_WINDOW_DAYS,
            "key_rate": provenance.key_rate(),
            "source_url": "https://cbu.uz/ru/monetary-policy/operations/fiscal-agent/",
        }
        return _etag_json(request, payload, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("bonds curve failed")
        raise HTTPException(status_code=502, detail="bonds curve unavailable") from exc


@app.get("/api/bonds/calendar")
async def api_bonds_calendar(request: Request, months: int = 14) -> Response:
    """Every future payment the bond market owes, by issue and by month.

    Declared before /api/bonds/{ticker} so "calendar" cannot be read as a
    ticker. The exchange's register is what makes the screen possible: before
    it, the only future payment known was the one an issuer had already
    announced, so a "calendar" would have held the next coupon of one issue.
    """
    try:
        payload = bonds.market_cashflows(provenance.bond_references(),
                                         provenance.bond_coupons(),
                                         horizon_months=max(1, min(int(months), 60)))
        payload["ok"] = True
        payload["source_url"] = bond_registry.REGISTRY_PAGE
        return _etag_json(request, payload, max_age=600)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("bonds calendar failed")
        raise HTTPException(status_code=502, detail="bonds calendar unavailable") from exc


@app.get("/api/bonds/{ticker}")
async def api_bond_detail(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()
    inputs = await _market_inputs()
    references, coupons = provenance.bond_references(), provenance.bond_coupons()
    quality = await _bond_history_quality(inputs)
    gov_points = bonds.gov_curve_points(provenance.gov_auctions())
    key_rate = provenance.key_rate()
    payload = bonds.build_bond_board(inputs["board"], inputs["securities"],
                                     references, coupons, quality,
                                     key_rate=(key_rate or {}).get("rate"),
                                     stats=inputs["stats"], gov_points=gov_points)
    row = next((r for r in payload["items"] if r["ticker"] == ticker), None)
    if not row:
        raise HTTPException(status_code=404, detail="bond not found")
    from sector_report_service import bond_issuer_context
    issuer_context = await asyncio.get_running_loop().run_in_executor(None, bond_issuer_context, references.get(ticker) or {})
    schedule_flows = bonds.issue_schedule(references.get(ticker), coupons.get(ticker, []))
    payment_watch = next((flow for flow in schedule_flows if flow.get("execution_status") == "due_unconfirmed"), None)
    payment_watch = payment_watch or next((flow for flow in schedule_flows if flow.get("execution_status") == "scheduled"), None)
    assessments = {
        "issuer_financials": {
            "status": "verified" if (issuer_context.get("issuer_report") or {}).get("status") == "available" else "limited",
            "financial_as_of": issuer_context.get("financial_as_of"),
            "reason": issuer_context.get("issuer_link_status"),
        },
        "issue_terms_and_execution": {
            "status": row.get("instrument_verdict"),
            "schedule_status": (row.get("schedule") or {}).get("calculation_status"),
            "unconfirmed_due_payments": sum(flow.get("execution_status") == "due_unconfirmed" for flow in schedule_flows),
        },
        "market_price_and_liquidity": {
            "status": (row.get("freshness") or {}).get("status"),
            "quote_as_of": row.get("quote_as_of"), "trades": row.get("trades"),
            "turnover": row.get("turnover"),
        },
    }
    monitoring_points = []
    if payment_watch:
        monitoring_points.append({
            "metric_code": "next_or_unconfirmed_payment", "date": payment_watch.get("date"),
            "current_baseline": payment_watch.get("execution_status"),
            "improvement_signal": "payment execution is confirmed by an official source",
            "risk_signal": "the due date passes without verified execution",
            "required_disclosure": "official payment confirmation and any contractual cure period",
        })
    monitoring_points.append({
        "metric_code": "market_liquidity", "current_baseline": {
            "quote_as_of": row.get("quote_as_of"), "trades": row.get("trades"), "turnover": row.get("turnover")},
        "improvement_signal": "new verified trades broaden the recent price and volume history",
        "risk_signal": "the quote ages or remains unsupported by trades and volume",
        "required_disclosure": "dated 30/90-day trading activity, volume and available bid/ask data",
    })
    return _json_safe({"ok": True, **row, **issuer_context, "coupons": coupons.get(ticker, []),
                       "assessments": assessments, "monitoring_points": monitoring_points[:2],
                       # The whole payment schedule of THIS issue — filed where
                       # the issuer filed it, reconstructed from the register's
                       # cycle everywhere else. Served on the card only: the
                       # board would carry sixty-five of these for nothing.
                       "schedule_flows": schedule_flows,
                       "gov_curve": gov_points, "key_rate": key_rate,
                       "board_day": payload.get("board_day")})


@app.get("/api/bonds/{ticker}/coupons")
async def api_bond_coupons(ticker: str) -> dict[str, Any]:
    rows = provenance.bond_coupons().get(ticker.upper(), [])
    return _json_safe({"ok": True, "ticker": ticker.upper(), "count": len(rows), "items": rows})


@app.post("/api/admin/bonds/reference")
async def api_admin_bond_reference(payload: dict[str, Any],
                                   _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Load the issue reference — the second half of the contour (§А.4).

    Three switches, not one: the par (from the exchange) turns on the price as a
    percentage of par, the coupon rate (from the issuer's payment filings) turns
    on accrued interest and the running yield, and only a FILED redemption date
    turns on yield to maturity and duration. Each arrives from a different place
    and at a different time, and each turns its metrics on with no code change.
    """
    written = provenance.upsert_bond_reference(payload.get("rows") or [])
    coupons = provenance.upsert_bond_coupons(payload.get("coupons") or [])
    return {"ok": True, "upserted": written, "coupons": coupons}


@app.post("/api/admin/gov-auctions")
async def api_admin_gov_auctions(payload: AdminGovAuctionsRequest,
                                 _: None = Depends(_require_admin)) -> dict[str, Any]:
    """ГЦБ auction results + the key rate, pushed by the collector.

    Each row is a published placement protocol — final the day it appears, so
    the upsert overwrites rather than merges. The key rate is a history table:
    one row per change, arrival-only.
    """
    written = provenance.upsert_gov_auctions(payload.rows)
    rate_written = provenance.upsert_key_rate(payload.key_rate)
    return {"ok": True, "upserted": written, "key_rate": rate_written}


@app.post("/api/admin/bank-fx")
async def api_admin_bank_fx(payload: AdminBankFxRequest,
                            _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Commercial-bank exchange rates from bankxizmatlari.uz, pushed hourly.

    Keyed on each bank's own stated update time, so a quiet poll — nobody
    moved a rate — writes nothing new; only an actual change lands a row.
    """
    written = provenance.upsert_bank_fx_rates(payload.rows)
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
            # The invariant report is the fourth level of testing and belongs on
            # the same trigger: both answer "is what we just loaded sane?", and
            # an empty report is the only normal outcome for either.
            report = await _run_invariants()
            level = logger.warning if not report["ok"] else logger.info
            level("invariants after %s: %d finding(s), ok=%s", trigger,
                  len(report["findings"]), report["ok"])
        except Exception:  # noqa: BLE001
            logger.exception("scheduled invariants after %s failed", trigger)

    try:
        asyncio.get_running_loop().create_task(_go())
        return True
    except RuntimeError:
        return False


@app.post("/api/audit/run")
async def api_audit_run(payload: dict[str, Any] | None = None,
                        _: None = Depends(_admin_gate)) -> dict[str, Any]:
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
async def api_audit_runs(limit: int = 20, _: None = Depends(_admin_gate)) -> dict[str, Any]:
    from audit import list_runs
    return _json_safe({"ok": True, "items": list_runs(max(1, min(limit, 200)))})


@app.get("/api/audit/runs/{run_id}")
async def api_audit_run_detail(run_id: str, _: None = Depends(_admin_gate)) -> dict[str, Any]:
    from audit import find_findings, get_run

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return _json_safe({"ok": True, "run": run, "findings": find_findings(run_id=run_id)})


@app.get("/api/audit/findings")
async def api_audit_findings(severity: str | None = None, group: str | None = None,
                             status: str | None = None, ticker: str | None = None,
                             limit: int = 200,
                             _: None = Depends(_admin_gate)) -> dict[str, Any]:
    from audit import find_findings
    return _json_safe({"ok": True, "items": find_findings(
        severity=severity, group=group, status=status, ticker=ticker,
        limit=max(1, min(limit, 2000)))})


@app.patch("/api/audit/findings/{finding_id}")
async def api_audit_update_finding(finding_id: int, payload: dict[str, Any],
                                   _: None = Depends(_admin_gate)) -> dict[str, Any]:
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
                         _: None = Depends(_admin_gate)) -> dict[str, Any]:
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
                           _: None = Depends(_admin_gate)) -> Response:
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


async def _run_invariants() -> dict[str, Any]:
    """The fourth level of testing (ТЗ §11.5), on this morning's data."""
    inputs = await _market_inputs()
    payload = _multiples_payload(inputs)
    map_payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
    catalog = instruments.build_catalog(
        securities=inputs["securities"], board=inputs["board"],
        listings=inputs["listings"], financials=inputs["financials"],
        ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
    cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
    return invariants.run([
        ("multiples_agree", lambda: invariants.check_multiples_agree_across_classes(
            payload["by_issuer"])),
        ("multiples_in_range", lambda: invariants.check_multiples_in_range(payload["items"])),
        ("statements_suppressed", lambda: invariants.check_invalid_statements_are_suppressed(
            payload["items"])),
        ("market_map", lambda: invariants.check_map(map_payload)),
        ("catalog", lambda: invariants.check_catalog(catalog)),
        ("market_cap", lambda: invariants.check_market_cap(cap)),
    ])


@app.get("/api/admin/overview")
async def api_admin_overview(history: int = 14, decide: int = 8,
                             _: None = Depends(_admin_gate)) -> dict[str, Any]:
    """One read for the admin panel's «Обзор» screen.

    Deliberately one endpoint rather than six: the screen is a single answer to
    a single question, and six round trips would let it render four true blocks
    beside two that are still loading — which reads as an outage that is not
    happening. See ``admin_overview`` for what each block is measured from, and
    in particular why the freshness block reports a last write and not a run.
    """
    import admin_overview

    loop = asyncio.get_running_loop()
    return _json_safe(await loop.run_in_executor(
        None, partial(admin_overview.build_overview,
                      history=max(1, min(history, 60)), decide=max(1, min(decide, 50)))))


@app.get("/api/admin/reports")
async def api_admin_reports(_: None = Depends(_admin_gate)) -> dict[str, Any]:
    """Screen «Отчёты» — what the pipeline took in, record by record.

    Deliberately the FIRST screen of the console. Half the defects found in the
    multiples so far were not errors of formula but of which record reached it,
    and while a record's status is invisible every fix to the calculation is
    made blind.
    """
    import admin_data
    import reports_catalog

    def _stored() -> tuple[list[dict[str, Any]], int]:
        # The RAW table, not the read path's per-ticker pick: the records the
        # read path drops are exactly the ones nobody has been able to see.
        conn = reports_catalog.get_catalog_conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT ticker, form, year, quarter, revenue, net_income, "
                "total_assets, total_equity, total_liabilities, org_type, "
                "balance_period, report_id, updated_at "
                "FROM catalog_financials")]
        finally:
            conn.close()
        return rows, reports_catalog._latest_complete_fiscal_year()

    loop = asyncio.get_running_loop()
    (stored, last_fy), inputs = await asyncio.gather(
        loop.run_in_executor(None, _stored),
        _market_inputs(),
    )
    # WHICH period each ticker's published multiple was computed from — so a
    # stored row can say whether it is the one that counted. Taken from the
    # inputs the market screen itself uses, never re-selected here.
    used: dict[str, tuple[int, int] | None] = {}
    for ticker, fin in (inputs["financials"] or {}).items():
        if not fin or fin.get("year") is None:
            continue
        used[str(ticker).upper()] = (int(fin["year"]), int(fin.get("quarter") or 0))
    return _json_safe({"ok": True, **admin_data.report_intake(stored, last_fy, used)})


@app.get("/api/admin/rules")
async def api_admin_rules(_: None = Depends(_admin_gate)) -> dict[str, Any]:
    """Screen «Правила» — the parameters, and the line the panel must not cross."""
    import admin_data

    return _json_safe({"ok": True, **admin_data.rule_book()})


@app.get("/api/admin/source")
async def api_admin_source(_: None = Depends(_admin_gate)) -> dict[str, Any]:
    """Screen «Источник» — who was due to file, who did, and who has gone quiet.

    Being late is a fact about the ISSUER, not about our collector, and the
    screen states it as one. The same list is the basis of a public disclosure
    index: an issuer that has filed nothing since 2019 is worth publishing.
    """
    import admin_data
    import openinfo_probe

    loop = asyncio.get_running_loop()
    # Two halves of one question. The calendar answers "did the issuer file";
    # the probe answers "could we have read it if they had". Run together so a
    # screen never blames one for the other.
    financials, probe = await asyncio.gather(
        loop.run_in_executor(None, get_all_financials),
        loop.run_in_executor(None, openinfo_probe.run_probe),
    )
    latest = {str(t).upper(): (int(r["year"]), int(r.get("quarter") or 0))
              for t, r in (financials or {}).items()
              if isinstance(r, dict) and r.get("year") is not None}
    steps = [r for r in (probe.get("results") or []) if r.get("name") != "egress_ip"]
    return _json_safe({
        "ok": True,
        "calendar": admin_data.disclosure_calendar(latest),
        "probe": {
            "verdict": probe.get("verdict"),
            "reachable": probe.get("reachable"),
            "failed": probe.get("failed"),
            # Response time is per endpoint class and they differ by an order of
            # magnitude; one averaged number would hide the slow one.
            "steps": [{"name": s.get("name"), "ok": s.get("ok"),
                       "elapsed_ms": s.get("elapsed_ms"),
                       "status_code": s.get("status_code"),
                       "error": s.get("error")} for s in steps],
        },
    })


@app.get("/api/admin/issuer/{ticker}")
async def api_admin_issuer(ticker: str,
                           _: None = Depends(_admin_gate)) -> dict[str, Any]:
    """Screen «Эмитент» — one issuer's whole calculation, line by line.

    Every block is the OUTPUT of the published path, not a re-derivation: the
    same TTM assembly, the same balance snapshot, the same ``issuer_multiples``
    the board calls. A second implementation would eventually disagree with the
    first and the panel would be reporting its own bug.
    """
    import admin_data

    ticker = ticker.upper()
    inputs = await _market_inputs()
    payload = _multiples_payload(inputs)
    row = next((r for r in payload["items"] if r["ticker"] == ticker), None)
    if not row:
        raise HTTPException(status_code=404, detail="issuer not found")
    key = row["issuer"]
    tickers = row["issuer_classes"]
    board_by_ticker = {str(r.get("ticker") or "").upper(): r for r in inputs["board"]}
    classes = []
    for one in tickers:
        meta = (inputs["securities"] or {}).get(one) or {}
        board_row = board_by_ticker.get(one) or {}
        classes.append({
            "ticker": one, **meta,
            "market_cap": (board_row.get("market_cap")
                           if str(board_row.get("last_trade_date") or "").strip() else None),
            "shares_outstanding": (board_row.get("shares_outstanding")
                                   or meta.get("shares_outstanding")),
        })
    fin = next((inputs["financials"].get(t) for t in tickers if inputs["financials"].get(t)), None)
    rat = next((inputs["ratios"].get(t) for t in tickers if inputs["ratios"].get(t)), None)
    ledger = admin_data.issuer_ledger(key, classes, fin, rat)
    # What the SHOP WINDOW currently publishes for the same issuer, so the two
    # sit side by side. They come from the same call, so a difference here is a
    # bug in this screen and not in the market — which is itself worth seeing.
    ledger["published"] = {k: row.get(k) for k in
                           ("pe", "pb", "ps", "roe", "roa", "net_margin")}
    return _json_safe({"ok": True, "ticker": ticker, **ledger})


@app.get("/api/admin/invariants")
async def api_admin_invariants(_: None = Depends(_admin_gate)) -> dict[str, Any]:
    """The same check the scheduler runs, on demand. Empty is the good outcome."""
    return _json_safe(await _run_invariants())


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
    counts = {"price": 0, "volume": 0, "financials": 0, "financial_history": 0, "reports": 0, "resolved": 0}
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
        counts["financial_history"] += (cov.get("financial_history") or {}).get("status") == "COLLECTED"
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
            "financial_history": cov.get("financial_history"),
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
        # Ordered by the date the ISSUER published the filing, not by when our sync
        # first saw it. `detected_at` is a fact about our schedule; it also carried
        # the literal string «now» on 195 of 199 rows (a DDL default that
        # pg_migrate mistranslated), which sorted above every real date and could
        # never age out — so the timeline was 195 undated items deep.
        filings, listings = await asyncio.gather(
            loop.run_in_executor(None, partial(get_recent_filings, max(1, days), max(1, limit))),
            loop.run_in_executor(None, get_all_listings),
        )
    except Exception as exc:
        logger.exception("news feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    items: list[dict[str, Any]] = []
    for r in filings or []:
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
            # The document itself, so a row in the timeline is a way INTO the
            # filing rather than only a note that it exists.
            "pdf_url": r.get("pdf_url"),
            "excel_url": r.get("excel_url"),
            "date": r.get("published_at"),
        })

    listing_map = listings or {}
    listed = sorted(
        ((tk, l) for tk, l in listing_map.items() if l.get("listing_date")),
        key=lambda kv: kv[1]["listing_date"], reverse=True,
    )[:20]
    # The RFB registry has no security-kind field, so every line in it reads
    # «ordinary» — including a bond's. IPYB2B6, admitted 04.08.2026, is «Ipak
    # Yo'li» AITB's 20% issue: calling it an ordinary share and printing the
    # placement's own size as a CAPITALISATION is the same defect that put it on
    # the equities board. The bond register is what knows, and it knows by ISIN.
    bond_isins = await loop.run_in_executor(None, _registered_bond_isins)
    for tk, l in listed:
        is_bond = str(l.get("isin") or "").upper() in bond_isins
        item = {
            "type": "listing", "ticker": tk, "company": l.get("name") or tk,
            "share_type": "bond" if is_bond else l.get("share_type"),
            "date": l.get("listing_date"),
        }
        # An issue has no capitalisation. The field is omitted rather than
        # zeroed: absent means «we do not report this», zero would be a claim.
        if not is_bond:
            item["market_cap"] = l.get("market_cap")
        items.append(item)

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
                        order: str = "rank", instrument: str | None = None) -> dict[str, Any]:
    """Editorial news feed (§3.11): classified, market-relevant items, ranked by impact.

    Distinct from /api/news (the market-events timeline). Each item carries a
    model-estimated tone / impact / direction — an analytical signal, not advice — plus the
    ``rank`` it was ordered by. ``order=recent`` returns plain newest-first instead.
    Low-relevance items are skipped and the same story from several outlets is merged.

    ``type`` takes one of the classifier's four classes, a comma-separated list, or
    one of the two reading groups the news section offers — ``economy`` (market +
    regulatory) and ``corporate`` (corporate_event + financial_report). The groups
    partition all four, so nothing is unreachable from both tabs.

    A corporate request is served from the **disclosure sources alone** (openinfo, the
    issuers' own filings — customer, 2026-08-11): a paper's write-up of a filing is a
    retelling, and the tab is the record. Only the corporate classes are narrowed, so
    ``type`` unset — the «Все» tab — is still the mixed feed it says it is.

    ``instrument`` (``stock`` / ``bond``) narrows the feed to the filings that name a
    security of that kind. The classifier files a coupon payment and a dividend under
    the same «corporate_event», so the split cannot come from it — it comes from the
    securities the item names, typed by the catalog here rather than guessed from the
    shape of a ticker.
    """
    loop = asyncio.get_running_loop()
    ticker_types = None
    notes: dict[str, Any] = {}
    if str(instrument or "").lower() in ("stock", "bond"):
        # TWO sources, because the traded universe is not the listed one.
        # `securities` is filled from the exchange feed, so it knows only what
        # trades — the eleven dormant listings (AGMK, TGBK, UZNG…) are absent
        # from it, and a filing about one of them would have fallen out of both
        # «Акции» and «Облигации» without a word. The registry carries them, and
        # its `share_type` is a SHARE class, so a row that has one is a share.
        # The feed's own `type` is layered on top and wins, which is how all
        # fifteen bonds stay bonds.
        listings, smap = await asyncio.gather(
            loop.run_in_executor(None, get_all_listings),
            loop.run_in_executor(None, get_securities_map),
        )
        ticker_types = {}
        for tk, row in (listings or {}).items():
            klass = str((row or {}).get("share_type") or "").strip().lower()
            if klass in ("ordinary", "preferred"):
                ticker_types[str(tk).upper()] = "stock"
            elif klass == "bond":
                ticker_types[str(tk).upper()] = "bond"
        for tk, s in (smap or {}).items():
            kind = str((s or {}).get("type") or "").strip().lower()
            if kind in ("stock", "bond"):
                ticker_types[str(tk).upper()] = kind
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_feed, limit=limit, days=days, news_type=type,
                      order="recent" if order == "recent" else "rank",
                      instrument=instrument, ticker_types=ticker_types, notes=notes))
    body: dict[str, Any] = {"ok": True, "count": len(items), "items": items,
                            "disclaimer": NEWS_DISCLAIMER}
    # Diagnostic, not rendered: the news page showed this and the customer had
    # it removed — a reader does not care that TNGB has no catalog type. It
    # stays on the response because it is the only place the gap is visible at
    # all, and the items themselves are still reachable under «Все бумаги».
    if notes.get("untyped_tickers"):
        body["untyped_tickers"] = notes["untyped_tickers"]
    return _json_safe(body)


@app.get("/api/news/calendar/meetings")
async def api_news_calendar_meetings(year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """One month of upcoming shareholder-meeting announcements (news «Календарь»).

    Served from ``catalog_meetings`` (see meetings.py) — openinfo's announcement
    calendar, the one disclosure feed that names a corporate event BEFORE it
    happens. The filings feed the rest of the news section reads shows a meeting
    only once its minutes are filed.
    """
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, partial(meetings_store.meetings_for, year, month))
        return _json_safe(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("meetings calendar failed for %s-%s", year, month)
        return {"ok": False, "error": str(exc), "items": []}


@app.get("/api/news/calendar/announcements")
async def api_news_calendar_announcements(limit: int = 1000) -> dict[str, Any]:
    """The meeting-notice feed, newest publication first — the list shape of the
    same ``catalog_meetings`` window the month grid reads."""
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(
            None, partial(meetings_store.announcements, max(1, min(limit, 2000))))
        return _json_safe(payload)
    except Exception as exc:
        logger.exception("announcements feed failed")
        return {"ok": False, "error": str(exc), "items": []}


@app.get("/api/news/calendar/announcements/{announcement_id}")
async def api_news_calendar_announcement(
    announcement_id: int,
    language: str = "ru",
) -> dict[str, Any]:
    """One openinfo notice, parsed into safe fields for our internal page."""
    import meetings as meetings_store

    if language not in {"ru", "uz", "en"}:
        raise HTTPException(status_code=422, detail="language must be ru, uz or en")
    loop = asyncio.get_running_loop()
    try:
        item = await loop.run_in_executor(
            None,
            partial(meetings_store.announcement_detail, announcement_id, language),
        )
        return _json_safe({"ok": True, "item": item})
    except meetings_store.AnnouncementNotFound as exc:
        raise HTTPException(status_code=404, detail="announcement not found") from exc
    except meetings_store.AnnouncementSourceError as exc:
        logger.warning("openinfo announcement %s failed: %s", announcement_id, exc)
        raise HTTPException(status_code=502, detail="announcement source is unavailable") from exc


@app.get("/api/news/calendar/dividends")
async def api_news_calendar_dividends(limit: int = 300) -> dict[str, Any]:
    """The market-wide dividend calendar, one row per filing, newest first.

    The same ``catalog_dividends`` snapshot the company pages read, folded back
    from per-security copies to one row per filing so the market table does not
    list an issuer once per share class (see dividends.read_all).
    """
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    try:
        state = await loop.run_in_executor(None, dividends_store.snapshot_state)
        age = state.get("age_hours")
        if (not state.get("filings")) or age is None or age >= dividends_store.REFRESH_TTL_HOURS:
            dividends_store.refresh_in_background()
        items = await loop.run_in_executor(
            None, partial(dividends_store.read_all, max(1, min(limit, 1000))))
        return _json_safe({"ok": True, "count": len(items), "items": items,
                           "as_of": state.get("updated_at")})
    except Exception as exc:
        logger.exception("dividend calendar read failed")
        return {"ok": False, "error": str(exc), "items": []}


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


@app.get("/api/news/item/{news_id}/reaction")
async def api_news_reaction(news_id: int, max_tickers: int = 3) -> dict[str, Any]:
    """What the tagged issuers' prices did around this story (§3.11).

    Its own endpoint rather than a field on /api/news/item: the first call for an
    issuer reaches openinfo for the full series, and an article page must not wait
    on that to render its text. Repeat calls are served from the same ten-minute
    memo the company card uses, so a reader moving between stories about one issuer
    pays for the history once.

    Nothing here claims the story MOVED the price — `formulas.price_reaction` returns
    two dated closes and the interface says so in as many words.
    """
    loop = asyncio.get_running_loop()
    item = await loop.run_in_executor(None, partial(news_store.get_news_item, news_id))
    if item is None:
        raise HTTPException(status_code=404, detail="news item not found")
    tickers = [t for t in (item.get("tickers") or [])][:max(1, min(max_tickers, 5))]
    published = item.get("published_at")
    out: list[dict[str, Any]] = []
    for ticker in tickers:
        try:
            isin = await _resolve_isin(ticker)
            if not isin:
                out.append({"ticker": ticker, "status": "no_isin"})
                continue
            data = await _full_history(isin)
            points = formulas.normalize_points(data.get("points") or [])
            out.append({"ticker": ticker, "isin": isin,
                        **formulas.price_reaction(points, published)})
        except Exception:  # noqa: BLE001 — one unreachable series is not a broken page
            logger.exception("news reaction failed for %s", ticker)
            out.append({"ticker": ticker, "status": "unavailable"})
    return _json_safe({"ok": True, "id": item.get("id"), "published_at": published,
                       "items": out})


@app.get("/api/news/ticker/{ticker}")
async def api_news_ticker(
    ticker: str,
    limit: int = 30,
    days: int = 90,
    exclude_news_id: int | None = None,
) -> dict[str, Any]:
    """Per-issuer news + coverage-weighted background tone (the §3.4 info dimension)."""
    loop = asyncio.get_running_loop()
    items = await loop.run_in_executor(
        None, partial(news_store.get_news_for_ticker, ticker, limit=limit, days=days,
                      exclude_news_id=exclude_news_id))
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
    /api/admin/news: this only touches ``news.image_url``, so a stored item's classification
    (tone/impact/relevance) can never be overwritten. By default it only fills rows that
    have no image; ``replace: true`` is the upgrade pass, which swaps a feed thumbnail for
    the full-size original the collector has already verified.
    """
    images = payload.images or {}
    if len(images) > 2000:
        raise HTTPException(status_code=422, detail="too many images (max 2000 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(news_store.set_image_urls, images, replace=payload.replace))
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


@app.post("/api/admin/news/details")
async def api_admin_news_details(
    payload: AdminNewsDetailsRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Fill the story page's long read on already-stored news rows (§3.11).

    A feed teaser is one sentence; the article behind it is several paragraphs, and a reader
    who opened the story used to get the sentence. The collector's detail pass reads the
    source's article page once and writes OUR OWN 3-5 paragraph account of it in all three UI
    languages — the source's text is never stored, which is what keeps the legal invariant.

    Its own route rather than /api/admin/news for the same reason as the image, snippet and
    translation routes: a full upsert from a partial record would rewrite the classification.
    Normal runs fill only empty columns. ``replace`` is the explicit admin-only migration
    path used when one source's extraction quality materially improves.
    """
    details = payload.details or {}
    if len(details) > 500:
        raise HTTPException(status_code=422, detail="too many details (max 500 per call)")
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(news_store.set_details, details, replace=payload.replace)
        )
    except Exception as exc:
        logger.exception("admin news detail update failed")
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


@app.post("/api/admin/news/rejudge")
async def api_admin_news_rejudge(
    payload: dict[str, Any],
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Delete one source's rejected rows so the collector classifies them again.

    A stored verdict is what stops us paying twice for the same item; it also means a gate
    that judged wrong keeps that judgement for the life of the row. When the gate changes,
    this is how the items it buried get a second reading. Only ``relevant = 0`` rows go —
    a card already on the feed is never withdrawn by this call.
    """
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="source_id is required")
    days = int(payload.get("days") or 60)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, partial(news_store.delete_rejected_from_source, source_id, days=days))
    except Exception as exc:
        logger.exception("admin news rejudge failed")
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
    from admin_control.service import role_for
    if role_for(current_user.email) != "administrator":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@app.get("/api/admin/data-quality/issues")
async def api_data_quality_issues(
    status: Literal["open", "resolved", "ignored"] | None = None,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Persisted review queue; reading it never alters source financial rows."""
    import data_quality
    return _json_safe(await asyncio.get_running_loop().run_in_executor(
        None, partial(data_quality.list_issues, status)))


@app.post("/api/admin/data-quality/scan")
async def api_data_quality_scan(
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Run the deterministic financial completeness/balance checks on demand."""
    import data_quality
    return _json_safe(await asyncio.get_running_loop().run_in_executor(
        None, data_quality.scan_financial_issues))


@app.post("/api/admin/data-quality/companies/{ticker}/refresh")
async def api_data_quality_refresh_company_reporting(
    ticker: str,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Re-import one issuer's official filings and re-parse its latest NSBU data."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.refresh_company_reporting, ticker, current_user.email))
        return _json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/admin/data-quality/analysis/{ticker}/scan")
async def api_data_quality_analysis_scan(
    ticker: str,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Run the public company analysis gate for one issuer and persist blockers."""
    import data_quality
    try:
        return _json_safe(await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.scan_analysis_issue, ticker)))
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/admin/data-quality/corrections")
async def api_data_quality_corrections(
    ticker: str | None = None,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    import data_quality
    return _json_safe(await asyncio.get_running_loop().run_in_executor(
        None, partial(data_quality.list_corrections, ticker)))


@app.post("/api/admin/data-quality/publication-holds")
async def api_data_quality_publication_hold(
    payload: PublicationHoldRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Temporarily hide a filing from public report and quarterly-finance tabs."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.set_publication_hold, **payload.model_dump(), actor=current_user.email))
        return _json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.get("/api/admin/data-quality/issues/{issue_id}/suggestion")
async def api_data_quality_suggestion(
    issue_id: str,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Calculate an editable proposal; it never writes or approves a correction."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.suggest_correction, issue_id))
        return _json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/api/admin/data-quality/issues/{issue_id}/apply")
async def api_data_quality_apply_issue(
    issue_id: str,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Apply the calculated correction and its linked report evidence in one click."""
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.auto_apply_issue, issue_id, current_user.email))
        return _json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/admin/data-quality/issues/{issue_id}/apply-unit-scale")
async def api_data_quality_apply_unit_scale(
    issue_id: str,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Apply the verified 1,000× Form-2 unit conversion and recheck it."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.auto_apply_unit_scale_issue, issue_id, current_user.email))
        return _json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/admin/data-quality/corrections")
async def api_data_quality_create_correction(
    payload: DataCorrectionRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.create_correction, payload.model_dump(), current_user.email))
        return _json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/admin/data-quality/corrections/apply")
async def api_data_quality_apply_correction(
    payload: DataCorrectionRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Apply a manually edited correction immediately, retaining the audit record."""
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.apply_correction, payload.model_dump(), current_user.email))
        return _json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/admin/data-quality/corrections/{correction_id}/review")
async def api_data_quality_review_correction(
    correction_id: str,
    payload: DataCorrectionReviewRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.review_correction, correction_id, payload.status,
                          current_user.email, payload.note))
        return _json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


_admin_company_syncs: set[str] = set()
_admin_company_syncs_lock = threading.Lock()


def _sync_approved_company(ticker: str) -> None:
    """Run one approved import through the existing report collector."""
    ticker = ticker.upper()
    try:
        company_imports.set_sync_status(ticker, "running")
        metadata = company_imports.approved_metadata_map().get(ticker) or {}
        if not metadata:
            raise RuntimeError("company is not approved")
        result = catalog_sync_company(
            ticker,
            str(metadata.get("company_name") or ticker),
            force=True,
            org_id=str(metadata.get("org_id") or "") or None,
        )
        errors = result.get("errors") if isinstance(result, dict) else None
        if errors:
            company_imports.set_sync_status(ticker, "failed", "; ".join(map(str, errors)))
        else:
            company_imports.set_sync_status(ticker, "complete")
    except Exception as exc:  # noqa: BLE001 - status is the admin-facing result
        logger.exception("admin company sync failed for %s", ticker)
        company_imports.set_sync_status(ticker, "failed", str(exc))
    finally:
        with _admin_company_syncs_lock:
            _admin_company_syncs.discard(ticker)


def _schedule_company_sync(ticker: str) -> bool:
    ticker = ticker.upper()
    with _admin_company_syncs_lock:
        if ticker in _admin_company_syncs:
            return False
        _admin_company_syncs.add(ticker)
    company_imports.set_sync_status(ticker, "queued")
    asyncio.get_running_loop().run_in_executor(None, _sync_approved_company, ticker)
    return True


@app.get("/api/admin/companies")
async def api_admin_companies(
    status: str | None = None,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Review queue for securities discovered from UZSE and OpenInfo."""
    try:
        return _json_safe(company_imports.list_imports(status))
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/admin/companies/search")
async def api_admin_companies_search(
    q: str,
    limit: int = 12,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Small, live issuer lookup used by operational admin controls."""
    return _json_safe({"ok": True, "items": await asyncio.get_running_loop().run_in_executor(
        None, partial(company_imports.search_companies, q, limit))})


@app.post("/api/admin/companies/discover")
async def api_admin_companies_discover(
    force: bool = False,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Refresh the queue from the authoritative exchange/OpenInfo sources."""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.refresh_candidates, force=force, actor=current_user.email),
        )
        return _json_safe(result)
    except (requests.RequestException, LookupError) as exc:
        raise HTTPException(status_code=502, detail=f"Company discovery failed: {exc}") from exc


@app.get("/api/admin/companies/{ticker}/preview")
async def api_admin_company_preview(
    ticker: str,
    refresh: bool = True,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Resolve one ticker and return the exact facts an admin will approve."""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.preview_import, ticker, refresh=refresh,
                    actor=current_user.email),
        )
        return _json_safe({"ok": True, "company": result})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenInfo is unavailable: {exc}") from exc


@app.post("/api/admin/companies/{ticker}/approve")
async def api_admin_company_approve(
    ticker: str,
    payload: AdminCompanyApproveRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Publish a reviewed candidate and optionally start its first sync."""
    try:
        company = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.approve_import, ticker,
                    payload.model_dump(exclude={"sync"}, exclude_none=True),
                    actor=current_user.email),
        )
        # An approved OpenInfo org ID directly resolves the corresponding
        # data-quality mapping finding; the document sync may continue in the
        # background without keeping a now-fixed mapping marked as open.
        import data_quality
        await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.resolve_issuer_mapping_issue, ticker, current_user.email))
        started = _schedule_company_sync(ticker) if payload.sync else False
        return _json_safe({"ok": True, "company": company,
                           "sync_started": started, "sync_requested": payload.sync})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/admin/companies/{ticker}/reject")
async def api_admin_company_reject(
    ticker: str,
    payload: AdminCompanyRejectRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    try:
        company = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.reject_import, ticker, actor=current_user.email,
                    note=payload.note),
        )
        return _json_safe({"ok": True, "company": company})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/api/admin/companies/{ticker}/visibility")
async def api_admin_company_visibility(
    ticker: str,
    payload: AdminCompanyVisibilityRequest,
    current_user: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    """Reversibly include or exclude an approved issuer from the public catalog."""
    try:
        company = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.set_catalog_visibility, ticker, payload.visible,
                    actor=current_user.email),
        )
        return _json_safe({"ok": True, "company": company,
                           "visible": payload.visible,
                           "affected_tickers": company.get("affected_tickers", 1)})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/admin/companies/{ticker}/sync")
async def api_admin_company_sync(
    ticker: str,
    _: WebUser = Depends(_require_admin_user),
) -> dict[str, Any]:
    metadata = company_imports.approved_metadata_map().get(ticker.upper())
    if not metadata:
        raise HTTPException(status_code=409, detail="Approve the company before syncing it")
    started = _schedule_company_sync(ticker)
    return {"ok": True, "ticker": ticker.upper(), "started": started}


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
    """Overwrite the trade-statistics cache from an externally-computed batch.

    The same numbers are also BANKED per session into the quote history. The
    statistics table holds one row per security, so every session's open, high,
    low, deal count and largest deal used to be discarded when the next session
    replaced it — which is why the board could summarise a day and not a month.
    Banking them is what lets a period answer with the same figures a session
    does. Its failure is logged, not raised: the cache the board reads is what
    this endpoint exists to keep current.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(
            None, partial(bulk_upsert_trade_stats, payload.rows, payload.trade_date))
    except Exception as exc:
        logger.exception("admin trade-stats upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    banked = 0
    try:
        sessions = trade_stats_as_history(payload.rows, payload.trade_date)
        if sessions:
            banked = await loop.run_in_executor(
                None, partial(bulk_upsert_quote_history, sessions))
    except Exception:  # noqa: BLE001 — the session's own numbers are already stored
        logger.exception("banking day statistics into quote history failed")
    _schedule_audit("ingest:trade-stats")
    return {"ok": True, "upserted": n, "history": banked}


@app.post("/api/admin/quotes")
async def api_admin_quotes(
    payload: AdminQuotesRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Store the exchange's own session quotes (close, previous close, change).

    `history` carries the settled daily closes the same pages published. It is
    written after the quotes and its failure is logged, not raised: the board is
    what this endpoint exists to keep current, and losing a day of sparkline
    history must not cost the session its prices.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(bulk_upsert_quotes, payload.rows))
    except Exception as exc:
        logger.exception("admin quotes upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    days = 0
    if payload.history:
        try:
            days = await loop.run_in_executor(
                None, partial(bulk_upsert_quote_history, payload.history))
        except Exception:  # noqa: BLE001 — history is not worth the session
            logger.exception("admin quote-history upsert failed")
    bars = 0
    if payload.intraday:
        try:
            bars = await loop.run_in_executor(
                None, partial(bulk_upsert_intraday_history, payload.intraday))
        except Exception:  # noqa: BLE001 — hourly bars are not worth the session either
            logger.exception("admin intraday-history upsert failed")
    _schedule_audit("ingest:quotes")
    return {"ok": True, "upserted": n, "history": days, "intraday": bars}


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

    def _write_ratios() -> int:
        written = 0
        for r in payload.ratios:
            metrics = {k: r.get(k) for k in ("ROA", "ROE", "net_margin",
                                             "debt_ratio", "debt_to_equity")
                       if r.get(k) is not None}
            if not metrics or not r.get("ticker") or r.get("year") is None:
                continue
            upsert_ratio_cache(str(r["ticker"]).upper(), payload.form,
                               int(r["year"]), int(r.get("quarter") or 0), metrics)
            written += 1
        return written

    try:
        n = await loop.run_in_executor(None, partial(writer, payload.rows, payload.form))
    except Exception as exc:
        logger.exception("admin financials %s failed", payload.mode)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    ratios_written = 0
    if payload.ratios:
        try:
            ratios_written = await loop.run_in_executor(None, _write_ratios)
        except Exception:  # noqa: BLE001 — the sums are what the board reads
            logger.exception("admin financials: ratio write failed")
    _schedule_audit("ingest:financials")
    def _queue_sector_analysis():
        import analysis_monitor
        for row in payload.rows:
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                analysis_monitor.enqueue(ticker, hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest())
    await loop.run_in_executor(None, _queue_sector_analysis)
    return {"ok": True, ("replaced" if payload.mode == "replace" else "upserted"): n,
            "ratios": ratios_written}


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


@app.post("/api/admin/pg/copy")
async def api_admin_pg_copy(payload: dict[str, Any] | None = None,
                            _: None = Depends(_require_admin)) -> dict[str, Any]:
    """Copy the SQLite databases into PostgreSQL (ТЗ §10.1, phase one).

    It runs HERE, on the service, because this is where the volume is mounted —
    a developer's machine holds a partial copy with test rows in it, and seeding
    production from that would be worse than not migrating at all.

    Additive and reversible: the copied tables sit beside the web-auth ones, the
    SQLite files are untouched, and nothing that serves a request changes until
    DATABASE_BACKEND is flipped. Pass `{"schema": "..."}` to rehearse into a
    throwaway schema first.
    """
    import pg_migrate

    payload = payload or {}
    loop = asyncio.get_running_loop()
    report = await loop.run_in_executor(None, partial(
        pg_migrate.migrate,
        schema=str(payload.get("schema") or "public"),
        dry_run=bool(payload.get("dry_run")),
        only=payload.get("only")))
    if not report.get("ok"):
        # A partial copy that reports success is how a bad cutover happens.
        return JSONResponse(_json_safe(report), status_code=500)
    return _json_safe(report)


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
    # `seed=False`: the registry was just synced on the line above, and running
    # it twice per request is half of why this endpoint outlasted the collector's
    # 120s timeout and turned the daily run red.
    backfilled = await loop.run_in_executor(
        None, functools.partial(backfill_report_links, seed=False))
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


@app.post("/api/admin/catalog-watch")
async def api_admin_catalog_watch(
    hours: int = CATALOG_WATCH_WINDOW_HOURS,
    stale: int = CATALOG_WATCH_BATCH,
    force: bool = False,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Run the hourly catalog pass now, and answer with what it did.

    Both halves of it: the issuers openinfo says filed in the last ``hours``,
    and the ``stale`` issuers that have gone longest without a sync. Deliberately
    NOT the full sweep — that one runs for minutes and belongs behind
    /api/admin/catalog-sync, which returns immediately and reports to the log.
    """
    from reports_catalog import sync_recent_filings, sync_stale_companies

    hours = max(1, min(int(hours), 24 * 30))
    stale = max(0, min(int(stale), 100))
    loop = asyncio.get_running_loop()
    try:
        filings = await loop.run_in_executor(
            None, partial(sync_recent_filings, hours=hours, force=force))
        stragglers = await loop.run_in_executor(
            None, partial(sync_stale_companies, limit=stale,
                          older_than_hours=CATALOG_FULL_SYNC_HOURS))
    except Exception as exc:
        logger.exception("admin catalog watch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "filings": _json_safe(filings), "stale": _json_safe(stragglers)}


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


def duplicate_filed_years(series: dict[str, Any], periods: Any,
                          annual_years: set[str]) -> list[str]:
    """Annual periods that are another year's copy — the ones to drop.

    `catalog_financials` is written by upsert and pruned by nothing, so a filing
    once catalogued under one year and later under another leaves the first
    behind. The ghost is bit-identical to its neighbour on every filed line —
    BECM and UZHM both show 2025 and 2024 agreeing to the sum on revenue, gross
    profit, operating income, net profit, cash and liabilities, which is not
    something two trading years do — and it made the page state «Рост г/г
    0.00%» for a year that was never filed.

    What separates the ghost from the real year is the report registry: one of
    the pair has an annual filing behind it and the other does not. Measured
    across all 100 tickers, five rows match — BECM, BECMP, METQ, UZHM and UQEQ
    — and for UQEQ it is the NEWER year that is unsupported, which is why the
    rule is "keep the one with the filing" and not "keep the newest".

    Pairs where BOTH years have a filing are left alone: BNGPP 2022/2021 and
    UZNGP 2023/2022/2021 are identical too, but nothing here can say which of
    two filed years is wrong, and guessing is worse than publishing the source.
    """
    filed_money = [f for f, e in series.items() if e.get("filed") and e.get("money")]
    ordered = sorted(periods, reverse=True)
    ghosts: list[str] = []
    for a, b in zip(ordered, ordered[1:]):
        if a in ghosts or b in ghosts:
            continue
        pair = [(series[f]["values"].get(a), series[f]["values"].get(b)) for f in filed_money]
        both = [(x, y) for x, y in pair if x is not None and y is not None]
        # Three lines, not one: a single matching figure between two years is a
        # coincidence that happens, and dropping a year on it would lose data.
        if len(both) < 3 or not all(x == y for x, y in both):
            continue
        if a in annual_years and b not in annual_years:
            ghosts.append(b)
        elif b in annual_years and a not in annual_years:
            ghosts.append(a)
    return ghosts


# The income-statement lines a quarterly filing states as a RUNNING TOTAL from
# 1 January (NSBU form 2 is cumulative — a Q2 revenue is six months of revenue)
# versus the balance lines, which are a snapshot of the quarter's last day.
# The distinction decides everything below: flows are differenced into
# three-month figures, stocks are served as filed.
QUARTER_FLOW_FIELDS = {"revenue": "net_revenue", "gross_profit": "gross_profit",
                       "operating_income": "operating_income", "operating_expenses": "operating_expenses",
                       "net_income": "net_profit"}
QUARTER_STOCK_FIELDS = {"cash": "cash", "total_liabilities": "total_liabilities",
                        "total_assets": "total_assets", "total_equity": "total_equity"}


def derive_quarterly_series(cumulative: dict[str, Any],
                            annual: dict[str, Any], *,
                            issues: list[dict[str, Any]] | None = None) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Discrete three-month columns out of NSBU's cumulative quarterly filings.

    This is the standard presentation for comparing quarters — every terminal
    prints Q2 as the three months of Q2, not as «за 6 месяцев» — and it is the
    only one on which a same-quarter-last-year comparison means anything. The
    arithmetic is the one every data vendor applies to running totals:

      Q1 = the Q1 filing;  Qn = filing(Qn) − filing(Qn−1);
      Q4 = the annual filing − the nine-month filing,

    Usually the annual is the Q4 disclosure. An explicitly filed cumulative Q4
    (some banks publish one) is also accepted; a separately filed annual wins.
    A quarter whose predecessor was never filed yields no
    figure rather than a running total masquerading as three months: a six-month
    sum in a column of quarters is exactly the «full year beside a quarter»
    defect _period_months exists to stop.

    Balance-sheet lines (cash, obligations) are snapshots and pass through
    untouched; the year-end snapshot doubles as Q4's.

    Restatements can make a derived quarter negative on lines that are usually
    positive. That is faithful: the two filings really do disagree by that
    amount, and inventing a floor would hide the restatement.

    Returns (periods newest-first, {field: {period: value}}) in the store's own
    unit (thousands of UZS); the endpoint owns the scale contract, as everywhere.
    """
    from decimal import Decimal

    def difference(current: Any, previous: Any) -> float | None:
        if current is None or previous is None:
            return None
        return float(Decimal(str(current)) - Decimal(str(previous)))

    cum: dict[tuple[int, int], dict[str, Any]] = {}
    for p, fields in (cumulative or {}).items():
        m = re.fullmatch(r"(\d{4})Q([1-4])", str(p))
        # A row where every figure is zero-or-missing is an empty filing, the
        # quarterly cousin of the zero-balance-sheet annual purged above.
        if m and any(fields.get(k) for k in (*QUARTER_FLOW_FIELDS, *QUARTER_STOCK_FIELDS)):
            cum[(int(m.group(1)), int(m.group(2)))] = dict(fields)

    # THE WITNESS LINE. A running total of revenue cannot decrease — sales are
    # not returnable in the aggregate — so within one year the cumulative
    # revenue points, annual included, must form a non-decreasing chain. Where
    # they do not, one of the filings misstates its period, and differencing it
    # would print an impossible figure as a fact: TNBN's «Q1 2023» carries
    # 932 B against a 585 B half-year — three months larger than six — and the
    # subtraction served a revenue of −347 B; SQBN's empty 2024 annual (revenue
    # zero against a 8 018 B nine-month) would have made Q4 −8 T. Measured
    # fleet-wide: 14 ticker-years of 832 are inconsistent.
    #
    # The chain itself says which filing is the odd one out: keep the longest
    # non-decreasing run (preferring the later filings on a tie — the annual
    # anchors the tail, and a later filing is the better-corrected one) and
    # drop the INCOME lines of what falls outside it. The whole statement is
    # suspect, not just its revenue, so every flow goes; the balance snapshot
    # stays — it is a statement of some real date even when mislabelled.
    def keep_consistent(points: list[tuple[int, float]]) -> set[int]:
        n = len(points)
        best: tuple[int, tuple[int, ...]] = (0, ())
        for mask in range(1 << n):
            idx = tuple(i for i in range(n) if mask >> i & 1)
            vals = [points[i][1] for i in idx]
            if any(b < a for a, b in zip(vals, vals[1:])):
                continue
            best = max(best, (len(idx), idx))
        return {points[i][0] for i in best[1]}

    annual_q4_ok: dict[int, bool] = {}
    for year in {y for y, _ in cum}:
        a_rev = ((annual or {}).get(str(year)) or {}).get("revenue")
        points = [(q, cum[(year, q)]["revenue"]) for q in (1, 2, 3)
                  if (year, q) in cum and cum[(year, q)].get("revenue") is not None]
        if a_rev is not None:
            points.append((4, a_rev))
        annual_q4_ok[year] = True
        if len(points) < 2:
            continue
        for q in {q for q, _ in points} - keep_consistent(points):
            if issues is not None:
                issues.append({"period": f"{year}Q{q}", "code": "INCONSISTENT_CUMULATIVE_INCOME",
                               "fields": list(QUARTER_FLOW_FIELDS.values())})
            if q == 4:
                annual_q4_ok[year] = False
            else:
                for src in QUARTER_FLOW_FIELDS:
                    cum[(year, q)].pop(src, None)

    series: dict[str, dict[str, Any]] = {}
    periods: set[str] = set()

    def put(name: str, year: int, q: int, value: Any) -> None:
        if value is None:
            return
        period = f"{year}Q{q}"
        series.setdefault(name, {})[period] = value
        periods.add(period)

    for (year, q), fields in cum.items():
        for src, name in QUARTER_FLOW_FIELDS.items():
            v = fields.get(src)
            if v is None:
                continue
            prev = 0.0 if q == 1 else cum.get((year, q - 1), {}).get(src)
            if prev is None and issues is not None:
                issues.append({"period": f"{year}Q{q}", "code": "MISSING_COMPARATIVE_INPUT",
                               "field": name, "required_period": f"{year}Q{q - 1}"})
            put(name, year, q, difference(v, prev))
        for src, name in QUARTER_STOCK_FIELDS.items():
            put(name, year, q, fields.get(src))

    # Q4 exists only where the year filed quarterlies at all: synthesising a
    # lone Q4 for an annual-only issuer would dress the annual view up as a
    # quarterly one.
    for year in {y for y, _ in cum}:
        a = (annual or {}).get(str(year))
        if not a:
            continue
        # An annual the witness rejected contributes NOTHING — its balance is
        # as unsupported as its income (SQBN 2024 files zeros on both sides,
        # and a 0 in the Q4 cash column beside trillions reads as a figure).
        if not annual_q4_ok.get(year, True):
            continue
        q3 = cum.get((year, 3), {})
        for src, name in QUARTER_FLOW_FIELDS.items():
            v, nine = a.get(src), q3.get(src)
            if v is not None and nine is None and issues is not None:
                issues.append({"period": f"{year}Q4", "code": "MISSING_COMPARATIVE_INPUT",
                               "field": name, "required_period": f"{year}Q3"})
            put(name, year, 4, difference(v, nine))
        for src, name in QUARTER_STOCK_FIELDS.items():
            put(name, year, 4, a.get(src))

    return sorted(periods, reverse=True), series


def _fill_equity_by_identity(series: dict[str, dict[str, Any]]) -> None:
    """Close the Капитал holes the sources leave, by the balance identity.

    On every published balance assets = liabilities + equity, so a period that
    states the first two states the third — the 2015-style «—» beside two
    filled lines is a presentation gap, not a missing fact (customer,
    2026-08-16). Only periods with no equity of their own are filled: a figure
    the feed or a filing carries always wins, including a filed zero.
    """
    assets = (series.get("total_assets") or {}).get("values", {})
    liab = (series.get("total_liabilities") or {}).get("values", {})
    entry = series.get("total_equity")
    have = (entry or {}).get("values", {})
    gap = {p: assets[p] - liab[p] for p in assets if p in liab and p not in have}
    if not gap:
        return
    if entry is None:
        entry = series["total_equity"] = {"unit": "UZS", "money": True,
                                          "derived": True, "values": {}}
    entry["values"].update(gap)


@app.get("/api/company/{ticker}/financials/documents/{sha}")
async def api_financial_document(ticker: str, sha: str) -> Response:
    from financial_ingestion.documents import issuer_artifact
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        payload = await asyncio.get_running_loop().run_in_executor(None, partial(issuer_artifact, ticker, sha))
    except (OSError, ValueError) as exc:
        logger.error("Archived financial document unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Archived document integrity/unavailability error") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(payload, media_type="application/pdf", headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Disposition": f'inline; filename="{sha}.pdf"',
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/api/admin/financial-ingestion/status")
async def api_financial_ingestion_status(_: None = Depends(_require_admin)) -> dict[str, Any]:
    from financial_ingestion.store import status
    from financial_ingestion.maintenance import incidents
    result = await asyncio.get_running_loop().run_in_executor(None, status)
    alerts = await asyncio.get_running_loop().run_in_executor(None, incidents)
    return {"ok": True, **result, "incidents": alerts}


@app.get("/api/company/{ticker}/financials/passport")
async def api_company_financial_passport(
    ticker: str,
    period: str,
    field: str,
    form: str = "NSBU",
    scope: str | None = None,
) -> dict[str, Any]:
    """Evidence passport for a value shown in the issuer financial table.

    The endpoint deliberately returns an explicit state for calculated and
    legacy values.  A number without a safe report link is not presented as if
    it had one merely because a report exists for the same issuer and year.
    """
    form = str(form or "NSBU").strip().upper()
    if form not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    if scope not in {None, "consolidated", "separate"} or (scope is not None and form != "MSFO"):
        raise HTTPException(status_code=422, detail="scope must be consolidated or separate and requires MSFO")
    loop = asyncio.get_running_loop()
    if scope is not None:
        from financial_ingestion.publication import passport
        result = await loop.run_in_executor(None, partial(passport, ticker, period, field, scope=scope))
    else:
        result = await loop.run_in_executor(
            None, partial(get_financial_value_passport, ticker, period, field, form))
    return _json_safe({
        "ok": True,
        "ticker": ticker.strip().upper(),
        "contract_version": "financial-passport-v1",
        **result,
    })


@app.get("/api/company/{ticker}/financials")
async def api_company_financials(request: Request, ticker: str, freq: str = "annual",
                                 form: str = "NSBU", scope: str | None = None) -> Response:
    """The issuer's annual series — one row per indicator, one column per year.

    Reads the `financial_indicators` fact store, which is where openinfo's
    published indicators and the NSBU-derived ones both land, and which already
    holds nine to eleven years for most issuers. It was serving nobody: the
    Финансы tab showed a single period's ratios out of the reports cache.

    **Absolute sums are scaled here, coefficients are not.** The store keeps
    money in thousands of UZS (see NSBU_THOUSANDS_UZS); a raw read would print a
    10.5-trillion revenue as ten billion, beside a market cap in full UZS on the
    same page. That is the ~1000x class of defect this contract exists to stop,
    so the field list is pinned by a test.

    A period can carry the same field twice — openinfo publishes an indicator
    and the NSBU pass derives it. The newest write wins, which is the derived
    one when it exists: it is computed from the filing this platform parsed.
    """
    ticker = ticker.strip().upper()
    standard = str(form or "NSBU").strip().upper()
    if standard not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    if scope not in {None, "consolidated", "separate"} or (scope is not None and standard != "MSFO"):
        raise HTTPException(status_code=422, detail="scope must be consolidated or separate and requires MSFO")
    loop = asyncio.get_running_loop()
    scope_info = {}
    if standard == "MSFO":
        from financial_ingestion.publication import scopes as published_scopes, series as snapshot_series, snapshots as published_snapshots
        available_scopes = await loop.run_in_executor(None, partial(published_scopes, ticker))
        default_snapshots = await loop.run_in_executor(None, partial(published_snapshots, ticker)) if scope is None else []
        scope_info = {"scope": scope or (default_snapshots[0]["scope"] if default_snapshots else None), "available_scopes": available_scopes}
        if scope is not None:
            quarterly = str(freq or "").lower().startswith("q")
            values = await loop.run_in_executor(None, partial(snapshot_series, ticker, quarterly=quarterly, scope=scope)) or {}
            entries = {}
            gaps = []
            for period, fields in values.items():
                for field, value in fields.items():
                    name = {"net_income": "net_profit", "revenue": "net_revenue"}.get(field, field)
                    entries.setdefault(name, {"unit": "UZS", "money": True, "filed": True, "values": {}})["values"][period] = value * 1000
                missing = [f for f in ("total_assets", "total_equity", "total_liabilities", "net_income", "interest_income") if fields.get(f) is None]
                if missing:
                    gaps.append({"period": period, "code": "MISSING_FINANCIAL_FIELDS", "fields": missing})
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, partial(public_status, ticker))
            return _etag_json(request, {
                "ok": True, "ticker": ticker, "currency": "UZS", "standard": standard,
                "freq": "quarterly" if quarterly else "annual", **scope_info,
                "period_basis": "cumulative_ytd" if quarterly else "annual",
                "periods": sorted(values, reverse=True), "series": entries, "data_gaps": gaps,
                "ingestion": ingestion,
                "availability": "NO_PARSED_FINANCIALS" if not entries else "PARTIAL" if gaps or ingestion.get("status") == "PARTIAL" else "AVAILABLE",
                "reason": None if entries else "No reviewed figures have been published for this accounting scope and frequency.",
            }, max_age=300)
    if str(freq or "").lower().startswith("q"):
        # IFRS interim flows retain their reported YTD basis, never NSBU or
        # synthetic standalone quarters under an IFRS label.
        if standard != "NSBU":
            from financial_ingestion.publication import series as snapshot_series
            cumulative = await loop.run_in_executor(None, partial(snapshot_series, ticker, quarterly=True)) or {}
            entries = {}
            for period, fields in cumulative.items():
                for field, value in fields.items():
                    name = {"net_income": "net_profit", "revenue": "net_revenue"}.get(field, field)
                    entries.setdefault(name, {"unit": "UZS", "money": True, "filed": True, "values": {}})["values"][period] = value * 1000
            gaps = []
            for period, fields in cumulative.items():
                missing = [key for key in ("total_assets", "total_equity", "net_income", "interest_income") if fields.get(key) is None]
                if missing:
                    gaps.append({"period": period, "code": "MISSING_FINANCIAL_FIELDS", "fields": missing})
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, public_status, ticker)
            return _etag_json(request, {
                "ok": True, "ticker": ticker, "currency": "UZS",
                "standard": standard, "freq": "quarterly", "periods": sorted(cumulative, reverse=True),
                **scope_info,
                "series": entries, "availability": "NO_QUARTERLY_IFRS" if not entries else "PARTIAL" if gaps or ingestion.get("status") == "PARTIAL" else "AVAILABLE",
                "period_basis": "cumulative_ytd", "data_gaps": gaps, "ingestion": ingestion,
                "reason": "Flows cover January through the stated period end; they are not standalone three-month figures." if entries else "No reviewed interim IFRS figures have been published.",
            }, max_age=300)
        # The quarterly view is its own, simpler read: the filings alone. The
        # openinfo indicator feed publishes no quarterly sums, so there is
        # nothing to merge, no ghost years and no feed junk to purge — the
        # annual path's machinery has no work here.
        try:
            cumulative = await loop.run_in_executor(
                None, partial(get_financials_series_quarterly, ticker, standard))
            annual = await loop.run_in_executor(
                None, partial(get_financials_series, ticker, standard))
            # The share-class fallback the annual path applies — and it must
            # merge UNCONDITIONALLY, as that path does, not only when the
            # ticker's own read is empty: AGMK carries the ONE row the daily
            # pipeline pushes under its own name while the issuer's eleven
            # backfilled quarters sit under AGMKP (the class the org row is
            # on), and an if-empty fallback served that lone row as the whole
            # history. The ticker's own figures win where both classes carry
            # the same period.
            sibling = ticker[:-1] if ticker.endswith("P") else f"{ticker}P"
            if sibling and sibling != ticker:
                sib_cum = await loop.run_in_executor(
                    None, partial(get_financials_series_quarterly, sibling, standard))
                for period, fields in (sib_cum or {}).items():
                    merged = dict(fields)
                    merged.update(cumulative.get(period) or {})
                    cumulative[period] = merged
                sib_annual = await loop.run_in_executor(
                    None, partial(get_financials_series, sibling, standard))
                for period, fields in (sib_annual or {}).items():
                    merged = dict(fields)
                    merged.update(annual.get(period) or {})
                    annual[period] = merged
            data_gaps: list[dict[str, Any]] = []
            q_periods, raw = derive_quarterly_series(cumulative, annual, issues=data_gaps)
            import data_quality
            held_periods = await loop.run_in_executor(
                None, partial(data_quality.held_public_periods, ticker, standard))
            if held_periods:
                data_gaps.extend({"period": p, "code": "UNDER_REVIEW"} for p in sorted(held_periods))
                q_periods = [period for period in q_periods if period not in held_periods]
                raw = {name: {period: value for period, value in values.items()
                              if period not in held_periods}
                       for name, values in raw.items()}
            series: dict[str, dict[str, Any]] = {
                name: {"unit": "UZS", "money": True,
                       "values": {p: v * NSBU_THOUSANDS_UZS for p, v in values.items()}}
                for name, values in raw.items()}
            # A commercial NSBU form names its expenses directly at line 040
            # («Расходы периода, всего»). When a verified filing supplies that
            # line, retain it through the cumulative-to-quarterly conversion.
            # The gross-profit-minus-operating-income proxy remains a fallback
            # for forms without a comparable line (notably banks); it is wrong
            # when line 090 other operating income is material.
            gp = raw.get("gross_profit") or {}
            oi = raw.get("operating_income") or {}
            reported_opex = raw.get("operating_expenses") or {}
            fallback_opex = {p: gp[p] - oi[p] for p in gp if p in oi}
            opex = {**fallback_opex, **reported_opex}
            if opex:
                series["operating_expenses"] = {"unit": "UZS", "money": True,
                                                "derived": bool(fallback_opex),
                                                "filed": bool(reported_opex),
                                                "values": {p: v * NSBU_THOUSANDS_UZS
                                                           for p, v in opex.items()}}
            rev = raw.get("net_revenue") or {}
            prof = raw.get("net_profit") or {}
            margin = {p: round(prof[p] / rev[p] * 100.0, 4)
                      for p in rev if rev.get(p) and p in prof}
            if margin:
                series["net_margin"] = {"unit": "%", "money": False,
                                        "derived": True, "values": margin}
            _fill_equity_by_identity(series)
            for p in q_periods:
                missing = [field for field in ("net_revenue", "net_profit", "total_assets", "total_equity", "total_liabilities")
                           if (series.get(field) or {}).get("values", {}).get(p) is None]
                if missing:
                    data_gaps.append({"period": p, "code": "MISSING_FINANCIAL_FIELDS", "fields": missing})
            return _etag_json(request, {
                "ok": True, "ticker": ticker, "currency": "UZS", "standard": standard, "freq": "quarterly",
                "periods": q_periods, "series": series,
                "availability": "NO_PARSED_FINANCIALS" if not series else "PARTIAL" if data_gaps else "AVAILABLE",
                "data_gaps": data_gaps,
            }, max_age=300)
        except Exception as exc:
            logger.exception("company quarterly financials failed for %s", ticker)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        index = await loop.run_in_executor(None, partial(get_company_index, ticker))
        org_id = (index or {}).get("org_id")
        # A statement belongs to the ISSUER, not to a share class. The catalog
        # carries an org id for the ordinary line and often not for the
        # preferred one, so KSCMP, IPKYP, KFSKP, UZASP and PLSTP answered "no
        # financials published" while their ordinary sibling showed ten years of
        # the same company. Measured 2026-08-09: five of the seven pairs on the
        # board. The sibling is the same legal entity — this is the fallback the
        # company page already applies to P/E, moved to where the data is read.
        sibling = ticker[:-1] if ticker.endswith("P") else f"{ticker}P"
        if not org_id and sibling and sibling != ticker:
            alt = await loop.run_in_executor(None, partial(get_company_index, sibling))
            org_id = (alt or {}).get("org_id")
        if not org_id:
            return _etag_json(request, {"ok": True, "ticker": ticker, "org_id": None,
                                        "currency": "UZS", "standard": standard,
                                        "periods": [], "series": {}},
                              max_age=300)
        # The historical indicator feed has no accounting-standard dimension.
        # It may supplement NSBU only; putting it behind an IFRS selector would
        # silently mix standards, which this product must never do.
        facts = (await loop.run_in_executor(
            None, partial(get_facts, org_id, "financial_indicators"))) if standard == "NSBU" else []
        series: dict[str, dict[str, Any]] = {}
        periods: set[str] = set()
        # No annual for a year that has not ended: openinfo publishes a
        # placeholder "annual" for the CURRENT year (both as an indicator set
        # and as a mislabelled report), and rows stored before the входная
        # проверка existed still carry it — QZSM and BIOK showed a "2026"
        # column in August 2026 with half a year of figures presented as one.
        last_fy = _latest_complete_fiscal_year()
        for f in facts:
            value = f.get("value_num")
            period = str(f.get("period") or "").strip()
            # Annual columns only: a "2025Q1" among "2025" would sort in as a
            # year and put three months beside twelve in the growth row.
            if value is None or len(period) != 4 or not period.isdigit():
                continue
            if int(period) > last_fy:
                continue
            field = f["field"]
            money = field in FACT_MONEY_FIELDS
            share = field in FACT_SHARE_FIELDS
            # One unit per field, decided here rather than by the caller: the
            # store's own `unit` column is unreliable (net_profit_margin is
            # labelled "x" and carries a percent; gross_profit_margin is
            # labelled nothing and carries a share).
            unit = ("UZS" if money
                    else "%" if (share or field in FACT_PERCENT_FIELDS)
                    else None)
            entry = series.setdefault(field, {"unit": unit, "money": money, "values": {}})
            # 0.14 * 100 is 14.000000000000002 in binary floating point, and
            # this payload has a history of carrying such artefacts into a
            # database. Six decimals is far beyond any published precision.
            scaled = (value * NSBU_THOUSANDS_UZS if money
                      else round(value * 100.0, 6) if share
                      else value)
            entry["values"][period] = scaled
            periods.add(period)
        # A year with a ZERO BALANCE SHEET is an empty filing, not a year of no
        # activity. A going concern cannot have no balance sheet, so this is the
        # sharp test — sharper than "every money field is zero", which SQBN 2024
        # defeated: assets, equity, liabilities and revenue all zero but a stray
        # net profit of 13 000 sums, enough to keep the column and draw a bank
        # collapsing to nothing and back on the chart.
        #
        # BOTH sides of the balance must be zero. GRBK 2024 defeated the
        # assets-only test from the other direction: the feed prints
        # total_assets 0.0 beside an equity of 546.9 B and a real filed annual
        # (a −64 B loss year) — that zero is feed junk on one line, and purging
        # the year here kept the genuine filing off the page permanently.
        #
        # Zeros in the INCOME lines are kept when the balance sheet is real:
        # UZNF is a fund that genuinely earns no revenue while holding 30 T of
        # assets, and BRBN and UZNGP file on forms with no revenue line at all.
        # Those zeros are what the source says; only a missing statement goes.
        purged_empty: set[str] = set()
        for period in list(periods):
            assets = (series.get("total_assets") or {}).get("values", {}).get(period)
            equity = (series.get("total_equity") or {}).get("values", {}).get(period)
            money = [e["values"][period] for f, e in series.items()
                     if e["money"] and period in e["values"]]
            empty = (assets == 0 and not equity) or (money and not any(money))
            if empty:
                purged_empty.add(period)
                periods.discard(period)
                for entry in series.values():
                    entry["values"].pop(period, None)
        series = {f: e for f, e in series.items() if e["values"]}

        # THE FILINGS WIN. Everything above came from the openinfo indicator
        # feed, which is what we had before any historical report was parsed —
        # and which had UZTL's 2023 and 2024 revenue transposed and 2021 missing
        # while agreeing with the filings everywhere else. Where a year has been
        # parsed from the issuer's own annual report, that year is overwritten;
        # the feed is left to cover only what the filings do not carry (chiefly
        # liquidity coefficients).  Filed assets/equity are included here too:
        # the reviewed financial-organization register corrects those exact
        # balance lines, so ignoring them at this merge would make a verified
        # correction disappear behind the older indicator-feed value.
        FILED = {"revenue": "net_revenue", "net_income": "net_profit",
                 "interest_income": "interest_income", "interest_expense": "interest_expense",
                 "gross_profit": "gross_profit", "operating_income": "operating_income",
                 "operating_expenses": "operating_expenses",
                 "total_liabilities": "total_liabilities", "cash": "cash",
                 "total_assets": "total_assets", "total_equity": "total_equity",
                 "roe": "roe", "roa": "roa", "debt_ratio": "debt_ratio",
                 "debt_to_equity": "debt_to_equity"}
        filed = await loop.run_in_executor(None, partial(get_financials_series, ticker, standard))
        # get_financials_series reads the whole issuer, but only when the
        # catalog links the classes; KFSKP and KSCMP carry no org row of their
        # own, so the P-suffix fallback that already rescued org_id above
        # rescues the filed series the same way. The ticker's own rows win.
        if sibling and sibling != ticker:
            filed_sib = await loop.run_in_executor(
                None, partial(get_financials_series, sibling, standard))
            filed = filed or {}
            for period, fields in (filed_sib or {}).items():
                merged = dict(fields)
                merged.update(filed.get(period) or {})
                filed[period] = merged
        for period, fields in (filed or {}).items():
            if len(period) != 4 or not period.isdigit() or int(period) > last_fy:
                continue
            for src, name in FILED.items():
                if fields.get(src) is None:
                    continue
                money = name in FACT_MONEY_FIELDS or src in FIN_MONEY_FIELDS
                unit = ("UZS" if money else "%" if name in FACT_PERCENT_FIELDS else None)
                entry = series.setdefault(name, {"unit": unit, "money": money, "values": {}})
                entry["unit"], entry["money"] = unit, money
                entry["values"][period] = (fields[src] * NSBU_THOUSANDS_UZS if money
                                           else fields[src])
                entry["filed"] = True
                periods.add(period)
        # The empty-filing purge ran BEFORE this merge, so a year it removed
        # comes straight back if a junk parse of the same filing sits in the
        # cache — SQBN 2024 (the empty filing with a stray 13 000) was dropped
        # as empty and then re-entered with revenue 1 000. The purge's evidence
        # — the source itself published a zero balance sheet for the year —
        # does not vanish because a parse of that same filing is cached, so a
        # purged year stays out. A filed-only year the feed never carried was
        # never purged and is untouched.
        # A reviewed correction is stronger evidence than the indicator feed's
        # all-zero placeholder.  UZAS 2025 carries exactly that placeholder;
        # purging again here removed its three verified balance corrections
        # immediately after the filed-series merge restored them.
        correction_tickers = {ticker}
        if sibling and sibling != ticker:
            correction_tickers.add(sibling)
        reviewed_annuals = {
            period[:4]
            for correction_ticker in correction_tickers
            for period in (correction_periods_for(correction_ticker) if standard == "NSBU" else {})
            if period.endswith("Q4")
        }
        for period in (purged_empty - reviewed_annuals) & periods:
            periods.discard(period)
            for entry in series.values():
                entry["values"].pop(period, None)
        series = {f: e for f, e in series.items() if e["values"]}

        # A YEAR THAT IS ANOTHER YEAR'S COPY.
        #
        # `catalog_financials` is written by upsert and pruned by nothing, so a
        # filing that was once catalogued under one year and later under another
        # leaves the first behind. The ghost is bit-identical to its neighbour on
        # every filed line — BECM and UZHM both show 2025 and 2024 agreeing to
        # the sum on revenue, gross profit, operating income, net profit, cash
        # and liabilities, which is not something two trading years do — and it
        # made the page state «Рост г/г 0.00%» for a year that was never filed.
        #
        # The evidence that separates the ghost from the real year is the report
        # registry: one of the pair has an annual filing behind it and the other
        # does not. Measured across all 100 tickers, five rows match — BECM,
        # BECMP, METQ, UZHM and UQEQ — and for UQEQ it is the NEWER year that is
        # unsupported, which is why the rule is "keep the one with the filing"
        # and not "keep the newest".
        #
        # Pairs where BOTH years have a filing are left alone: BNGPP 2022/2021
        # and UZNGP 2023/2022/2021 are also identical, but nothing here can say
        # which of two filed years is wrong, and guessing would be worse than
        # publishing what the source holds.
        #
        # A read-side guard. The stale row is still in the cache; removing it
        # belongs to a collector prune, and this keeps it off the page today.
        annual_years = {str(r.get("year")) for r in (await loop.run_in_executor(
            None, partial(get_company_reports, ticker)) or [])
            if r.get("report_form") == standard and r.get("period_type") == "annual" and not r.get("quarter") and r.get("year")}
        data_gaps = [{"period": p, "code": "EMPTY_SOURCE_FILING"}
                     for p in sorted(purged_empty - reviewed_annuals, reverse=True)]
        for ghost in duplicate_filed_years(series, periods, annual_years):
            data_gaps.append({"period": ghost, "code": "UNSUPPORTED_DUPLICATE_PERIOD"})
            logger.info("financials %s: dropping %s — identical to its neighbour on every "
                        "filed line and with no annual filing of its own", ticker, ghost)
            periods.discard(ghost)
            for entry in series.values():
                entry["values"].pop(ghost, None)
        series = {f: e for f, e in series.items() if e["values"]}

        # Prefer the direct expense line when a filing names it.  The
        # gross-profit-minus-operating-income calculation is only a fallback:
        # it is wrong for banks where provisions and other operating income sit
        # between those tiers.
        gp = (series.get("gross_profit") or {}).get("values", {})
        oi = (series.get("operating_income") or {}).get("values", {})
        reported_opex = (series.get("operating_expenses") or {}).get("values", {})
        fallback_opex = {p: gp[p] - oi[p] for p in gp if p in oi}
        opex = {**fallback_opex, **reported_opex}
        if opex:
            series["operating_expenses"] = {"unit": "UZS", "money": True,
                                            "derived": bool(set(fallback_opex) - set(reported_opex)),
                                            "filed": bool(reported_opex), "values": opex}
        # Net margin, computed rather than republished — see FACT_PERCENT_FIELDS
        # for why the fed one is not trusted. Only where both sides exist and
        # revenue is not zero: BRBN files no revenue line, and a margin on a
        # zero base is a division, not a fact.
        rev = (series.get("net_revenue") or {}).get("values", {})
        prof = (series.get("net_profit") or {}).get("values", {})
        derived = {p: round(prof[p] / rev[p] * 100.0, 4)
                   for p in rev if rev.get(p) and p in prof}
        if derived:
            series["net_margin"] = {"unit": "%", "money": False, "derived": True,
                                    "values": derived}
        _fill_equity_by_identity(series)
        for p in sorted(annual_years - periods, reverse=True):
            if int(p) <= last_fy and not any(gap["period"] == p for gap in data_gaps):
                data_gaps.append({"period": p, "code": "REPORT_NOT_PARSED"})
        for p in sorted(periods, reverse=True):
            # Bank IFRS statements disclose interest income, not industrial
            # revenue/gross profit. Do not invent a revenue line or mark its
            # legitimate absence as a failed extraction.
            bank_reports = ((index or {}).get("availability") or {}).get("NSBU") or {}
            bank_ifrs = standard == "MSFO" and ("interest_income" in series or any(
                "org_type=bank" in str(report.get(link) or "")
                for reports in bank_reports.values() for report in reports
                for link in ("excel_url", "excel_url_form1")))
            top_line = "interest_income" if bank_ifrs else "net_revenue"
            missing = [field for field in (top_line, "net_profit", "total_assets", "total_equity", "total_liabilities")
                       if (series.get(field) or {}).get("values", {}).get(p) is None]
            if missing:
                data_gaps.append({"period": p, "code": "MISSING_FINANCIAL_FIELDS", "fields": missing})
        ingestion = None
        if standard == "MSFO":
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, partial(public_status, ticker))
        return _etag_json(request, {
            "ok": True, "ticker": ticker, "org_id": org_id, "currency": "UZS", "standard": standard,
            **scope_info,
            "periods": sorted(periods, reverse=True),
            "series": series,
            "availability": "NO_PARSED_FINANCIALS" if not series else "PARTIAL" if data_gaps or (ingestion or {}).get("status") == "PARTIAL" else "AVAILABLE",
            "reports_available": bool(annual_years), "data_gaps": data_gaps,
            **({"ingestion": ingestion} if ingestion is not None else {}),
        }, max_age=300)
    except Exception as exc:
        logger.exception("company financials failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/company/{ticker}/forecast")
async def api_company_forecast(ticker: str, form: str = "NSBU",
                               _: WebUser = Depends(_require_pro)) -> dict[str, Any]:
    """Three transparent business scenarios and a comparable-multiple range."""
    ticker, form = ticker.strip().upper(), str(form or "NSBU").strip().upper()
    if form not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    loop = asyncio.get_running_loop()
    annual, all_fin, listings = await asyncio.gather(
        loop.run_in_executor(None, partial(get_financials_series, ticker, form)),
        loop.run_in_executor(None, partial(get_all_financials, form)),
        loop.run_in_executor(None, get_all_listings),
    )
    listing = listings.get(ticker) or {}
    target_sector = COMPANY_SECTORS.get(ticker)
    peers = []
    for peer_ticker, fin in (all_fin or {}).items():
        if peer_ticker == ticker or not target_sector or COMPANY_SECTORS.get(peer_ticker) != target_sector:
            continue
        peer_listing = listings.get(peer_ticker) or {}
        price, shares, income = peer_listing.get("last_price"), peer_listing.get("shares_outstanding"), fin.get("net_income")
        try:
            pe = float(price) * float(shares) / (float(income) * NSBU_THOUSANDS_UZS)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if 0 < pe <= 80:
            peers.append(pe)
    result = await loop.run_in_executor(None, partial(
        build_forecast, ticker, form, annual,
        shares_outstanding=listing.get("shares_outstanding"), current_price=listing.get("last_price"), peer_pe=peers,
    ))
    # A market-wide P/E set is not a sector comparison.  With no reviewed
    # sector mapping, valuation remains NO DATA rather than quietly changing
    # the intended peer universe.
    result["peer_population"] = {"count": len(peers), "sector": target_sector,
                                 "scope": "sector" if target_sector else "NO_DATA"}
    return _json_safe({"ok": True, **result})


@app.get("/api/company/{ticker}/forecast/backtest")
async def api_company_forecast_backtest(ticker: str, form: str = "NSBU",
                                        _: WebUser = Depends(_require_pro)) -> dict[str, Any]:
    form = str(form or "NSBU").strip().upper()
    if form not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    ticker = ticker.strip().upper()
    loop = asyncio.get_running_loop()
    annual, reports = await asyncio.gather(
        loop.run_in_executor(None, partial(get_financials_series, ticker, form)),
        loop.run_in_executor(None, partial(get_company_reports, ticker)),
    )
    published_by_year = {
        str(row.get("year")): row.get("published_at")
        for row in reports
        if str(row.get("report_form") or "").upper() == form
        and str(row.get("period_type") or "").lower() == "annual"
        and row.get("year") is not None and row.get("published_at")
    }
    return _json_safe({"ok": True, "ticker": ticker.strip().upper(), "standard": form,
                       "publication_dates": published_by_year,
                       **walk_forward_annual(annual, publication_dates=published_by_year)})


@app.get("/api/company/{ticker}/technical-backtest")
async def api_company_technical_backtest(
    ticker: str, _: WebUser = Depends(_require_pro),
) -> dict[str, Any]:
    """Run the disclosed technical rule against stored confirmed sessions only."""
    ticker = ticker.strip().upper()
    isin = await _resolve_isin(ticker)
    if not isin:
        raise HTTPException(status_code=404, detail="ISIN not found")
    isin = str(isin).upper()
    history = await asyncio.get_running_loop().run_in_executor(
        None, partial(get_quote_history, [isin], 3650))
    result = await asyncio.get_running_loop().run_in_executor(
        None, partial(run_sma20_backtest, history.get(isin, [])))
    return _json_safe({"ok": True, "ticker": ticker, "isin": isin,
                       "source": "stored confirmed exchange sessions", **result})


@app.get("/api/quotes/series")
async def api_quotes_series(request: Request, tickers: str = "", days: int = 30) -> Response:
    """Settled daily closes for several securities in ONE request.

    This exists so a LIST of securities can carry a chart. The per-ticker
    `/api/price-history/{t}` calls openinfo live, so a ten-row watchlist cost ten
    upstream requests every time somebody opened a page — which is why lists here
    never had sparklines on them. Reads from `catalog_quote_history`, which the
    collector fills from pages it was already fetching.

    An unknown ticker is simply absent from `series`; asking for one is not an
    error, and a 404 for a list would throw away the rows that did resolve. A
    security with no stored session yet is absent for the same reason — the
    interface renders no line rather than a flat invented one.
    """
    wanted = [t.strip().upper() for t in (tickers or "").split(",") if t.strip()][:200]
    if not wanted:
        return _etag_json(request, {"ok": True, "days": days, "count": 0, "series": {}}, max_age=300)
    try:
        loop = asyncio.get_running_loop()
        smap = await loop.run_in_executor(None, get_securities_map)
        isin_of = {t: (smap.get(t) or {}).get("isin") for t in wanted}
        codes = [i for i in isin_of.values() if i]
        history = await loop.run_in_executor(None, partial(get_quote_history, codes, days))
        series = {}
        for ticker, isin in isin_of.items():
            rows = history.get(str(isin or "").upper()) or []
            # Restated onto today's share, exactly as /api/price-history is: these
            # points draw the sparklines and the Quick Compare peer lines, and an
            # unadjusted series puts a 40 % cliff in the middle of a flat one.
            rows, _applied = corporate_actions.adjust_history(
                rows, ticker, isin, date_key="trade_date", price_fields=("close_price",))
            # [date, close, turnover] triples, not objects: this is the one
            # payload that scales with tickers x sessions, and the key names
            # would be most of the bytes on the wire. Turnover is сумы rounded
            # to the whole сум; 0 means the session was carried forward, and
            # the compare tooltip renders that as «—», never as a small trade.
            points = [[r["trade_date"], r["close_price"], round(r.get("turnover") or 0)]
                      for r in rows if r.get("close_price") is not None]
            if points:
                series[ticker] = points
        return _etag_json(request, {"ok": True, "days": days, "count": len(series),
                                    "series": series}, max_age=300)
    except Exception as exc:
        logger.exception("quote series failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/company/{ticker}/splits")
async def api_company_splits(ticker: str) -> dict[str, Any]:
    """Share-count events for one security — the «Сплиты» view of the Финансы tab.

    Served from the curated register in corporate_actions.py: the same entries
    every price series on the site is already back-adjusted by, so the table a
    reader sees and the chart above it can never disagree. uzse.uz keeps the
    equivalent behind «Посмотреть сплиты» on its quote page, but lists only the
    redenominations — ALKB shows the 121× split and not the free issue that
    took it to 205× — while this register carries both, verified against the
    share count uzse reports today. An empty list is an answer, not a miss: no
    event ever multiplied this security's share count.
    """
    ticker = ticker.strip().upper()
    items = [
        {
            "ex_date": action.ex_date,
            "ratio": round(action.ratio, 6),
            "kind": action.kind,
            "factor": round(1.0 / action.ratio, 8),
            "source": action.source,
        }
        for action in corporate_actions.actions_for(ticker)
    ]
    return {"ok": True, "ticker": ticker, "items": items}


@app.get("/api/company/{ticker}/registry")
async def api_company_registry(ticker: str) -> dict[str, Any]:
    """Resolve the ticker through OpenInfo and fetch its full Soliq record.

    This route is intentionally per company rather than part of the market or
    securities catalog responses: the upstream request happens only when a
    visitor opens that issuer's page. The Soliq key remains server-side.
    """
    ticker = ticker.strip().upper()
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, soliq_company.fetch_company_registry, ticker)
    except soliq_company.SoliqConfigurationError as exc:
        logger.error("company registry configuration error: %s", exc)
        raise HTTPException(status_code=503, detail="Company registry is not configured") from exc
    except soliq_company.CompanyIdentityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except soliq_company.SoliqUpstreamError as exc:
        logger.warning("Soliq company registry failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=502, detail="Company registry is temporarily unavailable") from exc
    return _json_safe({"ok": True, **result})


@app.get("/api/securities/{ticker}/info")
async def api_securities_info(ticker: str, language: str = "ru") -> dict[str, Any]:
    """Return company info including Wikipedia extract for a ticker."""
    ticker = ticker.upper()
    try:
        loop = asyncio.get_running_loop()
        smap, approved = await asyncio.gather(
            loop.run_in_executor(None, get_securities_map),
            loop.run_in_executor(None, company_imports.approved_metadata_map),
        )
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
            # Catalog-only issuers (TNGB): the report catalog knows them but
            # neither the trading feed nor the RFB registry does. A name and a
            # sector are still better than a page headed by a bare ticker.
            name = next((n for n, t in COMPANY_CATALOG.items() if t == ticker), None)
            if name:
                sec = {"ticker": ticker, "company_name": name,
                       "sector": COMPANY_SECTORS.get(ticker, "other"),
                       "inactive": True}
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
            request.headers.get("user-agent"),
            _client_ip(request),
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
            None, partial(
                web_auth_store.login_user,
                payload.email,
                payload.password,
                payload.otp,
                request.headers.get("user-agent"),
                _client_ip(request),
            ))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return _auth_payload(user, token)


@app.get("/api/auth/me")
async def api_me(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    return {"ok": True, "user": current_user.to_public_dict()}


@app.patch("/api/admin/users/{user_id}/subscription")
async def api_admin_user_subscription(
    user_id: int,
    payload: SubscriptionUpdateRequest,
    request: Request,
    current_user: WebUser = Depends(_require_admin_user),
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
            source_ip_hash=web_analytics.hash_ip(_client_ip(request)),
        ),
    )
    if not result.get("ok") and result.get("reason") == "not found":
        raise HTTPException(status_code=404, detail="User not found")
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("reason") or "Subscription was not updated")
    return _json_safe(result)


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


@app.patch("/api/profile/preferences")
async def api_profile_preferences(
    payload: ProfilePreferencesRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        preferences = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.update_preferences,
                current_user.id,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "preferences": _json_safe(preferences)}


@app.post("/api/profile/password")
async def api_profile_password(
    payload: PasswordChangeRequest,
    current_user: WebUser = Depends(_require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = _extract_bearer_token(authorization)
        revoked = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.change_password,
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


@app.get("/api/profile/sessions")
async def api_profile_sessions(
    current_user: WebUser = Depends(_require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = _extract_bearer_token(authorization)
        sessions = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.list_sessions, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "sessions": _json_safe(sessions)}


@app.delete("/api/profile/sessions/{session_id}")
async def api_profile_session_delete(
    session_id: int,
    current_user: WebUser = Depends(_require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = _extract_bearer_token(authorization)
        revoked = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.revoke_session, current_user.id, session_id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not revoked:
        raise HTTPException(status_code=404, detail="Session not found or cannot revoke current session")
    return {"ok": True, "revoked": True}


@app.post("/api/profile/sessions/revoke-others")
async def api_profile_sessions_revoke_others(
    current_user: WebUser = Depends(_require_user),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    try:
        token = _extract_bearer_token(authorization)
        count = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.revoke_other_sessions, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "revoked_sessions": count}


@app.post("/api/profile/2fa/setup")
async def api_profile_two_factor_setup(
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        setup = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.begin_two_factor, current_user.id))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, **setup}


@app.post("/api/profile/2fa/enable")
async def api_profile_two_factor_enable(
    payload: TwoFactorCodeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.enable_two_factor, current_user.id, payload.code))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "two_factor_enabled": True}


@app.post("/api/profile/2fa/disable")
async def api_profile_two_factor_disable(
    payload: TwoFactorCodeRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.disable_two_factor, current_user.id, payload.code))
    except (ValueError, RuntimeError) as exc:
        status = 400 if isinstance(exc, ValueError) else 503
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"ok": True, "two_factor_enabled": False}


@app.patch("/api/profile/analyses/{analysis_id}")
async def api_profile_analysis_update(
    analysis_id: int,
    payload: AnalysisUpdateRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        analysis = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.update_analysis,
                current_user.id,
                analysis_id,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "analysis": _json_safe(analysis)}


@app.delete("/api/profile/analyses/{analysis_id}")
async def api_profile_analysis_delete(
    analysis_id: int,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.delete_analysis, current_user.id, analysis_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return {"ok": True, "deleted": True}


@app.get("/api/profile/analyses/{analysis_id}/export")
async def api_profile_analysis_export(
    analysis_id: int,
    format: Literal["pdf", "csv"] = "pdf",
    language: Literal["ru", "en", "uz"] = "ru",
    current_user: WebUser = Depends(_require_user),
) -> Response:
    try:
        analysis = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.get_analysis, current_user.id, analysis_id))
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
        None, partial(build_analysis_pdf, export_result, language, datetime.now()))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{ticker}-analysis.pdf"'},
    )


@app.patch("/api/favorites/{ticker}")
async def api_favorite_update(
    ticker: str,
    payload: FavoriteUpdateRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        favorite = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.update_favorite,
                current_user.id,
                ticker,
                payload.model_dump(exclude_unset=True),
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "favorite": _json_safe(favorite)}


@app.get("/api/portfolio")
async def api_portfolio(current_user: WebUser = Depends(_require_pro)) -> dict[str, Any]:
    """Value explicitly entered holdings against the last confirmed UZSE price.

    A missing or stale quote remains a missing valuation; it is never filled
    from an external aggregator or from the user's acquisition cost.
    """
    loop = asyncio.get_running_loop()
    positions, listings, securities = await asyncio.gather(
        loop.run_in_executor(None, partial(web_auth_store.list_portfolio_positions, current_user.id)),
        loop.run_in_executor(None, get_all_listings),
        loop.run_in_executor(None, get_securities_map),
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
    return _json_safe({"ok": True, "items": items, "count": len(items),
                       "priced_count": priced_count, "market_value": total_market_value if priced_count else None,
                       "cost_value": total_cost if priced_count else None,
                       "unrealized_pnl": (total_market_value - total_cost) if priced_count else None,
                       "price_basis": "last confirmed exchange trade", "currency": "UZS"})


@app.put("/api/portfolio/positions")
async def api_portfolio_position_upsert(
    payload: PortfolioPositionRequest,
    current_user: WebUser = Depends(_require_pro),
) -> dict[str, Any]:
    ticker = payload.ticker.strip().upper()
    securities = await asyncio.get_running_loop().run_in_executor(None, get_securities_map)
    if ticker not in securities:
        raise HTTPException(status_code=404, detail="Unknown security ticker")
    try:
        position = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.upsert_portfolio_position, current_user.id, ticker,
                          quantity=payload.quantity, average_cost=payload.average_cost,
                          currency=payload.currency, note=payload.note))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "position": _json_safe(position)}


@app.delete("/api/portfolio/positions/{ticker}")
async def api_portfolio_position_delete(
    ticker: str, current_user: WebUser = Depends(_require_pro),
) -> dict[str, Any]:
    deleted = await asyncio.get_running_loop().run_in_executor(
        None, partial(web_auth_store.delete_portfolio_position, current_user.id, ticker))
    if not deleted:
        raise HTTPException(status_code=404, detail="Portfolio position not found")
    return {"ok": True, "ticker": ticker.strip().upper(), "deleted": True}


@app.post("/api/profile/notes")
async def api_profile_note_create(
    payload: NoteWriteRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        note = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.save_note, current_user.id, None, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "note": _json_safe(note)}


@app.patch("/api/profile/notes/{note_id}")
async def api_profile_note_update(
    note_id: int,
    payload: NoteWriteRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        note = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.save_note, current_user.id, note_id, payload.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "note": _json_safe(note)}


@app.delete("/api/profile/notes/{note_id}")
async def api_profile_note_delete(
    note_id: int,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.delete_note, current_user.id, note_id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"ok": True, "deleted": True}


@app.post("/api/profile/support")
async def api_profile_support(
    payload: SupportRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        request = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.create_support_request,
                current_user.id,
                payload.subject,
                payload.message,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "request": _json_safe(request)}


@app.get("/api/profile/export")
async def api_profile_export(
    current_user: WebUser = Depends(_require_user),
    authorization: str | None = Header(default=None),
) -> Response:
    try:
        token = _extract_bearer_token(authorization)
        exported = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.export_user_data, current_user.id, token))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=json.dumps(_json_safe(exported), ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="uz-stock-profile-data.json"'},
    )


@app.delete("/api/profile/history")
async def api_profile_history_clear(
    payload: ConfirmationRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    if payload.confirmation.strip() != "CLEAR":
        raise HTTPException(status_code=400, detail='Enter "CLEAR" to confirm history deletion')
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.clear_analysis_history, current_user.id))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "deleted_analyses": count}


@app.delete("/api/profile/account")
async def api_profile_account_delete(
    payload: ConfirmationRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        deleted = await asyncio.get_running_loop().run_in_executor(
            None, partial(web_auth_store.delete_account, current_user.id, payload.confirmation))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "deleted": deleted}


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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
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
    current_user: WebUser = Depends(_require_pro),
) -> dict[str, Any]:
    # The regular analysis path is now deterministic and NSBU-first; it does not
    # spend LLM tokens, so an LLM quota must not block access to the report.
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
        "analysis_contract": result.get("analysis_contract"),
        "analysis_status": result.get("analysis_status"),
        "sector_template_code": result.get("sector_template_code"),
        "template_version": result.get("template_version"),
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
        "verified_facts": result.get("verified_facts"),
        "regulatory_compliance": result.get("regulatory_compliance"),
        "data_quality": result.get("data_quality"),
        "balance_check": result.get("balance_check"),
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


def _catalog_number(value: Any, language: str) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    separator = " " if language in {"ru", "uz"} else ","
    rendered = f"{value:,.1f}".rstrip("0").rstrip(".")
    return rendered.replace(",", separator)


def _catalog_change(current: Any, previous: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)) or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)


def _catalog_nonfinance_sections(
    analysis_type: str,
    company_name: str,
    period: str,
    current: dict[str, Any],
    previous: dict[str, Any],
    language: str,
    compare_name: str | None = None,
    compare: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Localized, deterministic report lenses over one verified filing row."""
    values = current.get("all_values") or {}
    prev_values = previous.get("all_values") or {}
    metrics = current.get("metrics") or {}
    revenue_growth = _catalog_change(values.get("revenue"), prev_values.get("revenue"))
    income_growth = _catalog_change(values.get("net_income"), prev_values.get("net_income"))

    def n(key: str) -> str:
        return _catalog_number(values.get(key), language)

    def pct(value: Any) -> str:
        return f"{_catalog_number(value, language)}%" if isinstance(value, (int, float)) else "—"

    if language == "uz":
        labels = {
            "period": f"{company_name} uchun {period} davridagi tanlangan hisobot tahlil qilindi. Barcha summalar hisobotdagi birlikda — ming so‘mda ko‘rsatilgan.",
            "income": f"Tushum: {n('revenue')} ming so‘m. Sof foyda: {n('net_income')} ming so‘m.",
            "balance": f"Aktivlar: {n('total_assets')}, majburiyatlar: {n('total_liabilities')}, kapital: {n('total_equity')} ming so‘m.",
            "trend": f"Solishtirma davrga nisbatan tushum o‘zgarishi: {pct(revenue_growth)}; sof foyda o‘zgarishi: {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; sof marja: {pct(metrics.get('net_margin'))}; qarz ulushi: {pct(metrics.get('debt_ratio'))}.",
            "price": "Faqat moliyaviy hisobot asosida adolatli aksiya narxi hisoblanmaydi; buning uchun tasdiqlangan bozor narxi va baholash modeli kerak.",
            "market": "Ushbu natija tanlangan moliyaviy hisobotga tegishli. Bozor kotirovkasi bu hisob-kitobga aralashtirilmagan.",
        }
    elif language == "en":
        labels = {
            "period": f"The selected {period} filing for {company_name} was analysed. All statement amounts are shown in the filing unit: thousand UZS.",
            "income": f"Revenue: {n('revenue')} thousand UZS. Net income: {n('net_income')} thousand UZS.",
            "balance": f"Assets: {n('total_assets')}, liabilities: {n('total_liabilities')}, equity: {n('total_equity')} thousand UZS.",
            "trend": f"Versus the comparable period, revenue changed by {pct(revenue_growth)} and net income by {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; net margin: {pct(metrics.get('net_margin'))}; debt ratio: {pct(metrics.get('debt_ratio'))}.",
            "price": "A fair share price is not calculated from a financial statement alone; it requires a verified market price and a valuation model.",
            "market": "This result is limited to the selected financial filing. Market quotes were not mixed into the calculation.",
        }
    else:
        labels = {
            "period": f"Проанализирован выбранный отчёт {company_name} за {period}. Все суммы показаны в единице отчётности — тысячах сумов.",
            "income": f"Выручка: {n('revenue')} тыс. сум. Чистая прибыль: {n('net_income')} тыс. сум.",
            "balance": f"Активы: {n('total_assets')}, обязательства: {n('total_liabilities')}, капитал: {n('total_equity')} тыс. сум.",
            "trend": f"К сопоставимому периоду выручка изменилась на {pct(revenue_growth)}, чистая прибыль — на {pct(income_growth)}.",
            "eff": f"ROA: {pct(metrics.get('ROA'))}; ROE: {pct(metrics.get('ROE'))}; чистая маржа: {pct(metrics.get('net_margin'))}; доля обязательств: {pct(metrics.get('debt_ratio'))}.",
            "price": "Справедливая цена акции не рассчитывается только по финансовому отчёту: для неё нужны подтверждённая рыночная цена и модель оценки.",
            "market": "Результат относится только к выбранному финансовому отчёту. Рыночные котировки в расчёт не подмешивались.",
        }

    # Never print a dash as though it were a reported value.  Build the factual
    # sentences again from fields that actually exist in this filing; a sparse
    # report therefore stays concise instead of showing rows of nulls.
    amount_names = {
        "ru": {"revenue": "Выручка", "net_income": "Чистая прибыль",
               "total_assets": "Активы", "total_liabilities": "Обязательства",
               "total_equity": "Капитал"},
        "uz": {"revenue": "Tushum", "net_income": "Sof foyda",
               "total_assets": "Aktivlar", "total_liabilities": "Majburiyatlar",
               "total_equity": "Kapital"},
        "en": {"revenue": "Revenue", "net_income": "Net income",
               "total_assets": "Assets", "total_liabilities": "Liabilities",
               "total_equity": "Equity"},
    }[language]
    ratio_names = {
        "ru": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Чистая маржа",
               "debt_ratio": "Доля обязательств"},
        "uz": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Sof marja",
               "debt_ratio": "Majburiyatlar ulushi"},
        "en": {"ROA": "ROA", "ROE": "ROE", "net_margin": "Net margin",
               "debt_ratio": "Debt ratio"},
    }[language]
    income_parts = [
        f"{amount_names[key]}: {_catalog_number(values.get(key), language)}"
        for key in ("revenue", "net_income") if isinstance(values.get(key), (int, float))
    ]
    balance_parts = [
        f"{amount_names[key]}: {_catalog_number(values.get(key), language)}"
        for key in ("total_assets", "total_liabilities", "total_equity")
        if isinstance(values.get(key), (int, float))
    ]
    ratio_parts = [
        f"{ratio_names[key]}: {pct(metrics.get(key))}"
        for key in ("ROA", "ROE", "net_margin", "debt_ratio")
        if isinstance(metrics.get(key), (int, float))
    ]
    trend_parts = []
    if isinstance(revenue_growth, (int, float)):
        trend_parts.append(("tushum" if language == "uz" else "revenue" if language == "en" else "выручка")
                           + f": {pct(revenue_growth)}")
    if isinstance(income_growth, (int, float)):
        trend_parts.append(("sof foyda" if language == "uz" else "net income" if language == "en" else "чистая прибыль")
                           + f": {pct(income_growth)}")
    unit = "ming so‘m" if language == "uz" else "thousand UZS" if language == "en" else "тыс. сум"
    unavailable = ("Taqqoslanadigan ma’lumot yo‘q." if language == "uz" else
                   "No comparable data is available." if language == "en" else
                   "Сопоставимые данные отсутствуют.")
    labels["income"] = ("; ".join(income_parts) + (f" {unit}." if income_parts else ""))
    labels["balance"] = ("; ".join(balance_parts) + (f" {unit}." if balance_parts else ""))
    labels["trend"] = "; ".join(trend_parts) + "." if trend_parts else unavailable
    labels["eff"] = "; ".join(ratio_parts) + "." if ratio_parts else unavailable

    if analysis_type == "financial":
        return {
            "ДОСЬЕ": labels["period"],
            "ЧТО_С_ДЕНЬГАМИ": f"{labels['income']} {labels['balance']}",
            "ТРЕНД": labels["trend"],
            "ЭФФЕКТИВНОСТЬ": labels["eff"],
            "ОЦЕНКА_ЦЕНЫ": labels["price"],
            "РЫНОЧНЫЕ_ДАННЫЕ": labels["market"],
        }

    available_checks: list[bool] = []
    net_income = values.get("net_income")
    debt_ratio = metrics.get("debt_ratio")
    roe = metrics.get("ROE")
    margin = metrics.get("net_margin")
    for value, check in (
        (net_income, lambda v: v > 0),
        (revenue_growth, lambda v: v > 0),
        (income_growth, lambda v: v > 0),
        (debt_ratio, lambda v: v < 70),
        (roe, lambda v: v > 0),
        (margin, lambda v: v > 0),
    ):
        if isinstance(value, (int, float)):
            available_checks.append(bool(check(value)))
    # A score based on one or two available cells looks precise but is not
    # representative.  Require four independent checks; sparse filings keep a
    # clear "insufficient" state instead of receiving an artificial 100/100.
    score = (round(sum(available_checks) / len(available_checks) * 100)
             if len(available_checks) >= 4 else None)

    if analysis_type == "swot":
        if language == "uz":
            strengths = []
            weaknesses = []
            if isinstance(net_income, (int, float)):
                (strengths if net_income > 0 else weaknesses).append("kompaniya foyda bilan ishlamoqda" if net_income > 0 else "tanlangan davrda zarar qayd etilgan")
            if isinstance(revenue_growth, (int, float)):
                (strengths if revenue_growth > 0 else weaknesses).append(f"tushum dinamikasi {pct(revenue_growth)}")
            if isinstance(debt_ratio, (int, float)):
                (strengths if debt_ratio < 70 else weaknesses).append(f"majburiyatlarning aktivlardagi ulushi {pct(debt_ratio)}")
            return {
                "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "Tasdiqlangan ma’lumotlarda aniq ijobiy signal yetarli emas.",
                "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "Tanlangan mezonlarda aniq salbiy signal topilmadi.",
                "КАТАЛИЗАТОРЫ": "Keyingi taqqoslanadigan hisobotda tushum, foyda va balans ko‘rsatkichlarining yaxshilanishi asosiy kuzatiladigan katalizator bo‘ladi.",
            }
        if language == "en":
            strengths = []
            weaknesses = []
            if isinstance(net_income, (int, float)):
                (strengths if net_income > 0 else weaknesses).append("the company is profitable" if net_income > 0 else "the selected period is loss-making")
            if isinstance(revenue_growth, (int, float)):
                (strengths if revenue_growth > 0 else weaknesses).append(f"revenue change is {pct(revenue_growth)}")
            if isinstance(debt_ratio, (int, float)):
                (strengths if debt_ratio < 70 else weaknesses).append(f"liabilities equal {pct(debt_ratio)} of assets")
            return {
                "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "The verified data does not contain enough clear positive signals.",
                "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "No clear negative signal was found in the selected checks.",
                "КАТАЛИЗАТОРЫ": "Improvement in revenue, profit and balance-sheet indicators in the next comparable filing is the principal catalyst to monitor.",
            }
        strengths = []
        weaknesses = []
        if isinstance(net_income, (int, float)):
            (strengths if net_income > 0 else weaknesses).append("компания прибыльна" if net_income > 0 else "в выбранном периоде получен убыток")
        if isinstance(revenue_growth, (int, float)):
            (strengths if revenue_growth > 0 else weaknesses).append(f"динамика выручки {pct(revenue_growth)}")
        if isinstance(debt_ratio, (int, float)):
            (strengths if debt_ratio < 70 else weaknesses).append(f"обязательства составляют {pct(debt_ratio)} активов")
        return {
            "СИЛЬНЫЕ_СТОРОНЫ": "; ".join(strengths) or "В подтверждённых данных недостаточно выраженных положительных сигналов.",
            "СЛАБЫЕ_СТОРОНЫ": "; ".join(weaknesses) or "По выбранным критериям явных отрицательных сигналов не найдено.",
            "КАТАЛИЗАТОРЫ": "Главный наблюдаемый катализатор — улучшение выручки, прибыли и балансовых показателей в следующем сопоставимом отчёте.",
        }

    if analysis_type == "recommendation":
        score_text = _catalog_number(score, language) if score is not None else None
        if language == "uz":
            verdict = "moliyaviy signallar ijobiy" if score is not None and score >= 60 else "moliyaviy signallar aralash"
            scoring = (f"Mavjud ko‘rsatkichlar bo‘yicha faktik ball: {score_text}/100."
                       if score_text else "Ishonchli ball uchun kamida to‘rtta mustaqil ko‘rsatkich kerak.")
            return {"СКОРИНГ": scoring,
                    "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"{period} uchun {verdict}.",
                    "ИТОГ": "Bu investitsiya tavsiyasi emas; yakun faqat tanlangan hisobotdagi mavjud ko‘rsatkichlarga asoslangan."}
        if language == "en":
            verdict = "financial signals are positive" if score is not None and score >= 60 else "financial signals are mixed"
            scoring = (f"Evidence score from available metrics: {score_text}/100."
                       if score_text else "At least four independent metrics are required for a reliable score.")
            return {"СКОРИНГ": scoring,
                    "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"For {period}, {verdict}.",
                    "ИТОГ": "This is not investment advice; the conclusion uses only available figures in the selected filing."}
        verdict = "финансовые сигналы положительные" if score is not None and score >= 60 else "финансовые сигналы смешанные"
        scoring = (f"Фактическая оценка по доступным показателям: {score_text}/100."
                   if score_text else "Для надёжной оценки нужны минимум четыре независимых показателя.")
        return {"СКОРИНГ": scoring,
                "ОЦЕНКА_ЦЕНЫ": labels["price"], "ВЕРДИКТ": f"За {period} {verdict}.",
                "ИТОГ": "Это не инвестиционная рекомендация; вывод основан только на доступных показателях выбранного отчёта."}

    if analysis_type == "multi_company" and compare is not None:
        other_values = compare.get("all_values") or {}
        other_metrics = compare.get("metrics") or {}
        revenue_diff = _catalog_change(values.get("revenue"), other_values.get("revenue"))
        income_diff = _catalog_change(values.get("net_income"), other_values.get("net_income"))
        diff_parts = []
        if isinstance(revenue_diff, (int, float)):
            diff_parts.append(("tushum farqi" if language == "uz" else
                               "revenue difference" if language == "en" else
                               "разница выручки") + f" {pct(revenue_diff)}")
        if isinstance(income_diff, (int, float)):
            diff_parts.append(("sof foyda farqi" if language == "uz" else
                               "net-income difference" if language == "en" else
                               "разница чистой прибыли") + f" {pct(income_diff)}")
        comparison_text = "; ".join(diff_parts) if diff_parts else unavailable
        roe_parts = []
        if isinstance(metrics.get("ROE"), (int, float)):
            roe_parts.append(f"{company_name} ROE {pct(metrics.get('ROE'))}")
        if isinstance(other_metrics.get("ROE"), (int, float)):
            roe_parts.append(f"{compare_name} ROE {pct(other_metrics.get('ROE'))}")
        efficiency_text = "; ".join(roe_parts) if roe_parts else unavailable
        if language == "uz":
            return {"СРАВНЕНИЕ": f"{company_name} va {compare_name}: {comparison_text}.",
                    "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Taqqoslash bir xil {period} davri va bir xil hisobot standarti bo‘yicha bajarildi."}
        if language == "en":
            return {"СРАВНЕНИЕ": f"{company_name} versus {compare_name}: {comparison_text}.",
                    "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Both use the same {period} period and reporting standard."}
        return {"СРАВНЕНИЕ": f"{company_name} против {compare_name}: {comparison_text}.",
                "ЭФФЕКТИВНОСТЬ": f"{efficiency_text}. Сравнение выполнено за один период {period} и по одному стандарту."}
    return {}


def _catalog_no_cached_data(language: str, form: str, period: str) -> str:
    if form == "Audition":
        return ({"ru": "Аудиторский отчёт не содержит стандартизированной финансовой таблицы для этого анализа.",
                 "uz": "Auditorlik hisobotida ushbu tahlil uchun standartlashtirilgan moliyaviy jadval yo‘q.",
                 "en": "An audit report has no standardized financial table for this analysis."})[language]
    return ({"ru": f"Подтверждённые финансовые данные за {period} ещё не загружены.",
             "uz": f"{period} uchun tasdiqlangan moliyaviy ma’lumotlar hali yuklanmagan.",
             "en": f"Verified financial data for {period} has not been loaded yet."})[language]

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
        approved = company_imports.approved_metadata_map()
        visible_companies = []
        for c in companies:
            ticker = str(c.get("ticker") or "").upper()
            member_metadata = [approved.get(str(member or "").upper())
                               for member in (c.get("tickers") or [ticker])]
            reviewed_members = [item for item in member_metadata if item]
            if reviewed_members and not any(bool(item.get("catalog_visible", 1))
                                            for item in reviewed_members):
                continue
            imported = approved.get(ticker) or {}
            c["company_name"] = imported.get("company_name") or c.get("company_name")
            c["logo"] = imported.get("logo_url") or resolve_logo(ticker, COMPANY_LOGOS) or ""
            c["sector"] = imported.get("sector") or COMPANY_SECTORS.get(ticker, "other")
            visible_companies.append(c)
        return {"ok": True, "count": len(visible_companies), "companies": visible_companies}
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
            imported = company_imports.approved_metadata_map().get(ticker) or {}
            company_name = (_TICKER_TO_NAME.get(ticker)
                            or imported.get("company_name"))
            if not company_name:
                raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
            result = await loop.run_in_executor(
                None, partial(catalog_sync_company, ticker, company_name, force=payload.force,
                              org_id=imported.get("org_id"))
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
    loop = asyncio.get_running_loop()
    approved = await loop.run_in_executor(None, company_imports.approved_metadata_map)
    company_name = _TICKER_TO_NAME.get(ticker) or (approved.get(ticker) or {}).get("company_name") or ticker
    form_map = {"NSBU": "NAS", "MSFO": "IFRS", "Audition": "Audit"}
    sectors = {**COMPANY_SECTORS,
               **{t: item.get("sector") for t, item in approved.items()
                  if item.get("sector")}}
    sector = sectors.get(ticker)

    try:
        # Ordinary issuers use the verified filing cache.  The former path
        # downloaded OpenInfo Excel files again for every click, so production
        # returned empty/error results whenever OpenInfo blocked the datacenter
        # address.  Financial-sector issuers deliberately remain on their
        # existing bank-aware path until that separate flow is changed.
        if sector and sector != "finance":
            period = f"{payload.year}Q{payload.quarter}" if payload.quarter else str(payload.year)

            if payload.analysis_type == "dynamics":
                dynamics = await loop.run_in_executor(
                    None, partial(build_cached_catalog_dynamics, ticker, payload.form)
                )
                if not dynamics.get("years") and not dynamics.get("quarterly"):
                    raise HTTPException(
                        status_code=404,
                        detail=_catalog_no_cached_data(payload.language, payload.form, period),
                    )
                return _json_safe({
                    "ok": True, "analysis_type": "dynamics", "ticker": ticker,
                    "company_name": company_name, "year": payload.year,
                    "quarter": payload.quarter, "sector": sector,
                    "data_source": "verified_cache", **dynamics,
                })

            current = await loop.run_in_executor(
                None, partial(get_cached_catalog_period, ticker, payload.form,
                              payload.year, payload.quarter)
            )
            if not current.get("has_data"):
                raise HTTPException(
                    status_code=404,
                    detail=_catalog_no_cached_data(payload.language, payload.form, period),
                )

            if payload.analysis_type == "ratio":
                previous = await loop.run_in_executor(
                    None, partial(get_cached_catalog_period, ticker, payload.form,
                                  payload.year - 1, payload.quarter)
                )
                sector_peers = [t for t, peer_sector in sectors.items()
                                if peer_sector == sector and t != ticker] if sector else []
                sector_avg: dict[str, Any] = {}
                if sector_peers:
                    try:
                        sector_avg = await loop.run_in_executor(
                            None, partial(get_sector_averages, sector_peers,
                                          payload.form, payload.year)
                        )
                    except Exception:
                        pass
                return _json_safe({
                    "ok": True, "analysis_type": "ratio", "ticker": ticker,
                    "company_name": company_name, "year": payload.year,
                    "quarter": payload.quarter, "form": payload.form,
                    "metrics": current.get("metrics"),
                    "source_values": current.get("source_values"),
                    "prev_year": payload.year - 1,
                    "prev_metrics": previous.get("metrics") if previous.get("has_data") else {},
                    "sector": sector, "sector_avg": sector_avg,
                    "data_source": "verified_cache",
                })

            if payload.analysis_type in ("quarter_compare", "annual_compare"):
                compare_year = payload.compare_year or (payload.year - 1)
                compare_quarter = (payload.compare_quarter
                                   if payload.compare_quarter is not None else payload.quarter)
                compared = await loop.run_in_executor(
                    None, partial(get_cached_catalog_period, ticker, payload.form,
                                  compare_year, compare_quarter)
                )
                compare_period = (f"{compare_year}Q{compare_quarter}"
                                  if compare_quarter else str(compare_year))
                if not compared.get("has_data"):
                    raise HTTPException(
                        status_code=404,
                        detail=_catalog_no_cached_data(
                            payload.language, payload.form, compare_period),
                    )
                return _json_safe({
                    "ok": True, "analysis_type": payload.analysis_type,
                    "ticker": ticker, "company_name": company_name,
                    "year": payload.year, "quarter": payload.quarter,
                    "sector": sector, "data_source": "verified_cache",
                    "period1": {"year": payload.year, "quarter": payload.quarter,
                                "form": payload.form, "metrics": current.get("metrics"),
                                "source_values": current.get("source_values")},
                    "period2": {"year": compare_year, "quarter": compare_quarter,
                                "form": payload.form, "metrics": compared.get("metrics"),
                                "source_values": compared.get("source_values")},
                })

            previous = await loop.run_in_executor(
                None, partial(get_cached_catalog_period, ticker, payload.form,
                              payload.year - 1, payload.quarter)
            )
            compare_name = None
            compared = None
            if payload.analysis_type == "multi_company":
                compare_ticker = str(payload.compare_ticker or "").strip().upper()
                if not compare_ticker:
                    raise HTTPException(status_code=400, detail="compare_ticker is required")
                if sectors.get(compare_ticker) == "finance":
                    raise HTTPException(
                        status_code=400,
                        detail=("Выберите нефинансовую компанию для сравнения."
                                if payload.language == "ru" else
                                "Taqqoslash uchun nomoliyaviy kompaniyani tanlang."
                                if payload.language == "uz" else
                                "Select a non-financial company for comparison."),
                    )
                compare_name = (_TICKER_TO_NAME.get(compare_ticker)
                                or (approved.get(compare_ticker) or {}).get("company_name")
                                or compare_ticker)
                compared = await loop.run_in_executor(
                    None, partial(get_cached_catalog_period, compare_ticker, payload.form,
                                  payload.year, payload.quarter)
                )
                if not compared.get("has_data"):
                    raise HTTPException(
                        status_code=404,
                        detail=_catalog_no_cached_data(payload.language, payload.form, period),
                    )

            sections = _catalog_nonfinance_sections(
                payload.analysis_type, company_name, period, current, previous,
                payload.language, compare_name=compare_name, compare=compared,
            )
            if not sections:
                raise HTTPException(status_code=400, detail="Unsupported analysis type")
            return _json_safe({
                "ok": True, "analysis_type": payload.analysis_type,
                "ticker": ticker, "company_name": company_name,
                "year": payload.year, "quarter": payload.quarter,
                "form": payload.form, "language": payload.language,
                "sector": sector, "sections": sections,
                "metrics": current.get("metrics"),
                "data_source": "verified_cache",
            })

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
            # Approved imports extend the legacy static sector map immediately.
            sector_peers = [t for t, s in sectors.items() if s == sector and t != ticker] if sector else []
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
            compare_name = (_TICKER_TO_NAME.get(compare_ticker)
                            or (approved.get(compare_ticker) or {}).get("company_name")
                            or compare_ticker)
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
_HISTORY_LOCKS: dict[str, asyncio.Lock] = {}


async def _full_history(isin: str, months: int = 60) -> dict[str, Any]:
    """Full price history for an ISIN, memoised for _HISTORY_CACHE_TTL seconds."""
    from openinfo_collector import fetch_price_history

    # Requests for the same archive can arrive together (the company chart and
    # metrics do this on first paint). Let the first fetch populate the cache
    # while the others wait for and reuse that result.
    key = f"{isin}:{months}"
    now = time.time()
    hit = _HISTORY_CACHE.get(key)
    if hit and now - hit[0] < _HISTORY_CACHE_TTL:
        return hit[1]
    lock = _HISTORY_LOCKS.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _HISTORY_CACHE.get(key)
        if hit and time.time() - hit[0] < _HISTORY_CACHE_TTL:
            return hit[1]
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None, partial(fetch_price_history, isin, None, months),
        )
        if len(_HISTORY_CACHE) >= _HISTORY_CACHE_MAX:
            oldest = min(_HISTORY_CACHE, key=lambda k: _HISTORY_CACHE[k][0])
            _HISTORY_CACHE.pop(oldest, None)
        _HISTORY_CACHE[key] = (time.time(), data)
        return data


# Names for the day-based windows. formulas.WINDOW_LABELS_RU is keyed by month
# count and has no entry for a week or for a year-to-date span, which is exactly
# why those two used to arrive labelled as a month.
_WINDOW_LABELS_RU = {"1d": "за сессию", "1w": "за неделю", "ytd": "с начала года"}


@app.get("/api/company/{ticker}/metrics")
async def api_company_metrics(ticker: str, months: int = 12,
                              days: int | None = None,
                              window: str | None = None) -> dict[str, Any]:
    """Window and absolute price metrics for one instrument (ТЗ v1.2 §5).

    The two blocks are the contract: ``window`` follows the period button,
    ``absolute`` never does.

    ``days`` is for the two buttons a month count cannot express — «1Н» is seven
    days, YTD is however many have passed since 1 January — and ``window`` names
    the result (``1w`` / ``ytd``). Without them the card answered «1Н» with a
    month: twenty-one sessions and a range four times too wide, under a label
    that said one week. Both are computed by formulas.py from one full
    history fetch, so the card, the market screen and the export cannot each
    arrive at a different VWAP or a different YTD.
    """
    from datetime import datetime, timezone

    import formulas

    ticker = ticker.upper()
    months = max(1, min(months, 60))
    days = max(1, min(int(days), 3650)) if days else None
    code = str(window).strip().lower()[:12] or None if window else None
    label = _WINDOW_LABELS_RU.get(code) if code else None
    # ТЗ §12: every number on the card can be replayed step by step under one
    # trace_id — input, decision with its reason, output.
    trace = obs.Trace(endpoint="company/metrics", ticker=ticker, months=months, days=days)
    try:
        isin = await _resolve_isin(ticker)
        if not isin:
            trace.reject("resolve_isin", reason="ISIN not found")
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "trace_id": trace.trace_id}, status_code=404)
        trace.step("resolve_isin", out={"isin": isin})
        # Match the company's default chart archive so first paint shares one
        # upstream fetch instead of downloading separate 5- and 20-year series.
        data = await _full_history(isin, months=240)
        points = data.get("points") or []
        trace.step("history_fetch", out={"points": len(points)})
        metrics = formulas.company_metrics(points, months=months, days=days,
                                           code=code, label=label)
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
    """Close price history for a ticker via UZSE ISIN lookup.

    The ceiling is 20 years, not 5: the chart's «Макс» button means the whole
    record, and a 60-month clamp would quietly serve five years under that label
    the moment an issuer's history grew past it. The archive answers with what
    exists, so asking for more than a security has costs nothing.
    """
    ticker = ticker.upper()
    months = max(1, min(months, 240))
    try:
        isin = await _resolve_isin(ticker)
        if not isin:
            # ТЗ §10.4.6: an unknown instrument is a 404. Returning 200 with a
            # failure body is why neither the browser, retries nor monitoring
            # could tell a fault from a normal answer.
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "points": []}, status_code=404)
        data = await _full_history(isin, months=months)
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


@app.get("/api/intraday/{ticker}")
async def api_intraday(ticker: str, days: int = 8) -> dict[str, Any]:
    """Hourly bars for the 1Д/1Н chart, from ``catalog_intraday_history``.

    The bars are rolled up from the exchange's own trade feed (per-trade moments
    live in each record's header; negotiated T1 deals are excluded — see
    trade_stats.hourly_bars) and banked by the collector: hourly by the
    trade-stats cron, historically by ``--backfill-intraday``, which the feed's
    date-filtered view makes possible months back. Days the bank has nothing
    for honestly have no bars, and the chart mixes in daily closes for them.
    Dates are ISO with an hour ("2026-08-17T14:00") so a series shared with the
    daily feed still sorts as strings.
    """
    ticker = ticker.upper()
    days = max(1, min(days, 60))
    loop = asyncio.get_running_loop()
    try:
        isin = await _resolve_isin(ticker)
        if not isin:
            return JSONResponse({"ok": False, "ticker": ticker, "error": "ISIN not found",
                                 "points": []}, status_code=404)
        rows = await loop.run_in_executor(None, partial(get_intraday_history, isin, days))
        points = [
            {
                "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}T{int(r['hour']):02d}:00",
                "open": r.get("open_price"),
                "high": r.get("high_price"),
                "low": r.get("low_price"),
                "close": r.get("close_price"),
                "volume": r.get("quantity"),
                "value": r.get("turnover"),
            }
            for r in rows
            if (d := str(r.get("trade_date") or "")) and r.get("close_price") is not None
        ]
        return {"ok": True, "ticker": ticker, "isin": isin, "points": points}
    except Exception as exc:
        logger.exception("intraday failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "points": []}


@app.get("/api/dividends/{ticker}")
async def api_dividends(ticker: str) -> dict[str, Any]:
    """Dividend history for one security, from the stored calendar snapshot.

    Served from ``catalog_dividends`` (see dividends.py), which maps openinfo's
    market-wide calendar onto our tickers by org id. The endpoint used to ask
    openinfo to resolve the *ticker* as a company name on every request — "UNVB"
    is not a company name, so the lookup failed and the page reported
    «Дивиденды не объявлялись» while openinfo held nine payouts for that bank.
    """
    import dividends as dividends_store

    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    try:
        payload = await loop.run_in_executor(None, partial(dividends_store.dividends_for, ticker))
        return _json_safe(payload)
    except Exception as exc:
        logger.exception("dividends failed for %s", ticker)
        return {"ok": False, "ticker": ticker, "error": str(exc), "items": []}


@app.post("/api/admin/dividends/refresh")
async def api_admin_dividends_refresh(
    force: bool = False,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Re-read openinfo's dividend calendar and rewrite the snapshot.

    The read path refreshes itself once the snapshot goes stale; this is the
    handle for the collector and for a deploy that must not wait for the first
    visitor to warm the table.
    """
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(dividends_store.refresh, force=force))
    return _json_safe(result)


@app.post("/api/admin/meetings/refresh")
async def api_admin_meetings_refresh(
    force: bool = False,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Re-read openinfo's meeting-announcement window and rewrite the snapshot.

    The read path warms and refreshes itself; this is the collector's handle so
    the calendar is current before the first visitor of the day."""
    import meetings as meetings_store

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(meetings_store.refresh, force=force))
    return _json_safe(result)


@app.get("/api/admin/dividends/state")
async def api_admin_dividends_state(_: None = Depends(_require_admin)) -> dict[str, Any]:
    """How much of the calendar is stored and how old it is."""
    import dividends as dividends_store

    loop = asyncio.get_running_loop()
    return _json_safe({"ok": True, **await loop.run_in_executor(None, dividends_store.snapshot_state)})


@app.get("/api/catalog/company/{ticker}/reports")
async def api_company_reports(ticker: str) -> dict[str, Any]:
    """Return all catalog reports and cached ratios for a ticker."""
    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    reports = await loop.run_in_executor(None, partial(get_company_reports, ticker))
    import data_quality
    held_by_form = {
        form: await loop.run_in_executor(None, partial(data_quality.held_public_periods, ticker, form))
        for form in {str(report.get("report_form") or "NSBU").upper() for report in reports}
    }
    reports = [report for report in reports if (
        f"{report.get('year')}Q{report.get('quarter')}" if report.get("quarter") else str(report.get("year"))
    ) not in held_by_form.get(str(report.get("report_form") or "NSBU").upper(), set())]
    ratios = await loop.run_in_executor(None, partial(get_company_ratios_cached, ticker))
    reports = public_contract.catalog_report_contract(reports)
    return _json_safe({"ok": True, "ticker": ticker,
                       "contract_version": public_contract.CONTRACT_VERSION,
                       "new_badge_window_hours": public_contract.NEW_REPORT_HOURS,
                       "reports": reports, "ratios": ratios})


@app.get("/api/notifications")
async def api_notifications(current_user: WebUser = Depends(_require_user)) -> dict[str, Any]:
    """Personal PRO alerts plus unread feedback alerts for human admins."""
    try:
        loop = asyncio.get_running_loop()
        # Keep investment notifications a paid feature, while allowing an
        # administrator to use the same bell for operational feedback even if
        # their account's consumer subscription has expired.
        has_pro_access = bool(getattr(current_user, "has_pro_access", False))
        from admin_control.service import role_for
        is_human_admin = role_for(current_user.email) == "administrator"
        favorites = await loop.run_in_executor(
            None, partial(web_auth_store.list_favorites, current_user.id)) if has_pro_access else []
        preferences = await loop.run_in_executor(
            None, partial(web_auth_store.get_preferences, current_user.id)) if has_pro_access else {}
        tickers = [f["ticker"] for f in favorites if f.get("report_alert_enabled", True)] \
            if preferences.get("notify_reports", True) else []
        items = (await loop.run_in_executor(None, partial(get_new_reports_for_tickers, tickers, 7))) \
            if tickers else []
        listings = await loop.run_in_executor(None, get_all_listings) if favorites else {}
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
        if is_human_admin:
            from financial_ingestion.maintenance import incidents
            ingestion_alerts = await loop.run_in_executor(None, incidents)
            for incident in ingestion_alerts:
                items.append({"ticker": "ADMIN", "report_form": "DATA_PIPELINE", "year": None, "quarter": 0,
                              "title": f"Bank data: {incident['code']} — {incident['detail']}",
                              "detected_at": incident["first_seen"], "kind": "data_pipeline", "href": "/admin"})
            feedback = await loop.run_in_executor(
                None, partial(web_auth_store.list_support_requests, status="open", limit=100))
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
            None, partial(web_auth_store.notification_states, current_user.id))
        visible: list[dict[str, Any]] = []
        for raw_item in items:
            item = dict(_json_safe(raw_item))
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
        logger.exception("notifications failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/notifications/read")
async def api_notifications_read(
    payload: NotificationStateRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(web_auth_store.set_notification_state, current_user.id, payload.ids),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "updated": count}


@app.post("/api/notifications/clear")
async def api_notifications_clear(
    payload: NotificationStateRequest,
    current_user: WebUser = Depends(_require_user),
) -> dict[str, Any]:
    try:
        count = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(
                web_auth_store.set_notification_state,
                current_user.id,
                payload.ids,
                dismissed=True,
            ),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "updated": count}


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
