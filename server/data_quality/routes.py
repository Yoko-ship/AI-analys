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
import server.auth.access as auth_access
import server.http as http
import web_auth as identity

router = APIRouter()


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


@router.get("/api/admin/data-quality/issues")
async def api_data_quality_issues(
    status: Literal["open", "resolved", "ignored"] | None = None,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Persisted review queue; reading it never alters source financial rows."""
    import data_quality
    return http._json_safe(await asyncio.get_running_loop().run_in_executor(
        None, partial(data_quality.list_issues, status)))


@router.post("/api/admin/data-quality/scan")
async def api_data_quality_scan(
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Run the deterministic financial completeness/balance checks on demand."""
    import data_quality
    return http._json_safe(await asyncio.get_running_loop().run_in_executor(
        None, data_quality.scan_financial_issues))


@router.post("/api/admin/data-quality/companies/{ticker}/refresh")
async def api_data_quality_refresh_company_reporting(
    ticker: str,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Re-import one issuer's official filings and re-parse its latest NSBU data."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.refresh_company_reporting, ticker, current_user.email))
        return http._json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/api/admin/data-quality/analysis/{ticker}/scan")
async def api_data_quality_analysis_scan(
    ticker: str,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Run the public company analysis gate for one issuer and persist blockers."""
    import data_quality
    try:
        return http._json_safe(await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.scan_analysis_issue, ticker)))
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/admin/data-quality/corrections")
async def api_data_quality_corrections(
    ticker: str | None = None,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    import data_quality
    return http._json_safe(await asyncio.get_running_loop().run_in_executor(
        None, partial(data_quality.list_corrections, ticker)))


@router.post("/api/admin/data-quality/publication-holds")
async def api_data_quality_publication_hold(
    payload: PublicationHoldRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Temporarily hide a filing from public report and quarterly-finance tabs."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.set_publication_hold, **payload.model_dump(), actor=current_user.email))
        return http._json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.get("/api/admin/data-quality/issues/{issue_id}/suggestion")
async def api_data_quality_suggestion(
    issue_id: str,
    _: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Calculate an editable proposal; it never writes or approves a correction."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.suggest_correction, issue_id))
        return http._json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@router.post("/api/admin/data-quality/issues/{issue_id}/apply")
async def api_data_quality_apply_issue(
    issue_id: str,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Apply the calculated correction and its linked report evidence in one click."""
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.auto_apply_issue, issue_id, current_user.email))
        return http._json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/api/admin/data-quality/issues/{issue_id}/apply-unit-scale")
async def api_data_quality_apply_unit_scale(
    issue_id: str,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Apply the verified 1,000× Form-2 unit conversion and recheck it."""
    import data_quality
    try:
        result = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.auto_apply_unit_scale_issue, issue_id, current_user.email))
        return http._json_safe(result)
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/api/admin/data-quality/corrections")
async def api_data_quality_create_correction(
    payload: DataCorrectionRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.create_correction, payload.model_dump(), current_user.email))
        return http._json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/api/admin/data-quality/corrections/apply")
async def api_data_quality_apply_correction(
    payload: DataCorrectionRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    """Apply a manually edited correction immediately, retaining the audit record."""
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.apply_correction, payload.model_dump(), current_user.email))
        return http._json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@router.post("/api/admin/data-quality/corrections/{correction_id}/review")
async def api_data_quality_review_correction(
    correction_id: str,
    payload: DataCorrectionReviewRequest,
    current_user: identity.WebUser = Depends(auth_access._require_admin_user),
) -> dict[str, Any]:
    import data_quality
    try:
        record = await asyncio.get_running_loop().run_in_executor(
            None, partial(data_quality.review_correction, correction_id, payload.status,
                          current_user.email, payload.note))
        return http._json_safe({"ok": True, "correction": record})
    except data_quality.DataQualityError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
