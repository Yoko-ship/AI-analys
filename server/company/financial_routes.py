"""Public HTTP adapter for issuer statement tables and archived evidence."""
import asyncio
import re
from functools import partial
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from server.http import _etag_json, _json_safe
from server.auth.access import _require_admin_user
import server.http as http
from . import financials

router = APIRouter()


@router.get('/api/company/{ticker}/shareholders', dependencies=[Depends(_require_admin_user)])
async def api_company_shareholders(request: Request, ticker: str) -> Response:
    from .shareholders import load
    response = _etag_json(request, await asyncio.to_thread(load, ticker), max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['Vary'] = 'Authorization'
    return response


@router.get('/api/company/{ticker}/financials/columns')
async def api_financial_columns(request: Request, ticker: str, form: str = 'NSBU',
                                scope: str | None = None, freq: str = 'annual', view: str = 'full', statement: str = 'all',
                                include_sources: bool = True, include_ratios: bool = True) -> Response:
    from financial_columns.service import load
    try:
        payload = await asyncio.to_thread(load, ticker, form=form, scope=scope, freq=freq, view=view, statement=statement,
                                          include_sources=include_sources, include_ratios=include_ratios)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _etag_json(request, payload, max_age=300)


@router.get('/api/company/{ticker}/financials/columns.{extension}')
async def api_financial_columns_export(ticker: str, extension: str, form: str = 'NSBU',
                                       scope: str | None = None, freq: str = 'annual', view: str = 'full', statement: str = 'all',
                                       layout: Literal['records', 'table'] = 'records', lang: Literal['ru', 'uz', 'en'] = 'ru',
                                       tab: Literal['summary', 'original', 'ratios'] = 'summary', from_year: int = 1900,
                                       query: str = '') -> Response:
    from financial_columns.service import load
    from financial_columns.exports import export
    if extension not in {'csv', 'xlsx'}:
        raise HTTPException(status_code=404, detail='Unknown export format')
    try:
        payload = await asyncio.to_thread(load, ticker, form=form, scope=scope, freq=freq, view=view, statement=statement,
                                          include_sources=layout != 'table', include_ratios=layout != 'table' or tab == 'ratios')
        body, media_type = await asyncio.to_thread(export, payload, extension, layout=layout, lang=lang,
                                                   tab=tab, from_year=from_year, query=query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = re.sub(r'[^A-Za-z0-9_-]', '_', ticker)[:32] or 'issuer'
    return Response(body, media_type=media_type, headers={
        'Content-Disposition': f'attachment; filename="{filename}-{form}-{freq}.{extension}"',
        'X-Content-Type-Options': 'nosniff'})


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
