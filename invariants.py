"""invariants.py — properties that must hold on live data, checked daily.

ТЗ v1.2 §11.5, fourth level of testing. Unit tests prove the formulas are right
on data we invented; these assert the properties still hold on the data that
actually arrived this morning. An empty report is the only normal outcome.

Each check returns findings, never raises: a check that dies takes the whole
report with it, and the report is what tells you the pipeline broke.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable, Iterable, Sequence

import formulas
import fundamentals
import heatmap as heatmap_mod

logger = logging.getLogger(__name__)

SEVERITY_BLOCKING = "blocking"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


def _finding(code: str, severity: str, message: str, **ctx: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message,
            **{k: v for k, v in ctx.items() if v is not None}}


# ---------------------------------------------------------------------------
# Price / metric invariants
# ---------------------------------------------------------------------------

def check_absolute_metrics_period_independent(points: Sequence[dict[str, Any]],
                                              ticker: str) -> list[dict[str, Any]]:
    """The main invariant: the period button may not move an absolute metric."""
    if len(points) < 3:
        return []
    reference = None
    for months in (1, 3, 6, 12, 36, 60):
        block = formulas.company_metrics(points, months=months)["absolute"]
        if reference is None:
            reference = block
        elif block != reference:
            differing = [k for k in block if block[k] != reference[k]]
            return [_finding("MET-01", SEVERITY_BLOCKING,
                             "абсолютные метрики изменились при смене периода",
                             ticker=ticker, metrics=differing, months=months)]
    return []


def check_ma_window(points: Sequence[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    """MA20 spans 28 calendar days ±20 % (ТЗ §11.5)."""
    pts = formulas.normalize_points(points)
    if len(pts) < 20:
        return []
    cfg = formulas.thresholds()["moving_average"]
    target = float(cfg["ma20_calendar_days"])
    series = formulas.moving_average(pts, int(target))
    covered = [i for i, v in enumerate(series) if v is not None]
    if not covered:
        return []
    i = covered[-1]
    start = i
    while start > 0 and (pts[i]["d"] - pts[start - 1]["d"]).days <= target - 1:
        start -= 1
    span = (pts[i]["d"] - pts[start]["d"]).days
    if span > target * 1.2:
        return [_finding("MET-02", SEVERITY_BLOCKING,
                         "окно MA20 шире 28 календарных дней", ticker=ticker,
                         span_days=span, expected=target)]
    return []


def check_vwap_method(points: Sequence[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    """VWAP must equal turnover/volume, never a close-weighted approximation."""
    pts = formulas.normalize_points(points)
    got = formulas.vwap(pts)
    if got["value"] is None:
        return []
    volume = sum(p["volume"] for p in pts if p["volume"] > 0)
    turnover = sum(p["turnover"] for p in pts if p["volume"] > 0 and p["turnover"] is not None)
    if volume <= 0:
        return []
    expected = turnover / volume
    if abs(got["value"] - expected) > max(1e-6, abs(expected) * 1e-9):
        return [_finding("MET-03", SEVERITY_BLOCKING, "VWAP не равен обороту делённому на объём",
                         ticker=ticker, got=got["value"], expected=expected)]
    return []


# ---------------------------------------------------------------------------
# Multiples invariants
# ---------------------------------------------------------------------------

def check_multiples_agree_across_classes(by_issuer: dict[str, dict[str, Any]]
                                         ) -> list[dict[str, Any]]:
    """ТЗ §8: both classes of one issuer carry the SAME P/E, P/B, ROE, ROA."""
    out: list[dict[str, Any]] = []
    for key, entry in by_issuer.items():
        tickers = entry.get("tickers") or []
        if len(tickers) < 2:
            continue
        multiples = entry.get("multiples") or {}
        for field in ("pe", "pb", "roe", "roa", "net_margin", "debt_to_equity"):
            values = {t: (multiples.get(field) or {}).get("value") for t in tickers}
            distinct = {v for v in values.values() if v is not None}
            if len(distinct) > 1:
                out.append(_finding("MUL-01", SEVERITY_BLOCKING,
                                    f"{field} различается у классов одного эмитента",
                                    issuer=key, values=values))
    return out


def check_multiples_in_range(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    cfg = formulas.thresholds()["multiples"]
    out: list[dict[str, Any]] = []
    for row in rows:
        for field, bounds in (("pe", cfg["pe_range"]), ("pb", cfg["pb_range"])):
            metric = row.get(field) or {}
            value = metric.get("value")
            if value is None:
                continue
            if not (float(bounds[0]) <= value <= float(bounds[1])):
                out.append(_finding("MUL-02", SEVERITY_BLOCKING,
                                    f"{field} опубликован вне допустимого диапазона",
                                    ticker=row.get("ticker"), value=value, allowed=bounds))
        roe = (row.get("roe") or {}).get("value")
        if roe is not None and abs(roe) > float(cfg["roe_abs_max"]):
            out.append(_finding("MUL-03", SEVERITY_BLOCKING, "ROE опубликован за пределами ±100 %",
                                ticker=row.get("ticker"), value=roe))
    return out


def check_invalid_statements_are_suppressed(rows: Iterable[dict[str, Any]]
                                            ) -> list[dict[str, Any]]:
    """A statement line that failed validation must not have produced a multiple.

    Line by line, not row by row: a balance-sheet failure leaves P/E standing,
    and holding the whole row hostage to it took thirteen sound numbers off the
    board. What may never happen is a multiple built FROM the broken line.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        validation = row.get("validation") or {}
        if validation.get("valid", True):
            continue
        # A statement with no per-line detail (an older payload) is still judged
        # whole — the previous rule, kept for anything that predates `findings`.
        findings = validation.get("findings")
        broken = ({f.get("field") for f in findings} if findings
                  else set().union(*fundamentals.MULTIPLE_INPUTS.values()))
        for field in ("pe", "pb"):
            if not broken & set(fundamentals.MULTIPLE_INPUTS[field]):
                continue
            if (row.get(field) or {}).get("value") is not None:
                out.append(_finding("FIN-01", SEVERITY_BLOCKING,
                                    "мультипликатор посчитан по непроверенной отчётности",
                                    ticker=row.get("ticker"), field=field,
                                    reasons=validation.get("reasons")))
    return out


