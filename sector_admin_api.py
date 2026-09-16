"""Admin exception monitoring. Registered behind the existing human role gate."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from datetime import date
from typing import Literal

import analysis_monitor
from sector_access import CAPABILITIES, role_for

router = APIRouter(prefix="/api/admin/sector-analysis", tags=["analysis monitoring"])


def actor_for(request, capability="read"):
    actor = request.state.control_actor
    if capability not in CAPABILITIES.get(actor["role"], set()):
        raise HTTPException(status_code=403, detail="Your role does not allow this action")
    return actor["email"]


class RetryRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class OverrideRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=30)
    override_template: Literal["bank", "insurance", "microfinance_bank", "microfinance",
                               "investment_fund_ifrs_annual", "commodity_exchange", "spv", "generic_nsbu",
                               "aviation", "telecom", "leasing", "cement", "metallurgy", "extractive", "trade", "transport", "industry"]
    evidence_source: str = Field(pattern=r"^https?://", max_length=2000)
    reason_code: str = Field(min_length=3, max_length=500)
    valid_from: date
    valid_to: date


@router.get("")
def overview(request: Request):
    actor_for(request)
    return {**analysis_monitor.overview(), "role": request.state.control_actor["role"],
            "capabilities": sorted(CAPABILITIES[request.state.control_actor["role"]] - {"activate", "rollback"}),
            "governed_workflow": True}


@router.get("/runs/{version}")
def run(version: str, request: Request):
    actor_for(request)
    report = analysis_monitor.get_run(version)
    if report is None:
        raise HTTPException(status_code=404, detail="Analysis version not found")
    return report


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str, payload: RetryRequest, request: Request):
    actor = actor_for(request, "retry")
    if not analysis_monitor.retry(job_id, actor, payload.reason):
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return {"ok": True, "state": "queued"}


@router.post("/overrides")
def override(payload: OverrideRequest, request: Request):
    actor_for(request, "activate")
    raise HTTPException(status_code=409, detail="USE_GOVERNED_WORKFLOW: Create and approve a versioned rule in /admin/templates.")


@router.post("/runs/{version}/rollback")
def rollback(version: str, payload: RetryRequest, request: Request):
    actor_for(request, "rollback")
    raise HTTPException(status_code=409, detail="USE_GOVERNED_WORKFLOW: Request a second reviewer in /admin/publications.")
