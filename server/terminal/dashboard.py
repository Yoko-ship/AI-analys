"""PM journal aggregates. SQL aggregates cover the entire window, not a page."""
from datetime import timedelta
from server.terminal import journal


def dashboard(days=7, at=None):
    at = at or journal.now()
    journal.flush()
    since = journal.stamp(at - timedelta(days=days))
    day, previous, hour = [journal.stamp(at - delta) for delta in (timedelta(days=1), timedelta(days=2), timedelta(hours=1))]
    until = journal.stamp(at)
    with journal.connection() as c:
        def counts(start, end):
            return {r["event"]: r["n"] for r in c.execute(
                "SELECT event, COUNT(*) AS n FROM terminal_events WHERE ts >= ? AND ts <= ? AND internal = 0 GROUP BY event",
                (start, end)).fetchall()}
        total, today, yesterday, hourly = counts(since, until), counts(day, until), counts(previous, day), counts(hour, until)
        def rank(column):
            return [{"name": r[column], "count": r["n"]} for r in c.execute(
                f"SELECT {column}, COUNT(*) AS n FROM terminal_events WHERE ts >= ? AND ts <= ? "
                f"AND internal = 0 AND event = 'cmd_run' AND {column} IS NOT NULL "
                f"GROUP BY {column} ORDER BY n DESC, {column} LIMIT 20", (since, until)).fetchall()]
        commands = total.get("cmd_run", 0) + total.get("cmd_unknown", 0)
        share = lambda n, d: n / d * 100 if d else None
        summary = {"quarantine": today.get("value_quarantine", 0), "verdict_conflicts": today.get("verdict_conflict", 0),
                   "ai_published": today.get("ai_published", 0),
                   "ai_published_change": today.get("ai_published", 0) - yesterday.get("ai_published", 0),
                   "hour_error_pct": share(hourly.get("screen_error", 0), hourly.get("cmd_run", 0)),
                   "slow_pct": share(today.get("screen_slow", 0), today.get("cmd_run", 0)),
                   "openings": today.get("cmd_run", 0)}
        return {"ok": True, "days": days, "as_of": until, "summary": summary,
                "usage": {"commands": commands, "unknown": total.get("cmd_unknown", 0),
                          "unknown_pct": share(total.get("cmd_unknown", 0), commands),
                          "functions": rank("function"), "tickers": rank("ticker")}}


async def coverage(form="NSBU", scope="separate"):
    """Actual published coverage, including known gaps before journal adoption."""
    import asyncio
    from server.terminal.service import universe
    from server.company.financials import financial_series
    import catalogue.filings as filings
    companies = await asyncio.to_thread(universe)
    now = journal.now()
    periods = [str(y) for y in range(2020, now.year)] + [f"{y}Q{q}" for y in range(2022, now.year + 1)
               for q in range(1, 5) if (y, q * 3) < (now.year, now.month)]
    rows = []
    sem = asyncio.Semaphore(4)
    async def load(company):
        async with sem:
            data = await asyncio.gather(*(financial_series(company["ticker"], freq, form, scope if form == "MSFO" else None)
                                         for freq in ("annual", "quarterly")), return_exceptions=True)
        try:
            reports = await asyncio.to_thread(filings.get_company_reports, company["ticker"])
            registered = {str(r["year"]) + (f"Q{r['quarter']}" if r.get("quarter") else "") for r in reports or []
                          if r.get("year") and r.get("report_form") == form and (r.get("excel_url") or r.get("excel_url_form1") or r.get("pdf_url"))}
        except Exception:
            registered = None
        cells = {}
        for p in periods:
            source = data[1 if "Q" in p else 0]
            if isinstance(source, Exception):
                cells[p] = "unavailable"
                continue
            gaps = [g.get("code") for g in source.get("data_gaps", []) if g.get("period") == p]
            has = any((e.get("values") or {}).get(p) is not None for e in source.get("series", {}).values())
            comparative = "FROM_COMPARATIVE" in gaps or "comparative" in str((source.get("period_sources") or {}).get(p, "")).lower()
            if has:
                cells[p] = "backfill" if comparative else "loaded" if not gaps else "gap"
            else:
                cells[p] = "gap" if gaps or registered is not None and p in registered else "unpublished" if registered is not None else "unavailable"
        return {"ticker": company["ticker"], "name": company["name"], "cells": cells}
    rows = await asyncio.gather(*(load(c) for c in companies))
    annual = [status for row in rows for p, status in row["cells"].items() if "Q" not in p and status != "unpublished"]
    return {"ok": True, "periods": periods, "rows": rows, "standard": form, "scope": scope,
            "annual_expected": len(annual), "annual_coverage_pct": 100 * sum(s in {"loaded", "backfill"} for s in annual) / len(annual) if annual else None}
