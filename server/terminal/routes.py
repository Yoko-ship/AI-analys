"""HTTP face of the terminal journal.

* ``POST /api/terminal/events``: the terminal's beacon. It is public, because
  guests use the terminal too. It accepts only the events a browser can
  witness, and always answers 204: a journal failure must never show up in a
  user's console. The user id comes only from a Bearer token the server
  resolves, never from the body.
* ``/api/admin/terminal/*``: reads for the admin «Терминал» section. Mounted
  behind the human-admin gate in api.py.
"""
from __future__ import annotations

import asyncio
from functools import partial
import json
import logging
import re
from typing import Any
from typing import Literal

from fastapi import APIRouter, Query, Request, Response

import server.auth.limits as auth_limits
from server.terminal import journal
from web_auth import web_auth_store

logger = logging.getLogger(__name__)

public_router = APIRouter()
admin_router = APIRouter()

# What a browser can see happen. Data, load and AI events are written by the
# server only, so a page cannot forge a quarantine or a load failure.
CLIENT_EVENTS = frozenset({"cmd_run", "cmd_unknown", "export", "screen_error", "screen_slow"})

_MAX_BYTES = 8192
_MAX_EVENTS = 20
_PER_MINUTE = 120

_TICKER = re.compile(r"^[A-Za-z0-9]{1,12}$")
_FUNCTION = re.compile(r"^[A-Za-z]{1,8}$")
_STANDARDS = {"NSBU", "MSFO", "IFRS"}
_PERIOD = re.compile(r"^[0-9A-Za-z\- ]{1,16}$")
_ERROR_ID = re.compile(r"^[0-9A-Za-z_\-]{1,64}$")


def _field(value: Any, pattern: re.Pattern) -> str | None:
    return value if isinstance(value, str) and pattern.match(value) else None


def clean_client_event(raw: Any) -> dict[str, Any] | None:
    """One beacon item, reduced to what the journal accepts, or None."""
    if not isinstance(raw, dict) or raw.get("event") not in CLIENT_EVENTS:
        return None
    standard = raw.get("standard")
    duration = raw.get("duration_ms")
    message = raw.get("message")
    return {
        "event": raw["event"],
        "ticker": _field(raw.get("ticker"), _TICKER),
        "function": (_field(raw.get("function"), _FUNCTION) or "").upper() or None,
        "standard": standard.upper() if isinstance(standard, str) and standard.upper() in _STANDARDS else None,
        "period": _field(raw.get("period"), _PERIOD),
        "error_id": _field(raw.get("error_id"), _ERROR_ID),
        "duration_ms": duration if isinstance(duration, (int, float)) and 0 <= duration < 3_600_000 else None,
        # An unknown command is kept as typed (short), which is how the PM
        # sees what people look for and do not find.
        "message": message[:200] if isinstance(message, str) else "",
    }


async def _user(request: Request):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        return await asyncio.get_running_loop().run_in_executor(
            None, web_auth_store.sessions.get_user_by_token, token.strip())
    except Exception:
        logger.debug("terminal beacon bearer could not be resolved", exc_info=True)
        return None


@public_router.post("/api/terminal/events", status_code=204)
async def api_terminal_events(request: Request) -> Response:
    try:
        body = await request.body()
        if not body or len(body) > _MAX_BYTES:
            return Response(status_code=204)
        data = json.loads(body)
        items = data.get("events") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return Response(status_code=204)
        ip = auth_limits._client_ip(request)
        user = await _user(request)
        internal = False
        if user:
            from identity.users import is_admin_email

            internal = is_admin_email(user.email)
        for raw in items[:_MAX_EVENTS]:
            event = clean_client_event(raw)
            if event is None:
                continue
            if not auth_limits._rate_limiter.allow(f"terminal-events:{ip}", _PER_MINUTE, 60.0):
                break
            journal.emit(event.pop("event"), user_id=user.id if user else None,
                         internal=internal, **event)
    except Exception:
        logger.debug("terminal beacon rejected", exc_info=True)
    return Response(status_code=204)


def _run(fn, *args, **kwargs):
    return asyncio.get_running_loop().run_in_executor(None, partial(fn, *args, **kwargs))


@admin_router.get("/api/admin/terminal/events")
async def api_admin_terminal_events(
    level: list[str] = Query(default=[]), event: str | None = None, ticker: str | None = None,
    function: str | None = None, since: str | None = None, until: str | None = None,
    standard: str | None = None, period: str | None = None,
    limit: int = 100, offset: int = 0,
) -> dict[str, Any]:
    return await _run(journal.events, levels=level, event=event, ticker=ticker, function=function,
                      since=since, until=until, limit=limit, offset=offset, standard=standard, period=period)


@admin_router.get("/api/admin/terminal/catalogue")
async def api_admin_terminal_catalogue() -> dict[str, Any]:
    return {"events": journal.catalogue()}


@public_router.get("/api/terminal/screener")
async def api_terminal_screener(form: Literal["NSBU", "MSFO"] = "NSBU",
                               scope: Literal["separate", "consolidated"] = "separate",
                               year: int | None = Query(default=None, ge=2015, le=2100)):
    from server.terminal import service
    return await service.screener(form, scope if form == "MSFO" else "separate", year)


@public_router.get("/api/terminal/issuer/{ticker}/analytics")
async def api_terminal_analytics(ticker: str, form: Literal["NSBU", "MSFO"] = "NSBU",
                                 scope: Literal["separate", "consolidated"] = "separate"):
    from server.terminal import service
    return await service.issuer(ticker.upper(), form, scope)


