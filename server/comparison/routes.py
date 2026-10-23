"""Public, bounded comparison reads over existing stored financial evidence."""
import asyncio
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
import logging
import web_auth
import server.auth.access as auth_access
from identity.comparisons import clean, ComparisonChanged
from openpyxl import Workbook
import server.http as http
from . import service, updates

router = APIRouter()
logger = logging.getLogger(__name__)


class SavedComparisonRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    tickers: list[str] = Field(min_length=2, max_length=4)
    period: str = Field(default='latest', max_length=12)
    standard: Literal['NSBU', 'IFRS'] = 'NSBU'
    scope: Literal['separate', 'consolidated'] = 'separate'
    unit: Literal['billion', 'million'] = 'billion'

    @model_validator(mode='after')
    def valid_selection(self):
        clean(self.model_dump())
        return self


async def saved_call(fn, *args):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=15)
    except ComparisonChanged as exc:
        return JSONResponse({'detail': str(exc)}, status_code=409, headers={'Cache-Control': 'no-store'})
    except ValueError as exc:
        return JSONResponse({'detail': str(exc)}, status_code=422, headers={'Cache-Control': 'no-store'})
    except Exception:
        logger.exception('Saved comparison storage failed')
        return JSONResponse({'detail': 'Saved comparisons are temporarily unavailable'}, status_code=503,
                            headers={'Cache-Control': 'no-store'})


@router.get('/api/saved-comparisons')
async def api_saved_comparisons(current_user=Depends(auth_access._require_user)):
    entries = await saved_call(web_auth.web_auth_store.comparisons.list, current_user.id)
    if isinstance(entries, Response): return entries
    return JSONResponse({'ok': True, 'comparisons': entries}, headers={'Cache-Control': 'no-store'})


@router.post('/api/saved-comparisons')
async def api_save_comparison(payload: SavedComparisonRequest, current_user=Depends(auth_access._require_user)):
    entry = await saved_call(updates.save, web_auth.web_auth_store.comparisons, current_user.id, payload.model_dump())
    if isinstance(entry, Response): return entry
    return JSONResponse({'ok': True, 'comparison': entry}, headers={'Cache-Control': 'no-store'})


class ComparisonSeenRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_key: str = Field(pattern=r'^[a-f0-9]{64}$')
    baseline_key: str = Field(pattern=r'^(?:none|[a-f0-9]{64})$')


@router.get('/api/saved-comparisons/{comparison_id}/updates')
async def api_comparison_updates(comparison_id: int = Path(ge=1, le=9223372036854775807), current_user=Depends(auth_access._require_user)):
    result = await saved_call(updates.inspect, web_auth.web_auth_store.comparisons, current_user.id, comparison_id)
    if isinstance(result, Response): return result
    return JSONResponse(result if result else {'detail': 'Comparison not found'}, status_code=200 if result else 404,
                        headers={'Cache-Control': 'no-store'})


@router.post('/api/saved-comparisons/{comparison_id}/seen')
async def api_comparison_seen(payload: ComparisonSeenRequest, comparison_id: int = Path(ge=1, le=9223372036854775807), current_user=Depends(auth_access._require_user)):
    result = await saved_call(updates.seen, web_auth.web_auth_store.comparisons, current_user.id, comparison_id,
                              payload.snapshot_key, payload.baseline_key)
    if isinstance(result, Response): return result
    return JSONResponse({'ok': True, **result} if result else {'detail': 'Comparison not found'}, status_code=200 if result else 404,
                        headers={'Cache-Control': 'no-store'})


@router.delete('/api/saved-comparisons/{comparison_id}')
async def api_delete_saved_comparison(comparison_id: int = Path(ge=1, le=9223372036854775807), current_user=Depends(auth_access._require_user)):
    deleted = await saved_call(web_auth.web_auth_store.comparisons.delete, current_user.id, comparison_id)
    if isinstance(deleted, Response): return deleted
    return JSONResponse({'ok': True} if deleted else {'detail': 'Comparison not found'},
                        status_code=200 if deleted else 404, headers={'Cache-Control': 'no-store'})


async def run(fn, *args):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=30)
    except service.UnknownCompany as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=503, detail='Comparison data is temporarily unavailable') from exc


@router.get('/api/company-comparison/options')
async def api_company_comparison_options(request: Request, tickers: str = Query('', max_length=100),
    standard: Literal['NSBU', 'IFRS'] = 'NSBU', scope: Literal['separate', 'consolidated'] = 'separate'):
    return http._etag_json(request, await run(service.options, tickers, standard, scope), max_age=60)


@router.get('/api/company-comparison')
async def api_company_comparison(request: Request, tickers: str = Query(..., max_length=100),
    period: str = Query('latest', max_length=12), standard: Literal['NSBU', 'IFRS'] = 'NSBU',
    scope: Literal['separate', 'consolidated'] = 'separate'):
    return http._etag_json(request, await run(service.compare, tickers, period, standard, scope), max_age=60)


def excel(data):
    book = Workbook()
    table = book.active
    table.title = 'Comparison'
    columns = data['companies']
    table.append(['Metric', *[c['ticker'] for c in columns]])
    for key in service.METRICS:
        table.append([key, *[c['metrics'][key]['value'] for c in columns]])
    table.freeze_panes = 'B2'
    table.column_dimensions['A'].width = 26
    from openpyxl.utils import get_column_letter
    for index in range(2, len(columns) + 2):
        table.column_dimensions[get_column_letter(index)].width = 23
    context = book.create_sheet('Context')
    for key in ['period', 'period_basis', 'standard', 'scope', 'currency', 'generated_at']:
        context.append([key, data.get(key)])
    context.append(['amount_unit', 'UZS; percentages in %, valuation multiples in x'])
    sources = book.create_sheet('Sources')
    sources.append(['Ticker', 'Metric', 'Status', 'Financial period', 'Market date', 'Source', 'Formula', 'Valuation basis'])
    for column in columns:
        for key, cell in column['metrics'].items():
            source = cell.get('source') or {}
            sources.append([column['ticker'], key, cell.get('status'), cell.get('period'), cell.get('as_of') or column.get('market_as_of'),
                            source.get('url'), cell.get('formula'), cell.get('base_period')])
    for sheet in book:
        for cell in sheet[1]:
            from openpyxl.styles import Font
            cell.font = Font(bold=True)
        sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    book.save(output)
    return output.getvalue()


@router.get('/api/company-comparison/export.xlsx')
async def api_company_comparison_excel(tickers: str = Query(..., max_length=100), period: str = Query('latest', max_length=12),
    standard: Literal['NSBU', 'IFRS'] = 'NSBU', scope: Literal['separate', 'consolidated'] = 'separate'):
    data = await run(service.compare, tickers, period, standard, scope)
    content = await asyncio.to_thread(excel, data)
    return Response(content, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition': 'attachment; filename="uzstock-comparison.xlsx"', 'Cache-Control': 'no-store'})
