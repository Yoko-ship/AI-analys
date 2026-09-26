from __future__ import annotations



from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import Response
from typing import Any
import asyncio
import bond_registry
import bonds
import provenance
import server.bonds.quality as bonds_quality
import server.http as http
import server.market.valuations as market_valuations


router = APIRouter()


@router.get("/api/bonds")
async def api_bonds(request: Request) -> Response:
    """The bond contour (Дополнение 1 §А.6).

    Twelve issues trade genuinely and appeared nowhere in the interface. They get
    their own section with the metrics that CAN be computed honestly from what
    the sources publish: the par from the exchange, the coupon from the issuer's
    own payment filings, and an explicit `no_bond_reference` for the discounting
    metrics, which need a redemption date nobody files until they redeem.
    """
    try:
        inputs = await market_valuations._market_inputs()
        references, coupons = provenance.bond_references(), provenance.bond_coupons()
        quality = await bonds_quality._bond_history_quality(inputs)
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
                                         stats=inputs["stats"], gov_points=gov_points,
                                         histories=await bonds_quality._bond_price_histories(inputs, references))
        payload["ok"] = True
        payload["trade_date"] = inputs["trade_date"]
        payload["gov_curve"] = gov_points
        payload["key_rate"] = key_rate
        return http._etag_json(request, payload, max_age=60)
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("bonds failed")
        raise HTTPException(status_code=502, detail="bonds unavailable") from exc


@router.get("/api/bonds/curve")
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
        return http._etag_json(request, payload, max_age=300)
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("bonds curve failed")
        raise HTTPException(status_code=502, detail="bonds curve unavailable") from exc


@router.get("/api/bonds/calendar")
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
        return http._etag_json(request, payload, max_age=600)
    except HTTPException:
        raise
    except Exception as exc:
        http.logger.exception("bonds calendar failed")
        raise HTTPException(status_code=502, detail="bonds calendar unavailable") from exc


@router.get("/api/bonds/{ticker}")
async def api_bond_detail(ticker: str) -> dict[str, Any]:
    ticker = ticker.upper()
    inputs = await market_valuations._market_inputs()
    references, coupons = provenance.bond_references(), provenance.bond_coupons()
    quality = await bonds_quality._bond_history_quality(inputs)
    gov_points = bonds.gov_curve_points(provenance.gov_auctions())
    key_rate = provenance.key_rate()
    payload = bonds.build_bond_board(inputs["board"], inputs["securities"],
                                     references, coupons, quality,
                                     key_rate=(key_rate or {}).get("rate"),
                                     stats=inputs["stats"], gov_points=gov_points,
                                     histories=await bonds_quality._bond_price_histories(inputs, references))
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
    return http._json_safe({"ok": True, **row, **issuer_context, "coupons": coupons.get(ticker, []),
                       "assessments": assessments, "monitoring_points": monitoring_points[:2],
                       # The whole payment schedule of THIS issue — filed where
                       # the issuer filed it, reconstructed from the register's
                       # cycle everywhere else. Served on the card only: the
                       # board would carry sixty-five of these for nothing.
                       "schedule_flows": schedule_flows,
                       "gov_curve": gov_points, "key_rate": key_rate,
                       "board_day": payload.get("board_day")})


@router.get("/api/bonds/{ticker}/coupons")
async def api_bond_coupons(ticker: str) -> dict[str, Any]:
    rows = provenance.bond_coupons().get(ticker.upper(), [])
    return http._json_safe({"ok": True, "ticker": ticker.upper(), "count": len(rows), "items": rows})
