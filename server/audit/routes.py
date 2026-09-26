from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import Response
from functools import partial
from typing import Any
import asyncio
import obs
import reports_catalog as catalog_store
import server.audit.jobs as audit_jobs
import server.auth.access as auth_access
import server.http as http
import server.market.valuations as market_valuations


router = APIRouter()


@router.post("/api/audit/run")
async def api_audit_run(payload: dict[str, Any] | None = None,
                        _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Run the auditor (ТЗ §12.5). Scope: all, one group, one rule, one ticker."""
    from audit import run_audit

    payload = payload or {}
    trace = obs.Trace(endpoint="audit/run")
    try:
        ctx = await audit_jobs._audit_context(with_history=int(payload.get("with_history") or 0))
        trace.step("context", instruments=len(ctx.board),
                   published=len(ctx.published_multiples), history=len(ctx.history))
        report = run_audit(
            ctx, trigger=str(payload.get("trigger") or "manual"),
            codes=payload.get("codes"), group=payload.get("group"),
            ticker=payload.get("ticker"), trace_id=trace.trace_id)
        trace.step("audit", decision=report["status"], **report["summary"])
        return http._json_safe(report)
    finally:
        trace.close()


@router.get("/api/audit/runs")
async def api_audit_runs(limit: int = 20, _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    from audit import list_runs
    return http._json_safe({"ok": True, "items": list_runs(max(1, min(limit, 200)))})


@router.get("/api/audit/runs/{run_id}")
async def api_audit_run_detail(run_id: str, _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    from audit import find_findings, get_run

    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return http._json_safe({"ok": True, "run": run, "findings": find_findings(run_id=run_id)})


@router.get("/api/audit/findings")
async def api_audit_findings(severity: str | None = None, group: str | None = None,
                             status: str | None = None, ticker: str | None = None,
                             limit: int = 200,
                             _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    from audit import find_findings
    return http._json_safe({"ok": True, "items": find_findings(
        severity=severity, group=group, status=status, ticker=ticker,
        limit=max(1, min(limit, 2000)))})


@router.patch("/api/audit/findings/{finding_id}")
async def api_audit_update_finding(finding_id: int, payload: dict[str, Any],
                                   _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Move a finding to `accepted` (a known exception) or `confirmed`/`fixed`.

    §12.2: no finding disappears silently — a decision about one is recorded on
    it, with its note, rather than expressed by deleting the row.
    """
    from audit import update_finding

    try:
        row = update_finding(finding_id, status=str(payload.get("status")),
                             note=payload.get("note"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="finding not found")
    return http._json_safe({"ok": True, "finding": row})


@router.get("/api/audit/rules")
async def api_audit_rules(request: Request) -> Response:
    """The rule book, readable without credentials: what is checked and why."""
    from audit import ALL_RULES, GROUPS
    return http._etag_json(request, {
        "ok": True,
        "groups": GROUPS,
        "count": len(ALL_RULES),
        "items": [{"code": r.code, "group": r.group, "title": r.title,
                   "severity": r.severity, "threshold": r.threshold, "note": r.note}
                  for r in ALL_RULES],
    }, max_age=3600)


@router.get("/api/audit/diff")
async def api_audit_diff(from_run: str | None = None, to_run: str | None = None,
                         _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """What changed between two runs (ТЗ v1.3 §12.5).

    Without this a regression reads as one more line in a list nobody finishes.
    Findings are matched by fingerprint, so the answer is in three buckets:
    appeared, resolved, still open.
    """
    from audit import find_findings, list_runs
    from audit.store import fingerprint

    runs = list_runs(50)
    if not to_run:
        to_run = runs[0]["id"] if runs else None
    if not from_run:
        from_run = runs[1]["id"] if len(runs) > 1 else None
    if not to_run or not from_run:
        raise HTTPException(status_code=404, detail="not enough runs to compare")

    def keyed(run_id: str) -> dict[str, dict[str, Any]]:
        # Every row the run touched, resolved ones included: a finding that was
        # fixed between the two runs is exactly what the diff is asked about.
        return {fingerprint(f["rule_code"], f["ticker"], f["metric"]): f
                for f in find_findings(run_id=run_id, limit=5000, include_resolved=True)}

    before, after = keyed(from_run), keyed(to_run)
    appeared = [v for k, v in after.items() if k not in before]
    resolved = [v for k, v in before.items() if k not in after]
    return http._json_safe({
        "ok": True, "from_run": from_run, "to_run": to_run,
        "appeared": appeared, "resolved": resolved,
        "still_open": [v for k, v in after.items() if k in before],
        "summary": {"appeared": len(appeared), "resolved": len(resolved),
                    "regressions": sum(1 for f in appeared if f["severity"] == "blocking")},
    })


@router.get("/api/audit/export")
async def api_audit_export(run_id: str | None = None,
                           _: None = Depends(auth_access._admin_gate)) -> Response:
    """The full report as CSV (ТЗ v1.3 §12.5)."""
    import csv
    import io

    from audit import find_findings, latest_run

    if not run_id:
        run = latest_run()
        run_id = (run or {}).get("id")
    rows = find_findings(run_id=run_id, limit=5000) if run_id else []
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["rule_code", "severity", "ticker", "metric", "expected", "actual",
                     "deviation", "status", "seen_count", "first_seen", "last_seen", "message"])
    for row in rows:
        writer.writerow([row.get(k) for k in (
            "rule_code", "severity", "ticker", "metric", "expected", "actual", "deviation",
            "status", "seen_count", "first_seen", "last_seen", "message")])
    # BOM so Excel opens the Cyrillic messages correctly rather than as mojibake.
    body = "﻿" + buffer.getvalue()
    return Response(body, media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="audit-{run_id or "empty"}.csv"'})


@router.get("/api/audit/badge/{ticker}")
async def api_audit_badge(ticker: str) -> dict[str, Any]:
    """Can this security's numbers be trusted right now? (ТЗ §12.5/§12.6)

    Public: this is the fact the reader needs. They do not need rule codes.
    """
    from audit import ticker_badge
    return http._json_safe({"ok": True, **ticker_badge(ticker)})


@router.get("/api/admin/overview")
async def api_admin_overview(history: int = 14, decide: int = 8,
                             _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """One read for the admin panel's «Обзор» screen.

    Deliberately one endpoint rather than six: the screen is a single answer to
    a single question, and six round trips would let it render four true blocks
    beside two that are still loading — which reads as an outage that is not
    happening. See ``admin_overview`` for what each block is measured from, and
    in particular why the freshness block reports a last write and not a run.
    """
    import admin_overview

    loop = asyncio.get_running_loop()
    return http._json_safe(await loop.run_in_executor(
        None, partial(admin_overview.build_overview,
                      history=max(1, min(history, 60)), decide=max(1, min(decide, 50)))))


@router.get("/api/admin/reports")
async def api_admin_reports(_: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Screen «Отчёты» — what the pipeline took in, record by record.

    Deliberately the FIRST screen of the console. Half the defects found in the
    multiples so far were not errors of formula but of which record reached it,
    and while a record's status is invisible every fix to the calculation is
    made blind.
    """
    import admin_data
    import reports_catalog

    def _stored() -> tuple[list[dict[str, Any]], int]:
        # The RAW table, not the read path's per-ticker pick: the records the
        # read path drops are exactly the ones nobody has been able to see.
        conn = reports_catalog.get_catalog_conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT ticker, form, year, quarter, revenue, net_income, "
                "total_assets, total_equity, total_liabilities, org_type, "
                "balance_period, report_id, updated_at "
                "FROM catalog_financials")]
        finally:
            conn.close()
        return rows, reports_catalog._latest_complete_fiscal_year()

    loop = asyncio.get_running_loop()
    (stored, last_fy), inputs = await asyncio.gather(
        loop.run_in_executor(None, _stored),
        market_valuations._market_inputs(),
    )
    # WHICH period each ticker's published multiple was computed from — so a
    # stored row can say whether it is the one that counted. Taken from the
    # inputs the market screen itself uses, never re-selected here.
    used: dict[str, tuple[int, int] | None] = {}
    for ticker, fin in (inputs["financials"] or {}).items():
        if not fin or fin.get("year") is None:
            continue
        used[str(ticker).upper()] = (int(fin["year"]), int(fin.get("quarter") or 0))
    return http._json_safe({"ok": True, **admin_data.report_intake(stored, last_fy, used)})


@router.get("/api/admin/rules")
async def api_admin_rules(_: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Screen «Правила» — the parameters, and the line the panel must not cross."""
    import admin_data

    return http._json_safe({"ok": True, **admin_data.rule_book()})


@router.get("/api/admin/source")
async def api_admin_source(_: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Screen «Источник» — who was due to file, who did, and who has gone quiet.

    Being late is a fact about the ISSUER, not about our collector, and the
    screen states it as one. The same list is the basis of a public disclosure
    index: an issuer that has filed nothing since 2019 is worth publishing.
    """
    import admin_data
    import openinfo_probe

    loop = asyncio.get_running_loop()
    # Two halves of one question. The calendar answers "did the issuer file";
    # the probe answers "could we have read it if they had". Run together so a
    # screen never blames one for the other.
    financials, probe = await asyncio.gather(
        loop.run_in_executor(None, catalog_store.get_all_financials),
        loop.run_in_executor(None, openinfo_probe.run_probe),
    )
    latest = {str(t).upper(): (int(r["year"]), int(r.get("quarter") or 0))
              for t, r in (financials or {}).items()
              if isinstance(r, dict) and r.get("year") is not None}
    steps = [r for r in (probe.get("results") or []) if r.get("name") != "egress_ip"]
    return http._json_safe({
        "ok": True,
        "calendar": admin_data.disclosure_calendar(latest),
        "probe": {
            "verdict": probe.get("verdict"),
            "reachable": probe.get("reachable"),
            "failed": probe.get("failed"),
            # Response time is per endpoint class and they differ by an order of
            # magnitude; one averaged number would hide the slow one.
            "steps": [{"name": s.get("name"), "ok": s.get("ok"),
                       "elapsed_ms": s.get("elapsed_ms"),
                       "status_code": s.get("status_code"),
                       "error": s.get("error")} for s in steps],
        },
    })


@router.get("/api/admin/issuer/{ticker}")
async def api_admin_issuer(ticker: str,
                           _: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """Screen «Эмитент» — one issuer's whole calculation, line by line.

    Every block is the OUTPUT of the published path, not a re-derivation: the
    same TTM assembly, the same balance snapshot, the same ``issuer_multiples``
    the board calls. A second implementation would eventually disagree with the
    first and the panel would be reporting its own bug.
    """
    import admin_data

    ticker = ticker.upper()
    inputs = await market_valuations._market_inputs()
    payload = market_valuations._multiples_payload(inputs)
    row = next((r for r in payload["items"] if r["ticker"] == ticker), None)
    if not row:
        raise HTTPException(status_code=404, detail="issuer not found")
    key = row["issuer"]
    tickers = row["issuer_classes"]
    board_by_ticker = {str(r.get("ticker") or "").upper(): r for r in inputs["board"]}
    classes = []
    for one in tickers:
        meta = (inputs["securities"] or {}).get(one) or {}
        board_row = board_by_ticker.get(one) or {}
        classes.append({
            "ticker": one, **meta,
            "market_cap": (board_row.get("market_cap")
                           if str(board_row.get("last_trade_date") or "").strip() else None),
            "shares_outstanding": (board_row.get("shares_outstanding")
                                   or meta.get("shares_outstanding")),
        })
    fin = next((inputs["financials"].get(t) for t in tickers if inputs["financials"].get(t)), None)
    rat = next((inputs["ratios"].get(t) for t in tickers if inputs["ratios"].get(t)), None)
    ledger = admin_data.issuer_ledger(key, classes, fin, rat)
    # What the SHOP WINDOW currently publishes for the same issuer, so the two
    # sit side by side. They come from the same call, so a difference here is a
    # bug in this screen and not in the market — which is itself worth seeing.
    ledger["published"] = {k: row.get(k) for k in
                           ("pe", "pb", "ps", "roe", "roa", "net_margin")}
    return http._json_safe({"ok": True, "ticker": ticker, **ledger})


@router.get("/api/admin/invariants")
async def api_admin_invariants(_: None = Depends(auth_access._admin_gate)) -> dict[str, Any]:
    """The same check the scheduler runs, on demand. Empty is the good outcome."""
    return http._json_safe(await audit_jobs._run_invariants())


@router.get("/api/admin/trace/{trace_id}")
async def api_admin_trace(trace_id: str, _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    """Replay one number's chain of derivation (ТЗ §12)."""
    record = obs.get_trace(trace_id)
    if not record:
        raise HTTPException(status_code=404, detail="trace not found or expired")
    return http._json_safe(record)


@router.get("/api/admin/traces")
async def api_admin_traces(limit: int = 50,
                           _: None = Depends(auth_access._require_admin)) -> dict[str, Any]:
    return http._json_safe({"ok": True, "items": obs.recent_traces(max(1, min(limit, 200)))})
