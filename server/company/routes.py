from __future__ import annotations



from backtest import walk_forward_annual
from company_catalog import COMPANY_CATALOG
from company_catalog import COMPANY_SECTORS
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import Response
from forecast_engine import build_forecast
from functools import partial
from technical_backtest import run_sma20_backtest
from typing import Any
import asyncio
import company_imports
import corporate_actions
import public_contract
import reports_catalog as catalog_store
import securities_catalog as securities_store
import server.auth.access as auth_access
import server.http as http
import server.market.history as market_history
import soliq_company
import web_auth as identity


router = APIRouter()


@router.get("/api/securities")
async def api_securities() -> dict[str, Any]:
    """Return the full securities map {ticker: info}."""
    try:
        loop = asyncio.get_running_loop()
        smap = await loop.run_in_executor(None, securities_store.get_securities_map)
        return {"ok": True, "count": len(smap), "securities": smap}
    except Exception as exc:
        http.logger.exception("securities map failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/company/{ticker}/forecast")
async def api_company_forecast(ticker: str, form: str = "NSBU",
                               _: identity.WebUser = Depends(auth_access._require_pro)) -> dict[str, Any]:
    """Three transparent business scenarios and a comparable-multiple range."""
    ticker, form = ticker.strip().upper(), str(form or "NSBU").strip().upper()
    if form not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    loop = asyncio.get_running_loop()
    annual, all_fin, listings = await asyncio.gather(
        loop.run_in_executor(None, partial(catalog_store.get_financials_series, ticker, form)),
        loop.run_in_executor(None, partial(catalog_store.get_all_financials, form)),
        loop.run_in_executor(None, catalog_store.get_all_listings),
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
            pe = float(price) * float(shares) / (float(income) * catalog_store.NSBU_THOUSANDS_UZS)
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
    return http._json_safe({"ok": True, **result})


@router.get("/api/company/{ticker}/forecast/backtest")
async def api_company_forecast_backtest(ticker: str, form: str = "NSBU",
                                        _: identity.WebUser = Depends(auth_access._require_pro)) -> dict[str, Any]:
    form = str(form or "NSBU").strip().upper()
    if form not in {"NSBU", "MSFO"}:
        raise HTTPException(status_code=422, detail="form must be NSBU or MSFO")
    ticker = ticker.strip().upper()
    loop = asyncio.get_running_loop()
    annual, reports = await asyncio.gather(
        loop.run_in_executor(None, partial(catalog_store.get_financials_series, ticker, form)),
        loop.run_in_executor(None, partial(catalog_store.get_company_reports, ticker)),
    )
    published_by_year = {
        str(row.get("year")): row.get("published_at")
        for row in reports
        if str(row.get("report_form") or "").upper() == form
        and str(row.get("period_type") or "").lower() == "annual"
        and row.get("year") is not None and row.get("published_at")
    }
    return http._json_safe({"ok": True, "ticker": ticker.strip().upper(), "standard": form,
                       "publication_dates": published_by_year,
                       **walk_forward_annual(annual, publication_dates=published_by_year)})


@router.get("/api/company/{ticker}/technical-backtest")
async def api_company_technical_backtest(
    ticker: str, _: identity.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    """Run the disclosed technical rule against stored confirmed sessions only."""
    ticker = ticker.strip().upper()
    isin = await market_history._resolve_isin(ticker)
    if not isin:
        raise HTTPException(status_code=404, detail="ISIN not found")
    isin = str(isin).upper()
    history = await asyncio.get_running_loop().run_in_executor(
        None, partial(catalog_store.get_quote_history, [isin], 3650))
    result = await asyncio.get_running_loop().run_in_executor(
        None, partial(run_sma20_backtest, history.get(isin, [])))
    return http._json_safe({"ok": True, "ticker": ticker, "isin": isin,
                       "source": "stored confirmed exchange sessions", **result})


@router.get("/api/quotes/series")
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
        return http._etag_json(request, {"ok": True, "days": days, "count": 0, "series": {}}, max_age=300)
    try:
        loop = asyncio.get_running_loop()
        smap = await loop.run_in_executor(None, securities_store.get_securities_map)
        isin_of = {t: (smap.get(t) or {}).get("isin") for t in wanted}
        codes = [i for i in isin_of.values() if i]
        history = await loop.run_in_executor(None, partial(catalog_store.get_quote_history, codes, days))
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
        return http._etag_json(request, {"ok": True, "days": days, "count": len(series),
                                    "series": series}, max_age=300)
    except Exception as exc:
        http.logger.exception("quote series failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/company/{ticker}/splits")
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


@router.get("/api/company/{ticker}/registry")
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
        http.logger.error("company registry configuration error: %s", exc)
        raise HTTPException(status_code=503, detail="Company registry is not configured") from exc
    except soliq_company.CompanyIdentityNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except soliq_company.SoliqUpstreamError as exc:
        http.logger.warning("Soliq company registry failed for %s: %s", ticker, exc)
        raise HTTPException(status_code=502, detail="Company registry is temporarily unavailable") from exc
    return http._json_safe({"ok": True, **result})


@router.get("/api/securities/{ticker}/info")
async def api_securities_info(ticker: str, language: str = "ru") -> dict[str, Any]:
    """Return company info including Wikipedia extract for a ticker."""
    ticker = ticker.upper()
    try:
        loop = asyncio.get_running_loop()
        smap, approved, listings = await asyncio.gather(
            loop.run_in_executor(None, securities_store.get_securities_map),
            loop.run_in_executor(None, company_imports.approved_metadata_map),
            loop.run_in_executor(None, catalog_store.get_all_listings),
        )
        sec = dict(smap[ticker]) if smap.get(ticker) else None
        listing = (listings or {}).get(ticker) or {}
        if sec and listing:
            # A live catalog identity can still lack registry metadata. Fill
            # missing fields without replacing its current price or identity.
            for field in ("listing_date", "shares_outstanding", "nominal", "market_cap"):
                if sec.get(field) is None and listing.get(field) is not None:
                    sec[field] = listing[field]
            for field in ("company_name", "security_name"):
                if not sec.get(field) and listing.get("name"):
                    sec[field] = listing["name"]
        if not sec:
            # The securities map is filled from the live trading feed only, so
            # listed-but-inactive securities (present in the RFB registry) used
            # to 404 into a blank company page. Serve their registry data.
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
            None, partial(securities_store.get_wiki_info, ticker, sec.get("company_name") or sec.get("security_name") or "", language)
        )
        return {"ok": True, "ticker": ticker, "security": sec, "wiki": wiki}
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("securities info failed for %s", ticker)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/catalog/company/{ticker}/reports")
async def api_company_reports(ticker: str) -> dict[str, Any]:
    """Return all catalog reports and cached ratios for a ticker."""
    ticker = ticker.upper()
    loop = asyncio.get_running_loop()
    reports = await loop.run_in_executor(None, partial(catalog_store.get_company_reports, ticker))
    import data_quality
    held_by_form = {
        form: await loop.run_in_executor(None, partial(data_quality.held_public_periods, ticker, form))
        for form in {str(report.get("report_form") or "NSBU").upper() for report in reports}
    }
    reports = [report for report in reports if (
        f"{report.get('year')}Q{report.get('quarter')}" if report.get("quarter") else str(report.get("year"))
    ) not in held_by_form.get(str(report.get("report_form") or "NSBU").upper(), set())]
    ratios = await loop.run_in_executor(None, partial(catalog_store.get_company_ratios_cached, ticker))
    reports = public_contract.catalog_report_contract(reports)
    return http._json_safe({"ok": True, "ticker": ticker,
                       "contract_version": public_contract.CONTRACT_VERSION,
                       "new_badge_window_hours": public_contract.NEW_REPORT_HOURS,
                       "reports": reports, "ratios": ratios})
