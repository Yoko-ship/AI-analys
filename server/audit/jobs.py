from __future__ import annotations

from company_catalog import COMPANY_SECTORS
from typing import Any
import asyncio
import bonds
import formulas
import fundamentals
import heatmap
import instruments
import invariants
import provenance
import server.http as http
import server.market.history as market_history
import server.market.valuations as market_valuations
import server.settings as settings
import threading
import time


async def _audit_context(with_history: int = 0):
    """Assemble everything the auditor looks at (ТЗ v1.3 §12).

    Raw sources AND what the API currently publishes — the auditor's whole
    method is to recompute the first and compare against the second.
    """
    from audit.checks import AuditContext

    inputs = await market_valuations._market_inputs()
    multiples = market_valuations._multiples_payload(inputs)
    map_payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
    catalog = instruments.build_catalog(
        securities=inputs["securities"], board=inputs["board"], listings=inputs["listings"],
        financials=inputs["financials"], ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
    cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
    board = inputs["board"]
    traded = [r for r in board if (formulas.to_number(r.get("trade_count")) or 0) > 0
              or (formulas.to_number(r.get("volume")) or 0) > 0]
    up = down = flat = 0
    for row in traded:
        change = heatmap.day_change(formulas.to_number(row.get("last_price")),
                                    formulas.to_number(row.get("close_price")))
        if change is None:
            continue
        up += change > 0.05
        down += change < -0.05
        flat += -0.05 <= change <= 0.05
    summary = {"instruments": len(board), "traded_today": len(traded), "up": up, "down": down,
               "flat": flat, "market_cap": cap,
               "turnover_today": sum((formulas.to_number(r.get("volume")) or 0) for r in traded),
               "trades_today": sum((formulas.to_number(r.get("trade_count")) or 0) for r in traded)}

    # XSC-03 needs the same security's absolute block under every period button.
    # History is expensive, so it is sampled unless explicitly asked for.
    history: dict[str, list] = {}
    metrics_by_period: dict[str, dict[int, Any]] = {}
    if with_history:
        active = [i for i in catalog["items"] if i["is_active"] and i["isin"]][:int(with_history)]
        for item in active:
            try:
                data = await market_history._full_history(item["isin"])
            except Exception:  # noqa: BLE001 — one unreachable series is a finding, not a crash
                continue
            points = data.get("points") or []
            history[item["ticker"]] = points
            metrics_by_period[item["ticker"]] = {
                months: formulas.company_metrics(points, months=months)["absolute"]
                for months in (1, 3, 6, 12, 36, 60)
            }

    references, coupons = provenance.bond_references(), provenance.bond_coupons()
    bond_board = bonds.build_bond_board(board, inputs["securities"], references, coupons)
    catalog_reports = provenance.summary()
    source_reports = [provenance.report(r["id"]) or r
                      for r in provenance.queue(200)]

    return AuditContext(
        board=board, securities=inputs["securities"], financials=inputs["financials"],
        ratios=inputs["ratios"], listings=inputs["listings"], stats=inputs["stats"],
        history=history, published_multiples=multiples["items"], published_map=map_payload,
        published_summary=summary, published_catalog=catalog,
        published_metrics_by_period=metrics_by_period,
        published_ma_windows=formulas.company_metrics([], months=12)["ma_windows"],
        published_bonds=bond_board["items"],
        bond_references=references,
        bond_coupons=coupons,
        published_catalog_reports=catalog_reports,
        source_reports=source_reports,
        parse_queue=provenance.queue(1000),
    )


_audit_lock = threading.Lock()


_audit_last_started = 0.0


_AUDIT_MIN_INTERVAL = 120.0


def _schedule_audit(trigger: str) -> bool:
    """Run the auditor after a data load, in the background (ТЗ v1.3 §12.7).

    The check is worth having precisely because data changes without anyone
    looking, so it fires on the load rather than on a person remembering. It
    never blocks the ingest that triggered it and never raises into it: a failed
    audit is a failed audit, not a failed collection.
    """
    global _audit_last_started
    if not settings.FEATURE_FLAGS.get("audit_v1", True):
        return False
    now = time.time()
    with _audit_lock:
        if now - _audit_last_started < _AUDIT_MIN_INTERVAL:
            return False
        _audit_last_started = now

    async def _go() -> None:
        from audit import run_audit
        try:
            ctx = await _audit_context()
            report = run_audit(ctx, trigger=trigger)
            http.logger.info("audit after %s: %s, blocking=%d", trigger, report["status"],
                        report["summary"]["blocking"])
        except Exception:  # noqa: BLE001 — never propagate into the ingest path
            http.logger.exception("scheduled audit after %s failed", trigger)
        try:
            # The invariant report is the fourth level of testing and belongs on
            # the same trigger: both answer "is what we just loaded sane?", and
            # an empty report is the only normal outcome for either.
            report = await _run_invariants()
            level = http.logger.warning if not report["ok"] else http.logger.info
            level("invariants after %s: %d finding(s), ok=%s", trigger,
                  len(report["findings"]), report["ok"])
        except Exception:  # noqa: BLE001
            http.logger.exception("scheduled invariants after %s failed", trigger)

    try:
        asyncio.get_running_loop().create_task(_go())
        return True
    except RuntimeError:
        return False


async def _run_invariants() -> dict[str, Any]:
    """The fourth level of testing (ТЗ §11.5), on this morning's data."""
    inputs = await market_valuations._market_inputs()
    payload = market_valuations._multiples_payload(inputs)
    map_payload = heatmap.build_heatmap(inputs["board"], inputs["securities"],
                                        inputs["stats"], inputs["trade_date"])
    catalog = instruments.build_catalog(
        securities=inputs["securities"], board=inputs["board"],
        listings=inputs["listings"], financials=inputs["financials"],
        ratios=inputs["ratios"], sectors=COMPANY_SECTORS)
    cap = fundamentals.market_capitalisation(inputs["board"], inputs["securities"])
    return invariants.run([
        ("multiples_agree", lambda: invariants.check_multiples_agree_across_classes(
            payload["by_issuer"])),
        ("multiples_in_range", lambda: invariants.check_multiples_in_range(payload["items"])),
        ("statements_suppressed", lambda: invariants.check_invalid_statements_are_suppressed(
            payload["items"])),
        ("market_map", lambda: invariants.check_map(map_payload)),
        ("catalog", lambda: invariants.check_catalog(catalog)),
        ("market_cap", lambda: invariants.check_market_cap(cap)),
    ])
