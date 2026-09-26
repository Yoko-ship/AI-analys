from __future__ import annotations

import server.catalog.analysis as catalog_analysis

from company_catalog import COMPANY_CATALOG
from company_catalog import COMPANY_SECTORS
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
import analysis_service as analysis_service
import asyncio
import company_imports
import functools
import openinfo_collector as openinfo_collector
import provenance
import reports_catalog as catalog_store
import requests
import securities_catalog as securities_store
import server.auth.access as auth_access
import server.auth.limits as auth_limits
import server.catalog.jobs as catalog_jobs
import server.http as http
import server.market.board as market_board
import server.market.dates as market_dates
import server.settings as settings
import web_auth as identity


router = APIRouter()


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


@router.get("/api/companies")
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
            "logo": securities_store.resolve_logo(ticker, settings.COMPANY_LOGOS) or "",
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


@router.get("/api/periods")
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
        result = await loop.run_in_executor(None, partial(openinfo_collector.get_company_periods, company.strip()))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenInfo request failed: {exc}") from exc
    except Exception as exc:
        http.logger.exception("Periods fetch failed for %s", company)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return http._json_safe(result)


@router.get("/api/catalog/reports/summary")
async def api_catalog_reports_summary(request: Request) -> Response:
    """Counters AND the issuer list from ONE query (Дополнение 1 §Б.5).

    The header said 85 companies and the list returned 73 because they were two
    queries nobody compared. Reading both from the same statement makes them
    unable to disagree, and the catalog's own age is a stated fact rather than a
    date the reader has to subtract from today.
    """
    payload = provenance.summary()
    payload["ok"] = True
    return http._etag_json(request, payload, max_age=120)


@router.get("/api/catalog/reports/{report_id}")
async def api_catalog_report(report_id: int) -> dict[str, Any]:
    """One report: its parse state, the figures taken from it, and why it was
    rejected if it was. `used_by` answers the reverse question — is this report
    behind a number we publish?"""
    row = provenance.report(report_id)
    if not row:
        raise HTTPException(status_code=404, detail="report not found")
    return http._json_safe({"ok": True, **row})


