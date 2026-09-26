"""Public HTTP adapter for issuer statement tables and archived evidence."""
import asyncio
import re
from functools import partial
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from server.http import _etag_json, _json_safe
import server.http as http
from . import financials

router = APIRouter()


@router.get("/api/company/{ticker}/financials/passport")
async def api_company_financial_passport(
    ticker: str, period: str, field: str, form: str = "NSBU", scope: str | None = None,
) -> dict[str, Any]:
    try:
        return _json_safe(await financials.financial_passport(ticker, period, field, form, scope))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/company/{ticker}/financials")
async def api_company_financials(
    request: Request, ticker: str, freq: str = "annual", form: str = "NSBU", scope: str | None = None,
) -> Response:
    try:
        payload = await financials.financial_series(ticker, freq, form, scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except financials.FinancialDataUnavailable as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _etag_json(request, payload, max_age=300)


@router.get("/api/company/{ticker}/financials/documents/{sha}")
async def api_financial_document(ticker: str, sha: str) -> Response:
    from financial_ingestion.documents import issuer_artifact
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        payload = await asyncio.get_running_loop().run_in_executor(None, partial(issuer_artifact, ticker, sha))
    except (OSError, ValueError) as exc:
        http.logger.error("Archived financial document unavailable: %s", exc)
        raise HTTPException(status_code=503, detail="Archived document integrity/unavailability error") from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return Response(payload, media_type="application/pdf", headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Disposition": f'inline; filename="{sha}.pdf"',
        "X-Content-Type-Options": "nosniff",
    })