# ---------------------------------------------------------------------------
# Market map invariants
# ---------------------------------------------------------------------------

def check_map(map_payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tile in map_payload.get("tiles") or []:
        if tile["status"] == heatmap_mod.TILE_NO_PRICE:
            out.append(_finding("MKT-03", SEVERITY_BLOCKING,
                                "есть сделки, но нет последней цены",
                                ticker=tile["ticker"], trades=tile.get("trades"),
                                turnover=tile.get("turnover")))
        if tile["status"] != heatmap_mod.TILE_OK and tile["change_pct"] is not None:
            out.append(_finding("MKT-04", SEVERITY_BLOCKING,
                                "плитка без сделок несёт изменение цены",
                                ticker=tile["ticker"], change=tile["change_pct"]))
    for sector in map_payload.get("sectors") or []:
        if sector["change_pct"] is not None and sector["tiles_counted"] == 0:
            out.append(_finding("MKT-12", SEVERITY_BLOCKING,
                                "сектор посчитан без единой плитки со статусом ok",
                                sector=sector["name"]))
        if sector.get("weighting") == "equal_no_turnover":
            out.append(_finding("MKT-12b", SEVERITY_WARNING,
                                "сектор посчитан простым средним: оборот не зарегистрирован",
                                sector=sector["name"]))
    return out


def check_catalog(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = catalog.get("source_counts") or {}
    distinct = {k: v for k, v in counts.items() if v}
    if len(set(distinct.values())) > 1:
        out.append(_finding("CAT-01", SEVERITY_WARNING,
                            "источники каталога расходятся по числу инструментов",
                            counts=distinct))
    for d in catalog.get("discrepancies") or []:
        if d.get("field") == "sector":
            out.append(_finding("CAT-02", SEVERITY_BLOCKING,
                                "сектор бумаги различается между справочниками",
                                ticker=d.get("ticker"), values=d.get("values")))
        elif d.get("field") == "isin":
            out.append(_finding("CAT-03", SEVERITY_BLOCKING,
                                "ISIN различается между справочниками",
                                ticker=d.get("ticker"), values=d.get("values")))
    return out


def check_market_cap(summary: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = (summary.get("excluded") or {})
    bonds = (excluded.get("bonds") or {}).get("instruments") or 0
    out: list[dict[str, Any]] = []
    if bonds:
        out.append(_finding("MKT-09", SEVERITY_WARNING,
                            "у облигаций рассчитана капитализация",
                            instruments=bonds,
                            amount=(excluded.get("bonds") or {}).get("amount")))
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(checks: Sequence[tuple[str, Callable[[], list[dict[str, Any]]]]]
        ) -> dict[str, Any]:
    """Run every check, surviving any that throws."""
    findings: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for name, fn in checks:
        try:
            findings.extend(fn() or [])
        except Exception as exc:  # noqa: BLE001 — a broken check must not hide the rest
            logger.exception("invariant check %s failed", name)
            failed.append({"check": name, "error": str(exc)})
    by_severity: dict[str, int] = {}
    for f in findings:
        by_severity[f["severity"]] = by_severity.get(f["severity"], 0) + 1
    return {
        "checks_run": len(checks),
        "checks_failed": failed,
        "findings": findings,
        "summary": by_severity,
        "ok": not any(f["severity"] == SEVERITY_BLOCKING for f in findings) and not failed,
    }