@router.get("/api/catalog/reports/queue")
async def api_catalog_queue(limit: int = 200,
                            _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """What has not been parsed — a work queue, not a shelf of links."""
    rows = provenance.queue(max(1, min(limit, 1000)))
    return http._json_safe({"ok": True, "count": len(rows), "items": rows})


@router.get("/api/coverage")
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
        shares, bonds = await asyncio.gather(market_board._build_board("stock"), market_board._build_board("bond"))
        stocks = list(shares.get("stocks") or []) + list(bonds.get("stocks") or [])
    except Exception as exc:
        http.logger.exception("coverage: board build failed")
        raise HTTPException(status_code=502, detail="Could not load the securities feed") from exc

    coverage = await loop.run_in_executor(None, catalog_store.get_catalog_coverage)

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
        flags = await loop.run_in_executor(None, catalog_store.audit_financials_consistency)
    except Exception:
        http.logger.exception("financials consistency audit failed")
        flags = []
    # Collector heartbeat: the last completed ingestion run (pushed as a meta
    # fact) — a silently dead collector shows up here as growing data age.
    collector: dict[str, Any] = {"last_run": None, "age_hours": None, "stale": None}
    try:
        meta = await loop.run_in_executor(None, partial(catalog_store.get_facts, "_collector", "meta"))
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
        http.logger.exception("collector heartbeat read failed")
    return http._json_safe({
        "ok": True, "total": len(items), "summary": summary,
        "collector": collector,
        "financials_flags": flags, "securities": items,
    })


@router.get("/api/facts/{ticker}")
async def api_facts(ticker: str, dataset: str | None = None) -> dict[str, Any]:
    """Generic fact store for a ticker's issuer (adapter-landed data).

    Resolves the ticker to its issuer org and returns every stored fact, grouped
    by dataset/field. New source adapters surface here automatically.
    """
    ticker = ticker.strip().upper()
    loop = asyncio.get_running_loop()
    index = await loop.run_in_executor(None, partial(catalog_store.get_company_index, ticker))
    org_id = (index or {}).get("org_id")
    if not org_id:
        return {"ok": True, "ticker": ticker, "org_id": None, "facts": []}
    facts = await loop.run_in_executor(None, partial(catalog_store.get_facts, org_id, dataset))
    grouped: dict[str, dict[str, list]] = {}
    for f in facts:
        grouped.setdefault(f["dataset"], {}).setdefault(f["field"], []).append(
            {"period": f["period"], "value": f["value_num"] if f["value_num"] is not None else f["value_text"], "unit": f["unit"], "source": f["source"]}
        )
    return http._json_safe({"ok": True, "ticker": ticker, "org_id": org_id, "count": len(facts), "datasets": grouped})


@router.get("/api/listings/feed")
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
            loop.run_in_executor(None, catalog_store.get_all_listings),
            loop.run_in_executor(None, market_dates._live_last_trade_dates),
            loop.run_in_executor(None, catalog_store.get_all_trade_stats),
        )
    except Exception as exc:
        http.logger.exception("listings feed read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _mk(tk: str, lst: dict[str, Any]) -> dict[str, Any]:
        isin = str(lst.get("isin") or "").upper()
        candidates = (
            market_dates._iso_trade_date(lst.get("last_trade_date")),
            live_dates.get(tk.upper()),
            market_dates._iso_trade_date(((stats or {}).get(isin) or {}).get("trade_date")),
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
    return http._json_safe({"ok": True, "count": len(items), "listed": listed, "inactive": inactive, "inactive_days": inactive_days})


@router.get("/api/admin/catalog/issuers")
async def api_admin_catalog_issuers(
    _: None = Depends(auth_access._require_admin),
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
        http.logger.exception("issuer catalog read failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "count": len(issuers),
            "with_org_id": sum(1 for i in issuers if i.get("org_id")), "issuers": issuers}


@router.get("/api/admin/companies")
async def api_admin_companies(
    status: str | None = None,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Review queue for securities discovered from UZSE and OpenInfo."""
    try:
        return http._json_safe(company_imports.list_imports(status))
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/admin/companies/discover")
async def api_admin_companies_discover(
    force: bool = False,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Refresh the queue from the authoritative exchange/OpenInfo sources."""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.refresh_candidates, force=force, actor=current_user.email),
        )
        return http._json_safe(result)
    except (requests.RequestException, LookupError) as exc:
        raise HTTPException(status_code=502, detail=f"Company discovery failed: {exc}") from exc


@router.get("/api/admin/companies/{ticker}/preview")
async def api_admin_company_preview(
    ticker: str,
    refresh: bool = True,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Resolve one ticker and return the exact facts an admin will approve."""
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.preview_import, ticker, refresh=refresh,
                    actor=current_user.email),
        )
        return http._json_safe({"ok": True, "company": result})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"OpenInfo is unavailable: {exc}") from exc


@router.post("/api/admin/companies/{ticker}/approve")
async def api_admin_company_approve(
    ticker: str,
    payload: AdminCompanyApproveRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
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
        started = catalog_jobs._schedule_company_sync(ticker) if payload.sync else False
        return http._json_safe({"ok": True, "company": company,
                           "sync_started": started, "sync_requested": payload.sync})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/admin/companies/{ticker}/reject")
async def api_admin_company_reject(
    ticker: str,
    payload: AdminCompanyRejectRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    try:
        company = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.reject_import, ticker, actor=current_user.email,
                    note=payload.note),
        )
        return http._json_safe({"ok": True, "company": company})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/api/admin/companies/{ticker}/visibility")
async def api_admin_company_visibility(
    ticker: str,
    payload: AdminCompanyVisibilityRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Reversibly include or exclude an approved issuer from the public catalog."""
    try:
        company = await asyncio.get_running_loop().run_in_executor(
            None,
            partial(company_imports.set_catalog_visibility, ticker, payload.visible,
                    actor=current_user.email),
        )
        return http._json_safe({"ok": True, "company": company,
                           "visible": payload.visible,
                           "affected_tickers": company.get("affected_tickers", 1)})
    except company_imports.CompanyImportError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/admin/companies/{ticker}/sync")
async def api_admin_company_sync(
    ticker: str,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    metadata = company_imports.approved_metadata_map().get(ticker.upper())
    if not metadata:
        raise HTTPException(status_code=409, detail="Approve the company before syncing it")
    started = catalog_jobs._schedule_company_sync(ticker)
    return {"ok": True, "ticker": ticker.upper(), "started": started}


@router.post("/api/admin/catalog/register")
async def api_admin_catalog_register(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
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


@router.post("/api/admin/catalog-sync")
async def api_admin_catalog_sync(
    force: bool = False,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Trigger this deployment's own full catalog sync in the background.

    openinfo is reachable from the deployment itself (verify via
    /api/admin/openinfo-probe), so the org map, report catalog and sync-error
    states can be rebuilt in place — including the self-healing purge for
    tickers whose issuer resolution changed. Returns immediately; progress is
    visible in /api/coverage.
    """
    if catalog_jobs._admin_catalog_sync_running.is_set():
        return {"ok": True, "started": False, "detail": "catalog sync already running"}

    def _run() -> None:
        catalog_jobs._admin_catalog_sync_running.set()
        try:
            res = catalog_store.sync_all(force=force)
            http.logger.info("admin catalog sync done: %s",
                        {k: res.get(k) for k in ("total", "synced", "skipped") if isinstance(res, dict)})
        except Exception:
            http.logger.exception("admin catalog sync failed")
        finally:
            catalog_jobs._admin_catalog_sync_running.clear()

    asyncio.get_running_loop().run_in_executor(None, _run)
    return {"ok": True, "started": True, "force": force}


@router.post("/api/admin/catalog-watch")
async def api_admin_catalog_watch(
    hours: int = catalog_jobs.CATALOG_WATCH_WINDOW_HOURS,
    stale: int = catalog_jobs.CATALOG_WATCH_BATCH,
    force: bool = False,
    _: None = Depends(auth_access._require_admin),
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
                          older_than_hours=catalog_jobs.CATALOG_FULL_SYNC_HOURS))
    except Exception as exc:
        http.logger.exception("admin catalog watch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "filings": http._json_safe(filings), "stale": http._json_safe(stragglers)}


# ---------------------------------------------------------------------------
# Report Catalog endpoints
# ---------------------------------------------------------------------------

@router.get("/api/catalog/status")
async def api_catalog_status() -> dict[str, Any]:
    try:
        return {"ok": True, **catalog_store.get_catalog_stats()}
    except Exception as exc:
        http.logger.exception("Catalog status failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/catalog/companies")
async def api_catalog_companies() -> dict[str, Any]:
    try:
        companies = catalog_store.list_companies_with_stats()
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
            c["logo"] = imported.get("logo_url") or securities_store.resolve_logo(ticker, settings.COMPANY_LOGOS) or ""
            c["sector"] = imported.get("sector") or COMPANY_SECTORS.get(ticker, "other")
            visible_companies.append(c)
        return {"ok": True, "count": len(visible_companies), "companies": visible_companies}
    except Exception as exc:
        http.logger.exception("Catalog companies list failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/catalog/index/{ticker}")
async def api_catalog_index(ticker: str) -> dict[str, Any]:
    try:
        index = catalog_store.get_company_index(ticker.upper())
        return {"ok": True, **index}
    except Exception as exc:
        http.logger.exception("Catalog index failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/catalog/sync")
async def api_catalog_sync(
    payload: CatalogSyncRequest,
    current_user: identity.WebUser = Depends(auth_access._require_user),
    x_admin_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    # A single-ticker sync is a bounded refresh any signed-in user may run; the
    # FULL catalog scrape is minutes of upstream traffic and admin-only
    # (X-Admin-Secret, same as /api/admin/catalog-sync).
    if not payload.ticker:
        auth_access._require_admin(x_admin_secret)
    loop = asyncio.get_running_loop()
    try:
        if payload.ticker:
            ticker = payload.ticker.upper()
            imported = company_imports.approved_metadata_map().get(ticker) or {}
            company_name = (catalog_store._TICKER_TO_NAME.get(ticker)
                            or imported.get("company_name"))
            if not company_name:
                raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
            result = await loop.run_in_executor(
                None, partial(catalog_store.sync_company, ticker, company_name, force=payload.force,
                              org_id=imported.get("org_id"))
            )
        else:
            result = await loop.run_in_executor(
                None, partial(catalog_store.sync_all, force=payload.force)
            )
        return {"ok": True, **http._json_safe(result)}
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("Catalog sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/api/catalog/analyze")
async def api_catalog_analyze(
    payload: CatalogAnalyzeRequest,
    current_user: identity.WebUser = Depends(auth_access._require_user),
) -> dict[str, Any]:
    ticker = payload.ticker.upper()
    loop = asyncio.get_running_loop()
    approved = await loop.run_in_executor(None, company_imports.approved_metadata_map)
    company_name = catalog_store._TICKER_TO_NAME.get(ticker) or (approved.get(ticker) or {}).get("company_name") or ticker
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
                    None, partial(catalog_store.build_cached_catalog_dynamics, ticker, payload.form)
                )
                if not dynamics.get("years") and not dynamics.get("quarterly"):
                    raise HTTPException(
                        status_code=404,
                        detail=catalog_analysis._catalog_no_cached_data(payload.language, payload.form, period),
                    )
                return http._json_safe({
                    "ok": True, "analysis_type": "dynamics", "ticker": ticker,
                    "company_name": company_name, "year": payload.year,
                    "quarter": payload.quarter, "sector": sector,
                    "data_source": "verified_cache", **dynamics,
                })

            current = await loop.run_in_executor(
                None, partial(catalog_store.get_cached_catalog_period, ticker, payload.form,
                              payload.year, payload.quarter)
            )
            if not current.get("has_data"):
                raise HTTPException(
                    status_code=404,
                    detail=catalog_analysis._catalog_no_cached_data(payload.language, payload.form, period),
                )

            if payload.analysis_type == "ratio":
                previous = await loop.run_in_executor(
                    None, partial(catalog_store.get_cached_catalog_period, ticker, payload.form,
                                  payload.year - 1, payload.quarter)
                )
                sector_peers = [t for t, peer_sector in sectors.items()
                                if peer_sector == sector and t != ticker] if sector else []
                sector_avg: dict[str, Any] = {}
                if sector_peers:
                    try:
                        sector_avg = await loop.run_in_executor(
                            None, partial(catalog_store.get_sector_averages, sector_peers,
                                          payload.form, payload.year)
                        )
                    except Exception:
                        pass
                return http._json_safe({
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
                    None, partial(catalog_store.get_cached_catalog_period, ticker, payload.form,
                                  compare_year, compare_quarter)
                )
                compare_period = (f"{compare_year}Q{compare_quarter}"
                                  if compare_quarter else str(compare_year))
                if not compared.get("has_data"):
                    raise HTTPException(
                        status_code=404,
                        detail=catalog_analysis._catalog_no_cached_data(
                            payload.language, payload.form, compare_period),
                    )
                return http._json_safe({
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
                None, partial(catalog_store.get_cached_catalog_period, ticker, payload.form,
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
                compare_name = (catalog_store._TICKER_TO_NAME.get(compare_ticker)
                                or (approved.get(compare_ticker) or {}).get("company_name")
                                or compare_ticker)
                compared = await loop.run_in_executor(
                    None, partial(catalog_store.get_cached_catalog_period, compare_ticker, payload.form,
                                  payload.year, payload.quarter)
                )
                if not compared.get("has_data"):
                    raise HTTPException(
                        status_code=404,
                        detail=catalog_analysis._catalog_no_cached_data(payload.language, payload.form, period),
                    )

            sections = catalog_analysis._catalog_nonfinance_sections(
                payload.analysis_type, company_name, period, current, previous,
                payload.language, compare_name=compare_name, compare=compared,
            )
            if not sections:
                raise HTTPException(status_code=400, detail="Unsupported analysis type")
            return http._json_safe({
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
                loop.run_in_executor(None, partial(catalog_store.fetch_report_excel_data, ticker, payload.form, payload.year, payload.quarter)),
                loop.run_in_executor(None, partial(catalog_store.fetch_report_excel_data, ticker, payload.form, prev_year, payload.quarter)),
            )
            if not excel.get("ok"):
                raise HTTPException(status_code=400, detail=excel.get("error") or "Could not fetch report")
            ratios = catalog_store.compute_financial_ratios(excel.get("income"), excel.get("balance"))
            ratios_prev = catalog_store.compute_financial_ratios(excel_prev.get("income"), excel_prev.get("balance")) if excel_prev.get("ok") else {}
            # Cache ratios for sector averaging
            if ratios.get("metrics"):
                try:
                    await loop.run_in_executor(None, partial(catalog_store.upsert_ratio_cache, ticker, payload.form, payload.year, payload.quarter, ratios["metrics"]))
                except Exception:
                    pass
            # Approved imports extend the legacy static sector map immediately.
            sector_peers = [t for t, s in sectors.items() if s == sector and t != ticker] if sector else []
            sector_avg: dict = {}
            if sector_peers:
                try:
                    sector_avg = await loop.run_in_executor(None, partial(catalog_store.get_sector_averages, sector_peers, payload.form, payload.year))
                except Exception:
                    pass
            return http._json_safe({
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
                None, partial(catalog_store.build_dynamics_data, ticker, payload.form)
            )
            return http._json_safe({"ok": True, "analysis_type": "dynamics", "ticker": ticker, **dynamics})

        if payload.analysis_type in ("quarter_compare", "annual_compare"):
            q2 = payload.compare_quarter if payload.compare_quarter is not None else payload.quarter
            y2 = payload.compare_year or (payload.year - 1)
            excel1, excel2 = await asyncio.gather(
                loop.run_in_executor(None, partial(catalog_store.fetch_report_excel_data, ticker, payload.form, payload.year, payload.quarter)),
                loop.run_in_executor(None, partial(catalog_store.fetch_report_excel_data, ticker, payload.form, y2, q2)),
            )
            ratios1 = catalog_store.compute_financial_ratios(excel1.get("income"), excel1.get("balance")) if excel1.get("ok") else {}
            ratios2 = catalog_store.compute_financial_ratios(excel2.get("income"), excel2.get("balance")) if excel2.get("ok") else {}
            return http._json_safe({
                "ok": True, "analysis_type": payload.analysis_type, "ticker": ticker,
                "period1": {"year": payload.year, "quarter": payload.quarter, "form": payload.form, **ratios1},
                "period2": {"year": y2, "quarter": q2, "form": payload.form, **ratios2},
            })

        if payload.analysis_type == "multi_company":
            auth_limits._enforce_llm_quota(current_user)
            compare_ticker = (payload.compare_ticker or "").upper()
            compare_name = (catalog_store._TICKER_TO_NAME.get(compare_ticker)
                            or (approved.get(compare_ticker) or {}).get("company_name")
                            or compare_ticker)
            if not compare_name:
                raise HTTPException(status_code=400, detail="compare_ticker is required")
            result = await loop.run_in_executor(
                None, partial(analysis_service.build_company_comparison, [company_name, compare_name], payload.language, True)
            )
            return http._json_safe({"ok": True, "analysis_type": "multi_company", **result})

        # AI-based: financial / swot / recommendation
        auth_limits._enforce_llm_quota(current_user)
        period_type = "quarterly" if payload.quarter > 0 else "annual"
        result = await analysis_service.run_company_analysis(
            company_name,
            language=payload.language,
            report_analysis_type=period_type,
            report_quarter=payload.quarter if payload.quarter > 0 else None,
            report_current_year=payload.year,
            report_previous_year=payload.year - 1,
            report_form=form_map.get(payload.form, "NAS"),
        )
        return http._json_safe({
            "ok": True, "analysis_type": payload.analysis_type, "ticker": ticker,
            "company_name": result.get("company_name"),
            "year": payload.year, "quarter": payload.quarter, "language": payload.language,
            "sections": result.get("sections", {}),
            "metrics": result.get("metrics"),
            "summary": analysis_service.build_summary(result),
            "article_report": result.get("article_report"),
            "report_tables": result.get("report_tables"),
        })

    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("Catalog analyze failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/admin/companies/search")
async def api_admin_companies_search(
    q: str,
    limit: int = 12,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Small, live issuer lookup used by operational admin controls."""
    return http._json_safe({"ok": True, "items": await asyncio.get_running_loop().run_in_executor(
        None, partial(company_imports.search_companies, q, limit))})
