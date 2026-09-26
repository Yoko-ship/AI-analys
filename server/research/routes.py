from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import Response
from functools import partial
from pydantic import BaseModel
from pydantic import Field
from typing import Any
from typing import Literal
import analysis_service as analysis_service
import reporting.exports as report_exports
from reporting.disclaimer import report_disclaimer
import asyncio
import openinfo_collector as openinfo_collector
import collectors.openinfo.runner as collectors_openinfo_runner
import requests
import server.auth.access as auth_access
import server.auth.limits as auth_limits
import server.http as http
import web_auth as identity
import identity.users as identity_users


router = APIRouter()


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


@router.post("/api/company-data")
async def api_company_data(
    payload: CompanyDataRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                collectors_openinfo_runner.collect_company_data,
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
        http.logger.exception("Company data collection failed for %s", payload.company)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    result["requested_by"] = current_user.to_public_dict()
    return http._json_safe(result)


@router.post("/api/compare")
async def api_compare(
    payload: CompareRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    auth_limits._enforce_llm_quota(current_user)
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            partial(
                analysis_service.build_company_comparison,
                payload.companies,
                payload.language,
                payload.include_ai_summary,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        http.logger.exception("Company comparison failed for %s", payload.companies)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not payload.include_market_context:
        for row in (result.get("comparison") or {}).get("rows", []):
            row.pop("market_context", None)

    result["requested_by"] = current_user.to_public_dict()
    return http._json_safe(result)


class ExcelExportRequest(BaseModel):
    result: dict[str, Any]
    language: str = "ru"


@router.post("/api/analyze/export/excel")
async def api_export_excel(
    payload: ExcelExportRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> Response:
    """Export a completed analysis result to .xlsx (ТЗ §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(report_exports.build_analysis_excel, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        http.logger.exception("excel export failed")
        raise HTTPException(status_code=500, detail="Could not build the Excel file") from exc

    company = payload.result.get("company_name") or payload.result.get("input") or "analysis"
    safe = "".join(ch for ch in str(company) if ch.isalnum() or ch in "-_")[:40] or "analysis"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe}_analysis.xlsx"'},
    )


@router.post("/api/analyze/export/pdf")
async def api_export_pdf(
    payload: ExcelExportRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> Response:
    """Export a completed analysis result to PDF (ТЗ §3.13 / C5)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(report_exports.build_analysis_pdf, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        http.logger.exception("pdf export failed")
        raise HTTPException(status_code=500, detail="Could not build the PDF file") from exc

    company = payload.result.get("company_name") or payload.result.get("input") or "analysis"
    safe = "".join(ch for ch in str(company) if ch.isalnum() or ch in "-_")[:40] or "analysis"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}_analysis.pdf"'},
    )


@router.post("/api/compare/export/excel")
async def api_compare_export_excel(
    payload: ExcelExportRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> Response:
    """Export a completed comparison result to .xlsx (ТЗ §3.6 / §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(report_exports.build_comparison_excel, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        http.logger.exception("compare excel export failed")
        raise HTTPException(status_code=500, detail="Could not build the Excel file") from exc

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="comparison.xlsx"'},
    )


@router.post("/api/compare/export/pdf")
async def api_compare_export_pdf(
    payload: ExcelExportRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> Response:
    """Export a completed comparison result to PDF (ТЗ §3.6 / §3.13)."""
    from datetime import datetime

    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            partial(report_exports.build_comparison_pdf, payload.result, payload.language, datetime.now()),
        )
    except Exception as exc:
        http.logger.exception("compare pdf export failed")
        raise HTTPException(status_code=500, detail="Could not build the PDF file") from exc

    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="comparison.pdf"'},
    )


@router.post("/api/analyze")
async def api_analyze(
    payload: AnalyzeRequest,
    current_user: identity_users.WebUser = Depends(auth_access._require_pro),
) -> dict[str, Any]:
    # The regular analysis path is now deterministic and NSBU-first; it does not
    # spend LLM tokens, so an LLM quota must not block access to the report.
    try:
        result = await analysis_service.run_company_analysis(
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
        http.logger.exception("Analysis failed with value error for %s", payload.company)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        http.logger.exception("Analysis failed for %s", payload.company)
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
        "summary": analysis_service.build_summary(result),
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
            None, partial(identity.web_auth_store.research.record_analysis, current_user.id, payload.model_dump(), result))
    except Exception as exc:
        http.logger.warning("Failed to record analysis history for user %s: %s", current_user.id, exc)

    return http._json_safe(response)
