from __future__ import annotations



from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from functools import partial
from pydantic import BaseModel
from pydantic import Field
from typing import Any
from typing import Literal
import asyncio
import hashlib
import json
import provenance
import reports_catalog as catalog_store
import server.audit.jobs as audit_jobs
import server.auth.access as auth_access
import server.http as http


router = APIRouter()


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


@router.post("/api/admin/bonds/reference")
async def api_admin_bond_reference(payload: dict[str, Any],
                                   _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
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


@router.post("/api/admin/gov-auctions")
async def api_admin_gov_auctions(payload: AdminGovAuctionsRequest,
                                 _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """ГЦБ auction results + the key rate, pushed by the collector.

    Each row is a published placement protocol — final the day it appears, so
    the upsert overwrites rather than merges. The key rate is a history table:
    one row per change, arrival-only.
    """
    written = provenance.upsert_gov_auctions(payload.rows)
    rate_written = provenance.upsert_key_rate(payload.key_rate)
    return {"ok": True, "upserted": written, "key_rate": rate_written}


@router.post("/api/admin/bank-fx")
async def api_admin_bank_fx(payload: AdminBankFxRequest,
                            _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """Commercial-bank exchange rates from bankxizmatlari.uz, pushed hourly.

    Keyed on each bank's own stated update time, so a quiet poll — nobody
    moved a rate — writes nothing new; only an actual change lands a row.
    """
    written = provenance.upsert_bank_fx_rates(payload.rows)
    return {"ok": True, "upserted": written}


@router.post("/api/admin/trade-stats")
async def api_admin_trade_stats(
    payload: AdminTradeStatsRequest,
    _: None = Depends(auth_access._require_admin),
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
            None, partial(catalog_store.bulk_upsert_trade_stats, payload.rows, payload.trade_date))
    except Exception as exc:
        http.logger.exception("admin trade-stats upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    banked = 0
    try:
        sessions = catalog_store.trade_stats_as_history(payload.rows, payload.trade_date)
        if sessions:
            banked = await loop.run_in_executor(
                None, partial(catalog_store.bulk_upsert_quote_history, sessions))
    except Exception:  # noqa: BLE001 — the session's own numbers are already stored
        http.logger.exception("banking day statistics into quote history failed")
    audit_jobs._schedule_audit("ingest:trade-stats")
    return {"ok": True, "upserted": n, "history": banked}


@router.post("/api/admin/quotes")
async def api_admin_quotes(
    payload: AdminQuotesRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Store the exchange's own session quotes (close, previous close, change).

    `history` carries the settled daily closes the same pages published. It is
    written after the quotes and its failure is logged, not raised: the board is
    what this endpoint exists to keep current, and losing a day of sparkline
    history must not cost the session its prices.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(catalog_store.bulk_upsert_quotes, payload.rows))
    except Exception as exc:
        http.logger.exception("admin quotes upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    days = 0
    if payload.history:
        try:
            days = await loop.run_in_executor(
                None, partial(catalog_store.bulk_upsert_quote_history, payload.history))
        except Exception:  # noqa: BLE001 — history is not worth the session
            http.logger.exception("admin quote-history upsert failed")
    bars = 0
    if payload.intraday:
        try:
            bars = await loop.run_in_executor(
                None, partial(catalog_store.bulk_upsert_intraday_history, payload.intraday))
        except Exception:  # noqa: BLE001 — hourly bars are not worth the session either
            http.logger.exception("admin intraday-history upsert failed")
    audit_jobs._schedule_audit("ingest:quotes")
    return {"ok": True, "upserted": n, "history": days, "intraday": bars}


@router.post("/api/admin/financials")
async def api_admin_financials(
    payload: AdminFinancialsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Overwrite the NSBU financials cache from an externally-computed batch.

    Lets a collector running where openinfo.uz is reachable refresh this
    deployment (whose datacenter IP openinfo blocks). Authenticated via the
    ADMIN_API_SECRET shared secret in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    writer = catalog_store.bulk_replace_financials if payload.mode == "replace" else catalog_store.bulk_upsert_financials

    def _write_ratios() -> int:
        written = 0
        for r in payload.ratios:
            metrics = {k: r.get(k) for k in ("ROA", "ROE", "net_margin",
                                             "debt_ratio", "debt_to_equity")
                       if r.get(k) is not None}
            if not metrics or not r.get("ticker") or r.get("year") is None:
                continue
            catalog_store.upsert_ratio_cache(str(r["ticker"]).upper(), payload.form,
                               int(r["year"]), int(r.get("quarter") or 0), metrics)
            written += 1
        return written

    try:
        n = await loop.run_in_executor(None, partial(writer, payload.rows, payload.form))
    except Exception as exc:
        http.logger.exception("admin financials %s failed", payload.mode)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    ratios_written = 0
    if payload.ratios:
        try:
            ratios_written = await loop.run_in_executor(None, _write_ratios)
        except Exception:  # noqa: BLE001 — the sums are what the board reads
            http.logger.exception("admin financials: ratio write failed")
    audit_jobs._schedule_audit("ingest:financials")
    def _queue_sector_analysis():
        from reporting import store as report_store
        for row in payload.rows:
            ticker = str(row.get("ticker") or "").upper()
            if ticker:
                report_store.enqueue(ticker, hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest())
    await loop.run_in_executor(None, _queue_sector_analysis)
    return {"ok": True, ("replaced" if payload.mode == "replace" else "upserted"): n,
            "ratios": ratios_written}


@router.post("/api/admin/facts")
async def api_admin_facts(
    payload: AdminFactsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Ingest generic facts from an external collector (adapter output).

    Lets the ingestion job — running where openinfo is reachable (a UZ host or a
    proxy) — push the fact store to this deployment, which openinfo blocks.
    Authenticated via ADMIN_API_SECRET in the X-Admin-Secret header.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(catalog_store.upsert_facts, payload.rows))
    except Exception as exc:
        http.logger.exception("admin facts upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@router.post("/api/admin/listings")
async def api_admin_listings(
    payload: AdminListingsRequest,
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Overwrite the exchange-listing registry from an externally-computed batch.

    Lets the collector (where openinfo is reachable) push listed-but-inactive
    issuers — the ones absent from the live uzse-stock feed — so they still appear
    on the market board. Authenticated via ADMIN_API_SECRET in X-Admin-Secret.
    """
    loop = asyncio.get_running_loop()
    try:
        n = await loop.run_in_executor(None, partial(catalog_store.bulk_upsert_listings, payload.rows))
    except Exception as exc:
        http.logger.exception("admin listings upsert failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "upserted": n}


@router.get("/api/admin/openinfo-probe")
async def api_admin_openinfo_probe(
    search: str = "Hamkorbank",
    _: None = Depends(auth_access._require_admin),
) -> dict[str, Any]:
    """Live connectivity matrix: which openinfo endpoint classes THIS deployment
    can reach from its own egress IP, using the same client configuration the
    collector uses (proxy, TLS). Diagnoses full/partial IP blocks without guessing.
    """
    from openinfo_probe import run_probe

    loop = asyncio.get_running_loop()
    try:
        return http._json_safe(await loop.run_in_executor(None, partial(run_probe, search)))
    except Exception as exc:
        http.logger.exception("openinfo probe failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/admin/financial-ingestion/status")
async def api_financial_ingestion_status(_: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    from financial_ingestion.store import status
    from financial_ingestion.maintenance import incidents
    result = await asyncio.get_running_loop().run_in_executor(None, status)
    alerts = await asyncio.get_running_loop().run_in_executor(None, incidents)
    return {"ok": True, **result, "incidents": alerts}