@public_router.get("/api/terminal/issuer/{ticker}/reconciliation")
async def api_terminal_reconciliation(ticker: str, scope: Literal["separate", "consolidated"] = "separate"):
    from server.terminal import service
    return await service.reconciliation(ticker.upper(), scope)


@admin_router.get("/api/admin/terminal/dashboard")
async def api_terminal_dashboard(days: Literal[7, 30] = 7):
    from server.terminal.dashboard import dashboard
    return await _run(dashboard, days)


@admin_router.get("/api/admin/terminal/coverage")
async def api_terminal_coverage(form: Literal["NSBU", "MSFO"] = "NSBU",
                                scope: Literal["separate", "consolidated"] = "separate"):
    from server.terminal.dashboard import coverage
    return await coverage(form, scope)


@admin_router.get("/api/admin/terminal/export")
async def api_terminal_export(level: list[str] = Query(default=[]), event: str | None = None,
                              ticker: str | None = None, since: str | None = None, until: str | None = None,
                              standard: str | None = None, period: str | None = None):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    def stream():
        yield "\ufeff"
        output = io.StringIO()
        writer = csv.writer(output)
        fields = ["ts", "level_label", "event", "ticker", "standard", "period", "function", "user_id",
                  "duration_ms", "error_id", "message", "source_url"]
        writer.writerow(fields)
        yield output.getvalue()
        output.seek(0); output.truncate(0)
        offset = 0
        # Freeze the upper time boundary so incoming events cannot shift pages.
        end = until or journal.now().isoformat()
        while True:
            page = journal.events(levels=level, event=event, ticker=ticker, since=since, until=end,
                                  standard=standard, period=period, limit=1000, offset=offset)
            for row in page["items"]:
                cells = []
                for field in fields:
                    value = row.get(field)
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                        value = "'" + value
                    cells.append(value)
                writer.writerow(cells)
            yield output.getvalue()
            output.seek(0); output.truncate(0)
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                break
    return StreamingResponse(stream(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="terminal-journal.csv"'})


@admin_router.get("/api/admin/terminal/valuations")
async def api_terminal_valuations(form: Literal["NSBU", "MSFO"] = "NSBU",
                                  scope: Literal["separate", "consolidated"] = "separate"):
    """The screener's model comparison shares FV's calculation and access gate."""
    from server.terminal import service, valuation, configuration
    scope = scope if form == "MSFO" else "separate"
    data = await service.screener(form, scope)
    config = await _run(configuration.parameters)
    rows = []
    for base in data['rows']:
        result = valuation.calculate(base, data['rows'], config['values'])
        rows.append({key: result[key] for key in ('ticker', 'period', 'standard', 'scope')} |
                    {'price_to_value_pct': result['summary']['price_to_value_pct'],
                     'method_count': result['summary']['method_count']})
    return {'ok': True, 'rows': rows, 'configuration': config, 'public_enabled': False}


@admin_router.get("/api/admin/terminal/valuation/{ticker}")
async def api_terminal_valuation(ticker: str, form: Literal["NSBU", "MSFO"] = "NSBU",
                                 scope: Literal["separate", "consolidated"] = "separate",
                                 key_rate: float | None = Query(default=None, ge=0, le=100),
                                 default_spread: float | None = Query(default=None, ge=0, le=100),
                                 equity_premium: float | None = Query(default=None, ge=0, le=100),
                                 growth: float | None = Query(default=None, ge=-99, le=100)):
    from fastapi import HTTPException
    from server.terminal import service, valuation, configuration
    data=await service.screener(form, scope if form == "MSFO" else "separate")
    base=next((r for r in data["rows"] if r["ticker"]==ticker.upper()),None)
    if base is None:raise HTTPException(404,"Issuer unavailable")
    config=await _run(configuration.parameters)
    overrides={k:v for k,v in dict(key_rate=key_rate,default_spread=default_spread,equity_premium=equity_premium,growth=growth).items() if v is not None}
    return {**valuation.calculate(base,data["rows"],{**config["values"],**overrides}), "configuration":config, "scenario":bool(overrides)}


@admin_router.get("/api/admin/terminal/templates")
async def api_terminal_templates():
    def catalogue():
        from server.terminal.service import universe
        from financial_analysis.sector_templates import resolve_template, CALCULATION_VERSION, OKED_MAP
        from financial_analysis.sector_calculations import METHODS, FINANCIAL_METHODS, FINANCIAL_RATIOS
        from financial_analysis.metric_names import named
        from admin_control.rules import active
        from server.terminal.configuration import parameters
        import catalogue.filings as filings
        companies=universe()
        assignments=[{"ticker":c["ticker"],"kind":c["kind"],**resolve_template(filings.get_company_index(c["ticker"]) or {}, {"fund":"investment_fund","industry":"non_financial"}.get(c["kind"],c["kind"]))} for c in companies]
        return {"ok":True,"version":CALCULATION_VERSION,"assignments":assignments,"oked":OKED_MAP,
                "formulas":[{"code":code,**named(code),"numerators":method[0],"denominators":method[1],"unit":method[2]} for code,method in {**METHODS,**FINANCIAL_METHODS}.items()],
                "financial_sets":FINANCIAL_RATIOS,"active_rules":active(),"valuation":parameters()}
    return await _run(catalogue)
